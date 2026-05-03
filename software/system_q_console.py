import copy
import math
import os
import sys
import time
import atexit
import logging
import subprocess
from dataclasses import dataclass, field, fields
from pathlib import Path
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import numpy as np
import sounddevice as sd
import soundfile as sf
from pol_visualizer import SpaceMouseController

_log_path = Path(__file__).resolve().parent / "console_debug.log"
logging.basicConfig(
    filename=str(_log_path),
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
_log = logging.getLogger("console")

# Minimum twist magnitude required to trigger a DISCRETE step (channel page,
# send-slot select, EQ band cycle). Analog tweaks (gain, level, frequency) keep
# their fine sensitivity. Raised from the controller's 0.12 deadzone so that
# incidental grip-twist no longer drifts you onto a different channel mid-edit.
DISCRETE_TWIST_MIN = 0.35

# Bumped when nav / SpaceMouse semantics change — window title + stdout so you
# can prove the running process loaded this file (close old console windows).
SYSTEM_Q_BUILD_ID = "coerce-stage-faders-cap-20260430"

# Fields not copied when mirroring mix settings onto strip-link targets (identity, playback, meters).
_STRIP_LINK_COPY_SKIP = frozenset({
    "name",
    "path",
    "audio",
    "wave_preview",
    "position",
    "level",
    "comp_gr_db",
    "comp_env",
    "gate_env",
    "gate_gain_smooth",
    "band_levels",
    "band_noise_floor",
})


def hsv_to_hex(h: float, s: float, v: float) -> str:
    h = max(0.0, min(1.0, h))
    s = max(0.0, min(1.0, s))
    v = max(0.0, min(1.0, v))
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    i %= 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return rgb_to_hex(
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def eq_spread_brightness_rgb(width_oct: float) -> str:
    """Wider symmetric Bell spread → nearer white text (narrow → EQ purple-grey)."""

    w = float(np.clip(width_oct, 0.15, 6.05))
    t = (w - 0.18) / 5.5
    t = float(np.clip(t, 0.0, 1.0))
    dim = (98, 86, 128)
    bright = (250, 252, 253)
    return lerp_color(dim, bright, t)


TONE_HEX_TRN = "#36e0dc"
TONE_HEX_CLR = "#ff8f3a"
TONE_HEX_XCT = "#c06cff"

# Polar parameter rings (harm / gate / comp / EQ overlays) — maximum-gamut red on dark UI.
POL_NEON_RED = "#ff0019"
POL_NEON_RED_HI = "#ff3355"
POL_NEON_RED_HOT = "#ff99aa"


def polar_edit_overlay_hex(
    layer_mix: float = 0.5,
    punch: float = 0.0,
    *,
    muted: bool = False,
    highlight: bool = False,
) -> str:
    """Red-only strokes for editable / affected regions (spectrum uses ``freq_rainbow_hue_hz`` below)."""

    m = float(np.clip(layer_mix, 0.0, 1.0))
    p = float(np.clip(punch, 0.0, 1.0))
    if muted:
        return hsv_to_hex(0.0, 0.38, float(np.clip(0.42 + m * 0.14 + p * 0.08, 0.40, 0.62)))
    if highlight:
        return POL_NEON_RED_HOT
    sat = float(np.clip(0.88 + m * 0.10, 0.82, 0.98))
    v = float(np.clip(0.72 + m * 0.22 + p * 0.10, 0.72, 1.0))
    return hsv_to_hex(0.0, sat, v)


def polar_dsp_ring_hex(layer_mix: float = 0.5, punch: float = 0.0, *, muted: bool = False) -> str:
    """Deprecated alias for ``polar_edit_overlay_hex``."""

    return polar_edit_overlay_hex(layer_mix, punch, muted=muted)


SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
POL_BANDS = 36
ROOT_DIR = Path(__file__).resolve().parent
# LEWITT x EYEHALFSHUT remix pack (`tracks/lewitt_eyes`, 48 kHz stems).
STEMS_DIR = ROOT_DIR / "tracks" / "lewitt_eyes"
CHANNEL_LAYOUT = [
    ("Kick", "01_kick.wav"),
    ("Pad", "02_pad.wav"),
    ("Vocal Clean", "03_vocal_clean.wav"),
    ("V Syn Chorus", "04_vocal_syn_ch.wav"),
    ("V Syn Verse", "05_vocal_syn_vs.wav"),
    ("Vocals Gp", "06_vocals_grp.wav"),
    ("Vocals Synth", "07_vocals_syn.wav"),
    ("Dirty Bass", "08_dirty_bass.wav"),
    ("Clap Snap", "09_clap_snap.wav"),
    ("Drums Gp", "10_drums_grp.wav"),
    ("Arp", "11_arp.wav"),
    ("Bass Syn", "12_bass_syn.wav"),
    ("B Oct", "13_bass_oct.wav"),
]
POL_LOW_HZ = 20.0
POL_HIGH_HZ = 22000.0
LOG_LOW = math.log10(POL_LOW_HZ)
LOG_HIGH = math.log10(POL_HIGH_HZ)

# Log-frequency band centers aligned with FFT analysis (`AudioEngine._pol_edges`).
_POL_ANALYSIS_EDGES = np.logspace(LOG_LOW, LOG_HIGH, POL_BANDS + 1)
POL_BAND_CENTER_HZ = np.sqrt(_POL_ANALYSIS_EDGES[:-1] * _POL_ANALYSIS_EDGES[1:])

# Radial **level / threshold** axis on CMP/GTE polars (independent of log-freq spectrum rings).
# Outer surrogate ≈ −∞ (“off”); inner end = **+12 dB**. Threshold ∈ [POL_LEVEL_DB_AXIS_OUTER … +12] maps to radius.
POL_LEVEL_DB_AXIS_OUTER = -72.0
POL_LEVEL_DB_AXIS_INNER = 12.0
# Inner-positive cluster (+12 at bullseye) plus negative landmarks toward the outer surrogate.
POL_LEVEL_GUIDE_TICKS_DB: tuple[float, ...] = (-48.0, -36.0, -24.0, -12.0, 0.0, 4.0, 8.0, 12.0)
# Guide rings land on evenly spaced mixes between pole outer … **tiny** inner (+12 hoop).
POL_LEVEL_GUIDE_INNER_SCALE = 0.28


def polar_level_db_to_mix(db: float) -> float:
    """Mix 0 = outer ellipse (axis outer dB); mix 1 = inner bullseye (+12 dB)."""

    lo = float(POL_LEVEL_DB_AXIS_OUTER)
    hi = float(POL_LEVEL_DB_AXIS_INNER)
    d = float(np.clip(db, lo, hi))
    if hi <= lo:
        return 0.0
    return (d - lo) / (hi - lo)


def polar_level_guide_label(db: float) -> str:
    if abs(db) < 0.05:
        return "0"
    if db > 0:
        return f"+{db:.0f}"
    return f"{db:.0f}"


def freq_rainbow_hue_hz(freq_hz: float) -> float:
    """Map log-frequency in [POL_LOW_HZ, POL_HIGH_HZ] to hue: cool blue (low) … hot red (high)."""

    lf = math.log10(float(np.clip(freq_hz, POL_LOW_HZ, POL_HIGH_HZ)))
    pos = (lf - LOG_LOW) / max(1e-9, LOG_HIGH - LOG_LOW)
    pos = float(np.clip(pos, 0.0, 1.0))
    hue_blue = 240.0 / 360.0
    hue_red = 0.0
    return hue_blue * (1.0 - pos) + hue_red * pos


def hz_log_lerp_hz(a_hz: float, b_hz: float, t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    a_hz = float(np.clip(a_hz, POL_LOW_HZ, POL_HIGH_HZ))
    b_hz = float(np.clip(b_hz, POL_LOW_HZ, POL_HIGH_HZ))
    la = math.log(a_hz)
    lb = math.log(b_hz)
    return float(math.exp(la + t * (lb - la)))


def eq_rainbow_color(gain_db: float, center_hz: float, *, insert_active: bool = True) -> str:
    """Rainbow keyed by EQ center frequency; gain sets saturation/value (muted when bypassed)."""

    h = freq_rainbow_hue_hz(center_hz)
    if not insert_active:
        return hsv_to_hex(h, 0.14, 0.32)
    g = float(np.clip(gain_db, -24.0, 24.0))
    mag = min(1.0, abs(g) / 18.0)
    sat = 0.42 + 0.50 * mag
    val = 0.42 + 0.52 * mag
    return hsv_to_hex(h, float(np.clip(sat, 0.18, 0.97)), float(np.clip(val, 0.24, 0.97)))


def ensure_demo_stems() -> None:
    missing = [filename for _, filename in CHANNEL_LAYOUT if not (STEMS_DIR / filename).exists()]
    if not missing:
        return

    if STEMS_DIR.name == "lewitt_eyes":
        raise FileNotFoundError(
            f"Missing multitrack WAVs in {STEMS_DIR}: {', '.join(missing)}. "
            "Copy/resample the LEWITT x EYESHALFSHUT 48 kHz stems into this folder "
            "(see CHANNEL_LAYOUT filenames) or regenerate your local import batch."
        )

    _log.info("Generating missing demo stems: %s", ", ".join(missing))
    try:
        from generate_band_stems import main as generate_band_stems

        generate_band_stems()
    except Exception as exc:
        raise FileNotFoundError(
            f"Missing demo stems in {STEMS_DIR}. Run: py -3 software/generate_band_stems.py"
        ) from exc

    still_missing = [filename for _, filename in CHANNEL_LAYOUT if not (STEMS_DIR / filename).exists()]
    if still_missing:
        raise FileNotFoundError(
            f"Missing demo stems after generation: {', '.join(still_missing)}. "
            "Run: py -3 software/generate_band_stems.py"
        )


@dataclass
class ChannelState:
    name: str
    path: Path
    audio: np.ndarray = field(default_factory=lambda: np.zeros((1, 2), dtype=np.float32))
    # Peak envelope across the whole clip / max amplitude 1 — built once at load so strip
    # waveforms don't rescan massive WAVs ~16× per second during playback.
    wave_preview: np.ndarray = field(default_factory=lambda: np.zeros((1,), dtype=np.float32))
    position: int = 0
    gain: float = 1.0
    send_slot: int = 1
    send_level: float = 0.0
    send_muted: bool = False
    send_prev_level: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    record_armed: bool = False
    pre_enabled: bool = False
    phantom: bool = False
    phase: bool = False
    tube: bool = False
    # Per-stage tube path (TBE row); independent of insert *_enabled.
    harm_tube: bool = False
    gate_tube: bool = False
    comp_tube: bool = False
    eq_tube: bool = False
    lpf_enabled: bool = False
    hpf_enabled: bool = False
    lpf_hz: float = POL_LOW_HZ
    hpf_hz: float = POL_HIGH_HZ
    harmonics_enabled: bool = False
    harmonics: np.ndarray = field(default_factory=lambda: np.zeros(5, dtype=np.float32))
    harmonic_makeup: float = 1.0
    comp_enabled: bool = False
    limit_enabled: bool = False
    gate_enabled: bool = False
    comp_threshold_db: float = -18.0
    comp_ratio: float = 4.0
    comp_attack_ms: float = 8.0
    comp_release_ms: float = 120.0
    comp_makeup: float = 1.0
    comp_center_hz: float = 3000.0
    comp_width_oct: float = 4.0
    comp_band_enabled: bool = False
    limit_center_hz: float = 3000.0
    limit_width_oct: float = 4.0
    limit_band_enabled: bool = False
    gate_center_hz: float = 3000.0
    gate_width_oct: float = 4.0
    gate_band_enabled: bool = False
    # Gate dynamics (independent from compressor; order: gate -> comp in DSP).
    gate_threshold_db: float = -45.0
    gate_ratio: float = 8.0
    gate_attack_ms: float = 3.0
    gate_release_ms: float = 140.0
    gate_makeup: float = 1.0
    gate_env: float = 0.0
    gate_gain_smooth: float = 1.0
    gate_gr_db: float = 0.0
    eq_enabled: bool = False
    eq_freq: float = 2200.0
    eq_gain_db: float = 0.0
    eq_width: float = 1.4
    eq_type: str = "BELL"
    eq_band_enabled: bool = False
    eq_band_count: int = 1
    eq_bands: list[dict] = field(default_factory=lambda: [
        {"enabled": False, "freq": 2200.0, "gain_db": 0.0, "width": 1.4, "type": "BELL", "band_enabled": False}
        for _ in range(8)
    ])
    # Per-cell bypass in the EQ column (label -> True = that parameter ignored).
    eq_param_bypass: dict[str, bool] = field(default_factory=dict)
    gate_param_bypass: dict[str, bool] = field(default_factory=dict)
    comp_param_bypass: dict[str, bool] = field(default_factory=dict)
    harm_param_bypass: dict[str, bool] = field(default_factory=dict)
    tone_param_bypass: dict[str, bool] = field(default_factory=dict)
    # Mirrors UI band index while multiband EQ is edited (DSP + polar preview bypass).
    eq_ui_band: int = 0
    tone_enabled: bool = False
    transient_enabled: bool = True
    exciter_enabled: bool = True
    saturation_enabled: bool = True
    trn_freq: float = 136.0
    trn_width: float = 1.12
    trn_band_enabled: bool = False
    trn_attack: float = 0.0
    trn_sustain: float = 0.0
    clr_drive: float = 0.0
    clr_tone: float = 0.0
    clr_mix: float = 0.55
    clr_gain: float = 1.0
    xct_freq: float = 7000.0
    xct_width: float = 1.20
    xct_band_enabled: bool = False
    xct_amount: float = 0.0
    xct_mix: float = 0.45
    level: float = 0.0
    comp_gr_db: float = 0.0
    comp_env: float = 0.0
    band_levels: np.ndarray = field(default_factory=lambda: np.zeros(POL_BANDS, dtype=np.float32))
    band_noise_floor: np.ndarray = field(default_factory=lambda: np.full(POL_BANDS, 0.0015, dtype=np.float32))


class ConsoleEngine:
    def __init__(self) -> None:
        ensure_demo_stems()
        self.channels = [self._load_channel(name, STEMS_DIR / filename) for name, filename in CHANNEL_LAYOUT]
        self.master_channel = ChannelState(name="Master", path=ROOT_DIR / "master_bus")
        self.master_channel.pre_enabled = False
        self.stream = None
        self.playing = False
        self.loop = True
        self.master_gain = 0.82
        self.master_level = 0.0
        self._lock = threading.Lock()
        # Monitor / calibration generators (summed into output when active).
        self.generator_mode = "none"  # none | osc | pink | white
        self.osc_hz = 440.0
        self.osc_phase = 0.0
        self._pink_b = np.zeros(6, dtype=np.float64)
        self.generator_gain = 0.11
        self._bootstrap_cleared_mix_state()

    def _bootstrap_cleared_mix_state(self) -> None:
        """Cold start: no solo, no inserts — operator gets a blank strip board every launch."""
        for ch in getattr(self, "channels", []) or []:
            ch.solo = False
            ch.mute = False
            ch.record_armed = False
            ch.pre_enabled = False
            ch.phantom = False
            ch.phase = False
            ch.tube = False
            ch.harm_tube = False
            ch.gate_tube = False
            ch.comp_tube = False
            ch.eq_tube = False
            ch.lpf_enabled = False
            ch.hpf_enabled = False
            ch.lpf_hz = float(POL_LOW_HZ)
            ch.hpf_hz = float(POL_HIGH_HZ)
            ch.harmonics_enabled = False
            ch.harmonics[:] = 0.0
            ch.harmonic_makeup = 1.0
            ch.comp_enabled = False
            ch.limit_enabled = False
            ch.gate_enabled = False
            ch.comp_band_enabled = False
            ch.limit_band_enabled = False
            ch.gate_band_enabled = False
            ch.eq_enabled = False
            ch.eq_band_enabled = False
            ch.eq_band_count = 1
            ch.eq_ui_band = 0
            ch.eq_freq = 2200.0
            ch.eq_gain_db = 0.0
            ch.eq_width = 1.4
            ch.eq_type = "BELL"
            for b in ch.eq_bands:
                b.update(
                    enabled=False,
                    freq=2200.0,
                    gain_db=0.0,
                    width=1.4,
                    type="BELL",
                    band_enabled=False,
                )
            ch.eq_param_bypass.clear()
            ch.gate_param_bypass.clear()
            ch.comp_param_bypass.clear()
            ch.harm_param_bypass.clear()
            ch.tone_param_bypass.clear()
            ch.tone_enabled = False
            ch.transient_enabled = False
            ch.exciter_enabled = False
            ch.saturation_enabled = False
            ch.trn_attack = 0.0
            ch.trn_sustain = 0.0
            ch.clr_drive = 0.0
            ch.xct_amount = 0.0
            ch.position = 0
        if getattr(self, "master_channel", None) is not None:
            mc = self.master_channel
            mc.eq_enabled = False
            mc.eq_band_enabled = False
            mc.tone_enabled = False
    def _load_channel(self, name: str, path: Path) -> ChannelState:
        if not path.exists():
            raise FileNotFoundError(f"Missing stem: {path}")
        data, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
        if samplerate != SAMPLE_RATE:
            raise ValueError(f"{path.name} samplerate {samplerate} != {SAMPLE_RATE}")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        ch = ChannelState(name=name, path=path, audio=data.astype(np.float32))
        ch.wave_preview = ConsoleEngine._build_wave_preview(ch.audio)
        return ch

    @staticmethod
    def _build_wave_preview(audio: np.ndarray, buckets: int = 512) -> np.ndarray:
        """Downsample amplitude envelope for strip waveforms (full clip normalized to 0..1)."""

        if audio is None or len(audio) < 2:
            return np.ones((1,), dtype=np.float32) * 1e-4
        if audio.ndim >= 2 and audio.shape[1] >= 2:
            mono = (np.abs(audio[:, 0].astype(np.float64)) + np.abs(audio[:, 1].astype(np.float64))) * 0.5
        else:
            mono = np.abs(audio.reshape(-1).astype(np.float64))
        n = int(len(mono))
        b = max(32, min(buckets, n))
        chunk = max(1, n // b)
        usable = (n // chunk) * chunk
        if usable < chunk:
            return np.ones((1,), dtype=np.float32) * 1e-4
        peaks = mono[:usable].reshape(-1, chunk).max(axis=1).astype(np.float32)
        mx = float(np.max(peaks))
        if mx < 1e-12:
            mx = 1.0
        peaks *= 1.0 / mx
        return peaks.astype(np.float32)

    def start(self) -> None:
        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self.stream.start()
        self.playing = True

    def prime_stream(self) -> None:
        """Open the output device but keep transport idle: silence until ``playing`` becomes True."""

        if self.stream is None:
            self.stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self.stream.start()
        self.playing = False

    def stop(self) -> None:
        self.playing = False
        with self._lock:
            for ch in self.channels:
                ch.position = 0

    def toggle_play(self) -> None:
        if not self.playing and self.stream is None:
            self.start()
            return
        self.playing = not self.playing

    def rewind(self) -> None:
        """Reset all channel positions to 0 without affecting play state."""
        with self._lock:
            for ch in self.channels:
                ch.position = 0

    def jump_forward(self, seconds: float = 5.0) -> None:
        samples = int(seconds * SAMPLE_RATE)
        with self._lock:
            for ch in self.channels:
                ch.position = min(max(0, len(ch.audio) - 1), ch.position + samples)

    def jump_back(self, seconds: float = 5.0) -> None:
        samples = int(seconds * SAMPLE_RATE)
        with self._lock:
            for ch in self.channels:
                ch.position = max(0, ch.position - samples)

    def seek_seconds(self, t: float) -> None:
        """Seek all input channels to absolute time ``t`` (seconds)."""
        with self._lock:
            if not self.channels:
                return
            mx = max(len(ch.audio) for ch in self.channels)
            pos = int(np.clip(t * SAMPLE_RATE, 0, max(0, mx - 1)))
            for ch in self.channels:
                ch.position = min(pos, len(ch.audio) - 1)

    @property
    def playhead_seconds(self) -> float:
        if not self.channels:
            return 0.0
        return float(self.channels[0].position) / SAMPLE_RATE

    def timeline_duration_seconds(self) -> float:
        if not self.channels:
            return 1.0
        return float(len(self.channels[0].audio)) / SAMPLE_RATE

    def toggle_loop(self) -> None:
        self.loop = not self.loop

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _synthesize_generator(self, frames: int) -> np.ndarray:
        """Return stereo float32 block for current ``generator_mode``. Caller must hold ``_lock``.

        Updates ``osc_phase`` / ``_pink_b`` in place.
        """
        mode = self.generator_mode
        sr = float(SAMPLE_RATE)
        g = float(self.generator_gain)
        if mode == "none" or frames <= 0:
            return np.zeros((max(0, frames), 2), dtype=np.float32)
        if mode == "white":
            x = (np.random.randn(frames) * g).astype(np.float32)
            return np.column_stack((x, x))
        if mode == "pink":
            pink = np.empty(frames, dtype=np.float64)
            b = self._pink_b
            for i in range(frames):
                w = float(np.random.randn()) * 0.11
                b[0] = 0.99886 * b[0] + w * 0.0555179
                b[1] = 0.99332 * b[1] + w * 0.0750759
                b[2] = 0.96900 * b[2] + w * 0.1538520
                b[3] = 0.86650 * b[3] + w * 0.3104856
                b[4] = 0.55000 * b[4] + w * 0.5329522
                b[5] = -0.7616 * b[5] - w * 0.0168980
                pink[i] = b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + w * 0.5362
            pink *= g * 3.2
            pv = pink.astype(np.float32)
            return np.column_stack((pv, pv))
        if mode == "osc":
            hz = float(np.clip(self.osc_hz, 20.0, 20000.0))
            ph = float(self.osc_phase)
            dt = (2.0 * math.pi * hz) / sr
            t = ph + dt * np.arange(frames, dtype=np.float64)
            s = (np.sin(t) * g * 1.15).astype(np.float32)
            self.osc_phase = float((ph + frames * dt) % (2.0 * math.pi))
            return np.column_stack((s, s))
        return np.zeros((frames, 2), dtype=np.float32)

    def _callback(self, outdata, frames, time_info, status) -> None:
        try:
            gen_out = None
            with self._lock:
                playing = self.playing
                if self.generator_mode != "none":
                    gen_out = self._synthesize_generator(frames)

                if not playing:
                    if gen_out is not None:
                        pk = float(np.max(np.abs(gen_out)))
                        if pk > 0.98:
                            gen_out = gen_out * (0.98 / pk)
                        outdata[:] = gen_out.astype(np.float32)
                        self.master_level = float(pk * 2.2)
                        self._analyze_channel(self.master_channel, gen_out.astype(np.float32))
                    else:
                        outdata[:] = 0.0
                        for ch in self.channels:
                            ch.level *= 0.92
                            ch.comp_gr_db *= 0.75
                            ch.band_levels *= 0.90
                        self.master_channel.level *= 0.92
                        self.master_channel.comp_gr_db *= 0.75
                        self.master_channel.band_levels *= 0.90
                        self.master_level *= 0.9
                    return

                any_solo = any(ch.solo for ch in self.channels)
                master_gain = self.master_gain
                channel_states = []
                for ch in self.channels:
                    channel_states.append({
                        "ch": ch,
                        "gain": ch.gain,
                        "pan": ch.pan,
                        "mute": ch.mute,
                        "solo": ch.solo,
                        "position": ch.position,
                    })

            mix = np.zeros((frames, 2), dtype=np.float32)
            for state in channel_states:
                ch = state["ch"]
                block = self._next_block(ch, frames)
                processed = self._process_channel(ch, block)
                in_mix = (not state["mute"]) and (not any_solo or state["solo"])
                self._analyze_channel(ch, processed if in_mix else np.zeros_like(processed))
                if not in_mix:
                    processed *= 0.0
                mix += self._apply_pan(processed, state["pan"]) * state["gain"]
                ch.level = float(np.sqrt(np.mean(np.square(processed))) * 3.4)

            mix *= master_gain
            master_processed = self._process_channel(self.master_channel, mix)
            self.master_channel.level = float(np.sqrt(np.mean(np.square(master_processed))) * 2.8)
            peak = float(np.max(np.abs(master_processed)))
            if peak > 0.98:
                master_processed = master_processed * (0.98 / peak)

            if gen_out is not None:
                mp = master_processed.astype(np.float64) + gen_out.astype(np.float64)
                peak2 = float(np.max(np.abs(mp)))
                if peak2 > 0.98:
                    mp *= 0.98 / peak2
                listen = mp.astype(np.float32)
                outdata[:] = listen
                pk_out = float(np.max(np.abs(listen)))
                self.master_level = float(min(1.0, max(float(np.sqrt(np.mean(np.square(listen))) * 2.8), pk_out * 2.2)))
            else:
                listen = master_processed.astype(np.float32)
                outdata[:] = listen
                self.master_level = float(np.sqrt(np.mean(np.square(listen))) * 2.8)

            self._analyze_channel(self.master_channel, listen)

            if status:
                _log.debug(f"Audio status: {status}")
        except Exception as e:
            _log.error(f"Audio callback error: {e}")
            import traceback
            _log.error(traceback.format_exc())
            outdata[:] = 0.0  # Output silence on error

    def _next_block(self, ch: ChannelState, frames: int, position_override: int = None) -> np.ndarray:
        """Get next audio block. Thread-safe if position_override is provided."""
        pos = position_override if position_override is not None else ch.position
        end = pos + frames

        if end <= len(ch.audio):
            block = ch.audio[pos:end]
            if position_override is None:
                ch.position = end
            return block.copy()

        head = ch.audio[pos:] if pos < len(ch.audio) else np.zeros((0, 2), dtype=np.float32)
        if not self.loop:
            if position_override is None:
                ch.position = len(ch.audio)
            return np.vstack([head, np.zeros((frames - len(head), 2), dtype=np.float32)])

        tail_frames = frames - len(head)
        wraps = []
        while tail_frames > 0:
            take = min(len(ch.audio), tail_frames)
            wraps.append(ch.audio[:take])
            tail_frames -= take

        if position_override is None:
            ch.position = sum(len(x) for x in wraps) % len(ch.audio)
        return np.vstack([head, *wraps]).astype(np.float32)

    def _process_channel(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        x = block.astype(np.float32) * ch.gain
        if ch.pre_enabled:
            if ch.phase:
                x[:, 1] *= -1.0
            if ch.lpf_enabled:
                x = self._apply_simple_filter(x, ch.lpf_hz, "highpass")
            if ch.hpf_enabled:
                x = self._apply_simple_filter(x, ch.hpf_hz, "lowpass")
        if ch.tube:
            x = np.tanh(x * 1.18).astype(np.float32)
        if ch.harmonics_enabled and np.any(ch.harmonics > 0.001):
            x = self._apply_harmonics(x, ch.harmonics, ch.harmonic_makeup, getattr(ch, "harm_param_bypass", None) or {})
        if ch.harm_tube:
            x = np.tanh(x * 1.18).astype(np.float32)
        if ch.gate_enabled:
            x = self._apply_gate(ch, x)
        if ch.gate_tube:
            x = np.tanh(x * 1.18).astype(np.float32)
        if ch.comp_enabled:
            x = self._apply_compressor(ch, x)
        if ch.comp_tube:
            x = np.tanh(x * 1.18).astype(np.float32)
        bp = getattr(ch, "eq_param_bypass", None) or {}
        if ch.eq_enabled:
            if ch.eq_band_enabled:
                nb = max(1, min(8, int(ch.eq_band_count)))
                sel = int(np.clip(getattr(ch, "eq_ui_band", 0), 0, nb - 1))
                for i in range(nb):
                    band = ch.eq_bands[i]
                    if not bool(band.get("enabled", False)):
                        continue
                    if i == sel and bp.get("FRQ"):
                        continue
                    gdb = float(band.get("gain_db", 0.0))
                    if i == sel and bp.get("GAN"):
                        gdb = 0.0
                    if abs(gdb) <= 0.03:
                        continue
                    freq_u = float(band.get("freq", ch.eq_freq))
                    wid_u = float(band.get("width", ch.eq_width))
                    if i == sel and (bp.get("SHP") or bp.get("BD2")):
                        wid_u = 1.4
                    x = self._apply_eq(x, freq_u, gdb, wid_u)
            else:
                freq_u = float(ch.eq_freq if not bp.get("FRQ") else 2400.0)
                gdb_u = float(ch.eq_gain_db if not bp.get("GAN") else 0.0)
                wid_u = float(ch.eq_width if not (bp.get("BD2") or bp.get("SHP")) else 1.4)
                if abs(gdb_u) > 0.03:
                    x = self._apply_eq(x, freq_u, gdb_u, wid_u)
        if ch.eq_tube:
            x = np.tanh(x * 1.18).astype(np.float32)
        if ch.tone_enabled:
            x = self._apply_tone(x, ch)
        return np.clip(x, -1.0, 1.0).astype(np.float32)

    def _analyze_channel(self, ch: ChannelState, block: np.ndarray) -> None:
        # Analyze every few blocks — spectrum is visibly smoothed; saves many rFFTs/sec with 13+ strips.
        if not hasattr(ch, "_analyze_counter"):
            ch._analyze_counter = 0
        ch._analyze_counter += 1
        if ch._analyze_counter % 4 != 0:
            ch.band_levels *= 0.962
            return

        mono = np.mean(block, axis=1).astype(np.float32)
        if len(mono) < 32:
            ch.band_levels *= 0.92
            return

        cache_key = len(mono)
        if not hasattr(self, "_hanning_cache"):
            self._hanning_cache = {}
        if cache_key not in self._hanning_cache:
            self._hanning_cache[cache_key] = np.hanning(cache_key).astype(np.float32)
        windowed = mono * self._hanning_cache[cache_key]

        spec = np.abs(np.fft.rfft(windowed))

        freq_cache = getattr(self, "_rfft_freq_cache", {})
        setattr(self, "_rfft_freq_cache", freq_cache)
        if cache_key not in freq_cache:
            freq_cache[cache_key] = np.fft.rfftfreq(cache_key, d=1.0 / SAMPLE_RATE)
        freqs = freq_cache[cache_key]

        if not hasattr(self, "_pol_edges"):
            self._pol_edges = np.logspace(LOG_LOW, LOG_HIGH, POL_BANDS + 1)
        edges = self._pol_edges

        i_bin = np.searchsorted(edges, freqs, side="right") - 1
        i_bin = np.clip(i_bin, 0, POL_BANDS - 1).astype(np.intp)
        mag_sq = (spec.astype(np.float64)) ** 2
        sums = np.bincount(i_bin, weights=mag_sq, minlength=POL_BANDS)
        counts = np.clip(np.bincount(i_bin, minlength=POL_BANDS).astype(np.float64), 1.0, 1e12)
        band_values = np.sqrt(sums / counts).astype(np.float32)

        ch.band_noise_floor = ch.band_noise_floor * 0.995 + np.minimum(ch.band_noise_floor, band_values + 1e-8) * 0.005
        relative = np.maximum(0.0, band_values - ch.band_noise_floor * 1.25)
        mapped = np.clip(relative / 8.0, 0.0, 1.0)
        mapped = np.power(mapped, 0.55).astype(np.float32)
        ch.band_levels = ch.band_levels * 0.58 + mapped * 0.42

    def _mono_for_dynamics_detector(
        self, ch: ChannelState, block: np.ndarray, *, kind: str
    ) -> np.ndarray:
        """Mono envelope-drive signal for gate / compressor.

        With sidechain band on, detector is band-limited unless ``FRQ`` or ``WDT`` is
        bypass-toggled (full-band detector so the bypass is audible).
        """
        mono_full = np.mean(block, axis=1).astype(np.float32)
        if kind == "gate":
            if not getattr(ch, "gate_band_enabled", False):
                return mono_full
            gb = getattr(ch, "gate_param_bypass", None) or {}
            if gb.get("FRQ") or gb.get("WDT"):
                return mono_full
            cen = float(ch.gate_center_hz)
            wo = float(ch.gate_width_oct)
        elif kind == "comp":
            if not getattr(ch, "comp_band_enabled", False):
                return mono_full
            cb = getattr(ch, "comp_param_bypass", None) or {}
            if cb.get("FRQ") or cb.get("WDT"):
                return mono_full
            cen = float(ch.comp_center_hz)
            wo = float(ch.comp_width_oct)
        else:
            return mono_full
        lo = max(float(POL_LOW_HZ), cen / (2.0 ** (wo / 2.0)))
        hi = min(float(POL_HIGH_HZ), cen * (2.0 ** (wo / 2.0)))
        if lo >= hi * 0.99:
            return mono_full
        hp = self._apply_simple_filter(block, lo, "highpass")
        return np.mean(self._apply_simple_filter(hp, hi, "lowpass"), axis=1).astype(np.float32)

    def _apply_simple_filter(self, block: np.ndarray, cutoff_hz: float, mode: str) -> np.ndarray:
        cutoff = float(np.clip(cutoff_hz, POL_LOW_HZ, SAMPLE_RATE * 0.45))
        freqs = np.fft.rfftfreq(len(block), d=1.0 / SAMPLE_RATE)
        scale = np.ones_like(freqs, dtype=np.float32)
        if mode == "lowpass":
            scale = 1.0 / np.sqrt(1.0 + (freqs / max(cutoff, 1.0)) ** 4)
        elif mode == "highpass":
            ratio = freqs / max(cutoff, 1.0)
            scale = np.where(freqs <= 0.0, 0.0, (ratio ** 2) / np.sqrt(1.0 + ratio ** 4))
        out = np.zeros_like(block)
        for idx in range(block.shape[1]):
            spec = np.fft.rfft(block[:, idx])
            out[:, idx] = np.fft.irfft(spec * scale, n=len(block)).astype(np.float32)
        return out

    def _apply_harmonics(
        self, block: np.ndarray, weights: np.ndarray, makeup: float, harm_bypass: dict[str, bool] | None = None
    ) -> np.ndarray:
        hpb = harm_bypass if isinstance(harm_bypass, dict) else {}
        out = np.zeros_like(block, dtype=np.float32)
        for idx in range(block.shape[1]):
            x = block[:, idx].astype(np.float32)
            base_rms = float(np.sqrt(np.mean(np.square(x))) + 1e-7)
            x = np.clip(x, -0.999, 0.999)
            theta = np.arccos(x)
            enhanced = x.copy()
            for order_idx, weight in enumerate(weights):
                if bool(hpb.get(f"H{order_idx + 1}", False)):
                    continue
                if weight <= 0.001:
                    continue
                order = order_idx + 2
                partial = np.cos(order * theta).astype(np.float32)
                enhanced += partial * float(weight) * (0.54 - order_idx * 0.05)
            shaped = np.tanh(enhanced * 1.4).astype(np.float32)
            resonance = shaped - np.tanh(x * 1.4).astype(np.float32)
            mix = x * 0.94 + resonance * 0.68
            mixed_rms = float(np.sqrt(np.mean(np.square(mix))) + 1e-7)
            auto_makeup = min(2.1, max(0.9, base_rms / mixed_rms))
            out[:, idx] = np.tanh(mix * auto_makeup * makeup).astype(np.float32)
        return out

    def _apply_gate(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        """Noise gate / downward expander — independent envelope from the compressor."""
        if not ch.gate_enabled or ch.gate_makeup <= 0.001:
            return block

        mono = self._mono_for_dynamics_detector(ch, block, kind="gate")
        gb = getattr(ch, "gate_param_bypass", None) or {}
        local_env = float(ch.gate_env)
        atk_ms = 0.05 if gb.get("ATK") else float(ch.gate_attack_ms)
        rls_ms = 0.05 if gb.get("RLS") else float(ch.gate_release_ms)
        attack_env = math.exp(-1.0 / max(1.0, (atk_ms / 1000.0) * SAMPLE_RATE))
        release_env = math.exp(-1.0 / max(1.0, (rls_ms / 1000.0) * SAMPLE_RATE))
        # Gain smoothing: open faster, close slower (fractions of knob times).
        atk_g = math.exp(-1.0 / max(1.0, (atk_ms * 0.25 / 1000.0) * SAMPLE_RATE))
        rel_g = math.exp(-1.0 / max(1.0, (rls_ms * 0.30 / 1000.0) * SAMPLE_RATE))

        thr_db = float(np.clip(ch.gate_threshold_db, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER))
        if gb.get("THR"):
            thr_db = float(POL_LEVEL_DB_AXIS_OUTER) - 96.0
        floor_linear = 1.0 / max(1.001, float(ch.gate_ratio))
        if gb.get("RAT"):
            floor_linear = 1.0
        mkup = max(0.001, float(ch.gate_makeup))
        if gb.get("GAN"):
            mkup = 1.0
        open_tgt = mkup
        closed_tgt = mkup * floor_linear

        gain_smooth = float(ch.gate_gain_smooth)
        gains = np.empty(len(mono), dtype=np.float32)
        last_gr = 0.0

        for i, sample in enumerate(mono):
            det = abs(float(sample))
            if det > local_env:
                local_env = attack_env * local_env + (1.0 - attack_env) * det
            else:
                local_env = release_env * local_env + (1.0 - release_env) * det
            env_db = 20.0 * math.log10(max(local_env, 1e-7))
            target = open_tgt if env_db >= thr_db else closed_tgt
            coef = atk_g if target > gain_smooth else rel_g
            gain_smooth = coef * gain_smooth + (1.0 - coef) * target
            g_lin = gain_smooth / mkup
            gains[i] = g_lin
            last_gr = -20.0 * math.log10(max(g_lin, 1e-7))

        ch.gate_env = local_env
        ch.gate_gain_smooth = gain_smooth
        ch.gate_gr_db = last_gr
        return block * gains[:, None]

    def _apply_compressor(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        # Early bypass if disabled or no compression needed
        if not ch.comp_enabled or ch.comp_makeup <= 0.001:
            return block

        mono = self._mono_for_dynamics_detector(ch, block, kind="comp")
        cb = getattr(ch, "comp_param_bypass", None) or {}
        env = float(ch.comp_env)
        ca_ms = 0.05 if cb.get("ATK") else float(ch.comp_attack_ms)
        cr_ms = 0.05 if cb.get("RLS") else float(ch.comp_release_ms)
        attack_coeff = math.exp(-1.0 / max(1.0, (ca_ms / 1000.0) * SAMPLE_RATE))
        release_coeff = math.exp(-1.0 / max(1.0, (cr_ms / 1000.0) * SAMPLE_RATE))
        ratio = max(1.0, float(ch.comp_ratio))
        if cb.get("RAT"):
            ratio = 1.0
        threshold = float(np.clip(ch.comp_threshold_db, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER))
        if cb.get("THR"):
            threshold = float(POL_LEVEL_DB_AXIS_OUTER) - 96.0

        gains = np.empty(len(mono), dtype=np.float32)
        last_gr = 0.0

        # Use local variables for speed
        local_env = env
        atk = attack_coeff
        rel = release_coeff
        thr = threshold
        rat = ratio
        mkup = float(ch.comp_makeup) if not cb.get("GAN") else 1.0

        for i, sample in enumerate(mono):
            detector = abs(float(sample))
            if detector > local_env:
                local_env = atk * local_env + (1.0 - atk) * detector
            else:
                local_env = rel * local_env + (1.0 - rel) * detector
            env_db = 20.0 * math.log10(max(local_env, 1e-7))
            over_db = max(0.0, env_db - thr)
            gr_db = over_db - (over_db / rat if over_db > 0 else 0.0)
            gains[i] = 10 ** (-gr_db / 20.0) * mkup
            last_gr = gr_db

        ch.comp_env = local_env
        ch.comp_gr_db = last_gr
        return block * gains[:, None]

    def _apply_eq(self, block: np.ndarray, freq: float, gain_db: float, width: float) -> np.ndarray:
        freqs = np.fft.rfftfreq(len(block), d=1.0 / SAMPLE_RATE)
        valid = freqs > 0
        log_freqs = np.zeros_like(freqs, dtype=np.float32)
        log_freqs[valid] = np.log2(np.maximum(freqs[valid], 1.0))
        center_log = math.log2(float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ)))
        sigma = max(0.08, float(width) / 2.355)
        shape = np.zeros_like(freqs, dtype=np.float32)
        shape[valid] = np.exp(-0.5 * ((log_freqs[valid] - center_log) / sigma) ** 2)
        scale = np.power(10.0, (gain_db * shape) / 20.0).astype(np.float32)
        out = np.zeros_like(block, dtype=np.float32)
        for idx in range(block.shape[1]):
            spec = np.fft.rfft(block[:, idx])
            out[:, idx] = np.fft.irfft(spec * scale, n=len(block)).astype(np.float32)
        return out

    def _apply_tone(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        x = block.astype(np.float32)
        tb = getattr(ch, "tone_param_bypass", None) or {}
        if getattr(ch, "transient_enabled", True) and not tb.get("TRN"):
            ta = 0.0 if tb.get("ATK") else ch.trn_attack
            ts = 0.0 if tb.get("SUT") else ch.trn_sustain
            if abs(ta) > 0.01 or abs(ts) > 0.01:
                x = self._apply_transient(x, ta, ts)
        if getattr(ch, "saturation_enabled", True) and ch.clr_drive > 0.01 and not tb.get("DRV"):
            drive = 1.0 + ch.clr_drive * 5.0
            x = np.tanh(x * drive).astype(np.float32)
        if getattr(ch, "exciter_enabled", True) and ch.xct_amount > 0.01 and not tb.get("XCT"):
            if tb.get("FRQ"):
                hp_hz = 4000.0
            elif ch.xct_band_enabled:
                hp_hz = float(ch.xct_freq)
            else:
                hp_hz = 4000.0
            high = self._apply_simple_filter(x, hp_hz, "highpass")
            excite = np.tanh(high * (1.0 + ch.xct_amount * 6.0)).astype(np.float32) - np.tanh(high * 0.8).astype(np.float32)
            x = np.clip(x + excite * 0.9, -1.0, 1.0).astype(np.float32)
        return x

    def _apply_transient(self, block: np.ndarray, attack_amt: float, sustain_amt: float) -> np.ndarray:
        # Early return if no processing needed
        if abs(attack_amt) <= 0.01 and abs(sustain_amt) <= 0.01:
            return block

        mono = np.mean(block, axis=1).astype(np.float32)
        detector = np.abs(mono)

        # Vectorized envelope followers using exponential smoothing
        fast_coef = 0.52
        slow_coef = 0.012

        # Fast envelope using vectorized approach
        fast_env = np.zeros_like(detector)
        slow_env = np.zeros_like(detector)

        fast = 0.0
        slow = 0.0
        for i in range(len(detector)):
            fast += (detector[i] - fast) * fast_coef
            slow += (detector[i] - slow) * slow_coef
            fast_env[i] = fast
            slow_env[i] = slow

        transient = np.maximum(0.0, fast_env - slow_env)
        sustain = slow_env.copy()

        max_transient = float(np.max(transient))
        max_sustain = float(np.max(sustain))
        if max_transient > 1e-6:
            transient /= max_transient
        if max_sustain > 1e-6:
            sustain /= max_sustain

        out = block.copy()
        for idx in range(block.shape[1]):
            x = block[:, idx].astype(np.float32)
            # Edge detection
            prev = np.concatenate(([0.0], x[:-1])).astype(np.float32)
            edge = (x - prev * 0.72) * transient * (attack_amt * 12.0)

            # Sustain body using vectorized exponential smoothing
            sustain_coef = 0.994
            input_coef = 0.055
            body = np.zeros(len(x), dtype=np.float32)
            acc = 0.0
            for i in range(len(x)):
                acc = acc * sustain_coef + x[i] * input_coef
                body[i] = acc

            tail = body * sustain * (sustain_amt * 6.0)
            out[:, idx] = x + edge + tail

        peak = float(np.max(np.abs(out)))
        if peak > 0.98:
            out *= 0.98 / peak
        return out.astype(np.float32)

    def _apply_pan(self, block: np.ndarray, pan: float) -> np.ndarray:
        p = float(np.clip(pan, -1.0, 1.0))
        angle = (p + 1.0) * (math.pi / 4.0)
        left = math.cos(angle)
        right = math.sin(angle)
        out = block.copy()
        mono = np.mean(block, axis=1)
        out[:, 0] = mono * left
        out[:, 1] = mono * right
        return out


class ConsoleApp:
    STRIP_WIDTH = 70
    STAGE_HEIGHT = 78
    # Unified grid: vertical **hold** repeats on a timer — Windows often gates ArrowDown
    # autorepeat differently than ArrowUp; UP/DOWN share the same pacing so wrap feels symmetric.
    STAGE_GRID_VKEY_REPEAT_INITIAL_S = 0.34
    STAGE_GRID_VKEY_REPEAT_STEP_S = 0.072

    def __init__(self, root: tk.Tk, *, internal_capture: bool = False, startup_play: bool = True) -> None:
        """``internal_capture`` is only for scripted screenshot tooling: skips the recurring
        ``after()`` redraw loop (so ``root.update()`` can drive paints) and skips the one-shot
        auto-geometry mover. Normal runs must leave this ``False`` (default).

        ``startup_play`` (default ``True``): primes the output device — stream open,
        silence/green-off until **PLY**, armed amber glyph. Set ``False`` for offline
        capture tooling (no stream until first Play press).

        """

        self.root = root
        self._internal_capture = internal_capture
        self._startup_play = bool(startup_play)
        self.root.title(f"System Q Console · {SYSTEM_Q_BUILD_ID}")
        # Explicit size before layout; overridden by _place_window_primary_visible().
        self.root.geometry("1560x960")
        self.root.configure(bg="#222831")
        self.engine = ConsoleEngine()
        self.spacemouse = SpaceMouseController()
        self.selected_channel = 0
        self.editor_channel = 0
        self.selected_stage_key = "pre"
        self.nav_scope = "console"
        self.console_row = "stages"
        self.editor_selected = {"pre": 0, "harm": 0, "comp": 0, "eq": 0, "tone": 0}
        self.editor_nav_scope = "body"
        self.editor_utility_selected = 0
        self.editor_fader_selected = 0
        self.pre_editor_column = 0
        self.pre_editor_positions = {"left": 0, "stage": 0, "body": 0}
        self.module_editor_column = 0
        self.module_editor_positions = {"left": 0, "stage": 0, "body": 0}
        # Unified all-stages editor grid: cap focus is (column, row). Column
        # is 0..len(_STAGE_GRID)-1; row is interpreted relative to the
        # current column's param list (clamped on column changes).
        self.editor_stage_col = 0
        self.editor_param_row = 0
        self.editor_unified_header_focus = False
        # Per-stage memory of the last body-cursor position. Cycling away from a
        # stage and back used to reset body to 0; this dict lets each stage
        # remember where you were so "peek another stage and come back" doesn't
        # wipe your edit position.
        self._module_body_memory: dict[str, int] = {}
        self._module_body_last_stage = self.selected_stage_key
        # Per-stage cap row when using the unified multi-column editor grid so
        # leaving EQ for another stage and returning restores the EQ row rather
        # than reusing a numeric index meant for another column's param list.
        self._unified_editor_param_row_by_stage: dict[str, int] = {}
        self.comp_editor_mode = "COMP"
        self.comp_nav_row = "bottom"
        self.tone_editor_mode = "TRN"
        self.tone_nav_row = "bottom"
        self.eq_nav_row = "bottom"
        self.eq_selected_band = 0
        self._pending_strip_click = None
        self._pending_stage_action = None
        self._console_hold_target = None
        self._console_hold_repeat_at = 0.0
        self._editor_last_press_at = 0.0
        self._double_press_exit_enabled = False
        self._syncing_controls = False
        self.editor_transport_selected = 0
        self._nav_keys_held: set[str] = set()
        self._nav_key_press_mono: dict[str, float] = {}
        self._stage_grid_vkey_repeat_prev: dict[str, float] = {}
        self._axis_discrete_at = 0.0
        self._pol_out_pulse_hold = 0.0
        self._pol_pulse_cached = 0.0
        # Transport panel NAV state: focused row/col within the 2x8 grid.
        # Active only when nav_scope == "transport".
        self.transport_focus_row = 0
        self.transport_focus_col = 0
        # Tracks how the transport panel was entered so BACK / edge-exit can
        # return the cap to the same scope the user came from.
        #   "console" -> exit goes to console footer
        #   "editor"  -> exit goes back to editor SENDS column (pre or module)
        self._transport_entered_from: str | None = None
        # Knob-row NAV state: a horizontal row of per-channel send-level knobs
        # in the strip view. Reached from the editor via a double-tap LEFT or
        # RIGHT on the cap. Active only when nav_scope == "knobs".
        self.knob_focus_channel = 0
        self._knobs_entered_from: str | None = None
        # Fader-row NAV state: a horizontal row of per-channel volume faders
        # in the strip view. Reached from the knob row via cap DOWN. Active
        # only when nav_scope == "faders".
        self.fader_focus_channel = 0
        self._faders_entered_from: str | None = None
        # SpaceMouse: plain LRUD tilt (no double-tap / hold-macro preprocessing on XY).
        # Long cap push (≥ spacemouse engage_hold_s, default 1s) emits engage_toggle;
        # Editor enter/exit: sustained twist CW/CCW on SpaceMouse (pol_visualizer);
        # keyboard rim + Back still use EDITOR_LR_HOLD_S (see _poll_editor_leave_hold_gate).
        self.EDITOR_LEAVE_HOLD_S = 1.0
        self.EDITOR_LR_HOLD_S = 1.0
        self._editor_leave_hold_key: str | None = None
        self._editor_leave_hold_since = 0.0
        # Strip-link group: long Z on STAGES row toggles membership; in-editor edits
        # mirror mix settings from editor_channel to all other linked input strips.
        self.strip_link_indices: set[int] = set()
        # Snapshot of nav/UI before entering the editor — long Z in editor restores here.
        self._editor_return_ctx: dict[str, object] | None = None
        # Per-strip knob row mode. Default is PAN (each knob shows the
        # channel's pan position, twist rides ch.pan). Pressing any knob
        # while focused on the knob row flips ALL knobs to SEND mode (the
        # global send-bus pick: every channel's send_slot snaps to the
        # focused channel's index+1, all knobs read "S<N>" and twist
        # rides ch.send_level). Pressing again returns to PAN.
        self.knobs_send_mode: bool = False
        self.stage_color = {
            "pre": "#77f0c6",
            "harm": "#ffb757",
            "gate": "#ddc270",
            "comp": "#ff6a53",
            "eq": "#75baff",
            "tone": "#c780ff",
        }
        # Timeline / PLY jog: SRB=scrub (fine steps), SHT=shuttle (coarse).
        self.timeline_jog_step = 0.10
        self.timeline_scrub_active = False
        self.timeline_shuttle_active = False
        self._build_ui()
        self._bind_nav_keys()
        self._bootstrap_kick_eq_view()
        self._sync_from_engine()
        if self._internal_capture:
            try:
                self._poll_spacemouse()
                self._poll_editor_leave_hold_gate()
                self._draw_strips()
                self._draw_timeline()
                self._draw_focus()
                self._draw_editor_controls()
            except Exception:
                import traceback

                traceback.print_exc()
                self.root.title(f"DRAW ERROR: {traceback.format_exc().splitlines()[-1]}")
        else:
            self._schedule_refresh()
        if not self._internal_capture:
            src = Path(__file__).resolve()
            print(f"System Q [{SYSTEM_Q_BUILD_ID}] {src}", flush=True)
            self.root.after_idle(self._place_window_primary_visible)
            if self._startup_play:
                self.root.after_idle(self._startup_transport_ready)
            else:
                self.root.after_idle(self._sync_play_transport_glyph)

    def _startup_transport_ready(self) -> None:
        """Prime device I/O open on launch — PLY is armed (amber); first press actually rolls playback."""

        self.engine.prime_stream()
        self._sync_play_transport_glyph()

    def _place_window_primary_visible(self) -> None:
        """Force the Tk window onto the visible primary work area — stale remembered geometry can hide it."""

        self.root.update_idletasks()
        try:
            self.root.deiconify()
        except tk.TclError:
            pass

        preferred_w = 1660
        preferred_h = 960

        sw = max(800, int(self.root.winfo_screenwidth()))
        sh = max(600, int(self.root.winfo_screenheight()))

        w = max(1024, min(preferred_w, sw - 32))
        h = max(640, min(preferred_h, sh - 48))
        x = max(12, min(sw - w - 12, (sw - w) // 2))
        y = max(12, min(sh - h - 12, (sh - h) // 2))

        try:
            self.root.minsize(900, 600)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            return

        try:
            self.root.state("normal")
        except tk.TclError:
            pass

        self.root.lift()

        try:
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            self.root.after(
                400,
                lambda: self.root.attributes("-topmost", False) if self.root.winfo_exists() else None,
            )
        except tk.TclError:
            pass

        try:
            self.root.attributes("-fullscreen", False)
        except tk.TclError:
            pass

        self.root.focus_force()

    def promote_internal_capture_to_interactive(self) -> None:
        """After ``internal_capture`` proof pumps, attach the recurring UI loop on this same ``Tk``.

        Avoids tearing the window down and spawning a separate process — the frame the operator
        already sees stays up as the normal console."""

        if not getattr(self, "_internal_capture", False):
            try:
                self.root.after_idle(self._place_window_primary_visible)
            except tk.TclError:
                pass
            return
        self._internal_capture = False
        try:
            self.root.title(f"System Q Console · {SYSTEM_Q_BUILD_ID}")
        except tk.TclError:
            pass
        src = Path(__file__).resolve()
        print(f"System Q [{SYSTEM_Q_BUILD_ID}] {src}", flush=True)
        self._schedule_refresh()
        self.root.after_idle(self._place_window_primary_visible)

    def _bootstrap_kick_eq_view(self) -> None:
        """Land on Kick / EQ with the stage grid aligned so the plot is on-screen every launch."""
        self.nav_scope = "editor"
        self.editor_nav_scope = "stage_grid"
        self.editor_channel = 0
        self.selected_channel = 0
        self.selected_stage_key = "eq"
        self.console_row = "stages"
        self.editor_stage_col = 4
        self.editor_param_row = 2
        self.editor_unified_header_focus = False
        self._unified_commit_param_row_for_col(4, 2)
        self.module_editor_positions["stage"] = 4
        self._module_body_last_stage = "eq"

    def _axis_discrete_tick(
        self,
        interval: float = 0.18,
        axis_value: float | None = None,
        magnitude: float | None = None,
    ) -> bool:
        """Rate-limit discrete SpaceMouse steps (channel / slot) while keeping
        analog tweaks smooth. If ``magnitude`` is provided, the call also requires
        ``abs(axis_value) >= magnitude`` so that incidental small twists can't fire
        a discrete step (channel page, slot select, band cycle) without intent.
        """
        if magnitude is not None and axis_value is not None and abs(axis_value) < magnitude:
            return False
        now = time.monotonic()
        if now - self._axis_discrete_at < interval:
            return False
        self._axis_discrete_at = now
        return True

    def _bind_nav_keys(self) -> None:
        """bind_all + KeyPress/KeyRelease: discrete steps; unified grid vertical hold uses
        ``_poll_stage_grid_vertical_key_repeat`` (same timing for UP/DOWN) because OS
        autorepeat on ArrowDown is often slower or less reliable than ArrowUp on Windows."""
        def _clear_nav_held_if_app_lost_keyboard_focus() -> None:
            try:
                if self.root.focus_get() is None:
                    self._nav_keys_held.clear()
                    self._nav_key_press_mono.clear()
                    self._stage_grid_vkey_repeat_prev.clear()
                    self._reset_editor_leave_hold_tracking()
            except tk.TclError:
                pass

        def on_press(target: str):
            def handler(_event) -> str:
                if target in self._nav_keys_held:
                    return "break"
                self._nav_keys_held.add(target)
                self._nav_key_press_mono[target] = time.monotonic()
                if self.nav_scope == "editor" and target == "back":
                    return "break"
                self._handle_nav(target)
                return "break"

            return handler

        def on_release(target: str):
            def handler(_event) -> str:
                self._nav_keys_held.discard(target)
                self._nav_key_press_mono.pop(target, None)
                if target in ("up", "down"):
                    self._stage_grid_vkey_repeat_prev.pop(target, None)
                return "break"

            return handler

        for press_seq, release_seq, target in (
            ("<KeyPress-Left>", "<KeyRelease-Left>", "left"),
            ("<KeyPress-Right>", "<KeyRelease-Right>", "right"),
            ("<KeyPress-Up>", "<KeyRelease-Up>", "up"),
            ("<KeyPress-Down>", "<KeyRelease-Down>", "down"),
            ("<KeyPress-space>", "<KeyRelease-space>", "press"),
            ("<KeyPress-BackSpace>", "<KeyRelease-BackSpace>", "back"),
        ):
            self.root.bind_all(press_seq, on_press(target))
            self.root.bind_all(release_seq, on_release(target))

        def clear_held(_event=None) -> str:
            self._nav_keys_held.clear()
            self._nav_key_press_mono.clear()
            self._stage_grid_vkey_repeat_prev.clear()
            self._reset_editor_leave_hold_tracking()
            return "break"

        self.root.bind_all("<Escape>", clear_held)

        def on_root_unmap(_event) -> str:
            if getattr(_event, "widget", None) is self.root:
                clear_held()
            return "break"

        self.root.bind("<Unmap>", on_root_unmap, add="+")

        def on_root_focus_out(_event) -> str:
            if getattr(_event, "widget", None) is not self.root:
                return "break"
            self.root.after_idle(_clear_nav_held_if_app_lost_keyboard_focus)
            return "break"

        self.root.bind("<FocusOut>", on_root_focus_out, add="+")

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#222831")
        top.pack(fill="x", padx=14, pady=(12, 8))
        brand_row = tk.Frame(top, bg="#222831")
        brand_row.pack(fill="x")
        tk.Label(
            brand_row,
            text="System Q Inter",
            bg="#222831",
            fg="#f3f4f7",
            font=("Segoe UI", 24, "bold"),
        ).pack(side="left")
        tk.Label(
            brand_row,
            text="13-strip rehearsal / Lewitt Eyes multitracks",
            bg="#222831",
            fg="#9fb0c2",
            font=("Segoe UI", 12),
        ).pack(side="left", padx=14, pady=(10, 0))
        # Track + stage headline and clip path live in the window chrome (not
        # inside the highlighted editor pane) per layout request.
        self._editor_context_strip = tk.Frame(top, bg="#1a2230")
        self._editor_context_strip.pack(fill="x", pady=(10, 0))
        self.editor_title = tk.Label(
            self._editor_context_strip,
            text="",
            bg="#1a2230",
            fg="#f2f3f6",
            font=("Segoe UI", 21, "bold"),
        )
        self.editor_title.pack(anchor="w", fill="x", padx=10, pady=(6, 2))
        self.editor_subtitle = tk.Label(
            self._editor_context_strip,
            text="",
            bg="#141a21",
            fg="#8fa3b8",
            font=("Segoe UI", 10),
        )
        # Fixed chrome height: subtitle row is never pack_forget()’d — only its text updates.
        self.editor_subtitle.pack(
            anchor="w",
            fill="x",
            padx=10,
            pady=(0, 6),
            ipadx=4,
            ipady=3,
            after=self.editor_title,
        )

        body = tk.Frame(self.root, bg="#222831")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # Pack from the RIGHT edge inward so each column reserves its slot
        # before the expanding `left` column claims the rest. Order:
        #   1) right  (editor pane; fixed width matched to strip pitch)
        #   2) left   (channel strips, fills remainder)
        # The standalone right-edge transport dock was removed; the new
        # transport section now lives at the BOTTOM of the editor pane.
        right = tk.Frame(body, bg="#161b22", bd=0, highlightthickness=1, highlightbackground="#344250", width=638)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)

        left = tk.Frame(body, bg="#1f252d", bd=0, highlightthickness=1, highlightbackground="#344250")
        left.pack(side="left", fill="both", expand=True)

        # Transport lives UNDER the channel strips, inside `left`. Pack it
        # FIRST (side="bottom") so the strip canvas (packed next, fill=both
        # expand) takes the rest. The dock spans the full strip-area width
        # so its grid columns roughly align under the channel strip row above.
        # Timeline scrub strip removed (was read as noisy “slider”); transport sits
        # directly beneath the mixer strips — meters + faders unchanged above.
        self.timeline_canvas = None

        transport_dock = tk.Frame(
            left,
            bg="#0c1118",
            bd=0,
            highlightthickness=1,
            highlightbackground="#283242",
        )
        transport_dock.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.transport_dock = transport_dock
        self.transport_panel = self._build_transport_panel(transport_dock)
        self.transport_panel.pack(fill="x", padx=6, pady=8)

        self.strip_canvas = tk.Canvas(left, bg="#1c222a", highlightthickness=0)
        self.strip_canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.strip_canvas.bind("<Button-1>", self._on_strip_click)
        self.strip_canvas.bind("<Double-Button-1>", self._on_strip_double_click)
        self.strip_canvas.bind("<MouseWheel>", self._on_strip_mousewheel)

        self.editor_frame = right
        self._build_editor(right)

    def _build_editor(self, parent: tk.Frame) -> None:
        # ``editor_title`` / ``editor_subtitle`` are parented under
        # ``_editor_context_strip`` in ``_build_ui`` (full-width header strip).

        # Master meter removed -- it was just dead chrome at the bottom of
        # the editor pane. We still keep the attribute as a no-op canvas so
        # any code that pokes self.master_meter doesn't AttributeError.
        self.master_meter = tk.Canvas(parent, width=1, height=1, bg="#161b22", highlightthickness=0)

        # Pack BOTTOM-up so the layout fills naturally:
        #   editor_canvas (fixed height, sits just above the master meter)
        #   fader_canvas  (legacy, hidden at 1px)
        #   focus_canvas  (expands to absorb everything left over)
        # Result: enlarging the editor pane height grows the upper visualizer
        # instead of leaving a dead strip below the stage grid.
        self.editor_canvas = tk.Canvas(parent, width=380, height=400, bg="#10151b", highlightthickness=1, highlightbackground="#344250")
        self.editor_canvas.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        self.editor_canvas.bind("<Button-1>", self._on_editor_canvas_click)
        self.fader_canvas = tk.Canvas(parent, width=380, height=1, bg="#10151b", highlightthickness=0)
        self.fader_canvas.pack(side="bottom", fill="x", padx=16, pady=(0, 0))
        self.fader_canvas.bind("<Button-1>", self._on_fader_canvas_click)
        self.focus_canvas = tk.Canvas(parent, width=380, height=200, bg="#10151b", highlightthickness=1, highlightbackground="#344250")
        self.focus_canvas.pack(side="top", fill="both", expand=True, padx=16, pady=(8, 12))

        self._init_editor_state_vars()

    # ------------------------------------------------------------------ #
    # Hardware-mirror transport panel                                    #
    # ------------------------------------------------------------------ #
    # 6 columns x 2 rows = 12 buttons. Lives at the bottom of the editor #
    # pane (the standalone right-edge dock was removed). Layout matches  #
    # the user's hardware grid:                                          #
    #   Row 0 (transport): SHT  RWD  PLY  FWD  SRB  REC                  #
    #   Row 1 (automode):  RDE  WRT  TRM  LTC  UND  RDU                  #
    # Most actions are stubs that log; play/rewind/forward/record/undo/  #
    # redo are wired to the engine. Renaming/rewiring is one line each.  #
    # ------------------------------------------------------------------ #
    # Wired transport buttons live in cols 3..8 of the 12-col grid so that
    # PLY (col 5) sits at the center of the row. Cols 0..2 on row 1 are
    # monitor generators (OSC / PNK / WHT); cols 9..11 stay blank for now.
    _TRANSPORT_BUTTONS = [
        # (row, col, key,     label, color,     glyph)
        # Row 0 - transport
        (0, 3, "shuttle",    "SHT", "#9aa3ad", "\u21c4"),
        (0, 4, "rewind",     "RWD", "#5ec8ff", "\u23ee"),
        (0, 5, "play",       "PLY", "#5cb8ff", "\u25b6"),
        (0, 6, "forward",    "FWD", "#5ec8ff", "\u23ed"),
        (0, 7, "scrub",      "SRB", "#f2efe5", "\u2194"),
        (0, 8, "record",     "REC", "#ff5050", "\u25cf"),
        # Row 1 - oscill / noise + automation (cols 0–2 = gen, 3–8 = auto/tx)
        (1, 0, "oscillator", "", "#f0c6ff", "~"),
        (1, 1, "pink",       "", "#f472c0", "\u223f"),
        (1, 2, "white",      "", "#a8d8ff", "\u25c7"),
        (1, 3, "read",       "RDE", "#7cf0a9", "R"),
        (1, 4, "write",      "WRT", "#ff5050", "W"),
        (1, 5, "trim",       "TRM", "#ddc270", "T"),
        (1, 6, "latch",      "LTC", "#5cb8ff", "L"),
        (1, 7, "undo",       "UND", "#ff7d6e", "\u21ba"),
        (1, 8, "redo",       "RDU", "#ddc270", "\u21bb"),
    ]

    # Width of one editor stage column (in px). Used by the editor body
    # grid so each PRE/HRM/GTE/CMP/EQ/TON column sits at a uniform pitch.
    # Transport is no longer pinned to this constant -- it lives under the
    # channel strips and stretches to whatever pitch matches one strip.
    STAGE_COL_WIDTH = 84
    STAGE_COL_PAD = 2
    # Fallback editor_canvas heights before layout / Tk errors. Prefer
    # ``_unified_editor_grid_need_height_px()`` — the unified grid tallest
    # column is 9 rows; 328px clipped the bottom cells on normal windows.
    EDITOR_CANVAS_H_NORMAL = 396
    EDITOR_CANVAS_H_MULTIBAND = 284
    # Legacy note: reserving a huge focus minimum here previously starved the
    # unified stage grid (~396px tall) whenever ``split - reservation`` was small.
    # Polar/focus_canvas still expands with ``expand=True``; we only reserve a
    # small tail when budgeting editor_canvas height below.
    EDITOR_FOCUS_AUTOSIZE_TAIL_RESERVE = 96
    EDITOR_GRID_AUTOSHRINK_MIN_H = 168
    GRID_HEADER_H_NORMAL = 26
    GRID_CELL_H_NORMAL = 36
    GRID_HEADER_H_MULTIBAND = 22
    GRID_CELL_H_MULTIBAND = 24

    # Transport grid dimensions. 12 columns x 2 rows = 24 cells; the user's
    # 6-key wide labels go in cols 0-5 and cols 6-11 are intentionally left
    # blank for now (placeholder slots to be wired later).
    TRANSPORT_COLS = 12
    TRANSPORT_ROWS = 2

    def _build_transport_panel(self, parent: tk.Frame) -> tk.Frame:
        BTN_H = 56
        PAD = 2
        # The panel fills the strip area horizontally; each of the 12 grid
        # columns gets equal weight so the cells stretch one strip-pitch.
        panel = tk.Frame(parent, bg="#0c1118", bd=0)
        inner = tk.Frame(panel, bg="#0c1118")
        inner.pack(fill="x", padx=0, pady=0)
        for c in range(self.TRANSPORT_COLS):
            inner.grid_columnconfigure(c, weight=1, uniform="tx_col")
        # Build a (row, col) -> button-spec lookup for the wired keys.
        spec_at: dict[tuple[int, int], tuple[str, str, str, str]] = {}
        for r, c, key, label, color, glyph in self._TRANSPORT_BUTTONS:
            spec_at[(r, c)] = (key, label, color, glyph)
        self._transport_buttons: dict[str, tk.Canvas] = {}
        # Track every cell (wired or blank) by (row, col) so navigation can
        # walk the full 12 x 2 grid even where there's no wired action yet.
        self._transport_cells: dict[tuple[int, int], tk.Frame] = {}

        for row in range(self.TRANSPORT_ROWS):
            for col in range(self.TRANSPORT_COLS):
                spec = spec_at.get((row, col))
                cell_bg = "#15202c" if spec else "#10161e"
                border = "#2a3848" if spec else "#1d2530"
                cell = tk.Frame(
                    inner,
                    bg=cell_bg,
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=border,
                    height=BTN_H,
                )
                cell.grid(row=row, column=col, padx=PAD, pady=PAD, sticky="nsew")
                cell.grid_propagate(False)
                self._transport_cells[(row, col)] = cell
                canvas = tk.Canvas(cell, bg=cell_bg, height=BTN_H, highlightthickness=0, takefocus=False)
                canvas.pack(fill="both", expand=True)
                if spec is None:
                    # Blank placeholder cell -- no glyph/label/handler yet.
                    continue
                key, label, color, glyph = spec
                canvas.create_text(0, 0, text=glyph, fill=color, font=("Segoe UI Symbol", 18, "bold"), tags=("glyph",))
                if label and label.strip():
                    canvas.create_text(0, 0, text=label, fill="#9aa6b6", font=("Segoe UI", 8, "bold"), tags=("label",))

                def _layout(ev, cv=canvas, lab=label):
                    if lab and lab.strip():
                        cv.coords("glyph", ev.width / 2, ev.height / 2 - 5)
                        cv.coords("label", ev.width / 2, ev.height - 10)
                    else:
                        cv.coords("glyph", ev.width / 2, ev.height / 2)
                canvas.bind("<Configure>", _layout)
                handler = getattr(self, f"_tx_{key}", None) or (lambda k=key: self._tx_stub(k))
                canvas.bind("<Button-1>", lambda e, h=handler: h())
                cell.bind("<Button-1>", lambda e, h=handler: h())
                self._transport_buttons[key] = canvas
        return panel

    def _sync_play_transport_glyph(self) -> None:
        """PLY: cooler idle if no OutputStream yet; warm amber once primed; green while rolling."""

        canvas = self._transport_buttons.get("play")
        if not canvas:
            return
        try:
            rolling = bool(getattr(self.engine, "playing", False))
            primed = getattr(self.engine, "stream", None) is not None
            if rolling:
                canvas.configure(bg="#15202c")
                canvas.itemconfigure("glyph", fill="#7cf0a9")
            elif primed:
                canvas.configure(bg="#24354a")
                canvas.itemconfigure("glyph", fill="#fcd34d")
            else:
                canvas.configure(bg="#1a2735")
                canvas.itemconfigure("glyph", fill="#94a3b8")
        except tk.TclError:
            pass

    def _tx_flash(self, key: str) -> None:
        """Briefly flash a button to give visual click feedback."""

        canvas = self._transport_buttons.get(key)
        if not canvas:
            return
        original = canvas.cget("bg")
        canvas.configure(bg="#27425e")
        for item in canvas.find_withtag("glyph") + canvas.find_withtag("label"):
            pass
        self.root.after(120, lambda: canvas.configure(bg=original))

    def _tx_stub(self, key: str) -> None:
        _log.debug("TRANSPORT stub press: %s", key)
        self._tx_flash(key)

    # Wired handlers --------------------------------------------------- #
    def _tx_play(self) -> None:
        # Press toggles play/stop. The engine's toggle_play() handles both
        # directions (start playback or stop it) so a single button works.
        self.engine.toggle_play()
        self._tx_flash("play")
        self._sync_play_transport_glyph()
        _log.debug("TRANSPORT play -> playing=%s", self.engine.playing)

    def _tx_play_jog(self, axis_value: float) -> None:
        """Jog timeline by ``timeline_jog_step`` × SRB (fine) / SHT (coarse)."""
        if abs(axis_value) < 0.01:
            return
        if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
            return
        delta = self.timeline_jog_step if axis_value > 0 else -self.timeline_jog_step
        eng = self.engine
        dur = eng.timeline_duration_seconds()
        nt = np.clip(float(eng.playhead_seconds) + delta, 0.0, max(1e-6, dur))
        eng.seek_seconds(nt)
        _log.debug("PLY jog %+gs (step %.3fs mode scrub=%s shuttle=%s)", delta, self.timeline_jog_step, self.timeline_scrub_active, self.timeline_shuttle_active)

    def _tx_stop(self) -> None:
        self.engine.stop()
        self._tx_flash("stop")
        _log.debug("TRANSPORT stop")

    def _tx_rewind(self) -> None:
        self.engine.rewind()
        self._tx_flash("rewind")
        _log.debug("TRANSPORT rewind to 0")

    def _tx_forward(self) -> None:
        self.engine.jump_forward(5.0)
        self._tx_flash("forward")
        _log.debug("TRANSPORT jump_forward 5s")

    def _tx_loop(self) -> None:
        self.engine.toggle_loop()
        self._tx_flash("loop")
        # Repaint LOOP button to indicate state.
        canvas = self._transport_buttons.get("loop")
        if canvas:
            canvas.itemconfigure("glyph", fill="#7cf0a9" if self.engine.loop else "#f0f0f0")
        _log.debug("TRANSPORT loop -> %s", self.engine.loop)

    def _tx_record(self) -> None:
        # Engine doesn't write to disk yet; this is a global "armed" indicator
        # placeholder. Toggling here lights the REC glyph and logs the intent
        # so the disk-recording subsystem can hook in later.
        self._record_armed_global = not getattr(self, "_record_armed_global", False)
        canvas = self._transport_buttons.get("record")
        if canvas:
            canvas.itemconfigure("glyph", fill="#ff2d2d" if self._record_armed_global else "#ff5050")
        self._tx_flash("record")
        _log.debug("TRANSPORT record (TODO: wire disk recorder) -> armed=%s", self._record_armed_global)

    def _tx_undo(self) -> None:
        # No command history yet. Stub for future _undo_stack.
        _log.debug("TRANSPORT undo (TODO: command history not implemented)")
        self._tx_flash("undo")

    def _tx_redo(self) -> None:
        _log.debug("TRANSPORT redo (TODO: command history not implemented)")
        self._tx_flash("redo")

    # New 6x2 grid handlers (placeholder stubs except where wired). All log
    # their press so the surrounding subsystem can hook into the intent.
    def _tx_shuttle(self) -> None:
        """Toggle shuttle mode: coarse PLY twist steps (timeline_jog grows)."""
        self.timeline_shuttle_active = not self.timeline_shuttle_active
        if self.timeline_shuttle_active:
            self.timeline_scrub_active = False
            self.timeline_jog_step = 1.15
        else:
            self.timeline_jog_step = 0.10
        self._tx_flash("shuttle")
        _log.debug("TIMELINE shuttle=%s jog_step=%.3f", self.timeline_shuttle_active, self.timeline_jog_step)

    def _tx_scrub(self) -> None:
        """Toggle scrub mode: fine PLY twist steps."""
        self.timeline_scrub_active = not self.timeline_scrub_active
        if self.timeline_scrub_active:
            self.timeline_shuttle_active = False
            self.timeline_jog_step = 0.04
        else:
            self.timeline_jog_step = 0.10
        self._tx_flash("scrub")
        _log.debug("TIMELINE scrub=%s jog_step=%.3f", self.timeline_scrub_active, self.timeline_jog_step)

    def _generator_select_mode(self, mode: str) -> None:
        """Exclusive monitor source: same key again turns off."""

        with self.engine._lock:
            if self.engine.generator_mode == mode:
                self.engine.generator_mode = "none"
            else:
                self.engine.generator_mode = mode

    def _tx_oscillator(self) -> None:
        self._generator_select_mode("osc")
        self._tx_flash("oscillator")
        self._sync_generator_transport_cells()
        if self.nav_scope == "transport":
            self._redraw_transport_focus()
        self._draw_focus()
        _log.debug("GEN osc -> mode=%s hz=%.2f", self.engine.generator_mode, self.engine.osc_hz)

    def _tx_pink(self) -> None:
        self._generator_select_mode("pink")
        self._tx_flash("pink")
        self._sync_generator_transport_cells()
        if self.nav_scope == "transport":
            self._redraw_transport_focus()
        self._draw_focus()
        _log.debug("GEN pink -> mode=%s", self.engine.generator_mode)

    def _tx_white(self) -> None:
        self._generator_select_mode("white")
        self._tx_flash("white")
        self._sync_generator_transport_cells()
        if self.nav_scope == "transport":
            self._redraw_transport_focus()
        self._draw_focus()
        _log.debug("GEN white -> mode=%s", self.engine.generator_mode)

    def _sync_generator_transport_cells(self) -> None:
        """Outline + fill hints for OSC / PNK / WHT when armed."""

        mapping = (
            ("oscillator", "osc", "#f0c6ff"),
            ("pink", "pink", "#f472c0"),
            ("white", "white", "#a8d8ff"),
        )
        for key, mode, glyph_col in mapping:
            cv = self._transport_buttons.get(key)
            if not cv:
                continue
            try:
                on = self.engine.generator_mode == mode
                cv.configure(bg="#2d1f3d" if on else "#15202c")
                cv.itemconfigure("glyph", fill="#fef3c7" if on else glyph_col)
            except tk.TclError:
                pass

    def _adjust_oscillator_frequency(self, axis_value: float) -> None:
        if abs(axis_value) < 0.012:
            return
        if self.engine.generator_mode != "osc":
            return
        with self.engine._lock:
            hz = float(self.engine.osc_hz) * (1.048 ** (axis_value * 4.5))
            self.engine.osc_hz = float(np.clip(hz, POL_LOW_HZ, POL_HIGH_HZ))

    def _osc_step_polar_band(self, delta: int) -> None:
        """Discrete SpaceMouse notch: snap ``osc_hz`` to the analyzer band ring before/after the nearest one."""

        if self.engine.generator_mode != "osc":
            return
        with self.engine._lock:
            hz = float(np.clip(float(self.engine.osc_hz), POL_LOW_HZ, POL_HIGH_HZ))
            cents = POL_BAND_CENTER_HZ
            i = int(np.argmin(np.abs(cents - hz)))
            i = (i + int(delta)) % POL_BANDS
            self.engine.osc_hz = float(cents[i])

    def _tx_read(self) -> None:
        _log.debug("TRANSPORT automation READ")
        self._tx_flash("read")

    def _tx_write(self) -> None:
        _log.debug("TRANSPORT automation WRITE")
        self._tx_flash("write")

    def _tx_trim(self) -> None:
        _log.debug("TRANSPORT automation TRIM")
        self._tx_flash("trim")

    def _tx_latch(self) -> None:
        _log.debug("TRANSPORT automation LATCH")
        self._tx_flash("latch")

    def _init_editor_state_vars(self) -> None:
        self.pre_vars = {
            "enabled": tk.BooleanVar(),
            "phase": tk.BooleanVar(),
            "tube": tk.BooleanVar(),
            "lpf_enabled": tk.BooleanVar(),
            "hpf_enabled": tk.BooleanVar(),
            "gain": tk.DoubleVar(),
            "pan": tk.DoubleVar(),
            "lpf_hz": tk.DoubleVar(),
            "hpf_hz": tk.DoubleVar(),
        }
        self.harm_vars = {"enabled": tk.BooleanVar(), "makeup": tk.DoubleVar()}
        self.harm_weight_vars = [tk.DoubleVar() for _ in range(5)]
        self.comp_vars = {
            "enabled": tk.BooleanVar(),
            "threshold": tk.DoubleVar(),
            "ratio": tk.DoubleVar(),
            "attack": tk.DoubleVar(),
            "release": tk.DoubleVar(),
            "makeup": tk.DoubleVar(),
        }
        self.eq_vars = {
            "enabled": tk.BooleanVar(),
            "freq": tk.DoubleVar(),
            "gain": tk.DoubleVar(),
            "width": tk.DoubleVar(),
        }
        self.tone_vars = {
            "enabled": tk.BooleanVar(),
            "trn_attack": tk.DoubleVar(),
            "trn_sustain": tk.DoubleVar(),
            "clr_drive": tk.DoubleVar(),
            "xct_amount": tk.DoubleVar(),
        }

    def _section(self, parent: tk.Frame, title: str) -> tk.LabelFrame:
        sec = tk.LabelFrame(parent, text=title, bg="#161b22", fg="#d6deea", bd=1, relief="solid", labelanchor="nw")
        sec.pack(fill="x", padx=12, pady=8)
        return sec

    def _scale(self, parent: tk.Widget, label: str, from_, to, var: tk.DoubleVar, command, resolution=0.01):
        row = tk.Frame(parent, bg="#161b22")
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text=label, bg="#161b22", fg="#b8c4d0", width=11, anchor="w").pack(side="left")
        tk.Scale(
            row,
            from_=from_,
            to=to,
            orient="horizontal",
            resolution=resolution,
            variable=var,
            command=command,
            bg="#161b22",
            fg="#d8e0ea",
            troughcolor="#28313b",
            highlightthickness=0,
            length=220,
        ).pack(side="right", fill="x", expand=True)

    def _check(self, parent: tk.Widget, label: str, var: tk.BooleanVar, command):
        tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            command=command,
            bg="#161b22",
            fg="#dde6ef",
            selectcolor="#2b3540",
            activebackground="#161b22",
            activeforeground="#dde6ef",
        ).pack(anchor="w", padx=10, pady=3)

    def _build_pre_tab(self, tab: tk.Frame) -> None:
        self.pre_vars = {
            "enabled": tk.BooleanVar(),
            "phase": tk.BooleanVar(),
            "tube": tk.BooleanVar(),
            "lpf_enabled": tk.BooleanVar(),
            "hpf_enabled": tk.BooleanVar(),
            "gain": tk.DoubleVar(),
            "pan": tk.DoubleVar(),
            "lpf_hz": tk.DoubleVar(),
            "hpf_hz": tk.DoubleVar(),
        }
        sec = self._section(tab, "Mic Pre")
        self._check(sec, "Mic Pre Enabled", self.pre_vars["enabled"], self._commit_pre)
        self._check(sec, "Phase", self.pre_vars["phase"], self._commit_pre)
        self._check(sec, "Tube", self.pre_vars["tube"], self._commit_pre)
        self._check(sec, "LPF", self.pre_vars["lpf_enabled"], self._commit_pre)
        self._check(sec, "HPF", self.pre_vars["hpf_enabled"], self._commit_pre)
        self._scale(sec, "Gain", 0.0, 2.5, self.pre_vars["gain"], lambda _=None: self._commit_pre())
        self._scale(sec, "Pan", -1.0, 1.0, self.pre_vars["pan"], lambda _=None: self._commit_pre())
        self._scale(sec, "LPF Hz", POL_LOW_HZ, 1200.0, self.pre_vars["lpf_hz"], lambda _=None: self._commit_pre(), resolution=1.0)
        self._scale(sec, "HPF Hz", 4000.0, POL_HIGH_HZ, self.pre_vars["hpf_hz"], lambda _=None: self._commit_pre(), resolution=1.0)

    def _build_harm_tab(self, tab: tk.Frame) -> None:
        self.harm_vars = {"enabled": tk.BooleanVar(), "makeup": tk.DoubleVar()}
        self.harm_weight_vars = [tk.DoubleVar() for _ in range(5)]
        sec = self._section(tab, "Harmonics H2-H6")
        self._check(sec, "Enabled", self.harm_vars["enabled"], self._commit_harm)
        for idx, var in enumerate(self.harm_weight_vars, start=2):
            self._scale(sec, f"H{idx}", 0.0, 1.0, var, lambda _=None: self._commit_harm())
        self._scale(sec, "Makeup", 0.6, 2.4, self.harm_vars["makeup"], lambda _=None: self._commit_harm())

    def _build_comp_tab(self, tab: tk.Frame) -> None:
        self.comp_vars = {
            "enabled": tk.BooleanVar(),
            "threshold": tk.DoubleVar(),
            "ratio": tk.DoubleVar(),
            "attack": tk.DoubleVar(),
            "release": tk.DoubleVar(),
            "makeup": tk.DoubleVar(),
        }
        sec = self._section(tab, "Compressor")
        self._check(sec, "Enabled", self.comp_vars["enabled"], self._commit_comp)
        self._scale(sec, "Threshold", POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER, self.comp_vars["threshold"], lambda _=None: self._commit_comp(), resolution=0.5)
        self._scale(sec, "Ratio", 1.0, 20.0, self.comp_vars["ratio"], lambda _=None: self._commit_comp(), resolution=0.1)
        self._scale(sec, "Attack", 0.8, 60.0, self.comp_vars["attack"], lambda _=None: self._commit_comp(), resolution=0.1)
        self._scale(sec, "Release", 20.0, 400.0, self.comp_vars["release"], lambda _=None: self._commit_comp(), resolution=1.0)
        self._scale(sec, "Makeup", 0.6, 2.2, self.comp_vars["makeup"], lambda _=None: self._commit_comp(), resolution=0.01)

    def _build_eq_tab(self, tab: tk.Frame) -> None:
        self.eq_vars = {
            "enabled": tk.BooleanVar(),
            "freq": tk.DoubleVar(),
            "gain": tk.DoubleVar(),
            "width": tk.DoubleVar(),
        }
        sec = self._section(tab, "Bell EQ")
        self._check(sec, "Enabled", self.eq_vars["enabled"], self._commit_eq)
        self._scale(sec, "Freq", 80.0, 12000.0, self.eq_vars["freq"], lambda _=None: self._commit_eq(), resolution=1.0)
        self._scale(sec, "Gain", -18.0, 18.0, self.eq_vars["gain"], lambda _=None: self._commit_eq(), resolution=0.1)
        self._scale(sec, "Width", 0.2, 4.0, self.eq_vars["width"], lambda _=None: self._commit_eq(), resolution=0.01)

    def _build_tone_tab(self, tab: tk.Frame) -> None:
        self.tone_vars = {
            "enabled": tk.BooleanVar(),
            "trn_attack": tk.DoubleVar(),
            "trn_sustain": tk.DoubleVar(),
            "clr_drive": tk.DoubleVar(),
            "xct_amount": tk.DoubleVar(),
        }
        sec = self._section(tab, "Transient / Color / Exciter")
        self._check(sec, "Enabled", self.tone_vars["enabled"], self._commit_tone)
        self._scale(sec, "TRN Attack", 0.0, 1.0, self.tone_vars["trn_attack"], lambda _=None: self._commit_tone())
        self._scale(sec, "TRN Sustain", 0.0, 1.0, self.tone_vars["trn_sustain"], lambda _=None: self._commit_tone())
        self._scale(sec, "Color Drive", 0.0, 1.0, self.tone_vars["clr_drive"], lambda _=None: self._commit_tone())
        self._scale(sec, "Exciter", 0.0, 1.0, self.tone_vars["xct_amount"], lambda _=None: self._commit_tone())

    def _active_channel_index(self) -> int:
        return self.editor_channel if self.nav_scope == "editor" else self.selected_channel

    def _current_channel(self) -> ChannelState:
        active_channel = self._active_channel_index()
        if active_channel >= len(self.engine.channels):
            return self.engine.master_channel
        return self.engine.channels[active_channel]

    def _console_stage_keys(self, channel_index: int | None = None) -> list[str]:
        idx = self._active_channel_index() if channel_index is None else channel_index
        if idx >= len(self.engine.channels):
            return ["harm", "gate", "comp", "eq", "tone"]
        return ["pre", "harm", "gate", "comp", "eq", "tone"]

    def _channel_nav_span(self) -> int:
        """Strip indices for left/right / CH paging: inputs + Master, except PRE (mic pre is inputs only)."""
        n = len(self.engine.channels)
        if self.selected_stage_key == "pre":
            return max(1, n)
        return n + 1

    def _clamp_pre_to_inputs(self) -> None:
        """PRE is only meaningful on input strips; never pair it with Master index."""
        n = len(self.engine.channels)
        if n <= 0 or self.selected_stage_key != "pre":
            return
        if self.nav_scope == "editor":
            if self.editor_channel >= n:
                self.editor_channel = n - 1
        else:
            if self.selected_channel >= n:
                self.selected_channel = n - 1

    def _normalize_stage_selection(self, channel_index: int) -> None:
        if self.nav_scope == "console" and self.console_row in ("footer", "record", "knob", "fader"):
            return
        stage_keys = self._console_stage_keys(channel_index)
        prev_stage = self.selected_stage_key
        # Mic-pre layout is only for input strips. If we were on PRE and switch to a bus
        # with no PRE (e.g. Master), stage remaps to HAR — but module_editor_column
        # often stays 0 (CH / CH VOL), which looks like focus "rolled to the fader".
        # That happens especially when paging channels from the CH knob (pre_editor_column 0),
        # not only when the stage column had keyboard focus (pre_editor_column 1).
        if self.selected_stage_key not in stage_keys:
            self.selected_stage_key = stage_keys[0]
        if (
            self.nav_scope == "editor"
            and prev_stage == "pre"
            and self.selected_stage_key != "pre"
        ):
            self.module_editor_column = 1
            if self.selected_stage_key in stage_keys:
                self.module_editor_positions["stage"] = stage_keys.index(self.selected_stage_key)
            # The canvas only paints the unified grid; module-stage + PRESS would toggle
            # coarse *_enabled (strip-style) instead of per-cell bypass.
            unify_ix = {row[0]: ri for ri, row in enumerate(self._STAGE_GRID)}
            sk = self.selected_stage_key
            if sk in unify_ix:
                icol = unify_ix[sk]
                self.editor_nav_scope = "stage_grid"
                self.editor_unified_header_focus = False
                self.editor_stage_col = icol
                plist = self._STAGE_GRID[icol][2]
                if plist:
                    self.editor_param_row = self._unified_pick_param_row_entering_stage(
                        icol, int(getattr(self, "editor_param_row", 0)), neighbor_row_priority=False
                    )
            else:
                self.editor_nav_scope = "module-stage"
        if self.selected_stage_key == "eq":
            ch = self.engine.master_channel if channel_index >= len(self.engine.channels) else self.engine.channels[channel_index]
            self.eq_selected_band = min(self.eq_selected_band, max(0, ch.eq_band_count - 1))

    def _eq_band(self, ch: ChannelState, idx: int | None = None) -> dict:
        band_idx = self.eq_selected_band if idx is None else idx
        band_idx = max(0, min(7, band_idx))
        while len(ch.eq_bands) < 8:
            ch.eq_bands.append({"enabled": False, "freq": 2200.0, "gain_db": 0.0, "width": 1.4, "type": "BELL", "band_enabled": False})
        return ch.eq_bands[band_idx]

    def _prime_eq_minimum_multiband(self, ch: ChannelState) -> None:
        """First multiband entry: guarantee ≥2 tiers so twist‑BND can rotate."""

        ch.eq_band_enabled = True
        ch.eq_band_count = max(int(ch.eq_band_count), 2)
        self.eq_selected_band = 0
        nb = self._eq_band(ch, 0)
        nb["freq"] = float(ch.eq_freq)
        nb["gain_db"] = float(ch.eq_gain_db)
        nb["width"] = float(ch.eq_width)
        nb["type"] = str(ch.eq_type)
        if abs(float(nb.get("gain_db", 0.0))) < 0.08:
            nb["gain_db"] = 4.0
        nb["enabled"] = True
        nb2 = self._eq_band(ch, 1)
        fq0 = float(nb["freq"])
        nb2["freq"] = float(
            np.clip(
                fq0 * 3.08 if fq0 < 950.0 else fq0 / 2.74,
                POL_LOW_HZ * 4.5,
                POL_HIGH_HZ * 0.85,
            )
        )
        nb2["width"] = float(max(0.25, min(float(nb["width"]) * 0.94, 4.8)))
        nb2["type"] = str(ch.eq_type)
        nb2["gain_db"] = float(np.clip(-3.9, -18.0, 18.0))
        nb2["enabled"] = True
        ch.eq_enabled = True
        self._sync_scalar_display_from_eq_band(ch)

    def _normalize_console_selection(self) -> None:
        self._normalize_stage_selection(self.selected_channel)

    def _mirror_eq_ui_band_to_channel(self, ch: ChannelState) -> None:
        """Keep DSP/preview band index aligned with BND selection (multiband width bypass)."""
        if not getattr(ch, "eq_band_enabled", False):
            return
        with self.engine._lock:
            n = max(1, int(ch.eq_band_count))
            ch.eq_ui_band = max(0, min(n - 1, int(getattr(self, "eq_selected_band", 0))))

    def _sync_from_engine(self) -> None:
        self._syncing_controls = True
        try:
            self._clamp_pre_to_inputs()
            self._normalize_stage_selection(self._active_channel_index())
            self._normalize_module_editor_positions()
            if self.nav_scope == "editor":
                self._coerce_editor_nav_to_unified_stage_grid()
            ch = self._current_channel()
            self.editor_title.config(
                text=(
                    f"{ch.name}  ·  {self._stage_label(self.selected_stage_key)}"
                    if self.selected_stage_key != "eq"
                    else f"{ch.name}  ·  EQ"
                )
            )
            active_channel = self._active_channel_index()
            # Subtitle stays packed from `_build_ui`; EQ vs other stages only change text —
            # never `pack_forget` (that was shifting the polar + grid vertically).
            if active_channel >= len(self.engine.channels):
                sub = "MASTER BUS"
            else:
                sub = f"{active_channel + 1:02d}  {ch.path.name}"
            self.editor_subtitle.config(text=sub)
            self.pre_vars["enabled"].set(ch.pre_enabled)
            self.pre_vars["phase"].set(ch.phase)
            self.pre_vars["tube"].set(ch.tube)
            self.pre_vars["lpf_enabled"].set(ch.lpf_enabled)
            self.pre_vars["hpf_enabled"].set(ch.hpf_enabled)
            self.pre_vars["gain"].set(ch.gain)
            self.pre_vars["pan"].set(ch.pan)
            self.pre_vars["lpf_hz"].set(ch.lpf_hz)
            self.pre_vars["hpf_hz"].set(ch.hpf_hz)
            self.harm_vars["enabled"].set(ch.harmonics_enabled)
            self.harm_vars["makeup"].set(ch.harmonic_makeup)
            for var, weight in zip(self.harm_weight_vars, ch.harmonics):
                var.set(float(weight))
            self.comp_vars["enabled"].set(ch.comp_enabled)
            self.comp_vars["threshold"].set(
                float(np.clip(ch.comp_threshold_db, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER))
            )
            self.comp_vars["ratio"].set(ch.comp_ratio)
            self.comp_vars["attack"].set(ch.comp_attack_ms)
            self.comp_vars["release"].set(ch.comp_release_ms)
            self.comp_vars["makeup"].set(ch.comp_makeup)
            eq_band = self._eq_band(ch)
            self.eq_vars["enabled"].set(ch.eq_enabled)
            self.eq_vars["freq"].set(float(eq_band["freq"]) if ch.eq_band_enabled else float(ch.eq_freq))
            self.eq_vars["gain"].set(float(eq_band["gain_db"]) if ch.eq_band_enabled else float(ch.eq_gain_db))
            self.eq_vars["width"].set(float(eq_band["width"]) if ch.eq_band_enabled else float(ch.eq_width))
            self._mirror_eq_ui_band_to_channel(ch)
            self.tone_vars["enabled"].set(ch.tone_enabled)
            self.tone_vars["trn_attack"].set(ch.trn_attack)
            self.tone_vars["trn_sustain"].set(ch.trn_sustain)
            self.tone_vars["clr_drive"].set(ch.clr_drive)
            self.tone_vars["xct_amount"].set(ch.xct_amount)
            self._draw_strips()
            self._draw_focus()
            self._draw_editor_controls()
        except Exception:
            self._syncing_controls = False
            raise
        self.root.after_idle(self._end_control_sync)

    def _end_control_sync(self) -> None:
        self._syncing_controls = False

    def _stage_label(self, key: str) -> str:
        return {
            "pre": "Mic Pre",
            "harm": "Harmonics",
            "gate": "Gate",
            "comp": "Compressor",
            "eq": "EQ",
            "tone": "TRN / CLR / XCT",
        }[key]

    def _commit_pre(self) -> None:
        if self._syncing_controls:
            return
        ch = self._current_channel()
        with self.engine._lock:
            ch.pre_enabled = self.pre_vars["enabled"].get()
            ch.phase = self.pre_vars["phase"].get()
            ch.tube = self.pre_vars["tube"].get()
            ch.lpf_enabled = self.pre_vars["lpf_enabled"].get()
            ch.hpf_enabled = self.pre_vars["hpf_enabled"].get()
            ch.gain = self.pre_vars["gain"].get()
            ch.pan = self.pre_vars["pan"].get()
            ch.lpf_hz = max(POL_LOW_HZ, self.pre_vars["lpf_hz"].get())
            ch.hpf_hz = min(POL_HIGH_HZ, self.pre_vars["hpf_hz"].get())
        self._propagate_strip_link_from_editor_channel()
        self._draw_strips()

    def _commit_harm(self) -> None:
        if self._syncing_controls:
            return
        ch = self._current_channel()
        with self.engine._lock:
            ch.harmonics_enabled = self.harm_vars["enabled"].get()
            ch.harmonic_makeup = self.harm_vars["makeup"].get()
            ch.harmonics = np.array([v.get() for v in self.harm_weight_vars], dtype=np.float32)
        self._propagate_strip_link_from_editor_channel()
        self._draw_strips()

    def _commit_comp(self) -> None:
        if self._syncing_controls:
            return
        ch = self._current_channel()
        with self.engine._lock:
            ch.comp_enabled = self.comp_vars["enabled"].get()
            ch.comp_threshold_db = float(
                np.clip(self.comp_vars["threshold"].get(), POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER)
            )
            ch.comp_ratio = self.comp_vars["ratio"].get()
            ch.comp_attack_ms = self.comp_vars["attack"].get()
            ch.comp_release_ms = self.comp_vars["release"].get()
            ch.comp_makeup = self.comp_vars["makeup"].get()
        self._propagate_strip_link_from_editor_channel()
        self._draw_strips()

    def _commit_eq(self) -> None:
        if self._syncing_controls:
            return
        ch = self._current_channel()
        with self.engine._lock:
            en = bool(self.eq_vars["enabled"].get())
            ch.eq_enabled = en
            if ch.eq_band_enabled:
                band = self._eq_band(ch)
                band["enabled"] = en
                band["freq"] = self.eq_vars["freq"].get()
                band["gain_db"] = self.eq_vars["gain"].get()
                band["width"] = self.eq_vars["width"].get()
                self._sync_scalar_display_from_eq_band(ch)
            else:
                ch.eq_freq = self.eq_vars["freq"].get()
                ch.eq_gain_db = self.eq_vars["gain"].get()
                ch.eq_width = self.eq_vars["width"].get()
                band = self._eq_band(ch)
                band["freq"] = float(ch.eq_freq)
                band["gain_db"] = float(ch.eq_gain_db)
                band["width"] = float(ch.eq_width)
                band["enabled"] = en
        self._propagate_strip_link_from_editor_channel()
        self._draw_strips()

    def _commit_tone(self) -> None:
        if self._syncing_controls:
            return
        ch = self._current_channel()
        with self.engine._lock:
            ch.tone_enabled = self.tone_vars["enabled"].get()
            ch.trn_attack = self.tone_vars["trn_attack"].get()
            ch.trn_sustain = self.tone_vars["trn_sustain"].get()
            ch.clr_drive = self.tone_vars["clr_drive"].get()
            ch.xct_amount = self.tone_vars["xct_amount"].get()
        self._propagate_strip_link_from_editor_channel()
        self._draw_strips()

    def _draw_master_meter(self) -> None:
        self.master_meter.delete("all")
        width = 360
        height = 18
        level = float(np.clip(self.engine.master_level, 0.0, 1.0))
        self.master_meter.create_rectangle(0, 0, width, height, fill="#232a33", outline="#2f3944")
        fill = width * level
        color = "#6ff0c1" if level < 0.66 else "#f6c06f" if level < 0.9 else "#ff6a53"
        self.master_meter.create_rectangle(0, 0, fill, height, fill=color, outline="")

    def _draw_focus(self) -> None:
        self._draw_focus_to(self.focus_canvas)

    def _draw_focus_to(self, c: tk.Canvas) -> None:
        c.delete("all")
        width = max(c.winfo_width(), 380)
        height = max(c.winfo_height(), 250)
        gm = getattr(self.engine, "generator_mode", "none")
        c.create_rectangle(0, 0, width, height, fill="#10151b", outline="")
        # One pulse sample per polar paint — spectrum + overlays share the same smoothed loudness lift.
        self._pol_pulse_cached = self._output_polar_pulse()
        ch = self._current_channel()
        if self.selected_stage_key == "pre":
            self._draw_focus_mic_pre(c, ch, width, height)
        elif self.selected_stage_key == "harm":
            self._draw_focus_harmonics(c, ch, width, height)
        elif self.selected_stage_key == "gate":
            self._draw_focus_gate(c, ch, width, height)
        elif self.selected_stage_key == "comp":
            self._draw_focus_compressor(c, ch, width, height)
        elif self.selected_stage_key == "eq":
            self._draw_focus_eq(c, ch, width, height)
        elif self.selected_stage_key == "tone":
            self._draw_focus_tone(c, ch, width, height)
        # Generator-mode polar decorations must not leak onto a bypassed insert's pane.
        # EQ focus with ``eq_enabled`` False already skips all EQ shells; without this guard OSC/PNK/WHT rings still drew on empty dark paint.
        show_gen_polar = True
        if ch is not None and self.selected_stage_key == "eq" and not ch.eq_enabled:
            show_gen_polar = False
        if show_gen_polar:
            if gm == "osc":
                self._draw_oscillator_polar_overlay(c, width, height)
            elif gm in ("pink", "white"):
                self._draw_noise_theory_polar_overlay(c, width, height, gm)

    def _draw_oscillator_polar_overlay(self, c: tk.Canvas, width: int, height: int) -> None:
        """When OSC is armed: bright ring + label at ``osc_hz`` on top of PRE/EQ/… polar view."""

        hz = float(np.clip(float(getattr(self.engine, "osc_hz", 440.0)), POL_LOW_HZ, POL_HIGH_HZ))
        cx_f, cy_f, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(width, height)
        cx_i = int(cx_f)
        cy_i = int(cy_f)
        band_pos = self._freq_to_slider(hz)
        rx = outer_rx - (outer_rx - inner_rx) * band_pos
        ry = outer_ry - (outer_ry - inner_ry) * band_pos
        hue = freq_rainbow_hue_hz(hz)
        pulse = float(getattr(self, "_pol_pulse_cached", 0.0))
        v_ring = float(np.clip(0.78 + pulse * 0.22, 0.72, 0.995))
        v_soft = float(np.clip(0.14 + pulse * 0.22, 0.12, 0.52))
        col = hsv_to_hex(hue, 0.88, v_ring)
        col_soft = hsv_to_hex(hue, 0.38, v_soft)
        ow = max(6, int(8 + pulse * 7))
        iw = max(4, int(5 + pulse * 4))
        c.create_oval(cx_i - rx - 5, cy_i - ry - 5, cx_i + rx + 5, cy_i + ry + 5, outline=col_soft, width=int(ow + 3))
        c.create_oval(cx_i - rx, cy_i - ry, cx_i + rx, cy_i + ry, outline=col, width=iw)
        label = f"OSC · {hz / 1000:.2f} kHz" if hz >= 1000.0 else f"OSC · {hz:.1f} Hz"
        c.create_text(14, height - 12, anchor="sw", text=label, fill=col, font=("Segoe UI", 11, "bold"))

    def _draw_noise_theory_polar_overlay(self, c: tk.Canvas, width: int, height: int, mode: str) -> None:
        """Pink / white armed: idealized PSD on the SAME log polar map as mic/tone OSC ring — not a second graphic."""

        if mode not in ("pink", "white"):
            return
        cx_f, cy_f, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(width, height)
        cx_i = int(cx_f)
        cy_i = int(cy_f)
        centers = POL_BAND_CENTER_HZ
        if mode == "white":
            raw = np.sqrt(np.clip(centers.astype(np.float64) / float(POL_LOW_HZ), 0.2, 80.0))
        else:
            raw = np.ones(POL_BANDS, dtype=np.float64)
        raw = raw / max(float(np.max(raw)), 1e-9)
        pulse = float(getattr(self, "_pol_pulse_cached", 0.0))
        lvl = float(np.clip(0.44 + pulse * 0.88, 0.35, 1.45))

        for i in range(POL_BANDS):
            amt = float(raw[i])
            mix = i / max(1, POL_BANDS - 1)
            rx = outer_rx - (outer_rx - inner_rx) * mix
            ry = outer_ry - (outer_ry - inner_ry) * mix
            band_hz = float(centers[i])
            hue = freq_rainbow_hue_hz(band_hz)
            sat = float(np.clip(0.88 * (0.42 + amt * 0.58), 0.35, 0.93))
            v_hi = float(np.clip((0.11 + amt * 0.80) * (0.52 + lvl * 0.38), 0.13, 0.96))
            color = hsv_to_hex(hue, sat, v_hi)
            lw = max(2, int((1.4 + amt * 5.0) * (0.68 + pulse * 0.52)))
            c.create_oval(cx_i - rx, cy_i - ry, cx_i + rx, cy_i + ry, outline=color, width=lw)
            if amt > 0.55:
                glow = hsv_to_hex(hue, 0.32, 0.10 + amt * 0.28)
                c.create_oval(cx_i - rx - 1.2, cy_i - ry - 1.2, cx_i + rx + 1.2, cy_i + ry + 1.2, outline=glow, width=1)

        lbl = (
            "PNK · octave-flat ideal ( PSD ∝ 1/f )"
            if mode == "pink"
            else "WHT · √f ideal in log bins ( PSD flat )"
        )
        tint = "#f472c0" if mode == "pink" else "#7dd3fc"
        c.create_text(14, height - 12, anchor="sw", text=lbl, fill=tint, font=("Segoe UI", 11, "bold"))

    def _draw_editor_controls(self) -> None:
        self._autosize_editor_canvas_height()
        # editor_canvas is now packed BOTTOM with a fixed height; focus_canvas
        # is packed TOP with expand=True so it absorbs all remaining vertical
        # space. We don't override the configured heights here.
        self.fader_canvas.delete("all")
        self._draw_editor_controls_to(self.editor_canvas, preview_only=False)

    def _editor_utility_items(self) -> list[tuple[str, str, bool]]:
        ch = self._current_channel()
        channel_value = "MST" if self._active_channel_index() >= len(self.engine.channels) else f"{self._active_channel_index() + 1:02d}"
        return [
            ("CH", channel_value, True),
            ("SND", f"{int(ch.send_slot)}", True),
            ("SOL", "", ch.solo),
            ("MUT", "", ch.mute),
        ]

    def _draw_editor_faders(self) -> None:
        c = self.fader_canvas
        c.delete("all")
        w = max(c.winfo_width(), 380)
        h = max(c.winfo_height(), 86)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        active = self.editor_nav_scope == "faders"
        c.create_rectangle(14, 10, w - 14, h - 10, outline="#41505f" if active else "#1d252d", width=1, fill="#151d25" if active else "")
        if active:
            c.create_rectangle(16, 12, 20, h - 12, outline="", fill="#6a7886")
        ch = self._current_channel()
        left_x0 = 42
        left_x1 = w * 0.5 - 18
        right_x0 = w * 0.5 + 18
        right_x1 = w - 42
        self._draw_horizontal_fader(c, left_x0, 24, left_x1, 62, ch.gain, 0.3, 2.2, "CH VOL", f"{ch.gain:.2f}x", active and self.editor_fader_selected == 0)
        self._draw_horizontal_fader(c, right_x0, 24, right_x1, 62, ch.send_level, 0.0, 1.0, f"SEND {int(ch.send_slot)}", f"{ch.send_level:.2f}", active and self.editor_fader_selected == 1)
        self.fader_hitboxes = [
            (left_x0, 18, left_x1, 68, 0),
            (right_x0, 18, right_x1, 68, 1),
        ]

    def _draw_horizontal_fader(self, c: tk.Canvas, x0: float, y0: float, x1: float, y1: float, value: float, min_value: float, max_value: float, label: str, value_text: str, selected: bool) -> None:
        c.create_text(x0, y0 - 8, text=label, fill="#cfd9e3", font=("Segoe UI", 8, "bold"), anchor="w")
        c.create_text(x1, y0 - 8, text=value_text, fill="#89a0b6", font=("Segoe UI", 8, "bold"), anchor="e")
        cy = (y0 + y1) / 2
        c.create_line(x0, cy, x1, cy, fill="#2b3743", width=4)
        c.create_rectangle(x0, cy - 8, x1, cy + 8, fill="#131920", outline="#31404e", width=1)
        norm = 0.0 if max_value <= min_value else max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))
        knob_x = x0 + (x1 - x0) * norm
        if selected:
            c.create_rectangle(knob_x - 14, cy - 14, knob_x + 14, cy + 14, outline="#8b96a3", width=2, fill="#1b232c")
            c.create_rectangle(knob_x - 16, cy - 16, knob_x + 16, cy + 16, outline="#465362", width=1)
        else:
            c.create_rectangle(knob_x - 12, cy - 12, knob_x + 12, cy + 12, outline="#31404e", width=1, fill="#161d25")
        c.create_line(knob_x, cy - 8, knob_x, cy + 8, fill="#5ef0b0", width=2)

    def _tone_body_items(self, ch: ChannelState | None = None, mode: str | None = None) -> list[tuple[str, str, bool]]:
        ch = ch or self._current_channel()
        mode = mode or self.tone_editor_mode
        if mode == "TRN":
            return [
                ("FREQ", f"{ch.trn_freq:.0f}Hz", ch.trn_band_enabled),
                ("WIDTH", f"{ch.trn_width:.2f}oct", ch.trn_band_enabled),
                ("ATTACK", f"{ch.trn_attack:.2f}", ch.trn_attack > 0.02),
                ("SUSTAIN", f"{ch.trn_sustain:.2f}", ch.trn_sustain > 0.02),
            ]
        if mode == "CLR":
            return [
                ("DRIVE", f"{ch.clr_drive:.2f}", ch.clr_drive > 0.02),
                ("TONE", f"{ch.clr_tone:+.2f}", abs(ch.clr_tone) > 0.02),
                ("MIX", f"{ch.clr_mix:.2f}", abs(ch.clr_mix - 0.55) > 0.02),
                ("GAIN", f"{ch.clr_gain:.2f}x", abs(ch.clr_gain - 1.0) > 0.02),
            ]
        return [
            ("FREQ", f"{ch.xct_freq:.0f}Hz", ch.xct_band_enabled),
            ("WIDTH", f"{ch.xct_width:.2f}oct", ch.xct_band_enabled),
            ("AMOUNT", f"{ch.xct_amount:.2f}", ch.xct_amount > 0.02),
            ("MIX", f"{ch.xct_mix:.2f}", abs(ch.xct_mix - 0.45) > 0.02),
        ]

    def _draw_editor_controls_to(self, c: tk.Canvas, preview_only: bool) -> None:
        c.delete("all")
        w = max(c.winfo_width(), 380)
        h = max(c.winfo_height(), 340 if not preview_only else 250)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        if not preview_only:
            self.editor_hitboxes = []
        ch = self._current_channel()
        stage_key = self.selected_stage_key
        selected_idx = self.editor_selected.get(stage_key, 0)
        channel_nav_y = 18 if not preview_only else 16
        util_y = 44 if not preview_only else 38
        stage_nav_y = 108 if not preview_only else 90
        top_y = 174 if preview_only else 174
        bottom_y = h - (58 if preview_only else 74)
        stage_keys = self._console_stage_keys()
        stage_label_map = {
            "pre": "PRE",
            "harm": "HAR",
            "comp": "CMP",
            "eq": "EQ",
            "tone": "FX",
        }
        utility_items = self._editor_utility_items()
        utility_selected = self.editor_utility_selected if self.editor_nav_scope == "utility" else -1
        stage_selected = stage_keys.index(stage_key) if self.editor_nav_scope == "stage" else -1
        body_selected = selected_idx if self.editor_nav_scope == "body" else -1
        if not preview_only:
            # Unified all-stages grid: 6 stage columns (PRE/HRM/GTE/CMP/EQ/TON)
            # rendered side-by-side, one cell per Google-Sheet entry. Replaces
            # the old "pick one stage, render its body" mode.
            self._draw_unified_editor(c, w, h, ch)
            return
        if not preview_only:
            row_specs: list[tuple[float, float, str]] = []
            row_specs.append((util_y - 22, util_y + 34, "utility"))
            row_specs.append((stage_nav_y - 24, stage_nav_y + 40, "stage"))
            if stage_key == "comp":
                row_specs.append((top_y - 24, top_y + 40, "comp-top"))
            elif stage_key == "eq":
                row_specs.append((top_y - 24, top_y + 48, "eq-top"))
            elif stage_key == "tone":
                row_specs.append((top_y - 24, top_y + 40, "tone-top"))
            row_specs.append((bottom_y - 24, bottom_y + 64, "body"))

            active_row = "body"
            if self.editor_nav_scope == "utility":
                active_row = "utility"
            elif self.editor_nav_scope == "stage":
                active_row = "stage"
            elif self.editor_nav_scope == "comp-top":
                active_row = "comp-top"
            elif self.editor_nav_scope == "eq-top":
                active_row = "eq-top"
            elif self.editor_nav_scope == "tone-top":
                active_row = "tone-top"

            for y0, y1, row_name in row_specs:
                is_active = row_name == active_row
                c.create_rectangle(
                    14,
                    y0,
                    w - 14,
                    y1,
                    outline="#41505f" if is_active else "#1d252d",
                    width=1,
                    fill="#151d25" if is_active else "",
                )
                if is_active:
                    c.create_rectangle(16, y0 + 2, 20, y1 - 2, outline="", fill="#6a7886")
        # Inline SOLO/MUTE/REC row removed -- those controls now live in the
        # editor's right (SENDS-replacement) column as a vertical button stack.
        self._draw_badge_row(c, w, util_y, utility_items, utility_selected, preview_only)
        stage_items = [(stage_label_map[key], "", True) for key in stage_keys]
        self._draw_icon_row(
            c,
            w,
            stage_nav_y,
            stage_items,
            stage_selected,
            "stage-top",
            preview_only,
        )
        if stage_key == "pre":
            items = [("LPF", f"{ch.lpf_hz:.0f}", ch.lpf_enabled), ("48V", "", ch.phantom), ("PHS", "", ch.phase), ("TBE", "", ch.tube), ("HPF", f"{ch.hpf_hz:.0f}", ch.hpf_enabled)]
            self._draw_icon_row(c, w, bottom_y, items, body_selected, stage_key, preview_only)
        elif stage_key == "harm":
            items = [
                ("H2", f"{ch.harmonics[0]:.2f}", ch.harmonics[0] > 0.001),
                ("H3", f"{ch.harmonics[1]:.2f}", ch.harmonics[1] > 0.001),
                ("H4", f"{ch.harmonics[2]:.2f}", ch.harmonics[2] > 0.001),
                ("H5", f"{ch.harmonics[3]:.2f}", ch.harmonics[3] > 0.001),
                ("H6", f"{ch.harmonics[4]:.2f}", ch.harmonics[4] > 0.001),
                ("MAKE", f"{ch.harmonic_makeup:.2f}x", abs(ch.harmonic_makeup - 1.0) > 0.01),
            ]
            self._draw_icon_row(c, w, bottom_y, items, body_selected, stage_key, preview_only)
        elif stage_key == "comp":
            top_items = [("COMP", "", ch.comp_enabled), ("LIMIT", "", ch.limit_enabled), ("GATE", "", ch.gate_enabled)]
            comp_top_selected = ["COMP", "LIMIT", "GATE"].index(self.comp_editor_mode) if self.editor_nav_scope == "comp-top" else -1
            self._draw_icon_row(c, w, top_y, top_items, comp_top_selected, "comp-top", preview_only)
            mode_enabled = self._comp_mode_enabled(ch, self.comp_editor_mode)
            mode_band_enabled = self._comp_mode_band_enabled(ch, self.comp_editor_mode)
            freq_label = f"{self._comp_mode_center(ch, self.comp_editor_mode):.0f}Hz"
            width_label = "ALL" if not mode_band_enabled else f"{self._comp_mode_width(ch, self.comp_editor_mode):.2f}oct"
            items = [
                ("THR", f"{ch.comp_threshold_db:.0f}dB", mode_enabled),
                ("ATT", f"{ch.comp_attack_ms:.0f}ms", mode_enabled),
                ("REL", f"{ch.comp_release_ms:.0f}ms", mode_enabled),
                ("RAT", f"{ch.comp_ratio:.1f}:1", mode_enabled),
                ("MAKE", f"{ch.comp_makeup:.2f}x", mode_enabled),
                ("FREQ", freq_label, mode_band_enabled),
                ("WIDTH", width_label, mode_band_enabled),
            ]
            self._draw_icon_row(c, w, bottom_y, items, body_selected, stage_key, preview_only)
        elif stage_key == "eq":
            top_items = []
            for i in range(max(1, ch.eq_band_count)):
                band = self._eq_band(ch, i)
                top_items.append((f"B{i + 1}", f"{int(float(band['freq']))}", bool(band["enabled"])))
            eq_top_selected = self.eq_selected_band if self.editor_nav_scope == "eq-top" else -1
            self._draw_icon_row(c, w, top_y, top_items, eq_top_selected, "eq-top", preview_only)
            items = [
                ("NEW", "", True),
                ("TYPE", str(band["type"]), bool(band["enabled"])),
                ("FREQ", f"{float(band['freq']):.0f}Hz", bool(band["band_enabled"])),
                ("GAIN", f"{float(band['gain_db']):+.1f}dB", bool(band["enabled"])),
                ("WIDTH", f"{float(band['width']):.2f}oct", bool(band["band_enabled"])),
            ]
            self._draw_icon_row(c, w, bottom_y, items, body_selected, stage_key, preview_only)
        else:
            top_items = [("TRN", "", ch.trn_attack > 0.02 or ch.trn_sustain > 0.02), ("CLR", "", ch.clr_drive > 0.02), ("XCT", "", ch.xct_amount > 0.02)]
            tone_top_selected = ["TRN", "CLR", "XCT"].index(self.tone_editor_mode) if self.editor_nav_scope == "tone-top" else -1
            self._draw_icon_row(c, w, top_y, top_items, tone_top_selected, "tone-top", preview_only)
            items = self._tone_body_items(ch, self.tone_editor_mode)
            self._draw_icon_row(c, w, bottom_y, items, body_selected, stage_key, preview_only)

    # ------------------------------------------------------------------ #
    # Unified all-stages editor grid                                     #
    # ------------------------------------------------------------------ #
    # Shape mirrors the user's Google-Sheet layout: 6 stage columns,     #
    # each with a header row and N param-cell rows (variable per stage). #
    # One Tk canvas hitbox per cell drives navigation + click selection. #
    # ------------------------------------------------------------------ #
    _STAGE_GRID: list[tuple[str, str, list[str]]] = [
        ("pre",  "PRE", ["TBE", "LPF", "48V", "PHS", "HPF"]),
        ("harm", "HRM", ["TBE", "H1", "H2", "H3", "H4", "H5"]),
        ("gate", "GTE", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("comp", "CMP", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("eq",   "EQ",  ["TBE", "FRQ", "GAN", "SHP", "BND", "TRN", "ATK", "SUT", "BD2"]),
        ("tone", "TON", ["TRN", "XCT", "DRV", "FRQ", "ATK", "SUT", "BND", "BD2"]),
    ]

    def _stage_cell_value(self, ch: ChannelState, stage_key: str, label: str) -> tuple[str, bool]:
        """Resolve (display_value, enabled) for one cell of the stage grid.
        Unmapped labels render as a neutral placeholder ("-", False). The
        backing fields get filled in over time as wiring is added; the grid
        will keep working visually even before each cell has a real signal."""
        # PRE
        if stage_key == "pre":
            if label == "TBE": return ("ON" if ch.tube else "off", bool(ch.tube))
            if label == "LPF": return (f"{ch.lpf_hz:.0f}", bool(ch.lpf_enabled))
            if label == "48V": return ("ON" if ch.phantom else "off", bool(ch.phantom))
            if label == "PHS": return ("INV" if ch.phase else "off", bool(ch.phase))
            if label == "HPF": return (f"{ch.hpf_hz:.0f}", bool(ch.hpf_enabled))
        # HARM (label H1..H5 maps to harmonics[0..4])
        if stage_key == "harm":
            if label == "TBE": return ("ON" if ch.harm_tube else "off", bool(ch.harm_tube))
            hp = getattr(ch, "harm_param_bypass", None) or {}
            if label.startswith("H") and len(label) == 2 and label[1].isdigit():
                idx = int(label[1]) - 1
                if 0 <= idx < len(ch.harmonics):
                    val = float(ch.harmonics[idx])
                    # Match the .2f display — tiny tail values shouldn't read as lit when printed "0.00".
                    rounded = round(val, 2)
                    ok = abs(rounded) >= 0.01 and abs(val) > 1e-9 and not bool(hp.get(label))
                    return (f"{rounded:.2f}", ok)
        # GATE — dedicated dynamics (DSP order: gate then compressor).
        if stage_key == "gate":
            gb = getattr(ch, "gate_param_bypass", None) or {}

            def gcell(nm: str) -> bool:
                return bool(ch.gate_enabled) and not bool(gb.get(nm))

            if label == "TBE": return ("ON" if ch.gate_tube else "off", bool(ch.gate_tube))
            if label == "THR": return (f"{ch.gate_threshold_db:.0f}", gcell("THR"))
            if label == "RAT": return (f"{ch.gate_ratio:.1f}", gcell("RAT"))
            if label == "ATK": return (f"{ch.gate_attack_ms:.0f}", gcell("ATK"))
            if label == "RLS": return (f"{ch.gate_release_ms:.0f}", gcell("RLS"))
            if label == "GAN": return (f"{ch.gate_makeup:.2f}", gcell("GAN"))
            if label == "FRQ":
                ok = bool(ch.gate_band_enabled) and not bool(gb.get("FRQ"))
                return (f"{ch.gate_center_hz:.0f}", ok)
            if label == "WDT":
                ok = bool(ch.gate_band_enabled) and not bool(gb.get("WDT"))
                return (f"{ch.gate_width_oct:.2f}", ok)
            if label == "BND": return ("ON" if ch.gate_band_enabled else "off", bool(ch.gate_band_enabled))
        # COMP
        if stage_key == "comp":
            cb = getattr(ch, "comp_param_bypass", None) or {}

            def ccell(nm: str) -> bool:
                return bool(ch.comp_enabled) and not bool(cb.get(nm))

            if label == "TBE": return ("ON" if ch.comp_tube else "off", bool(ch.comp_tube))
            if label == "THR": return (f"{ch.comp_threshold_db:.0f}", ccell("THR"))
            if label == "RAT": return (f"{ch.comp_ratio:.1f}", ccell("RAT"))
            if label == "ATK": return (f"{ch.comp_attack_ms:.0f}", ccell("ATK"))
            if label == "RLS": return (f"{ch.comp_release_ms:.0f}", ccell("RLS"))
            if label == "GAN": return (f"{ch.comp_makeup:.2f}", ccell("GAN"))
            if label == "FRQ":
                ok = bool(ch.comp_band_enabled) and not bool(cb.get("FRQ"))
                return (f"{ch.comp_center_hz:.0f}", ok)
            if label == "WDT":
                ok = bool(ch.comp_band_enabled) and not bool(cb.get("WDT"))
                return (f"{ch.comp_width_oct:.2f}", ok)
            if label == "BND": return ("ON" if ch.comp_band_enabled else "off", bool(ch.comp_band_enabled))
        # EQ — unified-band row; bypass flags dim individual letters.
        if stage_key == "eq":
            bp = getattr(ch, "eq_param_bypass", None) or {}
            def bypassed(nm: str) -> bool:
                return bool(bp.get(nm))
            b_sel = self._eq_band(ch) if getattr(ch, "eq_band_enabled", False) else None
            if label == "TBE": return ("ON" if ch.eq_tube else "off", bool(ch.eq_tube))
            if label == "FRQ":
                ok = bool(ch.eq_enabled) and not bypassed("FRQ")
                hz = float(b_sel["freq"]) if b_sel is not None else float(ch.eq_freq)
                return (f"{hz:.0f}", ok)
            if label == "GAN":
                ok = bool(ch.eq_enabled) and not bypassed("GAN")
                gdb = float(b_sel["gain_db"]) if b_sel is not None else float(ch.eq_gain_db)
                return (f"{gdb:+.1f}", ok)
            if label == "SHP":
                ok = bool(ch.eq_enabled) and not bypassed("SHP")
                wd = float(b_sel["width"]) if b_sel is not None else float(ch.eq_width)
                return (f"±{wd:.2f}", ok)
            if label == "BND":
                tier = max(1, int(ch.eq_band_count))
                sb = max(0, getattr(self, "eq_selected_band", 0))
                cur = min(tier, sb + 1)
                txt = f"{cur}/{tier}" if ch.eq_band_enabled else "off"
                return (txt, bool(ch.eq_band_enabled))
            if label == "BD2":
                ok = bool(ch.eq_band_enabled) and not bypassed("BD2")
                wd = float(b_sel["width"]) if b_sel is not None else float(ch.eq_width)
                return (f"{wd:.2f}", ok)
            ok = bool(ch.eq_enabled) and not bypassed(label)
            stub = "-" if bypassed(label) else "•"
            if label == "TRN": return (stub, ok)
            if label == "ATK": return (stub, ok)
            if label == "SUT": return (stub, ok)
        # TONE
        if stage_key == "tone":
            tb = getattr(ch, "tone_param_bypass", None) or {}
            if label == "TRN":
                on = bool(getattr(ch, "transient_enabled", True))
                return ("ON" if on else "off", on and not bool(tb.get("TRN")))
            if label == "XCT":
                ex = getattr(ch, "exciter_enabled", True)
                return (
                    f"{ch.xct_amount:.2f}",
                    ex and ch.xct_amount > 0.02 and not bool(tb.get("XCT")),
                )
            if label == "DRV":
                sat = getattr(ch, "saturation_enabled", True)
                return (f"{ch.clr_drive:.2f}", sat and not bool(tb.get("DRV")))
            if label == "FRQ":
                ok = bool(ch.xct_band_enabled) and not bool(tb.get("FRQ"))
                return (f"{ch.xct_freq:.0f}", ok)
            if label == "ATK":
                ok = ch.trn_attack != 0.0 and not bool(tb.get("ATK"))
                return (f"{ch.trn_attack:+.2f}", ok)
            if label == "SUT":
                ok = ch.trn_sustain != 0.0 and not bool(tb.get("SUT"))
                return (f"{ch.trn_sustain:+.2f}", ok)
            if label == "BND":
                return (
                    "ON" if ch.trn_band_enabled else "off",
                    bool(ch.trn_band_enabled) and not bool(tb.get("BND")),
                )
            if label == "BD2":
                return (
                    "ON" if ch.xct_band_enabled else "off",
                    bool(ch.xct_band_enabled) and not bool(tb.get("BD2")),
                )
        return ("-", False)

    def _multiband_visual_expanded(self, ch: ChannelState | None = None) -> bool:
        """Return True to use compact grid rows + shorter editor canvas pref.

        EQ used to opt in when ``eq_band_enabled``; that shrank the **entire**
        six-column unified grid and autosize height whenever ``selected_stage_key``
        crossed into EQ, so PRE/HRM/etc. appeared to jump. Multiband EQ is still
        drawn in the polar pane; only this shared row-height mode stays off for EQ.
        """
        ch = ch or self._current_channel()
        sk = self.selected_stage_key
        if sk == "eq":
            return False
        if sk == "gate":
            return bool(ch.gate_band_enabled)
        if sk == "comp":
            return bool(ch.comp_band_enabled)
        if sk == "tone":
            return bool(ch.trn_band_enabled or ch.xct_band_enabled)
        return False

    def _unified_editor_grid_need_height_px(self, ch: ChannelState | None = None) -> int:
        """Pixel height required for ``_draw_unified_editor`` (tallest column, no clipping)."""
        ch = ch or self._current_channel()
        mb = self._multiband_visual_expanded(ch)
        header_h = self.GRID_HEADER_H_MULTIBAND if mb else self.GRID_HEADER_H_NORMAL
        cell_h = self.GRID_CELL_H_MULTIBAND if mb else self.GRID_CELL_H_NORMAL
        max_rows = max(len(cols[2]) for cols in self._STAGE_GRID)
        top_y = 12
        bottom = top_y + header_h + 4 + (max_rows - 1) * (cell_h + 2) + cell_h
        return int(bottom + 14)

    def _autosize_editor_canvas_height(self) -> None:
        need = self._unified_editor_grid_need_height_px()
        try:
            self.editor_frame.update_idletasks()
            ph = int(self.editor_frame.winfo_height())
        except tk.TclError:
            self.editor_canvas.config(height=need)
            return

        if ph < 200:
            self.editor_canvas.config(height=need)
            return

        # Titles/subtitle live above the mixer body; only in-pane chrome here.
        hdr = 96

        split = max(140, ph - hdr)
        gap_below_focus = 32
        # Prefer fitting the unified grid; polar shares remaining height via
        # ``focus_canvas expand=True``. Old code reserved 368px and hid rows.
        tail = gap_below_focus + self.EDITOR_FOCUS_AUTOSIZE_TAIL_RESERVE
        max_editor_budget = split - tail
        tgt = max(self.EDITOR_GRID_AUTOSHRINK_MIN_H, min(need, max_editor_budget))

        try:
            if int(self.editor_canvas.cget("height")) != int(tgt):
                self.editor_canvas.config(height=int(tgt))
        except tk.TclError:
            self.editor_canvas.config(height=int(tgt))

    def _sync_scalar_display_from_eq_band(self, ch: ChannelState) -> None:
        band = self._eq_band(ch)
        ch.eq_freq = float(band.get("freq", ch.eq_freq))
        ch.eq_gain_db = float(band.get("gain_db", 0.0))
        ch.eq_width = float(band.get("width", 1.4))
        ch.eq_type = str(band.get("type", "BELL"))

    def _eq_bell_response_db(self, freqs: np.ndarray, center_hz: float, gain_db: float, width_oct: float) -> np.ndarray:
        freqs = np.asarray(freqs, dtype=np.float64)
        out = np.zeros_like(freqs)
        valid = freqs > 0.0
        if not np.any(valid) or abs(gain_db) < 1e-6:
            return out
        log_f = np.zeros_like(freqs)
        log_f[valid] = np.log2(np.maximum(freqs[valid], 1.0))
        c_log = math.log2(float(np.clip(center_hz, POL_LOW_HZ, POL_HIGH_HZ)))
        sigma = max(0.08, float(width_oct) / 2.355)
        dist = (log_f - c_log) / sigma
        shape = np.zeros_like(freqs)
        shape[valid] = np.exp(-0.5 * np.square(dist[valid]))
        return shape * float(gain_db)

    def _eq_visual_preview_db(self, ch: ChannelState, freqs: np.ndarray) -> np.ndarray:
        """Response curve implied by EQ knobs — always plotted in the EQ focus view."""

        freqs = np.asarray(freqs, dtype=np.float64)
        agg = np.zeros_like(freqs)
        bp = getattr(ch, "eq_param_bypass", None) or {}
        if bool(ch.eq_band_enabled):
            n = max(1, min(8, int(ch.eq_band_count)))
            sel = max(0, min(n - 1, int(getattr(self, "eq_selected_band", 0))))
            bypass_w = bool(bp.get("SHP") or bp.get("BD2"))
            for i in range(n):
                b = ch.eq_bands[i]
                if not bool(b.get("enabled", False)):
                    continue
                gdb = float(b.get("gain_db", 0.0))
                if abs(gdb) < 1e-4:
                    continue
                wid_b = float(b.get("width", 1.4))
                if bypass_w and i == sel:
                    wid_b = 1.4
                agg += self._eq_bell_response_db(
                    freqs, float(b.get("freq", 1000.0)), gdb, wid_b
                )
            return agg
        fc = float(ch.eq_freq if not bp.get("FRQ") else 2400.0)
        gdb = float(ch.eq_gain_db if not bp.get("GAN") else 0.0)
        wid = float(ch.eq_width if not (bp.get("BD2") or bp.get("SHP")) else 1.4)
        return self._eq_bell_response_db(freqs, fc, gdb, wid)

    def _eq_visual_aggregate_db(self, ch: ChannelState, freqs: np.ndarray) -> np.ndarray:
        """Same shape as preview when the insert is active; flat when bypassed."""
        if not ch.eq_enabled:
            return np.zeros_like(np.asarray(freqs, dtype=np.float64))
        return self._eq_visual_preview_db(ch, freqs)

    _STAGE_HEADER_FILL = {
        "pre":  "#7cf0a9",
        "harm": "#5cb8ff",
        "gate": "#ddc270",
        "comp": "#ff7d6e",
        "eq":   "#b08bff",
        "tone": "#5ec8ff",
    }

    def _draw_unified_editor(self, c: tk.Canvas, w: int, h: int, ch: ChannelState) -> None:
        """Render all 6 stage columns (PRE/HRM/GTE/CMP/EQ/TON) side-by-side.
        Each column has a header cell + one cell per param. The cap focus is
        ``editor_stage_col`` plus either ``editor_unified_header_focus`` (column
        bypass target) or ``editor_param_row`` (a param cell within that column)."""
        self.editor_hitboxes = []
        margin = 12
        gap = 4
        cols = len(self._STAGE_GRID)
        col_w = max(60, (w - margin * 2 - gap * (cols - 1)) / cols)
        mb = self._multiband_visual_expanded(ch)
        header_h = self.GRID_HEADER_H_MULTIBAND if mb else self.GRID_HEADER_H_NORMAL
        cell_h = self.GRID_CELL_H_MULTIBAND if mb else self.GRID_CELL_H_NORMAL
        top_y = 12

        focus_col = max(0, min(cols - 1, getattr(self, "editor_stage_col", 0)))
        focus_row = max(0, getattr(self, "editor_param_row", 0))
        hdr_focus_global = getattr(self, "editor_unified_header_focus", False)
        editor_focused = self.nav_scope == "editor"

        for col_idx, (stage_key, header, params) in enumerate(self._STAGE_GRID):
            x0 = margin + col_idx * (col_w + gap)
            x1 = x0 + col_w
            header_color = self._STAGE_HEADER_FILL.get(stage_key, "#9aa6b6")

            col_has_cap = editor_focused and col_idx == focus_col
            hdr_focus = bool(hdr_focus_global) and col_has_cap
            # Single cap rectangle: emphasize header XOR one param row — never both.
            # Unfocused columns and param rows below use neutral header chrome.
            if hdr_focus:
                header_outline_color = "#e8f0f8"
                header_outline_w = 3
            else:
                header_outline_color = "#2a3848"
                header_outline_w = 1

            # Column header cell -- shows stage name in its accent color.
            c.create_rectangle(
                x0,
                top_y,
                x1,
                top_y + header_h,
                outline=header_outline_color,
                width=header_outline_w,
                fill="#15202c",
            )
            c.create_text(
                (x0 + x1) / 2,
                top_y + header_h / 2,
                text=header,
                fill=header_color,
                font=("Segoe UI", 11, "bold"),
            )
            # Header selects the column header focus lane (distinct from first-row bypass hits).
            self.editor_hitboxes.append((x0, top_y, x1, top_y + header_h, ("stage_hdr", col_idx), header, "stage_header"))

            # Param cells stacked under the header.
            for row_idx, label in enumerate(params):
                cy0 = top_y + header_h + 4 + row_idx * (cell_h + 2)
                cy1 = cy0 + cell_h
                value, enabled = self._stage_cell_value(ch, stage_key, label)
                is_focused = (
                    editor_focused
                    and col_idx == focus_col
                    and row_idx == focus_row
                    and not hdr_focus_global
                )
                if enabled:
                    fill_bg = "#1d2c39"
                    label_fg = "#f2f3f6"
                    value_fg = header_color
                else:
                    fill_bg = "#131a22"
                    label_fg = "#7d8a9b"
                    value_fg = "#5d6b7c"
                if stage_key == "eq" and label == "SHP":
                    wd = float(self._eq_band(ch)["width"]) if getattr(ch, "eq_band_enabled", False) else float(ch.eq_width)
                    value_fg = eq_spread_brightness_rgb(wd if enabled else 0.35)
                cell_outline = "#7cf0a9" if is_focused else ("#2a3848" if enabled else "#1d2530")
                if stage_key == "tone" and enabled:
                    if label == "TRN":
                        fill_bg = "#153230"
                        label_fg = TONE_HEX_TRN
                        value_fg = TONE_HEX_TRN
                    elif label == "XCT":
                        fill_bg = "#261830"
                        label_fg = TONE_HEX_XCT
                        value_fg = TONE_HEX_XCT
                    elif label == "DRV":
                        fill_bg = "#302618"
                        label_fg = TONE_HEX_CLR
                        value_fg = TONE_HEX_CLR
                c.create_rectangle(
                    x0,
                    cy0,
                    x1,
                    cy1,
                    outline=cell_outline,
                    width=2 if is_focused else 1,
                    fill=fill_bg,
                )
                c.create_text(
                    (x0 + x1) / 2,
                    cy0 + 11,
                    text=label,
                    fill=label_fg,
                    font=("Segoe UI", 9, "bold"),
                )
                c.create_text(
                    (x0 + x1) / 2,
                    cy1 - 11,
                    text=value,
                    fill=value_fg,
                    font=("Segoe UI", 9),
                )
                self.editor_hitboxes.append((x0, cy0, x1, cy1, ("stage_col", col_idx, row_idx), label, "stage_cell"))

    def _draw_pre_editor_layout(self, c: tk.Canvas, w: int, h: int, ch: ChannelState, stage_keys: list[str]) -> None:
        self.editor_hitboxes = []
        # Editor is now 3 columns (CHANNEL / STAGE / BODY). The previous
        # right-most column hosted SOLO / MUTE / REC, which the user asked
        # to remove from the editor entirely; SMR lives only on the strips.
        margin = 16
        gap = 10
        available_w = w - margin * 2 - gap * 2
        side_w = min(80, max(56, int((available_w - 140) / 2)))
        body_w = available_w - side_w * 2
        if body_w < 140:
            side_w = max(50, int((available_w - 140) / 2))
            body_w = available_w - side_w * 2
        left_w = side_w
        stage_w = side_w
        top_y = 46
        bottom_y = h - 14
        section_h = bottom_y - top_y
        x0 = margin
        x1 = x0 + left_w
        x2 = x1 + gap
        x3 = x2 + stage_w
        x4 = x3 + gap
        x5 = x4 + body_w
        columns = [
            (x0, x1, "left"),
            (x2, x3, "stage"),
            (x4, x5, "body"),
        ]
        active_keys = ["left", "stage", "body"]
        active_col = active_keys[self.pre_editor_column]
        for col_x0, col_x1, key in columns:
            is_active = key == active_col
            c.create_rectangle(
                col_x0,
                top_y,
                col_x1,
                bottom_y,
                outline="#41505f" if is_active else "#22303b",
                width=1,
                fill="#151d25" if is_active else "",
            )
            if is_active:
                c.create_rectangle(col_x0 + 2, top_y + 2, col_x0 + 6, bottom_y - 2, outline="", fill="#6a7886")

        # Left column: channel selector only. The CH VOL fader was removed
        # from the editor; channel gain is set on the strip-view fader row.
        left_center = (x0 + x1) / 2
        knob_y = top_y + 42
        self._draw_pre_knob(
            c,
            left_center,
            knob_y,
            "CH",
            self._current_channel_short_label(),
            active_col == "left",
        )
        self.editor_hitboxes.append((x0 + 8, knob_y - 28, x1 - 8, knob_y + 42, 0, "CH", "pre-left"))

        # Stage column
        stage_labels = [("PRE", "pre"), ("HAR", "harm"), ("CMP", "comp"), ("EQ", "eq"), ("FX", "tone")]
        stage_step = (section_h - 64) / max(1, len(stage_labels) - 1)
        for idx, (label, key) in enumerate(stage_labels):
            cy = top_y + 30 + idx * stage_step
            selected = active_col == "stage" and self.pre_editor_positions["stage"] == idx
            enabled = self._stage_enabled(ch, key)
            self._draw_pre_dot(c, (x2 + x3) / 2, cy, label, "", enabled, selected)
            self.editor_hitboxes.append((x2 + 8, cy - 22, x3 - 8, cy + 30, idx, label, "pre-stage"))

        # Body column
        body_items = [
            ("LPF", f"{ch.lpf_hz:.0f}", ch.lpf_enabled),
            ("48V", "", ch.phantom),
            ("PHS", "", ch.phase),
            ("TBE", "", ch.tube),
            ("HPF", f"{ch.hpf_hz:.0f}", ch.hpf_enabled),
        ]
        body_step = (section_h - 64) / max(1, len(body_items) - 1)
        for idx, (label, value, enabled) in enumerate(body_items):
            cy = top_y + 30 + idx * body_step
            selected = active_col == "body" and self.pre_editor_positions["body"] == idx
            self._draw_pre_dot(c, (x4 + x5) / 2, cy, label, value, enabled, selected, slash=label in ("LPF", "HPF"))
            self.editor_hitboxes.append((x4 + 8, cy - 22, x5 - 8, cy + 34, idx, label, "pre-body"))

    def _module_stage_items(self, ch: ChannelState) -> tuple[list[tuple[str, str, bool]], list[tuple[str, str, bool]]]:
        if self.selected_stage_key == "harm":
            return [], [
                ("H2", f"{ch.harmonics[0]:.2f}", ch.harmonics[0] > 0.001),
                ("H3", f"{ch.harmonics[1]:.2f}", ch.harmonics[1] > 0.001),
                ("H4", f"{ch.harmonics[2]:.2f}", ch.harmonics[2] > 0.001),
                ("H5", f"{ch.harmonics[3]:.2f}", ch.harmonics[3] > 0.001),
                ("H6", f"{ch.harmonics[4]:.2f}", ch.harmonics[4] > 0.001),
                ("MAKE", f"{ch.harmonic_makeup:.2f}x", abs(ch.harmonic_makeup - 1.0) > 0.01),
            ]
        if self.selected_stage_key == "comp":
            mode_enabled = self._comp_mode_enabled(ch, self.comp_editor_mode)
            mode_band_enabled = self._comp_mode_band_enabled(ch, self.comp_editor_mode)
            top_items = [
                ("COMP", "", ch.comp_enabled),
                ("GATE", "", ch.gate_enabled),
            ]
            body_items = [
                ("THR", f"{ch.comp_threshold_db:.0f}dB", mode_enabled),
                ("ATT", f"{ch.comp_attack_ms:.0f}ms", mode_enabled),
                ("REL", f"{ch.comp_release_ms:.0f}ms", mode_enabled),
                ("RAT", f"{ch.comp_ratio:.1f}:1", mode_enabled),
                ("MAKE", f"{ch.comp_makeup:.2f}x", mode_enabled),
                ("FREQ", f"{self._comp_mode_center(ch, self.comp_editor_mode):.0f}Hz", mode_band_enabled),
                ("WIDTH", "ALL" if not mode_band_enabled else f"{self._comp_mode_width(ch, self.comp_editor_mode):.2f}oct", mode_band_enabled),
            ]
            return top_items, body_items
        if self.selected_stage_key == "eq":
            top_items = []
            for i in range(max(1, ch.eq_band_count)):
                band = self._eq_band(ch, i)
                top_items.append((f"B{i + 1}", f"{int(float(band['freq']))}", bool(band["enabled"])))
            band = self._eq_band(ch)
            body_items = [
                ("NEW", "", True),
                ("TYPE", str(band["type"]), bool(band["enabled"])),
                ("FREQ", f"{float(band['freq']):.0f}Hz", bool(band["band_enabled"])),
                ("GAIN", f"{float(band['gain_db']):+.1f}dB", bool(band["enabled"])),
                ("WIDTH", f"{float(band['width']):.2f}oct", bool(band["band_enabled"])),
            ]
            return top_items, body_items
        top_items = [
            ("TRN", "", ch.trn_attack > 0.02 or ch.trn_sustain > 0.02),
            ("CLR", "", ch.clr_drive > 0.02),
            ("XCT", "", ch.xct_amount > 0.02),
        ]
        return top_items, self._tone_body_items(ch, self.tone_editor_mode)

    def _module_editor_body_count(self, ch: ChannelState | None = None) -> int:
        ch = ch or self._current_channel()
        top_items, body_items = self._module_stage_items(ch)
        return len(top_items) + len(body_items)

    def _normalize_module_editor_positions(self) -> None:
        ch = self._current_channel()
        self.module_editor_positions["left"] = 0
        stage_keys = self._console_stage_keys()
        if self.selected_stage_key in stage_keys:
            self.module_editor_positions["stage"] = stage_keys.index(self.selected_stage_key)
        self.module_editor_positions["stage"] = max(0, min(len(stage_keys) - 1, self.module_editor_positions["stage"]))
        body_count = max(1, self._module_editor_body_count(ch))
        self.module_editor_positions["body"] = max(0, min(body_count - 1, self.module_editor_positions["body"]))
        if self.selected_stage_key == "eq":
            top_items, body_items = self._module_stage_items(ch)
            if top_items:
                band_idx = min(self.eq_selected_band, len(top_items) - 1)
                valid = [band_idx, len(top_items) + 0, len(top_items) + 1, len(top_items) + 2, len(top_items) + 3, len(top_items) + 4]
                if self.module_editor_positions["body"] not in valid:
                    self.module_editor_positions["body"] = band_idx

    def _draw_module_editor_layout(self, c: tk.Canvas, w: int, h: int, ch: ChannelState, stage_keys: list[str]) -> None:
        self.editor_hitboxes = []
        self._normalize_module_editor_positions()
        # Editor is now 3 columns (CHANNEL / STAGE / BODY). SOLO / MUTE / REC
        # have been removed from the editor entirely and live only on the
        # channel-strip footers.
        margin = 16
        gap = 10
        available_w = w - margin * 2 - gap * 2
        side_w = min(80, max(56, int((available_w - 140) / 2)))
        body_w = available_w - side_w * 2
        if body_w < 140:
            side_w = max(50, int((available_w - 140) / 2))
            body_w = available_w - side_w * 2
        left_w = side_w
        stage_w = side_w
        top_y = 46
        bottom_y = h - 14
        section_h = bottom_y - top_y
        x0 = margin
        x1 = x0 + left_w
        x2 = x1 + gap
        x3 = x2 + stage_w
        x4 = x3 + gap
        x5 = x4 + body_w
        columns = [
            (x0, x1, "left"),
            (x2, x3, "stage"),
            (x4, x5, "body"),
        ]
        active_keys = ["left", "stage", "body"]
        active_col = active_keys[self.module_editor_column]
        for col_x0, col_x1, key in columns:
            is_active = key == active_col
            c.create_rectangle(
                col_x0,
                top_y,
                col_x1,
                bottom_y,
                outline="#41505f" if is_active else "#22303b",
                width=1,
                fill="#151d25" if is_active else "",
            )
            if is_active:
                c.create_rectangle(col_x0 + 2, top_y + 2, col_x0 + 6, bottom_y - 2, outline="", fill="#6a7886")

        left_center = (x0 + x1) / 2
        knob_y = top_y + 42
        self._draw_pre_knob(
            c,
            left_center,
            knob_y,
            "CH",
            self._current_channel_short_label(),
            active_col == "left",
        )
        self.editor_hitboxes.append((x0 + 8, knob_y - 28, x1 - 8, knob_y + 42, 0, "CH", "module-left"))

        stage_labels = [("PRE", "pre"), ("HAR", "harm"), ("CMP", "comp"), ("EQ", "eq"), ("FX", "tone")]
        stage_step = (section_h - 64) / max(1, len(stage_labels) - 1)
        for idx, (label, key) in enumerate(stage_labels):
            cy = top_y + 30 + idx * stage_step
            selected = active_col == "stage" and self.module_editor_positions["stage"] == idx
            is_current = self._stage_enabled(ch, key)
            self._draw_pre_dot(c, (x2 + x3) / 2, cy, label, "", is_current, selected)
            self.editor_hitboxes.append((x2 + 8, cy - 22, x3 - 8, cy + 30, idx, label, "module-stage"))

        top_items, body_items = self._module_stage_items(ch)
        selected_body = self.module_editor_positions["body"]
        top_count = len(top_items)
        body_count = len(body_items)
        body_left_cx = x4 + body_w * 0.23
        body_mid_cx = x4 + body_w * 0.56
        body_right_cx = x4 + body_w * 0.82
        body_center = (x4 + x5) / 2
        content_top = top_y + 22
        content_bottom = bottom_y - 18
        content_h = content_bottom - content_top

        if self.selected_stage_key == "harm":
            cols = 2
            rows = max(1, math.ceil(body_count / cols))
            x_positions = [
                x4 + body_w * 0.32,
                x4 + body_w * 0.68,
            ]
            row_step = 88.0
            total_h = row_step * max(0, rows - 1)
            start_y = content_top + max(0.0, (content_h - total_h) / 2.0)
            for offset, (label, value, enabled) in enumerate(body_items):
                idx = offset
                col = 0 if offset < rows else 1
                row = offset if offset < rows else offset - rows
                cx = x_positions[min(col, len(x_positions) - 1)]
                cy = start_y + row * row_step
                selected = active_col == "body" and selected_body == idx
                self._draw_pre_dot(c, cx, cy, label, value, enabled, selected)
                self.editor_hitboxes.append((cx - 38, cy - 22, cx + 38, cy + 34, idx, label, "module-body"))
        elif self.selected_stage_key == "comp":
            combined_items = top_items + body_items
            comp_rows = [(0, 1), (2, 5), (3, 6), (4, 7), (8, None)]
            x_positions = [
                x4 + body_w * 0.31,
                x4 + body_w * 0.69,
            ]
            row_step = 68.0
            total_h = row_step * max(0, len(comp_rows) - 1)
            start_y = content_top + max(0.0, (content_h - total_h) / 2.0)
            for row, pair in enumerate(comp_rows):
                cy = start_y + row * row_step
                for col, idx in enumerate(pair):
                    if idx is None:
                        continue
                    label, value, enabled = combined_items[idx]
                    cx = x_positions[col]
                    selected = active_col == "body" and selected_body == idx
                    self._draw_pre_dot(c, cx, cy, label, value, enabled, selected)
                    self.editor_hitboxes.append((cx - 38, cy - 22, cx + 38, cy + 34, idx, label, "module-body"))
        elif self.selected_stage_key == "eq":
            combined_items = top_items + body_items
            band_idx = min(self.eq_selected_band, max(0, len(top_items) - 1)) if top_items else 0
            left_indices = [band_idx, top_count + 0, top_count + 2]
            right_indices = [top_count + 1, top_count + 3, top_count + 4]
            x_positions = [
                x4 + body_w * 0.31,
                x4 + body_w * 0.69,
            ]
            row_step = 94.0
            rows = 3
            total_h = row_step * max(0, rows - 1)
            start_y = content_top + max(0.0, (content_h - total_h) / 2.0)
            for row, idx in enumerate(left_indices):
                label, value, enabled = combined_items[idx]
                cx = x_positions[0]
                cy = start_y + row * row_step
                selected = active_col == "body" and selected_body == idx
                self._draw_pre_dot(c, cx, cy, label, value, enabled, selected)
                self.editor_hitboxes.append((cx - 38, cy - 22, cx + 38, cy + 34, idx, label, "module-body"))
            for row, idx in enumerate(right_indices):
                label, value, enabled = combined_items[idx]
                cx = x_positions[1]
                cy = start_y + row * row_step
                selected = active_col == "body" and selected_body == idx
                self._draw_pre_dot(c, cx, cy, label, value, enabled, selected)
                self.editor_hitboxes.append((cx - 38, cy - 22, cx + 38, cy + 34, idx, label, "module-body"))
        else:
            top_item_h = 74.0
            top_total_h = top_item_h * max(0, top_count - 1)
            top_start_y = content_top + max(0.0, (content_h - max(top_total_h, 0.0)) / 2.0)
            for idx, (label, value, enabled) in enumerate(top_items):
                cy = top_start_y + idx * top_item_h
                selected = active_col == "body" and selected_body == idx
                self._draw_pre_dot(c, body_left_cx, cy, label, value, enabled, selected)
                self.editor_hitboxes.append((body_left_cx - 34, cy - 22, body_left_cx + 34, cy + 34, idx, label, "module-body"))

            param_cols = 2 if body_count > 4 else 1
            param_rows = max(1, math.ceil(body_count / param_cols))
            param_xs = [body_mid_cx] if param_cols == 1 else [body_mid_cx - body_w * 0.09, body_right_cx]
            row_step = 74.0 if param_rows <= 4 else 60.0
            total_h = row_step * max(0, param_rows - 1)
            start_y = content_top + max(0.0, (content_h - total_h) / 2.0)
            for offset, (label, value, enabled) in enumerate(body_items):
                idx = top_count + offset
                col = offset // param_rows if param_cols > 1 else 0
                row = offset % param_rows if param_cols > 1 else offset
                cx = param_xs[min(col, len(param_xs) - 1)]
                cy = start_y + row * row_step
                selected = active_col == "body" and selected_body == idx
                self._draw_pre_dot(c, cx, cy, label, value, enabled, selected, slash=label in ("LPF", "HPF"))
                self.editor_hitboxes.append((cx - 38, cy - 22, cx + 38, cy + 34, idx, label, "module-body"))

    def _current_channel_short_label(self) -> str:
        idx = self._active_channel_index()
        if idx >= len(self.engine.channels):
            return "MST"
        return f"{idx + 1:02d}"

    def _draw_pre_knob(self, c: tk.Canvas, cx: float, cy: float, label: str, value: str, selected: bool) -> None:
        c.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, fill="#141a20", outline="#8b96a3" if selected else "#31404e", width=2 if selected else 1)
        if selected:
            c.create_oval(cx - 24, cy - 24, cx + 24, cy + 24, outline="#465362", width=1)
        c.create_line(cx - 8, cy, cx + 8, cy, fill="#5ef0b0", width=2)
        if label == "CH":
            c.create_line(cx - 8, cy, cx - 4, cy - 4, fill="#5ef0b0", width=2)
            c.create_line(cx - 8, cy, cx - 4, cy + 4, fill="#5ef0b0", width=2)
            c.create_line(cx + 8, cy, cx + 4, cy - 4, fill="#5ef0b0", width=2)
            c.create_line(cx + 8, cy, cx + 4, cy + 4, fill="#5ef0b0", width=2)
        else:
            c.create_arc(cx - 8, cy - 8, cx + 8, cy + 8, start=300, extent=220, style="arc", outline="#5ef0b0", width=2)
            c.create_line(cx + 4, cy - 1, cx + 9, cy - 5, fill="#5ef0b0", width=2)
            c.create_line(cx + 4, cy - 1, cx + 9, cy + 3, fill="#5ef0b0", width=2)
        c.create_text(cx, cy + 28, text=label, fill="#d3dfeb", font=("Segoe UI", 9, "bold"))
        c.create_text(cx, cy + 44, text=value, fill="#89a0b6", font=("Segoe UI", 8, "bold"))

    def _draw_pre_vertical_fader(self, c: tk.Canvas, cx: float, y0: float, y1: float, value: float, min_value: float, max_value: float, label: str, value_text: str, selected: bool) -> None:
        c.create_text(cx, y0 - 10, text=label, fill="#cfd9e3", font=("Segoe UI", 8, "bold"))
        c.create_text(cx, y1 + 10, text=value_text, fill="#89a0b6", font=("Segoe UI", 8, "bold"))
        c.create_rectangle(cx - 14, y0, cx + 14, y1, fill="#131920", outline="#31404e", width=1)
        c.create_line(cx, y0 + 10, cx, y1 - 10, fill="#2b3743", width=4)
        norm = 0.0 if max_value <= min_value else max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))
        knob_y = y1 - 10 - (y1 - y0 - 20) * norm
        knob_w = 18 if selected else 16
        c.create_rectangle(cx - knob_w, knob_y - 12, cx + knob_w, knob_y + 12, fill="#1b232c", outline="#8b96a3" if selected else "#31404e", width=2 if selected else 1)
        if selected:
            c.create_rectangle(cx - knob_w - 2, knob_y - 14, cx + knob_w + 2, knob_y + 14, outline="#465362", width=1)
        c.create_line(cx, knob_y - 8, cx, knob_y + 8, fill="#5ef0b0", width=2)

    def _draw_pre_dot(self, c: tk.Canvas, cx: float, cy: float, label: str, value: str, active: bool, selected: bool, slash: bool = False) -> None:
        fill = "#5ef0b0" if active else "#ff5b54"
        r = 14
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#141a20", outline="#8b96a3" if selected else "#31404e", width=2 if selected else 1)
        if selected:
            c.create_oval(cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5, outline="#465362", width=1)
        if slash:
            c.create_line(cx - 8, cy + 6 if label == "LPF" else cy - 6, cx + 8, cy - 6 if label == "LPF" else cy + 6, fill=fill, width=3)
        else:
            c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=fill, outline="")
        c.create_text(cx, cy + 28, text=label, fill="#d3dfeb", font=("Segoe UI", 9, "bold"))
        if value:
            if label == "LPF":
                c.create_text(cx - 26, cy, text=value, fill="#89a0b6", font=("Segoe UI", 8, "bold"), anchor="e")
            elif label == "HPF":
                c.create_text(cx + 26, cy, text=value, fill="#89a0b6", font=("Segoe UI", 8, "bold"), anchor="w")
            else:
                c.create_text(cx, cy + 44, text=value, fill="#89a0b6", font=("Segoe UI", 8, "bold"))

    def _draw_badge_row(self, c: tk.Canvas, w: int, y: float, items: list[tuple[str, str, bool]], selected_idx: int, preview_only: bool) -> None:
        usable_w = w - (86 if not preview_only else 40)
        gap = min(76, (usable_w - 110) / max(1, (len(items) - 1)))
        total = gap * (len(items) - 1)
        start_x = (usable_w - total) / 2
        for idx, (label, _, active) in enumerate(items):
            x = start_x + gap * idx
            fill = "#5ef0b0" if active else "#ff5b54"
            selected = idx == selected_idx
            c.create_oval(
                x - 10,
                y - 10,
                x + 10,
                y + 10,
                fill="#1b232c" if selected else "#141a20",
                outline="#8b96a3" if selected else "#31404e",
                width=2 if selected else 1,
            )
            if selected:
                c.create_oval(x - 16, y - 16, x + 16, y + 16, outline="#465362", width=1)
            if label == "CH":
                c.create_line(x - 7, y, x + 7, y, fill=fill, width=2)
                c.create_line(x - 7, y, x - 3, y - 4, fill=fill, width=2)
                c.create_line(x - 7, y, x - 3, y + 4, fill=fill, width=2)
                c.create_line(x + 7, y, x + 3, y - 4, fill=fill, width=2)
                c.create_line(x + 7, y, x + 3, y + 4, fill=fill, width=2)
            elif label == "SND":
                c.create_arc(x - 7, y - 7, x + 7, y + 7, start=300, extent=220, style="arc", outline=fill, width=2)
                c.create_line(x + 3, y - 1, x + 8, y - 5, fill=fill, width=2)
                c.create_line(x + 3, y - 1, x + 8, y + 3, fill=fill, width=2)
            elif label == "SOL":
                c.create_text(x, y, text="S", fill=fill, font=("Segoe UI", 10, "bold"))
            elif label == "MUT":
                c.create_text(x, y, text="M", fill=fill, font=("Segoe UI", 10, "bold"))
            if not preview_only:
                c.create_text(x, y + 22, text=label, fill="#cfd9e3", font=("Segoe UI", 8, "bold"))
                self.editor_hitboxes.append((x - 26, y - 18, x + 26, y + 30, idx, label, "utility-top"))

    def _draw_icon_row(self, c: tk.Canvas, w: int, y: float, items: list[tuple[str, str, bool]], selected_idx: int, tag: str, preview_only: bool) -> None:
        gap = min(78, (w - 124) / max(1, (len(items) - 1)))
        total = gap * (len(items) - 1)
        start_x = (w - total) / 2
        large = not preview_only
        for idx, (label, value, active) in enumerate(items, start=1):
            x = start_x + gap * (idx - 1)
            selected = (idx - 1) == selected_idx
            icon_r = 16 if large else 12
            fill = "#5ef0b0" if active else "#ff5b54"
            outline = "#8b96a3" if selected else "#31404e"
            c.create_oval(
                x - icon_r,
                y - icon_r,
                x + icon_r,
                y + icon_r,
                fill="#1b232c" if selected else "#141a20",
                outline=outline,
                width=2 if selected else 1,
            )
            if selected:
                c.create_oval(x - (icon_r + 5), y - (icon_r + 5), x + (icon_r + 5), y + (icon_r + 5), outline="#465362", width=1)
            if label == "NEW":
                arm = 9 if large else 7
                c.create_line(x - arm, y, x + arm, y, fill=fill, width=3)
                c.create_line(x, y - arm, x, y + arm, fill=fill, width=3)
            elif label in ("COMP", "LIMIT", "GATE"):
                inner = 9 if large else 7
                c.create_oval(x - inner, y - inner, x + inner, y + inner, outline=fill, width=3)
                if label == "LIMIT":
                    slash = 10 if large else 8
                    c.create_line(x - slash, y + slash, x + slash, y - slash, fill=fill, width=2)
                elif label == "GATE":
                    gate = 8 if large else 6
                    c.create_rectangle(x - gate, y - gate, x + gate, y + gate, outline=fill, width=2)
            elif label in ("LPF", "HPF"):
                arm = 10 if large else 8
                slope = 6 if large else 5
                c.create_line(x - arm, y + slope if label == "LPF" else y - slope, x + arm, y - slope if label == "LPF" else y + slope, fill=fill, width=3)
            elif label in ("48V", "PHS", "TBE"):
                dot = 7 if large else 5
                c.create_oval(x - dot, y - dot, x + dot, y + dot, fill=fill, outline="")
            else:
                dot = 7 if large else 5
                c.create_oval(x - dot, y - dot, x + dot, y + dot, fill=fill, outline="")
            if not preview_only:
                label_y = y + (28 if large else 22)
                value_y = y + (47 if large else 36)
                c.create_text(x, label_y, text=label, fill="#d3dfeb", font=("Segoe UI", 9 if large else 8, "bold"))
                if value:
                    c.create_text(x, value_y, text=value, fill="#89a0b6", font=("Segoe UI", 8 if large else 8, "bold"))
                self.editor_hitboxes.append((x - 30, y - 20, x + 30, y + (58 if large else 42), idx - 1, label, tag))

    def _draw_editor_transport_row(self, c: tk.Canvas, w: float, y: float) -> None:
        """Solo / Mute / Rec for the active strip (inputs only; Master shows inactive)."""
        idx = self._active_channel_index()
        n_in = len(self.engine.channels)
        is_input = idx < n_in
        ch = self.engine.channels[idx] if is_input else None
        solo_on = bool(ch.solo) if is_input else False
        mute_on = bool(ch.mute) if is_input else False
        rec_on = bool(ch.record_armed) if is_input else False
        pad = 14.0
        gap = 8.0
        bw = (w - 2 * pad - 2 * gap) / 3.0
        y0 = y - 14.0
        y1 = y + 14.0
        specs = [
            ("SOLO", solo_on, "#e6c84a", "editor-solo"),
            ("MUTE", mute_on, "#ff6a53", "editor-mute"),
            ("REC", rec_on, "#ff3b30", "editor-rec"),
        ]
        nav_here = self.editor_nav_scope == "transport"
        for i, (text, on, accent, etag) in enumerate(specs):
            x0 = pad + i * (bw + gap)
            x1 = x0 + bw
            fill = "#1a222b" if is_input else "#14191f"
            outline = accent if on else "#2f3a46"
            if nav_here and i == self.editor_transport_selected:
                outline = "#e8f0f8"
            c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=2 if nav_here and i == self.editor_transport_selected else 1)
            if nav_here and i == self.editor_transport_selected:
                c.create_rectangle(x0 + 2, y0 + 2, x0 + 5, y1 - 2, outline="", fill="#6a7886")
            fg = "#5a6575" if not is_input else ("#f5e9a8" if on and text == "SOLO" else "#ffc9c4" if on and text == "MUTE" else "#ffb4ae" if on and text == "REC" else "#c8d4e0")
            if nav_here and i == self.editor_transport_selected:
                fg = "#f2f6fb"
            c.create_text((x0 + x1) / 2, y, text=text, fill=fg, font=("Segoe UI", 8, "bold"))
            if is_input:
                self.editor_hitboxes.append((x0, y0, x1, y1, idx, text, etag))

    def _on_editor_canvas_click(self, event) -> None:
        for x0, y0, x1, y1, idx, label, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if self.nav_scope != "editor":
                    self._capture_editor_return_context()
                self.nav_scope = "editor"
                # Unified grid: param cells use ("stage_col", col, row); headers use ("stage_hdr", col).
                if tag == "stage_header" and isinstance(idx, tuple) and len(idx) == 2 and idx[0] == "stage_hdr":
                    _, col = idx
                    cols = len(self._STAGE_GRID)
                    col = max(0, min(cols - 1, int(col)))
                    self.editor_stage_col = col
                    self.editor_unified_header_focus = True
                    self.editor_param_row = self._unified_pick_param_row_entering_stage(
                        col, getattr(self, "editor_param_row", 0)
                    )
                    self.selected_stage_key = self._STAGE_GRID[col][0]
                    self.editor_nav_scope = "stage_grid"
                    self._unified_commit_param_row_for_col(col, int(self.editor_param_row))
                    self._draw_editor_controls()
                    self.root.focus_set()
                    return
                if tag == "stage_cell" and isinstance(idx, tuple) and len(idx) == 3 and idx[0] == "stage_col":
                    _, col, row = idx
                    cols = len(self._STAGE_GRID)
                    col = max(0, min(cols - 1, int(col)))
                    params = self._STAGE_GRID[col][2]
                    row_clamped = max(0, min(len(params) - 1, int(row))) if params else 0
                    self.editor_stage_col = col
                    self.editor_param_row = row_clamped
                    self.editor_unified_header_focus = False
                    self.selected_stage_key = self._STAGE_GRID[col][0]
                    self.editor_nav_scope = "stage_grid"
                    # Remember explicit click position (don't run pick() here — it
                    # would overwrite the cell the user tapped with stale memory).
                    self._unified_commit_param_row_for_col(col, row_clamped)
                    self._draw_editor_controls()
                    self.root.focus_set()
                    return
                _log.debug("EDITOR CLICK tag=%s idx=%s label=%s", tag, idx, label)
                if tag == "editor-solo":
                    self.editor_nav_scope = "transport"
                    self.editor_transport_selected = 0
                    self._toggle_solo(idx)
                    self.root.focus_set()
                    return
                if tag == "editor-mute":
                    self.editor_nav_scope = "transport"
                    self.editor_transport_selected = 1
                    self._toggle_mute(idx)
                    self.root.focus_set()
                    return
                if tag == "editor-rec":
                    self.editor_nav_scope = "transport"
                    self.editor_transport_selected = 2
                    self._toggle_record_arm(idx)
                    self.root.focus_set()
                    return
                if tag == "pre-left":
                    self.pre_editor_column = 0
                    self.pre_editor_positions["left"] = idx
                    self.editor_nav_scope = "pre-left"
                elif tag == "pre-stage":
                    self.pre_editor_column = 1
                    self.pre_editor_positions["stage"] = idx
                    self.editor_nav_scope = "pre-stage"
                    stage_keys = self._console_stage_keys()
                    if idx < len(stage_keys):
                        self.selected_stage_key = stage_keys[idx]
                elif tag == "pre-body":
                    self.pre_editor_column = 2
                    self.pre_editor_positions["body"] = idx
                    self.editor_selected["pre"] = idx
                    self.editor_nav_scope = "pre-body"
                    self._activate_editor_item(idx, label)
                elif tag == "module-left":
                    self.module_editor_column = 0
                    self.module_editor_positions["left"] = idx
                    self.editor_nav_scope = "module-left"
                elif tag == "module-stage":
                    self.module_editor_column = 1
                    self.module_editor_positions["stage"] = idx
                    self.editor_nav_scope = "module-stage"
                    stage_keys = self._console_stage_keys()
                    if idx < len(stage_keys):
                        self.selected_stage_key = stage_keys[idx]
                elif tag == "module-body":
                    self.module_editor_column = 2
                    self.module_editor_positions["body"] = idx
                    self.editor_nav_scope = "module-body"
                    self._module_click_body_item(idx)
                elif tag == "utility-top":
                    self.editor_nav_scope = "utility"
                    self.editor_utility_selected = idx
                    self._activate_utility_item(label)
                elif tag == "stage-top":
                    stage_keys = self._console_stage_keys()
                    if idx < len(stage_keys):
                        self.selected_stage_key = stage_keys[idx]
                        self.editor_nav_scope = "stage"
                elif tag == "comp-top":
                    self.comp_editor_mode = label
                    self.editor_nav_scope = "comp-top"
                elif tag == "eq-top":
                    self.eq_selected_band = idx
                    self.editor_nav_scope = "eq-top"
                elif tag == "tone-top":
                    self.tone_editor_mode = label
                    self.editor_nav_scope = "tone-top"
                else:
                    self.editor_nav_scope = "body"
                    self.editor_selected[self.selected_stage_key] = idx
                    self._activate_editor_item(idx, label)
                self._sync_from_engine()
                self.root.focus_set()
                return

    def _on_fader_canvas_click(self, event) -> None:
        if self.selected_stage_key == "pre":
            return
        for x0, y0, x1, y1, idx in getattr(self, "fader_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.nav_scope = "editor"
                self.editor_nav_scope = "faders"
                self.editor_fader_selected = idx
                self._sync_from_engine()
                return

    def _module_click_body_item(self, idx: int) -> None:
        ch = self._current_channel()
        top_items, body_items = self._module_stage_items(ch)
        if idx < len(top_items):
            label = top_items[idx][0]
            if self.selected_stage_key == "comp":
                self.comp_editor_mode = label
            elif self.selected_stage_key == "eq":
                self.eq_selected_band = idx
            elif self.selected_stage_key == "tone":
                self.tone_editor_mode = label
            return
        body_idx = idx - len(top_items)
        if 0 <= body_idx < len(body_items):
            self.editor_selected[self.selected_stage_key] = body_idx
            self._activate_editor_item(body_idx, body_items[body_idx][0])

    def _activate_utility_item(self, label: str) -> None:
        if label == "CH":
            return
        elif label == "SND":
            return
        elif label == "SOL" and self._active_channel_index() < len(self.engine.channels):
            self._toggle_solo(self._active_channel_index())
        elif label == "MUT" and self._active_channel_index() < len(self.engine.channels):
            self._toggle_mute(self._active_channel_index())

    def _toggle_comp_top(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            self._toggle_comp_mode_enabled(ch, self.comp_editor_mode)
        self._sync_from_engine()

    def _toggle_tone_top(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            if self.tone_editor_mode == "TRN":
                value = 0.0 if ch.trn_attack > 0.02 or ch.trn_sustain > 0.02 else 0.45
                ch.trn_attack = value
                ch.trn_sustain = value * 0.8
            elif self.tone_editor_mode == "CLR":
                ch.clr_drive = 0.0 if ch.clr_drive > 0.02 else 0.45
            elif self.tone_editor_mode == "XCT":
                ch.xct_amount = 0.0 if ch.xct_amount > 0.02 else 0.45
            ch.tone_enabled = any(v > 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount))
        self._sync_from_engine()

    def _activate_editor_item(self, idx: int, label: str) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            if self.selected_stage_key == "pre":
                if label == "LPF":
                    ch.lpf_enabled = not ch.lpf_enabled
                elif label == "48V":
                    ch.phantom = not ch.phantom
                elif label == "PHS":
                    ch.phase = not ch.phase
                elif label == "TBE":
                    ch.tube = not ch.tube
                elif label == "HPF":
                    ch.hpf_enabled = not ch.hpf_enabled
            elif self.selected_stage_key == "harm":
                if 0 <= idx <= 4:
                    ch.harmonics[idx] = 0.0 if ch.harmonics[idx] > 0.001 else 0.35
                elif label == "MAKE":
                    ch.harmonic_makeup = 1.6 if ch.harmonic_makeup < 1.2 else 1.0
            elif self.selected_stage_key == "comp":
                if label == "FREQ" or label == "WIDTH":
                    self._set_comp_mode_band_enabled(ch, self.comp_editor_mode, not self._comp_mode_band_enabled(ch, self.comp_editor_mode))
            elif self.selected_stage_key == "eq":
                band = self._eq_band(ch)
                if label == "NEW":
                    ch.eq_band_count = min(ch.eq_band_count + 1, 8)
                    self.eq_selected_band = ch.eq_band_count - 1
                    new_band = self._eq_band(ch)
                    new_band["enabled"] = True
                    new_band["gain_db"] = 6.0 if abs(float(new_band["gain_db"])) < 0.1 else float(new_band["gain_db"])
                elif label == "TYPE":
                    order = ["BELL", "LOW SHELF", "HIGH SHELF", "LPF", "HPF"]
                    band["type"] = order[(order.index(str(band["type"])) + 1) % len(order)]
                    band["enabled"] = True
                elif label == "FREQ" or label == "WIDTH":
                    band["band_enabled"] = not bool(band["band_enabled"])
                ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
            elif self.selected_stage_key == "tone":
                if self.tone_editor_mode == "TRN":
                    if label in ("FREQ", "WIDTH"):
                        ch.trn_band_enabled = not ch.trn_band_enabled
                    elif label == "ATTACK":
                        ch.trn_attack = 0.0 if ch.trn_attack > 0.02 else 0.45
                    elif label == "SUSTAIN":
                        ch.trn_sustain = 0.0 if ch.trn_sustain > 0.02 else 0.45
                elif self.tone_editor_mode == "CLR":
                    if label == "DRIVE":
                        ch.clr_drive = 0.0 if ch.clr_drive > 0.02 else 0.45
                    elif label == "TONE":
                        ch.clr_tone = 0.0 if abs(ch.clr_tone) > 0.02 else 0.4
                    elif label == "MIX":
                        ch.clr_mix = 0.55 if abs(ch.clr_mix - 0.55) > 0.02 else 0.8
                    elif label == "GAIN":
                        ch.clr_gain = 1.0 if abs(ch.clr_gain - 1.0) > 0.02 else 1.35
                elif self.tone_editor_mode == "XCT":
                    if label in ("FREQ", "WIDTH"):
                        ch.xct_band_enabled = not ch.xct_band_enabled
                    elif label == "AMOUNT":
                        ch.xct_amount = 0.0 if ch.xct_amount > 0.02 else 0.45
                    elif label == "MIX":
                        ch.xct_mix = 0.45 if abs(ch.xct_mix - 0.45) > 0.02 else 0.75
                ch.tone_enabled = any(v > 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount))
        self._sync_from_engine()

    # ------------------------------------------------------------------ #
    # Unified-grid twist adjustments                                     #
    # ------------------------------------------------------------------ #
    def _adjust_unified_editor_cell(self, axis_value: float) -> None:
        """Apply SpaceMouse twist to the cap-focused cell of the unified
        editor grid. Numeric cells get scaled deltas (Hz cells use a log
        step, time cells use a log step in ms, dB cells use linear). Boolean
        cells ignore twist -- press toggles them instead."""
        if getattr(self, "editor_unified_header_focus", False):
            return
        col = max(0, min(len(self._STAGE_GRID) - 1, self.editor_stage_col))
        stage_key, _header, params = self._STAGE_GRID[col]
        if not params:
            return
        row = max(0, min(len(params) - 1, self.editor_param_row))
        label = params[row]
        ch = self._current_channel()
        if ch is None:
            return

        # (stage_key, label) -> (attr, kind, lo, hi)
        # kind: "lin" (linear * step), "log" (multiplicative), "ratio"
        # `step` is the per-axis-unit delta (we scale by axis_value already).
        spec_table: dict[tuple[str, str], tuple[str, str, float, float, float]] = {
            ("pre",  "LPF"): ("lpf_hz",          "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("pre",  "HPF"): ("hpf_hz",          "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("harm", "H1"):  (("harmonics", 0),  "lin",  0.0,  1.0, 0.04),
            ("harm", "H2"):  (("harmonics", 1),  "lin",  0.0,  1.0, 0.04),
            ("harm", "H3"):  (("harmonics", 2),  "lin",  0.0,  1.0, 0.04),
            ("harm", "H4"):  (("harmonics", 3),  "lin",  0.0,  1.0, 0.04),
            ("harm", "H5"):  (("harmonics", 4),  "lin",  0.0,  1.0, 0.04),
            ("gate", "THR"): ("gate_threshold_db", "lin", POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER, 0.8),
            ("gate", "RAT"): ("gate_ratio",        "lin",   1.0, 20.0, 0.3),
            ("gate", "ATK"): ("gate_attack_ms",    "log",   0.1, 5000.0, 0.08),
            ("gate", "RLS"): ("gate_release_ms",   "log",   1.0, 5000.0, 0.08),
            ("gate", "GAN"): ("gate_makeup",       "lin",   0.0,  4.0, 0.08),
            ("gate", "FRQ"): ("gate_center_hz",  "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("gate", "WDT"): ("gate_width_oct",  "lin",   0.1,  6.0, 0.08),
            ("comp", "THR"): ("comp_threshold_db", "lin", POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER, 0.8),
            ("comp", "RAT"): ("comp_ratio",      "lin",   1.0, 20.0, 0.3),
            ("comp", "ATK"): ("comp_attack_ms",  "log",   0.1, 5000.0, 0.08),
            ("comp", "RLS"): ("comp_release_ms", "log",   1.0, 5000.0, 0.08),
            ("comp", "GAN"): ("comp_makeup",     "lin",   0.0,  4.0, 0.08),
            ("comp", "FRQ"): ("comp_center_hz",  "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("comp", "WDT"): ("comp_width_oct",  "lin",   0.1,  6.0, 0.08),
            ("eq",   "FRQ"): ("eq_freq",         "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("eq",   "GAN"): ("eq_gain_db",      "lin", -24.0, 24.0, 0.6),
            ("eq",   "BD2"): ("eq_width",        "lin",   0.1,  6.0, 0.08),
            ("eq",   "SHP"): ("eq_width",        "lin",   0.1,  6.0, 0.08),
            ("tone", "DRV"): ("clr_drive",       "lin",   0.0,  1.0, 0.04),
            ("tone", "XCT"): ("xct_amount",      "lin",   0.0,  1.0, 0.04),
            ("tone", "FRQ"): ("xct_freq",        "log",  POL_LOW_HZ, POL_HIGH_HZ, 0.08),
            ("tone", "ATK"): ("trn_attack",      "lin",  -1.0,  1.0, 0.04),
            ("tone", "SUT"): ("trn_sustain",     "lin",  -1.0,  1.0, 0.04),
        }
        # Multi-band EQ: TWIST BND selects which band FRQ/GAN/BD2/SHP apply to.
        if stage_key == "eq" and label == "BND":
            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                return
            with self.engine._lock:
                if not ch.eq_band_enabled:
                    self._prime_eq_minimum_multiband(ch)
                else:
                    tier = max(1, int(ch.eq_band_count))
                    self.eq_selected_band = (
                        self.eq_selected_band + (1 if axis_value > 0 else -1)
                    ) % tier
                    self._sync_scalar_display_from_eq_band(ch)
            self._draw_editor_controls()
            self._sync_from_engine()
            return

        spec = spec_table.get((stage_key, label))
        if spec is None:
            return
        attr, kind, lo, hi, step = spec

        if stage_key == "eq" and ch.eq_band_enabled and label in ("FRQ", "GAN", "BD2", "SHP"):
            bkey_map = {"FRQ": ("freq", "log"), "GAN": ("gain_db", "lin"), "BD2": ("width", "lin"), "SHP": ("width", "lin")}
            bkey, bk_kind = bkey_map[label]
            with self.engine._lock:
                band = self._eq_band(ch)
                cur = float(band[bkey])
                if bk_kind == "log":
                    factor = math.exp(axis_value * math.log(1.0 + step))
                    new = cur * factor
                else:
                    new = cur + axis_value * step * (hi - lo) / 2.0
                new = max(lo, min(hi, new))
                band[bkey] = new
                band["enabled"] = True
                self._sync_scalar_display_from_eq_band(ch)
            self._draw_editor_controls()
            self._sync_from_engine()
            return

        with self.engine._lock:
            if isinstance(attr, tuple):
                arr = getattr(ch, attr[0])
                cur = float(arr[attr[1]])
            else:
                cur = float(getattr(ch, attr))
            if kind == "log":
                factor = math.exp(axis_value * math.log(1.0 + step))
                new = cur * factor
            else:
                new = cur + axis_value * step * (hi - lo) / 2.0
            new = max(lo, min(hi, new))
            if isinstance(attr, tuple):
                arr = getattr(ch, attr[0])
                arr[attr[1]] = type(arr[attr[1]])(new)
            else:
                setattr(ch, attr, type(getattr(ch, attr))(new))
        self._draw_editor_controls()
        self._sync_from_engine()

    def _adjust_selected_editor_item(self, axis_value: float) -> None:
        if abs(axis_value) < 0.01:
            return
        if self.nav_scope != "editor":
            return
        # Unified all-stages grid: twist adjusts the focused cell directly.
        # All other branches below are legacy (pre/module editor) which the
        # cap path no longer enters, but they're left intact in case mouse
        # clicks still drop nav_scope into an old editor_nav_scope value.
        if self.editor_nav_scope == "stage_grid":
            self._adjust_unified_editor_cell(axis_value)
            return
        if self.editor_nav_scope == "transport":
            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                return
            span = self._channel_nav_span()
            self.editor_channel = (
                self.editor_channel + (1 if axis_value > 0 else -1)
            ) % span
            self._normalize_stage_selection(self.editor_channel)
            if self.selected_stage_key != "pre":
                self._normalize_module_editor_positions()
            self._sync_from_engine()
            return
        ch_top = self._current_channel()
        if self.editor_nav_scope == "comp-top":
            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                return
            order = ["COMP", "LIMIT", "GATE"]
            try:
                ii = order.index(self.comp_editor_mode)
            except ValueError:
                ii = 0
            self.comp_editor_mode = order[(ii + (1 if axis_value > 0 else -1)) % 3]
            self._sync_from_engine()
            return
        if self.editor_nav_scope == "eq-top":
            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                return
            nb = max(1, int(ch_top.eq_band_count))
            self.eq_selected_band = (
                int(self.eq_selected_band) + (1 if axis_value > 0 else -1)
            ) % nb
            self._sync_scalar_display_from_eq_band(ch_top)
            self._sync_from_engine()
            return
        if self.editor_nav_scope == "tone-top":
            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                return
            order = ["TRN", "CLR", "XCT"]
            try:
                ii = order.index(self.tone_editor_mode)
            except ValueError:
                ii = 0
            self.tone_editor_mode = order[(ii + (1 if axis_value > 0 else -1)) % 3]
            self._sync_from_engine()
            return
        if self.selected_stage_key == "pre":
            ch = self._current_channel()
            with self.engine._lock:
                if self.pre_editor_column == 0:
                    # CHANNEL column is just the CH knob now (the CH VOL
                    # fader was removed from the editor).
                    if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                        return
                    span = self._channel_nav_span()
                    self.editor_channel = (
                        self.editor_channel + (1 if axis_value > 0 else -1)
                    ) % span
                    self._normalize_stage_selection(self.editor_channel)
                elif self.pre_editor_column == 1:
                    if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                        return
                    span = self._channel_nav_span()
                    self.editor_channel = (
                        self.editor_channel + (1 if axis_value > 0 else -1)
                    ) % span
                    self._normalize_stage_selection(self.editor_channel)
                elif self.pre_editor_column == 2:
                    idx = self.pre_editor_positions["body"]
                    self.editor_selected["pre"] = idx
                    if idx == 0:
                        ch.lpf_hz = float(np.clip(ch.lpf_hz + axis_value * 30.0, POL_LOW_HZ, 1200.0))
                    elif idx == 4:
                        ch.hpf_hz = float(np.clip(ch.hpf_hz + axis_value * 260.0, 4000.0, POL_HIGH_HZ))
            self._sync_from_engine()
            return
        if self.selected_stage_key != "pre":
            ch = self._current_channel()
            with self.engine._lock:
                if self.module_editor_column == 0:
                    # CHANNEL column is just the CH knob now (the CH VOL
                    # fader was removed from the editor).
                    if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                        return
                    span = self._channel_nav_span()
                    self.editor_channel = (
                        self.editor_channel + (1 if axis_value > 0 else -1)
                    ) % span
                    self._normalize_stage_selection(self.editor_channel)
                    self._normalize_module_editor_positions()
                elif self.module_editor_column == 1:
                    if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                        return
                    span = self._channel_nav_span()
                    self.editor_channel = (
                        self.editor_channel + (1 if axis_value > 0 else -1)
                    ) % span
                    self._normalize_stage_selection(self.editor_channel)
                    self._normalize_module_editor_positions()
                elif self.module_editor_column == 2:
                    top_items, body_items = self._module_stage_items(ch)
                    idx = self.module_editor_positions["body"]
                    if idx < len(top_items):
                        label = top_items[idx][0]
                        if self.selected_stage_key == "comp":
                            enabled = self._comp_mode_enabled(ch, label)
                            new_state = axis_value > 0
                            if new_state != enabled:
                                self.comp_editor_mode = label
                                self._toggle_comp_mode_enabled(ch, label)
                        elif self.selected_stage_key == "eq":
                            if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
                                return
                            max_bands = max(1, ch.eq_band_count)
                            if axis_value > 0:
                                self.eq_selected_band = (self.eq_selected_band + 1) % max_bands
                            else:
                                self.eq_selected_band = (self.eq_selected_band - 1) % max_bands
                        elif self.selected_stage_key == "tone":
                            label = top_items[idx][0]
                            if label == "TRN":
                                val = 0.45 if axis_value > 0 else 0.0
                                ch.trn_attack = val
                                ch.trn_sustain = val * 0.8
                            elif label == "CLR":
                                ch.clr_drive = 0.45 if axis_value > 0 else 0.0
                            elif label == "XCT":
                                ch.xct_amount = 0.45 if axis_value > 0 else 0.0
                            ch.tone_enabled = any(v > 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount))
                    elif idx >= len(top_items):
                        body_idx = idx - len(top_items)
                        self.editor_selected[self.selected_stage_key] = body_idx
                        step = axis_value
                        if self.selected_stage_key == "harm":
                            if 0 <= body_idx <= 4:
                                ch.harmonics[body_idx] = float(np.clip(ch.harmonics[body_idx] + step * 0.05, 0.0, 1.0))
                            elif body_idx == 5:
                                ch.harmonic_makeup = float(np.clip(ch.harmonic_makeup + step * 0.08, 0.6, 2.4))
                        elif self.selected_stage_key == "comp":
                            if body_idx == 0:
                                ch.comp_threshold_db = float(
                                    np.clip(ch.comp_threshold_db + step * 1.0, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER)
                                )
                            elif body_idx == 1:
                                ch.comp_attack_ms = float(np.clip(ch.comp_attack_ms + step * 1.0, 0.8, 60.0))
                            elif body_idx == 2:
                                ch.comp_release_ms = float(np.clip(ch.comp_release_ms + step * 6.0, 20.0, 400.0))
                            elif body_idx == 3:
                                ch.comp_ratio = float(np.clip(ch.comp_ratio + step * 0.2, 1.0, 20.0))
                            elif body_idx == 4:
                                ch.comp_makeup = float(np.clip(ch.comp_makeup + step * 0.03, 0.6, 2.2))
                            elif body_idx == 5:
                                self._set_comp_mode_center(ch, self.comp_editor_mode, float(np.clip(self._comp_mode_center(ch, self.comp_editor_mode) * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ)))
                            elif body_idx == 6:
                                self._set_comp_mode_width(ch, self.comp_editor_mode, float(np.clip(self._comp_mode_width(ch, self.comp_editor_mode) + step * 0.08, 0.25, 6.0)))
                        elif self.selected_stage_key == "eq":
                            band = self._eq_band(ch)
                            if body_idx == 2:
                                band["freq"] = float(np.clip(float(band["freq"]) * (1.0 + step * 0.05), 80.0, 12000.0))
                            elif body_idx == 3:
                                band["gain_db"] = float(np.clip(float(band["gain_db"]) + step * 0.6, -18.0, 18.0))
                                band["enabled"] = True
                            elif body_idx == 4:
                                band["width"] = float(np.clip(float(band["width"]) + step * 0.06, 0.2, 4.0))
                            ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
                        elif self.selected_stage_key == "tone":
                            if self.tone_editor_mode == "TRN":
                                if body_idx == 0:
                                    ch.trn_freq = float(np.clip(ch.trn_freq * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ))
                                elif body_idx == 1:
                                    ch.trn_width = float(np.clip(ch.trn_width + step * 0.06, 0.2, 4.0))
                                elif body_idx == 2:
                                    ch.trn_attack = float(np.clip(ch.trn_attack + step * 0.04, 0.0, 1.0))
                                elif body_idx == 3:
                                    ch.trn_sustain = float(np.clip(ch.trn_sustain + step * 0.04, 0.0, 1.0))
                            elif self.tone_editor_mode == "CLR":
                                if body_idx == 0:
                                    ch.clr_drive = float(np.clip(ch.clr_drive + step * 0.04, 0.0, 1.0))
                                elif body_idx == 1:
                                    ch.clr_tone = float(np.clip(ch.clr_tone + step * 0.06, -1.0, 1.0))
                                elif body_idx == 2:
                                    ch.clr_mix = float(np.clip(ch.clr_mix + step * 0.04, 0.0, 1.0))
                                elif body_idx == 3:
                                    ch.clr_gain = float(np.clip(ch.clr_gain + step * 0.04, 0.5, 2.0))
                            elif self.tone_editor_mode == "XCT":
                                if body_idx == 0:
                                    ch.xct_freq = float(np.clip(ch.xct_freq * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ))
                                elif body_idx == 1:
                                    ch.xct_width = float(np.clip(ch.xct_width + step * 0.06, 0.2, 4.0))
                                elif body_idx == 2:
                                    ch.xct_amount = float(np.clip(ch.xct_amount + step * 0.04, 0.0, 1.0))
                                elif body_idx == 3:
                                    ch.xct_mix = float(np.clip(ch.xct_mix + step * 0.04, 0.0, 1.0))
                            ch.tone_enabled = any(v > 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount))
            self._sync_from_engine()
            return
        ch = self._current_channel()
        idx = self.editor_selected.get(self.selected_stage_key, 0)
        step = axis_value
        with self.engine._lock:
            if self.selected_stage_key == "pre":
                if idx == 0:
                    ch.lpf_hz = float(np.clip(ch.lpf_hz + step * 30.0, POL_LOW_HZ, 1200.0))
                elif idx == 4:
                    ch.hpf_hz = float(np.clip(ch.hpf_hz + step * 260.0, 4000.0, POL_HIGH_HZ))
            elif self.selected_stage_key == "harm":
                if 0 <= idx <= 4:
                    ch.harmonics[idx] = float(np.clip(ch.harmonics[idx] + step * 0.05, 0.0, 1.0))
                elif idx == 5:
                    ch.harmonic_makeup = float(np.clip(ch.harmonic_makeup + step * 0.08, 0.6, 2.4))
            elif self.selected_stage_key == "comp":
                if idx == 0:
                    ch.comp_threshold_db = float(
                        np.clip(ch.comp_threshold_db + step * 1.0, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER)
                    )
                elif idx == 1:
                    ch.comp_attack_ms = float(np.clip(ch.comp_attack_ms + step * 1.0, 0.8, 60.0))
                elif idx == 2:
                    ch.comp_release_ms = float(np.clip(ch.comp_release_ms + step * 6.0, 20.0, 400.0))
                elif idx == 3:
                    ch.comp_ratio = float(np.clip(ch.comp_ratio + step * 0.2, 1.0, 20.0))
                elif idx == 4:
                    ch.comp_makeup = float(np.clip(ch.comp_makeup + step * 0.03, 0.6, 2.2))
                elif idx == 5:
                    self._set_comp_mode_center(ch, self.comp_editor_mode, float(np.clip(self._comp_mode_center(ch, self.comp_editor_mode) * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ)))
                elif idx == 6:
                    self._set_comp_mode_width(ch, self.comp_editor_mode, float(np.clip(self._comp_mode_width(ch, self.comp_editor_mode) + step * 0.08, 0.25, 6.0)))
            elif self.selected_stage_key == "eq":
                band = self._eq_band(ch)
                if idx == 2:
                    band["freq"] = float(np.clip(float(band["freq"]) * (1.0 + step * 0.05), 80.0, 12000.0))
                elif idx == 3:
                    band["gain_db"] = float(np.clip(float(band["gain_db"]) + step * 0.6, -18.0, 18.0))
                    band["enabled"] = True
                elif idx == 4:
                    band["width"] = float(np.clip(float(band["width"]) + step * 0.06, 0.2, 4.0))
                ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
            elif self.selected_stage_key == "tone":
                if self.tone_editor_mode == "TRN":
                    if idx == 0:
                        ch.trn_freq = float(np.clip(ch.trn_freq * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ))
                    elif idx == 1:
                        ch.trn_width = float(np.clip(ch.trn_width + step * 0.06, 0.2, 4.0))
                    elif idx == 2:
                        ch.trn_attack = float(np.clip(ch.trn_attack + step * 0.04, 0.0, 1.0))
                    elif idx == 3:
                        ch.trn_sustain = float(np.clip(ch.trn_sustain + step * 0.04, 0.0, 1.0))
                elif self.tone_editor_mode == "CLR":
                    if idx == 0:
                        ch.clr_drive = float(np.clip(ch.clr_drive + step * 0.04, 0.0, 1.0))
                    elif idx == 1:
                        ch.clr_tone = float(np.clip(ch.clr_tone + step * 0.06, -1.0, 1.0))
                    elif idx == 2:
                        ch.clr_mix = float(np.clip(ch.clr_mix + step * 0.04, 0.0, 1.0))
                    elif idx == 3:
                        ch.clr_gain = float(np.clip(ch.clr_gain + step * 0.04, 0.5, 2.0))
                elif self.tone_editor_mode == "XCT":
                    if idx == 0:
                        ch.xct_freq = float(np.clip(ch.xct_freq * (1.0 + step * 0.05), POL_LOW_HZ, POL_HIGH_HZ))
                    elif idx == 1:
                        ch.xct_width = float(np.clip(ch.xct_width + step * 0.06, 0.2, 4.0))
                    elif idx == 2:
                        ch.xct_amount = float(np.clip(ch.xct_amount + step * 0.04, 0.0, 1.0))
                    elif idx == 3:
                        ch.xct_mix = float(np.clip(ch.xct_mix + step * 0.04, 0.0, 1.0))
                ch.tone_enabled = any(v > 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount))
        self._sync_from_engine()

    def _editor_item_count(self) -> int:
        if self.selected_stage_key == "pre" and self.nav_scope == "editor":
            return [2, len(self._console_stage_keys()), 5][self.pre_editor_column]
        if self.editor_nav_scope == "comp-top":
            return 3
        if self.editor_nav_scope == "eq-top":
            return max(1, self._current_channel().eq_band_count)
        if self.editor_nav_scope == "tone-top":
            return 3
        return {"pre": 5, "harm": 6, "comp": 7, "eq": 5, "tone": 4}[self.selected_stage_key]

    def _enter_editor_from_console(self, column: int = 0) -> None:
        """Hop from the strip view into the editor at ``column``
        (0 = first stage column / PRE, ``len(_STAGE_GRID)-1`` = TON)."""
        self._capture_editor_return_context()
        cols = len(self._STAGE_GRID)
        column = max(0, min(cols - 1, column))
        # Bind the editor to the strip the cap was on so the editor opens
        # showing the same channel.
        self.editor_channel = self.selected_channel
        self.nav_scope = "editor"
        self.editor_unified_header_focus = False
        self.editor_stage_col = column
        # Try to keep the cap row sensible across column changes.
        self.editor_param_row = self._unified_pick_param_row_entering_stage(
            column, getattr(self, "editor_param_row", 0)
        )
        self.selected_stage_key = self._STAGE_GRID[column][0]
        self.editor_nav_scope = "stage_grid"
        self._sync_from_engine()

    def _handle_console_nav(self, target: str) -> None:
        stage_keys = self._console_stage_keys()
        if self.console_row == "stages":
            stage_idx = stage_keys.index(self.selected_stage_key)
        else:
            stage_idx = 0
        is_input_channel = self.selected_channel < len(self.engine.channels)
        nav_span = self._channel_nav_span()
        if target == "left":
            if self.selected_channel == 0:
                self.selected_channel = nav_span - 1
            else:
                self.selected_channel -= 1
            if self.console_row == "record" and not (self.selected_channel < len(self.engine.channels)):
                self.console_row = "stages"
                self.selected_stage_key = self._console_stage_keys()[0]
            elif self.console_row == "stages":
                self._normalize_console_selection()
        elif target == "right":
            if self.selected_channel == nav_span - 1:
                self.selected_channel = 0
            else:
                self.selected_channel += 1
            if self.console_row == "record" and not (self.selected_channel < len(self.engine.channels)):
                self.console_row = "stages"
                self.selected_stage_key = self._console_stage_keys()[0]
            elif self.console_row == "stages":
                self._normalize_console_selection()
        elif target == "up":
            # Visual strip (inputs): waveform (no focus), REC — STAGES — ID — knob — fader — footer.
            # Nav ring skips waveform + ID-only band.
            if self.console_row == "footer":
                self.console_row = "fader"
            elif self.console_row == "fader":
                self.console_row = "knob"
            elif self.console_row == "knob":
                self.console_row = "stages"
                self._normalize_console_selection()
                self.selected_stage_key = stage_keys[-1]
            elif self.console_row == "record":
                # REC is below waveform only — wrap upward to footer / bottom of strip ring.
                self.console_row = "footer"
            else:
                if stage_idx == 0:
                    # Wrap past top of stages row to REC (below waveform).
                    self.console_row = "record"
                else:
                    self.selected_stage_key = stage_keys[(stage_idx - 1) % len(stage_keys)]
        elif target == "down":
            if self.console_row == "footer":
                # Wrap within the strip focus ring; transport is hold-DOWN / macro only.
                self.console_row = "record"
                self._sync_from_engine()
                return
            elif self.console_row == "fader":
                self.console_row = "footer"
            elif self.console_row == "knob":
                self.console_row = "fader"
            elif self.console_row == "record":
                self.console_row = "stages"
                self.selected_stage_key = stage_keys[0]
            elif stage_idx == len(stage_keys) - 1:
                # Bottom of STAGES matrix — pan/send row below IDs.
                self.console_row = "knob"
            else:
                self.selected_stage_key = stage_keys[(stage_idx + 1) % len(stage_keys)]
        elif target in ("press", "back"):
            if self.console_row == "footer":
                if target == "press":
                    self._toggle_solo(self.selected_channel)
                elif target == "back":
                    self._toggle_mute(self.selected_channel)
                return
            if self.console_row == "fader":
                if target == "press" and is_input_channel:
                    # Fader press toggles MUTE (the fader is the gain bus,
                    # so mute lives next to it conceptually).
                    self._toggle_mute(self.selected_channel)
                return
            if self.console_row == "knob":
                if target == "press" and is_input_channel:
                    # PAN -> SEND: enter SEND mode and pick the active
                    # send bus (every channel's send_slot snaps to the
                    # focused channel's index+1).
                    # SEND -> PAN: exit SEND mode (slots are left intact
                    # so re-entering SEND restores the same slot until
                    # another knob is pressed).
                    if not self.knobs_send_mode:
                        self.knobs_send_mode = True
                        target_slot = self.selected_channel + 1
                        with self.engine._lock:
                            for ch in self.engine.channels:
                                ch.send_slot = target_slot
                    else:
                        self.knobs_send_mode = False
                elif target == "back":
                    # BACK always returns the row to PAN, regardless of
                    # which knob was last pressed.
                    self.knobs_send_mode = False
                return
            if self.console_row == "record":
                if target == "press" and is_input_channel:
                    self._toggle_record_arm(self.selected_channel)
                return
            if target == "press":
                self._toggle_or_open_stage_from_console(self.selected_channel, self.selected_stage_key)
                return
            self._sync_from_engine()

    def _transport_button_at(self, row: int, col: int) -> tuple[str, str] | None:
        """Look up (key, label) for the transport button at (row, col), or None if no such button."""
        for r, c, key, label, _color, _glyph in self._TRANSPORT_BUTTONS:
            if r == row and c == col:
                return key, label
        return None

    def _enter_transport_panel(self, row: int = 0, col: int = 0, source: str = "console") -> None:
        self.nav_scope = "transport"
        # 12 cols x 2 rows grid (transport moved under the channel strips;
        # cols 0-5 carry the wired keys, cols 6-11 are blank placeholders).
        self.transport_focus_row = max(0, min(self.TRANSPORT_ROWS - 1, row))
        self.transport_focus_col = max(0, min(self.TRANSPORT_COLS - 1, col))
        self._transport_entered_from = source
        self._redraw_transport_focus()

    def _exit_transport_to_console(self) -> None:
        n = self._channel_nav_span()
        if n > 0:
            c = int(getattr(self, "transport_focus_col", 0))
            self.selected_channel = max(0, min(n - 1, c))
            self.editor_channel = self.selected_channel
        self.nav_scope = "console"
        self.console_row = "footer"
        self._transport_entered_from = None
        self._redraw_transport_focus()
        self._sync_from_engine()

    def _exit_transport_to_console_at_strip(self, side: str = "left") -> None:
        """Leave the transport panel and land on the console strip view at
        ``side`` ("left" = CH01 / first input, "right" = master / last).
        Used by the single-ring wrap (RIGHT off transport col 1 -> CH01)."""
        n = self._channel_nav_span()
        self.nav_scope = "console"
        self.console_row = "stages"
        self._transport_entered_from = None
        if n > 0:
            self.selected_channel = (n - 1) if side == "right" else 0
            self.editor_channel = self.selected_channel
            self._normalize_console_selection()
        self._redraw_transport_focus()
        self._sync_from_engine()

    # ------------------------------------------------------------------ #
    # Knob row navigation (per-channel SEND-LEVEL knobs in the strip view)
    # ------------------------------------------------------------------ #
    def _enter_knob_row(self, channel: int = 0, source: str = "editor") -> None:
        """Land the cap on the knob row at ``channel`` (0-based, capped at the
        last input channel; master strip does not have a navigable knob)."""
        n = len(self.engine.channels)
        if n == 0:
            return
        self.nav_scope = "knobs"
        self.knob_focus_channel = max(0, min(n - 1, channel))
        self._knobs_entered_from = source
        self._sync_from_engine()

    def _exit_knobs_to_editor(self) -> None:
        """Return from the knob row back into the editor on its right-most
        column (BODY). The old right (SENDS / SMR) column was removed when
        the editor was collapsed to 3 columns, so BODY is the rightmost
        landing spot now."""
        self._capture_editor_return_context()
        self.nav_scope = "editor"
        self._knobs_entered_from = None
        if self.selected_stage_key == "pre":
            self.pre_editor_column = 2
            self.editor_nav_scope = "pre-body"
        else:
            self.module_editor_column = 2
            self.editor_nav_scope = "module-body"
        self._sync_from_engine()

    def _exit_knobs_to_console(self) -> None:
        self.nav_scope = "console"
        self.console_row = "footer"
        self._knobs_entered_from = None
        self._sync_from_engine()

    def _handle_knobs_nav(self, target: str) -> None:
        """Cap nav inside the knob row.

        - LEFT / RIGHT:   walk between channel knobs.
        - PRESS:          set every channel's send_slot to the focused
                          channel's index+1 (selecting the active send bus).
        - DOWN:           no-op (faders scope is hold-DOWN / macro from strips).
        - UP:             no-op (top of the in-strip nav stack for now).
        - BACK:           return to the scope the cap entered the knob row
                          from (editor SENDS column or console footer).
        """
        n = len(self.engine.channels)
        if n == 0:
            return
        if target == "left":
            self.knob_focus_channel = (self.knob_focus_channel - 1) % n
        elif target == "right":
            self.knob_focus_channel = (self.knob_focus_channel + 1) % n
        elif target == "press":
            idx = self.knob_focus_channel
            if 0 <= idx < n:
                # Toggle the row's PAN <-> SEND mode (mirrors the console
                # knob-row press path). Entering SEND also picks the focused
                # channel as the active send bus; exiting goes back to PAN.
                if not self.knobs_send_mode:
                    self.knobs_send_mode = True
                    target_slot = idx + 1
                    with self.engine._lock:
                        for ch in self.engine.channels:
                            ch.send_slot = target_slot
                else:
                    self.knobs_send_mode = False
        elif target == "down":
            self._sync_from_engine()
            return
        elif target == "back":
            # BACK collapses the row back to PAN before unwinding the scope
            # so the operator never gets stuck staring at SEND knobs.
            self.knobs_send_mode = False
            if self._knobs_entered_from == "editor":
                self._exit_knobs_to_editor()
            else:
                self._exit_knobs_to_console()
            return
        # UP intentionally falls through (no row above the knobs yet).
        self._sync_from_engine()

    def _enter_fader_row(self, channel: int = 0, source: str = "knobs") -> None:
        """Land the cap on the fader row (``nav_scope == "faders"``).

        Typically entered via hold-LEFT / macro, not from discrete keys alone.
        """
        n = len(self.engine.channels)
        if n == 0:
            return
        self.nav_scope = "faders"
        self.fader_focus_channel = max(0, min(n - 1, channel))
        self._faders_entered_from = source
        self._sync_from_engine()

    def _exit_faders_to_knobs(self) -> None:
        """Climb back from the fader row up to the knob row at the same
        channel index."""
        n = len(self.engine.channels)
        if n == 0:
            self._exit_faders_to_console()
            return
        self.nav_scope = "knobs"
        self.knob_focus_channel = max(0, min(n - 1, self.fader_focus_channel))
        # Knob row remembers it came from the fader row so a BACK from the
        # knobs can collapse the whole stack cleanly.
        self._knobs_entered_from = "faders"
        self._faders_entered_from = None
        self._sync_from_engine()

    def _exit_faders_to_console(self) -> None:
        self.nav_scope = "console"
        self.console_row = "footer"
        self._faders_entered_from = None
        self._sync_from_engine()

    def _handle_faders_nav(self, target: str) -> None:
        """Cap nav inside the fader row.

        - LEFT / RIGHT:   walk between channel faders.
        - UP:             no-op (leave faders scope via hold UP / LEFT / RIGHT / DOWN macros).
        - PRESS:          toggle the focused channel's MUTE (faders are
                          volume-bus controls, so mute lives next to gain).
        - DOWN:           no-op (bottom of the in-strip nav stack).
        - BACK:           collapse back to whatever scope the knob row was
                          entered from.
        """
        n = len(self.engine.channels)
        if n == 0:
            return
        if target == "left":
            self.fader_focus_channel = (self.fader_focus_channel - 1) % n
        elif target == "right":
            self.fader_focus_channel = (self.fader_focus_channel + 1) % n
        elif target == "up":
            self._sync_from_engine()
            return
        elif target == "press":
            idx = self.fader_focus_channel
            if 0 <= idx < n:
                self._toggle_mute(idx)
        elif target == "back":
            if self._faders_entered_from == "knobs":
                self._exit_faders_to_knobs()
            else:
                self._exit_faders_to_console()
            return
        # DOWN intentionally falls through (nothing below the fader row).
        self._sync_from_engine()

    def _adjust_fader_gain_axis(self, axis_value: float) -> None:
        """Translate a SpaceMouse twist into a gain change on the focused
        fader. Mirrors :meth:`_adjust_send_level_axis` but writes ch.gain."""
        if abs(axis_value) < 0.01:
            return
        n = len(self.engine.channels)
        idx = self.fader_focus_channel
        if not (0 <= idx < n):
            return
        ch = self.engine.channels[idx]
        with self.engine._lock:
            ch.gain = float(np.clip(ch.gain + axis_value * 0.04, 0.3, 2.2))
        self._sync_from_engine()

    def _editor_active_column(self) -> int:
        """Return the active editor column index (0=left .. 2=body),
        whichever editor variant (pre vs. module) is currently shown."""
        if self.selected_stage_key == "pre":
            return self.pre_editor_column
        return self.module_editor_column

    def _exit_editor_to_console_at_strip(self, side: str) -> None:
        """Leave the editor and land on the console at ``side``
        ("left" = first input strip, "right" = master strip / last)."""
        n = self._channel_nav_span()
        if n <= 0:
            self._exit_editor_to_console()
            return
        if side == "right":
            self.selected_channel = n - 1
        else:
            self.selected_channel = 0
        self.editor_channel = self.selected_channel
        self.nav_scope = "console"
        self.console_row = "stages"
        self.editor_nav_scope = "body"
        self._normalize_console_selection()
        self._sync_from_engine()

    def _exit_transport_to_editor(self, column: int = 3) -> None:
        """Hop from transport back into the unified editor grid. ``column``
        is the editor stage column (0..len(_STAGE_GRID)-1). When called from
        legacy paths with column==3 (the old SENDS column index), we land
        on the rightmost stage column (TON) which is the new ring tail."""
        cols = len(self._STAGE_GRID)
        if column >= cols:
            column = cols - 1
        column = max(0, min(cols - 1, column))
        self.nav_scope = "editor"
        self._transport_entered_from = None
        self.editor_unified_header_focus = False
        self.editor_stage_col = column
        params = self._STAGE_GRID[column][2]
        bottom = max(0, len(params) - 1) if params else 0
        # Prefer last row for this stage; if we remembered a row from before
        # transport, restore it instead of snapping to bottom.
        self.editor_param_row = self._unified_pick_param_row_entering_stage(
            column, bottom
        )
        self.selected_stage_key = self._STAGE_GRID[column][0]
        self.editor_nav_scope = "stage_grid"
        self._redraw_transport_focus()
        self._sync_from_engine()

    def _handle_transport_nav(self, target: str) -> None:
        """Transport grid: **no wrap** on left/right/top — past an edge, exit to mixer strips.

        DOWN moves to the lower row; DOWN from the bottom row wraps to row 0.
        PRESS runs the wired key. BACK also exits (same landing as edge-out).
        """
        rows = self.TRANSPORT_ROWS
        cols = self.TRANSPORT_COLS
        r, c = int(self.transport_focus_row), int(self.transport_focus_col)
        if target == "left":
            if c <= 0:
                self._exit_transport_to_console()
                return
            self.transport_focus_col = c - 1
        elif target == "right":
            if c >= cols - 1:
                self._exit_transport_to_console()
                return
            self.transport_focus_col = c + 1
        elif target == "up":
            if r <= 0:
                self._exit_transport_to_console()
                return
            self.transport_focus_row = r - 1
        elif target == "down":
            if r >= rows - 1:
                self.transport_focus_row = 0
            else:
                self.transport_focus_row = r + 1
        elif target == "press":
            entry = self._transport_button_at(self.transport_focus_row, self.transport_focus_col)
            if entry is not None:
                key, _label = entry
                handler = getattr(self, f"_tx_{key}", None) or (lambda k=key: self._tx_stub(k))
                handler()
            else:
                # Blank placeholder cell -- no wired action yet, but log the
                # press so it's visible we hit a real cell.
                _log.debug("TRANSPORT placeholder press at (row=%d, col=%d)", self.transport_focus_row, self.transport_focus_col)
            return
        elif target == "back":
            self._exit_transport_to_console()
            return
        self._redraw_transport_focus()

    def _redraw_transport_focus(self) -> None:
        # Highlight by (row, col) so blank placeholder cells light up too
        # when the cap walks over them (the wired-key dict only covers the
        # mapped buttons; cap can still focus an empty cell).
        focused_pos: tuple[int, int] | None = None
        if self.nav_scope == "transport":
            focused_pos = (self.transport_focus_row, self.transport_focus_col)
        wired_positions = {
            (r, c): key for r, c, key, *_rest in self._TRANSPORT_BUTTONS
        }
        gm = getattr(getattr(self, "engine", None), "generator_mode", "none")

        def _gen_lit_at(pos: tuple[int, int]) -> bool:
            k = wired_positions.get(pos)
            if k == "oscillator":
                return gm == "osc"
            if k == "pink":
                return gm == "pink"
            if k == "white":
                return gm == "white"
            return False

        for pos, cell in getattr(self, "_transport_cells", {}).items():
            if not isinstance(cell, tk.Frame):
                continue
            if pos == focused_pos:
                cell.configure(highlightbackground="#7cf0a9", highlightthickness=2)
            elif _gen_lit_at(pos):
                cell.configure(highlightbackground="#fbbf24", highlightthickness=2)
            else:
                cell.configure(
                    highlightbackground="#2a3848" if pos in wired_positions else "#1d2530",
                    highlightthickness=1,
                )

    def _editor_row_sequence(self) -> list[str]:
        if self.selected_stage_key == "pre":
            return ["pre-left", "pre-stage", "pre-body"]
        return ["module-left", "module-stage", "module-body"]

    def _set_editor_nav_scope(self, scope: str) -> None:
        if self.selected_stage_key == "pre" and scope.startswith("pre-"):
            self.editor_nav_scope = scope
            self.pre_editor_column = {"pre-left": 0, "pre-stage": 1, "pre-body": 2}.get(scope, self.pre_editor_column)
            return
        if self.selected_stage_key != "pre" and scope.startswith("module-"):
            self.editor_nav_scope = scope
            self.module_editor_column = {"module-left": 0, "module-stage": 1, "module-body": 2}.get(scope, self.module_editor_column)
            return
        self.editor_nav_scope = scope
        if self.selected_stage_key == "comp":
            self.comp_nav_row = "top" if scope == "comp-top" else "bottom"
        elif self.selected_stage_key == "eq":
            self.eq_nav_row = "top" if scope == "eq-top" else "bottom"
        elif self.selected_stage_key == "tone":
            self.tone_nav_row = "top" if scope == "tone-top" else "bottom"

    def _exit_editor_to_console(self) -> None:
        """Return from editor to strip view without jumping to a stale channel."""
        self.selected_channel = self.editor_channel
        self.nav_scope = "console"
        self.console_row = "stages"
        self.editor_nav_scope = "body"
        self._normalize_console_selection()
        self._sync_from_engine()

    def _exit_editor_to_console_keep_channel(self) -> None:
        """Same as `_exit_editor_to_console` — explicit name for capsule back/pull routing."""

        self._exit_editor_to_console()

    def _focus_transport_play_cell(self, *, source: str) -> None:
        """Jump to transport UI with focus on the PLY key (does not start playback)."""
        self.nav_scope = "transport"
        self.transport_focus_row = 0
        self.transport_focus_col = 0
        for r, c, key, *_ in self._TRANSPORT_BUTTONS:
            if key == "play":
                self.transport_focus_row, self.transport_focus_col = int(r), int(c)
                break
        self._transport_entered_from = source
        self._redraw_transport_focus()

    def _coerce_editor_nav_to_unified_stage_grid(self) -> None:
        """Use the painted matrix column (``editor_stage_col``) whenever nav is stuck in legacy scope.

        ``module-*`` / ``body`` would route PRESS through :meth:`_handle_module_editor_nav` and toggle
        coarse ``*_enabled``. Polar ``selected_stage_key`` tracks the cap column after coercion."""

        ens = getattr(self, "editor_nav_scope", "") or ""
        ens = ens if isinstance(ens, str) else str(ens)
        if ens == "faders":
            return
        if ens.startswith("pre-"):
            return
        if ens in ("transport", "comp-top", "eq-top", "tone-top", "utility"):
            return
        if ens == "stage_grid":
            return
        # Orphan scopes: unified grid is what you see — these used to swallow PRESS or toggle *_enabled.
        orphan = (
            ens in ("module-left", "module-stage", "module-body", "body", "stage")
            or ens.strip() == ""
        )
        if not orphan:
            return
        ncols = len(self._STAGE_GRID)
        if ncols <= 0:
            return
        fc = max(0, min(ncols - 1, int(getattr(self, "editor_stage_col", 0))))
        stage_key = self._STAGE_GRID[fc][0]
        unify_ix = {row[0]: ri for ri, row in enumerate(self._STAGE_GRID)}
        if stage_key not in unify_ix:
            return
        plist = self._STAGE_GRID[fc][2]
        pr = int(getattr(self, "editor_param_row", 0))
        if plist:
            pr = max(0, min(len(plist) - 1, pr))

        self.editor_nav_scope = "stage_grid"
        self.editor_stage_col = fc
        self.editor_param_row = pr if plist else 0
        self.selected_stage_key = stage_key

    def _handle_nav(self, target: str) -> None:
        _log.debug(
            "NAV %s | scope=%s stage=%s col=%s body=%s editor_nav=%s",
            target, self.nav_scope, self.selected_stage_key,
            self.module_editor_column, self.module_editor_positions.get("body"),
            self.editor_nav_scope,
        )
        try:
            # Cross-section moves use hold / double-tilt macros (_run_cardinal_double_tap_macro),
            # not pull_scope_toggle (removed) or strip-edge wraps.
            if self.nav_scope == "transport":
                self._handle_transport_nav(target)
                return
            if self.nav_scope == "knobs":
                self._handle_knobs_nav(target)
                return
            if self.nav_scope == "faders":
                self._handle_faders_nav(target)
                return
            if self.nav_scope == "console":
                self._handle_console_nav(target)
                return
            if self.nav_scope == "editor":
                if (
                    self.editor_nav_scope == "transport"
                    and self._handle_editor_transport_nav(target)
                ):
                    return
                self._coerce_editor_nav_to_unified_stage_grid()
                ens = getattr(self, "editor_nav_scope", "")
                if ens == "stage_grid":
                    self._handle_unified_editor_nav(target)
                    return
                if ens in ("pre-left", "pre-stage", "pre-body"):
                    self._handle_pre_editor_nav(target)
                    return
                if ens in ("module-left", "module-stage", "module-body"):
                    self._handle_module_editor_nav(target)
                    return
                if ens in ("comp-top", "eq-top", "tone-top"):
                    self._handle_stage_top_nav(target)
                    return
                self._sync_from_engine()
                return
        except Exception:
            import traceback
            _log.error("NAV EXCEPTION:\n%s", traceback.format_exc())
        _log.debug(
            "NAV DONE | scope=%s stage=%s col=%s body=%s",
            self.nav_scope, self.selected_stage_key,
            self.module_editor_column, self.module_editor_positions.get("body"),
        )

    def _module_editor_count_for_key(self, key: str) -> int:
        if key == "left":
            return 1
        if key == "stage":
            return len(self._console_stage_keys())
        if key == "body":
            return max(1, self._module_editor_body_count())
        return 1

    def _reset_module_body_selection(self) -> None:
        ch = self._current_channel()
        new_stage = self.selected_stage_key
        last_stage = getattr(self, "_module_body_last_stage", None)
        # Stash the body position we're leaving behind under the OLD stage's key
        # so we can restore it next time the user lands back on that stage.
        if last_stage and last_stage != new_stage:
            self._module_body_memory[last_stage] = self.module_editor_positions["body"]
        if new_stage == "eq":
            top_items, _ = self._module_stage_items(ch)
            # EQ body position is bound to the selected band, which can change
            # for reasons unrelated to navigation. Keep its existing reset
            # semantics rather than restoring a stale band index from memory.
            self.module_editor_positions["body"] = min(self.eq_selected_band, max(0, len(top_items) - 1)) if top_items else 0
        else:
            remembered = self._module_body_memory.get(new_stage, 0)
            body_count = max(1, self._module_editor_body_count(ch))
            self.module_editor_positions["body"] = max(0, min(body_count - 1, remembered))
        self._module_body_last_stage = new_stage

    def _activate_module_body_selection(self) -> None:
        ch = self._current_channel()
        idx = self.module_editor_positions["body"]
        top_items, body_items = self._module_stage_items(ch)
        if idx < len(top_items):
            label = top_items[idx][0]
            if self.selected_stage_key == "comp":
                self.comp_editor_mode = label
                self._toggle_comp_top()
            elif self.selected_stage_key == "eq":
                self.eq_selected_band = idx
                band = self._eq_band(ch)
                band["enabled"] = not bool(band["enabled"])
                ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
                self._sync_from_engine()
            elif self.selected_stage_key == "tone":
                self.tone_editor_mode = label
            return
        body_idx = idx - len(top_items)
        if 0 <= body_idx < len(body_items):
            label = body_items[body_idx][0]
            self.editor_selected[self.selected_stage_key] = body_idx
            self._activate_editor_item(body_idx, label)

    def _handle_editor_transport_nav(self, target: str) -> bool:
        """Solo / Mute / Rec row: left/right = move between buttons; twist/axis = channel (see _adjust_selected_editor_item)."""
        if self.editor_nav_scope != "transport":
            return False
        idx = self._active_channel_index()
        n_in = len(self.engine.channels)
        if target == "left":
            self.editor_transport_selected = (self.editor_transport_selected - 1) % 3
        elif target == "right":
            self.editor_transport_selected = (self.editor_transport_selected + 1) % 3
        elif target == "down":
            if self.selected_stage_key == "pre":
                self.pre_editor_column = 0
                self.pre_editor_positions["left"] = 0
                self.editor_nav_scope = "pre-left"
            else:
                self.module_editor_column = 0
                self.module_editor_positions["left"] = 0
                self.editor_nav_scope = "module-left"
        elif target == "press":
            if idx < n_in:
                if self.editor_transport_selected == 0:
                    self._toggle_solo(idx)
                elif self.editor_transport_selected == 1:
                    self._toggle_mute(idx)
                else:
                    self._toggle_record_arm(idx)
        elif target == "back":
            self._sync_from_engine()
            return True
        self._sync_from_engine()
        return True

    def _unified_commit_param_row_for_col(self, stage_col: int, row: int) -> None:
        """Remember cap row for this stage column (round-trips via other columns)."""
        if not (0 <= stage_col < len(self._STAGE_GRID)):
            return
        sk, _h, plist = self._STAGE_GRID[stage_col]
        if not plist:
            return
        self._unified_editor_param_row_by_stage[sk] = max(
            0, min(len(plist) - 1, row)
        )

    def _unified_pick_param_row_entering_stage(
        self, stage_col: int, fallback_row: int, *, neighbor_row_priority: bool = False
    ) -> int:
        """Pick param row index when ``editor_stage_col`` becomes ``stage_col``.

        If ``neighbor_row_priority`` (LEFT/RIGHT in unified grid): use the row we
        are leaving, clamped to this column — same visual band as UP/DOWN in-column.
        Otherwise restore per-stage memory (opening editor / return from transport)."""
        if not (0 <= stage_col < len(self._STAGE_GRID)):
            return 0
        sk, _h, plist = self._STAGE_GRID[stage_col]
        if not plist:
            return 0
        lo, hi = 0, len(plist) - 1
        if neighbor_row_priority:
            return max(lo, min(hi, int(fallback_row)))
        stored = self._unified_editor_param_row_by_stage.get(sk)
        if stored is not None:
            return max(lo, min(hi, stored))
        return max(lo, min(hi, fallback_row))

    def _handle_stage_top_nav(self, target: str) -> None:
        """Cap moves on COMP/LIMIT/GATE • EQ bands • TRN/CLR/XCT top icon rows."""

        ch = self._current_channel()
        sk = self.selected_stage_key
        if sk == "comp":
            order = ["COMP", "LIMIT", "GATE"]
            try:
                ii = order.index(self.comp_editor_mode)
            except ValueError:
                ii = 0
            if target == "left":
                self.comp_editor_mode = order[(ii - 1) % 3]
            elif target == "right":
                self.comp_editor_mode = order[(ii + 1) % 3]
            elif target == "down":
                self._set_editor_nav_scope("module-body")
            elif target == "press":
                self._toggle_comp_top()
            elif target == "back":
                pass
        elif sk == "eq":
            nb = max(1, int(ch.eq_band_count))
            if target == "left":
                self.eq_selected_band = (int(self.eq_selected_band) - 1) % nb
            elif target == "right":
                self.eq_selected_band = (int(self.eq_selected_band) + 1) % nb
            elif target == "down":
                self._set_editor_nav_scope("module-body")
                self._sync_scalar_display_from_eq_band(ch)
            elif target == "press":
                band = self._eq_band(ch)
                order_types = ["BELL", "LOW SHELF", "HIGH SHELF", "LPF", "HPF"]
                try:
                    ix = order_types.index(str(band.get("type", "BELL")))
                except ValueError:
                    ix = 0
                band["type"] = order_types[(ix + 1) % len(order_types)]
                band["enabled"] = True
                ch.eq_enabled = any(
                    b["enabled"] and abs(float(b["gain_db"])) > 0.05
                    for b in ch.eq_bands[: max(1, ch.eq_band_count)]
                )
                self._sync_scalar_display_from_eq_band(ch)
            elif target == "back":
                pass
        elif sk == "tone":
            order = ["TRN", "CLR", "XCT"]
            try:
                ii = order.index(self.tone_editor_mode)
            except ValueError:
                ii = 0
            if target == "left":
                self.tone_editor_mode = order[(ii - 1) % 3]
            elif target == "right":
                self.tone_editor_mode = order[(ii + 1) % 3]
            elif target == "down":
                self._set_editor_nav_scope("module-body")
            elif target == "press":
                self._toggle_tone_top()
            elif target == "back":
                pass
        self._draw_editor_controls()
        self._sync_from_engine()

    def _handle_unified_editor_nav(self, target: str) -> None:
        """Cap navigation across the unified all-stages editor grid.

        Layout: ``len(_STAGE_GRID)`` columns, each with its own param list.
        Focus is (``editor_stage_col``, ``editor_param_row``). Leaving toward the
        mixer uses hold-gating on past-edge LEFT/RIGHT; see ``_poll_editor_leave_hold_gate``.

        UP from the top param row moves to the column header (stage bypass);
        DOWN from the header returns to the param rows. LEFT/RIGHT move across
        columns and exit the header lane (param row is preserved). Leaving
        toward the mixer uses hold-gating on past-edge LEFT/RIGHT; see
        ``_poll_editor_leave_hold_gate``.
        """
        cols = len(self._STAGE_GRID)
        col = max(0, min(cols - 1, self.editor_stage_col))
        params = self._STAGE_GRID[col][2]
        rows = max(1, len(params))
        row = max(0, min(rows - 1, self.editor_param_row))
        self.editor_nav_scope = "stage_grid"

        hdr_now = getattr(self, "editor_unified_header_focus", False)
        if target == "left":
            if col == 0:
                # Leaving the matrix is hold-gated (_poll_editor_leave_hold_gate).
                self._sync_from_engine()
                return
            if hdr_now:
                # Stay in the header lane: do not use ``neighbor_row_priority`` clamp — that read
                # ``editor_param_row`` from deep rows (saved when stepping UP onto the header)
                # and made LEFT/RIGHT look like diagonal moves into shorter columns.
                self._unified_commit_param_row_for_col(col, row)
                self.editor_stage_col = col - 1
                self.editor_unified_header_focus = True
                nrows = len(self._STAGE_GRID[self.editor_stage_col][2])
                self.editor_param_row = max(0, min(nrows - 1, row))
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
                self._unified_commit_param_row_for_col(self.editor_stage_col, self.editor_param_row)
            else:
                self.editor_unified_header_focus = False
                self._unified_commit_param_row_for_col(col, row)
                self.editor_stage_col = col - 1
                self.editor_param_row = self._unified_pick_param_row_entering_stage(
                    self.editor_stage_col, row, neighbor_row_priority=True
                )
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
        elif target == "right":
            if col == cols - 1:
                self._sync_from_engine()
                return
            if hdr_now:
                self._unified_commit_param_row_for_col(col, row)
                self.editor_stage_col = col + 1
                self.editor_unified_header_focus = True
                nrows = len(self._STAGE_GRID[self.editor_stage_col][2])
                self.editor_param_row = max(0, min(nrows - 1, row))
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
                self._unified_commit_param_row_for_col(self.editor_stage_col, self.editor_param_row)
            else:
                self.editor_unified_header_focus = False
                self._unified_commit_param_row_for_col(col, row)
                self.editor_stage_col = col + 1
                self.editor_param_row = self._unified_pick_param_row_entering_stage(
                    self.editor_stage_col, row, neighbor_row_priority=True
                )
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
        elif target == "up":
            if rows <= 0:
                self._sync_from_engine()
                return
            if getattr(self, "editor_unified_header_focus", False):
                self.editor_unified_header_focus = False
                self.editor_param_row = rows - 1
                self._unified_commit_param_row_for_col(col, self.editor_param_row)
            else:
                if row <= 0:
                    self.editor_unified_header_focus = True
                    self._unified_commit_param_row_for_col(col, 0)
                else:
                    self.editor_param_row = row - 1
                    self._unified_commit_param_row_for_col(col, self.editor_param_row)
        elif target == "down":
            if rows <= 0:
                self._sync_from_engine()
                return
            if getattr(self, "editor_unified_header_focus", False):
                self.editor_unified_header_focus = False
                self.editor_param_row = 0
                self._unified_commit_param_row_for_col(col, self.editor_param_row)
            else:
                if row >= rows - 1:
                    self.editor_unified_header_focus = True
                    self._unified_commit_param_row_for_col(col, row)
                else:
                    self.editor_param_row = row + 1
                    self._unified_commit_param_row_for_col(col, self.editor_param_row)
        elif target == "press":
            self._press_unified_editor_cell()
            return
        elif target == "back":
            self._sync_from_engine()
            return
        self._draw_editor_controls()
        self._sync_from_engine()

    def _press_unified_editor_finish(self) -> None:
        self._propagate_strip_link_from_editor_channel()
        self._draw_editor_controls()
        self._sync_from_engine()

    def _press_unified_editor_cell(self) -> None:
        """PRESS on unified cells: PRE ``TBE`` = ``ch.tube`` only; HRM/GTE/CMP/EQ
        ``TBE`` = that stage's ``*_tube`` path only — never toggles ``*_enabled``.
        Column header press still toggles coarse module engage (unchanged).

        Opening the editor does not engage DSP; inserts change only via explicit presses."""
        self._coerce_editor_nav_to_unified_stage_grid()
        col = max(0, min(len(self._STAGE_GRID) - 1, self.editor_stage_col))
        stage_key, _header, params = self._STAGE_GRID[col]
        if not params:
            return
        row = max(0, min(len(params) - 1, self.editor_param_row))
        label = params[row]
        ch = self._current_channel()
        if ch is None:
            return

        if getattr(self, "editor_unified_header_focus", False):
            with self.engine._lock:
                if stage_key == "pre":
                    ch.pre_enabled = not ch.pre_enabled
                elif stage_key == "harm":
                    ch.harmonics_enabled = not ch.harmonics_enabled
                elif stage_key == "gate":
                    ch.gate_enabled = not ch.gate_enabled
                elif stage_key == "comp":
                    ch.comp_enabled = not ch.comp_enabled
                elif stage_key == "eq":
                    ch.eq_enabled = not ch.eq_enabled
                elif stage_key == "tone":
                    ch.tone_enabled = not ch.tone_enabled
            self._press_unified_editor_finish()
            return

        pre_per_cell: dict[str, str] = {
            "TBE": "tube",
            "LPF": "lpf_enabled",
            "48V": "phantom",
            "PHS": "phase",
            "HPF": "hpf_enabled",
        }
        if stage_key == "pre":
            attr = pre_per_cell.get(label)
            if attr and hasattr(ch, attr):
                setattr(ch, attr, not bool(getattr(ch, attr)))
                _log.debug("BYPASS PRESS PRE.%s -> %s", label, getattr(ch, attr))
            self._press_unified_editor_finish()
            return

        if stage_key == "harm":
            if label == "TBE":
                ch.harm_tube = not bool(ch.harm_tube)
                _log.debug("HARM TBE harm_tube -> %s", ch.harm_tube)
                self._press_unified_editor_finish()
                return
            if label.startswith("H") and len(label) == 2 and label[1].isdigit():
                hp = getattr(ch, "harm_param_bypass", None)
                if not isinstance(hp, dict):
                    ch.harm_param_bypass = {}
                ch.harm_param_bypass[label] = not bool(ch.harm_param_bypass.get(label, False))
                _log.debug("HARM bypass %s -> %s", label, ch.harm_param_bypass[label])
                self._press_unified_editor_finish()
                return
            return

        if stage_key == "eq":
            bp = getattr(ch, "eq_param_bypass", None)
            if not isinstance(bp, dict):
                ch.eq_param_bypass = {}
                bp = ch.eq_param_bypass
            if label == "TBE":
                ch.eq_tube = not bool(ch.eq_tube)
            elif label in ("FRQ", "GAN", "SHP", "TRN", "ATK", "SUT", "BD2"):
                bp[label] = not bp.get(label, False)
            elif label == "BND":
                with self.engine._lock:
                    if ch.eq_band_enabled and ch.eq_band_count >= 8:
                        ch.eq_band_enabled = False
                        self.eq_selected_band = max(0, min(self.eq_selected_band, ch.eq_band_count - 1))
                        self._sync_scalar_display_from_eq_band(ch)
                        _log.debug("EQ BND at max bands -> multiband off")
                    elif ch.eq_band_enabled:
                        ch.eq_band_count = min(8, int(ch.eq_band_count) + 1)
                        self.eq_selected_band = int(ch.eq_band_count) - 1
                        nb = self._eq_band(ch)
                        nb["freq"] = float(
                            np.clip(100.0 * (2.05 ** float(self.eq_selected_band)), 80.0, 12000.0)
                        )
                        if abs(float(nb.get("gain_db", 0.0))) < 0.08:
                            nb["gain_db"] = 4.0
                        nb["enabled"] = True
                        self._sync_scalar_display_from_eq_band(ch)
                        ch.eq_enabled = True
                        _log.debug("EQ BND added band n=%s", ch.eq_band_count)
                    else:
                        self._prime_eq_minimum_multiband(ch)
                        _log.debug("EQ BND multiband on sel=%s n=%s", self.eq_selected_band, ch.eq_band_count)
            else:
                return
            _log.debug("EQ PRESS %s bypass=%s", label, bp.get(label))
            self._press_unified_editor_finish()
            return

        if stage_key == "tone":
            if label not in ("TRN", "XCT", "DRV", "FRQ", "ATK", "SUT", "BND", "BD2"):
                # FRQ / ATK / SUT — bypass via dict; numeric twist adjusts elsewhere.
                return
            tb = getattr(ch, "tone_param_bypass", None)
            if not isinstance(tb, dict):
                ch.tone_param_bypass = {}
            ch.tone_param_bypass[label] = not bool(ch.tone_param_bypass.get(label, False))
            _log.debug("TONE bypass %s -> %s", label, ch.tone_param_bypass.get(label))
            self._press_unified_editor_finish()
            return

        if stage_key == "gate":
            if label == "TBE":
                ch.gate_tube = not bool(ch.gate_tube)
                _log.debug("GATE TBE gate_tube -> %s", ch.gate_tube)
            elif label == "BND":
                ch.gate_band_enabled = not ch.gate_band_enabled
                _log.debug("GATE BND freq band -> %s", ch.gate_band_enabled)
            elif label in ("THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT"):
                gb = getattr(ch, "gate_param_bypass", None)
                if not isinstance(gb, dict):
                    ch.gate_param_bypass = {}
                ch.gate_param_bypass[label] = not bool(ch.gate_param_bypass.get(label, False))
                _log.debug("GATE bypass %s -> %s", label, ch.gate_param_bypass.get(label))
            else:
                return
            self._press_unified_editor_finish()
            return
        if stage_key == "comp":
            if label == "TBE":
                ch.comp_tube = not bool(ch.comp_tube)
                _log.debug("CMP TBE comp_tube -> %s", ch.comp_tube)
            elif label == "BND":
                ch.comp_band_enabled = not ch.comp_band_enabled
                _log.debug("COMP BND freq band -> %s", ch.comp_band_enabled)
            elif label in ("THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT"):
                cb = getattr(ch, "comp_param_bypass", None)
                if not isinstance(cb, dict):
                    ch.comp_param_bypass = {}
                ch.comp_param_bypass[label] = not bool(ch.comp_param_bypass.get(label, False))
                _log.debug("COMP bypass %s -> %s", label, ch.comp_param_bypass.get(label))
            else:
                return
            self._press_unified_editor_finish()
            return

        self._press_unified_editor_finish()

    def _handle_module_editor_nav(self, target: str) -> None:
        if self._handle_editor_transport_nav(target):
            return
        columns = ["left", "stage", "body"]
        current_key = columns[self.module_editor_column]
        if current_key == "stage" and target == "right":
            stage_keys = self._console_stage_keys()
            self.selected_stage_key = stage_keys[self.module_editor_positions["stage"]]
            self._engage_stage_module(self._active_channel_index(), self.selected_stage_key)
            self.module_editor_column = 2
            self._reset_module_body_selection()
            self._normalize_module_editor_positions()
            self.editor_nav_scope = "module-body"
            self._sync_from_engine()
            return
        if current_key == "body" and self.selected_stage_key == "harm":
            idx = self.module_editor_positions["body"]
            rows = 3
            col = 0 if idx < rows else 1
            row = idx if idx < rows else idx - rows
            if target == "left":
                if col == 1:
                    self.module_editor_positions["body"] = row
                else:
                    self.module_editor_column = (self.module_editor_column - 1) % len(columns)
            elif target == "right":
                if col == 0:
                    self.module_editor_positions["body"] = row + rows
                else:
                    # Wrap inside the module — transport is hold / double-tilt only.
                    self.module_editor_positions["body"] = row
            elif target == "up":
                row = (row - 1) % rows
                self.module_editor_positions["body"] = row if col == 0 else row + rows
            elif target == "down":
                row = (row + 1) % rows
                self.module_editor_positions["body"] = row if col == 0 else row + rows
            elif target == "press":
                now = time.monotonic()
                if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self._editor_last_press_at = 0.0
                    self._exit_editor_to_console()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                pass
                return
        elif current_key == "body" and self.selected_stage_key == "comp":
            idx = self.module_editor_positions["body"]
            comp_rows = [(0, 1), (2, 5), (3, 6), (4, 7), (8, None)]
            row = 0
            col = 0
            for row_idx, pair in enumerate(comp_rows):
                if idx in pair:
                    row = row_idx
                    col = 0 if pair[0] == idx else 1
                    break
            if target == "left":
                if col == 1:
                    self.module_editor_positions["body"] = comp_rows[row][0]
                else:
                    self.module_editor_column = (self.module_editor_column - 1) % len(columns)
            elif target == "right":
                if col == 0 and comp_rows[row][1] is not None:
                    self.module_editor_positions["body"] = comp_rows[row][1]
                else:
                    self.module_editor_positions["body"] = comp_rows[row][0]
            elif target == "up":
                row = (row - 1) % len(comp_rows)
                self.module_editor_positions["body"] = comp_rows[row][col] if comp_rows[row][col] is not None else comp_rows[row][0]
            elif target == "down":
                row = (row + 1) % len(comp_rows)
                self.module_editor_positions["body"] = comp_rows[row][col] if comp_rows[row][col] is not None else comp_rows[row][0]
            elif target == "press":
                now = time.monotonic()
                if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self._editor_last_press_at = 0.0
                    self._exit_editor_to_console()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                pass
                return
        elif current_key == "body" and self.selected_stage_key == "eq":
            ch = self._current_channel()
            top_items, _ = self._module_stage_items(ch)
            band_idx = min(self.eq_selected_band, max(0, len(top_items) - 1)) if top_items else 0
            left_indices = [band_idx, len(top_items) + 0, len(top_items) + 2]
            right_indices = [len(top_items) + 1, len(top_items) + 3, len(top_items) + 4]
            idx = self.module_editor_positions["body"]
            if idx in left_indices:
                col = 0
                row = left_indices.index(idx)
            elif idx in right_indices:
                col = 1
                row = right_indices.index(idx)
            else:
                col = 0
                row = 0
                self.module_editor_positions["body"] = left_indices[0]
            if target == "left":
                if col == 1:
                    self.module_editor_positions["body"] = left_indices[row]
                else:
                    self.module_editor_column = (self.module_editor_column - 1) % len(columns)
            elif target == "right":
                if col == 0:
                    self.module_editor_positions["body"] = right_indices[row]
                else:
                    self.module_editor_positions["body"] = left_indices[row]
            elif target == "up":
                row = (row - 1) % 3
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "down":
                row = (row + 1) % 3
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "press":
                now = time.monotonic()
                if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self._editor_last_press_at = 0.0
                    self._exit_editor_to_console()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                pass
                return
        elif current_key == "body" and self.selected_stage_key == "tone":
            ch = self._current_channel()
            top_items, body_items = self._module_stage_items(ch)
            left_indices = [0, 1, 2]
            right_indices = [len(top_items) + i for i in range(len(body_items))]
            idx = self.module_editor_positions["body"]
            if idx in left_indices:
                col = 0
                row = left_indices.index(idx)
            elif idx in right_indices:
                col = 1
                row = right_indices.index(idx)
            else:
                col = 0
                row = 0
                self.module_editor_positions["body"] = left_indices[0]
            if target == "left":
                if col == 1:
                    self.module_editor_positions["body"] = left_indices[min(row, len(left_indices) - 1)]
                else:
                    self.module_editor_column = (self.module_editor_column - 1) % len(columns)
            elif target == "right":
                if col == 0:
                    self.module_editor_positions["body"] = right_indices[min(row, len(right_indices) - 1)]
                else:
                    self.module_editor_positions["body"] = left_indices[min(row, len(left_indices) - 1)]
            elif target == "up":
                if col == 0:
                    row = (row - 1) % len(left_indices)
                    self.module_editor_positions["body"] = left_indices[row]
                else:
                    row = (row - 1) % len(right_indices)
                    self.module_editor_positions["body"] = right_indices[row]
            elif target == "down":
                if col == 0:
                    row = (row + 1) % len(left_indices)
                    self.module_editor_positions["body"] = left_indices[row]
                else:
                    row = (row + 1) % len(right_indices)
                    self.module_editor_positions["body"] = right_indices[row]
            elif target == "press":
                now = time.monotonic()
                if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self._editor_last_press_at = 0.0
                    self._exit_editor_to_console()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                pass
                return
        elif target == "left":
            if current_key == "left":
                self.module_editor_column = 2
                self.editor_nav_scope = "module-body"
                self._sync_from_engine()
                return
            self.module_editor_column = (self.module_editor_column - 1) % len(columns)
        elif target == "right":
            if current_key == "body":
                self.module_editor_column = 1
                self.editor_nav_scope = "module-stage"
                self._sync_from_engine()
                return
            self.module_editor_column = (self.module_editor_column + 1) % len(columns)
        elif target == "up":
            if current_key == "stage":
                self._sync_from_engine()
                return
            self.module_editor_positions[current_key] = (
                self.module_editor_positions[current_key] - 1
            ) % self._module_editor_count_for_key(current_key)
        elif target == "down":
            if current_key == "stage":
                self._sync_from_engine()
                return
            self.module_editor_positions[current_key] = (
                self.module_editor_positions[current_key] + 1
            ) % self._module_editor_count_for_key(current_key)
        elif target == "press":
            now = time.monotonic()
            if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                if current_key == "left" and self.module_editor_positions["left"] == 0:
                    if self._active_channel_index() < len(self.engine.channels):
                        self._toggle_solo(self._active_channel_index())
                    self._editor_last_press_at = 0.0
                    return
                self._editor_last_press_at = 0.0
                self._exit_editor_to_console()
                return
            self._editor_last_press_at = now
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.module_editor_positions["stage"]]
                self._normalize_module_editor_positions()
                self._toggle_stage_enabled_only(self._active_channel_index(), self.selected_stage_key)
                self.editor_nav_scope = "module-stage"
                self._sync_from_engine()
                return
            if current_key == "left" and self.module_editor_positions["left"] == 0:
                if self._active_channel_index() < len(self.engine.channels):
                    self._toggle_mute(self._active_channel_index())
                return
            if current_key == "body":
                self._activate_module_body_selection()
                return
        elif target == "back":
            return
        self.editor_nav_scope = ["module-left", "module-stage", "module-body"][self.module_editor_column]
        self._sync_from_engine()

    def _handle_pre_editor_nav(self, target: str) -> None:
        if self._handle_editor_transport_nav(target):
            return
        columns = ["left", "stage", "body"]
        current_key = columns[self.pre_editor_column]
        if target == "left":
            if current_key == "left":
                self.pre_editor_column = 2
                self.editor_nav_scope = "pre-body"
                self._sync_from_engine()
                return
            self.pre_editor_column = (self.pre_editor_column - 1) % len(columns)
        elif target == "right":
            if current_key == "body":
                self.pre_editor_column = 1
                self.editor_nav_scope = "pre-stage"
                self._sync_from_engine()
                return
            self.pre_editor_column = (self.pre_editor_column + 1) % len(columns)
        elif target == "up":
            if current_key == "stage":
                self._sync_from_engine()
                return
            self.pre_editor_positions[current_key] = (
                self.pre_editor_positions[current_key] - 1
            ) % self._pre_editor_count(current_key)
        elif target == "down":
            if current_key == "stage":
                self._sync_from_engine()
                return
            self.pre_editor_positions[current_key] = (
                self.pre_editor_positions[current_key] + 1
            ) % self._pre_editor_count(current_key)
        elif target == "press":
            now = time.monotonic()
            if self._double_press_exit_enabled and now - self._editor_last_press_at <= 0.30:
                if current_key == "left" and self.pre_editor_positions["left"] == 0:
                    if self._active_channel_index() < len(self.engine.channels):
                        self._toggle_solo(self._active_channel_index())
                    self._editor_last_press_at = 0.0
                    return
                self._editor_last_press_at = 0.0
                self._exit_editor_to_console()
                return
            self._editor_last_press_at = now
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.pre_editor_positions["stage"]]
                self._toggle_stage_enabled_only(self._active_channel_index(), self.selected_stage_key)
                self._sync_from_engine()
                return
            if current_key == "left" and self.pre_editor_positions["left"] == 0:
                if self._active_channel_index() < len(self.engine.channels):
                    self._toggle_mute(self._active_channel_index())
                return
            if current_key == "body":
                labels = ["LPF", "48V", "PHS", "TBE", "HPF"]
                idx = self.pre_editor_positions["body"]
                self.editor_selected["pre"] = idx
                self._activate_editor_item(idx, labels[idx])
                return
        elif target == "back":
            return
        self.editor_nav_scope = ["pre-left", "pre-stage", "pre-body"][self.pre_editor_column]
        self._sync_from_engine()

    def _pre_editor_count(self, key: str) -> int:
        if key == "left":
            return 1
        if key == "stage":
            return len(self._console_stage_keys())
        if key == "body":
            return 5
        return 1

    def _spacemouse_strip_channel_index(self) -> int | None:
        if self.nav_scope == "editor":
            return int(getattr(self, "editor_channel", self.selected_channel))
        if self.nav_scope == "console":
            return int(self.selected_channel)
        if self.nav_scope == "knobs":
            return int(self.knob_focus_channel)
        if self.nav_scope == "faders":
            return int(self.fader_focus_channel)
        if self.nav_scope == "transport":
            ec = getattr(self, "editor_channel", None)
            if ec is not None:
                return int(max(0, ec))
            return int(getattr(self, "selected_channel", 0))
        return None

    def _run_cardinal_double_tap_macro(self, d: str) -> None:
        """Programmatic scope jump (tests, agent proof). Live cap XY does not call this."""

        ch = self._spacemouse_strip_channel_index()
        if ch is None:
            return
        if self.nav_scope == "editor" and getattr(self, "editor_nav_scope", "") == "stage_grid":
            cols = len(self._STAGE_GRID)
            if cols <= 0:
                return
            col = max(0, min(cols - 1, int(self.editor_stage_col)))
            if d == "left" and col <= 0:
                return
            if d == "right" and col >= cols - 1:
                return
        n_in = len(self.engine.channels)
        try:
            if d == "right":
                self._open_stage_editor(ch, self.selected_stage_key)
                return
            if d == "left":
                if n_in <= 0:
                    self._sync_from_engine()
                    return
                chi = int(ch)
                if chi >= n_in:
                    chi = n_in - 1
                chi = max(0, min(n_in - 1, chi))
                self._enter_fader_row(chi, source="spacemouse_double_left")
                return
            if d == "up":
                self.nav_scope = "console"
                self.console_row = "stages"
                self.selected_channel = ch
                self.editor_channel = ch
                self._transport_entered_from = None
                self._normalize_console_selection()
                self._redraw_transport_focus()
                self._sync_from_engine()
                return
            if d == "down":
                self.editor_channel = ch
                self._focus_transport_play_cell(source="spacemouse_double_down")
                self._sync_from_engine()
        except Exception:
            _log.exception("cardinal double-tap macro %s", d)

    def _preprocess_directional_double_taps(self, directional: list[str]) -> list[str]:
        return list(directional)

    def _reset_editor_leave_hold_tracking(self) -> None:
        self._editor_leave_hold_key = None
        self._editor_leave_hold_since = 0.0

    def _resolve_editor_leave_hold_intent(self) -> str | None:
        """Keyboard/BackSpace rim hold to exit editor (cap uses twist CCW)."""

        if self.nav_scope != "editor":
            return None

        held_keys = self._nav_keys_held
        sm = getattr(self, "spacemouse", None)
        zk = None
        if sm is not None and getattr(sm, "available", False):
            zk = getattr(sm, "active_z_latched_kind", lambda: None)()

        ens = getattr(self, "editor_nav_scope", "")

        if ens == "stage_grid":
            cols = len(self._STAGE_GRID)
            col = max(0, min(cols - 1, int(self.editor_stage_col)))
            if col == 0 and "left" in held_keys:
                return "sg_el"
            if cols > 0 and col == cols - 1 and "right" in held_keys:
                return "sg_er"
            if zk == "back" or "back" in held_keys:
                return "sg_bk"

        if zk == "back" or "back" in held_keys:
            return "ed_bk"
        return None

    def _poll_editor_leave_hold_gate(self) -> None:
        """After ``EDITOR_LR_HOLD_S`` with a steady keyboard/back posture, restore pre-editor scope."""

        if self.nav_scope != "editor":
            self._reset_editor_leave_hold_tracking()
            return

        intent = self._resolve_editor_leave_hold_intent()
        now = time.monotonic()
        hold_s = float(getattr(self, "EDITOR_LR_HOLD_S", getattr(self, "EDITOR_LEAVE_HOLD_S", 1.0)))

        if intent is None:
            self._reset_editor_leave_hold_tracking()
            return

        if self._editor_leave_hold_key != intent:
            self._editor_leave_hold_key = intent
            self._editor_leave_hold_since = now
            return

        if now - float(self._editor_leave_hold_since) < hold_s:
            return

        if intent in ("sg_el", "sg_er", "sg_bk", "ed_bk"):
            self._restore_editor_return_context()
        self._reset_editor_leave_hold_tracking()

    def _system_q_agent_proof_active(self) -> bool:
        """Automated agent-proof harness: disables long-twist/down-hold nav so scripted runs stay put."""

        return bool(os.environ.get("SYSTEM_Q_AGENT_PROOF", "").strip())

    def _capture_editor_return_context(self) -> None:
        """Remember mixer scope before editor entry (twist CCW / keyboard exits)."""

        self._editor_return_ctx = {
            "nav_scope": str(self.nav_scope),
            "console_row": str(getattr(self, "console_row", "stages")),
            "selected_channel": int(self.selected_channel),
            "editor_channel": int(self.editor_channel),
            "transport_focus_row": int(self.transport_focus_row),
            "transport_focus_col": int(self.transport_focus_col),
            "knob_focus_channel": int(self.knob_focus_channel),
            "fader_focus_channel": int(self.fader_focus_channel),
        }

    def _restore_editor_return_context(self) -> None:
        """Pop back to the scope that was active when the editor was opened."""

        ctx = getattr(self, "_editor_return_ctx", None)
        self._editor_return_ctx = None
        if not ctx:
            self._exit_editor_to_console()
            return
        ns = str(ctx.get("nav_scope", "console"))
        try:
            if ns == "transport":
                self.nav_scope = "transport"
                self.transport_focus_row = int(ctx.get("transport_focus_row", 0))
                self.transport_focus_col = int(ctx.get("transport_focus_col", 0))
                self.selected_channel = int(ctx.get("selected_channel", 0))
                self.editor_channel = int(ctx.get("editor_channel", self.selected_channel))
            elif ns == "knobs":
                self.nav_scope = "knobs"
                self.knob_focus_channel = max(
                    0,
                    min(len(self.engine.channels) - 1, int(ctx.get("knob_focus_channel", 0))),
                )
                self.selected_channel = int(ctx.get("selected_channel", self.knob_focus_channel))
                self.editor_channel = int(
                    ctx.get("editor_channel", self.selected_channel)
                )
            elif ns == "faders":
                self.nav_scope = "faders"
                self.fader_focus_channel = max(
                    0,
                    min(len(self.engine.channels) - 1, int(ctx.get("fader_focus_channel", 0))),
                )
                self.selected_channel = int(ctx.get("selected_channel", self.fader_focus_channel))
                self.editor_channel = int(
                    ctx.get("editor_channel", self.selected_channel)
                )
            else:
                self.nav_scope = "console"
                self.console_row = str(ctx.get("console_row", "stages"))
                self.selected_channel = int(ctx.get("selected_channel", 0))
                self.editor_channel = int(ctx.get("editor_channel", self.selected_channel))
        except (TypeError, ValueError):
            self._exit_editor_to_console()
            return
        self.editor_nav_scope = "body"
        self._normalize_console_selection()
        self._redraw_transport_focus()
        self._sync_from_engine()

    def _strip_link_cap_engage_handles(self) -> bool:
        """Long Z on channel strips STAGES row: toggle strip-link membership."""

        if self.nav_scope != "console" or self.console_row != "stages":
            return False
        n_in = len(self.engine.channels)
        if n_in <= 0:
            return True
        idx = int(self.selected_channel)
        if idx < 0 or idx >= n_in:
            return False
        grp = self.strip_link_indices
        if idx in grp:
            grp.discard(idx)
        else:
            grp.add(idx)
        self._draw_strips()
        self._sync_from_engine()
        return True

    def _copy_mix_settings_for_link(self, src: ChannelState, dst: ChannelState) -> None:
        for f in fields(ChannelState):
            if f.name in _STRIP_LINK_COPY_SKIP:
                continue
            val = getattr(src, f.name)
            if f.name == "harmonics":
                dst.harmonics = np.asarray(val, dtype=np.float32).copy()
            elif f.name == "eq_bands":
                dst.eq_bands = copy.deepcopy(val)
            elif f.name == "eq_param_bypass":
                dst.eq_param_bypass = dict(val) if isinstance(val, dict) else {}
            else:
                setattr(dst, f.name, val)

    def _propagate_strip_link_from_editor_channel(self) -> None:
        if self.nav_scope != "editor":
            return
        n_in = len(self.engine.channels)
        ec = int(self.editor_channel)
        if not (0 <= ec < n_in):
            return
        grp = self.strip_link_indices
        if ec not in grp or len(grp) < 2:
            return
        others = [i for i in sorted(grp) if i != ec and 0 <= i < n_in]
        if not others:
            return
        with self.engine._lock:
            src = self.engine.channels[ec]
            for ti in others:
                self._copy_mix_settings_for_link(src, self.engine.channels[ti])

    def _handle_cap_engage_toggle(self) -> None:
        """Long cap push (~``engage_hold_s``): primary activate / bypass for focused nav target."""

        try:
            if self.nav_scope == "editor":
                # Coerce BEFORE branch: engage_toggle runs ahead of _poll_spacemouse's coerce; stale
                # scopes like legacy "stage" or "" would bypass _press_unified_editor_cell otherwise.
                self._coerce_editor_nav_to_unified_stage_grid()
                if getattr(self, "editor_nav_scope", "") == "stage_grid":
                    self._press_unified_editor_cell()
                else:
                    self._handle_nav("press")
            elif self.nav_scope == "console":
                if not self._strip_link_cap_engage_handles():
                    self._handle_console_nav("press")
            elif self.nav_scope == "transport":
                self._handle_transport_nav("press")
            elif self.nav_scope == "knobs":
                self._handle_knobs_nav("press")
            elif self.nav_scope == "faders":
                self._handle_faders_nav("press")
        except Exception:
            _log.exception("cap engage_toggle")

    def _handle_down_hold_jump(self) -> None:
        """~3s tilt toward DOWN (Y): console -> editor -> faders -> console cycle.

        Not the cap push (Z): keep Z neutral-ish while counting. If automated
        proof is active (SYSTEM_Q_AGENT_PROOF), this is intentionally disabled.
        """

        if self._system_q_agent_proof_active():
            if os.environ.get("SYSTEM_Q_NAV_DEBUG", "").strip() in ("1", "true", "yes"):
                print("System Q: down_hold ignored (SYSTEM_Q_AGENT_PROOF set)", flush=True)
            return
        if os.environ.get("SYSTEM_Q_NAV_DEBUG", "").strip() in ("1", "true", "yes"):
            print(
                f"System Q: down_hold jump from nav_scope={self.nav_scope!r}",
                flush=True,
            )
        if self.nav_scope == "console":
            if self.console_row not in ("stages", "record", "footer", "knob", "fader"):
                return
            self._open_stage_editor(self.selected_channel, self.selected_stage_key)
            return
        if self.nav_scope == "editor":
            ch = int(getattr(self, "editor_channel", self.selected_channel))
            self._enter_fader_row(ch, source="editor_down_hold")
            return
        if self.nav_scope == "faders":
            self._exit_faders_to_console()
            return

    def _handle_twist_cw_editor_enter(self) -> None:
        """Sustained clockwise twist: open stage editor from mixer (any strip ring row)."""

        if self.nav_scope != "console":
            return
        if self._system_q_agent_proof_active():
            return
        if self.console_row not in ("stages", "record", "footer", "knob", "fader"):
            return
        self._open_stage_editor(self.selected_channel, self.selected_stage_key)

    def _handle_twist_ccw_editor_exit(self) -> None:
        """Sustained counter-clockwise twist: leave editor back to captured scope."""

        if self.nav_scope != "editor":
            return
        if self._system_q_agent_proof_active():
            return
        self._restore_editor_return_context()

    def _poll_spacemouse(self) -> None:
        axis_value, pressed, directional = self.spacemouse.poll()
        directional = list(directional)
        twist_cw = "twist_cw_hold" in directional
        twist_ccw = "twist_ccw_hold" in directional
        directional = [d for d in directional if d not in ("twist_cw_hold", "twist_ccw_hold")]
        down_hold = "down_hold" in directional
        directional = [d for d in directional if d != "down_hold"]
        if twist_cw:
            self._handle_twist_cw_editor_enter()
        if twist_ccw:
            self._handle_twist_ccw_editor_exit()
        if down_hold:
            self._handle_down_hold_jump()
        # Long Z is ~1 s; XY often still jitters during the hold. Consume this poll after
        # engage so bypass attaches only to the cell that had focus — no stray LRUD/step.
        suppress_editor_nav_twist_after_cap = False
        if "engage_toggle" in directional:
            directional = [d for d in directional if d != "engage_toggle"]
            self._handle_cap_engage_toggle()
            if self.nav_scope == "editor":
                suppress_editor_nav_twist_after_cap = True
        # If the cap emitted a directional event this poll, suppress twist for this
        # poll so a navigating push doesn't also sneak a value-edit / channel-page
        # in via incidental twist on the user's grip. Twist resumes on the next
        # poll where no direction fires.
        twist_value = 0.0 if directional or twist_cw or twist_ccw or down_hold else axis_value
        if suppress_editor_nav_twist_after_cap:
            directional = []
            twist_value = 0.0
        if self.nav_scope == "editor":
            self._coerce_editor_nav_to_unified_stage_grid()
            handled_directional = bool(directional)
            if directional:
                grid = getattr(self, "editor_nav_scope", "") == "stage_grid"
                if grid:
                    for d in directional:
                        self._handle_nav(d)
                else:
                    # Deep PRE/EQ/COMP/etc.: tilt is plain LRUD via ``_handle_nav``.
                    for d in directional:
                        self._handle_nav(d)
            if pressed and 0 in pressed and not handled_directional and not suppress_editor_nav_twist_after_cap:
                self._handle_nav("press")
            self._adjust_selected_editor_item(twist_value)
        elif self.nav_scope == "knobs":
            handled_directional = bool(directional)
            if directional:
                for d in directional:
                    self._handle_nav(d)
            if pressed and 0 in pressed and not handled_directional:
                self._handle_nav("press")
            self._adjust_send_level_axis(twist_value)
        elif self.nav_scope == "faders":
            handled_directional = bool(directional)
            if directional:
                for d in directional:
                    self._handle_nav(d)
            if pressed and 0 in pressed and not handled_directional:
                self._handle_nav("press")
            self._adjust_fader_gain_axis(twist_value)
        elif self.nav_scope == "transport":
            handled_directional = bool(directional)
            if directional:
                for d in directional:
                    self._handle_transport_nav(d)
            if pressed and 0 in pressed and not handled_directional:
                self._handle_transport_nav("press")
            # Twist: PLY jogs timeline; when OSC armed, twist sweeps / steps frequency on other transport cells.
            entry = self._transport_button_at(self.transport_focus_row, self.transport_focus_col)
            if entry is not None:
                ek = entry[0]
                if ek == "play":
                    self._tx_play_jog(twist_value)
                elif self.engine.generator_mode == "osc":
                    discrete_step = False
                    if abs(twist_value) >= DISCRETE_TWIST_MIN and self._axis_discrete_tick(
                        axis_value=twist_value, magnitude=DISCRETE_TWIST_MIN
                    ):
                        self._osc_step_polar_band(1 if twist_value > 0 else -1)
                        discrete_step = True
                    if not discrete_step:
                        self._adjust_oscillator_frequency(twist_value)
        else:
            self._console_hold_target = None
            if self.nav_scope == "console":
                handled_directional = bool(directional)
                if directional:
                    saw_back = any(d == "back" for d in directional)
                    planed = [d for d in directional if d != "back"]
                    if saw_back:
                        self._handle_console_nav("back")
                    for d in planed:
                        self._handle_console_nav(d)
                if pressed and 0 in pressed and not handled_directional:
                    self._handle_console_nav("press")
                osc_on_strip = (
                    self.engine.generator_mode == "osc" and self.console_row not in ("knob", "fader")
                )
                if osc_on_strip:
                    discrete_step = False
                    if abs(twist_value) >= DISCRETE_TWIST_MIN and self._axis_discrete_tick(
                        axis_value=twist_value, magnitude=DISCRETE_TWIST_MIN
                    ):
                        self._osc_step_polar_band(1 if twist_value > 0 else -1)
                        discrete_step = True
                    if not discrete_step:
                        self._adjust_oscillator_frequency(twist_value)
                else:
                    self._adjust_console_channel_axis(twist_value)

    def _poll_console_hold_repeat(self) -> None:
        self._console_hold_target = None
        return

    def _freq_to_slider(self, freq: float) -> float:
        freq = float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ))
        return (math.log10(freq) - LOG_LOW) / (LOG_HIGH - LOG_LOW)

    def _slider_to_freq(self, slider_pos: float) -> float:
        slider_pos = max(0.0, min(1.0, slider_pos))
        return 10 ** (LOG_LOW + slider_pos * (LOG_HIGH - LOG_LOW))

    def _channel_eq_indicator_gain_freq(self, ch: ChannelState) -> tuple[float, float]:
        """Gain + center frequency for strip EQ tint (matches multi-band selection)."""

        if getattr(ch, "eq_band_enabled", False):
            n = max(1, min(8, int(ch.eq_band_count)))
            bi = max(0, min(n - 1, int(getattr(self, "eq_selected_band", 0))))
            b = ch.eq_bands[bi]
            gf = float(b.get("gain_db", ch.eq_gain_db))
            ff = float(np.clip(float(b.get("freq", ch.eq_freq)), POL_LOW_HZ, POL_HIGH_HZ))
            return gf, ff
        return float(ch.eq_gain_db), float(np.clip(ch.eq_freq, POL_LOW_HZ, POL_HIGH_HZ))

    def _processor_band_bounds(self, center_hz: float, width: float, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        if width >= 5.9:
            focus_start, focus_end = 0.0, 1.0
        else:
            start_hz = max(POL_LOW_HZ, center_hz / (2 ** (width / 2)))
            end_hz = min(POL_HIGH_HZ, center_hz * (2 ** (width / 2)))
            focus_start = self._freq_to_slider(start_hz)
            focus_end = self._freq_to_slider(end_hz)
        start_rx = outer_rx - (outer_rx - inner_rx) * focus_start
        start_ry = outer_ry - (outer_ry - inner_ry) * focus_start
        end_rx = outer_rx - (outer_rx - inner_rx) * focus_end
        end_ry = outer_ry - (outer_ry - inner_ry) * focus_end
        return start_rx, start_ry, end_rx, end_ry

    def _comp_mode_enabled(self, ch: ChannelState, mode: str) -> bool:
        return {"COMP": ch.comp_enabled, "LIMIT": ch.limit_enabled, "GATE": ch.gate_enabled}[mode]

    def _toggle_comp_mode_enabled(self, ch: ChannelState, mode: str) -> None:
        if mode == "COMP":
            ch.comp_enabled = not ch.comp_enabled
        elif mode == "LIMIT":
            ch.limit_enabled = not ch.limit_enabled
        elif mode == "GATE":
            ch.gate_enabled = not ch.gate_enabled

    def _comp_mode_band_enabled(self, ch: ChannelState, mode: str) -> bool:
        return {"COMP": ch.comp_band_enabled, "LIMIT": ch.limit_band_enabled, "GATE": ch.gate_band_enabled}[mode]

    def _set_comp_mode_band_enabled(self, ch: ChannelState, mode: str, enabled: bool) -> None:
        if mode == "COMP":
            ch.comp_band_enabled = enabled
        elif mode == "LIMIT":
            ch.limit_band_enabled = enabled
        elif mode == "GATE":
            ch.gate_band_enabled = enabled

    def _comp_mode_center(self, ch: ChannelState, mode: str) -> float:
        return {"COMP": ch.comp_center_hz, "LIMIT": ch.limit_center_hz, "GATE": ch.gate_center_hz}[mode]

    def _set_comp_mode_center(self, ch: ChannelState, mode: str, value: float) -> None:
        if mode == "COMP":
            ch.comp_center_hz = value
        elif mode == "LIMIT":
            ch.limit_center_hz = value
        elif mode == "GATE":
            ch.gate_center_hz = value

    def _comp_mode_width(self, ch: ChannelState, mode: str) -> float:
        return {"COMP": ch.comp_width_oct, "LIMIT": ch.limit_width_oct, "GATE": ch.gate_width_oct}[mode]

    def _set_comp_mode_width(self, ch: ChannelState, mode: str, value: float) -> None:
        if mode == "COMP":
            ch.comp_width_oct = value
        elif mode == "LIMIT":
            ch.limit_width_oct = value
        elif mode == "GATE":
            ch.gate_width_oct = value

    def _focus_geometry(self, w: int, h: int):
        header_offset = 52
        usable_h = h - header_offset
        cx = w * 0.50
        cy = header_offset + usable_h * 0.48
        outer_rx = w * 0.435
        outer_ry = usable_h * 0.435
        inner_rx = outer_rx * 0.22
        inner_ry = outer_ry * 0.22
        return cx, cy, outer_rx, outer_ry, inner_rx, inner_ry

    def _output_polar_pulse(self) -> float:
        """Fast attack / slower decay follower of ``engine.master_level`` for polar luminance pulses."""

        ml = float(np.clip(float(getattr(self.engine, "master_level", 0.0)), 0.0, 1.45))
        h = float(self._pol_out_pulse_hold)
        if ml > h:
            h = h * 0.26 + ml * 0.74
        else:
            h = h * 0.893 + ml * 0.107
        self._pol_out_pulse_hold = h
        return float(np.clip(h ** 0.88, 0.0, 1.18))

    def _draw_focus_ring_grid(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        for i in range(14):
            mix = i / 13.0
            rx = outer_rx - (outer_rx - inner_rx) * mix
            ry = outer_ry - (outer_ry - inner_ry) * mix
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline="#24313d", width=1)
        c.create_line(cx - outer_rx - 28, cy, cx + outer_rx + 28, cy, fill="#31404e")
        c.create_line(cx, max(0, cy - outer_ry - 36), cx, min(cy + outer_ry + 36, cy + outer_ry + 16), fill="#31404e")

    def _draw_polar_level_guide_rings(
        self,
        c: tk.Canvas,
        cx: float,
        cy: float,
        outer_rx: float,
        outer_ry: float,
        inner_rx: float,
        inner_ry: float,
    ) -> None:
        """Evenly spaced dB reference hoops (avoid log cramming toward +12). Inner label sits on a tight oval."""

        ticks = tuple(sorted(POL_LEVEL_GUIDE_TICKS_DB))
        n_tick = len(ticks)
        g_in_rx = inner_rx * float(POL_LEVEL_GUIDE_INNER_SCALE)
        g_in_ry = inner_ry * float(POL_LEVEL_GUIDE_INNER_SCALE)
        for k, db in enumerate(ticks):
            m = 0.0 if n_tick <= 1 else float(k) / float(n_tick - 1)
            rx = outer_rx - (outer_rx - g_in_rx) * m
            ry = outer_ry - (outer_ry - g_in_ry) * m
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline="#2c3c50", width=1)
            tag = polar_level_guide_label(db)
            ox = 12 if k % 2 == 0 else 22
            c.create_text(cx + ox, cy - ry - 5, anchor="w", text=f"{tag} dB", fill="#5a6d80", font=("Segoe UI", 7))

    def _draw_focus_signal(
        self,
        c: tk.Canvas,
        spectrum_ch: ChannelState,
        cx: int,
        cy: int,
        outer_rx: float,
        outer_ry: float,
        inner_rx: float,
        inner_ry: float,
        *,
        level_gain: float = 1.0,
    ):
        """Log-frequency spectral rings driven by monitored output (``spectrum_ch``, usually Master).

        Band ``level`` expresses relative energy vs noise floor (“which frequencies”).
        Output-level pulse lifts value and stroke weight so louder hits read as brighter flashes.
        """
        lg = float(np.clip(level_gain, 0.06, 1.5))
        pulse = float(getattr(self, "_pol_pulse_cached", 0.0))
        thick_glow = float(np.clip(0.72 + pulse * 0.95, 0.55, 1.72))
        for i, level in enumerate(spectrum_ch.band_levels):
            amt = float(np.clip(level, 0.0, 1.0))
            amt *= lg
            if amt < 0.018:
                continue
            mix = i / max(1, POL_BANDS - 1)
            rx = outer_rx - (outer_rx - inner_rx) * mix
            ry = outer_ry - (outer_ry - inner_ry) * mix
            band_hz = float(POL_BAND_CENTER_HZ[i])
            hue = freq_rainbow_hue_hz(band_hz)
            sat = float(np.clip(0.92 * (0.45 + lg * 0.55), 0.2, 0.95))
            v_hi = float(
                np.clip((0.08 + amt * lg * 0.98) * (0.42 + 0.64 * pulse), 0.07, 0.995)
            )
            color = hsv_to_hex(hue, sat, v_hi)
            width = max(1, int((1 + amt * lg * 3.15) * thick_glow))
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=width)
            if amt * lg > 0.36:
                glow = hsv_to_hex(hue, 0.38, np.clip((0.09 + amt * 0.36) * (0.5 + pulse * 0.55), 0.08, 0.82))
                c.create_oval(cx - rx - 1.5, cy - ry - 1.5, cx + rx + 1.5, cy + ry + 1.5, outline=glow, width=1)

    def _draw_focus_button_row(self, c: tk.Canvas, labels: list[tuple[str, bool]], w: int, h: int):
        y = h - 34
        gap = w / (len(labels) + 1)
        for idx, (label, active) in enumerate(labels, start=1):
            x = gap * idx
            fill = "#f6a864" if active else "#24303a"
            outline = "#ffd490" if active else "#4f667b"
            text_color = "#11151a" if active else "#c9d8e6"
            c.create_rectangle(x - 40, y - 16, x + 40, y + 16, fill=fill, outline=outline, width=2)
            c.create_text(x, y, text=label, fill=text_color, font=("Segoe UI", 10, "bold"))

    def _draw_focus_mic_pre(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if ch.lpf_enabled:
            pos = self._freq_to_slider(ch.lpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * pos
            for layer in range(14):
                mix = layer / 13.0
                layer_rx = cutoff_rx + (outer_rx - cutoff_rx) * mix
                layer_ry = cutoff_ry + (outer_ry - cutoff_ry) * mix
                lc = polar_edit_overlay_hex(mix, 0.35 + mix * 0.25)
                c.create_oval(
                    cx - layer_rx,
                    cy - layer_ry,
                    cx + layer_rx,
                    cy + layer_ry,
                    outline=lc,
                    width=3,
                )
            c.create_oval(
                cx - outer_rx,
                cy - outer_ry,
                cx + outer_rx,
                cy + outer_ry,
                outline=hsv_to_hex(freq_rainbow_hue_hz(POL_HIGH_HZ), 0.55, 0.52),
                width=4,
            )
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline=POL_NEON_RED_HOT, width=3)
        if ch.hpf_enabled:
            pos = self._freq_to_slider(ch.hpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * pos
            for layer in range(14):
                mix = layer / 13.0
                layer_rx = inner_rx + (cutoff_rx - inner_rx) * mix
                layer_ry = inner_ry + (cutoff_ry - inner_ry) * mix
                lc = polar_edit_overlay_hex(mix, 0.35 + mix * 0.25)
                c.create_oval(
                    cx - layer_rx,
                    cy - layer_ry,
                    cx + layer_rx,
                    cy + layer_ry,
                    outline=lc,
                    width=3,
                )
            c.create_oval(
                cx - inner_rx,
                cy - inner_ry,
                cx + inner_rx,
                cy + inner_ry,
                outline=hsv_to_hex(freq_rainbow_hue_hz(POL_LOW_HZ), 0.58, 0.48),
                width=4,
            )
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline=POL_NEON_RED_HOT, width=3)

    def _draw_focus_harmonics(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        positions = [0.10, 0.30, 0.50, 0.68, 0.84]
        for idx, weight in enumerate(ch.harmonics):
            if weight <= 0.01:
                continue
            rx = outer_rx - (outer_rx - inner_rx) * positions[idx]
            ry = outer_ry - (outer_ry - inner_ry) * positions[idx]
            heat = float(weight)
            expand = 8 + heat * 14
            color = polar_edit_overlay_hex(idx / 4.0, heat)
            glow = polar_edit_overlay_hex(idx / 4.0, heat * 0.55, muted=True)
            c.create_oval(cx - rx - expand, cy - ry - expand * 0.72, cx + rx + expand, cy + ry + expand * 0.72, outline=glow, width=1)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 + int(heat * 3))
        c.create_text(cx, h - 28, text=f"MAKE {ch.harmonic_makeup:.2f}x", fill="#8ea3ba", font=("Segoe UI", 10, "bold"))

    def _draw_focus_compressor(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_polar_level_guide_rings(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        # Monitored mix spectrum always (even when CMP bypassed — user hears output here).
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if not ch.comp_enabled:
            c.create_text(cx, h - 52, text="COMP BYPASSED", fill="#aebfcf", font=("Segoe UI", 12, "bold"))
            c.create_text(cx, h - 28, text="Engage CMP on the grid or strip", fill="#70869a", font=("Segoe UI", 10))
            return
        thr_mix = float(polar_level_db_to_mix(ch.comp_threshold_db))
        ratio_darkness = min(1.0, max(0.0, (ch.comp_ratio - 1.0) / 19.0))
        pressure = min(1.0, max(0.0, ch.comp_gr_db / 18.0))

        def band_bounds(mode: str):
            if self._comp_mode_band_enabled(ch, mode):
                return self._processor_band_bounds(
                    self._comp_mode_center(ch, mode),
                    self._comp_mode_width(ch, mode),
                    outer_rx,
                    outer_ry,
                    inner_rx,
                    inner_ry,
                )
            return outer_rx, outer_ry, inner_rx, inner_ry

        outer_wall_rx, outer_wall_ry, band_inner_rx, band_inner_ry = band_bounds("COMP")
        inner_threshold_rx = max(band_inner_rx, outer_wall_rx - (outer_wall_rx - band_inner_rx) * thr_mix)
        inner_threshold_ry = max(band_inner_ry, outer_wall_ry - (outer_wall_ry - band_inner_ry) * thr_mix)
        pulse_pull = pressure * (0.12 + thr_mix * 0.10)
        pump_rx = max(band_inner_rx, inner_threshold_rx - (inner_threshold_rx - band_inner_rx) * pulse_pull)
        pump_ry = max(band_inner_ry, inner_threshold_ry - (inner_threshold_ry - band_inner_ry) * pulse_pull)
        overlay_layers = 8 + int(10 * ratio_darkness)
        for layer in range(overlay_layers):
            mix = layer / max(1, overlay_layers - 1)
            layer_rx = pump_rx + (outer_wall_rx - pump_rx) * mix
            layer_ry = pump_ry + (outer_wall_ry - pump_ry) * mix
            punch = ratio_darkness * 1.08
            layer_color = polar_edit_overlay_hex(mix, punch)
            c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=1 + int(ratio_darkness * 2))
        c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline=POL_NEON_RED, width=5)
        c.create_oval(cx - pump_rx, cy - pump_ry, cx + pump_rx, cy + pump_ry, outline=POL_NEON_RED_HOT, width=3 + int(pressure * 2))
        c.create_text(cx, cy - 14, text=f"COMP   GR {ch.comp_gr_db:.1f} dB", fill="#f6a864", font=("Segoe UI", 16, "bold"))

    def _draw_focus_gate(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_polar_level_guide_rings(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        # Monitored mix spectrum always — bypass only removes gate diagram, not the output meter plane.
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if not ch.gate_enabled:
            c.create_text(cx, h - 52, text="GATE BYPASSED", fill="#aebfcf", font=("Segoe UI", 12, "bold"))
            c.create_text(cx, h - 28, text="Engage GTE on the grid or strip", fill="#70869a", font=("Segoe UI", 10))
            return
        thr_mix = float(polar_level_db_to_mix(ch.gate_threshold_db))
        depth = min(1.0, max(0.0, abs(ch.gate_gr_db) / 36.0))

        def band_bounds(mode: str):
            if self._comp_mode_band_enabled(ch, mode):
                return self._processor_band_bounds(
                    self._comp_mode_center(ch, mode),
                    self._comp_mode_width(ch, mode),
                    outer_rx,
                    outer_ry,
                    inner_rx,
                    inner_ry,
                )
            return outer_rx, outer_ry, inner_rx, inner_ry

        outer_wall_rx, outer_wall_ry, band_inner_rx, band_inner_ry = band_bounds("GATE")
        throat_rx = max(band_inner_rx, outer_wall_rx - (outer_wall_rx - band_inner_rx) * thr_mix)
        throat_ry = max(band_inner_ry, outer_wall_ry - (outer_wall_ry - band_inner_ry) * thr_mix)
        layers = 9 + int(6 * depth)
        for layer in range(layers):
            mix = layer / max(1, layers - 1)
            layer_rx = outer_wall_rx + (throat_rx - outer_wall_rx) * mix * (0.92 - 0.18 * depth)
            layer_ry = outer_wall_ry + (throat_ry - outer_wall_ry) * mix * (0.92 - 0.18 * depth)
            col = polar_edit_overlay_hex(mix, depth * 0.9)
            c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=col, width=2)
        c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline=POL_NEON_RED, width=5)
        c.create_oval(cx - throat_rx, cy - throat_ry, cx + throat_rx, cy + throat_ry, outline=POL_NEON_RED_HOT, width=3)
        c.create_text(cx, cy - 14, text=f"GATE ~{depth * 36.0:.0f} dB floor", fill="#76ffe0", font=("Segoe UI", 16, "bold"))

    def _polar_collect_eq_bands_for_draw(self, ch: ChannelState) -> list[tuple[int, dict]]:
        """Bands to paint in polar EQ overlay (aligned with ``pol_visualizer._draw_eq_overlay``)."""

        pairs: list[tuple[int, dict]] = []
        if getattr(ch, "eq_band_enabled", False):
            n = max(1, min(8, int(ch.eq_band_count)))
            for i in range(n):
                b = ch.eq_bands[i]
                if not bool(b.get("enabled", False)):
                    continue
                pairs.append((i, dict(b)))
        else:
            pairs.append(
                (
                    0,
                    {
                        "freq": float(ch.eq_freq),
                        "gain_db": float(ch.eq_gain_db),
                        "width": float(ch.eq_width),
                        "type": str(ch.eq_type),
                    },
                )
            )
        return pairs

    def _polar_eq_frequency_tick_labels(
        self, c: tk.Canvas, cx: float, cy: float, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float
    ) -> None:
        band_edges = np.geomspace(POL_LOW_HZ, POL_HIGH_HZ, num=POL_BANDS + 1)
        band_centers = np.sqrt(band_edges[:-1] * band_edges[1:])
        label_indices = [0, 9, 18, 27, POL_BANDS - 1]
        for idx in label_indices:
            band_pos = idx / max(1, POL_BANDS - 1)
            ry = outer_ry - (outer_ry - inner_ry) * band_pos
            hz = band_centers[idx]
            txt = f"{hz / 1000:.1f} kHz" if hz >= 1000 else f"{int(round(hz))} Hz"
            c.create_text(cx, cy - ry - 10, text=txt, fill="#9fb6cb", font=("Segoe UI", 9))

        c.create_text(cx - outer_rx + 26, cy - outer_ry + 52, anchor="nw", text="20 Hz", fill="#7a93ad", font=("Segoe UI", 9, "bold"))
        c.create_text(cx + inner_rx + 48, cy - inner_ry - 40, anchor="ne", text="22 kHz", fill="#7a93ad", font=("Segoe UI", 9, "bold"))

    def _polar_eq_paint_console_bands(
        self,
        c: tk.Canvas,
        ch: ChannelState,
        cx: float,
        cy: float,
        outer_rx: float,
        outer_ry: float,
        inner_rx: float,
        inner_ry: float,
        engage: bool,
    ) -> None:
        """Log-frequency radial mapping: red edit shells over output spectrum (``freq_rainbow`` per bin)."""

        if not engage:
            return
        pairs = self._polar_collect_eq_bands_for_draw(ch)
        if not pairs:
            return
        sel = max(0, min(7, int(getattr(self, "eq_selected_band", 0))))

        for bi, band in pairs:
            selected = (not ch.eq_band_enabled) or (bi == sel)
            center = float(np.clip(float(band.get("freq", ch.eq_freq)), POL_LOW_HZ, POL_HIGH_HZ))
            band_pos = self._freq_to_slider(center)
            rx = outer_rx - (outer_rx - inner_rx) * band_pos
            ry = outer_ry - (outer_ry - inner_ry) * band_pos
            kind = str(band.get("type", "BELL"))
            gain_db = float(band.get("gain_db", 0.0))
            width = float(np.clip(float(band.get("width", ch.eq_width)), 0.20, 6.0))
            gain_punch = float(np.clip(abs(gain_db) / 15.0, 0.0, 1.0))
            muted_eq = not engage
            color = polar_edit_overlay_hex(0.38, gain_punch, muted=muted_eq)
            edge = POL_NEON_RED_HOT if selected else color

            if kind == "BELL":
                start_hz = max(POL_LOW_HZ, center / (2 ** (width / 2)))
                end_hz = min(POL_HIGH_HZ, center * (2 ** (width / 2)))
                start_pos = self._freq_to_slider(start_hz)
                end_pos = self._freq_to_slider(end_hz)
                start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
                start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
                end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
                end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
                span_oct = max(1e-9, math.log2(end_hz / start_hz))
                band_layers = int(np.clip(round(5.0 + span_oct * 4.5), 5, 26))
                lw_base = max(2, min(5, int(1.5 + span_oct * 0.85)))
                if selected:
                    lw_base += 1
                for layer in range(band_layers):
                    mix = layer / max(1, band_layers - 1)
                    layer_rx = start_rx + (end_rx - start_rx) * mix
                    layer_ry = start_ry + (end_ry - start_ry) * mix
                    layer_color = (
                        POL_NEON_RED_HOT
                        if selected and abs(mix - 0.5) < 0.18
                        else polar_edit_overlay_hex(mix, gain_punch + mix * 0.1, muted=muted_eq)
                    )
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=lw_base)
                c.create_oval(
                    cx - rx,
                    cy - ry,
                    cx + rx,
                    cy + ry,
                    outline=(POL_NEON_RED_HOT if selected else color),
                    width=(4 if selected else 3),
                )
            elif kind in ("LOW SHELF", "HIGH SHELF"):
                transition_oct = max(0.20, min(3.0, width))
                if kind == "LOW SHELF":
                    trans_end_hz = min(POL_HIGH_HZ, center * (2 ** transition_oct))
                    trans_end_pos = self._freq_to_slider(trans_end_hz)
                    trans_end_rx = outer_rx - (outer_rx - inner_rx) * trans_end_pos
                    trans_end_ry = outer_ry - (outer_ry - inner_ry) * trans_end_pos
                    band_layers = 10 if selected else 7
                    for layer in range(band_layers):
                        mix = layer / max(1, band_layers - 1)
                        layer_rx = rx + (trans_end_rx - rx) * mix
                        layer_ry = ry + (trans_end_ry - ry) * mix
                        layer_color = (
                            POL_NEON_RED_HOT
                            if selected and layer == 0
                            else polar_edit_overlay_hex(mix, gain_punch + mix * 0.08, muted=muted_eq)
                        )
                        c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3 if selected else 2)
                    c.create_oval(cx - outer_rx, cy - outer_ry, cx + outer_rx, cy + outer_ry, outline=color, width=3 if selected else 2)
                    if selected:
                        c.create_oval(cx - trans_end_rx, cy - trans_end_ry, cx + trans_end_rx, cy + trans_end_ry, outline=edge, width=2)
                else:
                    trans_start_hz = max(POL_LOW_HZ, center / (2 ** transition_oct))
                    trans_start_pos = self._freq_to_slider(trans_start_hz)
                    trans_start_rx = outer_rx - (outer_rx - inner_rx) * trans_start_pos
                    trans_start_ry = outer_ry - (outer_ry - inner_ry) * trans_start_pos
                    band_layers = 10 if selected else 7
                    for layer in range(band_layers):
                        mix = layer / max(1, band_layers - 1)
                        layer_rx = trans_start_rx + (rx - trans_start_rx) * mix
                        layer_ry = trans_start_ry + (ry - trans_start_ry) * mix
                        layer_color = (
                            POL_NEON_RED_HOT
                            if selected and layer == band_layers - 1
                            else polar_edit_overlay_hex(mix, gain_punch + mix * 0.08, muted=muted_eq)
                        )
                        c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3 if selected else 2)
                    c.create_oval(cx - inner_rx, cy - inner_ry, cx + inner_rx, cy + inner_ry, outline=color, width=3 if selected else 2)
                    if selected:
                        c.create_oval(cx - trans_start_rx, cy - trans_start_ry, cx + trans_start_rx, cy + trans_start_ry, outline=edge, width=2)
            elif kind == "LPF":
                for layer in range(10):
                    mix = layer / 9.0
                    layer_rx = rx + (outer_rx - rx) * mix
                    layer_ry = ry + (outer_ry - ry) * mix
                    lc = polar_edit_overlay_hex(mix, gain_punch + mix * 0.06, muted=muted_eq)
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=lc, width=2)
            elif kind == "HPF":
                for layer in range(10):
                    mix = layer / 9.0
                    layer_rx = inner_rx + (rx - inner_rx) * mix
                    layer_ry = inner_ry + (ry - inner_ry) * mix
                    lc = polar_edit_overlay_hex(mix, gain_punch + mix * 0.06, muted=muted_eq)
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=lc, width=2)
            else:
                start_hz = max(POL_LOW_HZ, center / (2 ** (width / 2)))
                end_hz = min(POL_HIGH_HZ, center * (2 ** (width / 2)))
                sp = self._freq_to_slider(start_hz)
                ep = self._freq_to_slider(end_hz)
                sr = outer_rx - (outer_rx - inner_rx) * sp
                sry = outer_ry - (outer_ry - inner_ry) * sp
                er = outer_rx - (outer_rx - inner_rx) * ep
                ery = outer_ry - (outer_ry - inner_ry) * ep
                for layer in range(6):
                    mix = layer / 5.0
                    lc = polar_edit_overlay_hex(mix, gain_punch + mix * 0.05, muted=muted_eq)
                    c.create_oval(
                        cx - (sr + (er - sr) * mix),
                        cy - (sry + (ery - sry) * mix),
                        cx + (sr + (er - sr) * mix),
                        cy + (sry + (ery - sry) * mix),
                        outline=lc,
                        width=2,
                    )

    def _draw_focus_eq(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        # Insert bypassed: pane stays empty (palette fill only from ``_draw_focus_to``;
        # no analyzer rings, spectrum, or EQ shells).
        if not ch.eq_enabled:
            return
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        # Output spectrum backbone (quiet) — EQ bells/dips paint on top for edit context.
        self._draw_focus_signal(
            c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry, level_gain=0.50
        )
        self._polar_eq_paint_console_bands(
            c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry, engage=True
        )

    def _tone_logfreq_outline(
        self,
        c: tk.Canvas,
        cx: float,
        cy: float,
        outer_rx: float,
        outer_ry: float,
        inner_rx: float,
        inner_ry: float,
        center_hz: float,
        width_oct: float,
        strength: float,
        active_mode: bool,
    ) -> None:
        """Log-freq band shell for TRN/XCT — red overlays (analyzer rainbow paints underneath via ``_draw_focus_signal``)."""

        wo = float(np.clip(width_oct, 0.20, 6.0))
        center = float(np.clip(center_hz, POL_LOW_HZ, POL_HIGH_HZ))
        start_hz = max(POL_LOW_HZ, center / (2 ** (wo / 2)))
        end_hz = min(POL_HIGH_HZ, center * (2 ** (wo / 2)))
        start_pos = self._freq_to_slider(start_hz)
        end_pos = self._freq_to_slider(end_hz)
        start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
        start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
        end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
        end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
        crx = outer_rx - (outer_rx - inner_rx) * self._freq_to_slider(center)
        cry = outer_ry - (outer_ry - inner_ry) * self._freq_to_slider(center)
        span_oct = max(1e-9, math.log2(end_hz / start_hz))
        layers = int(np.clip(round(6 + span_oct * 3.8 * (0.55 + strength * 0.45)), 5, 24))
        lw = max(2, min(6, int(2.0 + strength * 4.5 + (2 if active_mode else 0))))
        dim_outline = "#2f3c4d"
        st = min(1.0, strength)
        for layer in range(layers):
            mix = layer / max(1, layers - 1)
            lr = start_rx + (end_rx - start_rx) * mix
            lry = start_ry + (end_ry - start_ry) * mix
            if st <= 0.04:
                col = dim_outline
            elif active_mode and abs(mix - 0.5) < 0.14:
                col = POL_NEON_RED_HOT
            else:
                col = polar_edit_overlay_hex(mix, st * (0.85 if active_mode else 0.65), muted=not active_mode and st < 0.12)
            c.create_oval(cx - lr, cy - lry, cx + lr, cy + lry, outline=col, width=max(1, lw - int(layer > layers * 0.65)))
        edge = polar_edit_overlay_hex(0.5, st, muted=st <= 0.06)
        c.create_oval(
            cx - crx,
            cy - cry,
            cx + crx,
            cy + cry,
            outline=POL_NEON_RED_HOT if active_mode else edge,
            width=lw + 1,
        )

    def _draw_focus_tone(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)

        mode = getattr(self, "tone_editor_mode", "TRN")
        transient_on = getattr(ch, "transient_enabled", True) and (
            getattr(ch, "trn_attack", 0.0) > 0.02 or getattr(ch, "trn_sustain", 0.0) > 0.02
        )
        sat_on = getattr(ch, "saturation_enabled", True) and getattr(ch, "clr_drive", 0.0) > 0.02
        xct_on = getattr(ch, "exciter_enabled", True) and getattr(ch, "xct_amount", 0.0) > 0.02

        if transient_on:
            tr_strength = min(1.0, float((ch.trn_attack + ch.trn_sustain) * 0.58))
            self._tone_logfreq_outline(
                c,
                cx,
                cy,
                outer_rx,
                outer_ry,
                inner_rx,
                inner_ry,
                ch.trn_freq,
                ch.trn_width,
                tr_strength,
                mode == "TRN",
            )
        if xct_on:
            self._tone_logfreq_outline(
                c,
                cx,
                cy,
                outer_rx,
                outer_ry,
                inner_rx,
                inner_ry,
                ch.xct_freq,
                ch.xct_width,
                min(1.0, float(ch.xct_amount) * 1.05),
                mode == "XCT",
            )
        if sat_on:
            drive = float(np.clip(ch.clr_drive, 0.0, 1.0))
            amber = TONE_HEX_CLR
            for layer in range(6):
                t = layer / max(1, 5)
                hue = 0.072 + 0.038 * drive * (1 - t * 0.5)
                col = hsv_to_hex(min(1.0, hue), 0.28 + drive * 0.58, 0.22 + drive * (0.50 + t * 0.22))
                r = 14 + drive * (24 + layer * t * 7)
                ww = (4 if mode == "CLR" and layer >= 5 else 2) + (int(drive > 0.85) if layer == 5 else 0)
                c.create_oval(cx - r, cy - r * 0.70, cx + r, cy + r * 0.70, outline=col if layer < 5 else amber, width=min(ww, 6))

        c.create_text(
            22,
            h - 30,
            anchor="w",
            text=(
                "Tone: TRN / XCT band shells = red edit overlays on the analyzer polar • CLR amber = tube drive • "
                "cap TRN/CLR/XCT picks row (FRQ BD2 DRV XCT)"
            ),
            fill="#5d7588" if (transient_on or sat_on or xct_on) else "#3d4753",
            font=("Segoe UI", 8),
        )

    def _draw_strips(self) -> None:
        """Hardware-mirror strip view.

        Layout (top -> bottom):
          1. Per-channel strip body: waveform, record arm — then shared STAGES
             matrix (channels × PRE/HRM/… slots) bridging all columns.
          2. Below that: strip ID (01–13 / MST), pan/send knob, vertical fader,
             footer split SOLO (left) + MUTE (right), or full-width MST on master.
        """
        c = self.strip_canvas
        c.delete("all")
        self.stage_hitboxes = []
        self.record_hitboxes = []
        self.scribble_hitboxes = []
        width = max(c.winfo_width(), 980)
        height = max(c.winfo_height(), 720)
        c.create_rectangle(0, 0, width, height, fill="#0c1014", outline="")

        margin_x = 18
        top_y = 14
        strip_gap = 8
        strip_w = self.STRIP_WIDTH
        strip_sources = list(self.engine.channels) + [self.engine.master_channel]
        n_strips = len(strip_sources)
        total_w = n_strips * strip_w + (n_strips - 1) * strip_gap
        start_x = max(margin_x, (width - total_w) / 2)

        if self.nav_scope == "editor":
            active_strip_index = self.editor_channel
        else:
            active_strip_index = self.selected_channel
        console_row_active = self.console_row if self.nav_scope == "console" else None

        stage_keys = ["pre", "harm", "gate", "comp", "eq", "tone"]
        stage_labels_map = {"pre": "PRE", "harm": "HAR", "gate": "GTE", "comp": "CMP", "eq": "EQ", "tone": "TON"}
        grid_label_h = 14
        grid_cell_h = 16
        grid_top_pad = 8
        grid_bot_pad = 8
        grid_h = grid_label_h + len(stage_keys) * grid_cell_h + grid_top_pad + grid_bot_pad

        # ---------- PER-CHANNEL COLUMNS: outer + waveform + REC (STAGES bridges below REC) ----------
        body_y0 = top_y + 10
        bottom_y = height - 14
        body_h = bottom_y - body_y0
        label_h = 18
        record_h = 26
        pan_h = 50
        footer_h = 28
        spacers = 14
        # Strip STAGES occupies channel-space between REC and IDs — reserve vertical budget.
        fixed_h = grid_h + label_h + record_h + pan_h + footer_h + spacers
        remaining_h = max(80, body_h - fixed_h)
        waveform_h = int(remaining_h * 0.55)
        fader_h = remaining_h - waveform_h

        for col, ch in enumerate(strip_sources):
            x0 = start_x + col * (strip_w + strip_gap)
            x1 = x0 + strip_w
            is_master = col == len(self.engine.channels)
            selected_channel = col == active_strip_index

            outer_fill = "#181e25" if not is_master else "#1b1d24"
            outer_outline = "#30404f" if not is_master else "#506071"
            c.create_rectangle(x0, body_y0, x1, bottom_y,
                               fill=outer_fill, outline=outer_outline, width=1)
            if not is_master and col in self.strip_link_indices:
                c.create_rectangle(
                    x0 - 3,
                    body_y0 - 3,
                    x1 + 3,
                    bottom_y + 3,
                    outline="#e8b84a",
                    width=2,
                )

            cur_y = body_y0 + 4

            # WAVEFORM (top of strip body)
            wf_x0 = x0 + 5
            wf_x1 = x1 - 5
            wf_y0 = cur_y
            wf_y1 = cur_y + waveform_h
            c.create_rectangle(wf_x0, wf_y0, wf_x1, wf_y1,
                               fill="#0a0d11", outline="#1d2735")
            self._draw_vertical_waveform(c, ch, wf_x0 + 2, wf_y0 + 2,
                                         wf_x1 - 2, wf_y1 - 2, is_master)
            cur_y = wf_y1 + 4

            # RECORD ARM
            rec_top = cur_y
            rec_bot = cur_y + record_h - 4
            if not is_master:
                record_selected = selected_channel and console_row_active == "record"
                c.create_rectangle(
                    x0 + 14, rec_top, x1 - 14, rec_bot,
                    fill="#232b34" if record_selected else "#10151b",
                    outline="#f8d58a" if record_selected else "#2b3743",
                    width=2 if record_selected else 1,
                )
                cx = (x0 + x1) / 2
                cy_rec = (rec_top + rec_bot) / 2
                rr = max(4, (rec_bot - rec_top) / 2 - 4)
                c.create_oval(
                    cx - rr, cy_rec - rr, cx + rr, cy_rec + rr,
                    fill="#ff3b30" if ch.record_armed else "#ff7b73",
                    outline="#ffd7d3" if ch.record_armed else "",
                    width=1 if ch.record_armed else 0,
                )
                self.record_hitboxes.append((x0 + 14, rec_top, x1 - 14, rec_bot, col))
            cur_y = rec_bot + 4

        # ---------- STAGE GRID between REC row and channel-ID row ----------
        grid_x0 = start_x - 12
        grid_x1 = start_x + total_w + 12
        grid_y0 = body_y0 + 4 + waveform_h + 4 + record_h
        grid_y1 = grid_y0 + grid_h
        c.create_rectangle(grid_x0, grid_y0, grid_x1, grid_y1, fill="#0a0d12", outline="#1f2933")
        c.create_text(grid_x0 + 8, grid_y0 + 4, anchor="nw", text="STAGES",
                      fill="#5ec8ff", font=("Segoe UI", 8, "bold"))
        cells_y0 = grid_y0 + grid_label_h + grid_top_pad
        for r, key in enumerate(stage_keys):
            cy = cells_y0 + r * grid_cell_h
            c.create_text(grid_x0 + 8, cy + grid_cell_h / 2, anchor="w",
                          text=stage_labels_map[key], fill="#62748a",
                          font=("Segoe UI", 7, "bold"))
            for col, ch in enumerate(strip_sources):
                cx0 = start_x + col * (strip_w + strip_gap) + 4
                cx1 = cx0 + strip_w - 8
                cy0 = cy + 2
                cy1 = cy + grid_cell_h - 2
                is_master_col = col == len(self.engine.channels)
                if is_master_col and key == "pre":
                    c.create_rectangle(cx0, cy0, cx1, cy1, fill="#10151b", outline="#1c2530")
                    continue
                enabled = self._stage_enabled(ch, key)
                sel_match = (
                    active_strip_index == col
                    and self.selected_stage_key == key
                    and (
                        self.nav_scope == "editor"
                        or (self.nav_scope == "console" and console_row_active == "stages")
                    )
                )
                base = self.stage_color[key] if enabled else "#1c2530"
                if not enabled:
                    fill_color = "#10151b"
                else:
                    fill_color = base
                border = "#d9e6f2" if sel_match else ("#2a3848" if not enabled else base)
                c.create_rectangle(cx0, cy0, cx1, cy1, fill=fill_color,
                                   outline=border, width=2 if sel_match else 1)
                if enabled:
                    c.create_rectangle(cx0 + 2, cy0 + 2, cx1 - 2, cy1 - 2,
                                       fill=base, outline="")
                self.stage_hitboxes.append((cx0, cy0, cx1, cy1, col, key))

        # ---------- PER-CHANNEL: ID row, pan, fader, footer ----------
        id_block_y0 = grid_y1 + 10

        for col, ch in enumerate(strip_sources):
            x0 = start_x + col * (strip_w + strip_gap)
            x1 = x0 + strip_w
            is_master = col == len(self.engine.channels)
            selected_channel = col == active_strip_index

            cur_y = id_block_y0 + 4

            # Channel-ID / scribble indicators (below STAGES)
            lbl_y0 = cur_y
            lbl_y1 = cur_y + label_h - 4
            c.create_rectangle(x0 + 3, lbl_y0, x1 - 3, lbl_y1,
                               fill="#1e2a36" if not is_master else "#272e38",
                               outline="")
            ch_label = "MST" if is_master else f"{col + 1:02d}"
            c.create_text((x0 + x1) / 2, (lbl_y0 + lbl_y1) / 2,
                          text=ch_label, fill="#d6e1ec",
                          font=("Orbitron", 9, "bold"))
            cur_y = lbl_y1 + 4

            # SEND KNOB (formerly pan)
            kn_x0 = x0 + 6
            kn_x1 = x1 - 6
            kn_y0 = cur_y
            kn_y1 = cur_y + pan_h - 4
            knob_focused = (
                not is_master
                and (
                    (self.nav_scope == "knobs"
                     and self.knob_focus_channel == col)
                    or (self.nav_scope == "console"
                        and self.console_row == "knob"
                        and self.selected_channel == col)
                )
            )
            self._draw_send_knob(c, ch, kn_x0, kn_y0, kn_x1, kn_y1,
                                 focused=knob_focused, channel_idx=col)
            cur_y = kn_y1 + 4

            # FADER (vertical, ch.gain)
            fd_x0 = x0 + 12
            fd_x1 = x1 - 12
            fd_y0 = cur_y
            fd_y1 = bottom_y - footer_h - 6
            fader_focused = (
                not is_master
                and (
                    (self.nav_scope == "faders"
                     and self.fader_focus_channel == col)
                    or (self.nav_scope == "console"
                        and self.console_row == "fader"
                        and self.selected_channel == col)
                )
            )
            self._draw_strip_fader(c, ch, fd_x0, fd_y0, fd_x1, fd_y1,
                                   is_master, focused=fader_focused)

            # FOOTER: SOLO (left) + MUTE (right), or full-width MST on master bus
            ft_x0 = x0 + 8
            ft_x1 = x1 - 8
            ft_y0 = bottom_y - footer_h - 2
            ft_y1 = bottom_y - 4
            footer_selected = selected_channel and console_row_active == "footer"
            cy = (ft_y0 + ft_y1) / 2
            if is_master:
                c.create_rectangle(ft_x0, ft_y0, ft_x1, ft_y1,
                                   fill="#1b222a", outline="#31404e")
                cx = (ft_x0 + ft_x1) / 2
                if footer_selected:
                    c.create_rectangle(ft_x0 + 2, ft_y0 + 2, ft_x1 - 2, ft_y1 - 2,
                                       fill="#2a313b", outline="")
                c.create_text(cx, cy, text="MST", fill="#d8dfe8",
                              font=("Orbitron", 8, "bold"))
            else:
                mid = (ft_x0 + ft_x1) / 2
                g = 2
                s_x1 = mid - g
                m_x0 = mid + g
                nav_focus = footer_selected
                s_outline = "#f8d58a" if (nav_focus or ch.solo) else "#3d4a5a"
                m_outline = "#f8d58a" if (nav_focus or ch.mute) else "#3d4a5a"
                s_w = 2 if (nav_focus or ch.solo) else 1
                m_w = 2 if (nav_focus or ch.mute) else 1
                # SOLO — left half
                s_fill = "#645019" if ch.solo else "#1b222a"
                c.create_rectangle(ft_x0, ft_y0, s_x1, ft_y1,
                                   fill=s_fill, outline=s_outline, width=s_w)
                c.create_text((ft_x0 + s_x1) / 2, cy, text="S",
                              fill="#fff0b2" if ch.solo else "#7a8a9c",
                              font=("Orbitron", 9, "bold"))
                # MUTE — right half
                m_fill = "#6b171c" if ch.mute else "#1b222a"
                c.create_rectangle(m_x0, ft_y0, ft_x1, ft_y1,
                                   fill=m_fill, outline=m_outline, width=m_w)
                c.create_text((m_x0 + ft_x1) / 2, cy, text="M",
                              fill="#ffd7d3" if ch.mute else "#7a8a9c",
                              font=("Orbitron", 9, "bold"))
                self.scribble_hitboxes.append((ft_x0, ft_y0, s_x1, ft_y1, col, "solo"))
                self.scribble_hitboxes.append((m_x0, ft_y0, ft_x1, ft_y1, col, "mute"))

        self._draw_master_meter()

    # ------------------------------------------------------------------ #
    # Strip-view helpers (top grid + per-channel waveform/knob/fader)
    # ------------------------------------------------------------------ #
    def _draw_vertical_waveform(self, c: tk.Canvas, ch: ChannelState,
                                x0: float, y0: float, x1: float, y1: float,
                                is_master: bool) -> None:
        """Vertical orange waveform: time runs top -> bottom, amplitude
        deflects left/right from the column's center axis. A bright
        playhead line marks ``ch.position``."""
        h = y1 - y0
        w = x1 - x0
        if h < 6 or w < 4:
            return
        cx = (x0 + x1) / 2
        half_w = w / 2 - 1
        if is_master or ch.audio is None or len(ch.audio) == 0:
            # Master / empty: render a flat axis with a faint glow so the
            # column doesn't look broken.
            c.create_line(cx, y0 + 2, cx, y1 - 2, fill="#2a313b", width=1)
            return

        pv = np.asarray(ch.wave_preview, dtype=np.float32).reshape(-1)
        rows = max(8, int(h))
        if pv.size <= 1 or float(np.max(pv)) < 1e-10:
            c.create_line(cx, y0 + 2, cx, y1 - 2, fill="#2a313b", width=1)
            return

        xp = np.linspace(0.0, 1.0, int(pv.size), dtype=np.float64)
        xd = ((np.arange(rows, dtype=np.float64) + 0.5) / float(rows)).clip(0.0, 1.0)
        peaks = np.interp(xd, xp, pv.astype(np.float64)).astype(np.float32)

        step = h / rows
        for i in range(rows):
            yt = y0 + i * step
            yb = yt + step
            p = float(peaks[i])
            ext = p * half_w
            if ext < 0.5:
                continue
            c.create_rectangle(cx - ext, yt, cx + ext, yb,
                               fill="#ff8c1a", outline="")
        c.create_line(cx, y0, cx, y1, fill="#3a2410", width=1)
        n_samples = len(ch.audio)
        if n_samples > 1:
            ph = max(0.0, min(1.0, ch.position / float(n_samples)))
            phy = y0 + ph * h
            c.create_line(x0, phy, x1, phy, fill="#ffd97a", width=2)

    def _draw_send_knob(self, c: tk.Canvas, ch: ChannelState,
                        x0: float, y0: float, x1: float, y1: float,
                        focused: bool = False, channel_idx: int = -1) -> None:
        """Per-channel knob. Renders one of two modes for the WHOLE row:

        - PAN (default, ``knobs_send_mode`` is False): indicator shows
          ch.pan (-1..+1) with the centerline straight up at pan=0.
        - SEND (``knobs_send_mode`` is True): indicator shows
          ch.send_level (0..1) and the face shows the active send slot
          ``S<N>`` so the operator can see which bus is being dialed.

        ``focused`` paints a bright outer ring on the knob the cap is on.
        """
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        r = max(8, min((x1 - x0), (y1 - y0)) / 2 - 4)
        send_mode = bool(getattr(self, "knobs_send_mode", False))
        send_muted = bool(getattr(ch, "send_muted", False)) and send_mode
        if focused:
            c.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
                          outline="#7cf0a9", width=2)
        outer_color = "#33485e" if not send_muted else "#2a323d"
        inner_color = "#1a2330" if not send_muted else "#141a20"
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      fill=inner_color, outline=outer_color, width=1)
        c.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62,
                      fill="#0f161f", outline="#28394d", width=1)
        # Indicator angle depends on mode.
        if send_mode:
            level = float(np.clip(getattr(ch, "send_level", 0.0), 0.0, 1.0))
            # 0..1 maps to -135..+135 deg around 12 o'clock.
            angle_deg = -90 - 135 + level * 270.0
            ind_color = "#ff8c1a" if not send_muted else "#5b6c80"
        else:
            pan = float(np.clip(getattr(ch, "pan", 0.0), -1.0, 1.0))
            # -1..+1 maps to -135..+135 deg around 12 o'clock; 0.0 = straight up.
            angle_deg = -90 + pan * 135.0
            ind_color = "#7cd7ff"  # cool blue for pan to distinguish from send orange
        angle = math.radians(angle_deg)
        ix = cx + math.cos(angle) * (r - 3)
        iy = cy + math.sin(angle) * (r - 3)
        c.create_line(cx, cy, ix, iy, fill=ind_color, width=2)
        # Min/max ticks at 7 o'clock / 5 o'clock.
        for tick_a in (-90 - 135, -90 + 135):
            ar = math.radians(tick_a)
            sx = cx + math.cos(ar) * (r + 1)
            sy = cy + math.sin(ar) * (r + 1)
            ex = cx + math.cos(ar) * (r + 4)
            ey = cy + math.sin(ar) * (r + 4)
            c.create_line(sx, sy, ex, ey, fill="#5b6c80", width=1)
        # Center tick at 12 o'clock (visual home position for pan).
        if not send_mode:
            ctop_x = cx
            ctop_y0 = cy - r - 1
            ctop_y1 = cy - r - 5
            c.create_line(ctop_x, ctop_y0, ctop_x, ctop_y1,
                          fill="#5b6c80", width=1)
        # Center label on the knob face.
        if send_mode:
            slot = int(getattr(ch, "send_slot", 1))
            face_text = f"S{slot}"
        else:
            face_text = "PAN"
        c.create_text(cx, cy - 1, text=face_text,
                      fill="#9aa6b6" if send_muted else "#d6e1ec",
                      font=("Segoe UI", 7, "bold"))
        # Bottom corners: mode tag + value.
        if send_mode:
            level = float(np.clip(getattr(ch, "send_level", 0.0), 0.0, 1.0))
            tag, value_txt = "SND", ("OFF" if send_muted else f"{int(level * 100):02d}")
        else:
            pan = float(np.clip(getattr(ch, "pan", 0.0), -1.0, 1.0))
            if abs(pan) < 0.01:
                value_txt = "C"
            else:
                value_txt = f"{'L' if pan < 0 else 'R'}{int(abs(pan) * 100):02d}"
            tag = "PAN"
        c.create_text(x0 + 4, cy + r + 4, text=tag, fill="#5b6c80",
                      font=("Segoe UI", 6, "bold"), anchor="w")
        c.create_text(x1 - 4, cy + r + 4, text=value_txt,
                      fill="#9aa6b6" if send_muted else "#d6e1ec",
                      font=("Segoe UI", 6, "bold"), anchor="e")

    def _draw_strip_fader(self, c: tk.Canvas, ch: ChannelState,
                          x0: float, y0: float, x1: float, y1: float,
                          is_master: bool, focused: bool = False) -> None:
        """Vertical fader. ch.gain range 0.3..2.2; unity (1.0) sits 70% down
        the track so most of the visible travel is below unity with some
        boost head-room above. ``focused`` paints a green outline when the
        SpaceMouse cap is parked on this fader (nav_scope == "faders")."""
        cx = (x0 + x1) / 2
        track_w = max(4, (x1 - x0) - 6)
        if focused:
            c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2,
                               outline="#5ef0b0", width=2)
        # Track
        c.create_rectangle(cx - track_w / 2, y0, cx + track_w / 2, y1,
                           fill="#10151b", outline="#28323d")
        # Level meter overlay (live signal level inside the track).
        meter_fill = float(np.clip(ch.level, 0.0, 1.0))
        if meter_fill > 0.001:
            meter_y = y1 - (y1 - y0) * meter_fill
            meter_color = "#5ef0b0" if meter_fill < 0.7 else ("#f7c46f" if meter_fill < 0.9 else "#ff6868")
            c.create_rectangle(cx - track_w / 2 + 2, meter_y,
                               cx + track_w / 2 - 2, y1 - 2,
                               fill=meter_color, outline="")
        # Unity tick marks (every ~6dB-ish, just visual).
        for frac in (0.10, 0.30, 0.50, 0.70, 0.90):
            ty = y0 + (y1 - y0) * frac
            c.create_line(x0, ty, x0 + 4, ty, fill="#33485e")
            c.create_line(x1 - 4, ty, x1, ty, fill="#33485e")
        # Fader knob position. Map gain 0.3..2.2 -> 0..1, unity (1.0) at 0.70.
        gain = float(np.clip(getattr(ch, "gain", 1.0), 0.3, 2.2))
        if gain <= 1.0:
            frac = (gain - 0.3) / (1.0 - 0.3) * 0.70
        else:
            frac = 0.70 + (gain - 1.0) / (2.2 - 1.0) * 0.30
        thumb_y = y1 - (y1 - y0) * frac
        thumb_h = 14
        thumb_w = (x1 - x0) + 4
        c.create_rectangle(cx - thumb_w / 2, thumb_y - thumb_h / 2,
                           cx + thumb_w / 2, thumb_y + thumb_h / 2,
                           fill="#ff8c1a" if not is_master else "#7cf0a9",
                           outline="#1a1a1a")
        c.create_line(cx - thumb_w / 2 + 2, thumb_y, cx + thumb_w / 2 - 2, thumb_y,
                      fill="#1a1a1a", width=1)

    def _stage_enabled(self, ch: ChannelState, key: str) -> bool:
        return {
            "pre": ch.pre_enabled,
            "harm": ch.harmonics_enabled,
            "gate": ch.gate_enabled,
            "comp": ch.comp_enabled,
            "eq": ch.eq_enabled,
            "tone": ch.tone_enabled,
        }[key]

    def _draw_stage_visual(self, c: tk.Canvas, ch: ChannelState, key: str, x0: float, y0: float, x1: float, y1: float, enabled: bool, selected: bool, focus: bool = False) -> None:
        w = x1 - x0
        h = y1 - y0
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        outline = "#f8d58a" if selected else "#526579"
        box_fill = "#202832"
        if selected:
            c.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, fill="#f8d58a", outline="")
        c.create_rectangle(x0, y0, x1, y1, fill=box_fill, outline=outline, width=2 if selected else 1)
        oval_x0 = x0 + w * 0.08
        oval_x1 = x1 - w * 0.08
        oval_y0 = y0 + h * 0.08
        oval_y1 = y1 - h * 0.08
        c.create_oval(oval_x0, oval_y0, oval_x1, oval_y1, outline="#25313d", width=1)
        c.create_oval(oval_x0 + w * 0.10, oval_y0 + h * 0.10, oval_x1 - w * 0.10, oval_y1 - h * 0.10, outline="#1f2b37", width=1)
        if key == "pre":
            # Phoenix-style mic pre faceplate
            c.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3, fill="#2d333a", outline="#586472")
            c.create_rectangle(x0 + 5, y0 + 5, x1 - 5, y1 - 5, fill="#313842", outline="#1d232a")
            knob_r = min(w, h) * 0.18
            knob_cx = center_x
            knob_cy = y0 + h * 0.72
            c.create_oval(knob_cx - knob_r, knob_cy - knob_r, knob_cx + knob_r, knob_cy + knob_r, fill="#b62023" if enabled else "#39424c", outline="#ffb7aa" if enabled else "#4c5864", width=1)
            for angle in range(-120, 121, 30):
                a = math.radians(angle)
                sx = knob_cx + math.cos(a) * (knob_r + 2)
                sy = knob_cy + math.sin(a) * (knob_r + 2)
                ex = knob_cx + math.cos(a) * (knob_r + 8)
                ey = knob_cy + math.sin(a) * (knob_r + 8)
                c.create_line(sx, sy, ex, ey, fill="#e5e8eb" if enabled else "#53606d", width=1)
            c.create_line(knob_cx, knob_cy, knob_cx + knob_r * 0.7, knob_cy - knob_r * 0.35, fill="#ffe0d7" if enabled else "#5a6774", width=2)
            for i, color in enumerate(("#47d05f", "#47d05f", "#47d05f", "#e3ce55", "#ff5b54")):
                ly = y0 + h * (0.82 - i * 0.10)
                c.create_oval(x0 + 8, ly - 3, x0 + 14, ly + 3, fill=color if enabled else "#29313b", outline="")
            if enabled and ch.phantom:
                c.create_oval(x0 + 8, y0 + 8, x0 + 14, y0 + 14, fill="#ff5b54", outline="")
            if enabled and ch.phase:
                c.create_oval(x0 + w * 0.18, y0 + h * 0.40, x0 + w * 0.34, y0 + h * 0.56, outline="#d7dde5", width=1)
                c.create_line(x0 + w * 0.20, y0 + h * 0.54, x0 + w * 0.32, y0 + h * 0.42, fill="#d7dde5", width=1)
            if ch.tube:
                c.create_text(x1 - 12, y0 + 12, text="~", fill="#ff5b54", font=("Segoe UI", 14, "bold"))
            if enabled and ch.hpf_enabled:
                c.create_text(x1 - 12, y0 + h * 0.34, text="HPF", fill="#e6e9ee", font=("Segoe UI", 6, "bold"))
            if enabled and ch.lpf_enabled:
                c.create_text(x0 + 12, y0 + h * 0.18, text="LP", fill="#e6e9ee", font=("Segoe UI", 6, "bold"))
        elif key == "harm":
            # 3D harmonics bloom
            petals = 8
            amp = max(0.25, float(np.max(ch.harmonics)) * 1.8 if enabled else 0.25)
            pts = []
            rx0 = w * 0.26
            ry0 = h * 0.24
            for step in range(96):
                t = step / 96.0 * math.tau
                petal = 1.0 + 0.35 * math.sin(t * petals) * amp
                x = center_x + math.cos(t) * rx0 * petal
                y = center_y + math.sin(t) * ry0 * petal
                pts.extend([x, y])
            c.create_polygon(*pts, fill="#7cbcff" if enabled else "#31404d", outline="#4a7fd8" if enabled else "#465565", smooth=True)
            pts2 = []
            for step in range(96):
                t = step / 96.0 * math.tau
                petal = 1.0 + 0.32 * math.sin(t * petals + 0.8) * amp
                x = center_x + math.cos(t + 0.6) * rx0 * 0.82 * petal
                y = center_y + math.sin(t + 0.6) * ry0 * 0.82 * petal
                pts2.extend([x, y])
            c.create_polygon(*pts2, fill="#ff7d7d" if enabled else "#39424c", outline="#c64242" if enabled else "#566270", smooth=True)
            c.create_oval(center_x - 5, center_y - 5, center_x + 5, center_y + 5, fill="#ffb347" if enabled else "#44505c", outline="")
        elif key == "gate":
            c.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3, fill="#101f1b", outline="#2d6f5c")
            c.create_rectangle(x0 + 6, y0 + 6, x1 - 6, y0 + h * 0.55, fill="#2ab89a", outline="#1f5f51")
            gate_gr = min(1.0, max(0.0, getattr(ch, "gate_gr_db", 0.0) / 30.0))
            vu_cx = center_x
            vu_cy = y0 + h * 0.62
            radius = min(w * 0.32, h * 0.4)
            for tick in range(-20, 4, 4):
                ang = math.radians(-150 + (tick + 20) / 23.0 * 120.0)
                sx = vu_cx + math.cos(ang) * (radius - 2)
                sy = vu_cy + math.sin(ang) * (radius - 2)
                ex = vu_cx + math.cos(ang) * (radius + 5)
                ey = vu_cy + math.sin(ang) * (radius + 5)
                c.create_line(sx, sy, ex, ey, fill="#2d574d", width=1)
            ang = math.radians(-150 + gate_gr * 120.0)
            ex = vu_cx + math.cos(ang) * (radius + 2)
            ey = vu_cy + math.sin(ang) * (radius + 2)
            c.create_line(vu_cx, vu_cy, ex, ey, fill="#fce37b", width=2)
            c.create_text(vu_cx, y0 + h * 0.15, text="GTE", fill="#b7fff0", font=("Segoe UI", 8, "bold"))
        elif key == "comp":
            # Analog VU meter style
            c.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3, fill="#151311", outline="#403126")
            c.create_rectangle(x0 + 6, y0 + 6, x1 - 6, y0 + h * 0.58, fill="#f0c585", outline="#a36d43")
            vu_cx = center_x
            vu_cy = y0 + h * 0.60
            radius = min(w * 0.33, h * 0.42)
            for tick in range(-20, 4, 4):
                ang = math.radians(-150 + (tick + 20) / 23.0 * 120.0)
                sx = vu_cx + math.cos(ang) * (radius - 2)
                sy = vu_cy + math.sin(ang) * (radius - 2)
                ex = vu_cx + math.cos(ang) * (radius + 5)
                ey = vu_cy + math.sin(ang) * (radius + 5)
                c.create_line(sx, sy, ex, ey, fill="#7d4c29", width=1)
            gr = min(1.0, max(0.0, ch.comp_gr_db / 18.0 if enabled else 0.0))
            ang = math.radians(-150 + gr * 120.0)
            ex = vu_cx + math.cos(ang) * (radius + 2)
            ey = vu_cy + math.sin(ang) * (radius + 2)
            c.create_line(vu_cx, vu_cy, ex, ey, fill="#c74633", width=2)
            c.create_text(vu_cx, y0 + h * 0.16, text="VU", fill="#5e3a27", font=("Segoe UI", 8, "bold"))
        elif key == "eq":
            # Phoenix-style EQ button/module feel
            c.create_rectangle(x0 + 3, y0 + 3, x1 - 3, y1 - 3, fill="#2d333a", outline="#586472")
            c.create_rectangle(x0 + 5, y0 + 5, x1 - 5, y1 - 5, fill="#313842", outline="#1d232a")
            upper_r = min(w, h) * 0.13
            lower_r = min(w, h) * 0.16
            c.create_oval(center_x - upper_r, y0 + h * 0.24 - upper_r, center_x + upper_r, y0 + h * 0.24 + upper_r, fill="#b62023" if enabled else "#4f2224", outline="#ffd7d3", width=1)
            c.create_oval(center_x - lower_r, y0 + h * 0.66 - lower_r, center_x + lower_r, y0 + h * 0.66 + lower_r, fill="#b62023" if enabled else "#4f2224", outline="#ffd7d3", width=1)
            c.create_text(center_x, y0 + h * 0.47, text="EQ", fill="#f0f2f5", font=("Segoe UI", 7, "bold"))
            gdb, fq = self._channel_eq_indicator_gain_freq(ch)
            gain_col = eq_rainbow_color(gdb, fq) if enabled else "#3d4856"
            c.create_oval(x0 + 8, y0 + h * 0.78 - 4, x0 + 16, y0 + h * 0.78 + 4, fill=gain_col, outline="")
        elif key == "tone":
            # Outer shell = transient (TRN teal), inner = exciter (XCT violet); drive dot = CLR.
            pts = []
            rx0 = w * 0.25
            ry0 = h * 0.22
            amp = 0.35 + min(1.0, ch.trn_attack + ch.clr_drive + ch.xct_amount)
            for step in range(72):
                t = step / 72.0 * math.tau
                mod = 1.0 + 0.28 * math.cos(t * 6.0) * amp
                x = center_x + math.cos(t) * rx0 * mod
                y = center_y + math.sin(t) * ry0 * mod
                pts.extend([x, y])
            shell1 = "#123330" if enabled else "#33414f"
            c.create_polygon(*pts, fill=shell1, outline=TONE_HEX_TRN, smooth=True, width=1)
            pts2 = []
            for step in range(72):
                t = step / 72.0 * math.tau
                mod = 1.0 + 0.24 * math.sin(t * 5.0 + 0.7) * amp
                x = center_x + math.cos(t + 0.5) * rx0 * 0.72 * mod
                y = center_y + math.sin(t + 0.5) * ry0 * 0.72 * mod
                pts2.extend([x, y])
            shell2 = "#291a38" if enabled else "#3c434c"
            c.create_polygon(*pts2, fill=shell2, outline=TONE_HEX_XCT, smooth=True, width=1)
            c.create_oval(
                center_x - 4,
                center_y - 4,
                center_x + 4,
                center_y + 4,
                fill=TONE_HEX_CLR if enabled else "#3c4652",
                outline=TONE_HEX_CLR if enabled else "",
            )

    def _adjust_send_level_axis(self, axis_value: float) -> None:
        """SpaceMouse twist while focused on the per-channel knob row.
        Routes the twist by the row's current mode:

        - PAN  (knobs_send_mode is False): adjusts ch.pan in [-1, +1].
        - SEND (knobs_send_mode is True): adjusts ch.send_level in [0, 1].

        Twist sensitivity is kept gentle so the operator can dial without
        overshoot."""
        if abs(axis_value) < 0.01:
            return
        n = len(self.engine.channels)
        idx = self.knob_focus_channel
        if not (0 <= idx < n):
            return
        ch = self.engine.channels[idx]
        with self.engine._lock:
            if self.knobs_send_mode:
                ch.send_level = float(np.clip(ch.send_level + axis_value * 0.04, 0.0, 1.0))
            else:
                ch.pan = float(np.clip(ch.pan + axis_value * 0.04, -1.0, 1.0))
        self._sync_from_engine()

    def _adjust_console_channel_axis(self, axis_value: float) -> None:
        """SpaceMouse twist in console: knob/fader rows adjust pan/send or gain; OSC when armed.

        Stages / REC / footer use **tilt** (LRUD) for channel + row — twist is reserved for
        CW/CCW editor open and must not page channels during a hold.
        """
        if abs(axis_value) < 0.01:
            return
        n = len(self.engine.channels)
        idx = self.selected_channel
        if self.console_row == "knob" and 0 <= idx < n:
            ch = self.engine.channels[idx]
            with self.engine._lock:
                if self.knobs_send_mode:
                    ch.send_level = float(np.clip(ch.send_level + axis_value * 0.04, 0.0, 1.0))
                else:
                    ch.pan = float(np.clip(ch.pan + axis_value * 0.04, -1.0, 1.0))
            self._sync_from_engine()
            return
        if self.console_row == "fader" and 0 <= idx < n:
            ch = self.engine.channels[idx]
            with self.engine._lock:
                ch.gain = float(np.clip(ch.gain + axis_value * 0.04, 0.3, 2.2))
            self._sync_from_engine()
            return
        if self.console_row in ("stages", "record", "footer"):
            return
        if abs(axis_value) < 0.06:
            return
        if not self._axis_discrete_tick(axis_value=axis_value, magnitude=DISCRETE_TWIST_MIN):
            return
        span = self._channel_nav_span()
        self.selected_channel = (self.selected_channel + (1 if axis_value > 0 else -1)) % span
        self._normalize_console_selection()
        self._sync_from_engine()

    def _cancel_pending_stage_click(self) -> None:
        if self._pending_stage_action is not None:
            self.root.after_cancel(self._pending_stage_action)
            self._pending_stage_action = None

    def _stage_delayed_toggle(self, idx: int, key: str) -> None:
        self._pending_stage_action = None
        self._toggle_stage_module(idx, key)

    def _toggle_stage_module(self, idx: int, key: str) -> None:
        """Engage / disengage a strip module (single click)."""
        if idx >= len(self.engine.channels) and key == "pre":
            return
        self._toggle_stage_enabled_only(idx, key)
        self.selected_channel = idx
        self.selected_stage_key = key
        self.nav_scope = "console"
        self.console_row = "stages"
        self._sync_from_engine()

    def _toggle_stage_enabled_only(self, idx: int, key: str) -> None:
        if idx >= len(self.engine.channels) and key == "pre":
            return
        ch = self.engine.channels[idx] if idx < len(self.engine.channels) else self.engine.master_channel
        with self.engine._lock:
            if key == "pre":
                ch.pre_enabled = not ch.pre_enabled
            elif key == "harm":
                ch.harmonics_enabled = not ch.harmonics_enabled
            elif key == "gate":
                ch.gate_enabled = not ch.gate_enabled
            elif key == "comp":
                ch.comp_enabled = not ch.comp_enabled
            elif key == "eq":
                ch.eq_enabled = not ch.eq_enabled
            elif key == "tone":
                ch.tone_enabled = not ch.tone_enabled

    def _engage_stage_module(self, idx: int, key: str) -> None:
        """Turn a selected module on without making SpaceMouse press act like a toggle."""
        if idx >= len(self.engine.channels) and key == "pre":
            return
        ch = self.engine.channels[idx] if idx < len(self.engine.channels) else self.engine.master_channel
        with self.engine._lock:
            if key == "pre":
                ch.pre_enabled = True
            elif key == "harm":
                ch.harmonics_enabled = True
                if not np.any(ch.harmonics > 0.001):
                    ch.harmonics[0] = 0.35
            elif key == "gate":
                ch.gate_enabled = True
            elif key == "comp":
                ch.comp_enabled = True
            elif key == "eq":
                ch.eq_band_count = max(1, ch.eq_band_count)
                self.eq_selected_band = min(self.eq_selected_band, ch.eq_band_count - 1)
                band = self._eq_band(ch, self.eq_selected_band)
                band["enabled"] = True
                if abs(float(band["gain_db"])) <= 0.05:
                    band["gain_db"] = 3.0
                ch.eq_enabled = True
            elif key == "tone":
                ch.tone_enabled = True
                if all(v <= 0.02 for v in (ch.trn_attack, ch.trn_sustain, ch.clr_drive, ch.xct_amount)):
                    ch.trn_attack = 0.45
                    ch.trn_sustain = 0.35

    def _toggle_or_open_stage_from_console(self, idx: int, key: str) -> None:
        if idx >= len(self.engine.channels) and key == "pre":
            return
        self._toggle_stage_module(idx, key)

    def _open_stage_editor(self, idx: int, key: str, focus_body: bool = False) -> None:
        self._capture_editor_return_context()
        # Viewing/editing a stage must not flip bypass or prime parameters —
        # that only happens via explicit toggle (strip click, grid PRESS on T/TBE/header, etc.).
        self.selected_channel = idx
        self.editor_channel = idx
        self.selected_stage_key = key
        self.console_row = "stages"
        self.nav_scope = "editor"
        unify_cols = {row[0]: ri for ri, row in enumerate(self._STAGE_GRID)}
        if key in unify_cols:
            icol = unify_cols[key]
            self.editor_stage_col = icol
            self.editor_unified_header_focus = False
            plist = self._STAGE_GRID[icol][2]
            if plist:
                self.editor_param_row = self._unified_pick_param_row_entering_stage(
                    icol, self.editor_param_row
                )
            else:
                self.editor_param_row = 0
            self.editor_nav_scope = "stage_grid"
            self._sync_from_engine()
            self.root.focus_set()
            return
        if key == "pre":
            self.pre_editor_column = 2 if focus_body else 1
            self.editor_nav_scope = "pre-body" if focus_body else "pre-stage"
        else:
            self.module_editor_column = 2 if focus_body else 1
            self._reset_module_body_selection()
            self._normalize_module_editor_positions()
            self.editor_nav_scope = "module-body" if focus_body else "module-stage"
        self._sync_from_engine()
        self.root.focus_set()

    def _on_strip_mousewheel(self, event) -> None:
        if self.nav_scope != "console":
            return
        for x0, y0, x1, y1, idx, key in getattr(self, "stage_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                delta = int(getattr(event, "delta", 0))
                step = 1 if delta > 0 else -1
                span = self._channel_nav_span()
                self.selected_channel = (self.selected_channel + step) % span
                self._normalize_console_selection()
                self._sync_from_engine()
                return

    def _on_strip_click(self, event) -> None:
        _log.debug("STRIP CLICK x=%d y=%d", event.x, event.y)
        self.root.after_idle(self.root.focus_set)

        for x0, y0, x1, y1, idx in getattr(self, "record_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._cancel_pending_stage_click()
                self.selected_channel = idx
                self.console_row = "record"
                self.nav_scope = "console"
                self._sync_from_engine()
                self.root.focus_set()
                return
        for x0, y0, x1, y1, idx, zone in getattr(self, "scribble_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._cancel_pending_stage_click()
                self.selected_channel = idx
                self.console_row = "footer"
                self.nav_scope = "console"
                if self._pending_strip_click is not None:
                    try:
                        self.root.after_cancel(self._pending_strip_click)
                    except Exception:
                        pass
                    self._pending_strip_click = None
                if zone == "solo":
                    self._toggle_solo(idx)
                else:
                    self._toggle_mute(idx)
                self._sync_from_engine()
                self.root.focus_set()
                return
        for x0, y0, x1, y1, idx, key in getattr(self, "stage_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                _log.debug("STAGE HIT ch=%d key=%s (delayed toggle)", idx, key)
                self._cancel_pending_stage_click()
                self._pending_stage_action = self.root.after(
                    280,
                    lambda i=idx, k=key: self._stage_delayed_toggle(i, k),
                )
                return

    def _on_strip_double_click(self, event) -> None:
        for x0, y0, x1, y1, idx, key in getattr(self, "stage_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._cancel_pending_stage_click()
                _log.debug("STAGE DOUBLE ch=%d key=%s -> editor", idx, key)
                self._open_stage_editor(idx, key)
                return
        if self._pending_strip_click is not None:
            self.root.after_cancel(self._pending_strip_click)
            self._pending_strip_click = None

        # Footer uses split SOLO/MUTE hit targets (handled on single-click only).

    def _toggle_solo(self, idx: int) -> None:
        self._pending_strip_click = None
        ch = self.engine.channels[idx]
        with self.engine._lock:
            if ch.mute:
                ch.mute = False
            else:
                ch.solo = not ch.solo
        self._sync_from_engine()

    def _toggle_mute(self, idx: int) -> None:
        ch = self.engine.channels[idx]
        with self.engine._lock:
            ch.mute = not ch.mute
            if ch.mute:
                ch.solo = False
        self._sync_from_engine()

    def _toggle_send_mute(self, idx: int) -> None:
        if idx >= len(self.engine.channels):
            return
        ch = self.engine.channels[idx]
        with self.engine._lock:
            if ch.send_muted:
                restore = ch.send_prev_level if ch.send_prev_level > 0.0 else 0.5
                ch.send_level = float(np.clip(restore, 0.0, 1.0))
                ch.send_muted = False
            else:
                ch.send_prev_level = ch.send_level
                ch.send_level = 0.0
                ch.send_muted = True
        self._sync_from_engine()

    def _toggle_record_arm(self, idx: int) -> None:
        if idx >= len(self.engine.channels):
            return
        ch = self.engine.channels[idx]
        with self.engine._lock:
            ch.record_armed = not ch.record_armed
        self._sync_from_engine()

    def _on_timeline_press(self, event) -> None:
        canvas = getattr(self, "timeline_canvas", None)
        if canvas is None:
            return

        ww = max(320, int(canvas.winfo_width()))
        frac = float(np.clip(float(event.x) / ww, 0.0, 1.0))
        dur = max(1e-9, float(self.engine.timeline_duration_seconds()))
        self.engine.seek_seconds(frac * dur)

    def _draw_timeline(self) -> None:
        canvas = getattr(self, "timeline_canvas", None)
        if canvas is None:
            return

        canvas.delete("all")
        ww = max(400, int(canvas.winfo_width()))
        hh = max(46, int(canvas.winfo_height()))
        dur = max(1e-9, float(self.engine.timeline_duration_seconds()))
        ph = float(np.clip(float(self.engine.playhead_seconds), 0.0, dur))
        frac = ph / dur
        gutter = hh // 3
        canvas.create_rectangle(0, 0, ww, hh, outline="", fill="#0f141c")
        canvas.create_rectangle(4, gutter, ww - 4, hh - gutter, outline="#252f3c", fill="#090d11")
        progress_x = 4 + (ww - 8) * frac
        canvas.create_rectangle(4, gutter, progress_x, hh - gutter, outline="", fill="#3786b9")
        canvas.create_line(progress_x, 10, progress_x, hh - 10, fill="#fcd34d", width=3)
        mode = "scrub" if self.timeline_scrub_active else ("shuttle" if self.timeline_shuttle_active else "ply")
        canvas.create_text(
            8, hh - 12, anchor="w",
            text=f"{ph:5.1f}s / {dur:5.1f}s   step {self.timeline_jog_step:.2f}s   [{mode}]",
            fill="#8a9aaa", font=("Segoe UI", 8),
        )

    def _poll_stage_grid_vertical_key_repeat(self) -> None:
        """While UP/DOWN are held in the unified grid, emit extra steps on a fixed clock.

        Relying on OS KeyPress autorepeat makes ArrowDown feel slower or less consistent
        than ArrowUp on Windows; timer repeat matches both directions and follows the
        same wrap (header ↔ first/last row) as single presses.
        """
        if self.nav_scope != "editor" or getattr(self, "editor_nav_scope", "") != "stage_grid":
            self._stage_grid_vkey_repeat_prev.clear()
            return
        now = time.monotonic()
        t_init = float(self.STAGE_GRID_VKEY_REPEAT_INITIAL_S)
        t_step = float(self.STAGE_GRID_VKEY_REPEAT_STEP_S)
        for key in ("up", "down"):
            if key not in self._nav_keys_held:
                self._stage_grid_vkey_repeat_prev.pop(key, None)
                continue
            t0 = self._nav_key_press_mono.get(key)
            if t0 is None:
                continue
            if now < t0 + t_init:
                continue
            prev = self._stage_grid_vkey_repeat_prev.get(key)
            if prev is None:
                self._stage_grid_vkey_repeat_prev[key] = now
                self._handle_nav(key)
                continue
            if now - prev >= t_step:
                self._stage_grid_vkey_repeat_prev[key] = now
                self._handle_nav(key)

    def _schedule_refresh(self) -> None:
        try:
            self._poll_spacemouse()
            self._poll_editor_leave_hold_gate()
            self._poll_stage_grid_vertical_key_repeat()
            self._draw_strips()
            self._draw_timeline()
            self._draw_focus()
            self._draw_editor_controls()
            self._sync_play_transport_glyph()
        except Exception:
            import traceback
            traceback.print_exc()
            self.root.title(f"DRAW ERROR: {traceback.format_exc().splitlines()[-1]}")
        tick_ms = 96 if getattr(self.engine, "playing", False) else 52
        self.root.after(tick_ms, self._schedule_refresh)

    def on_close(self) -> None:
        self.engine.close()
        self.root.destroy()

    def _agent_proof_topmost_toggle(self, on: bool) -> None:
        try:
            if self.root.winfo_exists():
                self.root.attributes("-topmost", bool(on))
        except tk.TclError:
            pass

    def _agent_proof_foreground(self) -> None:
        """Make the Tk root visible above other windows before proof captures."""

        try:
            self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(180, lambda: self._agent_proof_topmost_toggle(False))
        except tk.TclError:
            pass
        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.root.winfo_id())
                ctypes.windll.user32.SetForegroundWindow(hwnd)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _agent_proof_paint_everything(self) -> None:
        """One redraw pass so strip focus / editor chrome actually update on-screen."""

        try:
            self._poll_spacemouse()
            self._poll_editor_leave_hold_gate()
            self._draw_strips()
            self._draw_timeline()
            self._draw_focus()
            self._draw_editor_controls()
            self._sync_play_transport_glyph()
        except Exception:
            import traceback

            traceback.print_exc()

    def _agent_ui_proof_shots(self) -> None:
        """When ``SYSTEM_Q_AGENT_PROOF=1``: save PNG proof of editor, then programmatic
        double-down macro → transport PLY — same binary the user ships; leaves UI running."""
        base = Path(__file__).resolve().parent
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            print(f"SYSTEM_Q_AGENT_PROOF: Pillow required ({exc})", flush=True)
            return

        def grab_root() -> "object":
            self.root.update_idletasks()
            self.root.update()
            rx = int(self.root.winfo_rootx())
            ry = int(self.root.winfo_rooty())
            rw = max(int(self.root.winfo_width()), 1024)
            rh = max(int(self.root.winfo_height()), 680)
            bbox = (rx, ry, rx + rw, ry + rh)
            try:
                return ImageGrab.grab(bbox=bbox, all_screens=True)
            except TypeError:
                return ImageGrab.grab(bbox=bbox)

        def mirror_desktop(fname: str, img) -> None:
            desk = Path.home() / "Desktop"
            if desk.is_dir():
                path = desk / fname
                try:
                    img.save(path)
                    print(f"SYSTEM_Q_AGENT_PROOF: mirror {path}", flush=True)
                except OSError as e:
                    print(f"SYSTEM_Q_AGENT_PROOF: desktop copy failed ({e})", flush=True)

        if self.nav_scope != "editor" or getattr(self, "editor_nav_scope", "") != "stage_grid":
            self.nav_scope = "editor"
            self.editor_nav_scope = "stage_grid"
            self.editor_channel = int(getattr(self, "editor_channel", self.selected_channel))
            self._sync_from_engine()

        img_ed = grab_root()
        p_ed = base / "SYSTEM_Q_proof_agent_editor.png"
        img_ed.save(p_ed)
        print(f"SYSTEM_Q_AGENT_PROOF: editor -> {p_ed}", flush=True)
        mirror_desktop("SYSTEM_Q_proof_agent_editor.png", img_ed)

        self._run_cardinal_double_tap_macro("down")
        self._sync_from_engine()

        def grab_transport() -> None:
            if self.nav_scope != "transport":
                print(
                    "SYSTEM_Q_AGENT_PROOF: expected nav_scope transport, got "
                    f"{self.nav_scope!r}",
                    flush=True,
                )
            img_tr = grab_root()
            p_tr = base / "SYSTEM_Q_proof_agent_transport_ply.png"
            img_tr.save(p_tr)
            print(f"SYSTEM_Q_AGENT_PROOF: transport -> {p_tr}", flush=True)
            mirror_desktop("SYSTEM_Q_proof_agent_transport_ply.png", img_tr)
            tag = SYSTEM_Q_BUILD_ID
            try:
                self.root.title(f"System Q Console · {tag} · agent proof OK")
            except tk.TclError:
                pass

        self.root.after(500, grab_transport)

    def _agent_ui_proof_four_double_taps(self) -> None:
        """Four PNGs on the Desktop PLUS an animated GIF so focus changes read as motion.

        Each double-macro waits ``SYSTEM_Q_AGENT_VISIBLE_MS`` (default 2800 ms) with the
        window forced to foreground so you **see** scopes move live; then grabs the PNG.
        At the end, ``SYSTEM_Q_proof_DOUBLE_sequence_MOVES.gif`` repeats the four frames."""

        base = Path(__file__).resolve().parent
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            print(f"SYSTEM_Q_AGENT_PROOF: Pillow required ({exc})", flush=True)
            return

        paint_ms = max(80, int(os.environ.get("SYSTEM_Q_AGENT_PAINT_MS", "140")))
        dwell_ms = max(1200, int(os.environ.get("SYSTEM_Q_AGENT_VISIBLE_MS", "2800")))
        lead_ms = max(1800, int(os.environ.get("SYSTEM_Q_AGENT_LEAD_MS", "3400")))
        gif_frame_ms = max(700, int(os.environ.get("SYSTEM_Q_AGENT_GIF_MS", "2000")))
        after_snap_ms = max(220, int(os.environ.get("SYSTEM_Q_AGENT_STEP_GAP_MS", "450")))
        gif_frames: list = []

        def grab_root():
            self._agent_proof_foreground()
            self.root.update_idletasks()
            self.root.update()
            rx = int(self.root.winfo_rootx())
            ry = int(self.root.winfo_rooty())
            rw = max(int(self.root.winfo_width()), 1024)
            rh = max(int(self.root.winfo_height()), 680)
            bbox = (rx, ry, rx + rw, ry + rh)
            try:
                return ImageGrab.grab(bbox=bbox, all_screens=True)
            except TypeError:
                return ImageGrab.grab(bbox=bbox)

        def mirror_and_repo(fname: str, img) -> None:
            rp = base / fname
            try:
                img.save(rp)
                print(f"SYSTEM_Q_AGENT_PROOF: repo {rp}", flush=True)
            except OSError as e:
                print(f"SYSTEM_Q_AGENT_PROOF: repo save failed ({e})", flush=True)
            desk = Path.home() / "Desktop"
            if desk.is_dir():
                dp = desk / fname
                try:
                    img.save(dp)
                    print(f"SYSTEM_Q_AGENT_PROOF: DESKTOP {dp}", flush=True)
                except OSError as e:
                    print(f"SYSTEM_Q_AGENT_PROOF: desktop failed ({e})", flush=True)

        def finish_gif() -> None:
            desk = Path.home() / "Desktop"
            if not desk.is_dir() or not gif_frames:
                return
            outp = desk / "SYSTEM_Q_proof_DOUBLE_sequence_MOVES.gif"
            rep_copy = base / outp.name
            try:
                seq = []
                base_im = gif_frames[0]
                bw, bh = base_im.width, base_im.height
                for raw in gif_frames:
                    rgb = raw.convert("RGB")
                    if rgb.size != (bw, bh):
                        rgb = rgb.resize((bw, bh))
                    seq.append(rgb)
                dq = [fp.quantize(colors=220, method=2) for fp in seq]
                dq[0].save(
                    outp,
                    format="GIF",
                    save_all=True,
                    append_images=dq[1:],
                    duration=gif_frame_ms,
                    loop=0,
                    optimize=False,
                )
                dq[0].save(
                    rep_copy,
                    format="GIF",
                    save_all=True,
                    append_images=dq[1:],
                    duration=gif_frame_ms,
                    loop=0,
                )
                print(f"SYSTEM_Q_AGENT_PROOF: MOTION GIF {outp}", flush=True)
                try:
                    os.startfile(outp)  # noqa: SIM115 — open GIF → watch it cycle
                except OSError:
                    pass
            except Exception:
                import traceback

                print("SYSTEM_Q_AGENT_PROOF: GIF failed\n" + traceback.format_exc(), flush=True)

        nav_ok = ""

        plan: list[tuple[str, str, object]] = [
            (
                "right",
                "SYSTEM_Q_proof_DOUBLE_RIGHT_editor.png",
                lambda: self.nav_scope == "editor"
                and getattr(self, "editor_nav_scope", "") == "stage_grid",
            ),
            (
                "left",
                "SYSTEM_Q_proof_DOUBLE_LEFT_faders.png",
                lambda: self.nav_scope == "faders",
            ),
            (
                "up",
                "SYSTEM_Q_proof_DOUBLE_UP_channel_strips.png",
                lambda: self.nav_scope == "console" and self.console_row == "stages",
            ),
            (
                "down",
                "SYSTEM_Q_proof_DOUBLE_DOWN_transport_PLY.png",
                lambda: self.nav_scope == "transport",
            ),
        ]

        def run_step(i: int) -> None:
            nonlocal nav_ok
            self._agent_proof_foreground()

            if i >= len(plan):
                try:
                    self.root.title(
                        f"System Q Console · {SYSTEM_Q_BUILD_ID} · 4-double proof OK ({nav_ok})"
                    )
                except tk.TclError:
                    pass
                finish_gif()
                print(
                    "SYSTEM_Q_AGENT_PROOF: four_double_taps complete "
                    f"(dwell={dwell_ms}ms per step). GIF shows motion.",
                    flush=True,
                )
                return

            cardinal, fname, predicate = plan[i]
            self._run_cardinal_double_tap_macro(cardinal)
            self._sync_from_engine()
            self._agent_proof_paint_everything()

            def after_dwell_snap() -> None:
                nonlocal nav_ok
                self._agent_proof_foreground()
                self._agent_proof_paint_everything()
                self._sync_from_engine()

                ok = bool(predicate())
                nav_ok += ("+" if ok else "-") + cardinal[0].upper()
                step_label = fname.replace("SYSTEM_Q_proof_", "").replace(".png", "")
                try:
                    self.root.title(f"System Q · {SYSTEM_Q_BUILD_ID} · proof {step_label}")
                except tk.TclError:
                    pass

                if not ok:
                    print(
                        "SYSTEM_Q_AGENT_PROOF: scope FAILED after "
                        f"macro({cardinal!r}) -> nav_scope={self.nav_scope!r} "
                        f"console_row={self.console_row!r} editor_nav="
                        f"{getattr(self, 'editor_nav_scope', '?')!r}",
                        flush=True,
                    )
                pil_img = grab_root()
                gif_frames.append(pil_img.copy())
                mirror_and_repo(fname, pil_img.copy())
                self.root.after(after_snap_ms, lambda: run_step(i + 1))

            self.root.after(paint_ms, lambda: self.root.after(dwell_ms, after_dwell_snap))

        self.nav_scope = "console"
        self.console_row = "stages"
        self.selected_channel = 0
        self.editor_channel = 0
        self._transport_entered_from = None
        self._normalize_console_selection()
        self._redraw_transport_focus()
        self._sync_from_engine()
        self._agent_proof_paint_everything()

        print(
            f"SYSTEM_Q_AGENT_PROOF: WATCH SCREEN - foreground window, dwell {dwell_ms}ms between jumps.",
            flush=True,
        )

        self._agent_proof_foreground()

        try:
            self.root.title(f"System Q · {SYSTEM_Q_BUILD_ID} · proof START strips (pause {lead_ms}ms)")
        except tk.TclError:
            pass

        print(
            f"SYSTEM_Q_AGENT_PROOF: lead {lead_ms}ms on STRIPS, then DOUBLE right->editor ... down->PLY.",
            flush=True,
        )

        self.root.after(lead_ms, lambda: run_step(0))

def _pid_command_line_contains_win32(pid: int, needle: str) -> bool:
    cre = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0  # type: ignore[attr-defined]
    try:
        r = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=cre,
        )
        blob = (r.stdout or "") + (r.stderr or "")
        return needle in blob
    except Exception:
        return False


def _ensure_single_system_q_launch_win32() -> None:
    """Double-click/BAT launches always load disk code: previous ``system_q_console.py`` exits.

    Set ``SYSTEM_Q_MULTI_INSTANCE=1`` or pass ``--multi`` to allow more than one window.
    PID file under ``%%LOCALAPPDATA%%\\SystemQ\\``.
    """

    if sys.platform != "win32":
        return
    if os.environ.get("SYSTEM_Q_MULTI_INSTANCE", "").strip() == "1":
        return
    if "--multi" in sys.argv:
        return

    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    lock = local / "SystemQ" / "console_instance.pid"
    needle = "system_q_console.py"
    me = os.getpid()
    cre = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0  # type: ignore[attr-defined]

    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    if lock.exists():
        old_pid = None
        try:
            parts = lock.read_text(encoding="utf-8").strip().split()
            if parts:
                old_pid = int(parts[0])
        except Exception:
            old_pid = None
        if old_pid not in (None, me):
            if _pid_command_line_contains_win32(old_pid, needle):
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(old_pid), "/T", "/F"],
                        capture_output=True,
                        timeout=30,
                        creationflags=cre,
                    )
                    print(f"System Q: replaced prior window (PID {old_pid}) with this launch.", flush=True)
                except Exception:
                    pass
        try:
            lock.unlink()
        except OSError:
            pass

    try:
        lock.write_text(str(me) + "\n", encoding="utf-8")
    except OSError:
        return

    def _release_lock_if_ours() -> None:
        try:
            txt = lock.read_text(encoding="utf-8").strip().split()
            if txt and int(txt[0]) == os.getpid():
                lock.unlink()
        except Exception:
            pass

    atexit.register(_release_lock_if_ours)


def main() -> None:
    _ensure_single_system_q_launch_win32()

    def _proof_from_argv() -> str:
        for a in sys.argv[1:]:
            if a.startswith("--agent-proof="):
                return a.split("=", 1)[1].strip().lower()
            if a in ("--agent-proof-all", "--agent-proof"):
                return "all"
        return ""

    _proof_env = os.environ.get("SYSTEM_Q_AGENT_PROOF", "").strip().lower()
    if not _proof_env:
        _proof_env = _proof_from_argv()
    if _proof_env:
        os.environ["SYSTEM_Q_AGENT_PROOF"] = str(_proof_env)
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
            except Exception:
                pass
    root = tk.Tk()
    app = ConsoleApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    root.after(250, app._place_window_primary_visible)
    if _proof_env in ("1", "yes", "true", "dual"):
        root.after(5200, app._agent_ui_proof_shots)
    elif _proof_env in ("all", "4", "four", "quadruple"):
        root.after(5200, app._agent_ui_proof_four_double_taps)
    root.mainloop()


if __name__ == "__main__":
    main()

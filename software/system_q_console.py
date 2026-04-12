import math
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
import threading
import tkinter as tk
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


def eq_gain_color(gain_db: float) -> str:
    gain_db = max(-18.0, min(18.0, gain_db))
    if gain_db < 0.0:
        return lerp_color((255, 60, 46), (255, 208, 138), (gain_db + 18.0) / 18.0)
    return lerp_color((255, 208, 138), (105, 223, 242), gain_db / 18.0)


SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
POL_BANDS = 36
ROOT_DIR = Path(__file__).resolve().parent
STEMS_DIR = ROOT_DIR / "band_stems"
CHANNEL_LAYOUT = [
    ("Kick", "01_kick.wav"),
    ("Snare", "02_snare.wav"),
    ("OH L", "03_oh_l.wav"),
    ("OH R", "04_oh_r.wav"),
    ("Bass", "05_bass.wav"),
    ("Gtr L", "06_gtr_l.wav"),
    ("Gtr R", "07_gtr_r.wav"),
    ("Keys L", "08_keys_l.wav"),
    ("Keys R", "09_keys_r.wav"),
    ("Vocal", "10_vocal.wav"),
    ("BGV", "11_bgv.wav"),
    ("Perc", "12_perc.wav"),
]
POL_LOW_HZ = 20.0
POL_HIGH_HZ = 20000.0
LOG_LOW = math.log10(POL_LOW_HZ)
LOG_HIGH = math.log10(POL_HIGH_HZ)


@dataclass
class ChannelState:
    name: str
    path: Path
    audio: np.ndarray = field(default_factory=lambda: np.zeros((1, 2), dtype=np.float32))
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
    pre_enabled: bool = True
    phantom: bool = False
    phase: bool = False
    tube: bool = False
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
    tone_enabled: bool = False
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
        self.channels = [self._load_channel(name, STEMS_DIR / filename) for name, filename in CHANNEL_LAYOUT]
        self.master_channel = ChannelState(name="Master", path=ROOT_DIR / "master_bus")
        self.master_channel.pre_enabled = False
        self.stream = None
        self.playing = False
        self.loop = True
        self.master_gain = 0.82
        self.master_level = 0.0
        self._lock = threading.Lock()

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
        return ChannelState(name=name, path=path, audio=data.astype(np.float32))

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

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            if not self.playing:
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
            mix = np.zeros((frames, 2), dtype=np.float32)
            for ch in self.channels:
                block = self._next_block(ch, frames)
                processed = self._process_channel(ch, block)
                self._analyze_channel(ch, processed)
                if ch.mute or (any_solo and not ch.solo):
                    processed *= 0.0
                mix += self._apply_pan(processed, ch.pan)
                ch.level = float(np.sqrt(np.mean(np.square(processed))) * 3.4)

            mix *= self.master_gain
            master_processed = self._process_channel(self.master_channel, mix)
            self._analyze_channel(self.master_channel, master_processed)
            self.master_channel.level = float(np.sqrt(np.mean(np.square(master_processed))) * 2.8)
            peak = float(np.max(np.abs(master_processed)))
            if peak > 0.98:
                master_processed *= 0.98 / peak
            self.master_level = float(np.sqrt(np.mean(np.square(master_processed))) * 2.8)
            outdata[:] = master_processed.astype(np.float32)

    def _next_block(self, ch: ChannelState, frames: int) -> np.ndarray:
        end = ch.position + frames
        if end <= len(ch.audio):
            block = ch.audio[ch.position:end]
            ch.position = end
            return block.copy()

        head = ch.audio[ch.position:] if ch.position < len(ch.audio) else np.zeros((0, 2), dtype=np.float32)
        if not self.loop:
            ch.position = len(ch.audio)
            return np.vstack([head, np.zeros((frames - len(head), 2), dtype=np.float32)])
        tail_frames = frames - len(head)
        wraps = []
        while tail_frames > 0:
            take = min(len(ch.audio), tail_frames)
            wraps.append(ch.audio[:take])
            tail_frames -= take
        ch.position = sum(len(x) for x in wraps) % len(ch.audio)
        return np.vstack([head, *wraps]).astype(np.float32)

    def _process_channel(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        x = block.astype(np.float32) * ch.gain
        if ch.pre_enabled:
            if ch.phase:
                x[:, 1] *= -1.0
            if ch.tube:
                x = np.tanh(x * 1.18).astype(np.float32)
            if ch.lpf_enabled:
                x = self._apply_simple_filter(x, ch.lpf_hz, "highpass")
            if ch.hpf_enabled:
                x = self._apply_simple_filter(x, ch.hpf_hz, "lowpass")
        if ch.harmonics_enabled and np.any(ch.harmonics > 0.001):
            x = self._apply_harmonics(x, ch.harmonics, ch.harmonic_makeup)
        if ch.comp_enabled:
            x = self._apply_compressor(ch, x)
        eq_active = False
        for band in ch.eq_bands[: max(1, ch.eq_band_count)]:
            if band["enabled"] and abs(float(band["gain_db"])) > 0.05:
                x = self._apply_eq(x, float(band["freq"]), float(band["gain_db"]), float(band["width"]))
                eq_active = True
        ch.eq_enabled = eq_active
        if ch.tone_enabled:
            x = self._apply_tone(x, ch)
        return np.clip(x, -1.0, 1.0).astype(np.float32)

    def _analyze_channel(self, ch: ChannelState, block: np.ndarray) -> None:
        mono = np.mean(block, axis=1).astype(np.float32)
        if len(mono) < 32:
            ch.band_levels *= 0.92
            return
        windowed = mono * np.hanning(len(mono)).astype(np.float32)
        spec = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(mono), d=1.0 / SAMPLE_RATE)
        edges = np.logspace(LOG_LOW, LOG_HIGH, POL_BANDS + 1)
        band_values = np.zeros(POL_BANDS, dtype=np.float32)
        for i in range(POL_BANDS):
            mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
            if np.any(mask):
                band_values[i] = float(np.sqrt(np.mean(np.square(spec[mask]))))
        # Absolute-ish mapping instead of frame-relative normalization.
        # This keeps each ring tied to its own band intensity rather than the loudest band in the frame.
        ch.band_noise_floor = ch.band_noise_floor * 0.995 + np.minimum(ch.band_noise_floor, band_values + 1e-8) * 0.005
        relative = np.maximum(0.0, band_values - ch.band_noise_floor * 1.25)
        mapped = np.clip(relative / 8.0, 0.0, 1.0)
        mapped = np.power(mapped, 0.55).astype(np.float32)
        ch.band_levels = ch.band_levels * 0.58 + mapped * 0.42

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

    def _apply_harmonics(self, block: np.ndarray, weights: np.ndarray, makeup: float) -> np.ndarray:
        out = np.zeros_like(block, dtype=np.float32)
        for idx in range(block.shape[1]):
            x = block[:, idx].astype(np.float32)
            base_rms = float(np.sqrt(np.mean(np.square(x))) + 1e-7)
            x = np.clip(x, -0.999, 0.999)
            theta = np.arccos(x)
            enhanced = x.copy()
            for order_idx, weight in enumerate(weights):
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

    def _apply_compressor(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        mono = np.mean(block, axis=1).astype(np.float32)
        env = float(ch.comp_env)
        attack_coeff = math.exp(-1.0 / max(1.0, (ch.comp_attack_ms / 1000.0) * SAMPLE_RATE))
        release_coeff = math.exp(-1.0 / max(1.0, (ch.comp_release_ms / 1000.0) * SAMPLE_RATE))
        ratio = max(1.0, float(ch.comp_ratio))
        threshold = float(ch.comp_threshold_db)
        gains = np.empty(len(mono), dtype=np.float32)
        last_gr = 0.0
        for i, sample in enumerate(mono):
            detector = abs(float(sample))
            if detector > env:
                env = attack_coeff * env + (1.0 - attack_coeff) * detector
            else:
                env = release_coeff * env + (1.0 - release_coeff) * detector
            env_db = 20.0 * math.log10(max(env, 1e-7))
            over_db = max(0.0, env_db - threshold)
            gr_db = over_db - (over_db / ratio if over_db > 0 else 0.0)
            gains[i] = 10 ** (-gr_db / 20.0) * ch.comp_makeup
            last_gr = gr_db
        ch.comp_env = env
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
        if abs(ch.trn_attack) > 0.01 or abs(ch.trn_sustain) > 0.01:
            x = self._apply_transient(x, ch.trn_attack, ch.trn_sustain)
        if ch.clr_drive > 0.01:
            drive = 1.0 + ch.clr_drive * 5.0
            x = np.tanh(x * drive).astype(np.float32)
        if ch.xct_amount > 0.01:
            high = self._apply_simple_filter(x, 4000.0, "highpass")
            excite = np.tanh(high * (1.0 + ch.xct_amount * 6.0)).astype(np.float32) - np.tanh(high * 0.8).astype(np.float32)
            x = np.clip(x + excite * 0.9, -1.0, 1.0).astype(np.float32)
        return x

    def _apply_transient(self, block: np.ndarray, attack_amt: float, sustain_amt: float) -> np.ndarray:
        mono = np.mean(block, axis=1).astype(np.float32)
        detector = np.abs(mono)
        fast_env = np.zeros_like(detector)
        slow_env = np.zeros_like(detector)
        fast = 0.0
        slow = 0.0
        for i, sample in enumerate(detector):
            fast += (sample - fast) * 0.52
            slow += (sample - slow) * 0.012
            fast_env[i] = fast
            slow_env[i] = slow
        transient = np.maximum(0.0, fast_env - slow_env)
        sustain = slow_env.copy()
        if float(np.max(transient)) > 1e-6:
            transient /= float(np.max(transient))
        if float(np.max(sustain)) > 1e-6:
            sustain /= float(np.max(sustain))
        out = block.copy()
        for idx in range(block.shape[1]):
            x = block[:, idx].astype(np.float32)
            prev = np.concatenate(([0.0], x[:-1])).astype(np.float32)
            edge = (x - prev * 0.72) * transient * (attack_amt * 12.0)
            acc = 0.0
            body = np.zeros(len(x), dtype=np.float32)
            for i, sample in enumerate(x):
                acc = acc * 0.994 + sample * 0.055
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

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("System Q Console")
        self.root.geometry("1560x880")
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
        self.pre_editor_positions = {"left": 0, "stage": 0, "body": 0, "right": 0}
        self.module_editor_column = 0
        self.module_editor_positions = {"left": 0, "stage": 0, "body": 0, "right": 0}
        self.comp_editor_mode = "COMP"
        self.comp_nav_row = "bottom"
        self.tone_editor_mode = "TRN"
        self.tone_nav_row = "bottom"
        self.eq_nav_row = "bottom"
        self.eq_band_count = 1
        self.eq_selected_band = 0
        self._pending_strip_click = None
        self._console_hold_target = None
        self._console_hold_repeat_at = 0.0
        self._editor_last_press_at = 0.0
        self.stage_color = {
            "pre": "#77f0c6",
            "harm": "#ffb757",
            "comp": "#ff6a53",
            "eq": "#75baff",
            "tone": "#c780ff",
        }
        self._build_ui()
        self._bind_nav_keys()
        self._sync_from_engine()
        self._schedule_refresh()

    def _bind_nav_keys(self):
        self.root.bind("<Left>", lambda e: self._handle_nav("left"))
        self.root.bind("<Right>", lambda e: self._handle_nav("right"))
        self.root.bind("<Up>", lambda e: self._handle_nav("up"))
        self.root.bind("<Down>", lambda e: self._handle_nav("down"))
        self.root.bind("<space>", lambda e: self._handle_nav("press"))
        self.root.bind("<BackSpace>", lambda e: self._handle_nav("back"))
        self.root.bind("<Key>", lambda e: _log.debug("RAW KEY sym=%s widget=%s focus=%s", e.keysym, e.widget, self.root.focus_get()))

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#222831")
        top.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(top, text="System Q Inter", bg="#222831", fg="#f3f4f7", font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(top, text="12-channel rehearsal / recording console", bg="#222831", fg="#9fb0c2", font=("Segoe UI", 12)).pack(side="left", padx=14, pady=(10, 0))
        tk.Button(top, text="Play / Pause", command=self.engine.toggle_play, width=12).pack(side="right", padx=6)
        tk.Button(top, text="Stop", command=self.engine.stop, width=10).pack(side="right", padx=6)

        body = tk.Frame(self.root, bg="#222831")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        left = tk.Frame(body, bg="#1f252d", bd=0, highlightthickness=1, highlightbackground="#344250")
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg="#161b22", bd=0, highlightthickness=1, highlightbackground="#344250", width=420)
        right.pack(side="right", fill="y", padx=(14, 0))
        right.pack_propagate(False)

        self.strip_canvas = tk.Canvas(left, bg="#1c222a", highlightthickness=0)
        self.strip_canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.strip_canvas.bind("<Button-1>", self._on_strip_click)
        self.strip_canvas.bind("<Double-Button-1>", self._on_strip_double_click)

        self.editor_frame = right
        self._build_editor(right)

    def _build_editor(self, parent: tk.Frame) -> None:
        self.editor_title = tk.Label(parent, text="", bg="#161b22", fg="#f2f3f6", font=("Segoe UI", 22, "bold"))
        self.editor_title.pack(anchor="w", padx=16, pady=(14, 4))
        self.editor_subtitle = tk.Label(parent, text="", bg="#161b22", fg="#92a3b5", font=("Segoe UI", 10))
        self.editor_subtitle.pack(anchor="w", padx=16, pady=(0, 10))

        self.focus_canvas = tk.Canvas(parent, width=380, height=300, bg="#10151b", highlightthickness=1, highlightbackground="#344250")
        self.focus_canvas.pack(fill="x", padx=16, pady=(0, 12))
        self.fader_canvas = tk.Canvas(parent, width=380, height=86, bg="#10151b", highlightthickness=1, highlightbackground="#344250")
        self.fader_canvas.pack(fill="x", padx=16, pady=(0, 12))
        self.fader_canvas.bind("<Button-1>", self._on_fader_canvas_click)
        self.editor_canvas = tk.Canvas(parent, width=380, height=340, bg="#10151b", highlightthickness=1, highlightbackground="#344250")
        self.editor_canvas.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.editor_canvas.bind("<Button-1>", self._on_editor_canvas_click)

        quick = tk.Frame(parent, bg="#161b22")
        quick.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(quick, text="Master", bg="#161b22", fg="#9fb0c2", font=("Segoe UI", 10)).pack(anchor="w")
        self.master_meter = tk.Canvas(quick, width=360, height=18, bg="#232a33", highlightthickness=0)
        self.master_meter.pack(anchor="w", pady=(4, 0))
        self._init_editor_state_vars()

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
        self._scale(sec, "Threshold", -42.0, 0.0, self.comp_vars["threshold"], lambda _=None: self._commit_comp(), resolution=0.5)
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
            return ["harm", "comp", "eq", "tone"]
        return ["pre", "harm", "comp", "eq", "tone"]

    def _normalize_stage_selection(self, channel_index: int) -> None:
        if self.nav_scope == "console" and self.console_row in ("footer", "record"):
            return
        stage_keys = self._console_stage_keys(channel_index)
        if self.selected_stage_key not in stage_keys:
            self.selected_stage_key = stage_keys[0]
        if self.selected_stage_key == "eq":
            ch = self.engine.master_channel if channel_index >= len(self.engine.channels) else self.engine.channels[channel_index]
            self.eq_selected_band = min(self.eq_selected_band, max(0, ch.eq_band_count - 1))

    def _eq_band(self, ch: ChannelState, idx: int | None = None) -> dict:
        band_idx = self.eq_selected_band if idx is None else idx
        band_idx = max(0, min(7, band_idx))
        while len(ch.eq_bands) < 8:
            ch.eq_bands.append({"enabled": False, "freq": 2200.0, "gain_db": 0.0, "width": 1.4, "type": "BELL", "band_enabled": False})
        return ch.eq_bands[band_idx]

    def _normalize_console_selection(self) -> None:
        self._normalize_stage_selection(self.selected_channel)

    def _sync_from_engine(self) -> None:
        self._normalize_stage_selection(self._active_channel_index())
        self._normalize_module_editor_positions()
        ch = self._current_channel()
        self.editor_title.config(text=f"{ch.name} / {self._stage_label(self.selected_stage_key)}")
        active_channel = self._active_channel_index()
        if active_channel >= len(self.engine.channels):
            self.editor_subtitle.config(text="MASTER BUS")
        else:
            self.editor_subtitle.config(text=f"{active_channel + 1:02d}  {ch.path.name}")
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
        self.comp_vars["threshold"].set(ch.comp_threshold_db)
        self.comp_vars["ratio"].set(ch.comp_ratio)
        self.comp_vars["attack"].set(ch.comp_attack_ms)
        self.comp_vars["release"].set(ch.comp_release_ms)
        self.comp_vars["makeup"].set(ch.comp_makeup)
        eq_band = self._eq_band(ch)
        self.eq_vars["enabled"].set(bool(eq_band["enabled"]))
        self.eq_vars["freq"].set(float(eq_band["freq"]))
        self.eq_vars["gain"].set(float(eq_band["gain_db"]))
        self.eq_vars["width"].set(float(eq_band["width"]))
        self.tone_vars["enabled"].set(ch.tone_enabled)
        self.tone_vars["trn_attack"].set(ch.trn_attack)
        self.tone_vars["trn_sustain"].set(ch.trn_sustain)
        self.tone_vars["clr_drive"].set(ch.clr_drive)
        self.tone_vars["xct_amount"].set(ch.xct_amount)
        self._draw_strips()
        self._draw_focus()
        self._draw_editor_controls()

    def _stage_label(self, key: str) -> str:
        return {
            "pre": "Mic Pre",
            "harm": "Harmonics",
            "comp": "Compressor",
            "eq": "EQ",
            "tone": "TRN / CLR / XCT",
        }[key]

    def _commit_pre(self) -> None:
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
        self._draw_strips()

    def _commit_harm(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            ch.harmonics_enabled = self.harm_vars["enabled"].get()
            ch.harmonic_makeup = self.harm_vars["makeup"].get()
            ch.harmonics = np.array([v.get() for v in self.harm_weight_vars], dtype=np.float32)
        self._draw_strips()

    def _commit_comp(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            ch.comp_enabled = self.comp_vars["enabled"].get()
            ch.comp_threshold_db = self.comp_vars["threshold"].get()
            ch.comp_ratio = self.comp_vars["ratio"].get()
            ch.comp_attack_ms = self.comp_vars["attack"].get()
            ch.comp_release_ms = self.comp_vars["release"].get()
            ch.comp_makeup = self.comp_vars["makeup"].get()
        self._draw_strips()

    def _commit_eq(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            band = self._eq_band(ch)
            band["enabled"] = self.eq_vars["enabled"].get()
            band["freq"] = self.eq_vars["freq"].get()
            band["gain_db"] = self.eq_vars["gain"].get()
            band["width"] = self.eq_vars["width"].get()
            ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
        self._draw_strips()

    def _commit_tone(self) -> None:
        ch = self._current_channel()
        with self.engine._lock:
            ch.tone_enabled = self.tone_vars["enabled"].get()
            ch.trn_attack = self.tone_vars["trn_attack"].get()
            ch.trn_sustain = self.tone_vars["trn_sustain"].get()
            ch.clr_drive = self.tone_vars["clr_drive"].get()
            ch.xct_amount = self.tone_vars["xct_amount"].get()
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
        c.create_rectangle(0, 0, width, height, fill="#10151b", outline="")
        ch = self._current_channel()
        c.create_text(18, 18, text=self._stage_label(self.selected_stage_key), fill="#f4d58b", font=("Segoe UI", 18, "bold"), anchor="w")
        c.create_text(18, 42, text=ch.name, fill="#90a1b3", font=("Segoe UI", 11), anchor="w")
        if self.selected_stage_key == "pre":
            self._draw_focus_mic_pre(c, ch, width, height)
        elif self.selected_stage_key == "harm":
            self._draw_focus_harmonics(c, ch, width, height)
        elif self.selected_stage_key == "comp":
            self._draw_focus_compressor(c, ch, width, height)
        elif self.selected_stage_key == "eq":
            self._draw_focus_eq(c, ch, width, height)
        elif self.selected_stage_key == "tone":
            self._draw_focus_tone(c, ch, width, height)

    def _draw_editor_controls(self) -> None:
        self.focus_canvas.configure(height=250)
        self.fader_canvas.configure(height=1)
        self.fader_canvas.delete("all")
        self.editor_canvas.configure(height=460)
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
        if stage_key == "pre" and not preview_only:
            self._draw_pre_editor_layout(c, w, h, ch, stage_keys)
            return
        if not preview_only:
            self._draw_module_editor_layout(c, w, h, ch, stage_keys)
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
        self._draw_editor_channel_nav(c, w, channel_nav_y, preview_only)
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
            band = self._eq_band(ch)
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

    def _draw_pre_editor_layout(self, c: tk.Canvas, w: int, h: int, ch: ChannelState, stage_keys: list[str]) -> None:
        self.editor_hitboxes = []
        self._draw_editor_channel_nav(c, w, 20, preview_only=False)
        margin = 16
        gap = 10
        available_w = w - margin * 2 - gap * 3
        side_w = min(70, max(52, int((available_w - 116) / 3)))
        body_w = available_w - side_w * 3
        if body_w < 116:
            side_w = max(48, int((available_w - 116) / 3))
            body_w = available_w - side_w * 3
        left_w = side_w
        stage_w = side_w
        right_w = side_w
        top_y = 46
        bottom_y = h - 14
        section_h = bottom_y - top_y
        x0 = margin
        x1 = x0 + left_w
        x2 = x1 + gap
        x3 = x2 + stage_w
        x4 = x3 + gap
        x5 = x4 + body_w
        x6 = x5 + gap
        x7 = x6 + right_w
        columns = [
            (x0, x1, "left"),
            (x2, x3, "stage"),
            (x4, x5, "body"),
            (x6, x7, "right"),
        ]
        active_keys = ["left", "stage", "body", "right"]
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

        # Left column: channel selector + channel fader
        left_center = (x0 + x1) / 2
        knob_y = top_y + 42
        self._draw_pre_knob(
            c,
            left_center,
            knob_y,
            "CH",
            self._current_channel_short_label(),
            active_col == "left" and self.pre_editor_positions["left"] == 0,
        )
        self.editor_hitboxes.append((x0 + 8, knob_y - 28, x1 - 8, knob_y + 42, 0, "CH", "pre-left"))
        self._draw_pre_vertical_fader(
            c,
            left_center,
            knob_y + 76,
            bottom_y - 20,
            ch.gain,
            0.3,
            2.2,
            "CH VOL",
            f"{ch.gain:.2f}x",
            active_col == "left" and self.pre_editor_positions["left"] == 1,
        )
        self.editor_hitboxes.append((x0 + 10, knob_y + 54, x1 - 10, bottom_y - 10, 1, "CH VOL", "pre-left"))

        # Stage column
        stage_labels = [("PRE", "pre"), ("HAR", "harm"), ("CMP", "comp"), ("EQ", "eq"), ("FX", "tone")]
        stage_step = (section_h - 64) / max(1, len(stage_labels) - 1)
        for idx, (label, key) in enumerate(stage_labels):
            cy = top_y + 30 + idx * stage_step
            selected = active_col == "stage" and self.pre_editor_positions["stage"] == idx
            is_current = self.selected_stage_key == key
            self._draw_pre_dot(c, (x2 + x3) / 2, cy, label, "", is_current, selected)
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

        # Right column: send selector + send fader
        right_center = (x6 + x7) / 2
        self._draw_pre_knob(
            c,
            right_center,
            knob_y,
            "SND",
            str(int(ch.send_slot)),
            active_col == "right" and self.pre_editor_positions["right"] == 0,
        )
        self.editor_hitboxes.append((x6 + 8, knob_y - 28, x7 - 8, knob_y + 42, 0, "SND", "pre-right"))
        self._draw_pre_vertical_fader(
            c,
            right_center,
            knob_y + 76,
            bottom_y - 20,
            ch.send_level,
            0.0,
            1.0,
            "SEND",
            f"{ch.send_level:.2f}",
            active_col == "right" and self.pre_editor_positions["right"] == 1,
        )
        self.editor_hitboxes.append((x6 + 10, knob_y + 54, x7 - 10, bottom_y - 10, 1, "SEND", "pre-right"))

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
                ("LIMIT", "", ch.limit_enabled),
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
        self.module_editor_positions["left"] = max(0, min(1, self.module_editor_positions["left"]))
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
        self.module_editor_positions["right"] = max(0, min(1, self.module_editor_positions["right"]))

    def _draw_module_editor_layout(self, c: tk.Canvas, w: int, h: int, ch: ChannelState, stage_keys: list[str]) -> None:
        self.editor_hitboxes = []
        self._normalize_module_editor_positions()
        self._draw_editor_channel_nav(c, w, 20, preview_only=False)
        margin = 16
        gap = 10
        available_w = w - margin * 2 - gap * 3
        side_w = min(70, max(52, int((available_w - 116) / 3)))
        body_w = available_w - side_w * 3
        if body_w < 116:
            side_w = max(48, int((available_w - 116) / 3))
            body_w = available_w - side_w * 3
        left_w = side_w
        stage_w = side_w
        right_w = side_w
        top_y = 46
        bottom_y = h - 14
        section_h = bottom_y - top_y
        x0 = margin
        x1 = x0 + left_w
        x2 = x1 + gap
        x3 = x2 + stage_w
        x4 = x3 + gap
        x5 = x4 + body_w
        x6 = x5 + gap
        x7 = x6 + right_w
        columns = [
            (x0, x1, "left"),
            (x2, x3, "stage"),
            (x4, x5, "body"),
            (x6, x7, "right"),
        ]
        active_keys = ["left", "stage", "body", "right"]
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
            active_col == "left" and self.module_editor_positions["left"] == 0,
        )
        self.editor_hitboxes.append((x0 + 8, knob_y - 28, x1 - 8, knob_y + 42, 0, "CH", "module-left"))
        self._draw_pre_vertical_fader(
            c,
            left_center,
            knob_y + 76,
            bottom_y - 20,
            ch.gain,
            0.3,
            2.2,
            "CH VOL",
            f"{ch.gain:.2f}x",
            active_col == "left" and self.module_editor_positions["left"] == 1,
        )
        self.editor_hitboxes.append((x0 + 10, knob_y + 54, x1 - 10, bottom_y - 10, 1, "CH VOL", "module-left"))

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
            left_indices = [0, 1, 2, 4, 5]
            right_indices = [3, 7, 8, 9, 6]
            x_positions = [
                x4 + body_w * 0.31,
                x4 + body_w * 0.69,
            ]
            row_step = 68.0
            rows = 5
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

        right_center = (x6 + x7) / 2
        self._draw_pre_knob(
            c,
            right_center,
            knob_y,
            "SND",
            str(int(ch.send_slot)),
            active_col == "right" and self.module_editor_positions["right"] == 0,
        )
        self.editor_hitboxes.append((x6 + 8, knob_y - 28, x7 - 8, knob_y + 42, 0, "SND", "module-right"))
        self._draw_pre_vertical_fader(
            c,
            right_center,
            knob_y + 76,
            bottom_y - 20,
            ch.send_level,
            0.0,
            1.0,
            "SEND",
            f"{ch.send_level:.2f}",
            active_col == "right" and self.module_editor_positions["right"] == 1,
        )
        self.editor_hitboxes.append((x6 + 10, knob_y + 54, x7 - 10, bottom_y - 10, 1, "SEND", "module-right"))

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

    def _draw_editor_channel_nav(self, c: tk.Canvas, w: int, y: float, preview_only: bool) -> None:
        names = [ch.name for ch in self.engine.channels] + ["Master"]
        idx = self._active_channel_index() % len(names)
        left = names[(idx - 1) % len(names)]
        current = names[idx]
        right = names[(idx + 1) % len(names)]
        c.create_text(w * 0.28, y, text=left.upper(), fill="#607182", font=("Segoe UI", 8 if not preview_only else 7, "bold"))
        c.create_text(w * 0.50, y, text=current.upper(), fill="#d7e2ec", font=("Segoe UI", 9 if not preview_only else 8, "bold"))
        c.create_text(w * 0.72, y, text=right.upper(), fill="#607182", font=("Segoe UI", 8 if not preview_only else 7, "bold"))
        c.create_line(w * 0.36, y, w * 0.42, y, fill="#31404e", width=1)
        c.create_line(w * 0.58, y, w * 0.64, y, fill="#31404e", width=1)

    def _on_editor_canvas_click(self, event) -> None:
        for x0, y0, x1, y1, idx, label, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.nav_scope = "editor"
                _log.debug("EDITOR CLICK tag=%s idx=%d label=%s", tag, idx, label)
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
                elif tag == "pre-right":
                    self.pre_editor_column = 3
                    self.pre_editor_positions["right"] = idx
                    self.editor_nav_scope = "pre-right"
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
                elif tag == "module-right":
                    self.module_editor_column = 3
                    self.module_editor_positions["right"] = idx
                    self.editor_nav_scope = "module-right"
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
                    ch.harmonics_enabled = bool(np.any(ch.harmonics > 0.001))
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

    def _adjust_selected_editor_item(self, axis_value: float) -> None:
        if abs(axis_value) < 0.01:
            return
        if self.nav_scope != "editor":
            return
        if self.selected_stage_key == "pre":
            ch = self._current_channel()
            with self.engine._lock:
                if self.pre_editor_column == 0:
                    if self.pre_editor_positions["left"] == 0:
                        if axis_value > 0:
                            self.editor_channel = (self.editor_channel + 1) % (len(self.engine.channels) + 1)
                        else:
                            self.editor_channel = (self.editor_channel - 1) % (len(self.engine.channels) + 1)
                        self._normalize_stage_selection(self.editor_channel)
                    else:
                        ch.gain = float(np.clip(ch.gain + axis_value * 0.04, 0.3, 2.2))
                elif self.pre_editor_column == 2:
                    idx = self.pre_editor_positions["body"]
                    self.editor_selected["pre"] = idx
                    if idx == 0:
                        ch.lpf_hz = float(np.clip(ch.lpf_hz + axis_value * 30.0, POL_LOW_HZ, 1200.0))
                    elif idx == 4:
                        ch.hpf_hz = float(np.clip(ch.hpf_hz + axis_value * 260.0, 4000.0, POL_HIGH_HZ))
                elif self.pre_editor_column == 3:
                    if self.pre_editor_positions["right"] == 0:
                        ch.send_slot = int(np.clip(ch.send_slot + (1 if axis_value > 0 else -1), 1, 8))
                    else:
                        ch.send_level = float(np.clip(ch.send_level + axis_value * 0.04, 0.0, 1.0))
            self._sync_from_engine()
            return
        if self.selected_stage_key != "pre":
            ch = self._current_channel()
            with self.engine._lock:
                if self.module_editor_column == 0:
                    if self.module_editor_positions["left"] == 0:
                        if axis_value > 0:
                            self.editor_channel = (self.editor_channel + 1) % (len(self.engine.channels) + 1)
                        else:
                            self.editor_channel = (self.editor_channel - 1) % (len(self.engine.channels) + 1)
                        self._normalize_stage_selection(self.editor_channel)
                        self._normalize_module_editor_positions()
                    else:
                        ch.gain = float(np.clip(ch.gain + axis_value * 0.04, 0.3, 2.2))
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
                            band = self._eq_band(ch, idx)
                            band["enabled"] = axis_value > 0
                            ch.eq_enabled = any(b["enabled"] and abs(float(b["gain_db"])) > 0.05 for b in ch.eq_bands[: max(1, ch.eq_band_count)])
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
                                ch.harmonics_enabled = bool(np.any(ch.harmonics > 0.001))
                            elif body_idx == 5:
                                ch.harmonic_makeup = float(np.clip(ch.harmonic_makeup + step * 0.08, 0.6, 2.4))
                        elif self.selected_stage_key == "comp":
                            if body_idx == 0:
                                ch.comp_threshold_db = float(np.clip(ch.comp_threshold_db + step * 1.0, -42.0, 0.0))
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
                elif self.module_editor_column == 3:
                    if self.module_editor_positions["right"] == 0:
                        ch.send_slot = int(np.clip(ch.send_slot + (1 if axis_value > 0 else -1), 1, 8))
                    else:
                        ch.send_level = float(np.clip(ch.send_level + axis_value * 0.04, 0.0, 1.0))
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
                    ch.harmonics_enabled = bool(np.any(ch.harmonics > 0.001))
                elif idx == 5:
                    ch.harmonic_makeup = float(np.clip(ch.harmonic_makeup + step * 0.08, 0.6, 2.4))
            elif self.selected_stage_key == "comp":
                if idx == 0:
                    ch.comp_threshold_db = float(np.clip(ch.comp_threshold_db + step * 1.0, -42.0, 0.0))
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
            return [2, len(self._console_stage_keys()), 5, 2][self.pre_editor_column]
        if self.editor_nav_scope == "comp-top":
            return 3
        if self.editor_nav_scope == "eq-top":
            return max(1, self._current_channel().eq_band_count)
        if self.editor_nav_scope == "tone-top":
            return 3
        return {"pre": 5, "harm": 6, "comp": 7, "eq": 5, "tone": 4}[self.selected_stage_key]

    def _handle_console_nav(self, target: str) -> None:
        stage_keys = self._console_stage_keys()
        if self.console_row == "stages":
            stage_idx = stage_keys.index(self.selected_stage_key)
        else:
            stage_idx = 0
        is_input_channel = self.selected_channel < len(self.engine.channels)
        if target == "left":
            self.selected_channel = (self.selected_channel - 1) % (len(self.engine.channels) + 1)
            if self.console_row == "record" and not (self.selected_channel < len(self.engine.channels)):
                self.console_row = "stages"
                self.selected_stage_key = self._console_stage_keys()[0]
            elif self.console_row == "stages":
                self._normalize_console_selection()
        elif target == "right":
            self.selected_channel = (self.selected_channel + 1) % (len(self.engine.channels) + 1)
            if self.console_row == "record" and not (self.selected_channel < len(self.engine.channels)):
                self.console_row = "stages"
                self.selected_stage_key = self._console_stage_keys()[0]
            elif self.console_row == "stages":
                self._normalize_console_selection()
        elif target == "up":
            if self.console_row == "footer":
                if is_input_channel:
                    self.console_row = "record"
                else:
                    self.console_row = "stages"
                    self._normalize_console_selection()
                    self.selected_stage_key = stage_keys[-1]
            elif self.console_row == "record":
                self.console_row = "stages"
                self.selected_stage_key = stage_keys[0]
            else:
                if stage_idx == 0:
                    self.console_row = "record" if is_input_channel else "footer"
                else:
                    self.selected_stage_key = stage_keys[(stage_idx - 1) % len(stage_keys)]
        elif target == "down":
            if self.console_row == "footer":
                if is_input_channel:
                    self.console_row = "record"
                else:
                    self.console_row = "stages"
                    self._normalize_console_selection()
                    if stage_keys:
                        self.selected_stage_key = stage_keys[0]
            elif self.console_row == "record":
                self.console_row = "stages"
                self.selected_stage_key = stage_keys[0]
            elif stage_idx == len(stage_keys) - 1:
                self.console_row = "footer"
            else:
                self.selected_stage_key = stage_keys[(stage_idx + 1) % len(stage_keys)]
        elif target in ("press", "back"):
            if self.console_row == "footer":
                if target == "press":
                    self._toggle_solo(self.selected_channel)
                elif target == "back":
                    self._toggle_mute(self.selected_channel)
                return
            if self.console_row == "record":
                if target == "press" and is_input_channel:
                    self._toggle_record_arm(self.selected_channel)
                return
            if target == "press":
                self.editor_channel = self.selected_channel
                self.nav_scope = "editor"
                self.editor_nav_scope = "body"
                self._sync_from_engine()
                return
            self._sync_from_engine()

    def _editor_row_sequence(self) -> list[str]:
        if self.selected_stage_key == "pre":
            return ["pre-left", "pre-stage", "pre-body", "pre-right"]
        return ["module-left", "module-stage", "module-body", "module-right"]

    def _set_editor_nav_scope(self, scope: str) -> None:
        if self.selected_stage_key == "pre" and scope.startswith("pre-"):
            self.editor_nav_scope = scope
            self.pre_editor_column = {"pre-left": 0, "pre-stage": 1, "pre-body": 2, "pre-right": 3}.get(scope, self.pre_editor_column)
            return
        if self.selected_stage_key != "pre" and scope.startswith("module-"):
            self.editor_nav_scope = scope
            self.module_editor_column = {"module-left": 0, "module-stage": 1, "module-body": 2, "module-right": 3}.get(scope, self.module_editor_column)
            return
        self.editor_nav_scope = scope
        if self.selected_stage_key == "comp":
            self.comp_nav_row = "top" if scope == "comp-top" else "bottom"
        elif self.selected_stage_key == "eq":
            self.eq_nav_row = "top" if scope == "eq-top" else "bottom"
        elif self.selected_stage_key == "tone":
            self.tone_nav_row = "top" if scope == "tone-top" else "bottom"

    def _handle_nav(self, target: str) -> None:
        _log.debug(
            "NAV %s | scope=%s stage=%s col=%s body=%s editor_nav=%s",
            target, self.nav_scope, self.selected_stage_key,
            self.module_editor_column, self.module_editor_positions.get("body"),
            self.editor_nav_scope,
        )
        try:
            if self.nav_scope == "console":
                self._handle_console_nav(target)
                return
            if self.selected_stage_key == "pre":
                self._handle_pre_editor_nav(target)
                return
            self._handle_module_editor_nav(target)
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
            return 2
        if key == "stage":
            return len(self._console_stage_keys())
        if key == "body":
            return max(1, self._module_editor_body_count())
        return 2

    def _reset_module_body_selection(self) -> None:
        ch = self._current_channel()
        top_items, _ = self._module_stage_items(ch)
        if self.selected_stage_key == "eq":
            self.module_editor_positions["body"] = min(self.eq_selected_band, max(0, len(top_items) - 1)) if top_items else 0
        else:
            self.module_editor_positions["body"] = 0

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
                self._toggle_tone_top()
            return
        body_idx = idx - len(top_items)
        if 0 <= body_idx < len(body_items):
            label = body_items[body_idx][0]
            self.editor_selected[self.selected_stage_key] = body_idx
            self._activate_editor_item(body_idx, label)

    def _handle_module_editor_nav(self, target: str) -> None:
        columns = ["left", "stage", "body", "right"]
        current_key = columns[self.module_editor_column]
        if current_key == "stage" and target == "right":
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
                    self.module_editor_column = (self.module_editor_column + 1) % len(columns)
            elif target == "up":
                row = (row - 1) % rows
                self.module_editor_positions["body"] = row if col == 0 else row + rows
            elif target == "down":
                row = (row + 1) % rows
                self.module_editor_positions["body"] = row if col == 0 else row + rows
            elif target == "press":
                now = time.monotonic()
                if now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self.nav_scope = "console"
                    self.editor_nav_scope = "body"
                    self._editor_last_press_at = 0.0
                    self._sync_from_engine()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._sync_from_engine()
                return
        elif current_key == "body" and self.selected_stage_key == "comp":
            idx = self.module_editor_positions["body"]
            left_indices = [0, 1, 2, 4, 5]
            right_indices = [3, 7, 8, 9, 6]
            if idx in left_indices:
                col = 0
                row = left_indices.index(idx)
            else:
                col = 1
                row = right_indices.index(idx)
            if target == "left":
                if col == 1:
                    self.module_editor_positions["body"] = left_indices[row]
                else:
                    self.module_editor_column = (self.module_editor_column - 1) % len(columns)
            elif target == "right":
                if col == 0:
                    self.module_editor_positions["body"] = right_indices[row]
                else:
                    self.module_editor_column = (self.module_editor_column + 1) % len(columns)
            elif target == "up":
                row = (row - 1) % 5
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "down":
                row = (row + 1) % 5
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "press":
                now = time.monotonic()
                if now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self.nav_scope = "console"
                    self.editor_nav_scope = "body"
                    self._editor_last_press_at = 0.0
                    self._sync_from_engine()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._sync_from_engine()
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
                    self.module_editor_column = (self.module_editor_column + 1) % len(columns)
            elif target == "up":
                row = (row - 1) % 3
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "down":
                row = (row + 1) % 3
                self.module_editor_positions["body"] = left_indices[row] if col == 0 else right_indices[row]
            elif target == "press":
                now = time.monotonic()
                if now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self.nav_scope = "console"
                    self.editor_nav_scope = "body"
                    self._editor_last_press_at = 0.0
                    self._sync_from_engine()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._sync_from_engine()
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
                    self.module_editor_column = (self.module_editor_column + 1) % len(columns)
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
                if now - self._editor_last_press_at <= 0.30:
                    if self.module_editor_positions["left"] == 0 and current_key == "left":
                        if self._active_channel_index() < len(self.engine.channels):
                            self._toggle_solo(self._active_channel_index())
                        self._editor_last_press_at = 0.0
                        return
                    self.nav_scope = "console"
                    self.editor_nav_scope = "body"
                    self._editor_last_press_at = 0.0
                    self._sync_from_engine()
                    return
                self._editor_last_press_at = now
                self._activate_module_body_selection()
                return
            elif target == "back":
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._sync_from_engine()
                return
        elif target == "left":
            self.module_editor_column = (self.module_editor_column - 1) % len(columns)
        elif target == "right":
            self.module_editor_column = (self.module_editor_column + 1) % len(columns)
        elif target == "up":
            self.module_editor_positions[current_key] = (self.module_editor_positions[current_key] - 1) % self._module_editor_count_for_key(current_key)
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.module_editor_positions["stage"]]
                self._reset_module_body_selection()
                if self.selected_stage_key == "pre":
                    self.pre_editor_column = 1
                    self.pre_editor_positions["stage"] = self.module_editor_positions["stage"]
                self._normalize_module_editor_positions()
        elif target == "down":
            self.module_editor_positions[current_key] = (self.module_editor_positions[current_key] + 1) % self._module_editor_count_for_key(current_key)
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.module_editor_positions["stage"]]
                self._reset_module_body_selection()
                if self.selected_stage_key == "pre":
                    self.pre_editor_column = 1
                    self.pre_editor_positions["stage"] = self.module_editor_positions["stage"]
                self._normalize_module_editor_positions()
        elif target == "press":
            now = time.monotonic()
            if now - self._editor_last_press_at <= 0.30:
                if current_key == "left" and self.module_editor_positions["left"] == 0:
                    if self._active_channel_index() < len(self.engine.channels):
                        self._toggle_solo(self._active_channel_index())
                    self._editor_last_press_at = 0.0
                    return
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._editor_last_press_at = 0.0
                self._sync_from_engine()
                return
            self._editor_last_press_at = now
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.module_editor_positions["stage"]]
                self._normalize_module_editor_positions()
                self._sync_from_engine()
                return
            if current_key == "left" and self.module_editor_positions["left"] == 0:
                if self._active_channel_index() < len(self.engine.channels):
                    self._toggle_mute(self._active_channel_index())
                return
            if current_key == "body":
                self._activate_module_body_selection()
                return
            if current_key == "right" and self.module_editor_positions["right"] == 0:
                self._toggle_send_mute(self._active_channel_index())
                return
        elif target == "back":
            self.nav_scope = "console"
            self.editor_nav_scope = "body"
            self._sync_from_engine()
            return
        self.editor_nav_scope = ["module-left", "module-stage", "module-body", "module-right"][self.module_editor_column]
        self._sync_from_engine()

    def _handle_pre_editor_nav(self, target: str) -> None:
        columns = ["left", "stage", "body", "right"]
        current_key = columns[self.pre_editor_column]
        if target == "left":
            self.pre_editor_column = (self.pre_editor_column - 1) % len(columns)
        elif target == "right":
            self.pre_editor_column = (self.pre_editor_column + 1) % len(columns)
        elif target == "up":
            self.pre_editor_positions[current_key] = (self.pre_editor_positions[current_key] - 1) % self._pre_editor_count(current_key)
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.pre_editor_positions["stage"]]
                if self.selected_stage_key != "pre":
                    self.module_editor_column = 1
                    self.module_editor_positions["stage"] = self.pre_editor_positions["stage"]
                    self._normalize_module_editor_positions()
        elif target == "down":
            self.pre_editor_positions[current_key] = (self.pre_editor_positions[current_key] + 1) % self._pre_editor_count(current_key)
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.pre_editor_positions["stage"]]
                if self.selected_stage_key != "pre":
                    self.module_editor_column = 1
                    self.module_editor_positions["stage"] = self.pre_editor_positions["stage"]
                    self._normalize_module_editor_positions()
        elif target == "press":
            now = time.monotonic()
            if now - self._editor_last_press_at <= 0.30:
                if current_key == "left" and self.pre_editor_positions["left"] == 0:
                    if self._active_channel_index() < len(self.engine.channels):
                        self._toggle_solo(self._active_channel_index())
                    self._editor_last_press_at = 0.0
                    return
                self.nav_scope = "console"
                self.editor_nav_scope = "body"
                self._editor_last_press_at = 0.0
                self._sync_from_engine()
                return
            self._editor_last_press_at = now
            if current_key == "stage":
                stage_keys = self._console_stage_keys()
                self.selected_stage_key = stage_keys[self.pre_editor_positions["stage"]]
                if self.selected_stage_key != "pre":
                    self.editor_nav_scope = "body"
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
            if current_key == "right" and self.pre_editor_positions["right"] == 0:
                self._toggle_send_mute(self._active_channel_index())
                return
        elif target == "back":
            self.nav_scope = "console"
            self.editor_nav_scope = "body"
            self._sync_from_engine()
            return
        self.editor_nav_scope = ["pre-left", "pre-stage", "pre-body", "pre-right"][self.pre_editor_column]
        self._sync_from_engine()

    def _pre_editor_count(self, key: str) -> int:
        if key == "left":
            return 2
        if key == "stage":
            return len(self._console_stage_keys())
        if key == "body":
            return 5
        return 2

    def _poll_spacemouse(self) -> None:
        axis_value, pressed, directional = self.spacemouse.poll()
        if self.nav_scope == "editor":
            if directional:
                self._handle_nav(directional[0])
            if pressed and 0 in pressed:
                self._handle_nav("press")
            self._adjust_selected_editor_item(axis_value)
        else:
            self._console_hold_target = None

    def _poll_console_hold_repeat(self) -> None:
        self._console_hold_target = None
        return

    def _freq_to_slider(self, freq: float) -> float:
        freq = float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ))
        return (math.log10(freq) - LOG_LOW) / (LOG_HIGH - LOG_LOW)

    def _slider_to_freq(self, slider_pos: float) -> float:
        slider_pos = max(0.0, min(1.0, slider_pos))
        return 10 ** (LOG_LOW + slider_pos * (LOG_HIGH - LOG_LOW))

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
        header_offset = 55
        usable_h = h - header_offset
        cx = w * 0.50
        cy = header_offset + usable_h * 0.48
        outer_rx = w * 0.38
        outer_ry = usable_h * 0.38
        inner_rx = outer_rx * 0.22
        inner_ry = outer_ry * 0.22
        return cx, cy, outer_rx, outer_ry, inner_rx, inner_ry

    def _draw_focus_ring_grid(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        for i in range(14):
            mix = i / 13.0
            rx = outer_rx - (outer_rx - inner_rx) * mix
            ry = outer_ry - (outer_ry - inner_ry) * mix
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline="#24313d", width=1)
        c.create_line(cx - outer_rx - 28, cy, cx + outer_rx + 28, cy, fill="#31404e")
        c.create_line(cx, max(0, cy - outer_ry - 36), cx, min(cy + outer_ry + 36, cy + outer_ry + 16), fill="#31404e")

    def _draw_focus_signal(self, c: tk.Canvas, ch: ChannelState, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        for i, level in enumerate(ch.band_levels):
            amt = float(np.clip(level, 0.0, 1.0))
            if amt < 0.02:
                continue
            mix = i / max(1, POL_BANDS - 1)
            rx = outer_rx - (outer_rx - inner_rx) * mix
            ry = outer_ry - (outer_ry - inner_ry) * mix
            color = hsv_to_hex(0.62 - amt * 0.62, 0.92, 0.12 + amt * 0.98)
            width = 1 + int(amt * 5)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=width)
            if amt > 0.35:
                glow = hsv_to_hex(0.62 - amt * 0.62, 0.45, 0.10 + amt * 0.45)
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
        self._draw_focus_signal(c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if ch.lpf_enabled:
            pos = self._freq_to_slider(ch.lpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * pos
            for layer in range(14):
                mix = layer / 13.0
                layer_rx = cutoff_rx + (outer_rx - cutoff_rx) * mix
                layer_ry = cutoff_ry + (outer_ry - cutoff_ry) * mix
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=hsv_to_hex(0.0, 0.94, 0.34 + mix * 0.28), width=3)
            c.create_oval(cx - outer_rx, cy - outer_ry, cx + outer_rx, cy + outer_ry, outline="#ff3c2e", width=4)
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline="#ffd08a", width=3)
        if ch.hpf_enabled:
            pos = self._freq_to_slider(ch.hpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * pos
            for layer in range(14):
                mix = layer / 13.0
                layer_rx = inner_rx + (cutoff_rx - inner_rx) * mix
                layer_ry = inner_ry + (cutoff_ry - inner_ry) * mix
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=hsv_to_hex(0.0, 0.94, 0.34 + mix * 0.28), width=3)
            c.create_oval(cx - inner_rx, cy - inner_ry, cx + inner_rx, cy + inner_ry, outline="#ff3c2e", width=4)
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline="#ffd08a", width=3)

    def _draw_focus_harmonics(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        positions = [0.10, 0.30, 0.50, 0.68, 0.84]
        for idx, weight in enumerate(ch.harmonics):
            if weight <= 0.01:
                continue
            rx = outer_rx - (outer_rx - inner_rx) * positions[idx]
            ry = outer_ry - (outer_ry - inner_ry) * positions[idx]
            heat = float(weight)
            expand = 8 + heat * 14
            color = hsv_to_hex(0.12 - idx * 0.015, 0.85, 0.55 + heat * 0.4)
            glow = hsv_to_hex(0.16 - idx * 0.012, 0.45, 0.22 + heat * 0.35)
            c.create_oval(cx - rx - expand, cy - ry - expand * 0.72, cx + rx + expand, cy + ry + expand * 0.72, outline=glow, width=1)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 + int(heat * 3))
        c.create_text(cx, h - 28, text=f"MAKE {ch.harmonic_makeup:.2f}x", fill="#8ea3ba", font=("Segoe UI", 10, "bold"))

    def _draw_focus_compressor(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        threshold_norm = np.clip((-ch.comp_threshold_db) / 48.0, 0.0, 1.0)
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

        if ch.comp_enabled:
            outer_wall_rx, outer_wall_ry, band_inner_rx, band_inner_ry = band_bounds("COMP")
            inner_threshold_rx = max(band_inner_rx, outer_wall_rx - (outer_wall_rx - band_inner_rx) * (threshold_norm * 0.58))
            inner_threshold_ry = max(band_inner_ry, outer_wall_ry - (outer_wall_ry - band_inner_ry) * (threshold_norm * 0.58))
            pulse_pull = pressure * (0.12 + threshold_norm * 0.10)
            pump_rx = max(band_inner_rx, inner_threshold_rx - (inner_threshold_rx - band_inner_rx) * pulse_pull)
            pump_ry = max(band_inner_ry, inner_threshold_ry - (inner_threshold_ry - band_inner_ry) * pulse_pull)
            overlay_layers = 8 + int(10 * ratio_darkness)
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                layer_rx = pump_rx + (outer_wall_rx - pump_rx) * mix
                layer_ry = pump_ry + (outer_wall_ry - pump_ry) * mix
                layer_color = hsv_to_hex(0.0, 0.84, min(1.0, 0.28 + mix * 0.18 + ratio_darkness * 0.22))
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=1 + int(ratio_darkness * 2))
            c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline="#ff5b54", width=4)
            c.create_oval(cx - pump_rx, cy - pump_ry, cx + pump_rx, cy + pump_ry, outline="#ffd2b0", width=3 + int(pressure * 2))

        if ch.limit_enabled:
            outer_wall_rx, outer_wall_ry, band_inner_rx, band_inner_ry = band_bounds("LIMIT")
            inner_threshold_rx = max(band_inner_rx, outer_wall_rx - (outer_wall_rx - band_inner_rx) * (threshold_norm * 0.58))
            inner_threshold_ry = max(band_inner_ry, outer_wall_ry - (outer_wall_ry - band_inner_ry) * (threshold_norm * 0.58))
            layers = 10 + int(ratio_darkness * 6)
            for layer in range(layers):
                mix = layer / max(1, layers - 1)
                layer_rx = inner_threshold_rx + (outer_wall_rx - inner_threshold_rx) * mix
                layer_ry = inner_threshold_ry + (outer_wall_ry - inner_threshold_ry) * mix
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline="#bf1f27", width=2)
            c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline="#ff5b54", width=4)
            c.create_oval(cx - inner_threshold_rx, cy - inner_threshold_ry, cx + inner_threshold_rx, cy + inner_threshold_ry, outline="#ffd2b0", width=3)

        if ch.gate_enabled:
            outer_wall_rx, outer_wall_ry, band_inner_rx, band_inner_ry = band_bounds("GATE")
            inner_threshold_rx = max(band_inner_rx, outer_wall_rx - (outer_wall_rx - band_inner_rx) * (threshold_norm * 0.58))
            inner_threshold_ry = max(band_inner_ry, outer_wall_ry - (outer_wall_ry - band_inner_ry) * (threshold_norm * 0.58))
            layers = 9
            for layer in range(layers):
                mix = layer / max(1, layers - 1)
                layer_rx = inner_threshold_rx + (outer_wall_rx - inner_threshold_rx) * mix
                layer_ry = inner_threshold_ry + (outer_wall_ry - inner_threshold_ry) * mix
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline="#a6222a", width=2)
            c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline="#ff5b54", width=4)
            c.create_oval(cx - inner_threshold_rx, cy - inner_threshold_ry, cx + inner_threshold_rx, cy + inner_threshold_ry, outline="#ffb0a0", width=2)

        c.create_text(cx, cy - 10, text=f"{self.comp_editor_mode} GR {ch.comp_gr_db:.1f} dB", fill="#f6a864", font=("Segoe UI", 16, "bold"))

    def _draw_focus_eq(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        active_count = max(1, ch.eq_band_count)
        for i in range(active_count):
            band = self._eq_band(ch, i)
            if not band["enabled"]:
                continue
            center = float(np.clip(float(band["freq"]), POL_LOW_HZ, POL_HIGH_HZ))
            width_oct = float(np.clip(float(band["width"]), 0.20, 6.0))
            start_hz = max(POL_LOW_HZ, center / (2 ** (width_oct / 2)))
            end_hz = min(POL_HIGH_HZ, center * (2 ** (width_oct / 2)))
            start_pos = self._freq_to_slider(start_hz)
            end_pos = self._freq_to_slider(end_hz)
            start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
            start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
            end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
            end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
            color = eq_gain_color(float(band["gain_db"]))
            for layer in range(7):
                mix = layer / 6.0
                layer_rx = start_rx + (end_rx - start_rx) * mix
                layer_ry = start_ry + (end_ry - start_ry) * mix
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=color, width=3 if i == self.eq_selected_band else 2)
        current_band = self._eq_band(ch)
        c.create_text(cx, cy - outer_ry - 18, text=f"B{self.eq_selected_band + 1}  {float(current_band['freq']):.0f} Hz  {float(current_band['gain_db']):+.1f} dB", fill="#f6a864", font=("Segoe UI", 11, "bold"))

    def _draw_focus_tone(self, c: tk.Canvas, ch: ChannelState, w: int, h: int):
        cx, cy, outer_rx, outer_ry, inner_rx, inner_ry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        self._draw_focus_signal(c, ch, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if ch.trn_attack > 0.02 or ch.trn_sustain > 0.02:
            attack_heat = float(np.clip(ch.trn_attack, 0.0, 1.0))
            for layer in range(8):
                mix = layer / 7.0
                color = lerp_color((105, 223, 242), (255, 92, 58), attack_heat)
                rx = inner_rx + (outer_rx * 0.7 - inner_rx) * mix
                ry = inner_ry + (outer_ry * 0.7 - inner_ry) * mix
                c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2)
        if ch.clr_drive > 0.02:
            radius = 12 + ch.clr_drive * 34
            c.create_oval(cx - radius, cy - radius * 0.7, cx + radius, cy + radius * 0.7, fill="#ff9d55", outline="")
        if ch.xct_amount > 0.02:
            c.create_line(cx - outer_rx * 0.7, cy + outer_ry * 0.1, cx + outer_rx * 0.7, cy - outer_ry * 0.18, fill="#f1f57a", width=4)

    def _draw_strips(self) -> None:
        c = self.strip_canvas
        c.delete("all")
        self.stage_hitboxes = []
        self.record_hitboxes = []
        self.scribble_hitboxes = []
        width = max(c.winfo_width(), 980)
        height = max(c.winfo_height(), 680)
        c.create_rectangle(0, 0, width, height, fill="#151a20", outline="")
        margin_x = 18
        top_y = 22
        strip_gap = 12
        meter_height = 104
        strip_w = self.STRIP_WIDTH
        strip_sources = list(self.engine.channels) + [self.engine.master_channel]
        total_w = len(strip_sources) * strip_w + (len(strip_sources) - 1) * strip_gap
        start_x = max(margin_x, (width - total_w) / 2)
        active_strip_index = self.editor_channel if self.nav_scope == "editor" else -1
        console_row_active = self.console_row if self.nav_scope == "console" else None
        for idx, ch in enumerate(strip_sources):
            x0 = start_x + idx * (strip_w + strip_gap)
            x1 = x0 + strip_w
            selected_channel = idx == active_strip_index
            stage_labels = [("PRE", "pre"), ("HAR", "harm"), ("CMP", "comp"), ("EQ", "eq"), ("TONE", "tone")]
            if idx == len(self.engine.channels):
                stage_labels = [("", None), ("HAR", "harm"), ("CMP", "comp"), ("EQ", "eq"), ("TONE", "tone")]
            outline = "#30404f"
            fill = "#181e25"
            if idx == len(self.engine.channels):
                fill = "#1b1d24"
                outline = "#506071"
            c.create_rectangle(x0, top_y, x1, height - 24, fill=fill, outline=outline, width=1)

            rec_top = top_y + 14
            rec_bottom = rec_top + 28
            is_master = idx == len(self.engine.channels)
            if not is_master:
                record_selected = selected_channel and console_row_active == "record"
                c.create_rectangle(
                    x0 + 18,
                    rec_top,
                    x1 - 18,
                    rec_bottom,
                    fill="#232b34" if record_selected else "#10151b",
                    outline="#f8d58a" if record_selected else "#2b3743",
                    width=2 if record_selected else 1,
                )
                dot_fill = "#ff3b30" if ch.record_armed else "#ff7b73"
                dot_outline = "#ffd7d3" if ch.record_armed else ""
                c.create_oval((x0 + x1) / 2 - 8, rec_top + 6, (x0 + x1) / 2 + 8, rec_bottom - 6, fill=dot_fill, outline=dot_outline, width=1 if ch.record_armed else 0)
                self.record_hitboxes.append((x0 + 18, rec_top, x1 - 18, rec_bottom, idx))

            meter_top = rec_bottom + 12
            c.create_rectangle(x0 + 24, meter_top, x1 - 24, meter_top + meter_height, fill="#0d1116", outline="#28323d")
            meter_fill = np.clip(ch.level, 0.0, 1.0)
            meter_y = meter_top + meter_height * (1.0 - meter_fill)
            meter_color = "#5ef0b0" if meter_fill < 0.7 else "#f7c46f" if meter_fill < 0.9 else "#ff6868"
            c.create_rectangle(x0 + 26, meter_y, x1 - 26, meter_top + meter_height - 2, fill=meter_color, outline="")

            for s_idx, (label, key) in enumerate(stage_labels):
                sy0 = meter_top + meter_height + 18 + s_idx * (self.STAGE_HEIGHT + 10)
                sy1 = sy0 + self.STAGE_HEIGHT
                if key is None:
                    c.create_rectangle(x0 + 8, sy0, x1 - 8, sy1, fill="#1b2128", outline="#28323d")
                    continue
                enabled = self._stage_enabled(ch, key)
                box_x0 = x0 + 8
                box_x1 = x1 - 8
                c.create_rectangle(box_x0, sy0, box_x1, sy1, fill="#202832", outline="#34414e")
                accent = self.stage_color[key] if enabled else "#2a3440"
                accent_fill = "#222b35"
                selected_stage = self.nav_scope == "editor" and selected_channel and key == self.selected_stage_key
                if selected_stage:
                    accent_fill = accent
                c.create_rectangle(box_x0 + 2, sy0 + 2, box_x1 - 2, sy1 - 2, fill=accent_fill, outline="")
                if selected_stage:
                    c.create_rectangle(box_x0 + 1, sy0 + 1, box_x1 - 1, sy1 - 1, outline="#d9e6f2", width=2)
                inner_pad = 8
                vis_x0 = box_x0 + inner_pad
                vis_x1 = box_x1 - inner_pad
                vis_y0 = sy0 + inner_pad
                vis_y1 = sy1 - inner_pad
                visual_enabled = enabled if selected_stage else False
                self._draw_stage_visual(c, ch, key, vis_x0, vis_y0, vis_x1, vis_y1, visual_enabled, selected_stage)
                self.stage_hitboxes.append((box_x0, sy0, box_x1, sy1, idx, key))

            footer_y = height - 56
            strip_y0 = footer_y - 16
            strip_y1 = footer_y + 16
            strip_x0 = x0 + 10
            strip_x1 = x1 - 10
            c.create_rectangle(strip_x0, strip_y0, strip_x1, strip_y1, fill="#1b222a", outline="#31404e")
            footer_selected = selected_channel and console_row_active == "footer"
            if is_master:
                c.create_rectangle(strip_x0 + 2, strip_y0 + 2, strip_x1 - 2, strip_y1 - 2, fill="#2a313b" if footer_selected else "", outline="")
                c.create_text((strip_x0 + strip_x1) / 2, footer_y, text="MST", fill="#d8dfe8", font=("Orbitron", 8, "bold"))
            elif ch.mute:
                c.create_rectangle(strip_x0 + 2, strip_y0 + 2, strip_x1 - 2, strip_y1 - 2, fill="#6b171c", outline="")
                c.create_text((strip_x0 + strip_x1) / 2, footer_y, text="M", fill="#ffd7d3", font=("Orbitron", 10, "bold"))
            elif ch.solo:
                c.create_rectangle(strip_x0 + 2, strip_y0 + 2, strip_x1 - 2, strip_y1 - 2, fill="#645019", outline="")
                c.create_text((strip_x0 + strip_x1) / 2, footer_y, text="S", fill="#fff0b2", font=("Orbitron", 10, "bold"))
            else:
                if footer_selected:
                    c.create_rectangle(strip_x0 + 2, strip_y0 + 2, strip_x1 - 2, strip_y1 - 2, fill="#2a313b", outline="")
                c.create_oval((strip_x0 + strip_x1) / 2 - 4, footer_y - 4, (strip_x0 + strip_x1) / 2 + 4, footer_y + 4, fill="#354250", outline="")
            if idx < len(self.engine.channels):
                self.scribble_hitboxes.append((strip_x0, strip_y0, strip_x1, strip_y1, idx))

        self._draw_master_meter()

    def _stage_enabled(self, ch: ChannelState, key: str) -> bool:
        return {"pre": ch.pre_enabled, "harm": ch.harmonics_enabled, "comp": ch.comp_enabled, "eq": ch.eq_enabled, "tone": ch.tone_enabled}[key]

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
            if enabled and ch.tube:
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
            gain_col = eq_gain_color(ch.eq_gain_db) if enabled else "#3d4856"
            c.create_oval(x0 + 8, y0 + h * 0.78 - 4, x0 + 16, y0 + h * 0.78 + 4, fill=gain_col, outline="")
        elif key == "tone":
            # 3D effects/transient visual
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
            c.create_polygon(*pts, fill="#86d5ff" if enabled else "#33414f", outline="#4d82cc", smooth=True)
            pts2 = []
            for step in range(72):
                t = step / 72.0 * math.tau
                mod = 1.0 + 0.24 * math.sin(t * 5.0 + 0.7) * amp
                x = center_x + math.cos(t + 0.5) * rx0 * 0.72 * mod
                y = center_y + math.sin(t + 0.5) * ry0 * 0.72 * mod
                pts2.extend([x, y])
            c.create_polygon(*pts2, fill="#ff8f70" if enabled else "#3c434c", outline="#d44a36", smooth=True)
            c.create_oval(center_x - 4, center_y - 4, center_x + 4, center_y + 4, fill="#ffd068" if enabled else "#3c4652", outline="")

    def _on_strip_click(self, event) -> None:
        _log.debug("STRIP CLICK x=%d y=%d", event.x, event.y)
        self.root.after_idle(self.root.focus_set)

        for x0, y0, x1, y1, idx in getattr(self, "record_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.selected_channel = idx
                self.console_row = "record"
                self.nav_scope = "console"
                self._sync_from_engine()
                self.root.focus_set()
                return
        for x0, y0, x1, y1, idx in getattr(self, "scribble_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.selected_channel = idx
                self.console_row = "footer"
                self.nav_scope = "console"
                if self._pending_strip_click is not None:
                    self.root.after_cancel(self._pending_strip_click)
                self._pending_strip_click = self.root.after(220, lambda channel=idx: self._toggle_solo(channel))
                self._sync_from_engine()
                self.root.focus_set()
                return
        for x0, y0, x1, y1, idx, key in getattr(self, "stage_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                _log.debug("STAGE HIT ch=%d key=%s", idx, key)
                self.selected_channel = idx
                self.editor_channel = idx
                self.selected_stage_key = key
                self.console_row = "stages"
                self.nav_scope = "editor"
                if key == "pre":
                    self.pre_editor_column = 1
                    self.editor_nav_scope = "pre-stage"
                else:
                    self.module_editor_column = 1
                    self._reset_module_body_selection()
                    self._normalize_module_editor_positions()
                    self.editor_nav_scope = "module-stage"
                self._sync_from_engine()
                self.root.focus_set()
                return

    def _on_strip_double_click(self, event) -> None:
        if self._pending_strip_click is not None:
            self.root.after_cancel(self._pending_strip_click)
            self._pending_strip_click = None
        for x0, y0, x1, y1, idx in getattr(self, "scribble_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._toggle_mute(idx)
                return

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

    def _schedule_refresh(self) -> None:
        try:
            self._poll_spacemouse()
            self._draw_strips()
            self._draw_focus()
            self._draw_editor_controls()
        except Exception:
            import traceback
            traceback.print_exc()
            self.root.title(f"DRAW ERROR: {traceback.format_exc().splitlines()[-1]}")
        self.root.after(60, self._schedule_refresh)

    def on_close(self) -> None:
        self.engine.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = ConsoleApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

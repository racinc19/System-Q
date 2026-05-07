import math
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import soundfile as sf

# Global logging setup for all modules
_log_path = Path(__file__).resolve().parent / "console_debug.log"
logging.basicConfig(
    filename=str(_log_path),
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
_log = logging.getLogger("console")

# --- Constants ---
SYSTEM_Q_BUILD_ID = "gen-pink-pulse-white-hot-20260503"
DISCRETE_TWIST_MIN = 0.35
SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
POL_BANDS = 36
POL_LOW_HZ = 20.0
POL_HIGH_HZ = 22000.0
LOG_LOW = math.log10(POL_LOW_HZ)
LOG_HIGH = math.log10(POL_HIGH_HZ)
POL_BAND_CENTER_HZ = np.logspace(LOG_LOW, LOG_HIGH, POL_BANDS)

POL_LEVEL_DB_AXIS_OUTER = -72.0
POL_LEVEL_DB_AXIS_INNER = 12.0
POL_LEVEL_GUIDE_TICKS_DB = (-48.0, -36.0, -24.0, -12.0, 0.0, 4.0, 8.0, 12.0)
POL_LEVEL_GUIDE_INNER_SCALE = 0.28

TONE_HEX_TRN = "#36e0dc"
TONE_HEX_CLR = "#ff8f3a"
TONE_HEX_XCT = "#c06cff"
POL_NEON_RED = "#ff0019"
POL_NEON_RED_HI = "#ff3355"
POL_NEON_RED_HOT = "#ff99aa"

ROOT_DIR = Path(__file__).resolve().parent
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

_STRIP_LINK_COPY_SKIP = frozenset({
    "name", "path", "audio", "wave_preview", "position", "level",
    "comp_gr_db", "comp_env", "gate_env", "gate_gain_smooth",
    "band_levels", "band_noise_floor",
})

# --- Utility Functions ---
def hsv_to_hex(h: float, s: float, v: float) -> str:
    h, s, v = max(0.0, min(1.0, h)), max(0.0, min(1.0, s)), max(0.0, min(1.0, v))
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1.0 - s), v * (1.0 - f * s), v * (1.0 - (1.0 - f) * s)
    i %= 6
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"

def lerp_color(c1, c2, t: float) -> str:
    t = max(0.0, min(1.0, t))
    return rgb_to_hex(int(c1[0] + (c2[0] - c1[0]) * t), int(c1[1] + (c2[1] - c1[1]) * t), int(c1[2] + (c2[2] - c1[2]) * t))

def eq_spread_brightness_rgb(width_oct: float) -> str:
    w = float(np.clip(width_oct, 0.15, 6.05))
    t = float(np.clip((w - 0.18) / 5.5, 0.0, 1.0))
    return lerp_color((98, 86, 128), (250, 252, 253), t)

def hz_log_lerp_hz(a_hz: float, b_hz: float, t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    a_hz = float(np.clip(a_hz, POL_LOW_HZ, POL_HIGH_HZ))
    b_hz = float(np.clip(b_hz, POL_LOW_HZ, POL_HIGH_HZ))
    la, lb = math.log(a_hz), math.log(b_hz)
    return float(math.exp(la + t * (lb - la)))

def ensure_demo_stems() -> None:
    missing = [f for _, f in CHANNEL_LAYOUT if not (STEMS_DIR / f).exists()]
    if not missing: return
    try:
        from generate_band_stems import main as generate_band_stems
        generate_band_stems()
    except Exception:
        raise FileNotFoundError(f"Missing stems in {STEMS_DIR}. Run: py -3 software/generate_band_stems.py")

def freq_rainbow_hue_hz(freq_hz: float) -> float:
    lf = math.log10(float(np.clip(freq_hz, POL_LOW_HZ, POL_HIGH_HZ)))
    pos = float(np.clip((lf - LOG_LOW) / max(1e-9, LOG_HIGH - LOG_LOW), 0.0, 1.0))
    return (240.0 / 360.0) * (1.0 - pos)

def eq_rainbow_color(gain_db: float, center_hz: float, *, insert_active: bool = True) -> str:
    h = freq_rainbow_hue_hz(center_hz)
    if not insert_active: return hsv_to_hex(h, 0.14, 0.32)
    mag = min(1.0, abs(float(np.clip(gain_db, -24.0, 24.0))) / 18.0)
    return hsv_to_hex(h, float(np.clip(0.42 + 0.50 * mag, 0.18, 0.97)), float(np.clip(0.42 + 0.52 * mag, 0.24, 0.97)))

@dataclass
class ChannelState:
    name: str
    path: Path
    audio: np.ndarray = field(default_factory=lambda: np.zeros((1, 2), dtype=np.float32))
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
    harm_tube: bool = False
    gate_tube: bool = False
    comp_tube: bool = False
    eq_tube: bool = False
    lpf_enabled: bool = False
    hpf_enabled: bool = False
    lpf_hz: float = POL_HIGH_HZ
    hpf_hz: float = POL_LOW_HZ
    lpf_state: object = None
    hpf_state: object = None
    lpf_state_cutoff: float = 0.0
    hpf_state_cutoff: float = 0.0
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
    comp_dyn_band_count: int = 1
    comp_dyn_ui_band: int = 0
    comp_dyn_bands: list[dict] = field(default_factory=lambda: [{
        "enabled": False, "freq": 3000.0, "width_oct": 4.0, "threshold_db": -18.0,
        "ratio": 4.0, "attack_ms": 8.0, "release_ms": 120.0, "makeup": 1.0
    } for _ in range(8)])
    limit_center_hz: float = 3000.0
    limit_width_oct: float = 4.0
    limit_band_enabled: bool = False
    gate_sb_band_enabled: bool = False
    gate_center_hz: float = 3000.0
    gate_width_oct: float = 4.0
    gate_band_enabled: bool = False
    gate_dyn_band_count: int = 1
    gate_dyn_ui_band: int = 0
    gate_dyn_bands: list[dict] = field(default_factory=lambda: [{
        "enabled": False, "freq": 3000.0, "width_oct": 4.0, "threshold_db": -45.0,
        "ratio": 8.0, "attack_ms": 3.0, "release_ms": 140.0, "makeup": 1.0
    } for _ in range(8)])
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
    eq_param_bypass: dict[str, bool] = field(default_factory=dict)
    gate_param_bypass: dict[str, bool] = field(default_factory=dict)
    comp_param_bypass: dict[str, bool] = field(default_factory=dict)
    harm_param_bypass: dict[str, bool] = field(default_factory=dict)
    tone_param_bypass: dict[str, bool] = field(default_factory=dict)
    eq_ui_band: int = 0
    trn_enabled: bool = False
    trn_freq: float = 136.0
    trn_width: float = 1.12
    trn_attack: float = 0.0
    trn_sustain: float = 0.0
    trn_drive: float = 0.0
    trn_band_enabled: bool = False
    xct_enabled: bool = False
    xct_freq: float = 7000.0
    xct_width: float = 1.20
    xct_attack: float = 0.0
    xct_sustain: float = 0.0
    xct_drive: float = 0.0
    xct_band_enabled: bool = False
    tbe_enabled: bool = False
    tbe_drive: float = 0.0
    tbe_band_enabled: bool = False
    level: float = 0.0
    comp_gr_db: float = 0.0
    comp_env: float = 0.0
    band_levels: np.ndarray = field(default_factory=lambda: np.zeros(POL_BANDS, dtype=np.float32))
    band_noise_floor: np.ndarray = field(default_factory=lambda: np.full(POL_BANDS, 0.0015, dtype=np.float32))

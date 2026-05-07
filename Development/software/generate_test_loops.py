import math
from pathlib import Path

import numpy as np
import soundfile as sf


SAMPLE_RATE = 48000
LENGTH_SECONDS = 4.0
OUT_DIR = Path(__file__).resolve().parent / "loops"


def envelope(total_samples: int, attack: float, decay: float, sustain: float, release: float) -> np.ndarray:
    a = int(total_samples * attack)
    d = int(total_samples * decay)
    r = int(total_samples * release)
    s = max(0, total_samples - a - d - r)
    parts = []
    if a > 0:
        parts.append(np.linspace(0.0, 1.0, a, endpoint=False))
    if d > 0:
        parts.append(np.linspace(1.0, sustain, d, endpoint=False))
    if s > 0:
        parts.append(np.full(s, sustain))
    if r > 0:
        parts.append(np.linspace(sustain, 0.0, r, endpoint=True))
    env = np.concatenate(parts) if parts else np.zeros(total_samples)
    if len(env) < total_samples:
        env = np.pad(env, (0, total_samples - len(env)))
    return env[:total_samples].astype(np.float32)


def add_note(buffer: np.ndarray, start_sec: float, dur_sec: float, freq: float, amp: float, kind: str):
    start = int(start_sec * SAMPLE_RATE)
    length = int(dur_sec * SAMPLE_RATE)
    end = min(len(buffer), start + length)
    length = end - start
    if length <= 0:
        return
    t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
    env = envelope(length, 0.02, 0.18, 0.55, 0.25)
    if kind == "guitar":
        wave = (
            0.75 * np.sin(2 * math.pi * freq * t)
            + 0.22 * np.sin(2 * math.pi * freq * 2 * t + 0.3)
            + 0.12 * np.sin(2 * math.pi * freq * 3 * t + 0.6)
        )
        wave = np.tanh(wave * 1.7)
    else:
        wave = (
            0.88 * np.sin(2 * math.pi * freq * t)
            + 0.18 * np.sin(2 * math.pi * freq * 2 * t)
        )
        wave = np.tanh(wave * 1.2)
    buffer[start:end] += (wave * env * amp).astype(np.float32)


def make_guitar_loop() -> np.ndarray:
    total = int(SAMPLE_RATE * LENGTH_SECONDS)
    mono = np.zeros(total, dtype=np.float32)
    notes = [
        (0.00, 0.42, 164.81),
        (0.50, 0.38, 196.00),
        (1.00, 0.42, 246.94),
        (1.50, 0.38, 220.00),
        (2.00, 0.42, 164.81),
        (2.50, 0.38, 196.00),
        (3.00, 0.42, 246.94),
        (3.50, 0.38, 293.66),
    ]
    for start, dur, freq in notes:
        add_note(mono, start, dur, freq, 0.6, "guitar")
    stereo = np.column_stack([mono * 0.96, mono * 0.82])
    return stereo


def make_bass_loop() -> np.ndarray:
    total = int(SAMPLE_RATE * LENGTH_SECONDS)
    mono = np.zeros(total, dtype=np.float32)
    notes = [
        (0.00, 0.72, 55.00),
        (1.00, 0.72, 65.41),
        (2.00, 0.72, 73.42),
        (3.00, 0.72, 49.00),
    ]
    for start, dur, freq in notes:
        add_note(mono, start, dur, freq, 0.82, "bass")
    stereo = np.column_stack([mono, mono * 0.95])
    return stereo


def make_kick_loop() -> np.ndarray:
    total = int(SAMPLE_RATE * LENGTH_SECONDS)
    mono = np.zeros(total, dtype=np.float32)
    hits = [0.0, 1.0, 2.0, 3.0]
    hit_len = int(0.28 * SAMPLE_RATE)
    t = np.arange(hit_len, dtype=np.float32) / SAMPLE_RATE
    pitch = np.linspace(120.0, 42.0, hit_len)
    base = np.sin(2 * math.pi * pitch * t)
    env = np.exp(-t * 16.0)
    click = np.random.randn(hit_len).astype(np.float32) * np.exp(-t * 55.0) * 0.08
    hit = (base * env + click).astype(np.float32)
    for start_sec in hits:
        start = int(start_sec * SAMPLE_RATE)
        end = min(total, start + hit_len)
        mono[start:end] += hit[: end - start] * 0.95
    stereo = np.column_stack([mono, mono])
    return stereo


def make_snare_loop() -> np.ndarray:
    total = int(SAMPLE_RATE * LENGTH_SECONDS)
    mono = np.zeros(total, dtype=np.float32)
    hits = [1.0, 3.0]
    hit_len = int(0.24 * SAMPLE_RATE)
    t = np.arange(hit_len, dtype=np.float32) / SAMPLE_RATE
    tone = np.sin(2 * math.pi * 210.0 * t) * np.exp(-t * 22.0) * 0.28
    noise = np.random.randn(hit_len).astype(np.float32)
    noise = np.tanh(noise * 1.6) * np.exp(-t * 18.0) * 0.62
    hit = (tone + noise).astype(np.float32)
    for start_sec in hits:
        start = int(start_sec * SAMPLE_RATE)
        end = min(total, start + hit_len)
        mono[start:end] += hit[: end - start]
    stereo = np.column_stack([mono * 0.94, mono])
    return stereo


def normalize(stereo: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(stereo)))
    if peak > 0.98:
        stereo = stereo * (0.98 / peak)
    return stereo.astype(np.float32)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    loops = {
        "electric_guitar_loop.wav": make_guitar_loop(),
        "bass_loop.wav": make_bass_loop(),
        "kick_drum_loop.wav": make_kick_loop(),
        "snare_drum_loop.wav": make_snare_loop(),
    }
    for name, data in loops.items():
        sf.write(OUT_DIR / name, normalize(data), SAMPLE_RATE)
    print(f"Wrote {len(loops)} loops to {OUT_DIR}")


if __name__ == "__main__":
    main()

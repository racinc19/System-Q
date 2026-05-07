import math
from pathlib import Path

import numpy as np
import soundfile as sf


SAMPLE_RATE = 48000
LENGTH_SECONDS = 8.0
OUT_DIR = Path(__file__).resolve().parent / "band_stems"


def normalize(stereo: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(stereo)))
    if peak > 0.98:
        stereo = stereo * (0.98 / peak)
    return stereo.astype(np.float32)


def env(total: int, attack: float, decay: float, sustain: float, release: float) -> np.ndarray:
    a = int(total * attack)
    d = int(total * decay)
    r = int(total * release)
    s = max(0, total - a - d - r)
    parts = []
    if a > 0:
        parts.append(np.linspace(0.0, 1.0, a, endpoint=False))
    if d > 0:
        parts.append(np.linspace(1.0, sustain, d, endpoint=False))
    if s > 0:
        parts.append(np.full(s, sustain))
    if r > 0:
        parts.append(np.linspace(sustain, 0.0, r, endpoint=True))
    out = np.concatenate(parts) if parts else np.zeros(total)
    if len(out) < total:
        out = np.pad(out, (0, total - len(out)))
    return out[:total].astype(np.float32)


def tone(freq: float, duration: float, level: float = 1.0, harmonics: tuple[float, ...] = (1.0, 0.0, 0.0)) -> np.ndarray:
    length = int(duration * SAMPLE_RATE)
    t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
    wave = np.zeros(length, dtype=np.float32)
    for idx, amp in enumerate(harmonics, start=1):
        if amp != 0.0:
            wave += np.sin(2 * math.pi * freq * idx * t).astype(np.float32) * amp
    peak = float(np.max(np.abs(wave)))
    if peak > 0:
        wave /= peak
    return wave * level


def place(buf: np.ndarray, start_sec: float, src: np.ndarray):
    start = int(start_sec * SAMPLE_RATE)
    end = min(len(buf), start + len(src))
    if end <= start:
        return
    buf[start:end] += src[: end - start]


def stereoize(mono: np.ndarray, left: float = 1.0, right: float = 1.0) -> np.ndarray:
    return np.column_stack([mono * left, mono * right]).astype(np.float32)


def make_kick() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    for beat in range(0, 8, 1):
        start = beat * 1.0
        hit_len = int(0.22 * SAMPLE_RATE)
        t = np.arange(hit_len, dtype=np.float32) / SAMPLE_RATE
        pitch = np.linspace(110.0, 42.0, hit_len)
        body = np.sin(2 * math.pi * pitch * t) * np.exp(-t * 14.0)
        click = np.random.randn(hit_len).astype(np.float32) * np.exp(-t * 65.0) * 0.06
        hit = (body + click) * 0.95
        place(mono, start, hit.astype(np.float32))
    return stereoize(mono, 1.0, 1.0)


def make_snare() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    for beat in [1.0, 3.0, 5.0, 7.0]:
        hit_len = int(0.24 * SAMPLE_RATE)
        t = np.arange(hit_len, dtype=np.float32) / SAMPLE_RATE
        body = np.sin(2 * math.pi * 210.0 * t) * np.exp(-t * 22.0) * 0.24
        noise = np.tanh(np.random.randn(hit_len).astype(np.float32) * 1.8) * np.exp(-t * 18.0) * 0.7
        place(mono, beat, (body + noise).astype(np.float32))
    return stereoize(mono, 0.95, 1.0)


def make_overheads() -> tuple[np.ndarray, np.ndarray]:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    left = np.zeros(total, dtype=np.float32)
    right = np.zeros(total, dtype=np.float32)
    for beat in np.arange(0.0, 8.0, 0.5):
        hit_len = int(0.14 * SAMPLE_RATE)
        t = np.arange(hit_len, dtype=np.float32) / SAMPLE_RATE
        splash = np.tanh(np.random.randn(hit_len).astype(np.float32) * 1.2) * np.exp(-t * 12.0) * 0.18
        pan = 0.35 if int(beat * 2) % 2 == 0 else 0.85
        place(left, float(beat), splash * (1.1 - pan))
        place(right, float(beat), splash * pan)
    return stereoize(left, 1.0, 0.0), stereoize(right, 0.0, 1.0)


def make_bass() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    notes = [(0.0, 55.0), (2.0, 65.41), (4.0, 73.42), (6.0, 49.0)]
    for start, freq in notes:
        src = tone(freq, 1.4, 0.82, (1.0, 0.20, 0.10))
        src *= env(len(src), 0.02, 0.14, 0.72, 0.18)
        place(mono, start, np.tanh(src * 1.15).astype(np.float32))
    return stereoize(mono, 1.0, 0.96)


def make_guitar(side: str) -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    freqs = [164.81, 196.00, 246.94, 220.00, 293.66, 246.94, 196.00, 164.81]
    for idx, freq in enumerate(freqs):
        src = tone(freq, 0.42, 0.64, (1.0, 0.25, 0.16))
        src *= env(len(src), 0.02, 0.18, 0.62, 0.20)
        src = np.tanh(src * 1.7).astype(np.float32)
        place(mono, idx * 0.9, src)
    if side == "L":
        return stereoize(mono, 1.0, 0.35)
    return stereoize(mono, 0.35, 1.0)


def make_keys(side: str) -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    chords = [
        (0.0, [261.63, 329.63, 392.00]),
        (2.0, [293.66, 369.99, 440.00]),
        (4.0, [246.94, 311.13, 392.00]),
        (6.0, [220.00, 293.66, 369.99]),
    ]
    for start, chord in chords:
        length = int(1.6 * SAMPLE_RATE)
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        wave = np.zeros(length, dtype=np.float32)
        for freq in chord:
            wave += (0.7 * np.sin(2 * math.pi * freq * t) + 0.22 * np.sin(2 * math.pi * freq * 2 * t)).astype(np.float32)
        wave = np.tanh(wave * 0.95).astype(np.float32)
        wave *= env(length, 0.03, 0.22, 0.74, 0.22)
        place(mono, start, wave * 0.42)
    if side == "L":
        return stereoize(mono, 1.0, 0.48)
    return stereoize(mono, 0.48, 1.0)


def make_vocal() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    melody = [(0.5, 220.0), (1.5, 246.94), (2.5, 261.63), (4.5, 293.66), (5.5, 329.63), (6.5, 293.66)]
    for start, freq in melody:
        length = int(0.55 * SAMPLE_RATE)
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        vibrato = 1.0 + 0.01 * np.sin(2 * math.pi * 5.2 * t)
        base = np.sin(2 * math.pi * freq * vibrato * t)
        form1 = np.sin(2 * math.pi * freq * 2.0 * t) * 0.32
        form2 = np.sin(2 * math.pi * freq * 3.1 * t) * 0.12
        wave = np.tanh((base + form1 + form2) * 1.15).astype(np.float32)
        wave *= env(length, 0.04, 0.12, 0.78, 0.16)
        place(mono, start, wave * 0.45)
    return stereoize(mono, 0.95, 1.0)


def make_bgv() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    notes = [(1.5, 329.63), (3.5, 392.0), (5.5, 369.99), (7.0, 329.63)]
    for start, freq in notes:
        src = tone(freq, 0.9, 0.35, (1.0, 0.18, 0.08))
        src *= env(len(src), 0.06, 0.18, 0.68, 0.22)
        place(mono, start, src)
    return stereoize(mono, 0.78, 0.88)


def make_perc() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    for beat in np.arange(0.25, 8.0, 0.5):
        length = int(0.08 * SAMPLE_RATE)
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        hit = np.tanh(np.random.randn(length).astype(np.float32) * 1.8) * np.exp(-t * 34.0) * 0.16
        place(mono, float(beat), hit)
    return stereoize(mono, 0.85, 0.95)


def make_room() -> np.ndarray:
    total = int(LENGTH_SECONDS * SAMPLE_RATE)
    mono = np.zeros(total, dtype=np.float32)
    noise = np.tanh(np.random.randn(total).astype(np.float32) * 0.22) * 0.04
    mono += noise
    return stereoize(mono, 1.0, 1.0)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stems = {
        "01_kick.wav": make_kick(),
        "02_snare.wav": make_snare(),
        "03_oh_l.wav": make_overheads()[0],
        "04_oh_r.wav": make_overheads()[1],
        "05_bass.wav": make_bass(),
        "06_gtr_l.wav": make_guitar("L"),
        "07_gtr_r.wav": make_guitar("R"),
        "08_keys_l.wav": make_keys("L"),
        "09_keys_r.wav": make_keys("R"),
        "10_vocal.wav": make_vocal(),
        "11_bgv.wav": make_bgv(),
        "12_perc.wav": make_perc(),
    }
    for name, data in stems.items():
        sf.write(OUT_DIR / name, normalize(data), SAMPLE_RATE)
    sf.write(OUT_DIR / "13_room.wav", normalize(make_room()), SAMPLE_RATE)
    print(f"Wrote {len(stems) + 1} stems to {OUT_DIR}")


if __name__ == "__main__":
    main()

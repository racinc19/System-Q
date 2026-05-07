#!/usr/bin/env python3
"""Show how much energy a typical kick drum actually carries in each octave.
If most of the energy lives below 200 Hz, then sweeping a working LPF from
22 kHz down to 4 kHz removes nothing audible — there is nothing there to remove.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 3:
        n_samples = len(raw) // 3
        out = np.empty(n_samples, dtype=np.int32)
        for i in range(n_samples):
            b = raw[i * 3 : i * 3 + 3]
            v = b[0] | (b[1] << 8) | (b[2] << 16)
            if v & 0x800000:
                v -= 1 << 24
            out[i] = v
        data = out.astype(np.float32) / (1 << 23)
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / (1 << 31)
    else:
        raise ValueError(f"unsupported sample width: {sw}")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def main() -> int:
    software = Path(__file__).resolve().parent
    repo = software.parent
    kick_candidates = (
        list(repo.rglob("01_kick*.wav"))
        + list(repo.rglob("**/band_stems/01_kick.wav"))
        + list(repo.rglob("**/lewitt_eyes/01_kick.wav"))
    )
    # Prefer the source stems (longest, untouched) over Evidence renders.
    kick_candidates = [p for p in kick_candidates if "Evidence" not in p.parts] or kick_candidates
    if not kick_candidates:
        print("FAIL no kick wav found")
        return 1
    path = kick_candidates[0]
    print(f"Reading: {path}")
    sig, sr = read_wav(path)
    n = len(sig)
    print(f"  duration: {n / sr:.2f} s   sr: {sr} Hz   peak: {np.max(np.abs(sig)):.3f}")

    # Loud chunk — a typical kick hit. Take the windowed loudest segment.
    win = int(0.4 * sr)
    if n > win:
        # Pick the window with the highest RMS so we're analyzing an actual hit, not silence.
        rms = np.sqrt(np.convolve(sig.astype(np.float64) ** 2, np.ones(win) / win, mode="valid"))
        center = int(np.argmax(rms))
        sig = sig[center : center + win]

    # Per-octave RMS via FFT.
    spec = np.fft.rfft(sig.astype(np.float64))
    freqs = np.fft.rfftfreq(len(sig), d=1.0 / sr)
    bands = [
        ("20-40 Hz",     20.0,    40.0),
        ("40-80",        40.0,    80.0),
        ("80-160",       80.0,   160.0),
        ("160-320",     160.0,   320.0),
        ("320-640",     320.0,   640.0),
        ("640-1280",    640.0,  1280.0),
        ("1.28k-2.56k",1280.0,  2560.0),
        ("2.56k-5.12k",2560.0,  5120.0),
        ("5.12k-10.24k",5120.0,10240.0),
        ("10.24k-20k",10240.0, 20000.0),
    ]
    total_pwr = float(np.sum(np.abs(spec) ** 2))
    print()
    print(f"  band              %   energy   bar")
    cumulative = 0.0
    for name, lo, hi in bands:
        idx = (freqs >= lo) & (freqs < hi)
        pwr = float(np.sum(np.abs(spec[idx]) ** 2))
        pct = 100.0 * pwr / max(total_pwr, 1e-12)
        cumulative += pct
        bar = "#" * int(round(pct / 2.0))
        print(f"  {name:<14}  {pct:5.2f}%   {bar}")
    print()
    print("  reading: percent of the kick's energy in each octave")
    print("  >>> if you set LPF 5 kHz on this kick, you cut content >5 kHz,")
    print("      which is the bottom of that table. There is almost nothing")
    print("      there, so you hear no change. To AUDIBLY cut a kick drum")
    print("      with an LPF, you need cutoff below ~500 Hz where the energy lives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

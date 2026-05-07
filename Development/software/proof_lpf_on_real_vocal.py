#!/usr/bin/env python3
"""Render a real vocal track through the production ConsoleEngine LPF at
various cutoffs. Output:
  - Evidence/lpf-real-vocal/vocal_dry.wav
  - Evidence/lpf-real-vocal/vocal_lpf_8000hz.wav
  - Evidence/lpf-real-vocal/vocal_lpf_4000hz.wav
  - Evidence/lpf-real-vocal/vocal_lpf_2000hz.wav
  - Evidence/lpf-real-vocal/vocal_lpf_1000hz.wav
  - Evidence/lpf-real-vocal/vocal_lpf_500hz.wav

Per-octave RMS printed for each. If the LPF works on the vocal, the
high-octave RMS values will collapse as the cutoff drops past them.
If they don't change, the engine's LPF path is dead and we have a real bug.
"""
from __future__ import annotations

import struct
import sys
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
        nb = len(raw) // 3
        out = np.empty(nb, dtype=np.int32)
        for i in range(nb):
            b = raw[i * 3 : i * 3 + 3]
            v = b[0] | (b[1] << 8) | (b[2] << 16)
            if v & 0x800000:
                v -= 1 << 24
            out[i] = v
        data = out.astype(np.float32) / (1 << 23)
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / (1 << 31)
    else:
        raise ValueError(f"unsupported sw {sw}")
    if ch > 1:
        data = data.reshape(-1, ch)
    else:
        data = np.stack([data, data], axis=1)
    return data.astype(np.float32), sr


def write_wav_16(path: Path, sig: np.ndarray, sr: int) -> None:
    sig = np.clip(sig, -1.0, 1.0)
    pcm = (sig * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def per_octave_rms(sig: np.ndarray, sr: int) -> dict[str, float]:
    mono = sig.mean(axis=1).astype(np.float64)
    spec = np.fft.rfft(mono)
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
    bands = [
        ("80-160",       80.0,   160.0),
        ("160-320",     160.0,   320.0),
        ("320-640",     320.0,   640.0),
        ("640-1.28k",   640.0,  1280.0),
        ("1.28k-2.56k",1280.0,  2560.0),
        ("2.56k-5.12k",2560.0,  5120.0),
        ("5.12k-10.24k",5120.0,10240.0),
        ("10.24k-20k",10240.0, 20000.0),
    ]
    out = {}
    for name, lo, hi in bands:
        idx = (freqs >= lo) & (freqs < hi)
        rms = float(np.sqrt(np.mean(np.abs(spec[idx]) ** 2)) / max(1, idx.sum()))
        out[name] = rms
    return out


def main() -> int:
    software = Path(__file__).resolve().parent
    repo = software.parent
    sys.path.insert(0, str(software))

    import system_q_console as sq

    out_dir = repo / "Evidence" / "lpf-real-vocal"
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = list(repo.rglob("**/03_vocal_clean.wav")) + list(
        repo.rglob("**/10_vocal.wav")
    )
    candidates = [p for p in candidates if "Evidence" not in p.parts]
    if not candidates:
        print("FAIL no vocal wav found", flush=True)
        return 1
    src = candidates[0]
    print(f"Source: {src}", flush=True)

    sig, sr = read_wav(src)
    print(f"  duration: {len(sig) / sr:.2f} s   sr: {sr}   peak: {np.max(np.abs(sig)):.3f}", flush=True)

    # Boot a transient ConsoleEngine without opening an audio device.
    import threading
    engine = sq.ConsoleEngine.__new__(sq.ConsoleEngine)
    engine._lock = threading.Lock()
    engine._butter_sos_cache = {}
    engine.master_channel = sq.ChannelState(name="MASTER", path=Path("master"))
    ch = sq.ChannelState(name="vocal", path=src)
    ch.gain = 1.0
    ch.audio = sig

    block_size = sq.BLOCK_SIZE
    n = len(sig)

    def render(lpf_on: bool, lpf_hz: float) -> np.ndarray:
        ch.pre_enabled = bool(lpf_on)
        ch.lpf_enabled = bool(lpf_on)
        ch.lpf_hz = float(lpf_hz)
        ch.lpf_state = None
        ch.lpf_state_cutoff = 0.0
        out = np.empty_like(sig)
        pos = 0
        while pos < n:
            blk_n = min(block_size, n - pos)
            blk = sig[pos:pos + blk_n]
            y = engine._process_channel(ch, blk)
            out[pos:pos + blk_n] = y
            pos += blk_n
        return out

    # Dry baseline.
    dry = render(False, 22000.0)
    write_wav_16(out_dir / "vocal_dry.wav", dry, sr)
    dry_rms = per_octave_rms(dry, sr)
    print()
    print(f"  cutoff   80-160  160-320  320-640  640-1k  1k-2k   2k-5k   5k-10k  10k-20k", flush=True)
    print(f"  -------- ------- -------- -------- ------- ------- ------- ------- --------", flush=True)
    def fmt_row(label, rms):
        return f"  {label:<8} " + " ".join(f"{rms[k]:7.5f}" for k in [
            "80-160","160-320","320-640","640-1.28k","1.28k-2.56k","2.56k-5.12k","5.12k-10.24k","10.24k-20k"
        ])
    print(fmt_row("DRY", dry_rms))
    cutoffs = [8000.0, 4000.0, 2000.0, 1000.0, 500.0]
    for hz in cutoffs:
        y = render(True, hz)
        write_wav_16(out_dir / f"vocal_lpf_{int(hz)}hz.wav", y, sr)
        r = per_octave_rms(y, sr)
        print(fmt_row(f"LPF{int(hz)}", r))
    print()
    print("  Drop expected: each LPF row should show columns ABOVE its cutoff collapse.", flush=True)
    print(f"  If a row's high-frequency columns DON'T change vs DRY, the engine's", flush=True)
    print(f"  LPF path is broken. Otherwise the DSP is doing its job.", flush=True)
    print()
    print(f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}", flush=True)
    print(f"WAVs: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

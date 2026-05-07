#!/usr/bin/env python3
"""End-to-end DSP proof: feed a known multi-tone signal through ConsoleEngine
and compare RMS of LF (200 Hz) vs HF (8 kHz) tones with the LPF off vs at
several cutoffs. If the LPF is wired correctly the HF tone amplitude must
collapse as the cutoff drops below 8 kHz, while the LF tone stays roughly
constant.

Prints a pass/fail per cutoff and writes `lpf_engine_proof.csv` to the
``Evidence/polar-lpf-hpf-stopband/`` folder for later review.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    software = Path(__file__).resolve().parent
    repo = software.parent
    out_dir = repo / "Evidence" / "polar-lpf-hpf-stopband"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import system_q_console as sq

    sr = sq.SAMPLE_RATE
    block = sq.BLOCK_SIZE
    duration_sec = 1.5
    n_total = int(sr * duration_sec)

    # Two-tone signal: 200 Hz (should pass under any LPF >= 400 Hz) and 8000 Hz
    # (should attenuate below 4 kHz LPF).
    t = np.arange(n_total, dtype=np.float64) / sr
    lf_amp = 0.40
    hf_amp = 0.40
    lf = lf_amp * np.sin(2.0 * math.pi * 200.0 * t)
    hf = hf_amp * np.sin(2.0 * math.pi * 8000.0 * t)
    mono = (lf + hf).astype(np.float32)
    stereo = np.stack([mono, mono], axis=1)

    def goertzel_rms(sig: np.ndarray, freq_hz: float) -> float:
        x = sig.astype(np.float64)
        n = len(x)
        k = int(round(freq_hz * n / sr))
        omega = 2.0 * math.pi * k / n
        coeff = 2.0 * math.cos(omega)
        s_prev = 0.0
        s_prev2 = 0.0
        for v in x:
            s = v + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s
        re = s_prev - s_prev2 * math.cos(omega)
        im = s_prev2 * math.sin(omega)
        # Goertzel returns (n/2) * amplitude squared in the (re,im) magnitude.
        amp = 2.0 * math.sqrt(re * re + im * im) / n
        return amp / math.sqrt(2.0)  # convert peak amp -> RMS

    # Build a transient ConsoleEngine that doesn't open a real audio stream.
    engine = sq.ConsoleEngine.__new__(sq.ConsoleEngine)
    engine._lock = __import__("threading").Lock()
    engine._butter_sos_cache = {}
    engine.master_channel = sq.ChannelState(name="MASTER", path=Path("master"))
    ch = sq.ChannelState(name="probe", path=Path("probe"))
    ch.gain = 1.0

    def render(lpf_enabled: bool, lpf_hz: float) -> np.ndarray:
        ch.pre_enabled = bool(lpf_enabled)
        ch.lpf_enabled = bool(lpf_enabled)
        ch.lpf_hz = float(lpf_hz)
        ch.lpf_state = None
        ch.lpf_state_cutoff = 0.0
        out = np.empty_like(stereo)
        pos = 0
        while pos < n_total:
            n = min(block, n_total - pos)
            blk = stereo[pos:pos + n]
            y = engine._process_channel(ch, blk)
            out[pos:pos + n] = y
            pos += n
        # Drop initial 200 ms (filter warmup) for steady-state measurement.
        warmup = int(0.20 * sr)
        return out[warmup:, 0].astype(np.float32)

    # Reference (LPF bypassed).
    dry = render(False, 22000.0)
    dry_lf = goertzel_rms(dry, 200.0)
    dry_hf = goertzel_rms(dry, 8000.0)
    print(f"DRY                         200 Hz RMS = {dry_lf:.4f}   8 kHz RMS = {dry_hf:.4f}")

    cutoffs = [22000.0, 12000.0, 6000.0, 4000.0, 2000.0, 1000.0, 500.0, 250.0]
    rows = ["cutoff_hz,200hz_rms,8khz_rms,200hz_db_vs_dry,8khz_db_vs_dry,result"]
    pass_count = 0
    fail_count = 0
    for hz in cutoffs:
        y = render(True, hz)
        lf = goertzel_rms(y, 200.0)
        hf = goertzel_rms(y, 8000.0)
        lf_db = 20.0 * math.log10(max(lf, 1e-9) / max(dry_lf, 1e-9))
        hf_db = 20.0 * math.log10(max(hf, 1e-9) / max(dry_hf, 1e-9))
        # Acceptance: 200 Hz never drops more than -1.5 dB for cutoffs >= 500 Hz.
        # 8 kHz must drop at least -3 dB once cutoff falls to 4 kHz, and >= -18 dB at 1 kHz.
        ok = True
        if hz >= 500.0 and lf_db < -1.5:
            ok = False
        if hz <= 4000.0 and hf_db > -3.0:
            ok = False
        if hz <= 1000.0 and hf_db > -18.0:
            ok = False
        # At 22 kHz cutoff (wide open) both bands should be intact.
        if hz >= 20000.0 and (lf_db < -1.0 or hf_db < -1.0):
            ok = False
        flag = "PASS" if ok else "FAIL"
        if ok: pass_count += 1
        else:  fail_count += 1
        print(
            f"LPF cutoff={hz:>7.0f} Hz   "
            f"200 Hz: {lf:.4f} ({lf_db:+6.2f} dB)   "
            f"8 kHz: {hf:.4f} ({hf_db:+6.2f} dB)   {flag}"
        )
        rows.append(f"{hz:.0f},{lf:.6f},{hf:.6f},{lf_db:.3f},{hf_db:.3f},{flag}")

    csv = out_dir / "lpf_engine_proof.csv"
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\nWROTE  {csv}")
    print(f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}")
    print(f"summary: pass={pass_count} fail={fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

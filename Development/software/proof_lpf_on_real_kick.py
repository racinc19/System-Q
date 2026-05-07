#!/usr/bin/env python3
"""Render the actual ``01_kick.wav`` through ``ConsoleEngine._process_channel``
at multiple LPF cutoffs and save side-by-side WAVs the operator can listen to.

The user reported "engaging LPF at 6461 Hz on the kick — no audible
difference". This script proves both:

    (a) The LPF DSP is wired correctly: at low cutoffs (~150–400 Hz) the
        kick's transient click is removed, only sub/body remains.
    (b) At high cutoffs (~6 kHz) a kick has almost nothing to attenuate
        because its energy lives below the cutoff. So an LPF at 6461 Hz
        on a kick *should* sound nearly identical to dry. That's how
        LPFs work — not a bug.

Outputs to ``../Evidence/lpf-real-kick/``:

    kick_dry.wav                 # baseline, no preamp processing
    kick_lpf_6461hz.wav          # operator's setting from the screenshot
    kick_lpf_1500hz.wav          # mid sweep, top end going dark
    kick_lpf_400hz.wav           # click gone, body + sub
    kick_lpf_150hz.wav           # only sub thump
    spectrum_summary.txt         # per-octave RMS for each render

Run from ``software/``::

    py -3 proof_lpf_on_real_kick.py
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path


def _read_wav_pcm16(path: Path) -> tuple["np.ndarray", int]:
    """Decode 16/24/32-bit signed PCM WAV into float32 stereo in [-1, 1]."""
    import numpy as np

    with wave.open(str(path), "rb") as wf:
        n_ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sw == 2:
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 3:
        # 24-bit little-endian signed PCM: build a 4-byte-per-sample int32 view
        # by sign-extending the high byte, then scale.
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        i32 = (b[:, 0].astype(np.int32)
               | (b[:, 1].astype(np.int32) << 8)
               | (b[:, 2].astype(np.int32) << 16))
        sign = (i32 & 0x800000).astype(np.int32)
        i32 -= sign << 1  # sign-extend if bit 23 is set
        pcm = i32.astype(np.float32) / float(1 << 23)
    elif sw == 4:
        pcm = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise SystemExit(f"unsupported sampwidth={sw}")
    if n_ch == 1:
        stereo = np.stack([pcm, pcm], axis=1)
    else:
        stereo = pcm.reshape(-1, n_ch)[:, :2]
    return stereo, sr


def _write_wav_pcm16(path: Path, stereo_f32: "np.ndarray", sr: int) -> None:
    import numpy as np

    clipped = np.clip(stereo_f32, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _octave_rms(stereo_f32: "np.ndarray", sr: int) -> dict[str, float]:
    """RMS per standard ISO octave band (mono-summed)."""
    import numpy as np

    mono = stereo_f32.mean(axis=1).astype(np.float64)
    n = len(mono)
    if n < 1024:
        return {}
    spec = np.fft.rfft(mono * np.hanning(n))
    mag2 = (np.abs(spec) ** 2).astype(np.float64)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    centers = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
    out: dict[str, float] = {}
    for fc in centers:
        lo = fc / (2 ** 0.5)
        hi = fc * (2 ** 0.5)
        sel = (freqs >= lo) & (freqs < hi)
        if not sel.any():
            out[f"{fc:>6.0f}Hz"] = 0.0
            continue
        band_energy = float(np.sqrt(mag2[sel].sum() / max(1, n)))
        out[f"{fc:>6.0f}Hz"] = band_energy
    return out


def main() -> int:
    software = Path(__file__).resolve().parent
    repo = software.parent
    out_dir = repo / "Evidence" / "lpf-real-kick"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import numpy as np

    import system_q_console as sq

    kick_path = software / "tracks" / "lewitt_eyes" / "01_kick.wav"
    if not kick_path.exists():
        print(f"missing: {kick_path}", flush=True)
        return 2

    stereo, sr = _read_wav_pcm16(kick_path)
    if sr != sq.SAMPLE_RATE:
        print(
            f"warn: file SR={sr} differs from engine SAMPLE_RATE={sq.SAMPLE_RATE}; "
            "DSP filter cutoff will be relative to engine SR",
            flush=True,
        )

    # Trim to the first ~6 seconds so the listening tests are short and bounded.
    take = min(len(stereo), sq.SAMPLE_RATE * 6)
    stereo = stereo[:take]

    engine = sq.ConsoleEngine()
    ch = engine.channels[0]
    # Cold path so only the LPF acts on the audio.
    ch.harmonics_enabled = False
    ch.eq_enabled = False
    ch.tone_enabled = False
    ch.gate_enabled = False
    ch.gate_band_enabled = False
    ch.comp_enabled = False
    ch.comp_band_enabled = False
    ch.tube = False
    ch.gain = 1.0
    ch.pan = 0.0
    ch.phase = False

    block_n = sq.BLOCK_SIZE

    def render(label: str, *, lpf_on: bool, lpf_hz: float) -> tuple[Path, dict[str, float]]:
        ch.pre_enabled = bool(lpf_on)
        ch.lpf_enabled = bool(lpf_on)
        ch.hpf_enabled = False
        ch.lpf_hz = float(lpf_hz)
        out_chunks: list[np.ndarray] = []
        for start in range(0, len(stereo), block_n):
            blk = stereo[start : start + block_n].astype(np.float32, copy=True)
            if len(blk) < block_n:
                pad = np.zeros((block_n - len(blk), 2), dtype=np.float32)
                blk = np.vstack([blk, pad])
                trim = block_n - (block_n - len(stereo[start:start + block_n]))
            else:
                trim = block_n
            processed = engine._process_channel(ch, blk)
            out_chunks.append(processed[:trim])
        rendered = np.concatenate(out_chunks, axis=0)[: len(stereo)]
        png = out_dir / f"{label}.wav"
        _write_wav_pcm16(png, rendered, sr)
        return png, _octave_rms(rendered, sr)

    renders = [
        ("kick_dry",          False,    0.0),
        ("kick_lpf_6461hz",   True,  6461.0),
        ("kick_lpf_1500hz",   True,  1500.0),
        ("kick_lpf_400hz",    True,   400.0),
        ("kick_lpf_150hz",    True,   150.0),
    ]
    summary: dict[str, dict[str, float]] = {}
    for label, on, hz in renders:
        path, oc = render(label, lpf_on=on, lpf_hz=hz)
        summary[label] = oc
        print(f"WROTE  {path}  size={path.stat().st_size:>10} bytes", flush=True)

    bands = list(summary["kick_dry"].keys())
    header = "band       | " + " | ".join(f"{lab:>15}" for lab, *_ in renders)
    print("", flush=True)
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for b in bands:
        cells = []
        for lab, *_ in renders:
            v = summary[lab].get(b, 0.0)
            cells.append(f"{v:>15.5f}")
        print(f"{b} | {' | '.join(cells)}", flush=True)

    # Show how much energy the LPF removed *relative* to dry. A correct LPF
    # makes the high bands collapse but barely touches the low bands.
    print("", flush=True)
    print("ratio vs dry (1.00 = unchanged, 0.00 = killed):", flush=True)
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for b in bands:
        dry = summary["kick_dry"].get(b, 0.0)
        cells = []
        for lab, *_ in renders:
            v = summary[lab].get(b, 0.0)
            ratio = (v / dry) if dry > 1e-9 else 0.0
            cells.append(f"{ratio:>15.3f}")
        print(f"{b} | {' | '.join(cells)}", flush=True)

    txt = out_dir / "spectrum_summary.txt"
    with txt.open("w", encoding="utf-8") as fh:
        fh.write(header + "\n")
        for b in bands:
            cells = " | ".join(
                f"{summary[lab].get(b, 0.0):>15.5f}" for lab, *_ in renders
            )
            fh.write(f"{b} | {cells}\n")

    print("", flush=True)
    print(f"WAV outputs: {out_dir}", flush=True)
    print(
        "listen to kick_dry.wav vs kick_lpf_6461hz.wav  -> should sound nearly identical (kick has no top above 6 kHz to remove)",
        flush=True,
    )
    print(
        "listen to kick_dry.wav vs kick_lpf_400hz.wav   -> click gone, only thump (proves the LPF actually works on the file)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

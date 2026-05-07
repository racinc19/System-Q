#!/usr/bin/env python3
"""Single-command LPF verification (no user interaction required).

Runs four checks and exits non-zero on any failure:
  1) Repository verifier (`verify_system_q.py`)
  2) DSP attenuation check through production `_process_channel`
  3) UI/state toggle check (LPF press engages PRE + audible starting cutoff)
  4) Focus polar paint check (LPF cutoff text reflects requested values)

Writes a plain-text report to:
  Evidence/lpf-end-to-end/lpf_end_to_end_report.txt
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np


def _goertzel_rms(sig: np.ndarray, freq_hz: float, sr: int) -> float:
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
    amp = 2.0 * math.sqrt(re * re + im * im) / n
    return amp / math.sqrt(2.0)


def _db_ratio(v: float, ref: float) -> float:
    return 20.0 * math.log10(max(v, 1e-12) / max(ref, 1e-12))


def run_verify_script(software_dir: Path) -> tuple[bool, str]:
    cmd = [sys.executable, "verify_system_q.py"]
    proc = subprocess.run(
        cmd,
        cwd=str(software_dir),
        capture_output=True,
        text=True,
    )
    merged = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    tail = "\n".join([ln for ln in merged.strip().splitlines()[-8:] if ln.strip()])
    ok = proc.returncode == 0
    return ok, f"verify_system_q.py return_code={proc.returncode}\n{tail}\n"


def run_dsp_check(sq) -> tuple[bool, str]:
    sr = int(sq.SAMPLE_RATE)
    n = int(sr * 1.5)
    t = np.arange(n, dtype=np.float64) / float(sr)
    mono = (0.40 * np.sin(2.0 * math.pi * 200.0 * t) + 0.40 * np.sin(2.0 * math.pi * 8000.0 * t)).astype(np.float32)
    stereo = np.stack([mono, mono], axis=1)

    engine = sq.ConsoleEngine.__new__(sq.ConsoleEngine)
    engine._lock = threading.Lock()
    engine._butter_sos_cache = {}
    engine.master_channel = sq.ChannelState(name="MASTER", path=Path("master"))
    ch = sq.ChannelState(name="probe", path=Path("probe"))
    ch.gain = 1.0

    def render(pre_on: bool, lpf_on: bool, cutoff: float) -> np.ndarray:
        ch.pre_enabled = bool(pre_on)
        ch.lpf_enabled = bool(lpf_on)
        ch.lpf_hz = float(cutoff)
        ch.hpf_enabled = False
        ch.lpf_state = None
        ch.hpf_state = None
        out = np.empty_like(stereo)
        pos = 0
        bs = int(sq.BLOCK_SIZE)
        while pos < n:
            take = min(bs, n - pos)
            out[pos : pos + take] = engine._process_channel(ch, stereo[pos : pos + take])
            pos += take
        return out[int(0.20 * sr) :, 0].astype(np.float32)

    dry = render(True, False, 22000.0)
    wet = render(True, True, 1000.0)
    dry_lf = _goertzel_rms(dry, 200.0, sr)
    dry_hf = _goertzel_rms(dry, 8000.0, sr)
    wet_lf = _goertzel_rms(wet, 200.0, sr)
    wet_hf = _goertzel_rms(wet, 8000.0, sr)
    lf_db = _db_ratio(wet_lf, dry_lf)
    hf_db = _db_ratio(wet_hf, dry_hf)
    # PRE master bypassed but LPF row on — must still kill highs (used to be gated on pre_enabled).
    wet_nopre = render(False, True, 1000.0)
    hf_nopre = _db_ratio(_goertzel_rms(wet_nopre, 8000.0, sr), dry_hf)

    ok = (lf_db > -1.5) and (hf_db < -18.0) and (hf_nopre < -18.0)
    msg = (
        "DSP check:\n"
        f"  200 Hz delta: {lf_db:+.2f} dB (expect > -1.5 dB)\n"
        f"  8 kHz delta : {hf_db:+.2f} dB (expect < -18 dB)\n"
        f"  8 kHz delta (PRE bypassed, LPF on): {hf_nopre:+.2f} dB (expect < -18 dB)\n"
    )
    return ok, msg


def run_ui_state_and_paint_check(sq) -> tuple[bool, str]:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    app = sq.ConsoleApp(root, startup_play=False)
    root.update_idletasks()
    root.update()

    ch = app._current_channel()
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    pre_params = app._STAGE_GRID[pre_col][2]
    lpf_row = pre_params.index("LPF")

    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.selected_stage_key = "pre"
    app.editor_stage_col = pre_col
    app.editor_param_row = lpf_row
    app.editor_unified_header_focus = False

    with app.engine._lock:
        ch.pre_enabled = False
        ch.lpf_enabled = False
        ch.hpf_enabled = False
        ch.lpf_hz = float(sq.POL_HIGH_HZ)
        ch.band_levels = np.linspace(0.8, 0.10, len(ch.band_levels)).astype(ch.band_levels.dtype)

    # Press LPF cell -> must enable LPF + auto-enable PRE (cutoff unchanged — no snap).
    app._press_unified_editor_cell()
    root.update_idletasks()
    root.update()

    with app.engine._lock:
        pre_enabled = bool(ch.pre_enabled)
        lpf_enabled = bool(ch.lpf_enabled)
        lpf_after_press = float(ch.lpf_hz)

    # Twist down once (axis -1) should lower LPF Hz in natural-direction build.
    app._adjust_unified_editor_cell(axis_value=-1.0)
    root.update_idletasks()
    root.update()
    with app.engine._lock:
        lpf_after_down = float(ch.lpf_hz)

    # Paint text check for two cutoffs.
    def draw_texts_for(hz: float) -> list[str]:
        with app.engine._lock:
            ch.pre_enabled = True
            ch.lpf_enabled = True
            ch.lpf_hz = float(hz)
        app._draw_focus_to(app.focus_canvas)
        root.update_idletasks()
        root.update()
        texts: list[str] = []
        for iid in app.focus_canvas.find_all():
            if app.focus_canvas.type(iid) == "text":
                texts.append(str(app.focus_canvas.itemcget(iid, "text")))
        return texts

    texts_500 = draw_texts_for(500.0)
    texts_22k = draw_texts_for(float(sq.POL_HIGH_HZ))

    root.destroy()

    has_500 = any("LPF 500 Hz cut" in t for t in texts_500)
    has_22k = any("LPF 22.00 kHz cut" in t for t in texts_22k)
    wide_open = abs(lpf_after_press - float(sq.POL_HIGH_HZ)) < 2.0
    ok = (
        pre_enabled
        and lpf_enabled
        and wide_open
        and (lpf_after_down < lpf_after_press)
        and has_500
        and has_22k
    )
    msg = (
        "UI/state/paint check:\n"
        f"  pre_enabled after LPF press: {pre_enabled}\n"
        f"  lpf_enabled after LPF press: {lpf_enabled}\n"
        f"  lpf_hz after LPF press      : {lpf_after_press:.1f} Hz (expect ~{float(sq.POL_HIGH_HZ):.0f}, no snap)\n"
        f"  lpf_hz after one twist-down : {lpf_after_down:.1f} Hz (expect lower)\n"
        f"  focus text includes 'LPF 500 Hz cut'    : {has_500}\n"
        f"  focus text includes 'LPF 22.00 kHz cut' : {has_22k}\n"
    )
    return ok, msg


def main() -> int:
    software_dir = Path(__file__).resolve().parent
    repo = software_dir.parent
    evidence_dir = repo / "Evidence" / "lpf-end-to-end"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = evidence_dir / "lpf_end_to_end_report.txt"

    sys.path.insert(0, str(software_dir))
    import system_q_console as sq

    checks: list[tuple[str, bool, str]] = []

    ok_v, msg_v = run_verify_script(software_dir)
    checks.append(("verify_system_q", ok_v, msg_v))

    ok_dsp, msg_dsp = run_dsp_check(sq)
    checks.append(("dsp_attenuation", ok_dsp, msg_dsp))

    ok_ui, msg_ui = run_ui_state_and_paint_check(sq)
    checks.append(("ui_state_and_paint", ok_ui, msg_ui))

    lines: list[str] = []
    lines.append(f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}")
    lines.append(f"SCRIPT={Path(__file__).name}")
    lines.append("")

    failed = []
    for name, ok, msg in checks:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        lines.append(msg.rstrip())
        lines.append("")
        if not ok:
            failed.append(name)

    lines.append(f"OVERALL={'PASS' if not failed else 'FAIL'}")
    if failed:
        lines.append("FAILED_CHECKS=" + ", ".join(failed))

    report = "\n".join(lines) + "\n"
    report_path.write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"REPORT={report_path}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

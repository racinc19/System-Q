#!/usr/bin/env python3
"""Prove that twisting UP on the LPF row drops the cutoff (more highs cut)
and that twisting UP on the HPF row raises the cutoff (more lows cut) — i.e.
both controls share a "twist UP = more filter" convention.

Boots a hidden System Q console, focuses the LPF row, fires synthetic twist
events through the editor nav handler, and prints the resulting cutoff after
each twist. Then does the same on the HPF row.

Also captures a polar PNG before/after to ``Evidence/polar-lpf-hpf-stopband/``
so you can eyeball that twisting UP grows the red stopband fill on both rows.
"""
from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


def main() -> int:
    _dpi_aware()
    software = Path(__file__).resolve().parent
    repo = software.parent
    out_dir = repo / "Evidence" / "polar-lpf-hpf-stopband"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import tkinter as tk
    from PIL import ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1680x1020")
    root.title("System Q LPF/HPF twist direction proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify(); root.lift()
    def pump(n: int = 8) -> None:
        for _ in range(n):
            root.update_idletasks(); root.update()
    pump()

    ch = app._current_channel()
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    plist = app._STAGE_GRID[pre_col][2]
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "pre"
    app.editor_stage_col = pre_col
    app.editor_unified_header_focus = False

    def grab(name: str) -> Path:
        app._draw_focus_to(app.focus_canvas)
        pump(8); time.sleep(0.05)
        fc = app.focus_canvas
        x0 = int(fc.winfo_rootx()); y0 = int(fc.winfo_rooty())
        wpx = max(int(fc.winfo_width()), 240); hpx = max(int(fc.winfo_height()), 240)
        png = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x0, y0, x0 + wpx, y0 + hpx), all_screens=True).save(png)
        return png

    # --- LPF -----------------------------------------------------------------
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = True
        ch.lpf_hz = 22000.0
        ch.hpf_enabled = False
        ch.hpf_hz = 20.0
    app.editor_param_row = plist.index("LPF")
    grab("06_LPF_before_twist_up")
    print("=== LPF: each tick should LOWER the cutoff (more cut, fill grows) ===")
    print(f"  start lpf_hz = {ch.lpf_hz:8.1f}")
    last = ch.lpf_hz
    failures = 0
    for tick in range(1, 21):
        app._adjust_unified_editor_cell(axis_value=1.0)
        pump(2)
        if ch.lpf_hz >= last:
            print(f"  tick {tick:2d}: lpf_hz = {ch.lpf_hz:8.1f}  FAIL (did not decrease from {last:8.1f})")
            failures += 1
        else:
            print(f"  tick {tick:2d}: lpf_hz = {ch.lpf_hz:8.1f}  ({last - ch.lpf_hz:+7.1f} Hz)")
        last = ch.lpf_hz
    grab("06_LPF_after_20_twists_up")

    # --- HPF -----------------------------------------------------------------
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = False
        ch.lpf_hz = 22000.0
        ch.hpf_enabled = True
        ch.hpf_hz = 20.0
    app.editor_param_row = plist.index("HPF")
    grab("07_HPF_before_twist_up")
    print("\n=== HPF: each tick should RAISE the cutoff (more cut, fill grows) ===")
    print(f"  start hpf_hz = {ch.hpf_hz:8.1f}")
    last = ch.hpf_hz
    for tick in range(1, 21):
        app._adjust_unified_editor_cell(axis_value=1.0)
        pump(2)
        if ch.hpf_hz <= last:
            print(f"  tick {tick:2d}: hpf_hz = {ch.hpf_hz:8.1f}  FAIL (did not increase from {last:8.1f})")
            failures += 1
        else:
            print(f"  tick {tick:2d}: hpf_hz = {ch.hpf_hz:8.1f}  ({ch.hpf_hz - last:+7.1f} Hz)")
        last = ch.hpf_hz
    grab("07_HPF_after_20_twists_up")

    print(f"\nBUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}")
    print(f"failures: {failures}")
    print(f"PNG dir : {out_dir}")
    root.destroy()
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

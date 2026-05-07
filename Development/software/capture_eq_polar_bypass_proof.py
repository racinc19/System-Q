#!/usr/bin/env python3
"""
Real Tk polar pane → PNG before/after EQ FRQ/GAN/SHP bypass (scalar EQ path).

Output (recording-environment/Evidence/editor-buttons/):
  EQ_polar_scalar_engaged.png
  EQ_polar_FRQ_GAIN_SHP_all_bypassed.png

Also prints RMS(audio) engaged vs bypassed — must differ when ±8 dB bell was applied.

py -3 capture_eq_polar_bypass_proof.py   (cwd: software/)
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
    out_dir = repo / "Evidence" / "editor-buttons"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import tkinter as tk
    import numpy as np
    from PIL import ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1680x1020")
    root.title("System Q EQ bypass proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()

    def pump() -> None:
        for _ in range(8):
            root.update_idletasks()
            root.update()

    ch = app.engine.channels[0]
    eq_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "eq")
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "eq"
    app.editor_stage_col = eq_ix
    app.editor_unified_header_focus = False

    rng = np.random.default_rng(1)
    noise = rng.standard_normal((sq.BLOCK_SIZE, 2)).astype(np.float32) * 0.06

    def proc_rms(eq_on: bool, *, frq_bp: bool, gan_bp: bool, shp_bp: bool) -> float:
        with app.engine._lock:
            ch.eq_enabled = eq_on
            ch.eq_band_enabled = False
            ch.eq_freq = 2200.0
            ch.eq_gain_db = 8.0
            ch.eq_width = 1.2
            ch.eq_param_bypass.clear()
            if frq_bp:
                ch.eq_param_bypass["FRQ"] = True
            if gan_bp:
                ch.eq_param_bypass["GAN"] = True
            if shp_bp:
                ch.eq_param_bypass["SHP"] = True
        y = app.engine._process_channel(ch, noise.copy())
        return float(np.sqrt(np.mean(np.square(y))))

    def grab_polar(name: str) -> Path:
        pump()
        time.sleep(0.05)
        fc = app.focus_canvas
        fc.update_idletasks()
        x0, y0 = int(fc.winfo_rootx()), int(fc.winfo_rooty())
        x1 = x0 + max(int(fc.winfo_width()), 220)
        y1 = y0 + max(int(fc.winfo_height()), 220)
        app._draw_focus()
        pump()
        p = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).save(p)
        return p

    with app.engine._lock:
        ch.eq_enabled = True
        ch.eq_band_enabled = False
        ch.eq_param_bypass.clear()
        ch.eq_freq = 2200.0
        ch.eq_gain_db = 8.0
        ch.eq_width = 1.2
    app._mirror_eq_ui_band_to_channel(ch)
    app._draw_focus()
    grab_polar("EQ_polar_scalar_engaged")
    r_eng = proc_rms(True, frq_bp=False, gan_bp=False, shp_bp=False)

    with app.engine._lock:
        ch.eq_param_bypass["FRQ"] = True
        ch.eq_param_bypass["GAN"] = True
        ch.eq_param_bypass["SHP"] = True
    app._mirror_eq_ui_band_to_channel(ch)
    app._draw_focus()
    grab_polar("EQ_polar_FRQ_GAIN_SHP_all_bypassed")
    r_bp = proc_rms(True, frq_bp=True, gan_bp=True, shp_bp=True)

    dsp_diff = abs(r_eng - r_bp) > 1e-6
    print(f"RMS engaged={r_eng:.6f} bypassed={r_bp:.6f} dsp_changed={dsp_diff}", flush=True)
    print(f"PNG: {out_dir / 'EQ_polar_scalar_engaged.png'}", flush=True)
    print(f"PNG: {out_dir / 'EQ_polar_FRQ_GAIN_SHP_all_bypassed.png'}", flush=True)

    root.destroy()
    return 0 if dsp_diff else 1


if __name__ == "__main__":
    raise SystemExit(main())

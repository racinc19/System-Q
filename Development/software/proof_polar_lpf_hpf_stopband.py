#!/usr/bin/env python3
"""Visible proof that the mic-pre LPF / HPF polar visualization paints the
**stopband** (the side being cut), not the passband.

Renders three states of the PRE focus pane to PNG so the operator can compare
visually:

    1. LPF engaged at 6461 Hz — stopband fill grows inward toward the
       high-Hz center, leaving a clean rim where the passband lives.
    2. HPF engaged at 800 Hz — stopband fill grows outward toward the
       low-Hz rim, leaving a clean center where the passband lives.
    3. BOTH engaged (LPF 6 kHz + HPF 200 Hz) — stopband from both ends,
       passband is the bright analyzer band in the middle.

Outputs to ``../Evidence/polar-lpf-hpf-stopband/``.
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
    import numpy as np
    from PIL import ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1680x1020")
    root.title("System Q LPF/HPF stopband visual proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()
    root.focus_force()

    def pump(n: int = 12) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()

    pump()

    n_bands = int(sq.POL_BANDS)
    bands = np.linspace(0.85, 0.10, n_bands).astype(np.float32) ** 1.2
    app.engine.master_channel.band_levels = bands.copy()
    app.engine.master_channel.level = 0.55
    app._pol_pulse_cached = 0.55

    ch = app._current_channel()
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "pre"
    app.editor_stage_col = pre_col
    app.editor_unified_header_focus = False
    plist_pre = app._STAGE_GRID[pre_col][2]
    app.editor_param_row = plist_pre.index("LPF")

    def grab(name: str) -> Path:
        app._draw_focus_to(app.focus_canvas)
        pump(8)
        time.sleep(0.05)
        fc = app.focus_canvas
        x0 = int(fc.winfo_rootx())
        y0 = int(fc.winfo_rooty())
        wpx = max(int(fc.winfo_width()), 240)
        hpx = max(int(fc.winfo_height()), 240)
        png = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x0, y0, x0 + wpx, y0 + hpx), all_screens=True).save(png)
        print(f"WROTE  {png}", flush=True)
        return png

    # 1. LPF engaged at 6461 Hz, HPF off.
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = True
        ch.lpf_hz = 6461.0
        ch.hpf_enabled = False
        ch.hpf_hz = 20.0
        ch.phase = False
    grab("01_LPF_6461hz_only")

    # 2. HPF engaged at 800 Hz, LPF off.
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = False
        ch.lpf_hz = 22000.0
        ch.hpf_enabled = True
        ch.hpf_hz = 800.0
    grab("02_HPF_800hz_only")

    # 3. BOTH on — bright passband sandwiched between two stopband fills.
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = True
        ch.lpf_hz = 6000.0
        ch.hpf_enabled = True
        ch.hpf_hz = 200.0
    grab("03_LPF_6kHz_HPF_200Hz_bandpass")

    # 4. Sweep LPF down: should show the stopband disc growing toward the rim.
    for hz in (12000.0, 4000.0, 1500.0, 500.0, 200.0):
        with app.engine._lock:
            ch.pre_enabled = True
            ch.lpf_enabled = True
            ch.lpf_hz = float(hz)
            ch.hpf_enabled = False
        grab(f"04_LPF_sweep_{int(hz)}hz")

    # 5. Sweep HPF up: stopband ring at the rim should grow inward.
    for hz in (40.0, 120.0, 400.0, 1200.0):
        with app.engine._lock:
            ch.pre_enabled = True
            ch.lpf_enabled = False
            ch.hpf_enabled = True
            ch.hpf_hz = float(hz)
        grab(f"05_HPF_sweep_{int(hz)}hz")

    print(f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}", flush=True)
    print(f"PNG dir: {out_dir}", flush=True)
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

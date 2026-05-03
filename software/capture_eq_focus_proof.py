"""Proof PNG: Tk + DPI-aware grab of editor pane (polar EQ in top focus canvas)."""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

import tkinter as tk
from PIL import ImageGrab

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


def _set_dpi_aware() -> None:
    """Align Tk/reporting coords with Pillow ImageGrab on scaled displays."""

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    _set_dpi_aware()

    software = Path(__file__).resolve().parent
    sys.path.insert(0, str(software))

    import system_q_console as sq  # noqa: PLC0415

    root = tk.Tk()
    root.geometry("1520x960")
    root.title("System Q Console")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()
    root.update_idletasks()
    root.update()

    app.nav_scope = "editor"
    app.editor_channel = 0
    app.selected_channel = 0
    app.selected_stage_key = "eq"
    app.editor_nav_scope = "stage_grid"
    app.editor_stage_col = 4
    # Focus SHP row (symmetric ±spread cell with width→whiten text).
    eq_params = app._STAGE_GRID[4][2]
    app.editor_param_row = eq_params.index("SHP")

    ch = app.engine.channels[0]
    with app.engine._lock:
        ch.eq_band_enabled = True
        ch.eq_band_count = 2
        ch.eq_enabled = True
        app.eq_selected_band = 0
        b0 = app._eq_band(ch, 0)
        b1 = app._eq_band(ch, 1)
        b0.update({"freq": 1000.0, "gain_db": 12.0, "width": 0.52, "type": "BELL", "enabled": True})
        b1.update({"freq": 7800.0, "gain_db": -13.5, "width": 2.95, "type": "BELL", "enabled": True})
        app._sync_scalar_display_from_eq_band(ch)

    for _ in range(50):
        root.update_idletasks()
        root.update()
        time.sleep(0.05)

    ef = app.editor_frame
    ef.update_idletasks()
    x0 = int(ef.winfo_rootx())
    y0 = int(ef.winfo_rooty())
    x1 = x0 + max(int(ef.winfo_width()), 520)
    y1 = y0 + max(int(ef.winfo_height()), 400)

    img = ImageGrab.grab(bbox=(x0, y0, x1, y1))
    out = software / "eq_editor_pane_polar_proof.png"
    img.save(out)
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        desk_copy = desktop / "SYSTEM_Q_EQ_SHP_proof.png"
        img.save(desk_copy)
        print(f"Saved {desk_copy}")

    print(f"Saved {out} editor_bbox=({x0},{y0},{x1},{y1}) SHP highlight row focused")
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

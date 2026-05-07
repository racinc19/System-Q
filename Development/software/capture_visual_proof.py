"""One-shot PNGs for chat / Desktop — EQ polar, TBE tone row colors, strips + PLY row."""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

import tkinter as tk
from PIL import ImageGrab

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


def _set_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _grab(widget: tk.Misc, out: Path) -> None:
    widget.update_idletasks()
    widget.update()
    x0 = int(widget.winfo_rootx())
    y0 = int(widget.winfo_rooty())
    x1 = x0 + max(int(widget.winfo_width()), 4)
    y1 = y0 + max(int(widget.winfo_height()), 4)
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(out)


def main() -> int:
    _set_dpi()
    soft = Path(__file__).resolve().parent
    sys.path.insert(0, str(soft))
    import system_q_console as sq  # noqa: PLC0415

    root = tk.Tk()
    root.geometry("1720x980")
    root.title("SYSTEM_Q visual proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()

    desk = Path.home() / "Desktop"

    def settle(n: int = 36) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()
            time.sleep(0.04)

    settle(45)

    strip_parent = app.strip_canvas.master
    strips_path = soft / "SYSTEM_Q_proof_strips_transport.png"
    _grab(strip_parent, strips_path)
    print(f"Saved {strips_path}", flush=True)
    if desk.is_dir():
        t = desk / "SYSTEM_Q_proof_strips_transport.png"
        _grab(strip_parent, t)
        print(f"Saved {t}", flush=True)

    app.nav_scope = "editor"
    app.selected_stage_key = "eq"
    app.editor_stage_col = 4
    eq_params = app._STAGE_GRID[4][2]
    app.editor_param_row = eq_params.index("SHP")
    app._sync_from_engine()
    settle(25)
    eq_path = soft / "SYSTEM_Q_proof_eq_polar.png"
    _grab(app.editor_frame, eq_path)
    print(f"Saved {eq_path}", flush=True)
    if desk.is_dir():
        te = desk / "SYSTEM_Q_proof_eq_polar.png"
        _grab(app.editor_frame, te)
        print(f"Saved {te}", flush=True)

    app.selected_stage_key = "tone"
    app.editor_stage_col = 5
    app.editor_param_row = app._STAGE_GRID[5][2].index("DRV")
    app._sync_from_engine()
    settle(25)
    tone_path = soft / "SYSTEM_Q_proof_tone_colors.png"
    _grab(app.editor_frame, tone_path)
    print(f"Saved {tone_path}", flush=True)
    if desk.is_dir():
        tt = desk / "SYSTEM_Q_proof_tone_colors.png"
        _grab(app.editor_frame, tt)
        print(f"Saved {tt}", flush=True)

    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

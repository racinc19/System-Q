"""PNG proof: EQ focus pane is visually empty when the insert is bypassed."""

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
    root.geometry("1500x900")
    root.title("EQ polar off proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()

    def settle(n: int = 30) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()
            time.sleep(0.04)

    settle(36)

    ch = app.engine.channels[0]
    ch.eq_gain_db = 12.0
    ch.eq_freq = 2200.0
    ch.eq_band_enabled = False
    ch.eq_enabled = False
    # Regression: generator polar (OSC/PNK/WHT) must not layer on empty EQ bypass pane.
    app.engine.generator_mode = "osc"

    app.nav_scope = "editor"
    app.selected_stage_key = "eq"
    app.editor_nav_scope = "stage_grid"
    app.editor_stage_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "eq")
    app.editor_param_row = 0
    app.editor_unified_header_focus = False

    app._sync_from_engine()
    app._draw_focus()
    settle(22)

    desk = Path.home() / "Desktop"
    name = "SYSTEM_Q_proof_EQ_polar_shells_when_insert_off.png"
    outp = soft / name
    _grab(app.focus_canvas, outp)
    print(
        f"Saved {outp} | eq_enabled=False gain_stored={ch.eq_gain_db}dB "
        "(pane should be solid fill only; no ellipses, spectrum, or bells)",
        flush=True,
    )
    if desk.is_dir():
        _grab(app.focus_canvas, desk / outp.name)
        print(f"Saved {desk / outp.name}", flush=True)

    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

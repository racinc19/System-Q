"""Save Desktop PNG proofs: narrow vs wide WINDOW, then narrow vs wide EQ spread (polar).

Uses ``ConsoleApp(..., internal_capture=True)`` only in this script so the normal GUI always
runs the recurring redraw timer and auto-placement. Do not set process-wide env vars for that.

Run from this folder:
  py -3 capture_eq_ui_narrow_wide_proof.py

Desktop outputs (when ~/Desktop exists):
  SYSTEM_Q_CONSOLE_window_NARROW.png
  SYSTEM_Q_CONSOLE_window_WIDE.png
  SYSTEM_Q_CONSOLE_spread_NARROW_band0.png
  SYSTEM_Q_CONSOLE_spread_WIDE_band0.png
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
import time
import traceback
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageGrab

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


class _QuietSpaceMouse:
    __slots__ = ()

    available = False
    name = "capture-disabled"

    def poll(self):  # noqa: ANN204
        return 0.0, [], []


def _set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _foreground_tk(root: tk.Tk) -> None:
    """Best-effort: raise Tk so grabs are not a blank/other window."""

    user32 = ctypes.windll.user32
    try:
        hwnd = wintypes.HWND(root.winfo_id())
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _grab_editor_frame(app: object, software: Path, tag: str) -> None:
    ef = app.editor_frame
    ef.update_idletasks()

    img: Image.Image | None = None
    try:
        img = _grab_tk_widget_win32(ef)
    except Exception as e_win:
        print(f"Win32 grab failed ({e_win}); trying ImageGrab...", flush=True)
        rootx = int(ef.winfo_rootx())
        rooty = int(ef.winfo_rooty())
        rw = max(int(ef.winfo_width()), 480)
        rh = max(int(ef.winfo_height()), 360)
        bbox = (rootx, rooty, rootx + rw, rooty + rh)
        try:
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:
            img = ImageGrab.grab(bbox=bbox)

    local = software / f"eq_proof_{tag}.png"
    img.save(local)
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        desk = desktop / f"SYSTEM_Q_CONSOLE_{tag}.png"
        img.save(desk)
        print(f"Saved {desk}", flush=True)


def _grab_tk_widget_win32(widget: tk.Misc) -> Image.Image:
    from tk_win32_widget_grab import grab_tk_widget_win32

    return grab_tk_widget_win32(widget)


def _paint(app: object, root: tk.Tk) -> None:
    """Redraw without the normal ``after(60)`` loop."""

    root.update_idletasks()
    root.update()
    try:
        app._poll_spacemouse()
        app._draw_strips()
        app._draw_timeline()
        app._draw_focus()
        app._draw_editor_controls()
    except Exception:
        traceback.print_exc()
        raise
    root.update_idletasks()
    root.update()


def main() -> int:
    root: tk.Tk | None = None
    try:
        _set_dpi_aware()
        software = Path(__file__).resolve().parent
        sys.path.insert(0, str(software))

        # ``SpaceMouseController`` runs pygame joystick init — can wedge without a logged-in GPU session.
        # Patch before importing the console module (it does ``from pol_visualizer import SpaceMouseController``).
        import pol_visualizer as pv  # noqa: PLC0415

        pv.SpaceMouseController = _QuietSpaceMouse  # type: ignore[misc]

        import system_q_console as sq  # noqa: PLC0415

        print("capture_eq_ui_narrow_wide_proof: Tk()", flush=True)
        root = tk.Tk()
        root.title("System Q Console — narrow/wide proof")
        root.deiconify()

        print("capture_eq_ui_narrow_wide_proof: ConsoleApp(internal_capture=True)", flush=True)
        app = sq.ConsoleApp(root, internal_capture=True)

        app.nav_scope = "editor"
        app.editor_channel = 0
        app.selected_channel = 0
        app.selected_stage_key = "eq"
        app.editor_nav_scope = "stage_grid"
        app.editor_stage_col = 4
        eq_params = app._STAGE_GRID[4][2]
        app.editor_param_row = eq_params.index("SHP")

        ch = app.engine.channels[0]
        with app.engine._lock:
            ch.eq_band_enabled = True
            ch.eq_band_count = 2
            ch.eq_enabled = True
            ch.eq_param_bypass.clear()
            app.eq_selected_band = 0
            b0 = app._eq_band(ch, 0)
            b1 = app._eq_band(ch, 1)
            b0.update(
                {"freq": 1200.0, "gain_db": 14.0, "width": 0.35, "type": "BELL", "enabled": True}
            )
            b1.update(
                {"freq": 8500.0, "gain_db": -10.0, "width": 1.8, "type": "BELL", "enabled": True}
            )
            app._sync_scalar_display_from_eq_band(ch)
            app._mirror_eq_ui_band_to_channel(ch)

        # --- narrow window ---
        root.geometry("920x900+80+48")
        _foreground_tk(root)
        app._autosize_editor_canvas_height()
        app._sync_from_engine()
        for _ in range(8):
            _paint(app, root)
            time.sleep(0.03)
        _grab_editor_frame(app, software, "window_NARROW")

        # --- wide window ---
        root.geometry("1880x1020+24+24")
        _foreground_tk(root)
        app._autosize_editor_canvas_height()
        app._sync_from_engine()
        for _ in range(10):
            _paint(app, root)
            time.sleep(0.03)
        _grab_editor_frame(app, software, "window_WIDE")

        # --- EQ spread narrow (wide chrome) ---
        with app.engine._lock:
            app._eq_band(ch, 0)["width"] = 0.18
            app._sync_scalar_display_from_eq_band(ch)
        app._autosize_editor_canvas_height()
        app._sync_from_engine()
        for _ in range(6):
            _paint(app, root)
        _grab_editor_frame(app, software, "spread_NARROW_band0")

        # --- EQ spread wide ---
        with app.engine._lock:
            app._eq_band(ch, 0)["width"] = 4.2
            app._sync_scalar_display_from_eq_band(ch)
        app._autosize_editor_canvas_height()
        app._sync_from_engine()
        for _ in range(6):
            _paint(app, root)
        _grab_editor_frame(app, software, "spread_WIDE_band0")

        print("Local copies also under", software, flush=True)
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

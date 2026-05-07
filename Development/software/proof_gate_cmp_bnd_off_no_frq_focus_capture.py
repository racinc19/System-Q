#!/usr/bin/env python3
"""HWND-only PNG plus **full desktop** PNG — GTE BND off cannot keep focus on inert FRQ/WDT.

The running app proves state in **the UI** (blank FRQ/WDT cells, gate focus row, title text).
- ``SYSTEM_Q_proof_gate_bnd_off_focus_not_frq_wdt.png`` = Win32 BitBlt of the Tk top-level only.
- ``SYSTEM_Q_proof_gate_bnd_DESKTOP_FULL.png`` = ``ImageGrab`` of all screens (what is actually on the desktop).

Optionally mirror the PNG to Explorer Desktop when ``SYSTEM_Q_MIRROR_PROOF_TO_DESKTOP=1``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import pathlib
import shutil
import sys
import time

import tkinter as tk
from PIL import ImageGrab

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


def _set_dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _foreground_tk(root: tk.Tk) -> None:
    if sys.platform != "win32":
        root.lift()
        return
    user32 = ctypes.windll.user32
    try:
        hwnd = wintypes.HWND(root.winfo_id())
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        root.lift()


def _windows_shell_desktop() -> pathlib.Path | None:
    try:
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH * 4)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) != 0:
            return None
        return pathlib.Path(buf.value)
    except Exception:
        return None


def desktop_png_dest(filename: str) -> pathlib.Path:
    for base in (_windows_shell_desktop(), pathlib.Path.home() / "Desktop"):
        if base is not None and base.is_dir():
            return base / filename
    return pathlib.Path.home() / filename


def main() -> None:
    _set_dpi_aware()
    import system_q_console as sq
    from tk_win32_widget_grab import grab_tk_widget_win32

    root = tk.Tk()
    root.geometry("1720x1040")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    _foreground_tk(root)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    ch = app.engine.channels[0]
    with app.engine._lock:
        ch.gate_band_enabled = False
        ch.comp_band_enabled = False
        ch.gate_enabled = True
        ch.comp_enabled = False

    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    gate_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "gate")
    app.editor_stage_col = gate_col
    plist = app._STAGE_GRID[gate_col][2]
    ir_f = plist.index("FRQ")
    ir_w = plist.index("WDT")

    app.editor_param_row = ir_f
    app.editor_unified_header_focus = False

    app._draw_editor_controls()
    app._draw_focus()
    for _ in range(10):
        root.update_idletasks()
        root.update()

    ipr = int(app.editor_param_row)
    if ipr in (ir_f, ir_w):
        print("BLOCKED: focus still on inert row", ipr, plist[ipr])
        sys.exit(2)

    row_label = plist[ipr]
    root.title(
        f"System Q Console · {sq.SYSTEM_Q_BUILD_ID} · "
        f"UI PROOF: GTE BND off → focus {row_label} (not FRQ/WDT)"
    )
    app._draw_editor_controls()
    app._draw_focus()
    for _ in range(4):
        root.update_idletasks()
        root.update()

    print(
        "PASS: remapped from stale FRQ idx to",
        ipr,
        row_label,
        "build",
        sq.SYSTEM_Q_BUILD_ID,
    )

    name = "SYSTEM_Q_proof_gate_bnd_off_focus_not_frq_wdt.png"
    out_repo = ROOT / name

    time.sleep(0.08)
    try:
        img = grab_tk_widget_win32(root)
    except Exception as e:
        print("Win32 window grab failed:", e, flush=True)
        sys.exit(3)
    img.save(out_repo)
    print("PNG (repo software, HWND-only):", out_repo)

    out_desktop_full = ROOT / "SYSTEM_Q_proof_gate_bnd_DESKTOP_FULL.png"
    time.sleep(0.12)
    try:
        desk_img = ImageGrab.grab(all_screens=True)
    except TypeError:
        desk_img = ImageGrab.grab()
    desk_img.save(out_desktop_full)
    print("PNG (full desktop / all monitors):", out_desktop_full)

    if os.environ.get("SYSTEM_Q_MIRROR_PROOF_TO_DESKTOP", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        out_desktop = desktop_png_dest(name)
        try:
            shutil.copyfile(out_repo, out_desktop)
            print("PNG (Explorer Desktop):", out_desktop.resolve())
        except OSError as e:
            fallback = (
                pathlib.Path(os.environ.get("USERPROFILE", str(pathlib.Path.home())))
                / "Desktop"
                / name
            )
            print("WARN: desktop copy failed", out_desktop, e, "; trying", fallback, flush=True)
            shutil.copyfile(out_repo, fallback)
            print("PNG (Desktop fallback):", fallback.resolve())

    root.destroy()


if __name__ == "__main__":
    main()

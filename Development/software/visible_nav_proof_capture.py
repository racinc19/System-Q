#!/usr/bin/env python3
"""
Visible System Q: open REAL window → one scope move → pause → fullscreen grab → repeat.

Screenshots land on Desktop (and copies under recording-environment/software/).

  py -3 visible_nav_proof_capture.py

Agent / unattended (closes after last PNG):

  py -3 visible_nav_proof_capture.py --auto-exit --dwell-ms 1200 --lead-ms 1500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


def main() -> int:
    _dpi_aware()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--auto-exit",
        action="store_true",
        help="Close the app shortly after the last screenshot (for automation).",
    )
    parser.add_argument("--dwell-ms", type=int, default=2800, help="Pause after UI update before grab.")
    parser.add_argument("--lead-ms", type=int, default=3400, help="Initial pause on strips before first grab.")
    args = parser.parse_args()

    software = Path(__file__).resolve().parent
    sys.path.insert(0, str(software))

    import tkinter as tk
    from PIL import ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.title(f"System Q visible proof ({sq.SYSTEM_Q_BUILD_ID})")
    root.geometry("1560x960")

    dwell = max(600, int(args.dwell_ms))
    lead = max(400, int(args.lead_ms))
    repo = software
    desktop = Path.home() / "Desktop"

    print(f"VISIBLE_PROOF: build {sq.SYSTEM_Q_BUILD_ID}", flush=True)
    print(f"VISIBLE_PROOF: dwell_ms={dwell} lead_ms={lead} auto_exit={args.auto_exit}", flush=True)

    app = sq.ConsoleApp(root, startup_play=False)

    steps: list[tuple[str | None, str]] = [
        (None, "00_START_strips"),
        ("right", "01_AFTER_macro_RIGHT_editor"),
        ("left", "02_AFTER_macro_LEFT_faders"),
        ("up", "03_AFTER_macro_UP_channel_strips"),
        ("down", "04_AFTER_macro_DOWN_transport_PLY"),
    ]

    idx = [0]

    def grab(tag: str) -> Path:
        app._agent_proof_foreground()
        app._agent_proof_paint_everything()
        app._sync_from_engine()
        root.update_idletasks()
        root.update()
        rx, ry = int(root.winfo_rootx()), int(root.winfo_rooty())
        rw = max(int(root.winfo_width()), 1024)
        rh = max(int(root.winfo_height()), 680)
        bbox = (rx, ry, rx + rw, ry + rh)
        try:
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:
            img = ImageGrab.grab(bbox=bbox)
        fname = f"VISIBLE_NAV_PROOF_{tag}.png"
        primary = repo / fname
        img.save(primary)
        print(f"VISIBLE_PROOF: saved ===> {primary}", flush=True)
        if desktop.is_dir():
            dup = desktop / fname
            try:
                img.save(dup)
                print(f"VISIBLE_PROOF: saved ===> {dup}", flush=True)
            except OSError as exc:
                print(f"VISIBLE_PROOF: Desktop copy skipped ({exc})", flush=True)
        return primary

    def run_phase() -> None:
        i = idx[0]

        def after_dwell() -> None:
            tag = steps[i][1]
            try:
                root.title(f"{sq.SYSTEM_Q_BUILD_ID} — capture {tag}")
            except tk.TclError:
                pass
            grab(tag)
            if i + 1 < len(steps):
                idx[0] = i + 1
                root.after(400, run_phase)
                return

            print("VISIBLE_PROOF: sequence complete.", flush=True)
            if args.auto_exit:
                root.after(1500, lambda: app.on_close())

        cardinal = steps[i][0]

        app._agent_proof_foreground()

        if cardinal is None:
            app.nav_scope = "console"
            app.console_row = "stages"
            app.selected_channel = 0
            app.editor_channel = 0
            app.selected_stage_key = "eq"
            app._transport_entered_from = None
            app._normalize_console_selection()
            app._redraw_transport_focus()
            app._sync_from_engine()
            app._agent_proof_paint_everything()

            pause = lead if i == 0 else dwell
            root.after(120, lambda: root.after(pause, after_dwell))
            return

        app._run_cardinal_double_tap_macro(cardinal)
        app._sync_from_engine()
        app._agent_proof_paint_everything()
        root.after(120, lambda: root.after(dwell, after_dwell))

    def begin() -> None:
        app._place_window_primary_visible()
        run_phase()

    root.after(600, begin)
    root.mainloop()

    print("VISIBLE_PROOF: mainloop exited", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

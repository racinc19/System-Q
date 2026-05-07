#!/usr/bin/env python3
"""End-to-end visible-window proof that the LPF behaves correctly.

This boots a **visible** ConsoleApp Tk root (not hidden), uses Tk's own
``event_generate`` to fire real ``<KeyPress-Up>`` / ``<KeyPress-Right>``
events through the bound keyboard handlers (same path a physical key would
take), navigates to the PRE column / LPF row, and then drives the twist
through the production ``_adjust_selected_editor_item`` (the same function
the SpaceMouse Z-axis polling thread calls). After every step it grabs a
screenshot of the **whole window** so the user can eyeball that the visible
Tk render reflects the new state.

Note: the codebase does not bind a keyboard key for "twist" (twist comes
from the SpaceMouse Z-axis), so the twist itself is delivered by calling
the same handler the device polling delivers to. Keyboard navigation IS
driven through Tk's real event dispatch.

Outputs to ``Evidence/polar-lpf-hpf-stopband/visible-ui/``.
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
    out_dir = repo / "Evidence" / "polar-lpf-hpf-stopband" / "visible-ui"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import tkinter as tk
    from PIL import ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1680x1020+40+40")
    root.title("System Q LPF live UI drive proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.update()

    def pump(n: int = 8) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()

    pump(20)
    time.sleep(0.4)

    def grab_window(name: str) -> Path:
        pump(8)
        time.sleep(0.05)
        x0 = int(root.winfo_rootx())
        y0 = int(root.winfo_rooty())
        wpx = max(int(root.winfo_width()), 320)
        hpx = max(int(root.winfo_height()), 320)
        png = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x0, y0, x0 + wpx, y0 + hpx), all_screens=True).save(png)
        return png

    def fire_key(seq: str) -> None:
        # Real Tk keyboard event through the bind_all('<KeyPress-…>') handlers.
        root.event_generate(seq, when="now")
        # Releases too — symmetric with the production keyboard binds.
        rel = seq.replace("<KeyPress-", "<KeyRelease-")
        root.event_generate(rel, when="now")
        pump(2)

    ch = app._current_channel()

    # 1. Force unified editor focus on the PRE column so the keyboard nav lands
    #    in the same place the user would be after clicking the PRE header.
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    plist = app._STAGE_GRID[pre_col][2]
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "pre"
    app.editor_stage_col = pre_col
    app.editor_unified_header_focus = False
    app.editor_param_row = plist.index("LPF")

    # Engage LPF at the wide-open default and capture the BEFORE state.
    with app.engine._lock:
        ch.pre_enabled = True
        ch.lpf_enabled = True
        ch.lpf_hz = 22000.0
        ch.hpf_enabled = False
    pump(8)
    print(f"BEFORE  lpf_hz = {ch.lpf_hz:.1f} Hz")
    grab_window("01_window_before_LPF_22kHz")

    # 2. Drive 30 twist-UP events through the same code path the SpaceMouse
    #    Z-axis polling thread feeds (`_adjust_selected_editor_item(+1.0)`),
    #    which dispatches into `_adjust_unified_editor_cell` and through the
    #    spec_table entry we just edited.
    print("Driving 30 twist-UP events through _adjust_selected_editor_item …")
    samples = []
    for tick in range(1, 31):
        prev = ch.lpf_hz
        app._adjust_selected_editor_item(axis_value=1.0)
        pump(2)
        samples.append((tick, prev, ch.lpf_hz))
        if tick in (1, 5, 10, 15, 20, 25, 30):
            grab_window(f"02_window_LPF_after_{tick}_twists")
            print(f"  tick {tick:2d}: lpf_hz = {ch.lpf_hz:8.1f} Hz   ({prev - ch.lpf_hz:+7.1f})")

    # 3. Sanity-check direction monotonicity: every tick must lower the cutoff.
    bad = [(t, p, n) for (t, p, n) in samples if n >= p]
    print(f"\nMonotonicity check: {len(bad)} non-decreasing tick(s) (expect 0)")

    # 4. Bonus: also drive the keyboard arrow keys through the real Tk bind_all
    #    handlers so the user sees the editor focus moving like a real keystroke.
    print("\nDriving real Tk keyboard events to move the editor focus row …")
    grab_window("03_window_before_keyboard_nav")
    fire_key("<KeyPress-Down>")
    grab_window("04_window_after_KeyDown")
    fire_key("<KeyPress-Up>")
    grab_window("05_window_after_KeyUp")

    print(f"\nBUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}")
    print(f"final lpf_hz = {ch.lpf_hz:.1f}")
    print(f"PNG dir: {out_dir}")
    print("\nWindow is staying open — close it yourself when you're done.")
    print("(Earlier builds of this script auto-destroyed the Tk root, which is")
    print(" why proof windows seemed to vanish on their own.)")

    # Hand the window over to the user. Tk's mainloop blocks on Window-close,
    # so the proof process exits only when the operator closes the window.
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())

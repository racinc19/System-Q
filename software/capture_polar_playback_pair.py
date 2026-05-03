"""Prove polar display tracks monitored audio — two grabs at different playback times, script changes only transport.

Creates:
  SYSTEM_Q_polar_proof_PLAY_A.png
  SYSTEM_Q_polar_proof_PLAY_B.png
Exits nonzero if grabs are pixel-identical (polar unchanged when music differs).

After the proof, **this same window** stays open as the normal interactive console
(see ``ConsoleApp.promote_internal_capture_to_interactive``) — no tear-down flash.

CLI:
  --capture-only   Save PNGs, destroy Tk, exit with pass/fail code (CI / automation).
  --detach         Close this Tk root and spawn ``run_system_q_console.bat`` (legacy).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import tkinter as tk
from PIL import Image, ImageGrab

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


def _set_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


def _grab(widget: tk.Misc, out: Path) -> None:
    widget.update_idletasks()
    widget.update()
    x0 = int(widget.winfo_rootx())
    y0 = int(widget.winfo_rooty())
    x1 = x0 + max(int(widget.winfo_width()), 8)
    y1 = y0 + max(int(widget.winfo_height()), 8)
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(out)


def _pump(root: tk.Misc, frames: int) -> None:
    for _ in range(frames):
        root.update_idletasks()
        root.update()
        time.sleep(0.012)


def main() -> int:
    _set_dpi()
    soft = Path(__file__).resolve().parent
    capture_only = "--capture-only" in sys.argv
    detach_spawn = "--detach" in sys.argv
    sys.path.insert(0, str(soft))
    import system_q_console as sq  # noqa: PLC0415

    root = tk.Tk()
    root.geometry("1680x960")
    root.title("Polar playback proof")

    app = sq.ConsoleApp(root, internal_capture=True, startup_play=False)
    root.deiconify()
    root.lift()

    engine = app.engine

    # Full monitored mix — not soloKick-only demo preset.
    with engine._lock:
        for ch in engine.channels:
            ch.solo = False
            ch.mute = False

    # Frequency+dynamics polar ring stack (monitor FFT) visible on PRE, not EQ bell-only plane.
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "pre"
    app.selected_channel = 0
    engine.generator_mode = "none"
    app._sync_from_engine()

    engine.prime_stream()
    engine.playing = True
    dur = float(max(8.0, engine.timeline_duration_seconds()))
    t_a = dur * 0.12
    t_b = dur * 0.58
    if abs(t_b - t_a) < 4.0:
        t_b = min(dur - 2.0, t_a + 8.0)

    def redraw_all() -> None:
        try:
            app._poll_spacemouse()
            app._draw_strips()
            app._draw_timeline()
            app._draw_focus()
            app._draw_editor_controls()
            app._sync_play_transport_glyph()
        except Exception:
            import traceback
            traceback.print_exc()

    redraw_all()
    _pump(root, 40)

    # --- Shot A ---
    engine.seek_seconds(t_a)
    # Let FFT + smoothed rings catch up (~0.65 s realtime + Tk pumps).
    deadline = time.monotonic() + 0.72
    while time.monotonic() < deadline:
        redraw_all()
        _pump(root, 3)

    out_a = soft / "SYSTEM_Q_polar_proof_PLAY_A.png"
    _grab(app.focus_canvas, out_a)
    img_a = np.array(Image.open(out_a))

    engine.seek_seconds(t_b)
    deadline = time.monotonic() + 0.76
    while time.monotonic() < deadline:
        redraw_all()
        _pump(root, 3)

    out_b = soft / "SYSTEM_Q_polar_proof_PLAY_B.png"
    _grab(app.focus_canvas, out_b)
    img_b = np.array(Image.open(out_b))

    desk = Path.home() / "Desktop"
    if desk.is_dir():
        img_a_save = desk / out_a.name
        img_b_save = desk / out_b.name
        Image.fromarray(img_a).save(img_a_save)
        Image.fromarray(img_b).save(img_b_save)
        print(f"Also Desktop: {img_a_save}", flush=True)
        print(f"Also Desktop: {img_b_save}", flush=True)

    diff = np.mean(np.abs(img_a.astype(np.int16) - img_b.astype(np.int16)))
    mx = np.max(np.abs(img_a.astype(np.int16) - img_b.astype(np.int16)))

    print(f"t_a={t_a:.2f}s  t_b={t_b:.2f}s  duration={dur:.2f}s", flush=True)
    print(f"Saved {out_a}", flush=True)
    print(f"Saved {out_b}", flush=True)
    print(f"Mean |pixel delta| RGB={diff:.4f}  max={mx}", flush=True)

    exit_code = 2 if (diff < 2.5 and mx < 48) else 0
    if exit_code != 0:
        print(
            "FAIL: captures too similar — polar may not follow playback or FFT settle time too short.",
            flush=True,
        )
    else:
        print("PASS: grabs differ materially (music/time changed the polar rendering).", flush=True)

    if capture_only:
        root.destroy()
        return exit_code

    if detach_spawn:
        root.destroy()
        bat = soft / "run_system_q_console.bat"
        exe = sys.executable
        try:
            if os.name == "nt" and bat.is_file():
                subprocess.Popen(  # noqa: S603,S607 — controlled path
                    ["cmd.exe", "/c", "start", "", str(bat)],
                    cwd=str(soft),
                    close_fds=True,
                )
            else:
                subprocess.Popen([exe, "-3", str(soft / "system_q_console.py")], cwd=str(soft))
            print("Spawned interactive System Q Console (duplicate instance).", flush=True)
        except Exception as exc:
            print(f"Could not spawn console ({exc}); run: py -3 system_q_console.py", flush=True)
        return exit_code

    print("Staying in this window — interactive System Q (close when done).", flush=True)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    app.promote_internal_capture_to_interactive()
    root.mainloop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

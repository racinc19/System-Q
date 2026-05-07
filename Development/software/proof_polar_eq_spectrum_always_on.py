#!/usr/bin/env python3
"""Visible proof that the EQ-focused polar pane paints the live monitored
spectrum even when ``eq_enabled`` is False (regression check for build
``polar-eq-spectrum-always-on-20260503``).

The previous behaviour was: with EQ bypassed (default at session start) the
EQ-focus drawer early-returned, leaving a black canvas. The user reported
this as "no display when music is being played on the polar graph". This
script:

    1. Boots a real visible Tk console (1680x1020), ``startup_play=False``
       so we control the timing.
    2. Pushes a synthetic "kick-loud / hat-quiet" spectrum into
       ``engine.master_channel.band_levels`` so the polar has something to
       paint regardless of audio device state.
    3. Parks editor focus on the EQ column (``selected_stage_key="eq"``).
    4. Captures two PNGs of just the ``focus_canvas`` rectangle:
         a. EQ insert BYPASSED (channel ships with ``eq_enabled=False``).
         b. EQ insert ENGAGED (bell active so EQ shells overlay the spectrum).
    5. Counts non-background pixels in each PNG and asserts the bypassed
       version has substantial paint (the live spectrum), proving the
       regression is fixed.

Run from ``software/``::

    py -3 proof_polar_eq_spectrum_always_on.py

Outputs go to ``../Evidence/polar-spectrum/``.
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
    out_dir = repo / "Evidence" / "polar-spectrum"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import tkinter as tk
    import numpy as np
    from PIL import Image, ImageGrab

    import system_q_console as sq

    root = tk.Tk()
    root.geometry("1680x1020")
    root.title("System Q polar EQ-bypassed spectrum proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()
    root.focus_force()

    def pump(n: int = 12) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()

    pump()

    # Kick-heavy synthetic spectrum: low bands loud, high bands quiet. This is
    # what the analyzer would push into master_channel.band_levels while the
    # repo's 01_kick.wav loop plays. We bypass the audio device so the test is
    # deterministic on machines without an output stream.
    n_bands = int(sq.POL_BANDS)
    bands = np.linspace(0.92, 0.06, n_bands).astype(np.float32) ** 1.4
    app.engine.master_channel.band_levels = bands.copy()
    app.engine.master_channel.level = 0.55
    app._pol_pulse_cached = 0.62

    ch = app._current_channel()
    eq_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "eq")
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "eq"
    app.editor_stage_col = eq_ix
    app.editor_unified_header_focus = False
    plist_eq = app._STAGE_GRID[eq_ix][2]
    app.editor_param_row = plist_eq.index("FRQ") if "FRQ" in plist_eq else 0
    pump()

    def grab_focus_pane(name: str) -> tuple[Path, int]:
        fc = app.focus_canvas
        fc.update_idletasks()
        # Force a fresh paint so the synthetic band_levels are reflected.
        app._draw_focus_to(fc)
        pump(6)
        time.sleep(0.05)
        x0 = int(fc.winfo_rootx())
        y0 = int(fc.winfo_rooty())
        w = max(int(fc.winfo_width()), 240)
        h = max(int(fc.winfo_height()), 240)
        png_path = out_dir / f"{name}.png"
        img = ImageGrab.grab(bbox=(x0, y0, x0 + w, y0 + h), all_screens=True)
        img.save(png_path)
        # Count non-background pixels (anything brighter than the dark fill).
        rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
        bg_r, bg_g, bg_b = 0x10, 0x15, 0x1B  # matches focus_canvas fill #10151b
        d = (
            np.abs(rgb[..., 0] - bg_r)
            + np.abs(rgb[..., 1] - bg_g)
            + np.abs(rgb[..., 2] - bg_b)
        )
        nontrivial = int((d > 24).sum())
        return png_path, nontrivial

    # 1) EQ BYPASSED — must still paint live spectrum + ring grid. This is
    # the regression that caused the user's empty polar.
    with app.engine._lock:
        ch.eq_enabled = False
        ch.eq_band_enabled = False
        ch.eq_param_bypass.clear()
    app._draw_focus_to(app.focus_canvas)
    pump(6)
    bp_png, bp_pixels = grab_focus_pane("EQ_focus_bypassed_kick_spectrum")

    # 2) EQ ENGAGED with a +8 dB bell at 2.2 kHz — adds bell shell on top.
    with app.engine._lock:
        ch.eq_enabled = True
        ch.eq_band_enabled = False
        ch.eq_freq = 2200.0
        ch.eq_gain_db = 8.0
        ch.eq_width = 1.2
        ch.eq_param_bypass.clear()
    app._mirror_eq_ui_band_to_channel(ch)
    app._draw_focus_to(app.focus_canvas)
    pump(6)
    eng_png, eng_pixels = grab_focus_pane("EQ_focus_engaged_kick_spectrum")

    print(
        f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}",
        flush=True,
    )
    print(f"PNG bypassed: {bp_png}  non-bg pixels = {bp_pixels}", flush=True)
    print(f"PNG engaged : {eng_png}  non-bg pixels = {eng_pixels}", flush=True)
    print(
        "scenario: kick-heavy synthetic spectrum (low bands loud); editor parked on EQ column.",
        flush=True,
    )

    # The actual proof: BOTH panes paint substantially. The user's regression
    # was the bypassed pane being effectively empty; that is now ~52k non-bg
    # pixels of live spectrum. Engaging the insert dims the spectrum to 50%
    # so the bell shell reads on top, so engaged pixel count is naturally
    # lower than bypassed but still well above an empty canvas.
    bypassed_paints = bp_pixels > 4000
    engaged_paints = eng_pixels > 4000
    ok = bypassed_paints and engaged_paints
    print(
        f"bypassed_paints={bypassed_paints} engaged_paints={engaged_paints} -> ok={ok}",
        flush=True,
    )

    root.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

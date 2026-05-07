#!/usr/bin/env python3
"""Visible audible-attenuation proof for the mic-pre LPF.

Drives broadband white noise through ``ConsoleEngine._process_channel`` for a
few seconds with the engine analyzer running, then captures the actual Tk
polar pane (``focus_canvas``) parked on the PRE column. Three states:

    1. ``pre_enabled=False, lpf_enabled=False``  — dry signal baseline.
    2. ``pre_enabled=False, lpf_enabled=True``   — LPF row "on" but master OFF.
       Pre-fix this is what the user reported: cutoff ring drawn, no audio
       change. Post-fix the press handler auto-engages the master so this
       state should not be reachable from the UI; we hand-craft it for the
       regression check anyway.
    3. ``pre_enabled=True,  lpf_enabled=True, lpf_hz=400 Hz``  — engaged LPF.

For each state we:
  - Run ~80 process blocks of fresh white noise through the channel.
  - Analyze the processed buffer into ``master_channel.band_levels`` so the
    polar paints the live spectrum.
  - Save a real PNG grab of ``focus_canvas`` parked on the PRE column.
  - Capture per-band level snapshot to compare lows vs highs.

The proof: in state 3 the high-frequency bands collapse compared to state 1
(LPF actually removes audio energy above ~400 Hz). State 2 (UI lying) keeps
the high content because the DSP wrapper short-circuits.

Run from ``software/``::

    py -3 proof_lpf_audible_attenuation.py

Outputs: ``../Evidence/lpf-audible/``
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
    out_dir = repo / "Evidence" / "lpf-audible"
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(software))

    import tkinter as tk
    import numpy as np
    from PIL import ImageGrab

    import system_q_console as sq

    rng = np.random.default_rng(7)

    root = tk.Tk()
    root.geometry("1680x1020")
    root.title("System Q LPF audible-attenuation proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()
    root.focus_force()

    def pump(n: int = 10) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()

    pump()

    ch = app.engine.channels[0]
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    plist_pre = app._STAGE_GRID[pre_col][2]

    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.selected_stage_key = "pre"
    app.editor_stage_col = pre_col
    app.editor_unified_header_focus = False
    app.editor_param_row = plist_pre.index("LPF")

    # Cold preamp/EQ/dynamics path so only the LPF affects the spectrum.
    with app.engine._lock:
        ch.harmonics_enabled = False
        ch.eq_enabled = False
        ch.tone_enabled = False
        ch.gate_enabled = False
        ch.gate_band_enabled = False
        ch.comp_enabled = False
        ch.comp_band_enabled = False
        ch.tube = False
        ch.gain = 1.0
        ch.pan = 0.0

    block_n = sq.BLOCK_SIZE
    n_bands = int(sq.POL_BANDS)

    def drive_and_capture(name: str) -> dict:
        # Reset master analyzer, drive ~80 blocks of fresh noise so the
        # rolling band_levels lock onto the post-LPF spectrum.
        app.engine.master_channel.band_levels[:] = 0.0
        for _ in range(80):
            noise = (
                rng.standard_normal((block_n, 2)).astype(np.float32) * 0.18
            )
            processed = app.engine._process_channel(ch, noise)
            app.engine._analyze_channel(app.engine.master_channel, processed)
        bands = np.asarray(app.engine.master_channel.band_levels, dtype=np.float64).copy()

        app._draw_focus_to(app.focus_canvas)
        pump(8)
        time.sleep(0.05)
        fc = app.focus_canvas
        x0 = int(fc.winfo_rootx())
        y0 = int(fc.winfo_rooty())
        w = max(int(fc.winfo_width()), 240)
        h = max(int(fc.winfo_height()), 240)
        png = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x0, y0, x0 + w, y0 + h), all_screens=True).save(png)
        # Split spectrum into low (bottom half of bands) vs high (top half).
        # POL_BAND_CENTER_HZ is log-spaced from POL_LOW_HZ to POL_HIGH_HZ, so
        # the upper half corresponds to ~the upper octaves where an LPF should bite.
        half = n_bands // 2
        low_avg = float(bands[:half].mean())
        high_avg = float(bands[half:].mean())
        return {
            "png": png,
            "bands": bands,
            "low_avg": low_avg,
            "high_avg": high_avg,
            "high_over_low": high_avg / max(low_avg, 1e-9),
        }

    # State 1: dry baseline.
    with app.engine._lock:
        ch.pre_enabled = False
        ch.lpf_enabled = False
        ch.hpf_enabled = False
    s1 = drive_and_capture("01_dry_baseline")

    # State 2: regression scenario — flag set but master forced off.
    with app.engine._lock:
        ch.pre_enabled = False
        ch.lpf_enabled = True
        ch.lpf_hz = 400.0
        ch.hpf_enabled = False
    s2 = drive_and_capture("02_lpf_flag_only_master_off")

    # State 3: real UI press path — LPF press auto-engages pre_enabled, polar
    # paints the cutoff ring AND audio path applies the filter.
    with app.engine._lock:
        ch.pre_enabled = False
        ch.lpf_enabled = False
        ch.lpf_hz = 400.0
        ch.hpf_enabled = False
    app.editor_unified_header_focus = False
    app.editor_param_row = plist_pre.index("LPF")
    app._press_unified_editor_cell()
    assert ch.lpf_enabled, "press handler must engage lpf_enabled"
    assert ch.pre_enabled, "press handler must auto-engage pre_enabled"
    s3 = drive_and_capture("03_lpf_engaged_via_ui_400hz")

    print(f"BUILD={getattr(sq, 'SYSTEM_Q_BUILD_ID', '?')}", flush=True)
    print("scenario: white-noise driven through channel 0, 400 Hz LPF cutoff", flush=True)
    print(
        "state          | low band avg | high band avg | high/low ratio | png",
        flush=True,
    )
    for label, s in (("1 dry         ", s1), ("2 flag_only   ", s2), ("3 ui_engaged  ", s3)):
        print(
            f"{label} | {s['low_avg']:>12.4f} | {s['high_avg']:>13.4f} | "
            f"{s['high_over_low']:>14.4f} | {s['png'].name}",
            flush=True,
        )

    # The actual audible-attenuation proof: state 3's high bands must collapse
    # vs state 1, while state 2 (master off) must NOT attenuate (DSP wrapper
    # short-circuits on the user's pre-fix code path).
    s1_high = s1["high_avg"]
    s2_high = s2["high_avg"]
    s3_high = s3["high_avg"]
    audible_drop = s3_high < s1_high * 0.55
    master_off_inert = abs(s2_high - s1_high) < s1_high * 0.20
    ok = audible_drop and master_off_inert
    print(
        f"audible_drop={audible_drop} master_off_inert={master_off_inert} -> ok={ok}",
        flush=True,
    )
    print(f"PNG dir: {out_dir}", flush=True)

    root.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

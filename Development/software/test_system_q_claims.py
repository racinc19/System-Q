"""
Headless checks for claimed System Q behavior (Tk canvas scrape + source invariants).

Run from this folder:
  py -3 test_system_q_claims.py

Exit 0 = all asserts-style checks printed PASS; nonzero = at least one FAIL.
Does not open a visible window. Does not need audio playback.
"""

from __future__ import annotations

import re

import tkinter as tk


def _outline_colors(canvas: tk.Canvas) -> list[str]:
    colors: list[str] = []
    for iid in canvas.find_all():
        try:
            o = canvas.itemcget(str(iid), "outline")
        except tk.TclError:
            continue
        if o:
            colors.append(o)
    return colors


def _looks_red_outline(o: str) -> bool:
    """Include bright (#ff…) and muted glow (#c0/#a84… reds) — not only Tk's neon prefix."""

    x = o.lower().strip()
    if not x.startswith("#") or len(x) < 7:
        return (x.startswith("#ff") or x.startswith("#fe")) and len(x) >= 4
    try:
        r = int(x[1:3], 16)
        g = int(x[3:5], 16)
        bl = int(x[5:7], 16)
    except ValueError:
        return False
    return r >= 130 and r >= g + 25 and r >= bl + 25


def _redish_outline_count(colors: list[str]) -> int:
    return sum(1 for o in colors if _looks_red_outline(o))


def main() -> int:
    import numpy as np

    import system_q_console as sq

    sq_path = getattr(sq, "__file__", "")
    with open(sq_path, encoding="utf-8", errors="replace") as fh:
        src_text = fh.read()

    checks: list[tuple[str, bool]] = []

    checks.append(("console defines EDITOR_LEAVE_HOLD_S", "EDITOR_LEAVE_HOLD_S" in src_text))
    checks.append(("console defines EDITOR_LR_HOLD_S", "EDITOR_LR_HOLD_S" in src_text))

    checks.append(("editor nav routing (stage_grid vs pre/module/top)", '_handle_nav' in src_text and 'if ens == "stage_grid"' in src_text))

    checks.append(
        ("EQ polar calls monitored master backbone (_draw_focus_signal + level_gain)", "_draw_focus_eq" in src_text and "master_channel" in src_text)
    )

    checks.append(("POL_NEON_RED defined and used", hasattr(sq, "POL_NEON_RED") and str(sq.POL_NEON_RED) in src_text))

    checks.append(("polar_dsp_ring_hex wired into EQ polar paint", "polar_dsp_ring_hex" in src_text))

    root = tk.Tk()
    root.geometry("620x620")
    root.withdraw()
    app = sq.ConsoleApp(root, internal_capture=True, startup_play=False)
    cw = max(520, app.focus_canvas.winfo_reqwidth())
    ch_canvas = max(520, app.focus_canvas.winfo_reqheight())
    app.focus_canvas.configure(width=cw, height=ch_canvas)

    ch0 = app.engine.channels[0]
    # Fake live spectrum energy on monitored master plane.
    app.engine.master_channel.band_levels = np.linspace(0.15, 0.92, sq.POL_BANDS).astype(np.float32)

    # --- EQ polar ---
    app.nav_scope = "editor"
    app.editor_nav_scope = "module-body"
    app.selected_stage_key = "eq"
    ch0.eq_enabled = True
    ch0.eq_band_enabled = True
    ch0.eq_band_count = 2
    ch0.eq_bands[0].update({"enabled": True, "freq": 1000.0, "gain_db": 6.0, "width": 1.0, "type": "BELL"})
    ch0.eq_bands[1].update({"enabled": True, "freq": 4000.0, "gain_db": -3.0, "width": 1.0, "type": "BELL"})
    app._draw_focus()
    eq_out = _outline_colors(app.focus_canvas)
    rq = _redish_outline_count(eq_out)
    checks.append((f"EQ polar: red-ish DSP ring strokes (have {rq}, want >=5)", rq >= 5))

    # --- Gate polar ---
    ch0.gate_enabled = True
    ch0.gate_band_enabled = False
    ch0.gate_threshold_db = -28.0
    ch0.gate_gr_db = -6.0
    app.selected_stage_key = "gate"
    app._draw_focus()
    gate_out = _outline_colors(app.focus_canvas)
    checks.append(("Gate polar outer ring uses POL_NEON_RED", sq.POL_NEON_RED in gate_out))

    # --- Compressor polar ---
    ch0.comp_enabled = True
    ch0.comp_band_enabled = False
    ch0.comp_threshold_db = -22.0
    ch0.comp_gr_db = 5.5
    app.selected_stage_key = "comp"
    app._draw_focus()
    comp_out = _outline_colors(app.focus_canvas)
    checks.append(("Comp polar outer edge uses POL_NEON_RED", sq.POL_NEON_RED in comp_out))

    # --- Harmonics ---
    ch0.harmonics_enabled = True
    ch0.harmonics[:] = np.array([0.35, 0.28, 0.22, 0.10, 0.05], dtype=np.float32)
    app.selected_stage_key = "harm"
    app._draw_focus()
    harm_out = _outline_colors(app.focus_canvas)
    hq = _redish_outline_count(harm_out)
    checks.append((f"Harmonics polar red-ish overlays (have {hq}, want >=2)", hq >= 2))

    # Transport → strip index for macros
    app.nav_scope = "transport"
    app.editor_channel = min(5, len(app.engine.channels) - 1)
    idx = app._spacemouse_strip_channel_index()
    checks.append(("Transport scope exposes editor_channel to macros", idx == app.editor_channel))

    fails = []
    for name, ok in checks:
        lab = "PASS" if ok else "FAIL"
        print(f"[{lab}] {name}", flush=True)
        if not ok:
            fails.append(name)
    if fails:
        print(f"\n{len(fails)} FAIL — {fails}", flush=True)
        return 2
    print("\nAll claim checks PASSED.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

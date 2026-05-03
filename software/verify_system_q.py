"""
One-shot sanity checks for system_q_console.py (DSP + Tk bootstrap + EQ BND).

IMPORTANT: This script does NOT open the console window. It uses a hidden Tk root
(root.withdraw()) so tests can run unattended. To actually see and use the polar
EQ UI, run:

  py -3 system_q_console.py

(or double-click ``run_system_q_console.bat`` in this folder.)

(For a console window opened from Explorer, scroll to the terminal text for the
printed ``System Q [nav-YYYYMMDD] …`` line — that confirms this ``system_q_console.py``
file was loaded.)

Also asserts **section-scoped** strip/transport cardinals. Programmatic scope jumps
(for tests only) remain in :meth:`ConsoleApp._run_cardinal_double_tap_macro`; live
SpaceMouse XY is plain LRUD + Z press / long engage.

Run verifier from this directory:
  py -3 verify_system_q.py
Exit 0 = all asserts passed; nonzero = failure with traceback.
"""
from __future__ import annotations

import os
import sys

import numpy as np


def main() -> int:
    import tkinter as tk

    import system_q_console as sq

    assert getattr(sq, "SYSTEM_Q_BUILD_ID", ""), "build id missing — wrong system_q_console import?"

    print(
        "verify_system_q: headless checks only (NO GUI). "
        "For the console window: py -3 system_q_console.py",
        flush=True,
    )

    rng = np.random.default_rng(0)
    engine = sq.ConsoleEngine()
    ch = engine.channels[0]
    assert (
        not ch.eq_enabled and abs(ch.eq_gain_db) < 0.02 and abs(ch.eq_freq - 2200.0) < 0.1
    ), "engine ships inserts bypassed (+12 kick demo preset removed)"
    assert not ch.solo and not engine.channels[1].solo, "no default solo — full mix on launch"
    x = rng.standard_normal((sq.BLOCK_SIZE, 2), dtype=np.float32) * 0.08

    def proc() -> np.ndarray:
        return engine._process_channel(ch, x.copy())

    ch.pre_enabled = False
    ch.harmonics_enabled = False
    ch.eq_enabled = False
    ch.tone_enabled = False
    ch.comp_enabled = False
    ch.gate_enabled = False

    silent = proc()
    ch.gate_enabled = True
    ch.gate_threshold_db = -20.0
    ch.gate_ratio = 10.0
    ch.gate_makeup = 1.0
    gated = proc()
    assert not np.allclose(gated, silent), "gate bypass vs engaged should differ"

    ch.comp_enabled = True
    ch.comp_threshold_db = -30.0
    ch.comp_ratio = 4.0
    ch.comp_makeup = 1.0
    both = proc()
    ch.gate_enabled = False
    comp_only = proc()
    assert not np.allclose(both, comp_only), "compressor path should respond when gate toggled"

    ch2 = sq.ChannelState(name="t", path=sq.ROOT_DIR)
    ch2.pre_enabled = False
    ch2.eq_enabled = True
    ch2.eq_band_enabled = True
    ch2.eq_band_count = 2
    ch2.eq_bands[0].update({"enabled": True, "freq": 200.0, "gain_db": 6.0, "width": 1.0})
    ch2.eq_bands[1].update({"enabled": True, "freq": 4000.0, "gain_db": -3.0, "width": 1.2})
    yb = engine._process_channel(ch2, x.copy())

    ch2.eq_band_enabled = False
    ch2.eq_freq = 1000.0
    ch2.eq_gain_db = 6.0
    ch2.eq_width = 1.0
    ys = engine._process_channel(ch2, x.copy())
    assert not np.allclose(yb, ys), "multi-band stacked EQ vs single scalar path should differ"

    root = tk.Tk()
    root.withdraw()
    # Tall enough editor column that the stage grid keeps its nominal height while
    # ``focus_canvas`` retains room for EQ / dynamics plots (layout is height-competitive).
    root.geometry("1200x980")
    app = sq.ConsoleApp(root, startup_play=False)
    assert getattr(app, "editor_title", None) is not None, "ConsoleApp must build UI (editor_title)"

    app.editor_nav_scope = "stage_grid"
    app.nav_scope = "editor"
    app.selected_stage_key = "eq"
    ch3 = app._current_channel()
    ch3.eq_band_enabled = True
    app._autosize_editor_canvas_height()
    h_eq_multiband_on = int(app.editor_canvas.cget("height"))
    ch3.eq_band_enabled = False
    app._autosize_editor_canvas_height()
    h_eq_multiband_off = int(app.editor_canvas.cget("height"))
    assert h_eq_multiband_on == h_eq_multiband_off, (
        "EQ multiband must not resize the editor canvas (_multiband_visual_expanded "
        "stable for eq so the unified grid does not jump)"
    )

    eq_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "eq")
    app.editor_stage_col = eq_col
    app.editor_param_row = app._STAGE_GRID[eq_col][2].index("BND")
    ch3.eq_band_enabled = False
    ch3.eq_band_count = 1
    ch3.eq_enabled = False
    ch3.eq_freq = 500.0
    ch3.eq_gain_db = 2.0
    app._press_unified_editor_cell()
    assert ch3.eq_band_enabled and ch3.eq_enabled, "first BND press should enable multi-band EQ + insert"
    assert ch3.eq_band_count >= 2, "multi-band layout must expose ≥2 tiers so BND twist can rotate bands"

    # Long-cap (engage_toggle) must toggle unified bypass in normal mixing — never require SYSTEM_Q_AGENT_PROOF.
    gte_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "gate")
    plist_g = app._STAGE_GRID[gte_ix][2]
    prev_proof = os.environ.pop("SYSTEM_Q_AGENT_PROOF", None)
    try:
        app.nav_scope = "editor"
        app.editor_nav_scope = "stage_grid"
        app.editor_channel = 0
        app.editor_stage_col = gte_ix
        app.editor_param_row = plist_g.index("GAN")
        app.editor_unified_header_focus = False
        app.selected_stage_key = "gate"
        cg = app.engine.channels[0]
        cg.gate_enabled = True
        cg.gate_makeup = 2.5
        cg.gate_param_bypass.clear()
        app._handle_cap_engage_toggle()
        assert cg.gate_param_bypass.get("GAN") is True, "cap engage_toggle must bypass GAN without agent-proof env"
        app._handle_cap_engage_toggle()
        assert cg.gate_param_bypass.get("GAN") is not True
    finally:
        if prev_proof:
            os.environ["SYSTEM_Q_AGENT_PROOF"] = prev_proof

    # Only the painted unified grid exists; stale module-stage + PRESS must not toggle coarse comp.
    cmp_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "comp")
    plist_c = app._STAGE_GRID[cmp_ix][2]
    ch4 = app.engine.channels[0]
    ch4.comp_enabled = True
    ch4.comp_param_bypass.clear()
    app.nav_scope = "editor"
    app.editor_nav_scope = "module-stage"
    app.module_editor_column = 1
    app.selected_stage_key = "comp"
    app.editor_channel = 0
    app.editor_stage_col = cmp_ix
    app.editor_param_row = plist_c.index("THR")
    app.editor_unified_header_focus = False
    app._handle_nav("press")
    assert ch4.comp_enabled is True, "stale module-stage must not strip-bypass comp on matrix PRESS"
    assert ch4.comp_param_bypass.get("THR") is True, "matrix PRESS must hit per-param bypass"
    app._handle_nav("press")
    assert ch4.comp_param_bypass.get("THR") is not True

    # Highlight column wins: stale polar + wrong legacy nav scope must align to matrix cell.
    app.editor_nav_scope = "body"
    app.editor_stage_col = cmp_ix
    app.selected_stage_key = "eq"
    app.editor_param_row = plist_c.index("GAN")
    app._coerce_editor_nav_to_unified_stage_grid()
    assert app.editor_nav_scope == "stage_grid", "body scope must coerce to unified routing"
    assert app.selected_stage_key == "comp" and app.editor_stage_col == cmp_ix

    # Orphan scopes "stage" / "" swallowed cap/keyboard PRESS (no unified handler routed).
    app.editor_nav_scope = "stage"
    app.editor_stage_col = cmp_ix
    app.selected_stage_key = "eq"
    app.editor_param_row = plist_c.index("RLS")
    app._coerce_editor_nav_to_unified_stage_grid()
    assert app.editor_nav_scope == "stage_grid"
    assert app.selected_stage_key == "comp" and app.editor_stage_col == cmp_ix

    app.editor_nav_scope = ""
    app.editor_stage_col = gte_ix
    app.selected_stage_key = "comp"
    app.editor_param_row = plist_g.index("ATK")
    app._coerce_editor_nav_to_unified_stage_grid()
    assert app.editor_nav_scope == "stage_grid"
    assert app.selected_stage_key == "gate"

    app.nav_scope = "editor"
    app.editor_nav_scope = "faders"
    app.editor_stage_col = 3
    app._coerce_editor_nav_to_unified_stage_grid()
    assert app.editor_nav_scope == "faders", "editor fader sub-scope must not coerce to grid"

    col_wrap = next(i for i, row in enumerate(app._STAGE_GRID) if len(row[2]) >= 2)
    plist = app._STAGE_GRID[col_wrap][2]
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.editor_stage_col = col_wrap
    app.editor_param_row = len(plist) - 1
    app.selected_stage_key = app._STAGE_GRID[col_wrap][0]
    app.editor_unified_header_focus = False
    app._handle_unified_editor_nav("down")
    assert app.nav_scope == "editor", "unified grid NAV down past last row must stay in editor"
    assert app.editor_unified_header_focus is True, "unified grid NAV down off bottom moves to column header focus"
    assert app.editor_param_row == len(plist) - 1, "param row index preserved when stepping to header"

    app._handle_unified_editor_nav("down")
    assert app.editor_unified_header_focus is False, "unified grid NAV down from header returns to params"
    assert app.editor_param_row == 0, "unified grid NAV down from header lands on row 0"

    # HEADER lane LEFT/RIGHT must stay on headers — old code used neighbor_row clamp so a deep
    # ``editor_param_row`` jumped into the wrong vertical band after column change.
    cmp_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "comp")
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    plist_cmp = app._STAGE_GRID[cmp_col][2]
    app.editor_stage_col = cmp_col
    app.editor_param_row = len(plist_cmp) - 1
    app.editor_unified_header_focus = False
    app.selected_stage_key = "comp"
    app._handle_unified_editor_nav("down")
    assert app.editor_unified_header_focus is True
    app._handle_unified_editor_nav("left")
    assert app.editor_stage_col == cmp_col - 1 and app.editor_unified_header_focus is True
    assert app.selected_stage_key == "gate"
    app._handle_unified_editor_nav("left")
    assert app.selected_stage_key == "harm"
    app._handle_unified_editor_nav("left")
    assert app.editor_stage_col == pre_col and app.editor_unified_header_focus is True
    plist_pre = app._STAGE_GRID[pre_col][2]
    assert app.editor_param_row == len(plist_pre) - 1, "header lateral clamps row to shorter column"

    ply_r = ply_c = None
    for r, c, key, *_ in app._TRANSPORT_BUTTONS:
        if key == "play":
            ply_r, ply_c = int(r), int(c)
            break
    assert ply_r is not None and ply_c is not None, "_TRANSPORT_BUTTONS must define play"

    app.nav_scope = "console"
    app.console_row = "stages"
    app.selected_channel = 0
    app.editor_channel = 0
    app.selected_stage_key = "eq"
    app._transport_entered_from = None
    app._normalize_console_selection()
    nav_span = app._channel_nav_span()

    # Strip L/R wrap across inputs + master.
    app._handle_console_nav("left")
    assert app.nav_scope == "console" and app.selected_channel == nav_span - 1, (
        "strip LEFT at first channel must wrap to last strip"
    )
    app._handle_console_nav("right")
    assert app.nav_scope == "console" and app.selected_channel == 0, (
        "strip RIGHT from last channel must wrap to first"
    )
    app.selected_channel = nav_span - 1
    app._handle_console_nav("right")
    assert app.nav_scope == "console" and app.selected_channel == 0, (
        "strip RIGHT at last channel must wrap to first strip"
    )
    app.console_row = "footer"
    app._handle_console_nav("down")
    assert app.nav_scope == "console" and app.console_row == "record", (
        "footer DOWN must stay on strips (wrap to REC row), not open transport"
    )

    app._enter_transport_panel(0, 0, source="verify")
    app._handle_transport_nav("up")
    assert app.nav_scope == "console" and app.console_row == "footer", (
        "transport UP from top row must exit to mixer footer"
    )
    assert app.selected_channel == 0, "transport exit should align selected strip with focus col"
    app._enter_transport_panel(1, 3, source="verify")
    app._handle_transport_nav("up")
    assert app.nav_scope == "transport" and app.transport_focus_row == 0, (
        "transport UP from row 1 moves to row 0"
    )

    app._enter_transport_panel(0, 0, source="verify")
    app._handle_transport_nav("left")
    assert app.nav_scope == "console" and app.console_row == "footer", (
        "transport LEFT at left edge must exit"
    )
    last_tc = app.TRANSPORT_COLS - 1
    app._enter_transport_panel(0, last_tc, source="verify")
    app._handle_transport_nav("right")
    assert app.nav_scope == "console" and app.console_row == "footer", (
        "transport RIGHT at right edge must exit"
    )
    expect_strip = max(0, min(nav_span - 1, last_tc))
    assert app.selected_channel == expect_strip, (
        "transport exit: strip index clamps to min(last strip, transport col)"
    )

    app.nav_scope = "console"
    app.console_row = "stages"
    app.selected_channel = 0
    app.editor_channel = 0
    app.selected_stage_key = "eq"
    app._transport_entered_from = None
    app._normalize_console_selection()

    app._run_cardinal_double_tap_macro("right")
    assert app.nav_scope == "editor", "DOUBLE RIGHT macro must land in editor"
    assert getattr(app, "editor_nav_scope", "") == "stage_grid", (
        "DOUBLE RIGHT macro must use unified editor stage_grid"
    )

    app._run_cardinal_double_tap_macro("left")
    assert app.nav_scope == "faders", "DOUBLE LEFT macro must land on faders scope"
    assert app.fader_focus_channel == 0, "DOUBLE LEFT must focus fader channel 0 from strip 0"

    app._run_cardinal_double_tap_macro("up")
    assert app.nav_scope == "console" and app.console_row == "stages", (
        "DOUBLE UP macro must land on channel strips (stages row)"
    )
    assert app.selected_channel == 0, "DOUBLE UP must preserve strip channel index"

    app._run_cardinal_double_tap_macro("down")
    assert app.nav_scope == "transport", "DOUBLE DOWN macro must land in transport"
    assert app.transport_focus_row == ply_r and app.transport_focus_col == ply_c, (
        "DOUBLE DOWN macro must focus PLY cell"
    )
    assert getattr(app, "_transport_entered_from", None) == "spacemouse_double_down", (
        "transport entered from spacemouse double-down"
    )

    root.destroy()
    print("verify_system_q: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

    # Mic preamp LPF / HPF behave like textbook channel filters:
    #   LPF passes frequencies BELOW lpf_hz (sweep down -> darker).
    #   HPF passes frequencies ABOVE hpf_hz (sweep up   -> thinner low end).
    # Defaults sit at the wide-open edges so engaging either is silent until swept.
    assert abs(ch.lpf_hz - sq.POL_HIGH_HZ) < 0.5, (
        "LPF default must be wide open at the top of the audible band"
    )
    assert abs(ch.hpf_hz - sq.POL_LOW_HZ) < 0.5, (
        "HPF default must be wide open at the bottom of the audible band"
    )
    block_n = sq.BLOCK_SIZE
    t_axis = np.arange(block_n, dtype=np.float32) / float(sq.SAMPLE_RATE)
    tone_low = (np.sin(2.0 * np.pi * 50.0 * t_axis) * 0.4).astype(np.float32)
    tone_high = (np.sin(2.0 * np.pi * 5000.0 * t_axis) * 0.4).astype(np.float32)
    tone_low_block = np.stack([tone_low, tone_low], axis=1)
    tone_high_block = np.stack([tone_high, tone_high], axis=1)

    def rms(buf: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(buf), dtype=np.float64)))

    pre_ch = sq.ChannelState(name="preamp_filter_test", path=sq.ROOT_DIR)
    pre_ch.pre_enabled = True
    pre_ch.gain = 1.0
    pre_ch.lpf_enabled = True
    pre_ch.lpf_hz = 800.0
    pre_ch.hpf_enabled = False
    lpf_high = engine._process_channel(pre_ch, tone_high_block.copy())
    lpf_low = engine._process_channel(pre_ch, tone_low_block.copy())
    assert rms(lpf_high) < rms(tone_high_block) * 0.4, (
        "LPF at 800 Hz must attenuate a 5 kHz tone (lowpass passes lows, kills highs)"
    )
    assert rms(lpf_low) > rms(tone_low_block) * 0.6, (
        "LPF at 800 Hz must pass a 50 Hz tone roughly intact"
    )

    pre_ch.lpf_enabled = False
    pre_ch.hpf_enabled = True
    pre_ch.hpf_hz = 800.0
    hpf_low = engine._process_channel(pre_ch, tone_low_block.copy())
    hpf_high = engine._process_channel(pre_ch, tone_high_block.copy())
    assert rms(hpf_low) < rms(tone_low_block) * 0.4, (
        "HPF at 800 Hz must attenuate a 50 Hz tone (highpass passes highs, kills lows)"
    )
    assert rms(hpf_high) > rms(tone_high_block) * 0.6, (
        "HPF at 800 Hz must pass a 5 kHz tone roughly intact"
    )

    # Wide-open defaults are inaudible: engaging either filter at the rest position
    # leaves the signal essentially untouched.
    pre_ch.lpf_enabled = True
    pre_ch.lpf_hz = float(sq.POL_HIGH_HZ)
    pre_ch.hpf_enabled = True
    pre_ch.hpf_hz = float(sq.POL_LOW_HZ)
    wideopen_high = engine._process_channel(pre_ch, tone_high_block.copy())
    wideopen_low = engine._process_channel(pre_ch, tone_low_block.copy())
    assert rms(wideopen_high) > rms(tone_high_block) * 0.85
    assert rms(wideopen_low) > rms(tone_low_block) * 0.85, (
        "wide-open LPF+HPF must be effectively transparent"
    )

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

    ch.comp_band_enabled = True
    ch.comp_dyn_band_count = 2
    ch.comp_dyn_ui_band = 0
    ch.comp_dyn_bands[0].update(
        {
            "threshold_db": -28.0,
            "ratio": 4.0,
            "attack_ms": 8.0,
            "release_ms": 120.0,
            "makeup": 1.0,
            "freq": 3000.0,
            "width_oct": 4.0,
            "enabled": True,
        }
    )
    ch.comp_threshold_db = -6.0
    ch.comp_env = 0.0
    mb_a = proc()
    ch.comp_threshold_db = -50.0
    ch.comp_env = 0.0
    mb_b = proc()
    assert np.allclose(mb_a, mb_b), "CMP BND on must not follow stray ch.comp_threshold_db (tier is authoritative)"

    cbd0 = ch.comp_dyn_bands[0]
    engine.write_comp_dynamics(
        ch,
        -50.0,
        float(cbd0["ratio"]),
        float(cbd0["attack_ms"]),
        float(cbd0["release_ms"]),
        float(cbd0["makeup"]),
    )
    ch.comp_env = 0.0
    mb_c = proc()
    assert not np.allclose(mb_a, mb_c), "write_comp_dynamics must steer DSP when CMP BND sidechain is on"

    ch.comp_band_enabled = False
    ch.comp_dyn_band_count = 1
    ch.comp_dyn_ui_band = 0
    ch.comp_threshold_db = -30.0
    ch.comp_ratio = 4.0
    ch.comp_attack_ms = 8.0
    ch.comp_release_ms = 120.0
    ch.comp_makeup = 1.0

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

    # PRE column: pressing LPF / HPF / PHS rows must auto-engage ``pre_enabled``
    # so the DSP wrapper actually runs (otherwise the polar paints a cutoff ring
    # while the audio path bypasses the filter — the user's reported regression).
    pre_col = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "pre")
    plist_pre = app._STAGE_GRID[pre_col][2]
    pre_ch = app._current_channel()
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_unified_header_focus = False
    app.editor_stage_col = pre_col
    app.selected_stage_key = "pre"
    pre_ch.pre_enabled = False
    pre_ch.lpf_enabled = False
    pre_ch.hpf_enabled = False
    pre_ch.phase = False
    app.editor_param_row = plist_pre.index("LPF")
    app._press_unified_editor_cell()
    assert pre_ch.lpf_enabled and pre_ch.pre_enabled, (
        "LPF row press must auto-engage pre_enabled so DSP runs"
    )
    app.editor_param_row = plist_pre.index("HPF")
    app._press_unified_editor_cell()
    assert pre_ch.hpf_enabled and pre_ch.pre_enabled, (
        "HPF row press must auto-engage pre_enabled"
    )
    app.editor_param_row = plist_pre.index("PHS")
    app._press_unified_editor_cell()
    assert pre_ch.phase and pre_ch.pre_enabled, (
        "PHS row press must auto-engage pre_enabled"
    )
    # Header coarse bypass clears DSP-gated rows so re-engage is predictable.
    app.editor_unified_header_focus = True
    app._press_unified_editor_cell()
    assert not pre_ch.pre_enabled
    assert not pre_ch.lpf_enabled and not pre_ch.hpf_enabled and not pre_ch.phase, (
        "PRE header coarse bypass must clear PHS/LPF/HPF flags"
    )
    app.editor_unified_header_focus = False

    # Engine path: LPF must attenuate a 5 kHz tone whenever ``lpf_enabled`` is on,
    # independent of ``pre_enabled`` (PRE column master must not silence the filter).
    pre_ch.harmonics_enabled = False
    pre_ch.eq_enabled = False
    pre_ch.tone_enabled = False
    pre_ch.gate_enabled = False
    pre_ch.gate_band_enabled = False
    pre_ch.comp_enabled = False
    pre_ch.comp_band_enabled = False
    pre_ch.gain = 1.0
    n_blk = sq.BLOCK_SIZE
    t_axis2 = np.arange(n_blk, dtype=np.float32) / float(sq.SAMPLE_RATE)
    tone_5k = (np.sin(2.0 * np.pi * 5000.0 * t_axis2) * 0.4).astype(np.float32)
    tone_5k_block = np.stack([tone_5k, tone_5k], axis=1)

    def _rms5(y: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(y))))

    pre_ch.pre_enabled = True
    pre_ch.lpf_enabled = False
    pre_ch.lpf_hz = 800.0
    pre_ch.lpf_state = None
    out_dry = engine._process_channel(pre_ch, tone_5k_block.copy())
    rms_dry = _rms5(out_dry)

    pre_ch.pre_enabled = True
    pre_ch.lpf_enabled = True
    pre_ch.lpf_hz = 800.0
    pre_ch.lpf_state = None
    out_master_on = engine._process_channel(pre_ch, tone_5k_block.copy())
    rms_on = _rms5(out_master_on)

    pre_ch.pre_enabled = False
    pre_ch.lpf_enabled = True
    pre_ch.lpf_hz = 800.0
    pre_ch.lpf_state = None
    out_master_off = engine._process_channel(pre_ch, tone_5k_block.copy())
    rms_off = _rms5(out_master_off)

    assert rms_on < rms_dry * 0.5 and rms_off < rms_dry * 0.5, (
        "LPF at 800 Hz must attenuate a 5 kHz probe whether PRE master is on or off "
        f"(rms dry={rms_dry:.5f}, pre_on={rms_on:.5f}, pre_off={rms_off:.5f})"
    )
    pre_ch.pre_enabled = False
    pre_ch.lpf_enabled = False
    pre_ch.hpf_enabled = False
    pre_ch.phase = False

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

    # Polar must paint the live monitored spectrum on EVERY stage focus, even when
    # the focused insert (e.g. EQ) is bypassed. The user has to see what they're
    # hearing regardless of which column the editor is parked on. Per the
    # `polar-shows-focused-channel-not-master-mix` build, focus drawers paint the
    # FOCUSED channel's spectrum so per-channel inserts read accurately — inject
    # the test fixture into both master + focused for forward / backward compat.
    bypass_ch = app._current_channel()
    fake_spectrum = np.linspace(0.6, 0.05, len(bypass_ch.band_levels)).astype(
        bypass_ch.band_levels.dtype
    )
    app.engine.master_channel.band_levels = fake_spectrum.copy()
    bypass_ch.band_levels = fake_spectrum.copy()
    app.editor_canvas.update_idletasks()
    app.focus_canvas.update_idletasks()
    bypass_ch.eq_enabled = False
    app.selected_stage_key = "eq"
    app._draw_focus_to(app.focus_canvas)
    eq_bypass_items = len(app.focus_canvas.find_all())
    bypass_ch.eq_enabled = True
    app._draw_focus_to(app.focus_canvas)
    eq_engaged_items = len(app.focus_canvas.find_all())
    assert eq_bypass_items > 25, (
        "EQ focus with insert bypassed must still paint the live spectrum + ring grid "
        "(empty polar regression: blank canvas when channel ships with eq_enabled=False)"
    )
    # Engaged EQ adds bell/dip shells on top -> at least as many canvas items.
    assert eq_engaged_items >= eq_bypass_items
    bypass_ch.eq_enabled = False

    # Long-cap (engage_toggle) must coarse-toggle gate insert on dynamics caps — not per-param bypass.
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
        assert cg.gate_enabled is False, "engage_toggle must turn whole gate insert off"
        assert not cg.gate_param_bypass, "coarse gate off must clear per-param bypass residue"
        app._handle_cap_engage_toggle()
        assert cg.gate_enabled is True
    finally:
        if prev_proof:
            os.environ["SYSTEM_Q_AGENT_PROOF"] = prev_proof

    # CMP dynamics rows (THR/RAT/ATK/RLS/GAN) are EACH a coarse bypass key for the
    # whole insert. Press from active -> OFF (regular and freq-dep both cleared,
    # polar empties, no audio effect). Press from OFF -> regular insert engaged.
    cmp_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "comp")
    plist_c = app._STAGE_GRID[cmp_ix][2]
    ch4 = app.engine.channels[0]
    ch4.comp_enabled = True
    ch4.comp_band_enabled = False
    ch4.comp_dyn_band_count = 1
    for _b in ch4.comp_dyn_bands:
        _b["enabled"] = False
    ch4.comp_param_bypass.clear()
    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_channel = 0
    app.editor_stage_col = cmp_ix
    app.editor_param_row = plist_c.index("THR")
    app.editor_unified_header_focus = False
    app.selected_stage_key = "comp"

    app._press_unified_editor_cell()
    assert ch4.comp_enabled is False, "THR press from active -> bypass whole insert (off)"
    assert not ch4.comp_band_enabled
    assert not ch4.comp_param_bypass, "no per-param residue (params ARE the coarse bypass)"
    app._press_unified_editor_cell()
    assert ch4.comp_enabled is True, "THR press from off -> regular insert engages"
    assert not ch4.comp_band_enabled, "engaging from OFF lands in regular (no bands)"

    # Same coarse-bypass behavior on every other dynamics row (RAT/ATK/RLS/GAN).
    for row_label in ("RAT", "ATK", "RLS", "GAN"):
        ch4.comp_enabled = True
        ch4.comp_band_enabled = False
        ch4.comp_param_bypass.clear()
        app.editor_param_row = plist_c.index(row_label)
        app._press_unified_editor_cell()
        assert ch4.comp_enabled is False, f"CMP {row_label} press must coarse-bypass insert"
    ch4.comp_enabled = True

    # Long cap engage routes through the same handler -> identical coarse toggle.
    app.editor_param_row = plist_c.index("THR")
    app._handle_cap_engage_toggle()
    assert ch4.comp_enabled is False
    app._handle_cap_engage_toggle()
    assert ch4.comp_enabled is True

    # Strict either/or: BND from regular forces the regular insert OFF — the two
    # modes (regular full-band vs. freq-dep ladder) are independent processes and
    # only one can be flagged on at a time. Entering freq-dep mode disengages main.
    cb_ch = app.engine.channels[0]
    cb_ch.comp_enabled = True
    cb_ch.comp_band_enabled = False
    cb_ch.comp_dyn_band_count = 1
    cb_ch.comp_dyn_ui_band = 0
    for _b in cb_ch.comp_dyn_bands:
        _b["enabled"] = False
    cb_ch.comp_param_bypass.clear()
    app.editor_param_row = plist_c.index("BND")
    app._press_unified_editor_cell()
    assert cb_ch.comp_band_enabled, "CMP BND press from regular must enter freq-dep mode"
    assert not cb_ch.comp_enabled, (
        "either/or: entering freq-dep forces regular comp_enabled OFF"
    )
    assert cb_ch.comp_dyn_band_count >= 2
    assert all(
        bool(cb_ch.comp_dyn_bands[i].get("enabled", False))
        for i in range(int(cb_ch.comp_dyn_band_count))
    ), "freshly primed CMP bands must all be enabled"

    # FRQ is the **frequency selector**, not a master switch. It only flips the
    # selected band's ``enabled``. It MUST NOT engage or disengage comp_enabled.
    cb_ch.comp_dyn_ui_band = 1
    app.editor_param_row = plist_c.index("FRQ")
    app._press_unified_editor_cell()
    assert not cb_ch.comp_dyn_bands[1]["enabled"], "FRQ press disables selected band"
    assert cb_ch.comp_band_enabled, "with another band still enabled freq-dep stays on"
    assert not cb_ch.comp_enabled, "FRQ press never touches the regular flag"

    cb_ch.comp_dyn_ui_band = 0
    app._press_unified_editor_cell()
    assert not cb_ch.comp_dyn_bands[0]["enabled"]
    assert not cb_ch.comp_band_enabled, "all bands disabled -> freq-dep mode drops"
    assert not cb_ch.comp_enabled, (
        "FRQ collapse leaves comp_enabled untouched (was already False per either/or)"
    )

    # 'If main is on you can't turn on the frequency': FRQ row is *inert* in regular
    # mode — focus rehomes off it and the press handler's FRQ branch is a no-op
    # (so even a forced press can't engage a band or touch comp_enabled).
    cb_ch.comp_enabled = True
    cb_ch.comp_band_enabled = False
    cb_ch.comp_dyn_band_count = 1
    cb_ch.comp_dyn_ui_band = 0
    for _b in cb_ch.comp_dyn_bands:
        _b["enabled"] = False
    cb_ch.comp_param_bypass.clear()
    app.editor_nav_scope = "stage_grid"
    app.editor_unified_header_focus = False
    app.editor_stage_col = cmp_ix
    app.selected_stage_key = "comp"
    app.editor_param_row = plist_c.index("FRQ")
    app._unified_rehome_if_inert_sidechain_row()
    assert app.editor_param_row != plist_c.index("FRQ"), (
        "FRQ row must rehome away in regular mode (frequency selector unreachable)"
    )
    snapshot_enabled = bool(cb_ch.comp_enabled)
    snapshot_band = bool(cb_ch.comp_band_enabled)
    snapshot_bands = [bool(b.get("enabled", False)) for b in cb_ch.comp_dyn_bands]
    cb_ch._press_freq_row_test = None
    with app.engine._lock:
        if cb_ch.comp_band_enabled:
            app._toggle_dyn_band_engage(cb_ch, "comp")
    assert bool(cb_ch.comp_enabled) is snapshot_enabled, (
        "FRQ branch logic must not engage/disengage comp_enabled"
    )
    assert bool(cb_ch.comp_band_enabled) is snapshot_band
    assert [bool(b.get("enabled", False)) for b in cb_ch.comp_dyn_bands] == snapshot_bands

    # Coarse bypass works from band mode too: pressing any of THR/RAT/ATK/RLS/GAN
    # collapses the entire insert ('kill the effect, hide the polar'). The user
    # cannot directly turn on the regular insert while a frequency is engaged —
    # the press first kills band mode, then a *second* press would engage regular.
    cb_ch.comp_band_enabled = True
    cb_ch.comp_enabled = False
    cb_ch.comp_dyn_band_count = 2
    cb_ch.comp_dyn_ui_band = 0
    cb_ch.comp_dyn_bands[0]["enabled"] = True
    cb_ch.comp_dyn_bands[1]["enabled"] = True
    cb_ch.comp_param_bypass.clear()
    app.editor_param_row = plist_c.index("THR")
    app._press_unified_editor_cell()
    assert not cb_ch.comp_enabled, "THR press from band mode -> insert off (effect gone)"
    assert not cb_ch.comp_band_enabled, "band mode collapses with the insert"
    assert all(not b.get("enabled", False) for b in cb_ch.comp_dyn_bands), (
        "every band cleared on coarse bypass"
    )

    # Polar overlay rule: in band mode (regardless of comp_enabled), the selected
    # band's per-band ``enabled`` gates whether the freq ellipse draws.
    cb_ch.comp_enabled = False
    cb_ch.comp_band_enabled = True
    cb_ch.comp_dyn_band_count = 2
    cb_ch.comp_dyn_ui_band = 0
    cb_ch.comp_dyn_bands[0]["enabled"] = False
    cb_ch.comp_dyn_bands[1]["enabled"] = True
    assert app._comp_mode_band_enabled(cb_ch, "COMP")
    assert not app._comp_mode_active_band_engaged(cb_ch, "COMP"), (
        "selected band disabled -> polar must hide its frequency overlay"
    )
    cb_ch.comp_dyn_bands[0]["enabled"] = True
    assert app._comp_mode_active_band_engaged(cb_ch, "COMP")

    # Engine path: with strict either/or, the freq-dep ladder runs even when
    # comp_enabled is False, so long as comp_band_enabled is set and the selected
    # band has its per-band ``enabled`` true. With per-band enabled False the path
    # bypasses immediately (input passes through, comp_gr_db pinned to 0 dB).
    eng_ch = engine.channels[0]
    eng_ch.pre_enabled = False
    eng_ch.harmonics_enabled = False
    eng_ch.eq_enabled = False
    eng_ch.tone_enabled = False
    eng_ch.gate_enabled = False
    eng_ch.gate_band_enabled = False
    eng_ch.comp_enabled = False
    eng_ch.comp_band_enabled = True
    eng_ch.comp_dyn_band_count = 1
    eng_ch.comp_dyn_ui_band = 0
    eng_ch.comp_dyn_bands[0].update(
        {
            "threshold_db": -60.0,
            "ratio": 12.0,
            "attack_ms": 2.0,
            "release_ms": 50.0,
            "makeup": 4.0,
            "freq": 1500.0,
            "width_oct": 3.0,
            "enabled": True,
        }
    )
    eng_ch.comp_env = 0.0
    eng_ch.comp_gr_db = 0.0
    band_path_active = engine._process_channel(eng_ch, x.copy())
    band_path_active_gr = float(eng_ch.comp_gr_db)
    eng_ch.comp_dyn_bands[0]["enabled"] = False
    eng_ch.comp_env = 0.0
    eng_ch.comp_gr_db = 0.0
    band_path_disabled = engine._process_channel(eng_ch, x.copy())
    assert not np.allclose(band_path_active, band_path_disabled), (
        "freq-dep band must process audio when its per-band enabled is True even "
        "with comp_enabled=False (and skip when the selected band is disabled)"
    )
    assert band_path_active_gr > 0.05, (
        "freq-dep band path with comp_enabled=False must still drive comp_gr_db"
    )
    eng_ch.comp_band_enabled = False
    eng_ch.comp_dyn_band_count = 1
    eng_ch.comp_dyn_ui_band = 0
    eng_ch.comp_dyn_bands[0]["enabled"] = False
    eng_ch.comp_gr_db = 0.0

    # Same rules for the gate column.
    g_ix = next(i for i, row in enumerate(app._STAGE_GRID) if row[0] == "gate")
    plist_g2 = app._STAGE_GRID[g_ix][2]
    gb_ch = app.engine.channels[0]
    gb_ch.gate_enabled = True
    gb_ch.gate_band_enabled = False
    gb_ch.gate_dyn_band_count = 1
    for _b in gb_ch.gate_dyn_bands:
        _b["enabled"] = False
    gb_ch.gate_param_bypass.clear()
    app.editor_stage_col = g_ix
    app.selected_stage_key = "gate"

    app.editor_param_row = plist_g2.index("ATK")
    app._press_unified_editor_cell()
    assert gb_ch.gate_enabled is False, "GTE ATK press coarse-bypasses the gate insert"
    assert not gb_ch.gate_param_bypass, "no per-param residue"
    app._press_unified_editor_cell()
    assert gb_ch.gate_enabled is True

    app.editor_param_row = plist_g2.index("BND")
    app._press_unified_editor_cell()
    assert gb_ch.gate_band_enabled, "GTE BND from regular -> freq-dep mode"
    assert not gb_ch.gate_enabled, (
        "either/or: BND from regular forces gate_enabled OFF (mutual exclusion)"
    )

    # FRQ in band mode disables a single band; all-off drops band mode but
    # never touches gate_enabled (which was already False per either/or above).
    app.editor_param_row = plist_g2.index("FRQ")
    gb_ch.gate_dyn_ui_band = 0
    app._press_unified_editor_cell()
    gb_ch.gate_dyn_ui_band = 1
    app._press_unified_editor_cell()
    assert not gb_ch.gate_band_enabled, "all gate bands off -> freq-dep collapses"
    assert not gb_ch.gate_enabled, "gate_enabled stays False; FRQ never engages main"

    # FRQ row inert in regular gate mode: frequency selector unreachable.
    gb_ch.gate_enabled = True
    gb_ch.gate_band_enabled = False
    gb_ch.gate_dyn_band_count = 1
    gb_ch.gate_dyn_ui_band = 0
    for _b in gb_ch.gate_dyn_bands:
        _b["enabled"] = False
    app.editor_nav_scope = "stage_grid"
    app.editor_unified_header_focus = False
    app.editor_stage_col = g_ix
    app.selected_stage_key = "gate"
    app.editor_param_row = plist_g2.index("FRQ")
    app._unified_rehome_if_inert_sidechain_row()
    assert app.editor_param_row != plist_g2.index("FRQ"), (
        "GTE FRQ row must rehome away in regular mode"
    )

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

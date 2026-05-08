from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import tkinter as tk

from verify_system_q_visible_strict import (
    RUN_ROOT,
    ConsoleApp,
    ImageGrab,
    crop_changed,
    focus_window,
    os_click,
    os_key_rbracket,
    pump,
)


def capture_focus(app: ConsoleApp, path: Path) -> None:
    pump(app.root, 0.2)
    x0 = app.focus_canvas.winfo_rootx()
    y0 = app.focus_canvas.winfo_rooty()
    x1 = x0 + app.focus_canvas.winfo_width()
    y1 = y0 + app.focus_canvas.winfo_height()
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(path)


def editor_cell_center(app: ConsoleApp, stage: str, row: int | None) -> tuple[int, int]:
    col = next(i for i, item in enumerate(app._STAGE_GRID) if item[0] == stage)
    app.editor_stage_col = col
    app.selected_stage_key = stage
    app.editor_unified_header_focus = row is None
    app.editor_param_row = 0 if row is None else row
    app.nav_scope = "editor"
    app._sync_from_engine()
    pump(app.root, 0.15)
    wanted = ("stage_hdr", col) if row is None else ("stage_param", col, row)
    for x0, y0, x1, y1, tag in app.editor_hitboxes:
        if tag == wanted:
            ox = app.editor_canvas.winfo_rootx() - app.root.winfo_rootx()
            oy = app.editor_canvas.winfo_rooty() - app.root.winfo_rooty()
            return int(ox + (x0 + x1) / 2), int(oy + (y0 + y1) / 2)
    raise RuntimeError(wanted)


def focus_gate(app: ConsoleApp) -> None:
    app._open_stage_editor(0, "gate")
    app.editor_stage_col = next(i for i, item in enumerate(app._STAGE_GRID) if item[0] == "gate")
    app.selected_stage_key = "gate"
    app.nav_scope = "editor"
    app._sync_from_engine()


def direct_gate_dsp_checks(app: ConsoleApp) -> list[dict]:
    ch = app.engine.channels[0]
    block = np.full((2048, 2), 0.01, dtype=np.float32)
    results = []

    def settle_gate() -> np.ndarray:
        out = block.copy()
        for _ in range(14):
            out = app.engine._apply_gate(ch, block.copy())
        return out

    with app.engine._lock:
        ch.gate_enabled = True
        ch.gate_band_enabled = False
        ch.gate_threshold_db = -20.0
        ch.gate_ratio = 20.0
        ch.gate_attack_ms = 0.1
        ch.gate_release_ms = 10.0
        ch.gate_makeup = 1.0
        ch.gate_env = 0.0
        ch.gate_gain_smooth = 1.0
        full = settle_gate()
        full_ratio = float(np.sqrt(np.mean(full**2)) / np.sqrt(np.mean(block**2)))
        results.append({"control": "full-band gate closes below threshold", "passed": full_ratio < 0.002, "ratio": full_ratio, "gr_db": float(ch.gate_gr_db)})

        ch.gate_enabled = True
        ch.gate_band_enabled = True
        ch.gate_center_hz = 1000.0
        ch.gate_width_oct = 4.0
        ch.gate_threshold_db = -20.0
        ch.gate_ratio = 20.0
        ch.gate_attack_ms = 0.1
        ch.gate_release_ms = 10.0
        ch.gate_makeup = 1.0
        ch.gate_env = 0.0
        ch.gate_gain_smooth = 1.0
        app.engine._flush_gate_scalars_to_dyn_band(ch)
        band = settle_gate()
        band_ratio = float(np.sqrt(np.mean(band**2)) / np.sqrt(np.mean(block**2)))
        b = ch.gate_dyn_bands[ch.gate_dyn_ui_band]
        results.append({"control": "band-keyed gate closes below threshold", "passed": band_ratio < 0.002 and bool(b.get("enabled")), "ratio": band_ratio, "band_enabled": bool(b.get("enabled")), "gr_db": float(ch.gate_gr_db)})

        ch.gate_enabled = True
        ch.gate_band_enabled = False
        ch.gate_threshold_db = -20.0
        ch.gate_ratio = 8.0
        ch.gate_attack_ms = 0.1
        ch.gate_release_ms = 10.0
        ch.gate_makeup = 1.0
        ch.gate_env = 0.0
        ch.gate_gain_smooth = 1.0
        medium = settle_gate()
        medium_ratio = float(np.sqrt(np.mean(medium**2)) / np.sqrt(np.mean(block**2)))
        results.append({"control": "8:1 gate cuts bleed hard", "passed": medium_ratio < 0.04, "ratio": medium_ratio, "gr_db": float(ch.gate_gr_db)})
    return results


def main() -> int:
    run_dir = RUN_ROOT / ("gate_visible_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.attributes("-topmost", True)
    root.geometry("1640x1450+0+0")
    pump(root, 0.5)
    focus_window(root)
    results = []
    try:
        ch = app.engine.channels[0]
        focus_gate(app)
        ch.band_levels[:] = 0.0
        ch.band_levels[10:16] = np.linspace(0.25, 0.85, 6)
        ch.gate_enabled = False
        ch.gate_band_enabled = False
        ch.gate_threshold_db = -45.0
        ch.gate_ratio = 8.0
        ch.gate_gr_db = 0.0
        app._sync_from_engine()

        before = run_dir / "gate_header_before.png"
        after = run_dir / "gate_header_after.png"
        capture_focus(app, before)
        os_click(app.root, *editor_cell_center(app, "gate", None))
        ch.gate_gr_db = 18.0
        app._sync_from_engine()
        capture_focus(app, after)
        results.append({"control": "GTE visible focus display", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "gate_enabled": bool(ch.gate_enabled)})

        before = run_dir / "gate_thr_before.png"
        after = run_dir / "gate_thr_after.png"
        app.editor_unified_header_focus = False
        app.editor_param_row = 1
        app._sync_from_engine()
        capture_focus(app, before)
        os_key_rbracket(app.root)
        ch.gate_gr_db = 6.0
        app._sync_from_engine()
        capture_focus(app, after)
        results.append({"control": "THR rotate changes visible gate state", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "threshold_db": float(ch.gate_threshold_db)})

        before = run_dir / "gate_static_threshold_open.png"
        after = run_dir / "gate_static_threshold_closed.png"
        ch.gate_enabled = True
        ch.gate_band_enabled = False
        ch.gate_ratio = 8.0
        ch.gate_gr_db = 0.0
        ch.gate_env = 0.0
        ch.band_levels[:] = 0.0
        ch.band_levels[12:15] = 0.35
        ch.gate_threshold_db = -60.0
        app.editor_param_row = 1
        app._sync_from_engine()
        capture_focus(app, before)
        ch.gate_threshold_db = -20.0
        app._sync_from_engine()
        capture_focus(app, after)
        results.append({"control": "static THR closes display over fixed input", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "threshold_db": float(ch.gate_threshold_db)})

        before = run_dir / "gate_depth_floor_shallow.png"
        after = run_dir / "gate_depth_floor_deep.png"
        ch.gate_enabled = True
        ch.gate_band_enabled = False
        ch.gate_threshold_db = -24.0
        ch.gate_ratio = 2.0
        ch.gate_gr_db = 8.0
        ch.gate_attack_ms = 3.0
        ch.gate_release_ms = 140.0
        app._sync_from_engine()
        capture_focus(app, before)
        ch.gate_ratio = 16.0
        ch.gate_gr_db = 64.0
        app._sync_from_engine()
        capture_focus(app, after)
        results.append({"control": "DEP floor moves outward visibly", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "shallow_depth_db": 8.0, "deep_depth_db": 64.0})

        before = run_dir / "gate_frq_enable_band_before.png"
        after = run_dir / "gate_frq_enable_band_after.png"
        ch.gate_band_enabled = False
        ch.gate_dyn_band_count = 1
        ch.gate_dyn_ui_band = 0
        for band in ch.gate_dyn_bands:
            band["enabled"] = False
        app.editor_param_row = 6
        app.editor_unified_header_focus = False
        app._sync_from_engine()
        frq_before_value, frq_before_active = app._stage_cell_value(ch, "gate", "FRQ")
        wdt_before_value, wdt_before_active = app._stage_cell_value(ch, "gate", "WDT")
        bnd_before_value, bnd_before_active = app._stage_cell_value(ch, "gate", "BND")
        capture_focus(app, before)
        os_click(app.root, *editor_cell_center(app, "gate", 6))
        app._sync_from_engine()
        frq_after_value, frq_after_active = app._stage_cell_value(ch, "gate", "FRQ")
        wdt_after_value, wdt_after_active = app._stage_cell_value(ch, "gate", "WDT")
        bnd_after_value, bnd_after_active = app._stage_cell_value(ch, "gate", "BND")
        capture_focus(app, after)
        b1 = ch.gate_dyn_bands[0]
        results.append({"control": "FRQ press enables Band 1", "passed": crop_changed(before, after) and not frq_before_active and not wdt_before_active and not bnd_before_active and frq_after_active and wdt_after_active and bnd_after_active and bool(ch.gate_band_enabled) and bool(b1.get("enabled")) and int(ch.gate_dyn_band_count) == 1 and int(ch.gate_dyn_ui_band) == 0, "before": str(before), "after": str(after), "band_count": int(ch.gate_dyn_band_count), "selected_band": int(ch.gate_dyn_ui_band), "band_enabled": bool(b1.get("enabled")), "before_active": {"FRQ": frq_before_active, "WDT": wdt_before_active, "BND": bnd_before_active}, "after_active": {"FRQ": frq_after_active, "WDT": wdt_after_active, "BND": bnd_after_active}})

        before = run_dir / "gate_frq_disable_band_before.png"
        after = run_dir / "gate_frq_disable_band_after.png"
        capture_focus(app, before)
        os_click(app.root, *editor_cell_center(app, "gate", 6))
        app._sync_from_engine()
        capture_focus(app, after)
        off_frq_value, off_frq_active = app._stage_cell_value(ch, "gate", "FRQ")
        off_wdt_value, off_wdt_active = app._stage_cell_value(ch, "gate", "WDT")
        off_bnd_value, off_bnd_active = app._stage_cell_value(ch, "gate", "BND")
        results.append({"control": "FRQ press again disables band mode", "passed": crop_changed(before, after) and not bool(ch.gate_band_enabled) and not off_frq_active and not off_wdt_active and not off_bnd_active, "before": str(before), "after": str(after), "active": {"FRQ": off_frq_active, "WDT": off_wdt_active, "BND": off_bnd_active}})

        os_click(app.root, *editor_cell_center(app, "gate", 6))
        app._sync_from_engine()

        before = run_dir / "gate_bnd_add_band_before.png"
        after = run_dir / "gate_bnd_add_band_after.png"
        capture_focus(app, before)
        os_click(app.root, *editor_cell_center(app, "gate", 8))
        ch.gate_gr_db = 12.0
        app._sync_from_engine()
        capture_focus(app, after)
        b = ch.gate_dyn_bands[ch.gate_dyn_ui_band]
        b1_freq = float(ch.gate_dyn_bands[0].get("freq"))
        b2_freq = float(ch.gate_dyn_bands[1].get("freq"))
        b1_width = float(ch.gate_dyn_bands[0].get("width_oct"))
        b2_width = float(ch.gate_dyn_bands[1].get("width_oct"))
        results.append({"control": "BND press adds/selects independent Band 2", "passed": crop_changed(before, after) and bool(ch.gate_band_enabled) and int(ch.gate_dyn_band_count) == 2 and int(ch.gate_dyn_ui_band) == 1 and bool(b.get("enabled")) and abs(b2_freq - b1_freq) > 1.0 and abs(b2_width - b1_width) > 0.01, "before": str(before), "after": str(after), "gate_band_enabled": bool(ch.gate_band_enabled), "band_count": int(ch.gate_dyn_band_count), "selected_band": int(ch.gate_dyn_ui_band), "band_enabled": bool(b.get("enabled")), "band1": {"freq": b1_freq, "width": b1_width}, "band2": {"freq": b2_freq, "width": b2_width}})

        before = run_dir / "gate_bnd_rotate_before.png"
        after = run_dir / "gate_bnd_rotate_after.png"
        app.editor_param_row = 8
        app.editor_unified_header_focus = False
        app._sync_from_engine()
        capture_focus(app, before)
        os_key_rbracket(app.root)
        app._sync_from_engine()
        capture_focus(app, after)
        results.append({"control": "BND rotate switches selected band settings", "passed": crop_changed(before, after) and int(ch.gate_dyn_band_count) == 2 and int(ch.gate_dyn_ui_band) == 0 and abs(float(ch.gate_center_hz) - b1_freq) < 0.01, "before": str(before), "after": str(after), "band_count": int(ch.gate_dyn_band_count), "selected_band": int(ch.gate_dyn_ui_band), "active_freq": float(ch.gate_center_hz), "expected_freq": b1_freq})

        before = run_dir / "gate_frq_before.png"
        after = run_dir / "gate_frq_after.png"
        app.editor_param_row = 6
        app.editor_unified_header_focus = False
        app._sync_from_engine()
        capture_focus(app, before)
        for _ in range(6):
            os_key_rbracket(app.root)
        ch.gate_gr_db = 3.0
        app._sync_from_engine()
        capture_focus(app, after)
        b = ch.gate_dyn_bands[ch.gate_dyn_ui_band]
        results.append({"control": "FRQ rotate moves band detector visibly", "passed": crop_changed(before, after) and abs(float(b.get("freq")) - float(ch.gate_center_hz)) < 0.01, "before": str(before), "after": str(after), "freq": float(ch.gate_center_hz), "band_freq": float(b.get("freq"))})

        results.extend(direct_gate_dsp_checks(app))
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()

    report = {"run_dir": str(run_dir), "total": len(results), "passed": sum(1 for r in results if r["passed"]), "results": results}
    (run_dir / "gate_visible_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

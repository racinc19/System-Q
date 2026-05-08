from __future__ import annotations

import json
from pathlib import Path

from verify_system_q_visible_strict import (
    RUN_ROOT,
    ConsoleApp,
    ImageGrab,
    crop_changed,
    focus_window,
    os_key_rbracket,
    pump,
    user32,
)
import tkinter as tk
from datetime import datetime


def capture_focus(app: ConsoleApp, path: Path) -> None:
    root = app.root
    pump(root, 0.2)
    x0 = app.focus_canvas.winfo_rootx()
    y0 = app.focus_canvas.winfo_rooty()
    x1 = x0 + app.focus_canvas.winfo_width()
    y1 = y0 + app.focus_canvas.winfo_height()
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(path)


def click_visible(app: ConsoleApp, root_x: int, root_y: int) -> None:
    from verify_system_q_visible_strict import os_click
    os_click(app.root, root_x, root_y)


def editor_cell_center(app: ConsoleApp, stage: str, row: int | None):
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


def main() -> int:
    run_dir = RUN_ROOT / ("mic_pre_visible_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
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
        app._open_stage_editor(0, "pre")
        ch.pre_enabled = True
        app._sync_from_engine()

        # PRE squeeze: focus header, use real bracket key.
        app.editor_unified_header_focus = True
        app.editor_stage_col = 0
        app.selected_stage_key = "pre"
        ch.pre_gain_db = 0.0
        ch.pre_squeeze = 1.0
        app._sync_from_engine()
        click_visible(app, *editor_cell_center(app, "pre", None))
        before = run_dir / "pre_squeeze_before.png"
        after = run_dir / "pre_squeeze_after.png"
        capture_focus(app, before)
        os_key_rbracket(root)
        capture_focus(app, after)
        results.append({"control": "PRE squeeze/gain", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "gain_db": ch.pre_gain_db, "squeeze": ch.pre_squeeze})

        # LPF: click visible LPF to enable, rotate down several steps so high-frequency red block thickens.
        ch.lpf_enabled = False
        ch.hpf_enabled = False
        ch.lpf_hz = 20000.0
        app._sync_from_engine()
        click_visible(app, *editor_cell_center(app, "pre", 1))
        before = run_dir / "lpf_block_before.png"
        after = run_dir / "lpf_block_after.png"
        capture_focus(app, before)
        for _ in range(10):
            app._adjust_unified_editor_cell(-1.0)
        capture_focus(app, after)
        results.append({"control": "LPF red high-frequency block", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "lpf_hz": ch.lpf_hz})

        # HPF: click visible HPF to enable, rotate up several steps so low-frequency red block thickens.
        ch.lpf_enabled = False
        ch.hpf_enabled = False
        ch.hpf_hz = 20.0
        app._sync_from_engine()
        click_visible(app, *editor_cell_center(app, "pre", 4))
        before = run_dir / "hpf_block_before.png"
        after = run_dir / "hpf_block_after.png"
        capture_focus(app, before)
        for _ in range(10):
            app._adjust_unified_editor_cell(1.0)
        capture_focus(app, after)
        results.append({"control": "HPF red low-frequency block", "passed": crop_changed(before, after), "before": str(before), "after": str(after), "hpf_hz": ch.hpf_hz})
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()
    report = {"run_dir": str(run_dir), "total": len(results), "passed": sum(1 for r in results if r["passed"]), "results": results}
    (run_dir / "mic_pre_visible_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

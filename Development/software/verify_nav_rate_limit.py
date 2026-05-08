from __future__ import annotations

import json
import time
from datetime import datetime

import tkinter as tk

from verify_system_q_visible_strict import RUN_ROOT, ConsoleApp, pump
from pol_visualizer import SpaceMouseController


class _FakeStick:
    def __init__(self, axes: list[float]):
        self.axes = axes

    def get_numaxes(self) -> int:
        return len(self.axes)

    def get_axis(self, idx: int) -> float:
        return self.axes[idx]

    def get_numbuttons(self) -> int:
        return 0

    def get_button(self, idx: int) -> int:
        return 0


def main() -> int:
    run_dir = RUN_ROOT / ("nav_rate_limit_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.geometry("1200x900+0+0")
    pump(root, 0.3)
    results = []
    try:
        ch = app.engine.channels[0]
        app._open_stage_editor(0, "gate")
        app.editor_stage_col = next(i for i, item in enumerate(app._STAGE_GRID) if item[0] == "gate")
        app.editor_param_row = 1
        app.editor_unified_header_focus = False
        ch.gate_threshold_db = -45.0
        app._sync_from_engine()

        before = float(ch.gate_threshold_db)
        app._adjust_unified_editor_cell(1.0)
        first = float(ch.gate_threshold_db)
        app._adjust_unified_editor_cell(1.0)
        second = float(ch.gate_threshold_db)
        time.sleep(0.09)
        app._adjust_unified_editor_cell(1.0)
        third = float(ch.gate_threshold_db)
        first_delta = first - before
        results.append({
            "control": "gate THR responsive fine step",
            "passed": 0.8 <= first_delta <= 2.2,
            "before": before,
            "after": first,
            "delta": first_delta,
        })
        results.append({
            "control": "immediate rotate repeat is dropped",
            "passed": second == first,
            "first": first,
            "immediate_second": second,
        })
        results.append({
            "control": "rotate accepts after cooldown",
            "passed": third > second,
            "after_cooldown": third,
            "previous": second,
        })

        ch.gate_threshold_db = -45.0
        app._last_editor_adjust_at = 0.0
        before_low = float(ch.gate_threshold_db)
        app._adjust_unified_editor_cell(0.25)
        low = float(ch.gate_threshold_db)
        results.append({
            "control": "small twist still moves threshold",
            "passed": low > before_low,
            "before": before_low,
            "after": low,
            "delta": low - before_low,
        })

        for stage, expected in (("gate", "THR"), ("harm", "H1"), ("pre", "LPF")):
            app._open_stage_editor(0, stage)
            app.editor_unified_header_focus = True
            app.editor_param_row = 0
            app._last_cardinal_nav_at = 0.0
            app._handle_nav("down")
            label = app._STAGE_GRID[app.editor_stage_col][2][app.editor_param_row]
            results.append({
                "control": f"{stage} header down skips TBE",
                "passed": label == expected and not app.editor_unified_header_focus,
                "landed": label,
                "expected": expected,
            })

        app.nav_scope = "console"
        app.console_row = "stages"
        app.selected_stage_key = "gate"
        app._last_cardinal_nav_at = 0.0
        app._handle_nav("right")
        first_stage = app.selected_stage_key
        app._handle_nav("right")
        second_stage = app.selected_stage_key
        time.sleep(0.23)
        app._handle_nav("right")
        third_stage = app.selected_stage_key
        results.append({
            "control": "immediate nav repeat is dropped",
            "passed": second_stage == first_stage,
            "first_stage": first_stage,
            "immediate_second_stage": second_stage,
        })
        results.append({
            "control": "nav accepts after cooldown",
            "passed": third_stage != second_stage,
            "after_cooldown_stage": third_stage,
            "previous": second_stage,
        })

        sm = SpaceMouseController()
        sm.available = True
        sm._sticks = [_FakeStick([0.0, 0.0, 0.0, 0.0, 0.0, 0.35])]
        sm.twist_axis = 5
        sm._last_poll_at = time.monotonic() - 1.0
        axis, _pressed, directions = sm.poll()
        results.append({
            "control": "stale poll keeps twist but drops nav",
            "passed": axis > 0.0 and directions == [],
            "axis": axis,
            "directions": directions,
        })

        sm = SpaceMouseController()
        sm.available = True
        sm._sticks = [_FakeStick([0.55, 0.0, 0.0, 0.0, 0.0, 0.0])]
        first_axis, _pressed, first_dirs = sm.poll()
        second_axis, _pressed, second_dirs = sm.poll()
        results.append({
            "control": "new tilt emits immediate one-step nav",
            "passed": first_dirs == ["right"] and second_dirs == [],
            "first_axis": first_axis,
            "first_dirs": first_dirs,
            "second_axis": second_axis,
            "second_dirs": second_dirs,
        })
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()

    report = {"run_dir": str(run_dir), "total": len(results), "passed": sum(1 for r in results if r["passed"]), "results": results}
    (run_dir / "nav_rate_limit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

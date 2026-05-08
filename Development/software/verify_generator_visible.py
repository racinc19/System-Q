from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import tkinter as tk
import numpy as np
from PIL import ImageGrab

from verify_system_q_visible_strict import (
    RUN_ROOT,
    ConsoleApp,
    crop_changed,
    focus_window,
    os_click,
    os_key_rbracket,
    pump,
)


def capture_focus(app: ConsoleApp, path: Path) -> None:
    root = app.root
    pump(root, 0.2)
    x0 = app.focus_canvas.winfo_rootx()
    y0 = app.focus_canvas.winfo_rooty()
    x1 = x0 + app.focus_canvas.winfo_width()
    y1 = y0 + app.focus_canvas.winfo_height()
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(path)


def transport_center(app: ConsoleApp, row: int, col: int) -> tuple[int, int]:
    btn = app.transport_cells[(row, col)]
    return (
        int(btn.winfo_rootx() - app.root.winfo_rootx() + btn.winfo_width() / 2),
        int(btn.winfo_rooty() - app.root.winfo_rooty() + btn.winfo_height() / 2),
    )


def refresh_generator_analyzer(app: ConsoleApp, blocks: int = 10, frames: int = 4096) -> dict:
    with app.engine._lock:
        app.engine.master_channel.band_levels *= 0.0
        if hasattr(app.engine.master_channel, "_analyze_counter"):
            app.engine.master_channel._analyze_counter = 0
        peak = 0.0
        for _ in range(blocks):
            block = app.engine._synthesize_generator(frames)
            peak = max(peak, float(np.max(np.abs(block))) if len(block) else 0.0)
            app.engine._analyze_channel(app.engine.master_channel, block.astype(np.float32))
        app.engine.master_level = peak * 2.2
        levels = np.asarray(app.engine.master_channel.band_levels, dtype=np.float32).copy()
    app._sync_from_engine()
    return {
        "peak": peak,
        "max_band": float(np.max(levels)) if levels.size else 0.0,
        "active_bands": int(np.count_nonzero(levels > 0.02)),
        "top_bands": [int(i) for i in np.argsort(levels)[-5:][::-1]],
    }


def main() -> int:
    run_dir = RUN_ROOT / ("generator_visible_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.attributes("-topmost", True)
    root.geometry("1640x1450+0+0")
    pump(root, 0.5)
    focus_window(root)
    results = []
    try:
        app._open_stage_editor(0, "pre")
        base = run_dir / "00_base.png"
        capture_focus(app, base)

        modes = [
            ("OSC", 1, 0, "osc"),
            ("PNK", 1, 1, "pink"),
            ("WHT", 1, 2, "white"),
            ("PLS", 1, 3, "pink_pulse"),
            ("HOT", 1, 4, "white_hot"),
        ]
        previous = base
        for label, row, col, expected_mode in modes:
            os_click(root, *transport_center(app, row, col))
            analyzer = refresh_generator_analyzer(app)
            shot = run_dir / f"mode_{label.lower()}.png"
            capture_focus(app, shot)
            results.append({
                "control": label,
                "expected_mode": expected_mode,
                "actual_mode": app.engine.generator_mode,
                "visible_changed": crop_changed(previous, shot),
                "analyzer": analyzer,
                "screenshot": str(shot),
            })
            previous = shot

        # Return to OSC, then use the real bracket key. Pass requires visible focus display change
        # and the oscillator frequency value moving.
        os_click(root, *transport_center(app, 1, 0))
        refresh_generator_analyzer(app)
        before = run_dir / "osc_rotate_before.png"
        after = run_dir / "osc_rotate_after.png"
        capture_focus(app, before)
        before_hz = float(app.engine.osc_hz)
        os_key_rbracket(root)
        refresh_generator_analyzer(app)
        capture_focus(app, after)
        results.append({
            "control": "OSC rotate frequency",
            "before_hz": before_hz,
            "after_hz": float(app.engine.osc_hz),
            "visible_changed": crop_changed(before, after),
            "screenshots": {"before": str(before), "after": str(after)},
        })
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()

    for item in results:
        item["passed"] = bool(item.get("visible_changed")) and (
            "expected_mode" not in item or item["actual_mode"] == item["expected_mode"]
        ) and (
            "before_hz" not in item or item["after_hz"] != item["before_hz"]
        ) and (
            "analyzer" not in item or item["analyzer"]["max_band"] > 0.02
        )
    report = {
        "run_dir": str(run_dir),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "results": results,
    }
    (run_dir / "generator_visible_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

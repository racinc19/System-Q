"""Strict visible UI verifier for System Q.

Pass means the visible control region changed after a real OS click/key event.
Internal state is recorded only for debugging and never used as the pass gate.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from PIL import Image, ImageChops, ImageGrab

ROOT = Path(__file__).resolve().parent
RUN_ROOT = ROOT / "SYSTEM_Q_VERIFY_RUNS"
sys.path.insert(0, str(ROOT))

from system_q_console import ConsoleApp  # noqa: E402

user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_RBRACKET = 0xDD


STAGES = [
    ("pre", "PRE", ["TBE", "LPF", "48V", "PHS", "HPF"]),
    ("harm", "HRM", ["TBE", "H1", "H2", "H3", "H4", "H5"]),
    ("gate", "GTE", ["TBE", "THR", "DEP", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
    ("comp", "CMP", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
    ("eq", "EQ", ["TBE", "FRQ", "GAN", "SHP", "BND", "TRN", "ATK", "SUT", "BD2"]),
    ("trn", "TRN", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
    ("xct", "XCT", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
    ("tbe", "TBE", ["DRV", "BND"]),
]

ROTATABLE = {
    ("pre", "LPF"), ("pre", "HPF"),
    ("harm", "H1"), ("harm", "H2"), ("harm", "H3"), ("harm", "H4"), ("harm", "H5"),
    ("gate", "THR"), ("gate", "DEP"), ("gate", "ATK"), ("gate", "RLS"), ("gate", "GAN"), ("gate", "FRQ"), ("gate", "WDT"),
    ("comp", "THR"), ("comp", "RAT"), ("comp", "ATK"), ("comp", "RLS"), ("comp", "GAN"), ("comp", "FRQ"), ("comp", "WDT"),
    ("eq", "FRQ"), ("eq", "GAN"), ("eq", "BND"), ("eq", "TRN"), ("eq", "ATK"), ("eq", "SUT"),
    ("trn", "FRQ"), ("trn", "ATK"), ("trn", "SUT"), ("trn", "DRV"),
    ("xct", "FRQ"), ("xct", "ATK"), ("xct", "SUT"), ("xct", "DRV"),
    ("tbe", "DRV"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pump(root: tk.Tk, seconds: float = 0.18) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update_idletasks()
        root.update()
        time.sleep(0.015)


def focus_window(root: tk.Tk) -> None:
    root.lift()
    root.focus_force()
    pump(root, 0.05)
    user32.SetForegroundWindow(root.winfo_id())
    pump(root, 0.08)


def os_click(root: tk.Tk, root_x: int, root_y: int) -> None:
    focus_window(root)
    user32.SetCursorPos(int(root.winfo_rootx() + root_x), int(root.winfo_rooty() + root_y))
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    pump(root, 0.22)


def os_key_rbracket(root: tk.Tk) -> None:
    focus_window(root)
    user32.keybd_event(VK_RBRACKET, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(VK_RBRACKET, 0, 0x0002, 0)
    pump(root, 0.22)


def capture_crop(root: tk.Tk, bbox_root: tuple[int, int, int, int], path: Path) -> None:
    pump(root, 0.15)
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    x0, y0, x1, y1 = bbox_root
    pad = 4
    full = ImageGrab.grab(bbox=(rx, ry, rx + root.winfo_width(), ry + root.winfo_height()))
    full.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad)).save(path)


def crop_changed(before: Path, after: Path) -> bool:
    with Image.open(before) as a, Image.open(after) as b:
        return ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is not None


def visible_cell(app: ConsoleApp, stage: str, row: int | None) -> tuple[int, int, int, int, int, int]:
    col = next(i for i, item in enumerate(app._STAGE_GRID) if item[0] == stage)
    app.editor_stage_col = col
    app.selected_stage_key = stage
    app.editor_unified_header_focus = row is None
    app.editor_param_row = 0 if row is None else row
    app.nav_scope = "editor"
    app._sync_from_engine()
    pump(app.root, 0.12)
    wanted = ("stage_hdr", col) if row is None else ("stage_param", col, row)
    for x0, y0, x1, y1, tag in app.editor_hitboxes:
        if tag == wanted:
            ox = app.editor_canvas.winfo_rootx() - app.root.winfo_rootx()
            oy = app.editor_canvas.winfo_rooty() - app.root.winfo_rooty()
            bbox = (int(ox + x0), int(oy + y0), int(ox + x1), int(oy + y1))
            return (*bbox, int((bbox[0] + bbox[2]) / 2), int((bbox[1] + bbox[3]) / 2))
    raise RuntimeError(f"missing visible cell {stage} {row}")


def enable_stage(app: ConsoleApp, stage: str) -> None:
    ch = app.engine.channels[0]
    attr = "harmonics_enabled" if stage == "harm" else f"{stage}_enabled"
    if hasattr(ch, attr):
        setattr(ch, attr, True)


def reset_control_state(app: ConsoleApp, stage: str, label: str) -> None:
    ch = app.engine.channels[0]
    enable_stage(app, stage)
    if label == "TBE":
        setattr(ch, "tube" if stage == "pre" else f"{stage}_tube", False)
    elif label == "LPF":
        ch.lpf_enabled = False
    elif label == "HPF":
        ch.hpf_enabled = False
    elif label == "48V":
        ch.phantom = False
    elif label == "PHS":
        ch.phase = False
    elif label == "BND" and hasattr(ch, f"{stage}_band_enabled"):
        setattr(ch, f"{stage}_band_enabled", False)
    elif label == "BD2":
        ch.limit_band_enabled = False
    else:
        maps = {
            "gate": "gate_param_bypass",
            "comp": "comp_param_bypass",
            "eq": "eq_param_bypass",
            "harm": "harm_param_bypass",
            "trn": "tone_param_bypass",
            "xct": "tone_param_bypass",
            "tbe": "tone_param_bypass",
        }
        bp_name = maps.get(stage)
        if bp_name:
            bp = getattr(ch, bp_name)
            bp[label] = False
            setattr(ch, bp_name, bp)


def state_snapshot(app: ConsoleApp) -> dict[str, Any]:
    ch = app.engine.channels[0]
    return {
        "stage": app.selected_stage_key,
        "row": app.editor_param_row,
        "header_focus": app.editor_unified_header_focus,
        "playing": app.engine.playing,
        "generator_mode": app.engine.generator_mode,
        "record_armed": ch.record_armed,
    }


def check_editor_click(app: ConsoleApp, run_dir: Path, stage: str, header: str, row: int | None, label: str) -> dict[str, Any]:
    out = run_dir / (f"editor_{stage}_header" if row is None else f"editor_{stage}_{label}_click")
    out.mkdir(parents=True, exist_ok=True)
    if row is None:
        ch = app.engine.channels[0]
        attr = "harmonics_enabled" if stage == "harm" else f"{stage}_enabled"
        if hasattr(ch, attr):
            setattr(ch, attr, False)
    else:
        reset_control_state(app, stage, label)
    x0, y0, x1, y1, cx, cy = visible_cell(app, stage, row)
    before = out / "visible_before.png"
    after = out / "visible_after.png"
    capture_crop(app.root, (x0, y0, x1, y1), before)
    before_state = state_snapshot(app)
    os_click(app.root, cx, cy)
    capture_crop(app.root, (x0, y0, x1, y1), after)
    after_state = state_snapshot(app)
    passed = crop_changed(before, after)
    return {
        "id": f"editor-{stage}-header-click" if row is None else f"editor-{stage}-{label.lower()}-click",
        "stage": stage,
        "label": header if row is None else label,
        "action": "real_click_visible_cell",
        "result": "PASS" if passed else "FAIL",
        "visible_changed": passed,
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "before_state": before_state,
        "after_state": after_state,
        "screenshots": {"before": str(before), "after": str(after)},
    }


def check_editor_rotate(app: ConsoleApp, run_dir: Path, stage: str, row: int, label: str) -> dict[str, Any]:
    out = run_dir / f"editor_{stage}_{label}_rotate"
    out.mkdir(parents=True, exist_ok=True)
    reset_control_state(app, stage, label)
    x0, y0, x1, y1, _cx, _cy = visible_cell(app, stage, row)
    before = out / "visible_before.png"
    after = out / "visible_after.png"
    capture_crop(app.root, (x0, y0, x1, y1), before)
    before_state = state_snapshot(app)
    os_key_rbracket(app.root)
    capture_crop(app.root, (x0, y0, x1, y1), after)
    after_state = state_snapshot(app)
    passed = crop_changed(before, after)
    return {
        "id": f"editor-{stage}-{label.lower()}-rotate",
        "stage": stage,
        "label": label,
        "action": "real_rbracket_visible_cell",
        "result": "PASS" if passed else "FAIL",
        "visible_changed": passed,
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "before_state": before_state,
        "after_state": after_state,
        "screenshots": {"before": str(before), "after": str(after)},
    }


def check_transport_click(app: ConsoleApp, run_dir: Path, button: tuple[int, int, str, str, str, str]) -> dict[str, Any]:
    r, c, key, label, _color, _glyph = button
    out = run_dir / f"transport_{key}"
    out.mkdir(parents=True, exist_ok=True)
    if key in ("oscillator", "pink", "white", "pink_pulse", "white_hot"):
        app.engine.generator_mode = "none"
    if key == "record":
        app.engine.channels[0].record_armed = False
    if key == "play":
        app.engine.playing = False
    if key in ("stop", "rewind"):
        app.engine.channels[0].position = 24000
    if key == "forward":
        app.engine.channels[0].position = 0
    app.nav_scope = "transport"
    app.transport_focus_row = r
    app.transport_focus_col = c
    app._sync_from_engine()
    pump(app.root, 0.12)
    widget = app.transport_cells[(r, c)]
    x0 = widget.winfo_rootx() - app.root.winfo_rootx()
    y0 = widget.winfo_rooty() - app.root.winfo_rooty()
    x1 = x0 + widget.winfo_width()
    y1 = y0 + widget.winfo_height()
    before = out / "visible_before.png"
    after = out / "visible_after.png"
    capture_crop(app.root, (x0, y0, x1, y1), before)
    before_state = state_snapshot(app)
    os_click(app.root, int((x0 + x1) / 2), int((y0 + y1) / 2))
    capture_crop(app.root, (x0, y0, x1, y1), after)
    after_state = state_snapshot(app)
    passed = crop_changed(before, after)
    return {
        "id": f"transport-{key}",
        "stage": "transport",
        "label": label,
        "action": "real_click_visible_button",
        "result": "PASS" if passed else "FAIL",
        "visible_changed": passed,
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "before_state": before_state,
        "after_state": after_state,
        "screenshots": {"before": str(before), "after": str(after)},
    }


def main() -> int:
    run_dir = RUN_ROOT / ("visible_strict_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.attributes("-topmost", True)
    root.geometry("1640x1450+0+0")
    pump(root, 0.5)
    focus_window(root)
    results = []
    try:
        for stage, header, labels in STAGES:
            results.append(check_editor_click(app, run_dir, stage, header, None, header))
            for row, label in enumerate(labels):
                results.append(check_editor_click(app, run_dir, stage, header, row, label))
                if (stage, label) in ROTATABLE:
                    results.append(check_editor_rotate(app, run_dir, stage, row, label))
        for button in app._TRANSPORT_BUTTONS:
            results.append(check_transport_click(app, run_dir, button))
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()

    passed = sum(1 for r in results if r["result"] == "PASS")
    report = {
        "run_dir": str(run_dir),
        "standard": "PASS only when the visible control crop changes after a real OS click/key event.",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    (run_dir / "visible_strict_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("run_dir", "total", "passed", "failed")}, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

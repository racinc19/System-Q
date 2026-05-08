"""Actual interface verifier for System Q.

This is intentionally separate from verify_system_q_live.py. It drives the
visible Tk window with Windows cursor/mouse/key events instead of calling
widget handlers or Tk event_generate directly.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from PIL import ImageChops, ImageGrab

ROOT = Path(__file__).resolve().parent
RUN_ROOT = ROOT / "SYSTEM_Q_VERIFY_RUNS"
sys.path.insert(0, str(ROOT))

from system_q_console import ConsoleApp  # noqa: E402

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_RBRACKET = 0xDD


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_diff_bbox(before: Path, after: Path) -> tuple[int, int, int, int] | None:
    from PIL import Image

    with Image.open(before) as a, Image.open(after) as b:
        return ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()


def pump(root: tk.Tk, seconds: float = 0.20) -> None:
    end = time.time() + seconds
    while time.time() < end:
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


def focus_window(root: tk.Tk) -> None:
    root.lift()
    root.focus_force()
    pump(root, 0.05)
    user32.SetForegroundWindow(root.winfo_id())
    pump(root, 0.10)


def os_click(root: tk.Tk, x: int, y: int) -> None:
    focus_window(root)
    sx = int(root.winfo_rootx() + x)
    sy = int(root.winfo_rooty() + y)
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    pump(root, 0.25)


def os_key_rbracket(root: tk.Tk) -> None:
    focus_window(root)
    user32.keybd_event(VK_RBRACKET, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(VK_RBRACKET, 0, 0x0002, 0)
    pump(root, 0.25)


def capture_root(root: tk.Tk, path: Path) -> None:
    pump(root, 0.20)
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)


def snapshot_state(app: ConsoleApp) -> dict[str, Any]:
    ch = app.engine.channels[app.editor_channel]
    data: dict[str, Any] = {
        "nav_scope": app.nav_scope,
        "playing": app.engine.playing,
        "generator_mode": app.engine.generator_mode,
        "editor_channel": app.editor_channel,
        "selected_channel": app.selected_channel,
        "selected_stage_key": app.selected_stage_key,
        "editor_stage_col": app.editor_stage_col,
        "editor_param_row": app.editor_param_row,
        "editor_unified_header_focus": app.editor_unified_header_focus,
        "channel0_position": app.engine.channels[0].position,
        "record_armed": app.engine.channels[0].record_armed,
    }
    for attr in [
        "pre_enabled", "phantom", "phase", "tube", "lpf_enabled", "hpf_enabled",
        "lpf_hz", "hpf_hz", "harmonics_enabled", "harm_tube", "gate_enabled",
        "gate_tube", "gate_threshold_db", "gate_ratio", "gate_attack_ms",
        "gate_release_ms", "gate_makeup", "gate_center_hz", "gate_width_oct",
        "gate_band_enabled", "comp_enabled", "comp_tube", "comp_threshold_db",
        "comp_ratio", "comp_attack_ms", "comp_release_ms", "comp_makeup",
        "comp_center_hz", "comp_width_oct", "comp_band_enabled", "eq_enabled",
        "eq_tube", "eq_freq", "eq_gain_db", "eq_width", "eq_band_enabled", "limit_band_enabled",
        "trn_enabled", "trn_freq", "trn_attack", "trn_sustain", "trn_drive",
        "trn_band_enabled", "xct_enabled", "xct_freq", "xct_attack",
        "xct_sustain", "xct_drive", "xct_band_enabled", "tbe_enabled",
        "tbe_drive", "tbe_band_enabled",
    ]:
        data[attr] = getattr(ch, attr)
    for i, value in enumerate(ch.harmonics):
        data[f"harmonics[{i}]"] = float(value)
    for key in ("gate_param_bypass", "comp_param_bypass", "eq_param_bypass", "harm_param_bypass", "tone_param_bypass"):
        bp = getattr(ch, key, {})
        for label, value in bp.items():
            data[f"{key}.{label}"] = bool(value)
    return data


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

ROTATE_ATTR = {
    ("pre", "LPF"): "lpf_hz",
    ("pre", "HPF"): "hpf_hz",
    ("harm", "H1"): "harmonics[0]",
    ("harm", "H2"): "harmonics[1]",
    ("harm", "H3"): "harmonics[2]",
    ("harm", "H4"): "harmonics[3]",
    ("harm", "H5"): "harmonics[4]",
    ("gate", "THR"): "gate_threshold_db",
    ("gate", "DEP"): "gate_ratio",
    ("gate", "ATK"): "gate_attack_ms",
    ("gate", "RLS"): "gate_release_ms",
    ("gate", "GAN"): "gate_makeup",
    ("gate", "FRQ"): "gate_center_hz",
    ("gate", "WDT"): "gate_width_oct",
    ("comp", "THR"): "comp_threshold_db",
    ("comp", "RAT"): "comp_ratio",
    ("comp", "ATK"): "comp_attack_ms",
    ("comp", "RLS"): "comp_release_ms",
    ("comp", "GAN"): "comp_makeup",
    ("comp", "FRQ"): "comp_center_hz",
    ("comp", "WDT"): "comp_width_oct",
    ("eq", "FRQ"): "eq_freq",
    ("eq", "GAN"): "eq_gain_db",
    ("eq", "BND"): "eq_width",
    ("eq", "TRN"): "trn_freq",
    ("eq", "ATK"): "trn_attack",
    ("eq", "SUT"): "trn_sustain",
    ("trn", "FRQ"): "trn_freq",
    ("trn", "ATK"): "trn_attack",
    ("trn", "SUT"): "trn_sustain",
    ("trn", "DRV"): "trn_drive",
    ("xct", "FRQ"): "xct_freq",
    ("xct", "ATK"): "xct_attack",
    ("xct", "SUT"): "xct_sustain",
    ("xct", "DRV"): "xct_drive",
    ("tbe", "DRV"): "tbe_drive",
}


def press_attr(stage: str, label: str) -> str:
    if label == "TBE":
        return "tube" if stage == "pre" else f"{stage}_tube"
    if label == "LPF":
        return "lpf_enabled"
    if label == "HPF":
        return "hpf_enabled"
    if label == "48V":
        return "phantom"
    if label == "PHS":
        return "phase"
    if label == "BND":
        return f"{stage}_band_enabled"
    if label == "BD2":
        return "limit_band_enabled"
    return {
        "gate": f"gate_param_bypass.{label}",
        "comp": f"comp_param_bypass.{label}",
        "eq": f"eq_param_bypass.{label}",
        "harm": f"harm_param_bypass.{label}",
        "trn": f"tone_param_bypass.{label}",
        "xct": f"tone_param_bypass.{label}",
        "tbe": f"tone_param_bypass.{label}",
    }.get(stage, "")


def get_state_value(state: dict[str, Any], attr: str) -> Any:
    if attr not in state and "." in attr:
        return False
    return state.get(attr)


def changed(before: Any, after: Any) -> bool:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return not math.isclose(float(before), float(after), rel_tol=1e-9, abs_tol=1e-9)
    return before != after


def center_for_editor_hitbox(app: ConsoleApp, stage: str, row: int | None) -> tuple[int, int, Any]:
    app._open_stage_editor(0, stage)
    app.root.update_idletasks()
    app.root.update()
    col = next(i for i, item in enumerate(app._STAGE_GRID) if item[0] == stage)
    wanted = ("stage_hdr", col) if row is None else ("stage_param", col, int(row))
    for x0, y0, x1, y1, tag in app.editor_hitboxes:
        if tag == wanted:
            cx = int(app.editor_canvas.winfo_rootx() - app.root.winfo_rootx() + (x0 + x1) / 2)
            cy = int(app.editor_canvas.winfo_rooty() - app.root.winfo_rooty() + (y0 + y1) / 2)
            return cx, cy, tag
    raise RuntimeError(f"missing editor hitbox {wanted}")


def verify_editor_click(app: ConsoleApp, out: Path, stage: str, label: str, row: int | None, attr: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    x, y, tag = center_for_editor_hitbox(app, stage, row)
    before_state = snapshot_state(app)
    before_png = out / "before_click.png"
    after_png = out / "after_click.png"
    capture_root(app.root, before_png)
    os_click(app.root, x, y)
    after_state = snapshot_state(app)
    capture_root(app.root, after_png)
    before_value = get_state_value(before_state, attr)
    after_value = get_state_value(after_state, attr)
    bbox = image_diff_bbox(before_png, after_png)
    state_changed = changed(before_value, after_value)
    visual_changed = sha256_file(before_png) != sha256_file(after_png) and bbox is not None
    result = "PASS" if state_changed and visual_changed else "FAIL"
    return {
        "id": f"editor-{stage}-{label.lower()}-click" if row is not None else f"editor-{stage}-header-click",
        "area": "Editor Grid",
        "stage": stage,
        "label": label,
        "action": "actual_os_click",
        "result": result,
        "state_attr": attr,
        "before_value": before_value,
        "after_value": after_value,
        "state_changed": state_changed,
        "visual_changed": visual_changed,
        "diff_bbox": bbox,
        "hitbox_tag": tag,
        "screenshots": {"before": str(before_png), "after": str(after_png)},
    }


def verify_editor_rotate(app: ConsoleApp, out: Path, stage: str, label: str, row: int, attr: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    x, y, tag = center_for_editor_hitbox(app, stage, row)
    os_click(app.root, x, y)
    before_state = snapshot_state(app)
    before_png = out / "before_rotate.png"
    after_png = out / "after_rotate.png"
    capture_root(app.root, before_png)
    os_key_rbracket(app.root)
    after_state = snapshot_state(app)
    capture_root(app.root, after_png)
    before_value = get_state_value(before_state, attr)
    after_value = get_state_value(after_state, attr)
    bbox = image_diff_bbox(before_png, after_png)
    state_changed = changed(before_value, after_value)
    visual_changed = sha256_file(before_png) != sha256_file(after_png) and bbox is not None
    result = "PASS" if state_changed and visual_changed else "FAIL"
    return {
        "id": f"editor-{stage}-{label.lower()}-rotate",
        "area": "Editor Grid",
        "stage": stage,
        "label": label,
        "action": "actual_os_key_rbracket_after_actual_click_focus",
        "result": result,
        "state_attr": attr,
        "before_value": before_value,
        "after_value": after_value,
        "state_changed": state_changed,
        "visual_changed": visual_changed,
        "diff_bbox": bbox,
        "hitbox_tag": tag,
        "screenshots": {"before": str(before_png), "after": str(after_png)},
    }


def verify_transport_click(app: ConsoleApp, out: Path, button: tuple[int, int, str, str, str, str], attr: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    r, c, key, label, _color, _glyph = button
    app.nav_scope = "transport"
    app.transport_focus_row = r
    app.transport_focus_col = c
    app._sync_from_engine()
    widget = app.transport_cells[(r, c)]
    x = widget.winfo_rootx() - app.root.winfo_rootx() + widget.winfo_width() // 2
    y = widget.winfo_rooty() - app.root.winfo_rooty() + widget.winfo_height() // 2
    before_state = snapshot_state(app)
    before_png = out / "before_click.png"
    after_png = out / "after_click.png"
    capture_root(app.root, before_png)
    os_click(app.root, x, y)
    after_state = snapshot_state(app)
    capture_root(app.root, after_png)
    before_value = get_state_value(before_state, attr)
    after_value = get_state_value(after_state, attr)
    bbox = image_diff_bbox(before_png, after_png)
    state_changed = changed(before_value, after_value)
    visual_changed = sha256_file(before_png) != sha256_file(after_png) and bbox is not None
    result = "PASS" if state_changed and visual_changed else "FAIL"
    return {
        "id": f"transport-{key}",
        "area": "Transport Panel",
        "stage": "transport",
        "label": label,
        "action": "actual_os_click",
        "result": result,
        "state_attr": attr,
        "before_value": before_value,
        "after_value": after_value,
        "state_changed": state_changed,
        "visual_changed": visual_changed,
        "diff_bbox": bbox,
        "screenshots": {"before": str(before_png), "after": str(after_png)},
    }


def main() -> int:
    run_dir = RUN_ROOT / ("actual_ui_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)

    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    screen_w = max(1560, root.winfo_screenwidth())
    screen_h = max(960, root.winfo_screenheight() - 80)
    root.geometry(f"{screen_w}x{screen_h}+0+0")
    root.update()
    focus_window(root)

    results: list[dict[str, Any]] = []
    try:
        for stage, header, labels in STAGES:
            stage_attr = "harmonics_enabled" if stage == "harm" else f"{stage}_enabled"
            results.append(verify_editor_click(app, run_dir / f"editor_{stage}_header", stage, header, None, stage_attr))
            for row, label in enumerate(labels):
                attr = press_attr(stage, label)
                if attr:
                    results.append(verify_editor_click(app, run_dir / f"editor_{stage}_{label}_click", stage, label, row, attr))
                rotate_attr = ROTATE_ATTR.get((stage, label))
                if rotate_attr:
                    results.append(verify_editor_rotate(app, run_dir / f"editor_{stage}_{label}_rotate", stage, label, row, rotate_attr))

        transport_attrs = {
            "play": "playing",
            "stop": "channel0_position",
            "rewind": "channel0_position",
            "forward": "channel0_position",
            "record": "record_armed",
            "oscillator": "generator_mode",
            "pink": "generator_mode",
            "white": "generator_mode",
            "pink_pulse": "generator_mode",
            "white_hot": "generator_mode",
        }
        for button in app._TRANSPORT_BUTTONS:
            key = button[2]
            if key == "stop":
                app.engine.channels[0].position = 24000
            if key == "rewind":
                app.engine.channels[0].position = 24000
            if key == "forward":
                app.engine.channels[0].position = 0
            if key == "play":
                app.engine.playing = False
            if key in ("oscillator", "pink", "white", "pink_pulse", "white_hot"):
                app.engine.generator_mode = "none"
            app._sync_from_engine()
            results.append(verify_transport_click(app, run_dir / f"transport_{key}", button, transport_attrs[key]))

    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()

    passes = sum(1 for r in results if r["result"] == "PASS")
    fails = len(results) - passes
    report = {
        "run_dir": str(run_dir),
        "total": len(results),
        "passed": passes,
        "failed": fails,
        "results": results,
    }
    (run_dir / "actual_ui_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "total": len(results), "passed": passes, "failed": fails}, indent=2))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

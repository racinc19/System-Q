"""Live System Q verification gate.

This script intentionally uses the real ConsoleApp and ConsoleEngine. It is not
an implementation audit unless it proves all three things for the requested
control: real state diff, visual screenshot delta, and non-duplicate hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def snapshot_state(app: ConsoleApp) -> dict[str, Any]:
    ch = app.engine.channels[app.editor_channel]
    return {
        "nav_scope": app.nav_scope,
        "playing": app.engine.playing,
        "generator_mode": app.engine.generator_mode,
        "editor_channel": app.editor_channel,
        "selected_channel": app.selected_channel,
        "channel0_position": app.engine.channels[0].position,
        "channel0_record_armed": app.engine.channels[0].record_armed,
        "selected_stage_key": app.selected_stage_key,
        "editor_stage_col": app.editor_stage_col,
        "editor_param_row": app.editor_param_row,
        "editor_unified_header_focus": app.editor_unified_header_focus,
        "pre_enabled": ch.pre_enabled,
        "tube": ch.tube,
        "lpf_enabled": ch.lpf_enabled,
        "phantom": ch.phantom,
        "phase": ch.phase,
        "hpf_enabled": ch.hpf_enabled,
        "lpf_hz": ch.lpf_hz,
        "hpf_hz": ch.hpf_hz,
        "harmonics_enabled": ch.harmonics_enabled,
        "harm_tube": ch.harm_tube,
        "harmonics_0": float(ch.harmonics[0]),
        "harmonics_1": float(ch.harmonics[1]),
        "harmonics_2": float(ch.harmonics[2]),
        "harmonics_3": float(ch.harmonics[3]),
        "harmonics_4": float(ch.harmonics[4]),
        "gate_enabled": ch.gate_enabled,
        "gate_tube": ch.gate_tube,
        "gate_threshold_db": ch.gate_threshold_db,
        "gate_ratio": ch.gate_ratio,
        "gate_attack_ms": ch.gate_attack_ms,
        "gate_release_ms": ch.gate_release_ms,
        "gate_makeup": ch.gate_makeup,
        "gate_center_hz": ch.gate_center_hz,
        "gate_width_oct": ch.gate_width_oct,
        "gate_band_enabled": ch.gate_band_enabled,
        "comp_enabled": ch.comp_enabled,
        "comp_tube": ch.comp_tube,
        "comp_threshold_db": ch.comp_threshold_db,
        "comp_ratio": ch.comp_ratio,
        "comp_attack_ms": ch.comp_attack_ms,
        "comp_release_ms": ch.comp_release_ms,
        "comp_makeup": ch.comp_makeup,
        "comp_center_hz": ch.comp_center_hz,
        "comp_width_oct": ch.comp_width_oct,
        "comp_band_enabled": ch.comp_band_enabled,
        "eq_enabled": ch.eq_enabled,
        "eq_tube": ch.eq_tube,
        "eq_freq": ch.eq_freq,
        "eq_gain_db": ch.eq_gain_db,
        "eq_width": ch.eq_width,
        "eq_param_bypass_SHP": bool(ch.eq_param_bypass.get("SHP", False)),
        "trn_freq": ch.trn_freq,
        "trn_attack": ch.trn_attack,
        "trn_sustain": ch.trn_sustain,
        "limit_band_enabled": ch.limit_band_enabled,
        "trn_enabled": ch.trn_enabled,
        "trn_drive": ch.trn_drive,
        "trn_band_enabled": ch.trn_band_enabled,
        "xct_enabled": ch.xct_enabled,
        "xct_freq": ch.xct_freq,
        "xct_attack": ch.xct_attack,
        "xct_sustain": ch.xct_sustain,
        "xct_drive": ch.xct_drive,
        "xct_band_enabled": ch.xct_band_enabled,
        "tbe_enabled": ch.tbe_enabled,
        "tbe_drive": ch.tbe_drive,
        "tbe_band_enabled": ch.tbe_band_enabled,
    }


def capture_root(root: tk.Tk, path: Path) -> None:
    root.update_idletasks()
    root.update()
    time.sleep(0.35)
    root.update_idletasks()
    root.update()
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)


PRE_CONTROLS = {
    "pre-header": {
        "label": "PRE_HEADER",
        "row": None,
        "action": "press",
        "attr": "pre_enabled",
    },
    "pre-tbe": {
        "label": "PRE_TBE",
        "row": 0,
        "action": "press",
        "attr": "tube",
    },
    "pre-lpf-toggle": {
        "label": "PRE_LPF_TOGGLE",
        "row": 1,
        "action": "press",
        "attr": "lpf_enabled",
    },
    "pre-lpf-adjust": {
        "label": "PRE_LPF_ADJUST",
        "row": 1,
        "action": "adjust",
        "attr": "lpf_hz",
    },
    "pre-48v": {
        "label": "PRE_48V",
        "row": 2,
        "action": "press",
        "attr": "phantom",
    },
    "pre-phase": {
        "label": "PRE_PHASE",
        "row": 3,
        "action": "press",
        "attr": "phase",
    },
    "pre-hpf-toggle": {
        "label": "PRE_HPF_TOGGLE",
        "row": 4,
        "action": "press",
        "attr": "hpf_enabled",
    },
    "pre-hpf-adjust": {
        "label": "PRE_HPF_ADJUST",
        "row": 4,
        "action": "adjust",
        "attr": "hpf_hz",
    },
}

HRM_CONTROLS = {
    "hrm-header": {
        "label": "HRM_HEADER",
        "stage": "harm",
        "row": None,
        "action": "press",
        "attr": "harmonics_enabled",
    },
    "hrm-tbe": {
        "label": "HRM_TBE",
        "stage": "harm",
        "row": 0,
        "action": "press",
        "attr": "harm_tube",
    },
    "hrm-h1-adjust": {
        "label": "HRM_H1_ADJUST",
        "stage": "harm",
        "row": 1,
        "action": "adjust",
        "attr": "harmonics_0",
    },
    "hrm-h2-adjust": {
        "label": "HRM_H2_ADJUST",
        "stage": "harm",
        "row": 2,
        "action": "adjust",
        "attr": "harmonics_1",
    },
    "hrm-h3-adjust": {
        "label": "HRM_H3_ADJUST",
        "stage": "harm",
        "row": 3,
        "action": "adjust",
        "attr": "harmonics_2",
    },
    "hrm-h4-adjust": {
        "label": "HRM_H4_ADJUST",
        "stage": "harm",
        "row": 4,
        "action": "adjust",
        "attr": "harmonics_3",
    },
    "hrm-h5-adjust": {
        "label": "HRM_H5_ADJUST",
        "stage": "harm",
        "row": 5,
        "action": "adjust",
        "attr": "harmonics_4",
    },
}

GTE_CONTROLS = {
    "gte-header": {
        "label": "GTE_HEADER",
        "stage": "gate",
        "row": None,
        "action": "press",
        "attr": "gate_enabled",
    },
    "gte-tbe": {
        "label": "GTE_TBE",
        "stage": "gate",
        "row": 0,
        "action": "press",
        "attr": "gate_tube",
    },
    "gte-thr-adjust": {
        "label": "GTE_THR_ADJUST",
        "stage": "gate",
        "row": 1,
        "action": "adjust",
        "attr": "gate_threshold_db",
    },
    "gte-rat-adjust": {
        "label": "GTE_RAT_ADJUST",
        "stage": "gate",
        "row": 2,
        "action": "adjust",
        "attr": "gate_ratio",
    },
    "gte-atk-adjust": {
        "label": "GTE_ATK_ADJUST",
        "stage": "gate",
        "row": 3,
        "action": "adjust",
        "attr": "gate_attack_ms",
    },
    "gte-rls-adjust": {
        "label": "GTE_RLS_ADJUST",
        "stage": "gate",
        "row": 4,
        "action": "adjust",
        "attr": "gate_release_ms",
    },
    "gte-gan-adjust": {
        "label": "GTE_GAN_ADJUST",
        "stage": "gate",
        "row": 5,
        "action": "adjust",
        "attr": "gate_makeup",
    },
    "gte-frq-adjust": {
        "label": "GTE_FRQ_ADJUST",
        "stage": "gate",
        "row": 6,
        "action": "adjust",
        "attr": "gate_center_hz",
    },
    "gte-wdt-adjust": {
        "label": "GTE_WDT_ADJUST",
        "stage": "gate",
        "row": 7,
        "action": "adjust",
        "attr": "gate_width_oct",
    },
    "gte-bnd": {
        "label": "GTE_BND",
        "stage": "gate",
        "row": 8,
        "action": "press",
        "attr": "gate_band_enabled",
    },
}

CMP_CONTROLS = {
    "cmp-header": {"label": "CMP_HEADER", "stage": "comp", "row": None, "action": "press", "attr": "comp_enabled"},
    "cmp-tbe": {"label": "CMP_TBE", "stage": "comp", "row": 0, "action": "press", "attr": "comp_tube"},
    "cmp-thr-adjust": {"label": "CMP_THR_ADJUST", "stage": "comp", "row": 1, "action": "adjust", "attr": "comp_threshold_db"},
    "cmp-rat-adjust": {"label": "CMP_RAT_ADJUST", "stage": "comp", "row": 2, "action": "adjust", "attr": "comp_ratio"},
    "cmp-atk-adjust": {"label": "CMP_ATK_ADJUST", "stage": "comp", "row": 3, "action": "adjust", "attr": "comp_attack_ms"},
    "cmp-rls-adjust": {"label": "CMP_RLS_ADJUST", "stage": "comp", "row": 4, "action": "adjust", "attr": "comp_release_ms"},
    "cmp-gan-adjust": {"label": "CMP_GAN_ADJUST", "stage": "comp", "row": 5, "action": "adjust", "attr": "comp_makeup"},
    "cmp-frq-adjust": {"label": "CMP_FRQ_ADJUST", "stage": "comp", "row": 6, "action": "adjust", "attr": "comp_center_hz"},
    "cmp-wdt-adjust": {"label": "CMP_WDT_ADJUST", "stage": "comp", "row": 7, "action": "adjust", "attr": "comp_width_oct"},
    "cmp-bnd": {"label": "CMP_BND", "stage": "comp", "row": 8, "action": "press", "attr": "comp_band_enabled"},
}

EQ_CONTROLS = {
    "eq-header": {"label": "EQ_HEADER", "stage": "eq", "row": None, "action": "press", "attr": "eq_enabled"},
    "eq-tbe": {"label": "EQ_TBE", "stage": "eq", "row": 0, "action": "press", "attr": "eq_tube"},
    "eq-frq-adjust": {"label": "EQ_FRQ_ADJUST", "stage": "eq", "row": 1, "action": "adjust", "attr": "eq_freq"},
    "eq-gan-adjust": {"label": "EQ_GAN_ADJUST", "stage": "eq", "row": 2, "action": "adjust", "attr": "eq_gain_db"},
    "eq-shp": {"label": "EQ_SHP", "stage": "eq", "row": 3, "action": "press", "attr": "eq_param_bypass_SHP"},
    "eq-bnd-adjust": {"label": "EQ_BND_ADJUST", "stage": "eq", "row": 4, "action": "adjust", "attr": "eq_width"},
    "eq-trn-adjust": {"label": "EQ_TRN_ADJUST", "stage": "eq", "row": 5, "action": "adjust", "attr": "trn_freq"},
    "eq-atk-adjust": {"label": "EQ_ATK_ADJUST", "stage": "eq", "row": 6, "action": "adjust", "attr": "trn_attack"},
    "eq-sut-adjust": {"label": "EQ_SUT_ADJUST", "stage": "eq", "row": 7, "action": "adjust", "attr": "trn_sustain"},
    "eq-bd2": {"label": "EQ_BD2", "stage": "eq", "row": 8, "action": "press", "attr": "limit_band_enabled"},
}

TRN_CONTROLS = {
    "trn-header": {"label": "TRN_HEADER", "stage": "trn", "row": None, "action": "press", "attr": "trn_enabled"},
    "trn-frq-adjust": {"label": "TRN_FRQ_ADJUST", "stage": "trn", "row": 0, "action": "adjust", "attr": "trn_freq"},
    "trn-atk-adjust": {"label": "TRN_ATK_ADJUST", "stage": "trn", "row": 1, "action": "adjust", "attr": "trn_attack"},
    "trn-sut-adjust": {"label": "TRN_SUT_ADJUST", "stage": "trn", "row": 2, "action": "adjust", "attr": "trn_sustain"},
    "trn-drv-adjust": {"label": "TRN_DRV_ADJUST", "stage": "trn", "row": 3, "action": "adjust", "attr": "trn_drive"},
    "trn-bnd": {"label": "TRN_BND", "stage": "trn", "row": 4, "action": "press", "attr": "trn_band_enabled"},
}

XCT_CONTROLS = {
    "xct-header": {"label": "XCT_HEADER", "stage": "xct", "row": None, "action": "press", "attr": "xct_enabled"},
    "xct-frq-adjust": {"label": "XCT_FRQ_ADJUST", "stage": "xct", "row": 0, "action": "adjust", "attr": "xct_freq"},
    "xct-atk-adjust": {"label": "XCT_ATK_ADJUST", "stage": "xct", "row": 1, "action": "adjust", "attr": "xct_attack"},
    "xct-sut-adjust": {"label": "XCT_SUT_ADJUST", "stage": "xct", "row": 2, "action": "adjust", "attr": "xct_sustain"},
    "xct-drv-adjust": {"label": "XCT_DRV_ADJUST", "stage": "xct", "row": 3, "action": "adjust", "attr": "xct_drive"},
    "xct-bnd": {"label": "XCT_BND", "stage": "xct", "row": 4, "action": "press", "attr": "xct_band_enabled"},
}

TBE_CONTROLS = {
    "tbe-header": {"label": "TBE_HEADER", "stage": "tbe", "row": None, "action": "press", "attr": "tbe_enabled"},
    "tbe-drv-adjust": {"label": "TBE_DRV_ADJUST", "stage": "tbe", "row": 0, "action": "adjust", "attr": "tbe_drive"},
    "tbe-bnd": {"label": "TBE_BND", "stage": "tbe", "row": 1, "action": "press", "attr": "tbe_band_enabled"},
}

TRANSPORT_CONTROLS = {
    "tx-play": {"label": "TX_PLAY", "row": 0, "col": 0, "attr": "playing", "setup": "stopped"},
    "tx-stop": {"label": "TX_STOP", "row": 0, "col": 1, "attr": "playing", "setup": "playing_positioned"},
    "tx-rewind": {"label": "TX_REWIND", "row": 0, "col": 2, "attr": "channel0_position", "setup": "positioned"},
    "tx-forward": {"label": "TX_FORWARD", "row": 0, "col": 3, "attr": "channel0_position", "setup": "start_position"},
    "tx-record": {"label": "TX_RECORD", "row": 0, "col": 4, "attr": "channel0_record_armed", "setup": "stopped"},
    "tx-osc": {"label": "TX_OSC", "row": 1, "col": 0, "attr": "generator_mode", "setup": "generator_none"},
    "tx-pink": {"label": "TX_PINK", "row": 1, "col": 1, "attr": "generator_mode", "setup": "generator_none"},
    "tx-white": {"label": "TX_WHITE", "row": 1, "col": 2, "attr": "generator_mode", "setup": "generator_none"},
    "tx-pink-pulse": {"label": "TX_PINK_PULSE", "row": 1, "col": 3, "attr": "generator_mode", "setup": "generator_none"},
    "tx-white-hot": {"label": "TX_WHITE_HOT", "row": 1, "col": 4, "attr": "generator_mode", "setup": "generator_none"},
}

ALL_CONTROL_GROUPS = {
    "pre": PRE_CONTROLS,
    "hrm": HRM_CONTROLS,
    "gte": GTE_CONTROLS,
    "cmp": CMP_CONTROLS,
    "eq": EQ_CONTROLS,
    "trn": TRN_CONTROLS,
    "xct": XCT_CONTROLS,
    "tbe": TBE_CONTROLS,
}


def _prepare_transport_control(app: ConsoleApp, spec: dict[str, Any]) -> None:
    app.nav_scope = "transport"
    app.selected_channel = 0
    app.editor_channel = 0
    app.transport_focus_row = int(spec["row"])
    app.transport_focus_col = int(spec["col"])
    setup = spec.get("setup")
    app.engine.playing = False
    app.engine.generator_mode = "none"
    app.engine.channels[0].record_armed = False
    if setup == "playing_positioned":
        app.engine.playing = True
        app.engine.channels[0].position = 24000
    elif setup == "positioned":
        app.engine.channels[0].position = 24000
    elif setup == "start_position":
        app.engine.channels[0].position = 0
    app._sync_from_engine()


def verify_transport_control(run_dir: Path, control: str, spec: dict[str, Any]) -> dict[str, Any]:
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.update()

    try:
        _prepare_transport_control(app, spec)

        before_state = snapshot_state(app)
        before_png = run_dir / f"before_{control}.png"
        after_png = run_dir / f"after_{control}.png"
        capture_root(root, before_png)

        if spec.get("driver") == "click":
            btn = app.transport_cells[(int(spec["row"]), int(spec["col"]))]
            btn.event_generate("<Button-1>")
            app.root.update_idletasks()
            app.root.update()
        else:
            app._handle_nav("press")
        app._sync_from_engine()
        after_state = snapshot_state(app)
        capture_root(root, after_png)

        before_hash = sha256_file(before_png)
        after_hash = sha256_file(after_png)
        diff_bbox = image_diff_bbox(before_png, after_png)

        attr = str(spec["attr"])
        state_changed = before_state[attr] != after_state[attr]
        visual_changed = before_hash != after_hash and diff_bbox is not None
        passed = state_changed and visual_changed

        return {
            "control": spec["label"],
            "result": "PASS" if passed else "BLOCKED",
            "checks": {
                "real_app_class": type(app).__name__,
                "action": "press",
                "driver": spec.get("driver", "method"),
                "state_attr": attr,
                "state_changed": state_changed,
                "before_value": before_state[attr],
                "after_value": after_state[attr],
                "screenshot_hash_changed": before_hash != after_hash,
                "visual_diff_bbox": diff_bbox,
            },
            "before_state": before_state,
            "after_state": after_state,
            "screenshots": {
                "before": str(before_png),
                "after": str(after_png),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            },
        }
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()


def verify_transport_group(run_dir: Path) -> dict[str, Any]:
    results = []
    for control, spec in TRANSPORT_CONTROLS.items():
        control_dir = run_dir / control
        control_dir.mkdir(parents=True, exist_ok=True)
        result = verify_transport_control(control_dir, control, spec)
        (control_dir / "report.json").write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )
        results.append(result)

    failures = [r for r in results if r["result"] != "PASS"]
    return {
        "control": "TRANSPORT_ALL",
        "result": "PASS" if not failures else "BLOCKED",
        "checks": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "blocked": len(failures),
        },
        "results": results,
    }


def _prepare_stage_control(app: ConsoleApp, stage: str, row: int | None) -> None:
    app._open_stage_editor(0, stage)
    app.editor_stage_col = next(
        i for i, item in enumerate(app._STAGE_GRID) if item[0] == stage
    )
    app.editor_param_row = 0 if row is None else int(row)
    app.editor_unified_header_focus = row is None
    app.selected_stage_key = stage
    app._sync_from_engine()


def _perform_action(app: ConsoleApp, action: str) -> None:
    if action == "press":
        app._handle_nav("press")
    elif action == "adjust":
        app._adjust_unified_editor_cell(1.0)
    else:
        raise ValueError(action)
    app._sync_from_engine()


def _perform_editor_click(app: ConsoleApp, spec: dict[str, Any]) -> None:
    row = spec["row"]
    wanted = (
        ("stage_hdr", app.editor_stage_col)
        if row is None
        else ("stage_param", app.editor_stage_col, int(row))
    )
    app._sync_from_engine()
    app.root.update_idletasks()
    app.root.update()
    for x0, y0, x1, y1, tag in getattr(app, "editor_hitboxes", []):
        if tag == wanted:
            app.editor_canvas.event_generate(
                "<Button-1>",
                x=int((x0 + x1) / 2),
                y=int((y0 + y1) / 2),
            )
            app.root.update_idletasks()
            app.root.update()
            app._sync_from_engine()
            return
    raise RuntimeError(f"no editor hitbox for {wanted}")


def verify_control(run_dir: Path, control: str, spec: dict[str, Any]) -> dict[str, Any]:
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    root.update()

    try:
        _prepare_stage_control(app, str(spec.get("stage", "pre")), spec["row"])

        before_state = snapshot_state(app)
        before_png = run_dir / f"before_{control}.png"
        after_png = run_dir / f"after_{control}.png"
        capture_root(root, before_png)

        if spec.get("driver") == "click":
            _perform_editor_click(app, spec)
        else:
            _perform_action(app, str(spec["action"]))
        after_state = snapshot_state(app)
        capture_root(root, after_png)

        before_hash = sha256_file(before_png)
        after_hash = sha256_file(after_png)
        diff_bbox = image_diff_bbox(before_png, after_png)

        attr = str(spec["attr"])
        state_changed = before_state[attr] != after_state[attr]
        visual_changed = before_hash != after_hash and diff_bbox is not None
        passed = state_changed and visual_changed

        return {
            "control": spec["label"],
            "result": "PASS" if passed else "BLOCKED",
            "checks": {
                "real_app_class": type(app).__name__,
                "action": spec["action"],
                "driver": spec.get("driver", "method"),
                "state_attr": attr,
                "state_changed": state_changed,
                "before_value": before_state[attr],
                "after_value": after_state[attr],
                "screenshot_hash_changed": before_hash != after_hash,
                "visual_diff_bbox": diff_bbox,
            },
            "before_state": before_state,
            "after_state": after_state,
            "screenshots": {
                "before": str(before_png),
                "after": str(after_png),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            },
        }
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()


def verify_group(run_dir: Path, group_name: str, controls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results = []
    for control, spec in controls.items():
        control_dir = run_dir / control
        control_dir.mkdir(parents=True, exist_ok=True)
        result = verify_control(control_dir, control, spec)
        (control_dir / "report.json").write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )
        results.append(result)

    failures = [r for r in results if r["result"] != "PASS"]
    return {
        "control": group_name,
        "result": "PASS" if not failures else "BLOCKED",
        "checks": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "blocked": len(failures),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "control",
        choices=[
            *PRE_CONTROLS.keys(),
            *HRM_CONTROLS.keys(),
            *GTE_CONTROLS.keys(),
            *CMP_CONTROLS.keys(),
            *EQ_CONTROLS.keys(),
            *TRN_CONTROLS.keys(),
            *XCT_CONTROLS.keys(),
            *TBE_CONTROLS.keys(),
            *TRANSPORT_CONTROLS.keys(),
            "pre-all",
            "hrm-all",
            "gte-all",
            "cmp-all",
            "eq-all",
            "trn-all",
            "xct-all",
            "tbe-all",
            "transport-all",
            "click-smoke",
            "all",
        ],
        help="Control to verify. Add controls only after each one proves honest.",
    )
    args = parser.parse_args()

    run_dir = RUN_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.control == "pre-all":
        result = verify_group(run_dir, "PRE_ALL", PRE_CONTROLS)
    elif args.control == "hrm-all":
        result = verify_group(run_dir, "HRM_ALL", HRM_CONTROLS)
    elif args.control == "gte-all":
        result = verify_group(run_dir, "GTE_ALL", GTE_CONTROLS)
    elif args.control == "cmp-all":
        result = verify_group(run_dir, "CMP_ALL", CMP_CONTROLS)
    elif args.control == "eq-all":
        result = verify_group(run_dir, "EQ_ALL", EQ_CONTROLS)
    elif args.control == "trn-all":
        result = verify_group(run_dir, "TRN_ALL", TRN_CONTROLS)
    elif args.control == "xct-all":
        result = verify_group(run_dir, "XCT_ALL", XCT_CONTROLS)
    elif args.control == "tbe-all":
        result = verify_group(run_dir, "TBE_ALL", TBE_CONTROLS)
    elif args.control == "transport-all":
        result = verify_transport_group(run_dir)
    elif args.control == "click-smoke":
        click_editor = {
            "pre-header-click": {**PRE_CONTROLS["pre-header"], "driver": "click"},
            "pre-tbe-click": {**PRE_CONTROLS["pre-tbe"], "driver": "click"},
        }
        editor_result = verify_group(run_dir / "editor_clicks", "EDITOR_CLICK_SMOKE", click_editor)
        transport_results = []
        click_transport = {
            "tx-play-click": {**TRANSPORT_CONTROLS["tx-play"], "driver": "click"},
            "tx-record-click": {**TRANSPORT_CONTROLS["tx-record"], "driver": "click"},
        }
        for control, spec in click_transport.items():
            control_dir = run_dir / "transport_clicks" / control
            control_dir.mkdir(parents=True, exist_ok=True)
            result_item = verify_transport_control(control_dir, control, spec)
            (control_dir / "report.json").write_text(
                json.dumps(result_item, indent=2),
                encoding="utf-8",
            )
            transport_results.append(result_item)
        blocked = [r for r in [editor_result, *transport_results] if r["result"] != "PASS"]
        result = {
            "control": "CLICK_SMOKE",
            "result": "PASS" if not blocked else "BLOCKED",
            "checks": {
                "total": 1 + len(transport_results),
                "passed": 1 + len(transport_results) - len(blocked),
                "blocked": len(blocked),
            },
            "results": [editor_result, *transport_results],
        }
    elif args.control == "all":
        results = []
        for name, group in ALL_CONTROL_GROUPS.items():
            group_dir = run_dir / name
            group_dir.mkdir(parents=True, exist_ok=True)
            group_result = verify_group(group_dir, f"{name.upper()}_ALL", group)
            (group_dir / "report.json").write_text(
                json.dumps(group_result, indent=2),
                encoding="utf-8",
            )
            results.append(group_result)
        transport_dir = run_dir / "transport"
        transport_dir.mkdir(parents=True, exist_ok=True)
        transport_result = verify_transport_group(transport_dir)
        (transport_dir / "report.json").write_text(
            json.dumps(transport_result, indent=2),
            encoding="utf-8",
        )
        results.append(transport_result)
        failures = [r for r in results if r["result"] != "PASS"]
        result = {
            "control": "ALL_SYSTEM_Q_GROUPS",
            "result": "PASS" if not failures else "BLOCKED",
            "checks": {
                "groups": len(results),
                "passed_groups": len(results) - len(failures),
                "blocked_groups": len(failures),
            },
            "results": results,
        }
    elif args.control in PRE_CONTROLS:
        result = verify_control(run_dir, args.control, PRE_CONTROLS[args.control])
    elif args.control in HRM_CONTROLS:
        result = verify_control(run_dir, args.control, HRM_CONTROLS[args.control])
    elif args.control in GTE_CONTROLS:
        result = verify_control(run_dir, args.control, GTE_CONTROLS[args.control])
    elif args.control in CMP_CONTROLS:
        result = verify_control(run_dir, args.control, CMP_CONTROLS[args.control])
    elif args.control in EQ_CONTROLS:
        result = verify_control(run_dir, args.control, EQ_CONTROLS[args.control])
    elif args.control in TRN_CONTROLS:
        result = verify_control(run_dir, args.control, TRN_CONTROLS[args.control])
    elif args.control in XCT_CONTROLS:
        result = verify_control(run_dir, args.control, XCT_CONTROLS[args.control])
    elif args.control in TBE_CONTROLS:
        result = verify_control(run_dir, args.control, TBE_CONTROLS[args.control])
    elif args.control in TRANSPORT_CONTROLS:
        result = verify_transport_control(run_dir, args.control, TRANSPORT_CONTROLS[args.control])
    else:
        raise AssertionError(args.control)

    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"[system-q-verify] run_dir: {run_dir}")
    print(f"[system-q-verify] control: {result['control']}")
    print(f"[system-q-verify] result: {result['result']}")
    print(f"[system-q-verify] report: {report_path}")
    print(json.dumps(result["checks"], indent=2))

    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

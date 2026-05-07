import copy
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import system_q_console as mod


class DummySpaceMouse:
    def poll(self):
        return None


def snapshot_channel_state(ch):
    return {
        "gain": float(ch.gain),
        "send_slot": int(ch.send_slot),
        "send_level": float(ch.send_level),
        "send_muted": bool(ch.send_muted),
        "mute": bool(ch.mute),
        "solo": bool(ch.solo),
        "record_armed": bool(ch.record_armed),
        "pre": (
            bool(ch.pre_enabled),
            bool(ch.phantom),
            bool(ch.phase),
            bool(ch.tube),
            bool(ch.lpf_enabled),
            bool(ch.hpf_enabled),
            float(ch.lpf_hz),
            float(ch.hpf_hz),
        ),
        "harmonics": tuple(float(x) for x in ch.harmonics.tolist()),
        "harmonics_enabled": bool(ch.harmonics_enabled),
        "harmonic_makeup": float(ch.harmonic_makeup),
        "comp": (
            bool(ch.comp_enabled),
            bool(ch.limit_enabled),
            bool(ch.gate_enabled),
            float(ch.comp_threshold_db),
            float(ch.comp_ratio),
            float(ch.comp_attack_ms),
            float(ch.comp_release_ms),
            float(ch.comp_makeup),
            float(ch.comp_center_hz),
            float(ch.comp_width_oct),
            bool(ch.comp_band_enabled),
            float(ch.limit_center_hz),
            float(ch.limit_width_oct),
            bool(ch.limit_band_enabled),
            float(ch.gate_center_hz),
            float(ch.gate_width_oct),
            bool(ch.gate_band_enabled),
        ),
        "eq_enabled": bool(ch.eq_enabled),
        "eq_bands": tuple(
            (
                bool(b["enabled"]),
                float(b["freq"]),
                float(b["gain_db"]),
                float(b["width"]),
                str(b["type"]),
                bool(b["band_enabled"]),
            )
            for b in ch.eq_bands[: max(1, ch.eq_band_count)]
        ),
        "tone": (
            bool(ch.tone_enabled),
            float(ch.trn_freq),
            float(ch.trn_width),
            bool(ch.trn_band_enabled),
            float(ch.trn_attack),
            float(ch.trn_sustain),
            float(ch.clr_drive),
            float(ch.clr_tone),
            float(ch.clr_mix),
            float(ch.clr_gain),
            float(ch.xct_freq),
            float(ch.xct_width),
            bool(ch.xct_band_enabled),
            float(ch.xct_amount),
            float(ch.xct_mix),
        ),
    }


def make_app():
    mod.SpaceMouseController = DummySpaceMouse
    mod.ConsoleApp._schedule_refresh = lambda self: None
    root = tk.Tk()
    root.withdraw()
    app = mod.ConsoleApp(root)
    return root, app


def set_module_stage(app, stage):
    app.nav_scope = "editor"
    app.selected_stage_key = stage
    app.module_editor_column = 2
    app.editor_nav_scope = "body"
    app.comp_editor_mode = "COMP"
    app.eq_selected_band = 0
    app.tone_editor_mode = "TRN"
    app.module_editor_positions = {
        "left": 0,
        "stage": app._console_stage_keys().index(stage),
        "body": 0,
        "right": 0,
    }
    app._normalize_module_editor_positions()


def run_checks():
    root, app = make_app()
    errors = []

    # Stage row should cycle modules in order.
    app.nav_scope = "editor"
    app.selected_stage_key = "pre"
    app.module_editor_column = 1
    app.editor_nav_scope = "module-stage"
    app.module_editor_positions["stage"] = 0
    app._normalize_module_editor_positions()
    seen = []
    for _ in range(5):
        seen.append(app.selected_stage_key)
        app._handle_module_editor_nav("down")
    if seen != ["pre", "harm", "comp", "eq", "tone"]:
        errors.append(f"stage-down: expected ['pre', 'harm', 'comp', 'eq', 'tone'], got {seen}")

    # Body nav maps per stage.
    body_cases = [
        ("harm", 0, ["right"], [("harm", 2, 3)]),
        ("harm", 3, ["left"], [("harm", 2, 0)]),
        ("harm", 0, ["down", "down", "down"], [("harm", 2, 1), ("harm", 2, 2), ("harm", 2, 0)]),
        ("harm", 3, ["down", "down", "down"], [("harm", 2, 4), ("harm", 2, 5), ("harm", 2, 3)]),
        ("comp", 0, ["down", "down", "down", "down", "down"], [("comp", 2, 1), ("comp", 2, 2), ("comp", 2, 4), ("comp", 2, 5), ("comp", 2, 0)]),
        ("comp", 0, ["right"], [("comp", 2, 3)]),
        ("comp", 3, ["down", "down", "down", "down", "down"], [("comp", 2, 7), ("comp", 2, 8), ("comp", 2, 9), ("comp", 2, 6), ("comp", 2, 3)]),
        ("eq", 0, ["down", "down", "down"], [("eq", 2, 1), ("eq", 2, 3), ("eq", 2, 0)]),
        ("eq", 0, ["right"], [("eq", 2, 2)]),
        ("eq", 2, ["down", "down", "down"], [("eq", 2, 4), ("eq", 2, 5), ("eq", 2, 2)]),
        ("tone", 0, ["down", "down", "down"], [("tone", 2, 1), ("tone", 2, 2), ("tone", 2, 0)]),
        ("tone", 0, ["right"], [("tone", 2, 3)]),
        ("tone", 3, ["down", "down", "down", "down"], [("tone", 2, 4), ("tone", 2, 5), ("tone", 2, 6), ("tone", 2, 3)]),
    ]
    for stage, start_idx, moves, expected in body_cases:
        set_module_stage(app, stage)
        app.module_editor_positions["body"] = start_idx
        app._normalize_module_editor_positions()
        before = snapshot_channel_state(app._current_channel())
        actual = []
        for move in moves:
            app._handle_module_editor_nav(move)
            actual.append((app.selected_stage_key, app.module_editor_column, app.module_editor_positions["body"]))
        after = snapshot_channel_state(app._current_channel())
        if actual != expected:
            errors.append(f"{stage}-body moves {moves}: expected {expected}, got {actual}")
        if before != after:
            errors.append(f"{stage}-body nav changed channel state on moves {moves}")

    # Left/right columns should have exactly two positions and wrap.
    for stage in ["harm", "comp", "eq", "tone"]:
        set_module_stage(app, stage)
        before = snapshot_channel_state(app._current_channel())
        app.module_editor_column = 0
        app.module_editor_positions["left"] = 0
        app._handle_module_editor_nav("down")
        first = app.module_editor_positions["left"]
        app._handle_module_editor_nav("down")
        second = app.module_editor_positions["left"]
        app.module_editor_column = 3
        app.module_editor_positions["right"] = 0
        app._handle_module_editor_nav("down")
        right_first = app.module_editor_positions["right"]
        after = snapshot_channel_state(app._current_channel())
        if (first, second, right_first) != (1, 0, 1):
            errors.append(f"{stage}-side columns expected (1,0,1), got {(first, second, right_first)}")
        if before != after:
            errors.append(f"{stage}-side nav changed channel state")

    root.destroy()
    return errors


if __name__ == "__main__":
    failures = run_checks()
    if failures:
        print("FAIL")
        for failure in failures:
            print(failure)
        raise SystemExit(1)
    print("OK")

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from system_q_console import ConsoleApp  # noqa: E402


def main() -> int:
    root = tk.Tk()
    app = ConsoleApp(root, internal_capture=True, startup_play=False)
    try:
        app._open_stage_editor(0, "pre")
        app.editor_stage_col = 0
        app.editor_param_row = 1
        app.editor_unified_header_focus = False
        app.selected_stage_key = "pre"
        before = (app.nav_scope, app.selected_stage_key, app.editor_stage_col, app.editor_param_row, app.editor_unified_header_focus)
        for _ in range(40):
            app._adjust_unified_editor_cell(-1.0)
            app._adjust_unified_editor_cell(1.0)
        after = (app.nav_scope, app.selected_stage_key, app.editor_stage_col, app.editor_param_row, app.editor_unified_header_focus)
        if before != after:
            raise AssertionError(f"rotate moved focus: before={before} after={after}")
        print("PASS: rotate stays on focused parameter")
        return 0
    finally:
        app.engine.stop()
        app.engine.close()
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())

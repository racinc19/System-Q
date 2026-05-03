"""PNG proof: unified grid TBE row only affects tube routing flags, not inserts."""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

import tkinter as tk
from PIL import ImageGrab

_WIN32_PROCESS_PER_MONITOR_AWARE = 2


def _set_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(_WIN32_PROCESS_PER_MONITOR_AWARE)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _grab(widget: tk.Misc, out: Path) -> None:
    widget.update_idletasks()
    widget.update()
    x0 = int(widget.winfo_rootx())
    y0 = int(widget.winfo_rooty())
    x1 = x0 + max(int(widget.winfo_width()), 4)
    y1 = y0 + max(int(widget.winfo_height()), 4)
    ImageGrab.grab(bbox=(x0, y0, x1, y1)).save(out)


def _neutral_tbe_channel(ch, app) -> None:
    """All inserts bypassed; multiband off; zero harmonics lifts; tube flags cleared."""
    ch.pre_enabled = False
    ch.tube = False
    ch.harm_tube = False
    ch.gate_tube = False
    ch.comp_tube = False
    ch.eq_tube = False
    ch.lpf_enabled = False
    ch.hpf_enabled = False
    ch.phantom = False
    ch.phase = False

    ch.harmonics_enabled = False
    ch.harmonics[:] = 0.0

    ch.gate_enabled = False
    ch.comp_enabled = False
    ch.eq_enabled = False
    ch.eq_band_enabled = False
    ch.eq_band_count = 1
    ch.eq_param_bypass = {}
    ch.tone_enabled = False
    app.eq_selected_band = 0

    ch.transient_enabled = False
    ch.exciter_enabled = False
    ch.saturation_enabled = False
    ch.trn_attack = 0.0
    ch.trn_sustain = 0.0
    ch.clr_drive = 0.0
    ch.xct_amount = 0.0
    ch.trn_band_enabled = False
    ch.xct_band_enabled = False


def main() -> int:
    _set_dpi()
    soft = Path(__file__).resolve().parent
    sys.path.insert(0, str(soft))
    import system_q_console as sq  # noqa: PLC0415

    root = tk.Tk()
    root.geometry("1500x900")
    root.title("TBE grid proof")
    app = sq.ConsoleApp(root, startup_play=False)
    root.deiconify()
    root.lift()

    def settle(n: int = 28) -> None:
        for _ in range(n):
            root.update_idletasks()
            root.update()
            time.sleep(0.04)

    settle(36)

    app.nav_scope = "editor"
    app.editor_nav_scope = "stage_grid"
    app.editor_stage_col = 3
    app.editor_param_row = 1
    app.editor_unified_header_focus = False
    app.selected_stage_key = "pre"
    app.editor_channel = 0

    ch = app.engine.channels[0]
    _neutral_tbe_channel(ch, app)

    desk = Path.home() / "Desktop"

    settle(24)
    p_off = soft / "SYSTEM_Q_proof_tbe_all_off_inserts_off.png"
    _grab(app.editor_frame, p_off)
    print(f"Saved {p_off} (all inserts off; all TBE off)", flush=True)
    if desk.is_dir():
        _grab(app.editor_frame, desk / p_off.name)
        print(f"Saved {desk / p_off.name}", flush=True)

    # PRE TBE ON only via grid simulate
    plist = app._STAGE_GRID[0][2]
    app.editor_stage_col = 0
    app.editor_param_row = plist.index("TBE")
    ch.pre_enabled = False
    ch.tube = True
    app._sync_from_engine()
    settle(24)
    p_on = soft / "SYSTEM_Q_proof_tbe_PRE_only_on.png"
    _grab(app.editor_frame, p_on)
    print(f"Saved {p_on} (PRE TBE on; inserts still bypassed)", flush=True)
    if desk.is_dir():
        _grab(app.editor_frame, desk / p_on.name)
        print(f"Saved {desk / p_on.name}", flush=True)

    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

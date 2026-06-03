import tkinter as tk
from tkinter import ttk
import numpy as np
import math
import sys
import os
import logging
import atexit
import subprocess
import traceback
from pathlib import Path
from typing import Optional, Any

from system_q_core import (
    ChannelState,
    SYSTEM_Q_BUILD_ID
)
from system_q_dsp import ConsoleEngine
from pol_visualizer import SpaceMouseController
from system_q_ui import UIMixin

_log = logging.getLogger("system_q.console")

class ConsoleApp(UIMixin):
    def __init__(self, root: tk.Tk, *, internal_capture: bool = False, startup_play: bool = True) -> None:
        self.root = root
        self._internal_capture = internal_capture
        self._startup_play = bool(startup_play)
        instance_label = os.environ.get("SYSTEM_Q_CONSOLE_LABEL", "").strip()
        instance_mode = os.environ.get("SYSTEM_Q_CONSOLE_MODE", "").strip()
        title_scope = f" · {instance_label}" if instance_label else ""
        title_mode = f" · {instance_mode}" if instance_mode and instance_mode != "personal" else ""
        self.root.title(f"System Q Console{title_scope}{title_mode} · {SYSTEM_Q_BUILD_ID}")
        self.root.geometry("1560x960")
        self.root.configure(bg="#222831")
        
        self.engine = ConsoleEngine()
        _log.info(f"--- Audio Load Audit ---")
        for ch in self.engine.channels:
            alen = len(ch.audio) if ch.audio is not None else 0
            _log.info(f"Channel {ch.name}: {alen} samples")
        self.spacemouse = SpaceMouseController()
        
        # State
        self.selected_channel = 0
        self.editor_channel = 0
        self.selected_stage_key = "pre"
        self.nav_scope = "console"
        self.console_row = "stages"
        
        self.editor_stage_col = 0
        self.editor_param_row = 0
        self.editor_unified_header_focus = False
        
        self.transport_focus_row = 0
        self.transport_focus_col = 0
        
        self._syncing_controls = False
        
        # UI Build
        self._init_editor_state_vars()
        self._build_ui()
        
        if self._startup_play:
            self.engine.prime_stream()
            
        self._schedule_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _schedule_refresh(self) -> None:
        if not self._internal_capture:
            self._poll_spacemouse()
            self._sync_from_engine()
        self.root.after(16, self._schedule_refresh)

    def on_close(self) -> None:
        self.engine.stop()
        self.engine.close()
        self.root.destroy()
        sys.exit(0)

def main() -> None:
    log_file = Path(__file__).resolve().parent / "console_debug.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="a"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    instance = os.environ.get("SYSTEM_Q_CONSOLE_INSTANCE", "standalone")
    _log.info(f"System Q Console Starting. Build: {SYSTEM_Q_BUILD_ID}. Instance: {instance}")
    root = tk.Tk()
    app = ConsoleApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()

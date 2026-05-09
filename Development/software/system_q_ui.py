import tkinter as tk
from tkinter import ttk
import numpy as np
import math
import sys
import os
import time
import logging
import atexit
import subprocess
import traceback
from pathlib import Path
from typing import Optional, Any, Tuple, List

from system_q_core import (
    ChannelState, 
    POL_LOW_HZ, 
    POL_HIGH_HZ, 
    POL_BANDS, 
    POL_BAND_CENTER_HZ,
    POL_LEVEL_DB_AXIS_OUTER,
    POL_LEVEL_DB_AXIS_INNER,
    POL_LEVEL_GUIDE_TICKS_DB,
    POL_LEVEL_GUIDE_INNER_SCALE,
    POL_NEON_RED_HOT,
    freq_rainbow_hue_hz,
    hsv_to_hex,
    eq_spread_brightness_rgb,
    eq_rainbow_color,
    TONE_HEX_TRN,
    TONE_HEX_XCT,
    TONE_HEX_CLR,
    DISCRETE_TWIST_MIN
)

_log = logging.getLogger("system_q.ui")

def polar_edit_overlay_hex(
    layer_mix: float = 0.5,
    punch: float = 0.0,
    *,
    muted: bool = False,
    highlight: bool = False,
) -> str:
    m = float(np.clip(layer_mix, 0.0, 1.0))
    p = float(np.clip(punch, 0.0, 1.0))
    if muted:
        return hsv_to_hex(0.0, 0.38, float(np.clip(0.42 + m * 0.14 + p * 0.08, 0.40, 0.62)))
    if highlight:
        return POL_NEON_RED_HOT
    sat = float(np.clip(0.88 + m * 0.10, 0.82, 0.98))
    v = float(np.clip(0.72 + m * 0.22 + p * 0.10, 0.72, 1.0))
    return hsv_to_hex(0.0, sat, v)

class UIMixin:
    # --- UI Constants ---
    TRANSPORT_ROWS = 2
    TRANSPORT_COLS = 13
    TOP_CHANNEL_CONTROL_COUNT = 12
    TOP_MASTER_VOL_INDEX = 12
    TOP_BANK_INDEX = 13
    TOP_CONTROL_COUNT = 14
    SEND_SLOT_COUNT = 8
    GRID_HEADER_H_NORMAL = 44
    GRID_CELL_H_NORMAL = 52
    STRIP_WIDTH = 76

    _STAGE_GRID = [
        ("pre",  "PRE", ["TBE", "LPF", "48V", "PHS", "HPF"]),
        ("harm", "HRM", ["TBE", "H1", "H2", "H3", "H4", "H5"]),
        ("gate", "GTE", ["TBE", "THR", "DEP", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("comp", "CMP", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("eq",   "EQ",  ["TBE", "FRQ", "GAN", "SHP", "BND"]),
        ("trn",  "TRN", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("xct",  "XCT", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("tbe",  "TBE", ["FRQ", "DRV", "BND"]),
    ]

    STAGE_COLOR = {
        "pre": "#77f0c6", "harm": "#ffb757", "gate": "#ddc270", "comp": "#ff6a53",
        "eq": "#75baff", "trn": "#36e0dc", "xct": "#c06cff", "tbe": "#ff8f3a"
    }

    _TRANSPORT_BUTTONS = [
        (0, 0, "play_stop", "PLY/SPT", "#6ff0c1", "▶"),
        (0, 1, "advance", "ADV", "#89a0b6", "↔"),
        (0, 2, "record", "REC", "#ff3b30", "●"),
        (0, 3, "cycle", "CYC", "#fbbf24", "↻"),
        (0, 4, "prepost", "PRE/POST", "#e5e7eb", "⏱"),
        (0, 6, "channel_solo", "SOL", "#ffd166", "S"),
        (0, 7, "channel_mute", "MTE", "#ff6a53", "M"),
        (0, 8, "channel_arm", "REC", "#ff8fa3", "●"),
        (0, 9, "channel_pan", "PAN", "#75baff", "◉"),
        (0, 12, "oscillator", "OSC", "#fbbf24", "∿"),
        (1, 0, "undo", "UND", "#e5e7eb", "↶"),
        (1, 1, "cut", "CUT", "#fb7185", "✂"),
        (1, 2, "paste", "PST", "#86efac", "▣"),
        (1, 3, "copy", "CPY", "#93c5fd", "⧉"),
        (1, 4, "cancel_edit", "CNL", "#fca5a5", "×"),
        (1, 5, "zoom", "ZM", "#fcd34d", "⌕"),
        (1, 6, "shuttle_scrub", "SRB", "#9ca3af", "»"),
        (1, 8, "auto_read", "RED", "#7dd3fc", "R"),
        (1, 9, "auto_write", "WRT", "#f87171", "W"),
        (1, 10, "auto_trim", "TRM", "#fbbf24", "T"),
        (1, 11, "auto_latch", "LTC", "#c084fc", "L"),
    ]

    # --- Initialization & State ---
    def _init_editor_state_vars(self) -> None:
        self.selected_channel = 0
        self.editor_channel = 0
        self.selected_stage_key = "pre"
        self.nav_scope = "editor"
        self.console_row = "stages"
        
        self.editor_stage_col = 0
        self._v_nav_target = None
        self._v_nav_start_at = 0
        self.editor_param_row = 0
        self.editor_unified_header_focus = False
        self._module_body_memory: dict[str, int] = {}
        self._unified_editor_param_row_by_stage: dict[str, int] = {}
        
        self.knob_focus_channel = 0
        self.fader_focus_channel = 0
        self.transport_focus_row = 0
        self.transport_focus_col = 0
        self.footer_focus_side = "solo"
        self.fader_layer = 0
        self.top_control_focus = 0
        self.target_bank_mode = "ch"
        self.target_bank_offsets = {"ch": 0, "grp": 0, "aux": 0, "mst": 0}
        self.group_bus_states: list[ChannelState] = []
        self.aux_return_states: list[ChannelState] = []
        self.group_assign_mode = False
        self.group_assign_index = 0
        self._group_assign_press_after_id = None
        self._group_assign_press_fired = False
        self._group_assign_pending_tag = None
        self.fader_bank_offset = 0
        self.virtual_mixer_channels: list[ChannelState] = []
        self._last_bank_press_at = 0.0
        self._bank_click_after_id = None
        self.editor_top_focus = False
        self._last_cardinal_nav_at = 0.0
        self._last_editor_adjust_at = 0.0
        self._last_console_adjust_at = 0.0
        self._last_transport_adjust_at = 0.0
        self._last_spacemouse_pull_play_at = 0.0
        self._last_advance_press_at = 0.0
        self._down_nav_hold_started_at = 0.0
        self._down_nav_hold_fired = False
        self._transport_adjust_dir = 0
        self._transport_adjust_count = 0
        self._prepost_focus = "pre"
        self._edit_clipboard_action = ""
        self._edit_clipboard_audio: list[np.ndarray] | None = None
        self._edit_clipboard_markers: tuple[float, float] | None = None
        self._edit_clipboard_duration = 0.0
        self._edit_undo_state: dict[str, Any] | None = None
        self._edit_undo_stack: list[dict[str, Any]] = []
        self._edit_redo_stack: list[dict[str, Any]] = []
        self._edit_preview_region: tuple[float, float, str] | None = None
        self._edit_preview_audio: list[np.ndarray] | None = None
        self._shuttle_scrub_mode = "scrub"
        self._timeline_selection: tuple[str, int] | None = None
        self._scrub_audition_after_id = None
        
        self.strip_link_indices: set[int] = set()
        self.knobs_send_mode: bool = False
        
        # UI Vars for bindings (legacy support)
        self.pre_vars = {k: tk.DoubleVar() for k in ("gain", "pan", "lpf_hz", "hpf_hz", "pre_gain_db", "pre_squeeze")}
        self.pre_vars.update({k: tk.BooleanVar() for k in ("enabled", "phase", "tube", "lpf_enabled", "hpf_enabled", "phantom")})
        self.harm_vars = {"enabled": tk.BooleanVar(), "makeup": tk.DoubleVar()}
        self.harm_weight_vars = [tk.DoubleVar() for _ in range(5)]
        self.gate_vars = {k: tk.DoubleVar() for k in ("threshold", "ratio", "attack", "release", "makeup")}
        self.gate_vars["enabled"] = tk.BooleanVar()
        self.comp_vars = {k: tk.DoubleVar() for k in ("threshold", "ratio", "attack", "release", "makeup")}
        self.comp_vars["enabled"] = tk.BooleanVar()
        self.eq_vars = {"enabled": tk.BooleanVar(), "freq": tk.DoubleVar(), "gain": tk.DoubleVar(), "width": tk.DoubleVar()}
        self.trn_vars = {"enabled": tk.BooleanVar(), "freq": tk.DoubleVar(), "attack": tk.DoubleVar(), "sustain": tk.DoubleVar(), "drive": tk.DoubleVar()}
        self.xct_vars = {"enabled": tk.BooleanVar(), "freq": tk.DoubleVar(), "attack": tk.DoubleVar(), "sustain": tk.DoubleVar(), "drive": tk.DoubleVar()}
        self.tbe_vars = {"enabled": tk.BooleanVar(), "drive": tk.DoubleVar()}

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#222831"); top.pack(fill="x", padx=14, pady=(12, 8))
        self._editor_context_strip = tk.Frame(top, bg="#1a2230"); self._editor_context_strip.pack(fill="x", pady=(10, 0))
        self.editor_title = tk.Label(self._editor_context_strip, text="", bg="#1a2230", fg="#f2f3f6", font=("Segoe UI", 21, "bold")); self.editor_title.pack(anchor="w", fill="x", padx=10, pady=(6, 2))
        self.editor_subtitle = tk.Label(self._editor_context_strip, text="", bg="#141a21", fg="#8fa3b8", font=("Segoe UI", 10)); self.editor_subtitle.pack(anchor="w", fill="x", padx=10, pady=(0, 6))
        body = tk.Frame(self.root, bg="#222831"); body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        master = tk.Frame(body, bg="#180d12", bd=0, highlightthickness=1, highlightbackground="#7f1d1d", width=136); master.pack(side="right", fill="y", padx=(14, 0)); master.pack_propagate(False)
        self.master_canvas = tk.Canvas(master, bg="#180d12", highlightthickness=0); self.master_canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.master_canvas.bind("<Button-1>", self._on_master_strip_click)
        right = tk.Frame(body, bg="#161b22", bd=0, highlightthickness=1, highlightbackground="#344250", width=638); right.pack(side="right", fill="y", padx=(14, 0)); right.pack_propagate(False)
        left = tk.Frame(body, bg="#1f252d", bd=0, highlightthickness=1, highlightbackground="#344250"); left.pack(side="left", fill="both", expand=True)
        self.strip_canvas = tk.Canvas(left, bg="#1c222a", highlightthickness=0); self.strip_canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.strip_canvas.bind("<Button-1>", self._on_strip_click)
        self.editor_frame = right; self._build_editor(right)
        self._bind_nav_keys()

    def _build_editor(self, parent: tk.Frame) -> None:
        self.focus_canvas = tk.Canvas(parent, bg="#10151b", highlightthickness=0)
        self.focus_canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.editor_canvas = tk.Canvas(parent, bg="#10151b", highlightthickness=0)
        self.editor_canvas.pack(fill="x", padx=8, pady=(0, 8))
        self.editor_canvas.bind("<Button-1>", self._on_editor_canvas_click)
        self.editor_canvas.bind("<ButtonRelease-1>", self._on_editor_canvas_release)
        self.editor_canvas.bind("<Double-Button-1>", self._on_editor_canvas_double_click)
        self.timeline_canvas = tk.Canvas(parent, bg="#0b1016", highlightthickness=1, highlightbackground="#263342", height=116)
        self.timeline_canvas.bind("<Button-1>", self._on_timeline_click)
        def _global_click(e):
            transport_widgets = set(getattr(self, "transport_cells", {}).values())
            if e.widget in transport_widgets or e.widget is getattr(self, "transport_panel", None) or e.widget is getattr(self, "timeline_canvas", None):
                return
            # If clicked on the editor surface, assume editor focus.
            if e.widget is self.editor_canvas or e.widget is self.focus_canvas:
                self.nav_scope = "editor"
        self.root.bind("<Button-1>", _global_click, add="+")
        
        # Timeline is the bottom-most editor element; transport sits directly above it.
        self.timeline_canvas.pack(fill="x", side="bottom", padx=8, pady=(0, 8))
        self.transport_panel = self._build_transport_panel(parent)
        self.transport_panel.pack(fill="x", side="bottom", padx=8, pady=(0, 8))

    def _build_transport_panel(self, parent: tk.Frame) -> tk.Frame:
        f = tk.Frame(parent, bg="#0c1118")
        self.transport_cells = {}
        for r, c, k, l, clr, glyph in self._TRANSPORT_BUTTONS:
            if k == "channel_pan":
                btn = tk.Canvas(f, bg="#151a21", highlightthickness=0, width=74, height=54)
                btn._base_text = "PAN"
            else:
                btn = tk.Label(f, text=f"{glyph}\n{l}", bg="#151a21", fg=clr, font=("Segoe UI", 9, "bold"), width=8, height=3, relief="flat", bd=2)
                btn._base_text = f"{glyph}\n{l}"
            btn._base_fg = clr
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            btn.bind("<Button-1>", lambda _e, row=r, col=c: self._on_transport_click(row, col))
            self.transport_cells[(r, c)] = btn
        for c in range(self.TRANSPORT_COLS):
            f.grid_columnconfigure(c, weight=1, uniform="transport")
        for c in (3, 8, 5):
            f.grid_columnconfigure(c, minsize=12)
        return f

    def _bind_nav_keys(self) -> None:
        self.root.bind("<Left>", lambda e: self._handle_nav("left"))
        self.root.bind("<Right>", lambda e: self._handle_nav("right"))
        self.root.bind("<Up>", lambda e: self._handle_nav("up"))
        self.root.bind("<Down>", lambda e: self._handle_nav("down"))
        self.root.bind("<Return>", lambda e: self._handle_nav("press"))
        self.root.bind("<space>", lambda e: self._handle_nav("press"))
        self.root.bind("<Escape>", lambda e: self._handle_nav("back"))
        self.root.bind("[", lambda e: (logging.getLogger("system_q.ui").info("KEY_PRESS: ["), self._adjust_focused_axis(-0.35)))
        self.root.bind("]", lambda e: (logging.getLogger("system_q.ui").info("KEY_PRESS: ]"), self._adjust_focused_axis(0.35)))

    # --- Transport Actions ---
    def _tx_play_stop(self) -> None: self.engine.toggle_play(); self._sync_from_engine()
    def _tx_play(self) -> None: self._tx_play_stop()
    def _flash_transport_action(self, key: str) -> None:
        self._transport_flash = (key, time.time())

    def _tx_stop(self) -> None: self._flash_transport_action("stop"); self.engine.stop(); self._sync_from_engine()
    def _tx_rewind(self) -> None: self._flash_transport_action("rewind"); self.engine.rewind(); self._sync_from_engine()
    def _tx_forward(self) -> None: self._flash_transport_action("forward"); self.engine.jump_forward(); self._sync_from_engine()
    def _tx_advance(self) -> None:
        now = time.monotonic()
        if now - float(getattr(self, "_last_advance_press_at", 0.0)) < 0.45:
            self._flash_transport_action("advance_end")
            self.engine.jump_end()
        else:
            self._flash_transport_action("advance_home")
            self.engine.rewind()
        self._last_advance_press_at = now
        self._sync_from_engine()

    def _tx_record(self) -> None:
        self._flash_transport_action("record")
        self.engine.toggle_record()
        self._sync_from_engine()

    def _tx_cycle(self) -> None:
        self.engine.toggle_loop()
        self._flash_transport_action("cycle")
        self._sync_from_engine()

    def _tx_channel_solo(self) -> None:
        ch = self._current_channel()
        if ch is not self.engine.master_channel:
            ch.solo = not bool(getattr(ch, "solo", False))
        self._sync_from_engine()

    def _tx_channel_mute(self) -> None:
        ch = self._current_channel()
        if ch is not self.engine.master_channel:
            ch.mute = not bool(getattr(ch, "mute", False))
        self._sync_from_engine()

    def _tx_channel_arm(self) -> None:
        ch = self._current_channel()
        if ch is not self.engine.master_channel:
            ch.record_armed = not bool(getattr(ch, "record_armed", False))
        self._sync_from_engine()

    def _tx_channel_pan(self) -> None:
        ch = self._current_channel()
        if ch is not self.engine.master_channel:
            ch.pan = 0.0
        self._flash_transport_action("channel_pan")
        self._sync_from_engine()

    def _set_generator_mode(self, mode: str) -> None:
        self.engine.generator_mode = "none" if self.engine.generator_mode == mode else mode
        self._sync_from_engine()

    def _tx_oscillator(self) -> None: self._set_generator_mode("osc")
    def _tx_pink(self) -> None: self._set_generator_mode("pink")
    def _tx_white(self) -> None: self._set_generator_mode("white")
    def _tx_pink_pulse(self) -> None: self._set_generator_mode("pink_pulse")
    def _tx_white_hot(self) -> None: self._set_generator_mode("white_hot")
    def _tx_marker(self) -> None:
        self._push_edit_undo("marker")
        self.engine.add_marker()
        self._timeline_selection = None
        self._flash_transport_action("marker")
        self._sync_from_engine()
    def _tx_shuttle(self) -> None: self._flash_transport_action("shuttle"); self._sync_from_engine()
    def _tx_scrub(self) -> None: self._flash_transport_action("scrub"); self._sync_from_engine()
    def _tx_shuttle_scrub(self) -> None:
        self._timeline_selection = None
        self._shuttle_scrub_mode = "shuttle" if getattr(self, "_shuttle_scrub_mode", "scrub") == "scrub" else "scrub"
        _log.info(f"SHUTTLE_SCRUB_TOGGLE: mode={self._shuttle_scrub_mode}")
        self._flash_transport_action("shuttle_scrub")
        self._sync_from_engine()

    def _audition_scrub_motion(self, hold_ms: int = 260, *, freeze_playhead: bool = True) -> None:
        until = time.monotonic() + max(0.12, hold_ms / 1000.0)
        self.engine.ignore_marker_cycle_until = max(
            float(getattr(self.engine, "ignore_marker_cycle_until", 0.0)),
            until,
        )
        self.engine.scrub_audition_until = until
        self.engine.scrub_audition_freeze = bool(freeze_playhead)
        was_playing = bool(getattr(self.engine, "playing", False))
        if getattr(self.engine, "stream", None) is None:
            self.engine.prime_stream()
        after_id = getattr(self, "_scrub_audition_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        if not was_playing:
            def _stop_audition() -> None:
                self._scrub_audition_after_id = None
                self.engine.scrub_audition_until = 0.0
                self.engine.scrub_audition_freeze = False
                self.engine.playing = False
            self._scrub_audition_after_id = self.root.after(hold_ms, _stop_audition)

    def _release_timeline_selection_for_transport(self, hold_seconds: float = 2.0) -> None:
        self._timeline_selection = None
        self.engine.ignore_marker_cycle_until = max(
            float(getattr(self.engine, "ignore_marker_cycle_until", 0.0)),
            time.monotonic() + max(0.2, float(hold_seconds)),
        )
    def _tx_cut(self) -> None:
        if self._has_edit_clipboard("cut"):
            self._push_edit_undo("discard cut")
            self._clear_edit_clipboard()
        else:
            if self._copy_selected_region_to_clipboard(cut=True):
                self.nav_scope = "timeline"
        self._flash_transport_action("cut")
        self._sync_from_engine()

    def _tx_copy(self) -> None:
        if self._has_edit_clipboard("copy"):
            self._paste_clipboard_at_playhead(clear_after=True)
        else:
            if self._copy_selected_region_to_clipboard(cut=False):
                self.nav_scope = "timeline"
        self._flash_transport_action("copy")
        self._sync_from_engine()

    def _tx_paste(self) -> None:
        self._paste_clipboard_at_playhead(clear_after=True)
        self._flash_transport_action("paste")
        self._sync_from_engine()
    def _tx_cancel_edit(self) -> None:
        if self._has_edit_clipboard():
            if self._has_edit_clipboard("cut") and self._edit_undo_stack:
                self._restore_edit_undo()
            else:
                self._push_edit_undo("cancel edit")
                self._clear_edit_clipboard()
        self._timeline_selection = None
        self._flash_transport_action("cancel_edit")
        self._sync_from_engine()
    def _tx_undo(self) -> None:
        if getattr(self, "_edit_undo_stack", None):
            self._restore_edit_undo()
        elif getattr(self, "_edit_redo_stack", None):
            self._restore_edit_redo()
        self._flash_transport_action("undo")
        self._sync_from_engine()
    def _tx_redo(self) -> None:
        self._restore_edit_redo()
        self._flash_transport_action("undo")
        self._sync_from_engine()
    def _tx_zoom(self) -> None:
        self.engine.timeline_zoom = 1.0
        self._flash_transport_action("zoom")
        self._sync_from_engine()
    def _set_automation_mode(self, mode: str) -> None:
        self.engine.automation_mode = mode
        self._flash_transport_action(f"auto_{mode}")
        self._sync_from_engine()
    def _tx_auto_read(self) -> None: self._set_automation_mode("read")
    def _tx_auto_write(self) -> None: self._set_automation_mode("write")
    def _tx_auto_trim(self) -> None: self._set_automation_mode("trim")
    def _tx_auto_latch(self) -> None: self._set_automation_mode("latch")
    def _tx_prepost(self) -> None:
        self._prepost_focus = "post" if getattr(self, "_prepost_focus", "pre") == "pre" else "pre"
        self._flash_transport_action("prepost")
        self._sync_from_engine()

    # --- Core Accessors ---
    def _active_channel_index(self) -> int:
        return self.editor_channel if getattr(self, "nav_scope", "console") == "editor" else self.selected_channel

    def _current_channel(self) -> ChannelState:
        mode = getattr(self, "target_bank_mode", "ch")
        idx = self._active_channel_index()
        return self._target_at(mode, idx)

    def _target_at(self, mode: str, idx: int) -> ChannelState:
        mode = mode if mode in ("ch", "grp", "aux", "mst") else "ch"
        idx = max(0, int(idx))
        if mode == "mst":
            return self.engine.master_channel
        if mode == "grp":
            return self._bus_channel_at(self.group_bus_states, "Group", "group_bus", idx)
        if mode == "aux":
            return self._bus_channel_at(self.aux_return_states, "Aux", "aux_return", idx)
        return self._mixer_channel_at(idx)

    def _bus_channel_at(self, store: list[ChannelState], name_prefix: str, path_prefix: str, idx: int) -> ChannelState:
        idx = max(0, int(idx))
        while len(store) <= idx:
            bus_num = len(store) + 1
            store.append(ChannelState(name=f"{name_prefix} {bus_num:02d}", path=Path(f"{path_prefix}_{bus_num:02d}")))
        return store[idx]

    def _target_count_for_mode(self, mode: str) -> int:
        if mode == "mst":
            return 1
        if mode in ("grp", "aux"):
            return 12
        return min(len(self.engine.channels), self.TOP_CHANNEL_CONTROL_COUNT)

    def _target_mode_label(self, mode: Optional[str] = None) -> str:
        mode = mode or getattr(self, "target_bank_mode", "ch")
        return {"ch": "FDR", "grp": "GRP", "aux": "AUX", "mst": "MST"}.get(mode, "FDR")

    def _target_display_label(self, mode: str, idx: int) -> str:
        if mode == "mst":
            return "MST"
        prefix = {"grp": "G", "aux": "A"}.get(mode, "")
        return f"{prefix}{idx + 1}" if prefix else str(idx + 1)

    def _channel_group_assignments(self, ch: ChannelState) -> set[int]:
        groups = getattr(ch, "group_assignments", None)
        if groups is None:
            groups = set()
            setattr(ch, "group_assignments", groups)
        if not isinstance(groups, set):
            groups = set(int(g) for g in groups)
            setattr(ch, "group_assignments", groups)
        return groups

    def _channel_in_group(self, ch: Optional[ChannelState], group_idx: int) -> bool:
        return ch is not None and int(group_idx) in self._channel_group_assignments(ch)

    def _channel_primary_group(self, ch: Optional[ChannelState]) -> Optional[int]:
        if ch is None:
            return None
        groups = sorted(int(g) for g in self._channel_group_assignments(ch))
        return groups[0] if groups else None

    def _toggle_channel_group_assignment(self, channel_idx: int, group_idx: Optional[int] = None) -> None:
        if not (0 <= int(channel_idx) < len(self.engine.channels)):
            return
        group_idx = int(getattr(self, "group_assign_index", 0) if group_idx is None else group_idx)
        ch = self.engine.channels[int(channel_idx)]
        groups = self._channel_group_assignments(ch)
        if group_idx in groups:
            groups.clear()
        else:
            groups.clear()
            groups.add(group_idx)
        _log.info(f"GROUP_ASSIGN_TOGGLE: channel={channel_idx + 1} group=G{group_idx + 1} assigned={group_idx in groups}")

    def _enter_group_assign_mode(self, group_idx: int) -> None:
        self.group_assign_mode = True
        self.group_assign_index = max(0, int(group_idx))
        self.target_bank_mode = "ch"
        self.fader_layer = 0
        self.knobs_send_mode = False
        self.editor_top_focus = True
        self.nav_scope = "editor"
        self.top_control_focus = 0
        self.selected_channel = self.editor_channel = 0
        _log.info(f"GROUP_ASSIGN_ENTER: group=G{self.group_assign_index + 1}")

    def _exit_group_assign_mode(self) -> None:
        if bool(getattr(self, "group_assign_mode", False)):
            _log.info(f"GROUP_ASSIGN_EXIT: group=G{int(getattr(self, 'group_assign_index', 0)) + 1}")
        self.group_assign_mode = False
        self.target_bank_mode = "grp"
        self.editor_top_focus = True
        self.nav_scope = "editor"
        self.top_control_focus = min(int(getattr(self, "group_assign_index", 0)), self.TOP_CHANNEL_CONTROL_COUNT - 1)
        self.selected_channel = self.editor_channel = int(getattr(self, "group_assign_index", 0))

    def _target_bank_offset(self, mode: Optional[str] = None) -> int:
        mode = mode or getattr(self, "target_bank_mode", "ch")
        if mode == "ch":
            return int(getattr(self, "fader_bank_offset", 0))
        return int(getattr(self, "target_bank_offsets", {}).get(mode, 0))

    def _set_target_bank_offset(self, mode: str, value: int) -> None:
        max_off = self._max_target_bank_offset(mode)
        value = int(np.clip(int(value), 0, max_off))
        if mode == "ch":
            self.fader_bank_offset = value
        self.target_bank_offsets[mode] = value

    def _max_target_bank_offset(self, mode: str) -> int:
        return max(0, self._target_count_for_mode(mode) - self.TOP_CHANNEL_CONTROL_COUNT)

    def _cycle_target_bank_mode(self, direction: int = 1) -> None:
        modes = ["ch", "grp", "aux"]
        cur = getattr(self, "target_bank_mode", "ch")
        i = modes.index(cur) if cur in modes else 0
        self.target_bank_mode = modes[(i + (1 if direction >= 0 else -1)) % len(modes)]
        self.editor_channel = self.selected_channel = 0

    def _console_stage_keys(self, channel_index: Optional[int] = None) -> List[str]:
        idx = self._active_channel_index() if channel_index is None else channel_index
        if self._is_master_nav_index(idx):
            return ["pre", "harm", "gate", "comp", "eq", "trn", "xct", "tbe"]
        return ["pre", "harm", "gate", "comp", "eq", "trn", "xct", "tbe"]

    def _stage_grid_for_channel(self, ch: ChannelState) -> list[tuple[str, str, list[str]]]:
        if ch is self.engine.master_channel:
            return [("pre", "FLT", ["LPF", "HPF"])] + [(key, lbl, params) for key, lbl, params in self._STAGE_GRID if key != "pre"]
        return self._STAGE_GRID

    def _channel_nav_span(self) -> int:
        return max(len(self.engine.channels), 96) + 1

    def _master_nav_index(self) -> int:
        return self._channel_nav_span() - 1

    def _is_master_nav_index(self, idx: int) -> bool:
        return int(idx) == self._master_nav_index()

    def _mixer_channel_at(self, idx: int) -> ChannelState:
        idx = max(0, int(idx))
        if self._is_master_nav_index(idx):
            return self.engine.master_channel
        if idx < len(self.engine.channels):
            return self.engine.channels[idx]
        v_idx = idx - len(self.engine.channels)
        while len(self.virtual_mixer_channels) <= v_idx:
            ch_num = len(self.engine.channels) + len(self.virtual_mixer_channels) + 1
            self.virtual_mixer_channels.append(ChannelState(name=f"Channel {ch_num:02d}", path=Path(f"virtual_channel_{ch_num:02d}")))
        return self.virtual_mixer_channels[v_idx]

    def _visible_bank_channels(self) -> list[tuple[int, ChannelState]]:
        start = min(int(getattr(self, "fader_bank_offset", 0)), self._max_fader_bank_offset())
        self.fader_bank_offset = start
        channel_limit = min(len(self.engine.channels), self.TOP_CHANNEL_CONTROL_COUNT)
        count = max(0, min(self.TOP_CHANNEL_CONTROL_COUNT, channel_limit - start))
        return [(start + i, self.engine.channels[start + i]) for i in range(count)]

    def _visible_strip_targets(self) -> tuple[str, list[tuple[int, ChannelState]]]:
        mode = getattr(self, "target_bank_mode", "ch")
        if mode == "ch":
            return mode, self._visible_bank_channels()
        offset = self._target_bank_offset(mode)
        count = self._target_count_for_mode(mode)
        visible_count = max(0, min(self.TOP_CHANNEL_CONTROL_COUNT, count - offset))
        return mode, [(offset + i, self._target_at(mode, offset + i)) for i in range(visible_count)]

    # --- Sync & Commit ---
    def _sync_from_engine(self) -> None:
        self._syncing_controls = True
        try:
            self.engine.master_channel.gain = float(getattr(self.engine, "master_gain", self.engine.master_channel.gain))
            ch = self._current_channel()
            mode = getattr(self, "target_bank_mode", "ch")
            self.editor_title.config(text=f"{ch.name}  ·  {self._stage_label(self.selected_stage_key, ch)}")
            if mode == "ch" and self._is_master_nav_index(self._active_channel_index()):
                sub = "MASTER BUS"
            elif mode == "ch":
                sub = f"{self._active_channel_index()+1:02d}  {ch.path.name}" if self._active_channel_index() < len(self.engine.channels) else f"CHANNEL {self._active_channel_index()+1:02d}"
            elif mode == "grp":
                sub = f"GROUP BUS {self._active_channel_index()+1:02d}"
            elif mode == "aux":
                sub = f"AUX RETURN {self._active_channel_index()+1:02d}"
            else:
                sub = "MASTER BUS"
            self.editor_subtitle.config(text=sub)
            
            self.pre_vars["enabled"].set(ch.pre_enabled)
            self.pre_vars["phase"].set(ch.phase)
            self.pre_vars["tube"].set(ch.tube)
            self.pre_vars["lpf_enabled"].set(ch.lpf_enabled)
            self.pre_vars["hpf_enabled"].set(ch.hpf_enabled)
            self.pre_vars["gain"].set(ch.gain)
            self.pre_vars["pan"].set(ch.pan)
            self.pre_vars["pre_gain_db"].set(getattr(ch, "pre_gain_db", 0.0))
            self.pre_vars["pre_squeeze"].set(getattr(ch, "pre_squeeze", 1.0))
            self.pre_vars["lpf_hz"].set(ch.lpf_hz)
            self.pre_vars["hpf_hz"].set(ch.hpf_hz)
            
            self.harm_vars["enabled"].set(ch.harmonics_enabled)
            for i, v in enumerate(ch.harmonics): self.harm_weight_vars[i].set(v)
            
            self.comp_vars["enabled"].set(ch.comp_enabled)
            self.eq_vars["enabled"].set(ch.eq_enabled)
            
            # Sync ALL stage variables to ensure UI state is valid
            for sk in ("gate", "comp", "eq", "trn", "xct", "tbe"):
                if hasattr(self, f"{sk}_vars"):
                    v = getattr(self, f"{sk}_vars")
                    if "enabled" in v: v["enabled"].set(getattr(ch, f"{sk}_enabled", False))

            # Update pulse state for breathing polar (with idle heartbeat)
            p_val = getattr(self, "_pol_pulse_cached", 0.0)
            idle_p = 0.04 + 0.04 * math.sin(time.time() * 3.0)
            target_p = float(np.clip(self.engine.master_level * 1.8 + idle_p, 0.0, 1.0))
            self._pol_pulse_cached = p_val * 0.6 + target_p * 0.4
            
            self._draw_strips()
            self._draw_master_panel()
            self._draw_focus()
            self._draw_editor_controls()
            self._sync_play_transport_glyph()
            self._draw_timeline()
        except Exception: 
            _log.error("Sync Error: " + traceback.format_exc())
        self._syncing_controls = False

    def _sync_play_transport_glyph(self) -> None:
        ns = getattr(self, "nav_scope", "console")
        tr_foc = (ns == "transport")
        tr_r, tr_c = getattr(self, "transport_focus_row", 0), getattr(self, "transport_focus_col", 0)
        is_playing = getattr(self.engine, "playing", False)
        focus_outline = hsv_to_hex((time.time() * 0.18) % 1.0, 0.95, 1.0)
        
        for (r, c), btn in self.transport_cells.items():
            is_f = tr_foc and r == tr_r and c == tr_c
            # Base colors
            bg = "#3d526b" if is_f else "#151a21"
            fg = getattr(btn, "_base_fg", "#d6e1ec")
            
            key = self._transport_button_at(r, c)
            action = key[0] if key else ""
            if action == "channel_pan":
                ch = self._current_channel()
                self._draw_transport_pan_knob(btn, float(getattr(ch, "pan", 0.0)), focused=is_f, bg=bg, focus_outline=focus_outline)
                continue
            base_text = getattr(btn, "_base_text", btn.cget("text"))
            btn.config(text=base_text)
            flash_key, flash_at = getattr(self, "_transport_flash", ("", 0.0))
            if action == flash_key and action != "prepost" and time.time() - float(flash_at) < 0.55:
                bg = "#f8d58a" if not is_f else "#ffe9a8"
                fg = "#0b1016"
            # Special case for Play/Stop button state
            elif action == "play_stop":
                if is_playing:
                    bg = "#2a4a3e" if not is_f else "#3d6b5a"
                    fg = "#6ff0c1"
                    btn.config(text="■\nSTOP")
                else:
                    fg = "#4a635a" if not is_f else "#6ff0c1"
                    btn.config(text="▶\nPLAY")
            elif action == "record":
                if bool(getattr(self.engine, "recording", False)):
                    bg = "#4a1820" if not is_f else "#6a2230"
                    fg = "#ff9aa8"
                    label = "PUNCH" if bool(getattr(self.engine, "punch_recording", False)) else "REC"
                    btn.config(text=f"●\n{label}")
                else:
                    btn.config(text="●\nREC")
            elif action == "cycle":
                if bool(getattr(self.engine, "loop", False)):
                    bg = "#4a3b17" if not is_f else "#6b5523"
                    fg = "#fbbf24"
            elif action in ("channel_solo", "channel_mute", "channel_arm"):
                ch = self._current_channel()
                active = (
                    (action == "channel_solo" and bool(getattr(ch, "solo", False))) or
                    (action == "channel_mute" and bool(getattr(ch, "mute", False))) or
                    (action == "channel_arm" and bool(getattr(ch, "record_armed", False)))
                )
                if active:
                    bg = "#4a3b17" if action == "channel_solo" else "#4a1820"
                    if is_f:
                        bg = "#6b5523" if action == "channel_solo" else "#6a2230"
                    fg = "#fff0b2" if action == "channel_solo" else "#ffb3bd"
            elif action in ("oscillator", "pink", "white", "pink_pulse", "white_hot"):
                mode = "osc" if action == "oscillator" else action
                if getattr(self.engine, "generator_mode", "none") == mode:
                    bg = "#3c3340" if not is_f else "#5a4d60"
                    fg = "#ffd37a"
            elif action in ("auto_read", "auto_write", "auto_trim", "auto_latch"):
                mode = action.split("_", 1)[1]
                if getattr(self.engine, "automation_mode", "read") == mode:
                    bg = "#263f55" if not is_f else "#345a78"
                    fg = "#d8f3ff"
            elif action == "prepost":
                pre = float(getattr(self.engine, "pre_roll_seconds", 0.0))
                post = float(getattr(self.engine, "post_roll_seconds", 0.0))
                is_pre = getattr(self, "_prepost_focus", "pre") == "pre"
                tag = "PRE" if is_pre else "PST"
                val = pre if is_pre else post
                btn.config(text=f"{tag}\n{val:.1f}s")
                bg = "#263f55" if not is_f else "#345a78"
                fg = "#d8f3ff"
            elif action == "zoom":
                btn.config(text=f"⌕\n{float(getattr(self.engine, 'timeline_zoom', 1.0)):.1f}x")
            elif action == "undo":
                if getattr(self, "_edit_undo_stack", None):
                    bg = "#27313f" if not is_f else "#3d526b"
                    fg = "#f8fafc"
                    btn.config(text=f"↶\nUND {len(getattr(self, '_edit_undo_stack', []))}")
                elif getattr(self, "_edit_redo_stack", None):
                    bg = "#202b24" if not is_f else "#34533c"
                    fg = "#bbf7d0"
                    btn.config(text=f"↷\nRDO {len(getattr(self, '_edit_redo_stack', []))}")
            elif action == "cancel_edit":
                if self._has_edit_clipboard():
                    bg = "#4a1820" if not is_f else "#6a2230"
                    fg = "#ffd0dc"
            elif action in ("cut", "copy", "paste"):
                if self._has_edit_clipboard("cut" if action == "cut" else "copy" if action == "copy" else None):
                    bg = "#3b2530" if action == "cut" else "#203348"
                    if is_f:
                        bg = "#5b3648" if action == "cut" else "#345276"
                    fg = "#ffd0dc" if action == "cut" else "#cde7ff"
            elif action == "shuttle_scrub":
                mode = getattr(self, "_shuttle_scrub_mode", "scrub")
                btn.config(text=("»\nSHT" if mode == "shuttle" else "≋\nSCR"))
                if mode == "shuttle":
                    bg = "#233044" if not is_f else "#3d526b"
                    fg = "#93c5fd"
                else:
                    bg = "#2f2740" if not is_f else "#4a3d63"
                    fg = "#d8b4fe"
            btn.config(bg=bg, fg=fg, relief="sunken" if is_f else "flat", bd=5 if is_f else 0, highlightthickness=3 if is_f else 0, highlightbackground=focus_outline, highlightcolor=focus_outline)

    def _draw_transport_pan_knob(self, c: tk.Canvas, pan: float, *, focused: bool, bg: str, focus_outline: str) -> None:
        c.configure(bg=bg, highlightthickness=3 if focused else 0, highlightbackground=focus_outline, highlightcolor=focus_outline)
        c.delete("all")
        w = max(48, int(c.winfo_width() or 74))
        h = max(42, int(c.winfo_height() or 54))
        cx, cy = w / 2.0, h / 2.0 - 1.0
        r = min(w, h) * 0.33
        pan = float(np.clip(pan, -1.0, 1.0))
        c.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4, outline="#29415a", width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#101923", outline="#3d526b", width=2)
        c.create_oval(cx - r * 0.58, cy - r * 0.58, cx + r * 0.58, cy + r * 0.58, fill="#0b121a", outline="#25384d", width=1)
        angle = math.radians(-90.0 + pan * 135.0)
        c.create_line(cx, cy, cx + math.cos(angle) * (r - 3), cy + math.sin(angle) * (r - 3), fill="#7cd7ff", width=3, capstyle="round")
        c.create_text(cx, cy + 1, text="PAN", fill="#d6e1ec", font=("Segoe UI", 7, "bold"))

    # --- Geometry & Drawing Support ---
    def _focus_geometry(self, w: int, h: int) -> Tuple[float, float, float, float, float, float]:
        cx, cy = w / 2, h / 2
        outer_rx = min(w, h) * 0.49
        outer_ry = outer_rx
        inner_rx = outer_rx * 0.18
        inner_ry = inner_rx
        return cx, cy, outer_rx, outer_ry, inner_rx, inner_ry

    def _freq_to_slider(self, hz: float) -> float:
        return (math.log10(hz) - math.log10(POL_LOW_HZ)) / (math.log10(POL_HIGH_HZ) - math.log10(POL_LOW_HZ))

    def _draw_focus_ring_grid(self, c: tk.Canvas, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        c.create_oval(cx - orx, cy - ory, cx + orx, cy + ory, outline="#3d526b", width=1)
        c.create_oval(cx - irx, cy - iry, cx + irx, cy + iry, outline="#3d526b", width=1)
        for hz in [100, 1000, 10000]:
            p = self._freq_to_slider(hz)
            rx, ry = orx - (orx - irx) * p, ory - (ory - iry) * p
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline="#2f3f52", width=1, dash=(2, 2))

    def _level_db_to_radius(self, db: float, orx: float, ory: float, irx: float, iry: float) -> tuple[float, float]:
        lo, hi = float(POL_LEVEL_DB_AXIS_OUTER), float(POL_LEVEL_DB_AXIS_INNER)
        t = float(np.clip((float(db) - lo) / max(1e-9, hi - lo), 0.0, 1.0))
        rx = orx - (orx - irx) * t
        ry = ory - (ory - iry) * t
        return rx, ry

    def _draw_level_db_guides(self, c: tk.Canvas, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float, *, focus: str = "") -> None:
        guides = [12, 8, 4, 0, -12, -24, -36, -48]
        for db in guides:
            rx, ry = self._level_db_to_radius(db, orx, ory, irx, iry)
            hot = db >= 0
            zero = db == 0
            color = "#60758b" if zero else ("#4b6379" if hot else "#2f3f52")
            width = 2 if zero else 1
            kwargs = {"outline": color, "width": width}
            if not zero:
                kwargs["dash"] = (3, 4)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, **kwargs)
            if focus == "gate":
                label = f"+{db}" if db > 0 else str(db)
                c.create_text(cx + rx + 18, cy, text=label, fill=color, font=("Consolas", 8, "bold"))

    def _draw_focus_signal(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        rings = getattr(ch, "band_levels", None)
        if rings is None: return
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        for i in range(POL_BANDS):
            val = float(np.clip(rings[i], 0.0, 1.0))
            if val < 0.005: continue
            p = i / (POL_BANDS - 1)
            # Breathing pulse effect
            rx_mod = 1.0 + (pulse * 0.08 * val)
            rx, ry = (orx - (orx - irx) * p) * rx_mod, (ory - (ory - iry) * p) * rx_mod
            hue = freq_rainbow_hue_hz(POL_BAND_CENTER_HZ[i])
            color = hsv_to_hex(hue, 0.7, 0.4 + val * 0.5 + pulse * 0.2)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=1 + val * 5 + pulse * 3)

    def _draw_focus_generator(self, c: tk.Canvas, mode: str, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        titles = {
            "osc": ("OSC", "#fbbf24"),
            "pink": ("PINK NOISE", "#f472c0"),
            "white": ("WHITE NOISE", "#7dd3fc"),
            "pink_pulse": ("PINK PULSE", "#fbcfe8"),
            "white_hot": ("WHITE HOT", "#38bdf8"),
        }
        title, color = titles.get(mode, (mode.upper(), "#d6e1ec"))
        if mode == "osc":
            title = f"OSC {float(np.clip(getattr(self.engine, 'osc_hz', 440.0), POL_LOW_HZ, POL_HIGH_HZ)):,.1f} Hz"
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        c.create_text(cx, 30, text=title, fill=color, font=("Segoe UI", 10, "bold"))

    def _draw_focus(self) -> None:
        c = self.focus_canvas; c.delete("all")
        w, h = max(c.winfo_width(), 380), max(c.winfo_height(), 250)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        ch = self._current_channel()
        sk = getattr(self, "selected_stage_key", "pre")
        
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)

        gen_mode = getattr(self.engine, "generator_mode", "none")
        if gen_mode != "none":
            self._draw_focus_generator(c, gen_mode, cx, cy, orx, ory, irx, iry)
            return
        
        # Consistent Anchor: Always show Master Signal in the backbone for tone stages
        anchor_ch = ch if sk == "pre" else self.engine.master_channel
        self._draw_focus_signal(c, anchor_ch, cx, cy, orx, ory, irx, iry)
        
        if sk == "pre":
            self._draw_focus_pre_shells(c, ch, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text="MIC PRE", fill="#77f0c6", font=("Segoe UI", 10, "bold"))
        elif sk == "eq":
            self._draw_focus_eq_shells(c, ch, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text="EQ", fill="#75baff", font=("Segoe UI", 10, "bold"))
        elif sk == "harm":
            self._draw_focus_harm_shells(c, ch, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text="HARMONICS", fill="#ffb757", font=("Segoe UI", 10, "bold"))
        elif sk == "gate":
            self._draw_focus_gate_shells(c, ch, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text="GATE", fill="#7c59ff", font=("Segoe UI", 10, "bold"))
        elif sk == "comp":
            self._draw_focus_comp_shells(c, ch, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text="COMP", fill="#ff6a53", font=("Segoe UI", 10, "bold"))
        elif sk in ("trn", "xct", "tbe"):
            self._draw_focus_tone_shells(c, ch, sk, cx, cy, orx, ory, irx, iry)
            c.create_text(cx, 30, text=sk.upper(), fill=self.STAGE_COLOR.get(sk, "#fff"), font=("Segoe UI", 10, "bold"))
        else:
            c.create_text(cx, 30, text=sk.upper(), fill=self.STAGE_COLOR.get(sk, "#fff"), font=("Segoe UI", 10, "bold"))

    def _draw_focus_pre_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        if not ch.pre_enabled: return
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        red = "#ff2d24"

        def radius_at(pos: float) -> tuple[float, float]:
            p = float(np.clip(pos, 0.0, 1.0))
            return orx - (orx - irx) * p, ory - (ory - iry) * p

        def draw_blocked_band(p0: float, p1: float, label: str) -> None:
            start = float(np.clip(min(p0, p1), 0.0, 1.0))
            end = float(np.clip(max(p0, p1), 0.0, 1.0))
            exact_start, exact_end = start, end
            if end - start < 0.08:
                if exact_end >= 0.995:
                    start = max(0.0, exact_end - 0.08)
                else:
                    end = min(1.0, exact_start + 0.08)
            span = end - start
            count = max(7, int(12 + span * 36))
            for idx in range(count):
                p = start + (end - start) * (idx / max(1, count - 1))
                rx, ry = radius_at(p)
                width = max(3, int(3 + span * 15 + pulse * 3))
                c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=red, width=width)
            mid = (start + end) * 0.5
            rx, ry = radius_at(mid)
            c.create_text(cx, cy - ry, text=label, fill=red, font=("Segoe UI", 8, "bold"))
            rx0, ry0 = radius_at(exact_start)
            rx1, ry1 = radius_at(exact_end)
            c.create_oval(cx - rx0, cy - ry0, cx + rx0, cy + ry0, outline="#ff8a80", width=5)
            c.create_oval(cx - rx1, cy - ry1, cx + rx1, cy + ry1, outline="#ff8a80", width=5)

        # Frequency map: outer ring is low end (20 Hz), inner ring is high end (20 kHz).
        # HPF blocks lows: red region grows from the outside inward as cutoff rises.
        if ch.hpf_enabled:
            h_pos = self._freq_to_slider(ch.hpf_hz)
            draw_blocked_band(0.0, h_pos, f"HPF {ch.hpf_hz:.0f}Hz")
            
        # LPF blocks highs: red region grows from the inside outward as cutoff lowers.
        if ch.lpf_enabled:
            l_pos = self._freq_to_slider(ch.lpf_hz)
            draw_blocked_band(l_pos, 1.0, f"LPF {ch.lpf_hz:.0f}Hz")
            rx, ry = radius_at(l_pos)
            c.create_text(cx, cy + ry + 18, text="LPF BLOCKS HIGHS", fill=red, font=("Segoe UI", 8, "bold"))

        gain_db = float(getattr(ch, "pre_gain_db", 0.0))
        squeeze = float(getattr(ch, "pre_squeeze", 1.0))
        squeeze_width = max(1.0, min(12.0, 1.5 + abs(gain_db) * 0.22 + (squeeze - 1.0) * 1.8))
        squeeze_rx = orx * max(0.22, 0.92 - (squeeze - 1.0) * 0.055)
        squeeze_ry = ory * max(0.22, 0.92 - (squeeze - 1.0) * 0.055)
        c.create_oval(cx - squeeze_rx, cy - squeeze_ry, cx + squeeze_rx, cy + squeeze_ry, outline="#77f0c6", width=squeeze_width)
        c.create_text(cx, cy + squeeze_ry + 16, text=f"PRE {gain_db:+.1f} dB  SQZ {squeeze:.1f}:1", fill="#77f0c6", font=("Consolas", 10, "bold"))

        # Tube (TBE). Warm orange ring in the center.
        if ch.tube:
            rx, ry = irx + (orx - irx) * 0.05, iry + (ory - iry) * 0.05
            color = hsv_to_hex(30/360.0, 0.7, 0.6 + pulse * 0.3)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=3 + pulse * 4)

    def _stage_param_bypassed(self, ch: ChannelState, stage_key: str) -> bool:
        bp_key = {
            "gate": "gate_param_bypass",
            "comp": "comp_param_bypass",
            "harm": "harm_param_bypass",
        }.get(stage_key)
        if not bp_key:
            return False
        return any(bool(v) and k not in ("FRQ", "TBE") for k, v in getattr(ch, bp_key, {}).items())

    def _draw_focus_gate_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        if not (ch.gate_enabled or ch.gate_band_enabled): return
        if self._stage_param_bypassed(ch, "gate"): return
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        self._draw_level_db_guides(c, cx, cy, orx, ory, irx, iry, focus="gate")
        levels = np.asarray(getattr(ch, "band_levels", np.zeros(POL_BANDS)), dtype=np.float32)
        if levels.size < POL_BANDS:
            levels = np.resize(levels, POL_BANDS).astype(np.float32)
        if ch.gate_band_enabled:
            f_pos_est = self._freq_to_slider(ch.gate_center_hz)
            width_bins = max(1, int(round(float(np.clip(ch.gate_width_oct, 0.1, 6.0)) * 2.0)))
            center_idx = int(np.clip(round(f_pos_est * (POL_BANDS - 1)), 0, POL_BANDS - 1))
            lo_i = max(0, center_idx - width_bins)
            hi_i = min(POL_BANDS, center_idx + width_bins + 1)
            detector_norm = float(np.max(levels[lo_i:hi_i])) if hi_i > lo_i else float(np.max(levels))
        else:
            detector_norm = float(np.max(levels)) if levels.size else 0.0
        env = float(getattr(ch, "gate_env", 0.0))
        if env > 1e-7:
            env_db = 20.0 * math.log10(max(env, 1e-7))
        else:
            env_db = -168.0
        level_db_from_display = float(POL_LEVEL_DB_AXIS_OUTER + np.clip(detector_norm, 0.0, 1.0) * (POL_LEVEL_DB_AXIS_INNER - POL_LEVEL_DB_AXIS_OUTER))
        detector_db = max(env_db, level_db_from_display)
        threshold_db = float(getattr(ch, "gate_threshold_db", -45.0))
        depth = float(np.clip(getattr(ch, "gate_ratio", 1.0), 1.0, 20.0))
        depth_db = depth * 4.0
        floor_db = float(np.clip(threshold_db - depth_db, POL_LEVEL_DB_AXIS_OUTER, threshold_db))
        estimated_gr_db = 0.0
        if threshold_db > detector_db:
            close_amt = float(np.clip((threshold_db - detector_db) / 24.0, 0.0, 1.0))
            estimated_gr_db = depth_db * close_amt
        gr_db = float(np.clip(max(getattr(ch, "gate_gr_db", 0.0), estimated_gr_db), 0.0, 80.0))
        depth_t = float(np.clip(depth / 20.0, 0.0, 1.0))
        closed = float(np.clip(gr_db / 48.0, 0.0, 1.0))
        status = "OPEN" if gr_db < 1.0 else "CLOSING" if gr_db < 12.0 else "CLOSED"
        status_color = "#77f0c6" if gr_db < 1.0 else "#ffd166" if gr_db < 12.0 else "#ff6a53"
        thr_rx, thr_ry = self._level_db_to_radius(threshold_db, orx, ory, irx, iry)
        floor_rx, floor_ry = self._level_db_to_radius(floor_db, orx, ory, irx, iry)
        attack_ms = float(np.clip(getattr(ch, "gate_attack_ms", 3.0), 0.1, 500.0))
        release_ms = float(np.clip(getattr(ch, "gate_release_ms", 140.0), 10.0, 2000.0))
        attack_t = float(np.clip(math.log10(attack_ms / 0.1) / math.log10(5000.0), 0.0, 1.0))
        edge_color = hsv_to_hex((attack_t * 42.0) / 360.0, 0.96, 1.0)

        band_active = bool(getattr(ch, "gate_band_enabled", False))
        if closed > 0.02 and not band_active:
            red_flash = 0.65 + 0.35 * math.sin(time.time() * 9.0)
            band_steps = max(5, int(8 + depth_t * 12))
            for i in range(band_steps):
                t = i / max(1, band_steps - 1)
                rx = floor_rx + (thr_rx - floor_rx) * t
                ry = floor_ry + (thr_ry - floor_ry) * t
                value = float(np.clip(0.18 + depth_t * 0.46 + closed * 0.24 + red_flash * 0.12, 0.0, 1.0))
                c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=hsv_to_hex(0.0, 0.92, value), width=1 + int(depth_t * 3))

        if not band_active:
            c.create_oval(cx - floor_rx, cy - floor_ry, cx + floor_rx, cy + floor_ry, outline="#8f1d24", width=2, dash=(5, 5))
            c.create_text(cx + floor_rx + 24, cy, text="DEP", fill="#b64248", font=("Consolas", 9, "bold"))
            c.create_oval(cx - thr_rx, cy - thr_ry, cx + thr_rx, cy + thr_ry, outline=edge_color, width=4)
            c.create_text(cx - thr_rx - 24, cy, text="THR", fill=edge_color, font=("Consolas", 9, "bold"))

        if band_active:
            width_oct = float(np.clip(getattr(ch, "gate_width_oct", 4.0), 0.1, 6.0))
            red_flash = 0.65 + 0.35 * math.sin(time.time() * 9.0)
            geom = self._frequency_width_geometry(ch.gate_center_hz, width_oct, orx, ory, irx, iry)
            fill_strength = depth_t * 0.18 + closed * 0.18 + red_flash * 0.06
            self._draw_frequency_width_shell(
                c,
                cx,
                cy,
                geom,
                center_hz=ch.gate_center_hz,
                width_oct=width_oct,
                color="#7d2528",
                fill_strength=fill_strength,
                line_width=1 + int(depth_t * 2),
            )
            c.create_text(cx, cy + geom["ry"] + 16, text=f"KEY {ch.gate_center_hz:.0f} Hz  WDT {width_oct:.1f}", fill="#ddc270", font=("Consolas", 9, "bold"))

        c.create_text(
            cx,
            cy + ory + 20,
            text=f"{status}  IN {detector_db:.1f} dB  THR {threshold_db:.1f} dB  FLOOR {floor_db:.1f} dB  DEP {depth_db:.0f} dB  ATK {attack_ms:.1f}  RLS {release_ms:.0f}",
            fill=status_color,
            font=("Consolas", 10, "bold"),
        )

    def _frequency_width_geometry(self, center_hz: float, width_oct: float, orx: float, ory: float, irx: float, iry: float) -> dict:
        center_hz = float(np.clip(center_hz, POL_LOW_HZ, POL_HIGH_HZ))
        width_oct = float(np.clip(width_oct, 0.1, 6.0))
        lo_hz = max(POL_LOW_HZ, center_hz / (2.0 ** (width_oct / 2.0)))
        hi_hz = min(POL_HIGH_HZ, center_hz * (2.0 ** (width_oct / 2.0)))
        f_pos = self._freq_to_slider(center_hz)
        p_lo = self._freq_to_slider(lo_hz)
        p_hi = self._freq_to_slider(hi_hz)
        return {
            "width_oct": width_oct,
            "rx": orx - (orx - irx) * f_pos,
            "ry": ory - (ory - iry) * f_pos,
            "outer_rx": orx - (orx - irx) * min(p_lo, p_hi),
            "outer_ry": ory - (ory - iry) * min(p_lo, p_hi),
            "inner_rx": orx - (orx - irx) * max(p_lo, p_hi),
            "inner_ry": ory - (ory - iry) * max(p_lo, p_hi),
        }

    def _draw_frequency_width_shell(self, c: tk.Canvas, cx: float, cy: float, geom: dict, *, center_hz: float, width_oct: float, color: str, fill_strength: float, line_width: int = 1) -> None:
        steps = max(3, int(3 + float(np.clip(width_oct, 0.1, 6.0)) * 1.4))
        for i in range(steps):
            t = i / max(1, steps - 1)
            wrx = geom["inner_rx"] + (geom["outer_rx"] - geom["inner_rx"]) * t
            wry = geom["inner_ry"] + (geom["outer_ry"] - geom["inner_ry"]) * t
            c.create_oval(cx - wrx, cy - wry, cx + wrx, cy + wry, outline=color, width=line_width)
        c.create_oval(cx - geom["outer_rx"], cy - geom["outer_ry"], cx + geom["outer_rx"], cy + geom["outer_ry"], outline=color, width=2)
        c.create_oval(cx - geom["inner_rx"], cy - geom["inner_ry"], cx + geom["inner_rx"], cy + geom["inner_ry"], outline=color, width=2)
        hue = freq_rainbow_hue_hz(center_hz)
        center_value = float(np.clip(0.58 + fill_strength, 0.0, 1.0))
        c.create_oval(cx - geom["rx"], cy - geom["ry"], cx + geom["rx"], cy + geom["ry"], outline=hsv_to_hex(0.0, 0.96, center_value), width=max(4, line_width + 4))
        c.create_oval(cx - geom["rx"], cy - geom["ry"], cx + geom["rx"], cy + geom["ry"], outline=hsv_to_hex(hue, 0.45, 0.42), width=1)

    def _draw_focus_comp_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        if not (ch.comp_enabled or ch.comp_band_enabled): return
        if self._stage_param_bypassed(ch, "comp"): return
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        self._draw_level_db_guides(c, cx, cy, orx, ory, irx, iry, focus="comp")
        levels = np.asarray(getattr(ch, "band_levels", np.zeros(POL_BANDS)), dtype=np.float32)
        if levels.size < POL_BANDS:
            levels = np.resize(levels, POL_BANDS).astype(np.float32)
        band_active = bool(getattr(ch, "comp_band_enabled", False))
        if band_active:
            f_pos_est = self._freq_to_slider(ch.comp_center_hz)
            width_bins = max(1, int(round(float(np.clip(ch.comp_width_oct, 0.1, 6.0)) * 2.0)))
            center_idx = int(np.clip(round(f_pos_est * (POL_BANDS - 1)), 0, POL_BANDS - 1))
            lo_i = max(0, center_idx - width_bins)
            hi_i = min(POL_BANDS, center_idx + width_bins + 1)
            detector_norm = float(np.max(levels[lo_i:hi_i])) if hi_i > lo_i else float(np.max(levels))
        else:
            detector_norm = float(np.max(levels)) if levels.size else 0.0

        env = float(getattr(ch, "comp_env", 0.0))
        env_db = 20.0 * math.log10(max(env, 1e-7)) if env > 1e-7 else -168.0
        level_db_from_display = float(POL_LEVEL_DB_AXIS_OUTER + np.clip(detector_norm, 0.0, 1.0) * (POL_LEVEL_DB_AXIS_INNER - POL_LEVEL_DB_AXIS_OUTER))
        detector_db = max(env_db, level_db_from_display)
        threshold_db = float(getattr(ch, "comp_threshold_db", -18.0))
        ratio = float(np.clip(getattr(ch, "comp_ratio", 4.0), 1.0, 20.0))
        limiter = ratio >= 19.95
        over_db = max(0.0, detector_db - threshold_db)
        estimated_gr_db = over_db if limiter else over_db - (over_db / max(1.0, ratio) if over_db > 0.0 else 0.0)
        gr_db = float(np.clip(max(getattr(ch, "comp_gr_db", 0.0), estimated_gr_db), 0.0, 48.0))
        thr_rx, thr_ry = self._level_db_to_radius(threshold_db, orx, ory, irx, iry)
        clamp_db = threshold_db + (over_db / max(1.0, ratio) if over_db > 0.0 and not limiter else 0.0)
        clamp_rx, clamp_ry = self._level_db_to_radius(clamp_db, orx, ory, irx, iry)
        ratio_t = float(np.clip((ratio - 1.0) / 19.0, 0.0, 1.0))
        thickness_db = 2.0 + ratio_t * 30.0
        thick_inner_db = float(np.clip(threshold_db + thickness_db * 0.45, threshold_db, POL_LEVEL_DB_AXIS_INNER))
        thick_outer_db = float(np.clip(threshold_db - thickness_db * 0.55, POL_LEVEL_DB_AXIS_OUTER, threshold_db))
        thick_inner_rx, thick_inner_ry = self._level_db_to_radius(thick_inner_db, orx, ory, irx, iry)
        thick_outer_rx, thick_outer_ry = self._level_db_to_radius(thick_outer_db, orx, ory, irx, iry)
        edge_color = "#ff2d24" if limiter else "#ff6a53"
        fill_color = "#ff2d24" if limiter else "#ff8f3a"
        status = "LIMIT" if limiter and gr_db > 0.5 else "READY" if gr_db < 0.5 else "COMP"

        if not band_active:
            c.create_oval(cx - thr_rx, cy - thr_ry, cx + thr_rx, cy + thr_ry, outline=edge_color, width=4)
            c.create_text(cx - thr_rx - 24, cy, text="THR", fill=edge_color, font=("Consolas", 9, "bold"))
            if limiter:
                steps = max(14, int(18 + min(gr_db / 24.0, 1.0) * 12))
                for i in range(steps):
                    t = i / max(1, steps - 1)
                    rx = irx + (thr_rx - irx) * t
                    ry = iry + (thr_ry - iry) * t
                    value = float(np.clip(0.42 + min(gr_db / 24.0, 1.0) * 0.34 + pulse * 0.08, 0.0, 1.0))
                    c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=hsv_to_hex(0.0, 0.96, value), width=2 + int(min(gr_db / 12.0, 1.0) * 2))
                c.create_oval(cx - irx, cy - iry, cx + irx, cy + iry, outline="#ff2d24", width=5)
                c.create_text(cx + thr_rx + 28, cy, text="LIM", fill="#ff2d24", font=("Consolas", 9, "bold"))
                c.create_text(cx, cy - iry - 16, text="RED TO 20K", fill="#ff2d24", font=("Consolas", 9, "bold"))
            else:
                c.create_oval(cx - thick_outer_rx, cy - thick_outer_ry, cx + thick_outer_rx, cy + thick_outer_ry, outline="#7a332b", width=2)
                c.create_oval(cx - thick_inner_rx, cy - thick_inner_ry, cx + thick_inner_rx, cy + thick_inner_ry, outline="#ffb199", width=2)
                c.create_text(cx + thick_outer_rx + 28, cy, text="RAT", fill="#ffb199", font=("Consolas", 9, "bold"))
                steps = max(3, int(3 + ratio_t * 16))
                active_value = 0.10 + min(gr_db / 24.0, 1.0) * 0.22
                for i in range(steps):
                    t = i / max(1, steps - 1)
                    rx = thick_inner_rx + (thick_outer_rx - thick_inner_rx) * t
                    ry = thick_inner_ry + (thick_outer_ry - thick_inner_ry) * t
                    value = float(np.clip(0.22 + ratio_t * 0.42 + active_value + pulse * 0.06, 0.0, 1.0))
                    c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=hsv_to_hex(12.0 / 360.0, 0.90, value), width=1 + int(ratio_t * 3))
        else:
            width_oct = float(np.clip(getattr(ch, "comp_width_oct", 4.0), 0.1, 6.0))
            geom = self._frequency_width_geometry(ch.comp_center_hz, width_oct, orx, ory, irx, iry)
            self._draw_frequency_width_shell(
                c,
                cx,
                cy,
                geom,
                center_hz=ch.comp_center_hz,
                width_oct=width_oct,
                color="#7d2528",
                fill_strength=ratio_t * 0.12 + min(gr_db / 24.0, 1.0) * 0.12,
                line_width=1,
            )
            if limiter:
                steps = max(10, int(12 + min(gr_db / 24.0, 1.0) * 10))
                for i in range(steps):
                    t = i / max(1, steps - 1)
                    wrx = irx + (geom["rx"] - irx) * t
                    wry = iry + (geom["ry"] - iry) * t
                    value = float(np.clip(0.38 + min(gr_db / 24.0, 1.0) * 0.34 + pulse * 0.08, 0.0, 1.0))
                    c.create_oval(cx - wrx, cy - wry, cx + wrx, cy + wry, outline=hsv_to_hex(0.0, 0.96, value), width=2)
            else:
                steps = max(3, int(3 + ratio_t * 12))
                center_bias = 0.50
                ratio_span = float(np.clip(0.12 + ratio_t * 0.88, 0.0, 1.0))
                for i in range(steps):
                    t = i / max(1, steps - 1)
                    t2 = center_bias + (t - 0.5) * ratio_span
                    wrx = geom["inner_rx"] + (geom["outer_rx"] - geom["inner_rx"]) * t2
                    wry = geom["inner_ry"] + (geom["outer_ry"] - geom["inner_ry"]) * t2
                    value = float(np.clip(0.20 + ratio_t * 0.50 + min(gr_db / 24.0, 1.0) * 0.22 + pulse * 0.08, 0.0, 1.0))
                    c.create_oval(cx - wrx, cy - wry, cx + wrx, cy + wry, outline=hsv_to_hex(12.0 / 360.0, 0.94, value), width=1 + int(ratio_t * 3))
            c.create_oval(cx - geom["rx"], cy - geom["ry"], cx + geom["rx"], cy + geom["ry"], outline="#ff2d24" if limiter else "#ff6a53", width=5 + int(ratio_t * 4))
            c.create_text(cx, cy + geom["ry"] + 16, text=f"KEY {ch.comp_center_hz:.0f} Hz  WDT {width_oct:.1f}{'  LIM TO 20K' if limiter else ''}", fill="#ff8f3a", font=("Consolas", 9, "bold"))

        c.create_text(
            cx,
            cy + ory + 20,
            text=f"{status}  IN {detector_db:.1f} dB  THR {threshold_db:.1f} dB  RAT {'LIM' if limiter else f'{ratio:.1f}:1'}  GR {gr_db:.1f} dB  ATK {ch.comp_attack_ms:.1f}  RLS {ch.comp_release_ms:.0f}",
            fill=fill_color,
            font=("Consolas", 10, "bold"),
        )


    def _draw_focus_harm_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        if not ch.harmonics_enabled:
            return
        if self._stage_param_bypassed(ch, "harm"):
            return

        col = max(0, min(len(self._STAGE_GRID) - 1, getattr(self, "editor_stage_col", 0)))
        sk, _, params = self._STAGE_GRID[col]
        row = max(0, min(len(params) - 1, getattr(self, "editor_param_row", 0)))
        label = params[row] if sk == "harm" and not getattr(self, "editor_unified_header_focus", True) else ""

        if label.startswith("H"):
            try:
                idx = int(label[1:]) - 1
            except Exception:
                idx = -1
            if 0 <= idx < 5:
                multiplier = idx + 2
                levels = np.asarray(getattr(ch, "band_levels", np.zeros(POL_BANDS)), dtype=np.float32)
                if levels.size >= POL_BANDS and float(np.max(levels)) > 0.01:
                    fundamental_idx = int(np.argmax(levels[: max(1, POL_BANDS - idx - 4)]))
                    fundamental_hz = float(POL_BAND_CENTER_HZ[fundamental_idx])
                    target_hz = float(np.clip(fundamental_hz * multiplier, POL_LOW_HZ, POL_HIGH_HZ))
                    f_pos = self._freq_to_slider(target_hz)
                    rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
                    amount = float(np.clip(ch.harmonics[idx], 0.0, 1.0))
                    color = hsv_to_hex(freq_rainbow_hue_hz(target_hz), 0.85, 0.58 + amount * 0.36 + pulse * 0.06)
                    c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 + amount * 4, dash=(8, 5))
                    c.create_text(cx, cy - ry - 16, text=f"{label} {multiplier}x target {target_hz:,.0f} Hz", fill=color, font=("Segoe UI", 8, "bold"))
                else:
                    c.create_text(cx, cy + iry + 26, text=f"{label} {multiplier}x ready - waiting for signal", fill="#ffb757", font=("Segoe UI", 8, "bold"))
        elif label == "TBE" and getattr(ch, "harm_tube", False):
            c.create_text(cx, cy + iry + 26, text="HRM TBE SATURATION", fill="#ffb757", font=("Segoe UI", 8, "bold"))

    def _draw_focus_eq_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        if not ch.eq_enabled: return
        if any(getattr(ch, "eq_param_bypass", {}).get(k, False) for k in ("FRQ", "GAN", "SHP")):
            return
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        freq = float(np.clip(getattr(ch, "eq_freq", 2200.0), POL_LOW_HZ, POL_HIGH_HZ))
        shape = float(np.clip(getattr(ch, "eq_width", 1.4), 0.0, 6.0))
        gain_db = float(np.clip(getattr(ch, "eq_gain_db", 0.0), -24.0, 24.0))
        gain_abs = abs(gain_db) / 24.0
        color = "#ff8c1a" if ch.eq_gain_db < 0 else "#75baff"
        if shape <= 0.1:
            f_pos = self._freq_to_slider(freq)
            rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=max(3, 3 + gain_abs * 6 + pulse * 2))
            shelf_label = "LOW SHELF" if freq < 1000.0 else "HIGH SHELF"
            c.create_text(cx, cy + ry + 16, text=f"{shelf_label} {freq:.0f} Hz  {gain_db:+.1f} dB", fill=color, font=("Consolas", 9, "bold"))
            return

        geom = self._frequency_width_geometry(freq, shape, orx, ory, irx, iry)
        steps = max(3, int(3 + shape * 1.6))
        for i in range(steps):
            t = i / max(1, steps - 1)
            wrx = geom["inner_rx"] + (geom["outer_rx"] - geom["inner_rx"]) * t
            wry = geom["inner_ry"] + (geom["outer_ry"] - geom["inner_ry"]) * t
            value = float(np.clip(0.24 + gain_abs * 0.45 + pulse * 0.07, 0.0, 1.0))
            c.create_oval(cx - wrx, cy - wry, cx + wrx, cy + wry, outline=hsv_to_hex(freq_rainbow_hue_hz(freq), 0.68, value), width=1 + int(gain_abs * 3))
        c.create_oval(cx - geom["outer_rx"], cy - geom["outer_ry"], cx + geom["outer_rx"], cy + geom["outer_ry"], outline=color, width=2)
        c.create_oval(cx - geom["inner_rx"], cy - geom["inner_ry"], cx + geom["inner_rx"], cy + geom["inner_ry"], outline=color, width=2)
        c.create_oval(cx - geom["rx"], cy - geom["ry"], cx + geom["rx"], cy + geom["ry"], outline=color, width=max(4, 4 + gain_abs * 5 + pulse * 2))
        c.create_text(cx, cy + geom["ry"] + 16, text=f"EQ {freq:.0f} Hz  {gain_db:+.1f} dB  SHP {shape:.1f}", fill=color, font=("Consolas", 9, "bold"))

    def _draw_focus_tone_shells(self, c: tk.Canvas, ch: ChannelState, mode: str, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        pre = mode + "_"
        enabled = getattr(ch, pre + "enabled", False)
        if not enabled: return
        if mode == "trn" and any(getattr(ch, "trn_param_bypass", {}).get(k, False) for k in ("FRQ", "ATK", "SUT", "DRV")):
            return
        if mode == "xct" and any(getattr(ch, "xct_param_bypass", {}).get(k, False) for k in ("FRQ", "ATK", "SUT", "DRV")):
            return

        hz = getattr(ch, pre + "freq", getattr(ch, pre + "center_hz", 1000.0))
        width_oct = float(np.clip(getattr(ch, pre + "width", 1.2), 0.1, 6.0))
        color = self.STAGE_COLOR.get(mode, "#fff")
        banded = bool(getattr(ch, pre + "band_enabled", False))

        if mode == "trn":
            atk = float(np.clip(getattr(ch, "trn_attack", 0.0), -1.0, 1.0))
            sut = float(np.clip(getattr(ch, "trn_sustain", 0.0), -1.0, 1.0))
            drv = float(np.clip(getattr(ch, "trn_drive", 0.0), 0.0, 1.0))
            active_width = width_oct if banded else 1.0
            geom = self._frequency_width_geometry(hz, active_width, orx, ory, irx, iry)
            levels = np.asarray(getattr(ch, "band_levels", np.zeros(POL_BANDS)), dtype=np.float32)
            f_pos_est = self._freq_to_slider(hz)
            center_idx = int(np.clip(round(f_pos_est * (POL_BANDS - 1)), 0, POL_BANDS - 1))
            width_bins = max(1, int(round(active_width * 2.0)))
            lo_i = max(0, center_idx - width_bins)
            hi_i = min(POL_BANDS, center_idx + width_bins + 1)
            band_energy = float(np.max(levels[lo_i:hi_i])) if levels.size >= POL_BANDS and hi_i > lo_i else 0.0
            energy_v = float(np.clip(band_energy, 0.0, 1.0))
            if banded:
                self._draw_frequency_width_shell(
                    c,
                    cx,
                    cy,
                    geom,
                    center_hz=hz,
                    width_oct=width_oct,
                    color=color,
                    fill_strength=energy_v * 0.35 + drv * 0.12 + pulse * 0.03,
                    line_width=1 + int(drv * 3),
                )
            else:
                c.create_oval(cx - geom["rx"], cy - geom["ry"], cx + geom["rx"], cy + geom["ry"], outline=color, width=2 + energy_v * 5 + drv * 2 + pulse * 1.5)

            attack_color = "#77f0c6" if atk >= 0.0 else "#ff8c1a"
            sustain_color = "#75baff" if sut >= 0.0 else "#ff6a53"
            atk_rx = geom["rx"] + 10.0 + abs(atk) * 40.0
            atk_ry = geom["ry"] + 10.0 + abs(atk) * 30.0
            sut_rx = max(irx, geom["rx"] - 8.0 - abs(sut) * 36.0)
            sut_ry = max(iry, geom["ry"] - 8.0 - abs(sut) * 28.0)
            c.create_oval(cx - atk_rx, cy - atk_ry, cx + atk_rx, cy + atk_ry, outline=attack_color, width=max(1, int(2 + abs(atk) * 5 + energy_v * 2)))
            c.create_text(cx, cy - atk_ry - 12, text="ATK", fill=attack_color, font=("Consolas", 8, "bold"))
            c.create_oval(cx - sut_rx, cy - sut_ry, cx + sut_rx, cy + sut_ry, outline=sustain_color, width=max(1, int(2 + abs(sut) * 5 + energy_v * 2)))
            c.create_text(cx, cy + sut_ry + 12, text="SUT", fill=sustain_color, font=("Consolas", 8, "bold"))
            c.create_text(cx, cy + geom["ry"] + 28, text=f"TRN {hz:.0f} Hz  WDT {active_width:.1f}  LVL {energy_v:.2f}  ATK {atk:+.2f}  SUT {sut:+.2f}  DRV {drv:.2f}", fill=color, font=("Consolas", 9, "bold"))
            return

        if mode == "xct":
            atk = float(np.clip(getattr(ch, "xct_attack", 0.0), -1.0, 1.0))
            sut = float(np.clip(getattr(ch, "xct_sustain", 0.0), -1.0, 1.0))
            drv = float(np.clip(getattr(ch, "xct_drive", 0.0), 0.0, 1.0))
            active_width = width_oct if banded else 1.0
            geom = self._frequency_width_geometry(hz, active_width, orx, ory, irx, iry)
            levels = np.asarray(getattr(ch, "band_levels", np.zeros(POL_BANDS)), dtype=np.float32)
            f_pos_est = self._freq_to_slider(hz)
            center_idx = int(np.clip(round(f_pos_est * (POL_BANDS - 1)), 0, POL_BANDS - 1))
            width_bins = max(1, int(round(active_width * 2.0)))
            lo_i = max(0, center_idx - width_bins)
            hi_i = min(POL_BANDS, center_idx + width_bins + 1)
            energy_v = float(np.clip(float(np.max(levels[lo_i:hi_i])) if levels.size >= POL_BANDS and hi_i > lo_i else 0.0, 0.0, 1.0))
            hue = freq_rainbow_hue_hz(hz)
            self._draw_frequency_width_shell(
                c,
                cx,
                cy,
                geom,
                center_hz=hz,
                width_oct=active_width,
                color=hsv_to_hex(hue, 0.85, 0.55 + drv * 0.35),
                fill_strength=energy_v * 0.25 + drv * 0.30 + pulse * 0.04,
                line_width=1 + int(drv * 4),
            )
            atk_rx = geom["rx"] + 8.0 + max(0.0, atk) * 34.0
            atk_ry = geom["ry"] + 8.0 + max(0.0, atk) * 24.0
            sut_rx = max(irx, geom["rx"] - 6.0 - max(0.0, sut) * 30.0)
            sut_ry = max(iry, geom["ry"] - 6.0 - max(0.0, sut) * 22.0)
            c.create_oval(cx - atk_rx, cy - atk_ry, cx + atk_rx, cy + atk_ry, outline="#f06cff", width=max(1, int(2 + abs(atk) * 4 + drv * 2)))
            c.create_text(cx, cy - atk_ry - 12, text="ATK", fill="#f06cff", font=("Consolas", 8, "bold"))
            c.create_oval(cx - sut_rx, cy - sut_ry, cx + sut_rx, cy + sut_ry, outline="#72d7ff", width=max(1, int(2 + abs(sut) * 4 + drv * 2)))
            c.create_text(cx, cy + sut_ry + 12, text="SUT", fill="#72d7ff", font=("Consolas", 8, "bold"))
            c.create_text(cx, cy + geom["ry"] + 28, text=f"XCT {hz:.0f} Hz  WDT {active_width:.1f}  LVL {energy_v:.2f}  ATK {atk:+.2f}  SUT {sut:+.2f}  DRV {drv:.2f}", fill=color, font=("Consolas", 9, "bold"))
            return

        if mode == "tbe":
            if getattr(ch, "tbe_param_bypass", {}).get("DRV", False):
                return
            drv = float(np.clip(getattr(ch, "tbe_drive", 0.0), 0.0, 1.0))
            active_width = width_oct if banded else 2.4
            geom = self._frequency_width_geometry(hz, active_width, orx, ory, irx, iry)
            warm = hsv_to_hex(30.0 / 360.0, 0.90, 0.42 + drv * 0.50 + pulse * 0.05)
            self._draw_frequency_width_shell(
                c,
                cx,
                cy,
                geom,
                center_hz=hz,
                width_oct=active_width,
                color=warm,
                fill_strength=drv * 0.40 + pulse * 0.04,
                line_width=1 + int(drv * 5),
            )
            c.create_text(cx, cy + geom["ry"] + 28, text=f"TBE {hz:.0f} Hz  DRV {drv:.2f}", fill=warm, font=("Consolas", 9, "bold"))
            return

        f_pos = self._freq_to_slider(hz)
        rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
        c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 + pulse * 3)

    # --- Editor Renders ---
    def _draw_editor_controls(self) -> None:
        self._autosize_editor_canvas_height()
        c = self.editor_canvas; c.delete("all")
        w, h = max(c.winfo_width(), 380), max(c.winfo_height(), 340)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        self._draw_unified_editor(c, w, h, self._current_channel())

    def _draw_unified_editor(self, c: tk.Canvas, w: int, h: int, ch: ChannelState) -> None:
        self.editor_hitboxes = []
        stage_grid = self._stage_grid_for_channel(ch)
        margin, gap, stages = 12, 8, len(stage_grid)
        # Row 1: Stages (Top)
        # Row 2 & 3: Parameters (Bottom)
        dial_y, dial_h = 8, 54
        top_y, hdr_h, cell_h = 70, 52, 48
        focus_col = max(0, min(len(stage_grid) - 1, getattr(self, "editor_stage_col", 0)))
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        top_focus = bool(getattr(self, "editor_top_focus", False))
        editor_focused = getattr(self, "nav_scope", "console") == "editor"
        pulse = 0.5 + 0.5 * math.sin(time.time() * 7.0)
        focus_outline = hsv_to_hex((time.time() * 0.18) % 1.0, 0.95, 1.0)

        self._draw_editor_fader_circles(c, w, dial_y, dial_h, editor_focused and top_focus, focus_outline)

        # Draw Row 1: Insert + DSP selection as matching circular buttons.
        c.create_text(margin, top_y - 10, anchor="w", text="INSERT / DSP", fill="#5ec8ff", font=("Segoe UI", 8, "bold"))
        circle_count = stages + 1
        sw = (w - margin * 2 - gap * (circle_count - 1)) / circle_count
        circle_r = max(16.0, min(24.0, sw / 2 - 3.0, hdr_h / 2 - 3.0))
        ins_x0 = margin
        ins_x1 = ins_x0 + sw
        ins_cx, ins_cy = (ins_x0 + ins_x1) / 2, top_y + hdr_h / 2
        ins_f = editor_focused and (not top_focus) and hdr_focus and getattr(self, "editor_insert_focus", False)
        if ins_f:
            c.create_oval(ins_cx - circle_r - 6, ins_cy - circle_r - 6, ins_cx + circle_r + 6, ins_cy + circle_r + 6, outline=focus_outline, width=4)
            c.create_oval(ins_cx - circle_r - 10, ins_cy - circle_r - 10, ins_cx + circle_r + 10, ins_cy + circle_r + 10, outline="#ffd400", width=2)
        c.create_oval(ins_cx - circle_r, ins_cy - circle_r, ins_cx + circle_r, ins_cy + circle_r, fill="#101923" if not ins_f else "#263648", outline="#9bd7ff" if ins_f else "#2a7ca8", width=2 if ins_f else 1)
        c.create_text(ins_cx, ins_cy - 4, text="INS", fill="#9bd7ff", font=("Segoe UI", 9, "bold"))
        c.create_text(ins_cx, ins_cy + 10, text="off", fill="#6f879a", font=("Consolas", 7, "bold"))
        self.editor_hitboxes.append((ins_cx - circle_r - 4, ins_cy - circle_r - 4, ins_cx + circle_r + 4, ins_cy + circle_r + 4, ("insert_hdr", 0)))

        for i, (sk, hdr, params) in enumerate(stage_grid):
            x0 = margin + (i + 1) * (sw + gap)
            x1 = x0 + sw
            hc = self.STAGE_COLOR.get(sk, "#9aa6b6")
            is_f = editor_focused and (not top_focus) and hdr_focus and not getattr(self, "editor_insert_focus", False) and i == focus_col
            en = self._stage_enabled(ch, sk)
            fill = hc if is_f and en else ("#263648" if is_f else ("#1d2c39" if en else "#15202c"))
            outline = "#fff" if is_f else (hc if en else "#2a3848")
            text_fill = "black" if is_f and en else (hc if en or is_f else "#6b7787")
            cx, cy = (x0 + x1) / 2, top_y + hdr_h / 2
            if is_f:
                c.create_oval(cx - circle_r - 6, cy - circle_r - 6, cx + circle_r + 6, cy + circle_r + 6, outline=focus_outline, width=4)
                c.create_oval(cx - circle_r - 10, cy - circle_r - 10, cx + circle_r + 10, cy + circle_r + 10, outline="#ffd400", width=2)
            c.create_oval(cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r, outline=outline, width=2 if is_f or en else 1, fill=fill)
            c.create_text(cx, cy - 4, text=hdr, fill=text_fill, font=("Segoe UI", 9, "bold"))
            c.create_text(cx, cy + 10, text="ON" if en else "off", fill=text_fill, font=("Consolas", 7, "bold"))
            self.editor_hitboxes.append((cx - circle_r - 4, cy - circle_r - 4, cx + circle_r + 4, cy + circle_r + 4, ("stage_hdr", i)))

        # Draw Row 2 & 3: Parameters for the selected stage
        sk, hdr, params = stage_grid[focus_col]
        focus_param = max(0, min(len(params) - 1, focus_param))
        self.editor_param_row = focus_param
        pw = (w - margin * 2 - gap * (len(params) - 1)) / len(params)
        py0 = top_y + hdr_h + 8
        for i, lbl in enumerate(params):
            px0 = margin + i * (pw + gap)
            px1 = px0 + pw
            is_f = editor_focused and (not top_focus) and not hdr_focus and i == focus_param
            val, en = self._stage_cell_value(ch, sk, lbl)
            hc = self.STAGE_COLOR.get(sk, "#9aa6b6")
            
            # Label Row (Row 2) + Value Row (Row 3) in one cell block
            c.create_rectangle(px0, py0, px1, py0 + cell_h, outline="#fff" if is_f else ("#2a3848" if en else "#1d2530"), width=2 if is_f else 1, fill="#1d2c39" if en else "#131a22")
            if is_f:
                c.create_rectangle(px0 - 4, py0 - 4, px1 + 4, py0 + cell_h + 4, outline=focus_outline, width=4)
                c.create_rectangle(px0 - 8, py0 - 8, px1 + 8, py0 + cell_h + 8, outline="#ffd400", width=2)
            c.create_text((px0+px1)/2, py0 + 10, text=lbl, fill="#f2f3f6" if en else "#7d8a9b", font=("Segoe UI", 8, "bold"))
            c.create_text((px0+px1)/2, py0 + cell_h - 14, text=val, fill=hc if en else "#5d6b7c", font=("Consolas", 10, "bold"))
            self.editor_hitboxes.append((px0, py0, px1, py0 + cell_h, ("stage_param", focus_col, i)))
        active_stage = "INS" if getattr(self, "editor_insert_focus", False) else stage_grid[focus_col][1]
        active_label = "INSERT" if getattr(self, "editor_insert_focus", False) else (active_stage if hdr_focus else params[focus_param])
        if editor_focused:
            c.create_text(w - 12, h - 8, anchor="se", text=f"FOCUS {active_stage}:{active_label}", fill=focus_outline, font=("Segoe UI", 9, "bold"))

    def _draw_editor_fader_circles(self, c: tk.Canvas, w: int, y0: float, h: float, focused: bool, focus_outline: str) -> None:
        layer = int(getattr(self, "fader_layer", 0))
        mode = getattr(self, "target_bank_mode", "ch")
        base_label = self._target_mode_label(mode)
        assign_mode = bool(getattr(self, "group_assign_mode", False))
        assign_idx = int(getattr(self, "group_assign_index", 0))
        layer_label = f"ASSIGN G{assign_idx + 1}" if assign_mode else (base_label if layer <= 0 or mode != "ch" else f"S{layer}")
        count = self.TOP_CONTROL_COUNT
        vol_idx = self.TOP_MASTER_VOL_INDEX
        bank_idx = self.TOP_BANK_INDEX
        bank_offset = self._target_bank_offset(mode)
        target_count = self._target_count_for_mode(mode)
        gap = 5
        diameter = max(26, min(36, (w - 24 - gap * (count - 1)) / count))
        total = diameter * count + gap * (count - 1)
        start = max(12, (w - total) / 2)
        cy = y0 + h / 2
        focus_idx = int(np.clip(getattr(self, "top_control_focus", 0), 0, count - 1))
        c.create_text(12, y0 + 4, anchor="nw", text=f"{layer_label}", fill="#ff4fd8" if assign_mode else ("#7dd3fc" if layer <= 0 else "#ffb757"), font=("Segoe UI", 8, "bold"))
        for i in range(count):
            cx = start + i * (diameter + gap) + diameter / 2
            r = diameter / 2
            is_focus = focused and i == focus_idx
            if i == bank_idx:
                fill = "#1b2430"
                outline = focus_outline if is_focus else "#5f7690"
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=outline, width=4 if is_focus else 2)
                c.create_text(cx, cy - 3, text="DONE" if assign_mode else "BNK", fill="#d6e1ec", font=("Segoe UI", 7, "bold"))
                c.create_text(cx, cy + 10, text=f"G{assign_idx + 1}" if assign_mode else (base_label if mode != "ch" else f"+{bank_offset}"), fill="#ff4fd8" if assign_mode else "#7dd3fc", font=("Consolas", 6, "bold"))
                self.editor_hitboxes.append((cx - r, cy - r, cx + r, cy + r, ("editor_top_circle", i)))
                continue
            if i == vol_idx:
                gain_val = float(np.clip(getattr(self.engine, "master_gain", 1.0), 0.0, 2.2))
                val = gain_val / 2.2
                fill = "#241923"
                outline = focus_outline if is_focus else "#7f1d1d"
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=outline, width=4 if is_focus else 2)
                self._draw_bottom_up_level_arc(c, cx, cy, r - 4, float(val), "#ef233c", width=3)
                angle = math.radians(270.0 - val * 270.0)
                c.create_line(cx, cy, cx + math.cos(angle) * (r - 7), cy - math.sin(angle) * (r - 7), fill="#ffd7d3", width=2)
                c.create_text(cx, cy - 3, text="VOL", fill="#ffd7d3", font=("Segoe UI", 7, "bold"))
                c.create_text(cx, cy + 10, text=f"{gain_val:.2f}", fill="#ff3355", font=("Consolas", 6, "bold"))
                self.editor_hitboxes.append((cx - r, cy - r, cx + r, cy + r, ("editor_top_circle", i)))
                continue
            mapped_idx = bank_offset + i
            has_strip = mapped_idx < target_count
            ch = self._target_at(mode, mapped_idx) if has_strip else None
            selected = mapped_idx == int(getattr(self, "editor_channel", getattr(self, "selected_channel", 0)))
            assigned_group = self._channel_primary_group(ch) if assign_mode and mode == "ch" else None
            assigned = assigned_group is not None
            assigned_to_active = assigned_group == assign_idx
            if layer <= 0:
                gain_val = float(getattr(self.engine, "master_gain", 0.0)) if mode == "mst" else float(getattr(ch, "gain", 0.0) if ch is not None else 0.0)
                val = float(np.clip(gain_val, 0.0, 2.2)) / 2.2
                color = "#7cf0a9"
            elif mode == "ch":
                val = self._channel_send_level(ch, layer) if ch is not None else 0.0
                color = "#ffb757"
            else:
                val = 0.0
                color = "#5f7690"
            fill = "#18222d" if has_strip else "#10151b"
            outline = focus_outline if is_focus else ("#ff4fd8" if assigned_to_active else ("#fbbf24" if assigned else ("#d9e6f2" if selected else ("#395065" if has_strip else "#1d2735"))))
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=outline, width=4 if is_focus or assigned_to_active else (3 if assigned else (2 if selected else 1)))
            if has_strip:
                self._draw_bottom_up_level_arc(c, cx, cy, r - 4, float(val), color, width=3)
            label = self._target_display_label(mode, mapped_idx)
            main = label if not assign_mode else "GRP"
            c.create_text(cx, cy - 3, text=main, fill="#d6e1ec" if has_strip else "#46586c", font=("Segoe UI", 8, "bold"))
            if assign_mode:
                sub = f"G{assigned_group + 1}" if assigned_group is not None else "G0"
                sub_fill = "#ff4fd8" if assigned_to_active else ("#fbbf24" if assigned else "#6f879a")
            else:
                sub = layer_label
                sub_fill = color if has_strip else "#31404e"
            c.create_text(cx, cy + 10, text=sub, fill=sub_fill, font=("Consolas", 6, "bold"))
            self.editor_hitboxes.append((cx - r, cy - r, cx + r, cy + r, ("editor_top_circle", i)))

    def _draw_bottom_up_level_arc(self, c: tk.Canvas, cx: float, cy: float, r: float, value: float, color: str, *, width: int = 3) -> None:
        val = float(np.clip(value, 0.0, 1.0))
        if val <= 0.001:
            return
        # Tk arc degrees start at 3 o'clock. 270 degrees is 6 o'clock.
        # Use a negative extent so the level grows up the opposite side of the
        # knob: zero starts at the bottom and full scale lands just shy of 360.
        c.create_arc(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            start=270,
            extent=-val * 270.0,
            style="arc",
            outline=color,
            width=width,
        )

    def _draw_strips(self) -> None:
        c = self.strip_canvas; c.delete("all")
        self.strip_hitboxes = []
        w, h = max(c.winfo_width(), 980), max(c.winfo_height(), 720)
        c.create_rectangle(0, 0, w, h, fill="#0c1014", outline="")
        gap = 8
        visible_count = self.TOP_CHANNEL_CONTROL_COUNT
        sx = 18
        channel_area_w = max(visible_count * 44, w - 36)
        sw = min(self.STRIP_WIDTH, max(44, int((channel_area_w - gap * (visible_count - 1)) / visible_count)))
        strip_mode, visible_bank = self._visible_strip_targets()
        tw = len(visible_bank)*sw + (len(visible_bank)-1)*gap
        self._strip_layout = {"sx": sx, "sw": sw, "gap": gap}
        top_y, bottom_y = 14, h - 14
        body_h = bottom_y - top_y
        insert_row_h = 18
        grid_h = 14 + insert_row_h + len(self._STAGE_GRID)*16 + 16
        fixed_h = grid_h + 18 + 26 + 50 + 28 + 14
        rem_h = max(80, body_h - fixed_h)
        wf_h, fader_h = int(rem_h*0.55), rem_h - int(rem_h*0.55)
        
        for col, (channel_idx, ch) in enumerate(visible_bank):
            x0, x1 = sx + col*(sw+gap), sx + col*(sw+gap) + sw
            is_m = False
            sel = strip_mode == getattr(self, "target_bank_mode", "ch") and channel_idx == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel)
            c.create_rectangle(x0, top_y+10, x1, bottom_y, fill="#181e25", outline="#30404f")
            # Waveform
            wfy0, wfy1 = top_y+14, top_y+14+wf_h
            c.create_rectangle(x0+5, wfy0, x1-5, wfy1, fill="#0a0d11", outline="#1d2735")
            self._draw_vertical_waveform(c, ch, x0+7, wfy0+2, x1-7, wfy1-2, is_m)
            # Record
            if not is_m:
                rec_f = strip_mode == "ch" and sel and getattr(self, "console_row", "") == "record"
                c.create_rectangle(x0+14, wfy1+4, x1-14, wfy1+4+22, fill="#232b34" if rec_f else "#10151b", outline="#f8d58a" if rec_f else "#2b3743")
                rr = 6; cx, cy_r = (x0+x1)/2, wfy1+4+11
                c.create_oval(cx-rr, cy_r-rr, cx+rr, cy_r+rr, fill="#ff3b30" if strip_mode == "ch" and getattr(ch, "record_armed", False) else "#ff7b73", outline="#ffd7d3" if strip_mode == "ch" and getattr(ch, "record_armed", False) else "", width=1 if strip_mode == "ch" and getattr(ch, "record_armed", False) else 0)
        
        # Stages Grid Bridge
        gy0 = top_y + 14 + wf_h + 26
        gy1 = gy0 + grid_h
        c.create_rectangle(sx-12, gy0, sx+tw+12, gy1, fill="#0a0d12", outline="#1f2933")
        c.create_text(sx-4, gy0+4, anchor="nw", text="INSERTS", fill="#5ec8ff", font=("Segoe UI", 8, "bold"))
        insert_cy = gy0 + 14 + 8
        c.create_text(sx-4, insert_cy+8, anchor="w", text="INS", fill="#9bd7ff", font=("Segoe UI", 7, "bold"))
        for col, (_channel_idx, _ch) in enumerate(visible_bank):
            cx0, cx1 = sx + col*(sw+gap)+4, sx + col*(sw+gap)+sw-4
            c.create_rectangle(cx0, insert_cy+2, cx1, insert_cy+14, fill="#101923", outline="#2a7ca8", width=1)
        for r, (key, lbl, _) in enumerate(self._STAGE_GRID):
            cy = gy0 + 14 + 8 + insert_row_h + r*16
            c.create_text(sx-4, cy+8, anchor="w", text=lbl, fill="#62748a", font=("Segoe UI", 7, "bold"))
            for col, (channel_idx, ch) in enumerate(visible_bank):
                cx0, cx1 = sx + col*(sw+gap)+4, sx + col*(sw+gap)+sw-4
                en = self._stage_enabled(ch, key)
                act = strip_mode == getattr(self, "target_bank_mode", "ch") and channel_idx == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel) and self.selected_stage_key == key and (self.nav_scope == "editor" or (self.nav_scope == "console" and getattr(self, "console_row", "") == "stages"))
                bc = self.STAGE_COLOR.get(key, "#1c2530") if en else "#1c2530"
                c.create_rectangle(cx0, cy+2, cx1, cy+14, fill=bc if en else "#10151b", outline="#d9e6f2" if act else ("#2a3848" if not en else bc), width=2 if act else 1)
        
        # ID, Knobs, Faders
        id_y = gy1 + 10
        for col, (channel_idx, ch) in enumerate(visible_bank):
            x0, x1 = sx + col*(sw+gap), sx + col*(sw+gap) + sw
            is_m = False
            sel = strip_mode == getattr(self, "target_bank_mode", "ch") and channel_idx == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel)
            assigned_group = self._channel_primary_group(ch) if bool(getattr(self, "group_assign_mode", False)) and strip_mode == "ch" else None
            assigned = assigned_group is not None
            assigned_to_active = assigned_group == int(getattr(self, "group_assign_index", 0))
            # ID + Status Glyphs (48V, PHS)
            c.create_rectangle(x0+3, id_y+4, x1-3, id_y+4+14, fill="#351735" if assigned_to_active else ("#352c17" if assigned else ("#1e2a36" if not is_m else "#272e38")), outline="#ff4fd8" if assigned_to_active else ("#fbbf24" if assigned else ""), width=2 if assigned else 1)
            id_label = f"{channel_idx+1:02d}" if strip_mode == "ch" else self._target_display_label(strip_mode, channel_idx)
            c.create_text((x0+x1)/2, id_y+4+7, text=id_label, fill="#d6e1ec", font=("Segoe UI", 9, "bold"))
            if assigned:
                c.create_text(x1-8, id_y+4+7, text=f"G{assigned_group + 1}", fill="#ff4fd8" if assigned_to_active else "#fbbf24", font=("Segoe UI", 6, "bold"))
            if not is_m:
                # 48V Glyph
                if getattr(ch, "phantom", False):
                    c.create_text(x0+10, id_y+4+7, text="48V", fill="#ff3b30", font=("Segoe UI", 6, "bold"))
                # Phase Glyph
                if getattr(ch, "phase", False):
                    c.create_text(x1-10, id_y+4+7, text="ø", fill="#ff9500", font=("Segoe UI", 8, "bold"))
            # Knob
            kn_f = not is_m and strip_mode == getattr(self, "target_bank_mode", "ch") and ((self.nav_scope == "knobs" and self.knob_focus_channel == col) or (self.nav_scope == "console" and getattr(self, "console_row", "") == "knob" and self.selected_channel == channel_idx))
            self._draw_send_knob(c, ch, x0+6, id_y+22, x1-6, id_y+22+46, focused=kn_f, channel_idx=col)
            # Fader
            fd_f = not is_m and strip_mode == getattr(self, "target_bank_mode", "ch") and ((self.nav_scope == "faders" and self.fader_focus_channel == col) or (self.nav_scope == "console" and getattr(self, "console_row", "") in ("fader", "faders") and self.selected_channel == channel_idx))
            self._draw_strip_fader(c, ch, x0+12, id_y+72, x1-12, bottom_y-28-6, is_m, focused=fd_f)
            # Footer
            ft_y0, ft_y1 = bottom_y-28-2, bottom_y-4
            f_sel = sel and getattr(self, "console_row", "") == "footer"
            if is_m:
                c.create_rectangle(x0+8, ft_y0, x1-8, ft_y1, fill="#1b222a", outline="#31404e")
                c.create_text((x0+x1)/2, (ft_y0+ft_y1)/2, text="MST", fill="#d8dfe8", font=("Segoe UI", 8, "bold"))
            else:
                mid = (x0+x1)/2; g=2
                solo_f = f_sel and getattr(self, "footer_focus_side", "solo") == "solo"
                mute_f = f_sel and getattr(self, "footer_focus_side", "solo") == "mute"
                c.create_rectangle(x0+8, ft_y0, mid-g, ft_y1, fill="#645019" if getattr(ch, "solo", False) else "#1b222a", outline="#f8d58a" if solo_f or getattr(ch, "solo", False) else "#3d4a5a", width=2 if solo_f or getattr(ch, "solo", False) else 1)
                c.create_text((x0+8+mid-g)/2, (ft_y0+ft_y1)/2, text="S", fill="#fff0b2" if getattr(ch, "solo", False) else "#7a8a9c", font=("Segoe UI", 9, "bold"))
                c.create_rectangle(mid+g, ft_y0, x1-8, ft_y1, fill="#6b171c" if getattr(ch, "mute", False) else "#1b222a", outline="#f8d58a" if mute_f or getattr(ch, "mute", False) else "#3d4a5a", width=2 if mute_f or getattr(ch, "mute", False) else 1)
                c.create_text((mid+g+x1-8)/2, (ft_y0+ft_y1)/2, text="M", fill="#ffd7d3" if getattr(ch, "mute", False) else "#7a8a9c", font=("Segoe UI", 9, "bold"))
                self.strip_hitboxes.append((x0+8, ft_y0, mid-g, ft_y1, ("solo", channel_idx)))
                self.strip_hitboxes.append((mid+g, ft_y0, x1-8, ft_y1, ("mute", channel_idx)))
        self._draw_master_meter()

    def _draw_master_strip(self, c: tk.Canvas, x0: float, top_y: float, x1: float, bottom_y: float, wf_h: float, gy0: float, gy1: float, id_y: float, selected: bool) -> None:
        ch = self.engine.master_channel
        c.create_rectangle(x0, top_y + 10, x1, bottom_y, fill="#211419", outline="#7f1d1d" if selected else "#4b2730", width=2 if selected else 1)
        wfy0, wfy1 = top_y + 14, top_y + 14 + wf_h
        c.create_rectangle(x0 + 5, wfy0, x1 - 5, wfy1, fill="#0a0d11", outline="#3b1f28")
        self._draw_stereo_master_waveform(c, ch, x0 + 7, wfy0 + 2, x1 - 7, wfy1 - 2)

        c.create_rectangle(x0 + 5, gy0, x1 - 5, gy1, fill="#12090d", outline="#4b2730")
        c.create_text(x0 + 10, gy0 + 8, anchor="w", text="MASTER INSERTS", fill="#ff8fa3", font=("Segoe UI", 8, "bold"))
        c.create_rectangle(x0 + 12, gy0 + 22, x1 - 12, gy0 + 34, fill="#140f14", outline="#8a3d4a", width=1)
        c.create_text(x0 + 16, gy0 + 28, anchor="w", text="INS", fill="#ff9aaa", font=("Segoe UI", 7, "bold"))
        c.create_text(x1 - 16, gy0 + 28, anchor="e", text="off", fill="#6f4a54", font=("Consolas", 7, "bold"))
        c.create_text(x0 + 10, gy0 + 44, anchor="w", text="MASTER DSP", fill="#ff8fa3", font=("Segoe UI", 8, "bold"))
        for r, (key, lbl, _) in enumerate(self._STAGE_GRID):
            cy = gy0 + 58 + r * 16
            cell_x0, cell_x1 = x0 + 12, x1 - 12
            en = self._stage_enabled(ch, key)
            act = selected and self.selected_stage_key == key and (self.nav_scope == "editor" or (self.nav_scope == "console" and getattr(self, "console_row", "") == "stages"))
            bc = self.STAGE_COLOR.get(key, "#1c2530") if en else "#1c2530"
            c.create_rectangle(cell_x0, cy, cell_x1, cy + 12, fill=bc if en else "#10151b", outline="#ffd7d3" if act else ("#4b2730" if not en else bc), width=2 if act else 1)
            c.create_text(cell_x0 + 4, cy + 6, anchor="w", text=lbl, fill="#ffe4e6" if en else "#6f4a54", font=("Segoe UI", 7, "bold"))

        c.create_rectangle(x0 + 3, id_y + 4, x1 - 3, id_y + 4 + 14, fill="#35151b", outline="")
        c.create_text((x0 + x1) / 2, id_y + 11, text="MST", fill="#ffd7d3", font=("Segoe UI", 9, "bold"))
        self._draw_strip_fader(c, ch, x0 + 12, id_y + 42, x1 - 12, bottom_y - 28 - 6, True, focused=selected and getattr(self, "console_row", "") in ("fader", "faders"))
        ft_y0, ft_y1 = bottom_y - 28 - 2, bottom_y - 4
        c.create_rectangle(x0 + 8, ft_y0, x1 - 8, ft_y1, fill="#2a1116", outline="#7f1d1d" if selected else "#4b2730", width=2 if selected else 1)
        c.create_text((x0 + x1) / 2, (ft_y0 + ft_y1) / 2, text="MASTER", fill="#ffd7d3", font=("Segoe UI", 7, "bold"))
        self.strip_hitboxes.append((x0, top_y + 10, x1, bottom_y, ("master", self._master_nav_index())))

    def _draw_master_panel(self) -> None:
        c = getattr(self, "master_canvas", None)
        if c is None:
            return
        c.delete("all")
        self.master_hitboxes = []
        w, h = max(c.winfo_width(), 112), max(c.winfo_height(), 640)
        ch = self.engine.master_channel
        selected = self._is_master_nav_index(self.editor_channel if self.nav_scope == "editor" else self.selected_channel)
        c.create_rectangle(0, 0, w, h, fill="#180d12", outline="")
        c.create_rectangle(4, 4, w - 4, h - 4, fill="#211419", outline="#ef233c" if selected else "#4b2730", width=3 if selected else 1)
        c.create_text(w / 2, 20, text="MASTER", fill="#ffd7d3", font=("Segoe UI", 10, "bold"))

        wf_y0, wf_y1 = 40, max(150, min(h * 0.38, 260))
        c.create_rectangle(14, wf_y0, w - 14, wf_y1, fill="#0a0d11", outline="#4b2730")
        self._draw_stereo_master_waveform(c, ch, 18, wf_y0 + 4, w - 18, wf_y1 - 4)

        dsp_y0 = wf_y1 + 24
        c.create_rectangle(12, dsp_y0, w - 12, dsp_y0 + 176, fill="#12090d", outline="#4b2730")
        c.create_text(18, dsp_y0 + 11, anchor="w", text="MASTER INSERTS", fill="#ff8fa3", font=("Segoe UI", 8, "bold"))
        c.create_rectangle(18, dsp_y0 + 28, w - 18, dsp_y0 + 42, fill="#140f14", outline="#8a3d4a", width=1)
        c.create_text(22, dsp_y0 + 35, anchor="w", text="INS", fill="#ff9aaa", font=("Segoe UI", 7, "bold"))
        c.create_text(w - 22, dsp_y0 + 35, anchor="e", text="off", fill="#6f4a54", font=("Consolas", 7, "bold"))
        c.create_text(18, dsp_y0 + 56, anchor="w", text="MASTER DSP", fill="#ff8fa3", font=("Segoe UI", 8, "bold"))
        master_stages = [("pre", "FLT")] + [(key, lbl) for key, lbl, _params in self._STAGE_GRID if key != "pre"]
        for r, (key, lbl) in enumerate(master_stages):
            cy = dsp_y0 + 72 + r * 16
            en = self._stage_enabled(ch, key)
            act = selected and self.selected_stage_key == key and (self.nav_scope == "editor" or (self.nav_scope == "console" and getattr(self, "console_row", "") == "stages"))
            bc = self.STAGE_COLOR.get(key, "#1c2530") if en else "#1c2530"
            c.create_rectangle(18, cy, w - 18, cy + 12, fill=bc if en else "#10151b", outline="#ffd7d3" if act else ("#4b2730" if not en else bc), width=2 if act else 1)
            c.create_text(22, cy + 6, anchor="w", text=lbl, fill="#ffe4e6" if en else "#6f4a54", font=("Segoe UI", 7, "bold"))
            self.master_hitboxes.append((18, cy, w - 18, cy + 12, ("master_stage", key)))

        fader_y0 = dsp_y0 + 200
        fader_y1 = h - 48
        c.create_rectangle(14, fader_y0, w - 14, fader_y1, fill="#0d1218", outline="#4b2730")
        self._draw_strip_fader(c, ch, 28, fader_y0 + 12, w - 28, fader_y1 - 12, True, focused=selected)
        c.create_rectangle(14, h - 38, w - 14, h - 12, fill="#35151b", outline="#7f1d1d")
        c.create_text(w / 2, h - 25, text="MST", fill="#ffd7d3", font=("Segoe UI", 9, "bold"))

    def _draw_master_gain_knob(self, c: tk.Canvas, cx: float, cy: float, r: float, selected: bool) -> None:
        gain = float(np.clip(getattr(self.engine, "master_gain", 1.0), 0.0, 2.2))
        norm = gain / 2.2
        if selected:
            c.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, outline="#ffd400", width=3)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#18222d", outline="#7f1d1d", width=2)
        self._draw_bottom_up_level_arc(c, cx, cy, r - 5, norm, "#ef233c", width=5)
        angle = math.radians(270.0 - norm * 270.0)
        px = cx + math.cos(angle) * (r - 10)
        py = cy - math.sin(angle) * (r - 10)
        c.create_line(cx, cy, px, py, fill="#ffd7d3", width=3)
        c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#ef233c", outline="")
        c.create_text(cx, cy + r + 13, text="VOL", fill="#ffd7d3", font=("Segoe UI", 8, "bold"))
        c.create_text(cx, cy + r + 29, text=f"{gain:.2f}", fill="#ff3355", font=("Consolas", 8, "bold"))

    def _draw_top_fader_circles(self, c: tk.Canvas, w: int, strip_sources: list[ChannelState], sx: float, sw: float, gap: float) -> None:
        layer = int(getattr(self, "fader_layer", 0))
        layer_label = "FDR" if layer <= 0 else f"S{layer}"
        top_focused = getattr(self, "nav_scope", "console") == "console" and getattr(self, "console_row", "") == "top"
        focus_idx = int(np.clip(getattr(self, "top_control_focus", 0), 0, self.TOP_CONTROL_COUNT - 1))
        c.create_text(18, 16, anchor="w", text=f"{layer_label} CONTROL", fill="#7dd3fc" if layer <= 0 else "#ffb757", font=("Segoe UI", 9, "bold"))
        total = self.TOP_CONTROL_COUNT * 42 + (self.TOP_CONTROL_COUNT - 1) * 10
        start = max(18, (w - total) / 2)
        for i in range(self.TOP_CONTROL_COUNT):
            cx = start + i * 52 + 21
            cy = 28
            if i == self.TOP_BANK_INDEX:
                focused = top_focused and i == focus_idx
                c.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, fill="#1b2430", outline="#ffd400" if focused else "#5f7690", width=4 if focused else 2)
                c.create_text(cx, cy - 3, text="BNK", fill="#d6e1ec", font=("Segoe UI", 7, "bold"))
                c.create_text(cx, cy + 10, text=f"+{self._target_bank_offset()}", fill="#7dd3fc", font=("Consolas", 6, "bold"))
                continue
            if i == self.TOP_MASTER_VOL_INDEX:
                focused = top_focused and i == focus_idx
                gain_val = float(np.clip(getattr(self.engine, "master_gain", 1.0), 0.0, 2.2))
                val = gain_val / 2.2
                c.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, fill="#241923", outline="#ffd400" if focused else "#7f1d1d", width=4 if focused else 2)
                self._draw_bottom_up_level_arc(c, cx, cy, 14, float(val), "#ef233c", width=3)
                c.create_text(cx, cy - 3, text="VOL", fill="#ffd7d3", font=("Segoe UI", 7, "bold"))
                c.create_text(cx, cy + 10, text=f"{gain_val:.2f}", fill="#ff3355", font=("Consolas", 6, "bold"))
                continue
            has_strip = i < len(strip_sources)
            ch = strip_sources[i] if has_strip else None
            selected = i == int(np.clip(getattr(self, "selected_channel", 0), 0, self.TOP_CONTROL_COUNT - 1))
            focused = top_focused and i == focus_idx
            if layer <= 0:
                val = float(np.clip(getattr(ch, "gain", 0.0) if ch is not None else 0.0, 0.0, 2.2)) / 2.2
                color = "#7cf0a9"
            else:
                val = self._channel_send_level(ch, layer) if ch is not None and i < len(self.engine.channels) else 0.0
                color = "#ffb757"
            fill = "#18222d" if has_strip else "#10151b"
            outline = "#ffd400" if focused else ("#d9e6f2" if selected else ("#395065" if has_strip else "#1d2735"))
            width = 4 if focused else (2 if selected else 1)
            c.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, fill=fill, outline=outline, width=width)
            if has_strip:
                self._draw_bottom_up_level_arc(c, cx, cy, 14, float(val), color, width=3)
            label = "M" if i == len(self.engine.channels) else str(i + 1)
            if not has_strip:
                label = "--"
            c.create_text(cx, cy - 2, text=label, fill="#d6e1ec" if has_strip else "#46586c", font=("Segoe UI", 8, "bold"))
            c.create_text(cx, cy + 11, text=layer_label, fill=color if has_strip else "#31404e", font=("Consolas", 6, "bold"))

    def _draw_master_meter(self) -> None:
        c = self.strip_canvas
        # Simplified master meter overlay
        pass

    # --- Events ---
    def _spacemouse_toggle_play_stop(self) -> None:
        now = time.monotonic()
        if now - float(getattr(self, "_last_spacemouse_pull_play_at", 0.0)) < 0.65:
            return
        self._last_spacemouse_pull_play_at = now
        self.engine.toggle_play()
        self._flash_transport_action("play_stop")
        _log.info(f"SPACEMOUSE_PLAY_STOP: playing={getattr(self.engine, 'playing', False)} nav_scope={getattr(self, 'nav_scope', '')}")
        self._sync_from_engine()

    def _poll_spacemouse(self) -> None:
        res = self.spacemouse.poll()
        if not res: return
        val, pr, dr = res
        if dr:
            for d in dr:
                if d in ("left", "right", "up", "down", "press", "back", "down_hold"):
                    if d == "back":
                        self._spacemouse_toggle_play_stop()
                        continue
                    if d == "down_hold":
                        self._handle_nav("down_hold")
                        continue
                    if d == "press":
                        _log.info(f"SPACEMOUSE_PRESS: dr nav_scope={getattr(self, 'nav_scope', '')} editor_top={getattr(self, 'editor_top_focus', False)} top={getattr(self, 'top_control_focus', None)} offset={getattr(self, 'fader_bank_offset', None)}")
                    self._handle_nav(d)
        elif pr and 0 in pr:
            _log.info(f"SPACEMOUSE_PRESS: pr nav_scope={getattr(self, 'nav_scope', '')} editor_top={getattr(self, 'editor_top_focus', False)} top={getattr(self, 'top_control_focus', None)} offset={getattr(self, 'fader_bank_offset', None)}")
            self._handle_nav("press")
        else:
            self._adjust_focused_axis(val)

    def _handle_nav(self, target: str) -> None:
        if target == "down_hold":
            self._rewind_from_down_hold()
            return
        if target in ("left", "right", "up", "down"):
            now = time.monotonic()
            if target == "down":
                started = float(getattr(self, "_down_nav_hold_started_at", 0.0))
                if started <= 0.0:
                    self._down_nav_hold_started_at = now
                    self._down_nav_hold_fired = False
                elif not bool(getattr(self, "_down_nav_hold_fired", False)) and now - started >= 1.0:
                    self._rewind_from_down_hold()
                    self._down_nav_hold_fired = True
                    return
            else:
                self._down_nav_hold_started_at = 0.0
                self._down_nav_hold_fired = False
            min_gap = 0.14 if target in ("up", "down") else 0.22
            if now - float(getattr(self, "_last_cardinal_nav_at", 0.0)) < min_gap:
                return
            self._last_cardinal_nav_at = now
        ns = getattr(self, "nav_scope", "console")
        if ns == "editor": self._handle_unified_editor_nav(target)
        elif ns == "console": self._handle_console_nav(target)
        elif ns == "transport": self._handle_transport_nav(target)
        elif ns == "timeline": self._handle_timeline_nav(target)

    def _rewind_from_down_hold(self) -> None:
        self.engine.rewind()
        self._timeline_selection = None
        self._flash_transport_action("advance_home")
        self._sync_from_engine()

    def _handle_console_nav(self, target: str) -> None:
        r = getattr(self, "console_row", "stages")
        if target == "left":
            if r == "top":
                self.console_row = "stages"
            elif r == "stages":
                sk = self._console_stage_keys(); si = sk.index(self.selected_stage_key)
                if si > 0: self.selected_stage_key = sk[si-1]
            elif r == "footer":
                self.footer_focus_side = "solo"
            elif self._is_master_nav_index(self.selected_channel):
                bank = self._visible_bank_channels()
                if bank:
                    self.selected_channel = bank[-1][0]
            else:
                self.selected_channel = (self.selected_channel - 1) % self._channel_nav_span()
        elif target == "right":
            if r == "top":
                self.console_row = "stages"
            elif r == "stages":
                sk = self._console_stage_keys(); si = sk.index(self.selected_stage_key)
                if si < len(sk)-1: self.selected_stage_key = sk[si+1]
            elif r == "footer":
                self.footer_focus_side = "mute"
            else:
                bank = self._visible_bank_channels()
                if bank and int(self.selected_channel) == int(bank[-1][0]):
                    self.selected_channel = self._master_nav_index()
                else:
                    self.selected_channel = (self.selected_channel + 1) % self._channel_nav_span()
        elif target == "up":
            if r == "stages": self.console_row = "top"
            elif r == "faders": self.console_row = "stages"
            elif r == "footer": self.console_row = "faders"
        elif target == "down":
            if r == "top": self.console_row = "stages"
            elif r == "stages": self.console_row = "faders"
            elif r == "faders": self.console_row = "footer"
        elif target == "press":
            if r == "top": self.console_row = "stages"
            elif r == "stages": self._open_stage_editor(self.selected_channel, self.selected_stage_key)
            elif r == "footer": self._toggle_channel_footer(self.selected_channel, getattr(self, "footer_focus_side", "solo"))
        self._sync_from_engine()


    def _handle_transport_nav(self, target: str) -> None:
        tr, tc = getattr(self, "transport_focus_row", 0), getattr(self, "transport_focus_col", 0)
        if target == "up":
            if tr > 0: self.transport_focus_row -= 1
            else:
                # Jump back to editor
                self.nav_scope = "editor"
                self.editor_unified_header_focus = False
        elif target == "down":
            if tr < self.TRANSPORT_ROWS - 1:
                self.transport_focus_row += 1
                if not self._transport_button_at(self.transport_focus_row, self.transport_focus_col):
                    self.transport_focus_col = self._transport_cols_for_row(self.transport_focus_row)[-1]
            else:
                self.nav_scope = "timeline"
        elif target == "left":
            cols = self._transport_cols_for_row(tr)
            self.transport_focus_col = cols[(cols.index(tc) - 1) % len(cols)] if tc in cols else cols[0]
        elif target == "right":
            cols = self._transport_cols_for_row(tr)
            self.transport_focus_col = cols[(cols.index(tc) + 1) % len(cols)] if tc in cols else cols[0]
        elif target == "press":
            btn = self._transport_button_at(tr, tc)
            if btn: getattr(self, f"_tx_{btn[0]}", lambda: None)()
        elif target == "back": self._exit_transport_to_console()
        self._sync_from_engine()

    def _handle_timeline_nav(self, target: str) -> None:
        if target == "up":
            self.nav_scope = "transport"
            self.transport_focus_row = self.TRANSPORT_ROWS - 1
            self.transport_focus_col = 0
        elif target == "down":
            self._delete_selected_timeline_marker()
        elif target == "left":
            if self._has_edit_clipboard():
                self._bump_edit_clipboard_position(-1)
            else:
                self._select_timeline_item(-1)
        elif target == "right":
            if self._has_edit_clipboard():
                self._bump_edit_clipboard_position(1)
            else:
                self._select_timeline_item(1)
        elif target == "press":
            self._push_edit_undo("marker")
            self.engine.add_marker()
            self._timeline_selection = None
            self._flash_transport_action("marker")
        elif target == "back":
            self.nav_scope = "transport"
            self.transport_focus_row = self.TRANSPORT_ROWS - 1
            self.transport_focus_col = 0
        self._sync_from_engine()

    def _timeline_items(self) -> list[dict[str, Any]]:
        markers = sorted(
            (float(m), idx) for idx, m in enumerate(getattr(self.engine, "markers", []))
        )
        items: list[dict[str, Any]] = []
        for sorted_idx, (t, original_idx) in enumerate(markers):
            items.append({"kind": "marker", "key": ("marker", original_idx), "time": t, "start": t, "end": t, "sorted_idx": sorted_idx, "original_idx": original_idx})
        for pair_idx, ((a, _ai), (b, _bi)) in enumerate(zip(markers[:-1], markers[1:])):
            items.append({"kind": "region", "key": ("region", pair_idx), "time": (a + b) * 0.5, "start": a, "end": b, "pair_idx": pair_idx})
        return sorted(items, key=lambda item: (float(item["time"]), 0 if item["kind"] == "marker" else 1))

    def _selected_timeline_item(self) -> Optional[dict[str, Any]]:
        sel = getattr(self, "_timeline_selection", None)
        if sel is None:
            return None
        return next((item for item in self._timeline_items() if item["key"] == sel), None)

    def _select_timeline_item(self, direction: int) -> None:
        items = self._timeline_items()
        duration = max(0.01, float(self.engine.timeline_duration_seconds()))
        if not items:
            if direction > 0:
                self.engine.jump_forward(0.25)
            else:
                self.engine.jump_back(0.25)
            self._flash_transport_action("timeline")
            return
        playhead = float(getattr(self.engine, "playhead_seconds", 0.0))
        sel = getattr(self, "_timeline_selection", None)
        cur_idx = next((i for i, item in enumerate(items) if item["key"] == sel), None)
        if cur_idx is None:
            if direction > 0:
                cur_idx = next((i for i, item in enumerate(items) if float(item["time"]) > playhead + 0.03), 0)
            else:
                cur_idx = next((i for i in range(len(items) - 1, -1, -1) if float(items[i]["time"]) < playhead - 0.03), len(items) - 1)
        else:
            cur_idx = (cur_idx + (1 if direction > 0 else -1)) % len(items)
        item = items[cur_idx]
        self._timeline_selection = item["key"]
        self.engine.seek_seconds(float(np.clip(item["start"], 0.0, duration)))
        self._flash_transport_action("timeline")

    def _bump_edit_clipboard_position(self, direction: int) -> None:
        duration = max(0.01, float(self.engine.timeline_duration_seconds()))
        clip_len = max(0.0, float(getattr(self, "_edit_clipboard_duration", 0.0)))
        max_start = max(0.0, duration - clip_len)
        current = float(getattr(self.engine, "playhead_seconds", 0.0))
        step = 2.0
        new_pos = float(np.clip(current + step * (1 if direction > 0 else -1), 0.0, max_start))
        self._timeline_selection = None
        self.engine.seek_seconds(new_pos)
        self.engine.ignore_marker_cycle_until = max(
            float(getattr(self.engine, "ignore_marker_cycle_until", 0.0)),
            time.monotonic() + 1.0,
        )
        self._flash_transport_action("timeline")

    def _delete_selected_timeline_marker(self) -> None:
        item = self._selected_timeline_item()
        if not item or item["kind"] != "marker":
            return
        idx = int(item["original_idx"])
        markers = getattr(self.engine, "markers", [])
        if 0 <= idx < len(markers):
            self._push_edit_undo("delete marker")
            del markers[idx]
            self._timeline_selection = None
            self._flash_transport_action("marker")

    def _copy_selected_region_to_clipboard(self, *, cut: bool) -> bool:
        item = self._selected_timeline_item()
        if not item or item["kind"] != "region":
            return False
        start_s = float(item["start"])
        end_s = float(item["end"])
        if end_s <= start_s:
            return False
        sr = 48000
        try:
            from system_q_core import SAMPLE_RATE as sr
        except Exception:
            pass
        start = int(max(0, round(start_s * sr)))
        end = int(max(start + 1, round(end_s * sr)))
        clips: list[np.ndarray] = []
        seek_after: Optional[float] = None
        if cut:
            self._push_edit_undo("cut")
        with self.engine._lock:
            for ch in self.engine.channels:
                ch_end = min(end, len(ch.audio))
                ch_start = min(start, ch_end)
                clips.append(ch.audio[ch_start:ch_end].copy())
                if cut and ch_start < ch_end:
                    ch.audio = np.vstack([ch.audio[:ch_start], ch.audio[ch_end:]]).astype(np.float32)
                    ch.position = min(ch.position, max(0, len(ch.audio) - 1))
                    ch.wave_preview = self.engine._build_wave_preview(ch.audio)
            if cut:
                removed = (end - start) / float(sr)
                new_markers = []
                for marker in getattr(self.engine, "markers", []):
                    m = float(marker)
                    if start_s <= m <= end_s:
                        continue
                    new_markers.append(m - removed if m > end_s else m)
                self.engine.markers[:] = new_markers
                seek_after = start_s
                self._timeline_selection = None
        self._edit_clipboard_audio = clips
        self._edit_clipboard_markers = (start_s, end_s)
        self._edit_clipboard_duration = max(0.0, end_s - start_s)
        self._edit_clipboard_action = "cut" if cut else "copy"
        self._edit_preview_region = (start_s, end_s, "CUT" if cut else "COPY")
        self._edit_preview_audio = [clip.copy() for clip in clips]
        if seek_after is not None:
            self.engine.seek_seconds(seek_after)
        return True

    def _capture_edit_state(self, label: str) -> dict[str, Any]:
        with self.engine._lock:
            audio = [ch.audio.copy() for ch in self.engine.channels]
            markers = [float(m) for m in getattr(self.engine, "markers", [])]
            positions = [int(ch.position) for ch in self.engine.channels]
            previews = [np.asarray(getattr(ch, "wave_preview", []), dtype=np.float32).copy() for ch in self.engine.channels]
        clip_audio = getattr(self, "_edit_clipboard_audio", None)
        preview_audio = getattr(self, "_edit_preview_audio", None)
        state = {
            "label": label,
            "audio": audio,
            "markers": markers,
            "positions": positions,
            "previews": previews,
            "clipboard_action": getattr(self, "_edit_clipboard_action", ""),
            "clipboard_audio": [c.copy() for c in clip_audio] if clip_audio else None,
            "clipboard_markers": getattr(self, "_edit_clipboard_markers", None),
            "clipboard_duration": float(getattr(self, "_edit_clipboard_duration", 0.0)),
            "timeline_selection": getattr(self, "_timeline_selection", None),
            "nav_scope": getattr(self, "nav_scope", "editor"),
            "preview_region": getattr(self, "_edit_preview_region", None),
            "preview_audio": [c.copy() for c in preview_audio] if preview_audio else None,
        }
        return state

    def _apply_edit_state(self, state: dict[str, Any]) -> None:
        with self.engine._lock:
            for ch, audio, pos, preview in zip(self.engine.channels, state["audio"], state["positions"], state["previews"]):
                ch.audio = audio.copy().astype(np.float32)
                ch.position = min(int(pos), max(0, len(ch.audio) - 1))
                ch.wave_preview = preview.copy()
            self.engine.markers[:] = [float(m) for m in state["markers"]]
        clip_audio = state.get("clipboard_audio")
        self._edit_clipboard_audio = [c.copy() for c in clip_audio] if clip_audio else None
        self._edit_clipboard_action = str(state.get("clipboard_action", ""))
        self._edit_clipboard_markers = state.get("clipboard_markers")
        self._edit_clipboard_duration = float(state.get("clipboard_duration", 0.0))
        self._timeline_selection = state.get("timeline_selection")
        self.nav_scope = str(state.get("nav_scope", "timeline"))
        self._edit_preview_region = state.get("preview_region")
        preview_audio = state.get("preview_audio")
        self._edit_preview_audio = [c.copy() for c in preview_audio] if preview_audio else None

    def _push_edit_undo(self, label: str) -> None:
        state = self._capture_edit_state(label)
        stack = getattr(self, "_edit_undo_stack", [])
        stack.append(state)
        del stack[:-12]
        self._edit_undo_stack = stack
        self._edit_undo_state = stack[-1] if stack else None
        self._edit_redo_stack = []

    def _restore_edit_undo(self) -> None:
        stack = getattr(self, "_edit_undo_stack", [])
        state = stack.pop() if stack else None
        if not state:
            self._edit_undo_state = None
            return
        redo = getattr(self, "_edit_redo_stack", [])
        redo.append(self._capture_edit_state("redo"))
        del redo[:-12]
        self._edit_redo_stack = redo
        self._apply_edit_state(state)
        self._edit_undo_stack = stack
        self._edit_undo_state = stack[-1] if stack else None

    def _restore_edit_redo(self) -> None:
        redo = getattr(self, "_edit_redo_stack", [])
        state = redo.pop() if redo else None
        if not state:
            return
        stack = getattr(self, "_edit_undo_stack", [])
        stack.append(self._capture_edit_state("undo redo"))
        del stack[:-12]
        self._edit_undo_stack = stack
        self._edit_undo_state = stack[-1] if stack else None
        self._edit_redo_stack = redo
        self._apply_edit_state(state)

    def _has_edit_clipboard(self, action: str | None = None) -> bool:
        clips = getattr(self, "_edit_clipboard_audio", None)
        if not clips:
            return False
        if action is None:
            return True
        return getattr(self, "_edit_clipboard_action", "") == action

    def _clear_edit_clipboard(self) -> None:
        self._edit_clipboard_audio = None
        self._edit_clipboard_markers = None
        self._edit_clipboard_duration = 0.0
        self._edit_clipboard_action = ""
        if not (getattr(self, "_edit_preview_region", None) and self._edit_preview_region[2] == "PASTE"):
            self._edit_preview_region = None
            self._edit_preview_audio = None

    def _paste_clipboard_at_playhead(self, *, clear_after: bool = False) -> None:
        clips = getattr(self, "_edit_clipboard_audio", None)
        if not clips:
            return
        self._push_edit_undo("paste")
        sr = 48000
        try:
            from system_q_core import SAMPLE_RATE as sr
        except Exception:
            pass
        pos = int(max(0, round(float(getattr(self.engine, "playhead_seconds", 0.0)) * sr)))
        seek_after: Optional[float] = None
        with self.engine._lock:
            for ch, clip in zip(self.engine.channels, clips):
                insert_at = min(pos, len(ch.audio))
                ch.audio = np.vstack([ch.audio[:insert_at], clip, ch.audio[insert_at:]]).astype(np.float32)
                ch.position = insert_at
                ch.wave_preview = self.engine._build_wave_preview(ch.audio)
            added = max((len(c) for c in clips), default=0) / float(sr)
            insert_s = pos / float(sr)
            self.engine.markers[:] = [float(m) + added if float(m) >= insert_s else float(m) for m in getattr(self.engine, "markers", [])]
            seek_after = insert_s + added
            self._timeline_selection = None
            self._edit_preview_region = (insert_s, insert_s + added, "PASTE")
            self._edit_preview_audio = [clip.copy() for clip in clips]
        if seek_after is not None:
            self.engine.seek_seconds(seek_after)
        if clear_after:
            self._clear_edit_clipboard()

    def _on_strip_click(self, event) -> None:
        self.root.after_idle(self.root.focus_set)
        for x0, y0, x1, y1, tag in getattr(self, "strip_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                kind, idx = tag
                self.nav_scope = "console"
                self.selected_channel = idx
                if kind == "master":
                    self.console_row = "faders"
                else:
                    self.console_row = "footer"
                    self.footer_focus_side = kind
                    self._toggle_channel_footer(idx, kind)
                self._sync_from_engine()
                return
        layout = getattr(self, "_strip_layout", {})
        sw, gap = int(layout.get("sw", self.STRIP_WIDTH)), int(layout.get("gap", 8))
        _strip_mode, visible_bank = self._visible_strip_targets()
        n_strips = len(visible_bank)
        sx = float(layout.get("sx", 18))
        idx = int((event.x - sx) / (sw + gap))
        if 0 <= idx < n_strips:
            self.selected_channel = self.editor_channel = visible_bank[idx][0]; self.nav_scope = "console"; self._sync_from_engine()
            return
        mx0 = float(layout.get("master_x0", -1))
        mx1 = float(layout.get("master_x1", -1))
        if mx0 <= event.x <= mx1:
            self.selected_channel = self._master_nav_index()
            self.nav_scope = "console"
            self.console_row = "faders"
            self._sync_from_engine()

    def _toggle_channel_footer(self, idx: int, kind: str) -> None:
        mode = getattr(self, "target_bank_mode", "ch")
        if idx < 0 or idx >= self._target_count_for_mode(mode):
            return
        ch = self._target_at(mode, idx)
        with self.engine._lock:
            if kind == "solo":
                ch.solo = not bool(getattr(ch, "solo", False))
            elif kind == "mute":
                ch.mute = not bool(getattr(ch, "mute", False))

    def _on_transport_click(self, row: int, col: int) -> None:
        self.nav_scope = "transport"
        self.transport_focus_row = row
        self.transport_focus_col = col
        btn = self._transport_button_at(row, col)
        if btn:
            getattr(self, f"_tx_{btn[0]}", lambda: None)()
        else:
            self._sync_from_engine()

    def _on_master_strip_click(self, event) -> None:
        self.selected_channel = self.editor_channel = self._master_nav_index()
        for x0, y0, x1, y1, tag in getattr(self, "master_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1 and tag[0] == "master_stage":
                stage_key = tag[1]
                stage_grid = self._stage_grid_for_channel(self.engine.master_channel)
                self.editor_stage_col = next((i for i, row in enumerate(stage_grid) if row[0] == stage_key), 0)
                self.selected_stage_key = stage_key
                self.editor_param_row = 0
                self.editor_unified_header_focus = True
                self.editor_top_focus = False
                self.nav_scope = "editor"
                self._sync_from_engine()
                return
        self.nav_scope = "console"
        self.console_row = "faders"
        self._sync_from_engine()

    def _on_timeline_click(self, event) -> None:
        c = getattr(self, "timeline_canvas", None)
        if c is None:
            return
        w = max(1, c.winfo_width())
        view_start, view_end, _duration = self._timeline_view_bounds()
        margin = 14
        frac = float(np.clip((event.x - margin) / max(1, w - margin * 2), 0.0, 1.0))
        self.engine.seek_seconds(view_start + frac * max(0.01, view_end - view_start))
        self._flash_transport_action("timeline")
        self._sync_from_engine()

    def _on_editor_canvas_click(self, event) -> None:
        self.nav_scope = "editor"
        for x0, y0, x1, y1, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if tag[0] == "editor_top_circle":
                    if self._maybe_start_group_assign_hold(int(tag[1])):
                        return "break"
                    self.editor_top_focus = True
                    self.editor_insert_focus = False
                    self.top_control_focus = int(tag[1])
                    self._select_top_control_channel()
                    if int(tag[1]) == self.TOP_BANK_INDEX:
                        self._press_top_control()
                    else:
                        self._press_top_control()
                elif tag[0] == "insert_hdr":
                    self.editor_top_focus = False
                    self.editor_unified_header_focus = True
                    self.editor_insert_focus = True
                elif tag[0] == "stage_hdr":
                    self.editor_top_focus = False
                    self.editor_insert_focus = False
                    self.editor_stage_col = tag[1]
                    self.editor_unified_header_focus = True
                    stage_grid = self._stage_grid_for_channel(self._current_channel())
                    self.selected_stage_key = stage_grid[tag[1]][0]
                    self._press_unified_editor_cell()
                elif tag[0] == "stage_param":
                    self.editor_top_focus = False
                    self.editor_insert_focus = False
                    self.editor_stage_col = tag[1]
                    self.editor_param_row = tag[2]
                    self.editor_unified_header_focus = False
                    stage_grid = self._stage_grid_for_channel(self._current_channel())
                    self.selected_stage_key = stage_grid[tag[1]][0]
                    self._press_unified_editor_cell()
                self._sync_from_engine()
                return
        self._sync_from_engine()

    def _on_editor_canvas_release(self, event) -> str:
        pending = getattr(self, "_group_assign_pending_tag", None)
        if pending is None:
            return "break"
        self._cancel_group_assign_hold()
        if not bool(getattr(self, "_group_assign_press_fired", False)):
            idx = int(pending)
            self.editor_top_focus = True
            self.editor_insert_focus = False
            self.top_control_focus = idx
            self._press_top_control()
            self._sync_from_engine()
        self._group_assign_press_fired = False
        self._group_assign_pending_tag = None
        return "break"

    def _cancel_group_assign_hold(self) -> None:
        after_id = getattr(self, "_group_assign_press_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self._group_assign_press_after_id = None

    def _maybe_start_group_assign_hold(self, idx: int) -> bool:
        idx = int(idx)
        if idx in (self.TOP_MASTER_VOL_INDEX, self.TOP_BANK_INDEX) or idx >= self.TOP_CHANNEL_CONTROL_COUNT:
            if bool(getattr(self, "group_assign_mode", False)) and idx == self.TOP_BANK_INDEX:
                self._exit_group_assign_mode()
                self._sync_from_engine()
                return True
            return False
        if bool(getattr(self, "group_assign_mode", False)):
            return False
        if getattr(self, "target_bank_mode", "ch") != "grp":
            return False
        group_idx = self._target_bank_offset("grp") + idx
        if group_idx >= self._target_count_for_mode("grp"):
            return False
        self._cancel_group_assign_hold()
        self._group_assign_pending_tag = idx
        self._group_assign_press_fired = False
        def _fire() -> None:
            self._group_assign_press_after_id = None
            self._group_assign_press_fired = True
            self._group_assign_pending_tag = None
            self._enter_group_assign_mode(group_idx)
            self._sync_from_engine()
        self._group_assign_press_after_id = self.root.after(650, _fire)
        return True

    def _on_editor_canvas_double_click(self, event) -> str:
        self.nav_scope = "editor"
        for x0, y0, x1, y1, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1 and tag == ("editor_top_circle", self.TOP_BANK_INDEX):
                self.editor_top_focus = True
                self.top_control_focus = self.TOP_BANK_INDEX
                self._cancel_bank_mouse_press()
                self._cycle_target_bank_mode(-1)
                self._sync_from_engine()
                return "break"
        return "break"

    # --- Interaction Logic ---
    def _open_stage_editor(self, idx: int, key: str) -> None:
        self._capture_editor_return_context()
        self.selected_channel = self.editor_channel = idx
        self.selected_stage_key, self.nav_scope = key, "editor"
        self.editor_top_focus = False
        self.editor_stage_col = next((i for i, r in enumerate(self._STAGE_GRID) if r[0]==key), 0)
        self.editor_param_row, self.editor_unified_header_focus = 0, True
        self._autosize_editor_canvas_height()
        self._sync_from_engine(); self.root.focus_set()

    def _capture_editor_return_context(self) -> None:
        self._editor_return_ctx = {"nav_scope": self.nav_scope, "console_row": self.console_row, "selected_channel": self.selected_channel}

    def _restore_editor_return_context(self) -> None:
        ctx = getattr(self, "_editor_return_ctx", None)
        if ctx: self.nav_scope, self.console_row, self.selected_channel = ctx["nav_scope"], ctx["console_row"], ctx["selected_channel"]
        else: self.nav_scope = "console"; self.console_row = "stages"
        self._sync_from_engine()

    def _exit_editor_to_console(self) -> None: self._restore_editor_return_context()
    def _exit_transport_to_console(self) -> None: self.nav_scope = "console"; self.console_row = "footer"; self._sync_from_engine()

    def _handle_twist_cw_editor_enter(self) -> None:
        if getattr(self, "nav_scope", "") == "console" and getattr(self, "console_row", "") == "stages":
            self._open_stage_editor(self.selected_channel, self.selected_stage_key)
            self._last_editor_toggle_at = time.time()

    def _handle_twist_ccw_editor_exit(self) -> None:
        if getattr(self, "nav_scope", "") == "editor":
            if time.time() - getattr(self, "_last_editor_toggle_at", 0) > 0.75:
                self._exit_editor_to_console()

    def _dyn_band_slot(self, ch: ChannelState, stage_key: str) -> int:
        count_attr = f"{stage_key}_dyn_band_count"
        ui_attr = f"{stage_key}_dyn_ui_band"
        raw_count = getattr(ch, count_attr, 1)
        raw_slot = getattr(ch, ui_attr, 0)
        if isinstance(raw_count, tuple):
            raw_count = raw_count[0] if raw_count else 1
        if isinstance(raw_slot, tuple):
            raw_slot = raw_slot[-1] if raw_slot else 0
        count = max(1, min(8, int(raw_count)))
        slot = max(0, min(count - 1, int(raw_slot)))
        setattr(ch, count_attr, count)
        setattr(ch, ui_attr, slot)
        return slot

    def _enable_stage_band(self, ch: ChannelState, stage_key: str, slot: int = 0, *, inherit_current: bool = True) -> None:
        if stage_key not in ("gate", "comp"):
            return
        count_attr = f"{stage_key}_dyn_band_count"
        ui_attr = f"{stage_key}_dyn_ui_band"
        bands = getattr(ch, f"{stage_key}_dyn_bands")
        count = max(int(getattr(ch, count_attr, 1)), slot + 1)
        count = max(1, min(8, count))
        slot = max(0, min(count - 1, slot))
        setattr(ch, f"{stage_key}_band_enabled", True)
        setattr(ch, count_attr, count)
        setattr(ch, ui_attr, slot)
        prefix = f"{stage_key}_"
        band = bands[slot]
        if inherit_current:
            freq = float(getattr(ch, prefix + "center_hz"))
            width = float(getattr(ch, prefix + "width_oct"))
            threshold = float(getattr(ch, prefix + "threshold_db"))
            ratio = float(getattr(ch, prefix + "ratio"))
            attack = float(getattr(ch, prefix + "attack_ms"))
            release = float(getattr(ch, prefix + "release_ms"))
            makeup = float(getattr(ch, prefix + "makeup"))
        else:
            base_freq = float(getattr(ch, prefix + "center_hz"))
            freq = base_freq * (1.75 ** max(1, slot))
            if freq > POL_HIGH_HZ:
                freq = base_freq / (1.75 ** max(1, slot))
            freq = float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ))
            width = 1.2 if stage_key == "gate" else 1.6
            threshold = -34.0 if stage_key == "gate" else -18.0
            ratio = 10.0 if stage_key == "gate" else 4.0
            attack = 3.0 if stage_key == "gate" else 8.0
            release = 140.0 if stage_key == "gate" else 120.0
            makeup = 1.0
        band.update(
            enabled=True,
            freq=freq,
            width_oct=width,
            threshold_db=threshold,
            ratio=ratio,
            attack_ms=attack,
            release_ms=release,
            makeup=makeup,
        )
        if stage_key == "gate":
            self.engine._hydrate_gate_dyn_to_scalars(ch)
        else:
            self.engine._hydrate_comp_dyn_to_scalars(ch)

    def _add_stage_band(self, ch: ChannelState, stage_key: str) -> None:
        if stage_key not in ("gate", "comp"):
            return
        count_attr = f"{stage_key}_dyn_band_count"
        count = max(1, min(8, int(getattr(ch, count_attr, 1))))
        slot = count if count < 8 else self._dyn_band_slot(ch, stage_key)
        self._enable_stage_band(ch, stage_key, slot, inherit_current=(slot == self._dyn_band_slot(ch, stage_key)))

    def _flush_eq_scalars_to_band(self, ch: ChannelState) -> None:
        if not getattr(ch, "eq_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "eq_ui_band", 0))))
        ch.eq_bands[slot].update(
            enabled=True,
            freq=float(ch.eq_freq),
            gain_db=float(ch.eq_gain_db),
            width=float(ch.eq_width),
            type="SHELF" if float(ch.eq_width) <= 0.1 else "BELL",
        )

    def _hydrate_eq_band_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "eq_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "eq_ui_band", 0))))
        b = ch.eq_bands[slot]
        if not b.get("enabled"):
            b.update(enabled=True, freq=float(ch.eq_freq), gain_db=float(ch.eq_gain_db), width=float(ch.eq_width), type="SHELF" if float(ch.eq_width) <= 0.1 else "BELL")
        ch.eq_freq = float(b.get("freq", ch.eq_freq))
        ch.eq_gain_db = float(b.get("gain_db", ch.eq_gain_db))
        ch.eq_width = float(b.get("width", ch.eq_width))
        ch.eq_type = str(b.get("type", "SHELF" if ch.eq_width <= 0.1 else "BELL"))

    def _add_eq_band(self, ch: ChannelState) -> None:
        count = max(1, min(8, int(getattr(ch, "eq_band_count", 1))))
        if not getattr(ch, "eq_band_enabled", False):
            ch.eq_band_enabled = True
            ch.eq_ui_band = 1
            ch.eq_band_count = 2
            ch.eq_bands[0].update(
                enabled=True,
                freq=float(ch.eq_freq),
                gain_db=float(ch.eq_gain_db),
                width=float(ch.eq_width),
                type="SHELF" if float(ch.eq_width) <= 0.1 else "BELL",
            )
            ch.eq_bands[1].update(
                enabled=True,
                freq=float(ch.eq_freq),
                gain_db=float(ch.eq_gain_db),
                width=float(ch.eq_width),
                type="SHELF" if float(ch.eq_width) <= 0.1 else "BELL",
            )
        elif count < 8:
            ch.eq_band_count = count + 1
            ch.eq_ui_band = count
        else:
            ch.eq_ui_band = (int(getattr(ch, "eq_ui_band", 0)) + 1) % count
        self._hydrate_eq_band_to_scalars(ch)

    def _flush_trn_scalars_to_band(self, ch: ChannelState) -> None:
        if not getattr(ch, "trn_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "trn_ui_band", 0))))
        ch.trn_bands[slot].update(
            enabled=True,
            freq=float(ch.trn_freq),
            width=float(ch.trn_width),
            attack=float(ch.trn_attack),
            sustain=float(ch.trn_sustain),
            drive=float(ch.trn_drive),
        )

    def _hydrate_trn_band_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "trn_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "trn_ui_band", 0))))
        b = ch.trn_bands[slot]
        if not b.get("enabled"):
            b.update(enabled=True, freq=float(ch.trn_freq), width=float(ch.trn_width), attack=float(ch.trn_attack), sustain=float(ch.trn_sustain), drive=float(ch.trn_drive))
        ch.trn_freq = float(b.get("freq", ch.trn_freq))
        ch.trn_width = float(b.get("width", ch.trn_width))
        ch.trn_attack = float(b.get("attack", ch.trn_attack))
        ch.trn_sustain = float(b.get("sustain", ch.trn_sustain))
        ch.trn_drive = float(b.get("drive", ch.trn_drive))

    def _add_trn_band(self, ch: ChannelState) -> None:
        count = max(1, min(8, int(getattr(ch, "trn_band_count", 1))))
        if not getattr(ch, "trn_band_enabled", False):
            ch.trn_band_enabled = True
            ch.trn_band_count = 2
            ch.trn_ui_band = 1
            for slot in (0, 1):
                ch.trn_bands[slot].update(enabled=True, freq=float(ch.trn_freq), width=float(ch.trn_width), attack=float(ch.trn_attack), sustain=float(ch.trn_sustain), drive=float(ch.trn_drive))
        elif count < 8:
            self._flush_trn_scalars_to_band(ch)
            ch.trn_band_count = count + 1
            ch.trn_ui_band = count
            ch.trn_bands[count].update(enabled=True, freq=float(ch.trn_freq), width=float(ch.trn_width), attack=float(ch.trn_attack), sustain=float(ch.trn_sustain), drive=float(ch.trn_drive))
        else:
            self._flush_trn_scalars_to_band(ch)
            ch.trn_ui_band = min(count - 1, int(getattr(ch, "trn_ui_band", 0)) + 1)
        self._hydrate_trn_band_to_scalars(ch)

    def _flush_xct_scalars_to_band(self, ch: ChannelState) -> None:
        if not getattr(ch, "xct_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "xct_ui_band", 0))))
        ch.xct_bands[slot].update(
            enabled=True,
            freq=float(ch.xct_freq),
            width=float(ch.xct_width),
            attack=float(ch.xct_attack),
            sustain=float(ch.xct_sustain),
            drive=float(ch.xct_drive),
        )

    def _hydrate_xct_band_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "xct_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "xct_ui_band", 0))))
        b = ch.xct_bands[slot]
        if not b.get("enabled"):
            b.update(enabled=True, freq=float(ch.xct_freq), width=float(ch.xct_width), attack=float(ch.xct_attack), sustain=float(ch.xct_sustain), drive=float(ch.xct_drive))
        ch.xct_freq = float(b.get("freq", ch.xct_freq))
        ch.xct_width = float(b.get("width", ch.xct_width))
        ch.xct_attack = float(b.get("attack", ch.xct_attack))
        ch.xct_sustain = float(b.get("sustain", ch.xct_sustain))
        ch.xct_drive = float(b.get("drive", ch.xct_drive))

    def _add_xct_band(self, ch: ChannelState) -> None:
        count = max(1, min(8, int(getattr(ch, "xct_band_count", 1))))
        if not getattr(ch, "xct_band_enabled", False):
            ch.xct_band_enabled = True
            ch.xct_band_count = 2
            ch.xct_ui_band = 1
            for slot in (0, 1):
                ch.xct_bands[slot].update(enabled=True, freq=float(ch.xct_freq), width=float(ch.xct_width), attack=float(ch.xct_attack), sustain=float(ch.xct_sustain), drive=float(ch.xct_drive))
        elif count < 8:
            self._flush_xct_scalars_to_band(ch)
            ch.xct_band_count = count + 1
            ch.xct_ui_band = count
            ch.xct_bands[count].update(enabled=True, freq=float(ch.xct_freq), width=float(ch.xct_width), attack=float(ch.xct_attack), sustain=float(ch.xct_sustain), drive=float(ch.xct_drive))
        else:
            self._flush_xct_scalars_to_band(ch)
            ch.xct_ui_band = min(count - 1, int(getattr(ch, "xct_ui_band", 0)) + 1)
        self._hydrate_xct_band_to_scalars(ch)

    def _flush_tbe_scalars_to_band(self, ch: ChannelState) -> None:
        if not getattr(ch, "tbe_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "tbe_ui_band", 0))))
        ch.tbe_bands[slot].update(enabled=True, freq=float(ch.tbe_freq), width=float(ch.tbe_width), drive=float(ch.tbe_drive))

    def _hydrate_tbe_band_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "tbe_band_enabled", False):
            return
        slot = max(0, min(7, int(getattr(ch, "tbe_ui_band", 0))))
        b = ch.tbe_bands[slot]
        if not b.get("enabled"):
            b.update(enabled=True, freq=float(ch.tbe_freq), width=float(ch.tbe_width), drive=float(ch.tbe_drive))
        ch.tbe_freq = float(b.get("freq", ch.tbe_freq))
        ch.tbe_width = float(b.get("width", ch.tbe_width))
        ch.tbe_drive = float(b.get("drive", ch.tbe_drive))

    def _add_tbe_band(self, ch: ChannelState) -> None:
        count = max(1, min(8, int(getattr(ch, "tbe_band_count", 1))))
        if not getattr(ch, "tbe_band_enabled", False):
            ch.tbe_band_enabled = True
            ch.tbe_band_count = 2
            ch.tbe_ui_band = 1
            for slot in (0, 1):
                ch.tbe_bands[slot].update(enabled=True, freq=float(ch.tbe_freq), width=float(ch.tbe_width), drive=float(ch.tbe_drive))
        elif count < 8:
            self._flush_tbe_scalars_to_band(ch)
            ch.tbe_band_count = count + 1
            ch.tbe_ui_band = count
            ch.tbe_bands[count].update(enabled=True, freq=float(ch.tbe_freq), width=float(ch.tbe_width), drive=float(ch.tbe_drive))
        else:
            self._flush_tbe_scalars_to_band(ch)
            ch.tbe_ui_band = min(count - 1, int(getattr(ch, "tbe_ui_band", 0)) + 1)
        self._hydrate_tbe_band_to_scalars(ch)

    def _handle_unified_editor_nav(self, target: str) -> None:
        stage_grid = self._stage_grid_for_channel(self._current_channel())
        focus_col = max(0, min(len(stage_grid) - 1, getattr(self, "editor_stage_col", 0)))
        self.editor_stage_col = focus_col
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        top_focus = bool(getattr(self, "editor_top_focus", False))
        insert_focus = bool(getattr(self, "editor_insert_focus", False))
        params = stage_grid[focus_col][2]
        
        if target == "up":
            if top_focus:
                pass
            elif hdr_focus:
                self.editor_top_focus = True
            else:
                self.editor_unified_header_focus = True
        elif target == "down":
            if top_focus:
                self.editor_top_focus = False
                self.editor_unified_header_focus = True
            elif hdr_focus:
                self.editor_insert_focus = False
                self.editor_unified_header_focus = False
                if params and params[0] == "TBE" and len(params) > 1:
                    self.editor_param_row = 1
            else:
                # Dive into transport
                self.nav_scope = "transport"
                self.transport_focus_row = 0
                self.transport_focus_col = focus_param % self.TRANSPORT_COLS
        elif target == "left":
            if top_focus:
                self.top_control_focus = (int(getattr(self, "top_control_focus", 0)) - 1) % self.TOP_CONTROL_COUNT
                self._select_top_control_channel()
            elif hdr_focus:
                if insert_focus:
                    self.editor_insert_focus = False
                    self.editor_stage_col = len(stage_grid) - 1
                elif focus_col == 0:
                    self.editor_insert_focus = True
                else:
                    self.editor_stage_col = focus_col - 1
                self.editor_param_row = 0
                if not self.editor_insert_focus:
                    self.selected_stage_key = stage_grid[self.editor_stage_col][0]
            else:
                self.editor_param_row = (focus_param - 1) % len(params)
        elif target == "right":
            if top_focus:
                self.top_control_focus = (int(getattr(self, "top_control_focus", 0)) + 1) % self.TOP_CONTROL_COUNT
                self._select_top_control_channel()
            elif hdr_focus:
                if insert_focus:
                    self.editor_insert_focus = False
                    self.editor_stage_col = 0
                elif focus_col >= len(stage_grid) - 1:
                    self.editor_insert_focus = True
                else:
                    self.editor_stage_col = focus_col + 1
                self.editor_param_row = 0
                if not self.editor_insert_focus:
                    self.selected_stage_key = stage_grid[self.editor_stage_col][0]
            else:
                self.editor_param_row = (focus_param + 1) % len(params)
        elif target == "press":
            if top_focus:
                self._press_top_control()
            elif insert_focus:
                pass
            else:
                self._press_unified_editor_cell()
        elif target == "back":
            if top_focus and int(getattr(self, "top_control_focus", 0)) == self.TOP_BANK_INDEX:
                self._cycle_target_bank_mode(-1)
                _log.info(f"BNK_BACK: target_mode={getattr(self, 'target_bank_mode', 'ch')} offset={self._target_bank_offset()}")
            else:
                self._exit_editor_to_console()
        self._sync_from_engine()

    def _press_unified_editor_cell(self) -> None:
        ch = self._current_channel()
        stage_grid = self._stage_grid_for_channel(ch)
        focus_col = max(0, min(len(stage_grid) - 1, getattr(self, "editor_stage_col", 0)))
        self.editor_stage_col = focus_col
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        stage_key, _hdr, params = stage_grid[focus_col]
        focus_param = max(0, min(len(params) - 1, focus_param))
        self.editor_param_row = focus_param
        label = params[focus_param]
        
        with self.engine._lock:
            # Visual feedback
            self.editor_title.config(fg="#6ff0c1")
            self.root.after(100, lambda: self.editor_title.config(fg="white"))
            
            if hdr_focus:
                if ch is self.engine.master_channel and stage_key == "pre":
                    self._sync_from_engine()
                    return
                attr = f"{stage_key}_enabled"
                if stage_key == "harm": attr = "harmonics_enabled"
                if hasattr(ch, attr):
                    new_enabled = not bool(getattr(ch, attr))
                    setattr(ch, attr, new_enabled)
                    if stage_key == "xct" and new_enabled and float(getattr(ch, "xct_drive", 0.0)) <= 0.01:
                        ch.xct_drive = 0.45
                        ch.xct_attack = 0.25
                        ch.xct_sustain = 0.15
                    if stage_key == "tbe" and new_enabled and float(getattr(ch, "tbe_drive", 0.0)) <= 0.01:
                        ch.tbe_drive = 0.35
            else:
                if stage_key in ("gate", "comp") and label == "FRQ":
                    bp_key = "gate_param_bypass" if stage_key == "gate" else "comp_param_bypass"
                    bp = getattr(ch, bp_key, {})
                    if bool(getattr(ch, f"{stage_key}_band_enabled", False)):
                        setattr(ch, f"{stage_key}_band_enabled", False)
                        for band in getattr(ch, f"{stage_key}_dyn_bands"):
                            band["enabled"] = False
                    else:
                        bp["FRQ"] = False
                        setattr(ch, bp_key, bp)
                        self._enable_stage_band(ch, stage_key, 0)
                    self._sync_from_engine()
                    return
                if stage_key == "eq" and label == "BND":
                    self._add_eq_band(ch)
                    self._sync_from_engine()
                    return
                if stage_key == "trn" and label == "BND":
                    self._add_trn_band(ch)
                    bp = getattr(ch, "trn_param_bypass", {})
                    bp["BND"] = False
                    setattr(ch, "trn_param_bypass", bp)
                    self._sync_from_engine()
                    return
                if stage_key == "xct" and label == "BND":
                    self._add_xct_band(ch)
                    bp = getattr(ch, "xct_param_bypass", {})
                    bp["BND"] = False
                    setattr(ch, "xct_param_bypass", bp)
                    self._sync_from_engine()
                    return
                if stage_key == "tbe" and label == "BND":
                    self._add_tbe_band(ch)
                    bp = getattr(ch, "tbe_param_bypass", {})
                    bp["BND"] = False
                    setattr(ch, "tbe_param_bypass", bp)
                    self._sync_from_engine()
                    return
                m = {
                    "TBE": "tube" if stage_key == "pre" else f"{stage_key}_tube",
                    "LPF": "lpf_enabled", "HPF": "hpf_enabled",
                    "48V": "phantom", "PHS": "phase",
                    "BD2": "limit_band_enabled"
                }
                attr = m.get(label)
                if attr and hasattr(ch, attr):
                    new_value = not bool(getattr(ch, attr))
                    setattr(ch, attr, new_value)
                    if stage_key == "gate" and label == "BND" and new_value:
                        band = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count) - 1, int(ch.gate_dyn_ui_band)))]
                        band.update(
                            enabled=True,
                            freq=float(ch.gate_center_hz),
                            width_oct=float(ch.gate_width_oct),
                            threshold_db=float(ch.gate_threshold_db),
                            ratio=float(ch.gate_ratio),
                            attack_ms=float(ch.gate_attack_ms),
                            release_ms=float(ch.gate_release_ms),
                            makeup=float(ch.gate_makeup),
                        )
                else:
                    m_bp = {"gate": "gate_param_bypass", "comp": "comp_param_bypass", "eq": "eq_param_bypass",
                            "harm": "harm_param_bypass", "trn": "trn_param_bypass", "xct": "xct_param_bypass", "tbe": "tbe_param_bypass"}
                    bp_key = m_bp.get(stage_key)
                    if bp_key:
                        bp = getattr(ch, bp_key, {})
                        bp[label] = not bp.get(label, False)
                        setattr(ch, bp_key, bp)
        self._sync_from_engine()

    def _adjust_unified_editor_cell(self, axis_value: float) -> None:
        raw_axis = float(axis_value)
        if abs(raw_axis) < DISCRETE_TWIST_MIN:
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_editor_adjust_at", 0.0)) < 0.075:
            return
        self._last_editor_adjust_at = now
        axis_value = 0.34 if raw_axis > 0 else -0.34
        if bool(getattr(self, "editor_top_focus", False)):
            self._adjust_top_fader_circle(axis_value)
            return
        ch = self._current_channel()
        stage_grid = self._stage_grid_for_channel(ch)
        col = max(0, min(len(stage_grid) - 1, self.editor_stage_col))
        self.editor_stage_col = col
        sk, _, params = stage_grid[col]
        if getattr(self, "editor_unified_header_focus", False):
            if ch is self.engine.master_channel and sk == "pre":
                return
            if sk != "pre":
                _log.info("ADJUST: Bail (header focus)")
                return
            with self.engine._lock:
                ch.pre_enabled = True
                ch.pre_gain_db = float(np.clip(getattr(ch, "pre_gain_db", 0.0) + axis_value * 1.0, -24.0, 24.0))
                ch.pre_squeeze = float(np.clip(1.0 + max(0.0, abs(ch.pre_gain_db)) / 6.0, 1.0, 8.0))
            self._sync_from_engine()
            return
        row = max(0, min(len(params) - 1, self.editor_param_row)); label = params[row]
        _log.info(f"ADJUST: Trying {sk}:{label}")
        if sk in ("gate", "comp") and label == "BND":
            with self.engine._lock:
                if not bool(getattr(ch, f"{sk}_band_enabled", False)):
                    self._enable_stage_band(ch, sk, 0)
                else:
                    count = max(1, min(8, int(getattr(ch, f"{sk}_dyn_band_count", 1))))
                    cur = self._dyn_band_slot(ch, sk)
                    nxt = max(0, min(count - 1, cur + (1 if axis_value > 0 else -1)))
                    setattr(ch, f"{sk}_dyn_ui_band", nxt)
                    if sk == "gate":
                        self.engine._hydrate_gate_dyn_to_scalars(ch)
                    else:
                        self.engine._hydrate_comp_dyn_to_scalars(ch)
            self._sync_from_engine()
            return
        if sk == "eq" and label == "BND":
            with self.engine._lock:
                if not bool(getattr(ch, "eq_band_enabled", False)):
                    self._add_eq_band(ch)
                else:
                    count = max(1, min(8, int(getattr(ch, "eq_band_count", 1))))
                    cur = max(0, min(count - 1, int(getattr(ch, "eq_ui_band", 0))))
                    ch.eq_ui_band = max(0, min(count - 1, cur + (1 if axis_value > 0 else -1)))
                    self._hydrate_eq_band_to_scalars(ch)
            self._sync_from_engine()
            return
        if sk == "trn" and label == "BND":
            with self.engine._lock:
                if not bool(getattr(ch, "trn_band_enabled", False)):
                    self._add_trn_band(ch)
                else:
                    self._flush_trn_scalars_to_band(ch)
                    count = max(1, min(8, int(getattr(ch, "trn_band_count", 1))))
                    cur = max(0, min(count - 1, int(getattr(ch, "trn_ui_band", 0))))
                    ch.trn_ui_band = max(0, min(count - 1, cur + (1 if axis_value > 0 else -1)))
                    self._hydrate_trn_band_to_scalars(ch)
            self._sync_from_engine()
            return
        if sk == "xct" and label == "BND":
            with self.engine._lock:
                if not bool(getattr(ch, "xct_band_enabled", False)):
                    self._add_xct_band(ch)
                else:
                    self._flush_xct_scalars_to_band(ch)
                    count = max(1, min(8, int(getattr(ch, "xct_band_count", 1))))
                    cur = max(0, min(count - 1, int(getattr(ch, "xct_ui_band", 0))))
                    ch.xct_ui_band = max(0, min(count - 1, cur + (1 if axis_value > 0 else -1)))
                    self._hydrate_xct_band_to_scalars(ch)
            self._sync_from_engine()
            return
        if sk == "tbe" and label == "BND":
            with self.engine._lock:
                if not bool(getattr(ch, "tbe_band_enabled", False)):
                    self._add_tbe_band(ch)
                else:
                    self._flush_tbe_scalars_to_band(ch)
                    count = max(1, min(8, int(getattr(ch, "tbe_band_count", 1))))
                    cur = max(0, min(count - 1, int(getattr(ch, "tbe_ui_band", 0))))
                    ch.tbe_ui_band = max(0, min(count - 1, cur + (1 if axis_value > 0 else -1)))
                    self._hydrate_tbe_band_to_scalars(ch)
            self._sync_from_engine()
            return
        
        spec_table = {
            ("pre",  "LPF"): ("lpf_hz", "log", 200.0, 22000.0, 0.1),
            ("pre",  "HPF"): ("hpf_hz", "log", 20.0, 1500.0, 0.1),
            ("harm", "H1"): ("harmonics[0]", "lin", 0.0, 1.0, 0.1),
            ("harm", "H2"): ("harmonics[1]", "lin", 0.0, 1.0, 0.1),
            ("harm", "H3"): ("harmonics[2]", "lin", 0.0, 1.0, 0.1),
            ("harm", "H4"): ("harmonics[3]", "lin", 0.0, 1.0, 0.1),
            ("harm", "H5"): ("harmonics[4]", "lin", 0.0, 1.0, 0.1),
            ("harm", "GAN"): ("harmonic_makeup", "lin", 0.0, 4.0, 0.1),
            ("gate", "THR"): ("gate_threshold_db", "lin", -60.0, 12.0, 0.3),
            ("gate", "DEP"): ("gate_ratio", "lin", 1.0, 20.0, 0.3),
            ("gate", "ATK"): ("gate_attack_ms", "log", 0.1, 500.0, 0.1),
            ("gate", "RLS"): ("gate_release_ms", "log", 10.0, 2000.0, 0.1),
            ("gate", "GAN"): ("gate_makeup", "lin", 0.0, 4.0, 0.1),
            ("gate", "FRQ"): ("gate_center_hz", "log", 20.0, 20000.0, 0.1),
            ("gate", "WDT"): ("gate_width_oct", "lin", 0.1, 6.0, 0.1),
            ("comp", "THR"): ("comp_threshold_db", "lin", -60.0, 12.0, 0.3),
            ("comp", "RAT"): ("comp_ratio", "lin", 1.0, 20.0, 0.3),
            ("comp", "ATK"): ("comp_attack_ms", "log", 0.1, 500.0, 0.1),
            ("comp", "RLS"): ("comp_release_ms", "log", 10.0, 2000.0, 0.1),
            ("comp", "GAN"): ("comp_makeup", "lin", 0.0, 4.0, 0.1),
            ("comp", "FRQ"): ("comp_center_hz", "log", 20.0, 20000.0, 0.1),
            ("comp", "WDT"): ("comp_width_oct", "lin", 0.1, 6.0, 0.1),
            ("eq",   "FRQ"): ("eq_freq", "log", 20.0, 22000.0, 0.1),
            ("eq",   "GAN"): ("eq_gain_db", "lin", -24.0, 24.0, 0.3),
            ("eq",   "SHP"): ("eq_width", "lin", 0.0, 6.0, 0.1),
            ("trn",  "FRQ"): ("trn_freq", "log", 20.0, 20000.0, 0.1),
            ("trn",  "ATK"): ("trn_attack", "lin", -1.0, 1.0, 0.1),
            ("trn",  "SUT"): ("trn_sustain", "lin", -1.0, 1.0, 0.1),
            ("trn",  "DRV"): ("trn_drive", "lin", 0.0, 1.0, 0.1),
            ("xct",  "FRQ"): ("xct_freq", "log", 20.0, 20000.0, 0.1),
            ("xct",  "ATK"): ("xct_attack", "lin", -1.0, 1.0, 0.1),
            ("xct",  "SUT"): ("xct_sustain", "lin", -1.0, 1.0, 0.1),
            ("xct",  "DRV"): ("xct_drive", "lin", 0.0, 1.0, 0.1),
            ("tbe",  "FRQ"): ("tbe_freq", "log", 20.0, 20000.0, 0.1),
            ("tbe",  "DRV"): ("tbe_drive", "lin", 0.0, 1.0, 0.1),
        }
        spec = spec_table.get((sk, label))
        if not spec: return
        attr, kind, lo, hi, step = spec
        with self.engine._lock:
            if "[" in attr: # Handling Harmonics array access
                base, idx = attr[:-1].split("[")
                arr = getattr(ch, base); cur = float(arr[int(idx)])
                new = cur + axis_value * step
                arr[int(idx)] = float(np.clip(new, lo, hi))
            else:
                cur = float(getattr(ch, attr))
                if kind == "log": new = cur * math.exp(axis_value * math.log(1.0 + step))
                else: new = cur + axis_value * step * (hi - lo) / 4.0 
                final = float(np.clip(new, lo, hi))
                setattr(ch, attr, final)
                if sk == "gate":
                    if label in ("THR", "DEP", "RAT", "ATK", "RLS", "GAN"):
                        self.engine.write_gate_dynamics(
                            ch,
                            ch.gate_threshold_db,
                            ch.gate_ratio,
                            ch.gate_attack_ms,
                            ch.gate_release_ms,
                            ch.gate_makeup,
                        )
                    elif label in ("FRQ", "WDT"):
                        self.engine._flush_gate_scalars_to_dyn_band(ch)
                elif sk == "comp":
                    if label in ("THR", "RAT", "ATK", "RLS", "GAN"):
                        self.engine.write_comp_dynamics(
                            ch,
                            ch.comp_threshold_db,
                            ch.comp_ratio,
                            ch.comp_attack_ms,
                            ch.comp_release_ms,
                            ch.comp_makeup,
                        )
                    elif label in ("FRQ", "WDT"):
                        self.engine._flush_comp_scalars_to_dyn_band(ch)
                elif sk == "eq":
                    if label in ("FRQ", "GAN", "SHP"):
                        ch.eq_type = "SHELF" if float(ch.eq_width) <= 0.1 else "BELL"
                        self._flush_eq_scalars_to_band(ch)
                elif sk == "trn":
                    if label in ("FRQ", "ATK", "SUT", "DRV"):
                        self._flush_trn_scalars_to_band(ch)
                elif sk == "xct":
                    if label in ("FRQ", "ATK", "SUT", "DRV"):
                        self._flush_xct_scalars_to_band(ch)
                elif sk == "tbe":
                    if label in ("FRQ", "DRV"):
                        self._flush_tbe_scalars_to_band(ch)
                _log.info(f"ADJUST: {sk}:{label} -> {final:.4f} (ax={axis_value:.2f})")
        self._sync_from_engine()

    def _adjust_focused_axis(self, axis_value: float) -> None:
        ns = getattr(self, "nav_scope", "console")
        if ns == "transport":
            self._adjust_transport_axis(axis_value)
        elif ns == "timeline":
            self._adjust_timeline_axis(axis_value)
        elif ns == "console":
            self._adjust_console_channel_axis(axis_value)
        else:
            self._adjust_unified_editor_cell(axis_value)

    def _adjust_timeline_axis(self, axis_value: float) -> None:
        if abs(axis_value) < DISCRETE_TWIST_MIN:
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_transport_adjust_at", 0.0)) < 0.055:
            return
        last_at = float(getattr(self, "_last_transport_adjust_at", 0.0))
        self._last_transport_adjust_at = now
        direction = 1 if axis_value > 0 else -1
        if direction == int(getattr(self, "_transport_adjust_dir", 0)) and now - last_at < 0.45:
            self._transport_adjust_count = min(14, int(getattr(self, "_transport_adjust_count", 0)) + 1)
        else:
            self._transport_adjust_count = 1
            self._transport_adjust_dir = direction
        seconds = 0.035 * (1.20 ** max(0, int(getattr(self, "_transport_adjust_count", 1)) - 1))
        item = self._selected_timeline_item()
        if item and item["kind"] == "marker":
            idx = int(item["original_idx"])
            markers = getattr(self.engine, "markers", [])
            duration = max(0.01, float(self.engine.timeline_duration_seconds()))
            if 0 <= idx < len(markers):
                self._push_edit_undo("move marker")
                markers[idx] = float(np.clip(float(markers[idx]) + seconds * direction, 0.0, duration))
                self.engine.seek_seconds(markers[idx])
                self._audition_scrub_motion(220, freeze_playhead=True)
        else:
            self._release_timeline_selection_for_transport(2.5)
            if direction > 0:
                self.engine.jump_forward(seconds)
            else:
                self.engine.jump_back(seconds)
            self._audition_scrub_motion(220, freeze_playhead=True)
        self._flash_transport_action("timeline")
        self._sync_from_engine()

    def _adjust_transport_axis(self, axis_value: float) -> None:
        if abs(axis_value) < DISCRETE_TWIST_MIN:
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_transport_adjust_at", 0.0)) < 0.09:
            return
        last_at = float(getattr(self, "_last_transport_adjust_at", 0.0))
        self._last_transport_adjust_at = now
        direction = 1 if axis_value > 0 else -1
        if direction == int(getattr(self, "_transport_adjust_dir", 0)) and now - last_at < 0.45:
            self._transport_adjust_count = min(12, int(getattr(self, "_transport_adjust_count", 0)) + 1)
        else:
            self._transport_adjust_count = 1
            self._transport_adjust_dir = direction
        axis_value = float(np.clip(axis_value, -1.0, 1.0)) * 0.28
        tr = getattr(self, "transport_focus_row", 0)
        tc = getattr(self, "transport_focus_col", 0)
        btn = self._transport_button_at(tr, tc)
        if not btn:
            return
        action = btn[0]
        if action == "advance":
            seconds = 0.35 * (1.45 ** max(0, int(getattr(self, "_transport_adjust_count", 1)) - 1))
            self._release_timeline_selection_for_transport(2.0)
            if direction > 0:
                self.engine.jump_forward(seconds)
            else:
                self.engine.jump_back(seconds)
            self._flash_transport_action("advance")
            self._sync_from_engine()
            return
        if action in ("shuttle", "shuttle_scrub"):
            mode = getattr(self, "_shuttle_scrub_mode", "scrub") if action == "shuttle_scrub" else "shuttle"
            base = 0.04 if mode == "scrub" else 1.0
            accel = 1.20 if mode == "scrub" else 1.55
            seconds = base * (accel ** max(0, int(getattr(self, "_transport_adjust_count", 1)) - 1))
            self._release_timeline_selection_for_transport(2.5)
            if direction > 0:
                self.engine.jump_forward(seconds)
            else:
                self.engine.jump_back(seconds)
            self._audition_scrub_motion(320 if mode == "shuttle" else 220, freeze_playhead=(mode == "scrub"))
            self._flash_transport_action(action)
            self._sync_from_engine()
            return
        if action == "scrub":
            seconds = 0.04 * (1.22 ** max(0, int(getattr(self, "_transport_adjust_count", 1)) - 1))
            self._release_timeline_selection_for_transport(2.5)
            if direction > 0:
                self.engine.jump_forward(seconds)
            else:
                self.engine.jump_back(seconds)
            self._audition_scrub_motion(220, freeze_playhead=True)
            self._flash_transport_action("scrub")
            self._sync_from_engine()
            return
        if action == "channel_pan":
            ch = self._current_channel()
            if ch is not self.engine.master_channel:
                ch.pan = float(np.clip(float(getattr(ch, "pan", 0.0)) + direction * 0.02, -1.0, 1.0))
            self._sync_from_engine()
            return
        if action == "zoom":
            cur = float(getattr(self.engine, "timeline_zoom", 1.0))
            self.engine.timeline_zoom = float(np.clip(cur * (1.18 if direction > 0 else 1.0 / 1.18), 1.0, 32.0))
            self._sync_from_engine()
            return
        if action == "undo":
            if direction < 0:
                self._restore_edit_undo()
            else:
                self._restore_edit_redo()
            self._flash_transport_action("undo")
            self._sync_from_engine()
            return
        if action == "prepost":
            attr = "pre_roll_seconds" if getattr(self, "_prepost_focus", "pre") == "pre" else "post_roll_seconds"
            cur = float(getattr(self.engine, attr, 0.0))
            setattr(self.engine, attr, float(np.clip(cur + direction * 0.25, 0.0, 30.0)))
            self._sync_from_engine()
            return
        if action != "oscillator" and getattr(self.engine, "generator_mode", "none") != "osc":
            return
        with self.engine._lock:
            self.engine.generator_mode = "osc"
            cur = float(np.clip(getattr(self.engine, "osc_hz", 440.0), POL_LOW_HZ, POL_HIGH_HZ))
            new = cur * math.exp(axis_value * math.log(1.18))
            self.engine.osc_hz = float(np.clip(new, POL_LOW_HZ, POL_HIGH_HZ))
        self._sync_from_engine()

    def _adjust_console_channel_axis(self, val: float) -> None:
        if abs(val) < DISCRETE_TWIST_MIN: return
        now = time.monotonic()
        if now - float(getattr(self, "_last_console_adjust_at", 0.0)) < 0.24:
            return
        self._last_console_adjust_at = now
        if self._is_master_nav_index(self.selected_channel):
            direction = self._fader_value_direction(val)
            new_gain = float(np.clip(float(getattr(self.engine, "master_gain", 1.0)) + direction * 0.04, 0.0, 2.2))
            self.engine.master_gain = new_gain
            self.engine.master_channel.gain = new_gain
            self._sync_from_engine()
            return
        if getattr(self, "console_row", "") == "top":
            self._adjust_top_fader_circle(val)
            return
        self.selected_channel = (self.selected_channel + (1 if val > 0 else -1)) % self._channel_nav_span()
        self._sync_from_engine()

    # --- Helpers ---
    def _max_fader_bank_offset(self) -> int:
        strip_count = min(len(self.engine.channels), self.TOP_CHANNEL_CONTROL_COUNT)
        return max(0, strip_count - self.TOP_CHANNEL_CONTROL_COUNT)

    def _select_top_control_channel(self) -> None:
        idx = int(getattr(self, "top_control_focus", 0))
        if idx == self.TOP_MASTER_VOL_INDEX:
            self.selected_channel = self.editor_channel = self._master_nav_index()
            return
        if idx >= self.TOP_CHANNEL_CONTROL_COUNT:
            return
        mode = getattr(self, "target_bank_mode", "ch")
        mapped_idx = self._target_bank_offset(mode) + idx
        if 0 <= mapped_idx < self._target_count_for_mode(mode):
            self.selected_channel = self.editor_channel = mapped_idx

    def _press_top_control(self) -> None:
        idx = int(getattr(self, "top_control_focus", 0))
        if bool(getattr(self, "group_assign_mode", False)):
            if idx == self.TOP_BANK_INDEX:
                self._exit_group_assign_mode()
                return
            if 0 <= idx < self.TOP_CHANNEL_CONTROL_COUNT:
                channel_idx = self._target_bank_offset("ch") + idx
                self._toggle_channel_group_assignment(channel_idx)
                self.selected_channel = self.editor_channel = channel_idx
                return
        if idx == self.TOP_MASTER_VOL_INDEX:
            self.selected_channel = self.editor_channel = self._master_nav_index()
            return
        if idx == self.TOP_BANK_INDEX:
            self._cycle_target_bank_mode(1)
            _log.info(f"BNK_PRESS: target_mode={getattr(self, 'target_bank_mode', 'ch')} offset={self._target_bank_offset()}")
            return
        if getattr(self, "target_bank_mode", "ch") != "ch":
            if getattr(self, "target_bank_mode", "ch") == "grp" and 0 <= idx < self.TOP_CHANNEL_CONTROL_COUNT:
                group_idx = self._target_bank_offset("grp") + idx
                if group_idx < self._target_count_for_mode("grp"):
                    self._enter_group_assign_mode(group_idx)
                    return
            self.fader_layer = 0
            self.knobs_send_mode = False
            self._select_top_control_channel()
            return
        self._set_fader_layer_for_control(idx)

    def _cancel_bank_mouse_press(self) -> None:
        after_id = getattr(self, "_bank_click_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self._bank_click_after_id = None

    def _schedule_bank_mouse_press(self) -> None:
        self._cancel_bank_mouse_press()
        def _run() -> None:
            self._bank_click_after_id = None
            self._adjust_fader_bank(12)
            self._sync_from_engine()
        self._bank_click_after_id = self.root.after(260, _run)
        self._sync_from_engine()

    def _adjust_fader_bank(self, delta: int) -> None:
        mode = getattr(self, "target_bank_mode", "ch")
        self._set_target_bank_offset(mode, self._target_bank_offset(mode) + int(delta))
        self._select_top_control_channel()

    def _set_fader_layer_for_control(self, control_idx: int) -> None:
        send_slot = int(control_idx) + 1
        if send_slot < 1 or send_slot > self.SEND_SLOT_COUNT:
            self.fader_layer = 0
        elif int(getattr(self, "fader_layer", 0)) == send_slot:
            self.fader_layer = 0
        else:
            self.fader_layer = send_slot
        self.knobs_send_mode = self.fader_layer > 0
        for ch in self.engine.channels:
            ch.send_slot = max(1, int(self.fader_layer or 1))
            if self.fader_layer > 0:
                ch.send_level = self._channel_send_level(ch, self.fader_layer)

    def _channel_send_level(self, ch: Optional[ChannelState], slot: int) -> float:
        if ch is None:
            return 0.0
        levels = getattr(ch, "send_levels", None)
        if not isinstance(levels, list) or len(levels) < self.SEND_SLOT_COUNT:
            base = float(np.clip(getattr(ch, "send_level", 0.0), 0.0, 1.0))
            levels = [base for _ in range(self.SEND_SLOT_COUNT)]
            ch.send_levels = levels
        idx = max(0, min(self.SEND_SLOT_COUNT - 1, int(slot) - 1))
        return float(np.clip(levels[idx], 0.0, 1.0))

    def _set_channel_send_level(self, ch: ChannelState, slot: int, value: float) -> None:
        levels = getattr(ch, "send_levels", None)
        if not isinstance(levels, list) or len(levels) < self.SEND_SLOT_COUNT:
            levels = [float(np.clip(getattr(ch, "send_level", 0.0), 0.0, 1.0)) for _ in range(self.SEND_SLOT_COUNT)]
            ch.send_levels = levels
        idx = max(0, min(self.SEND_SLOT_COUNT - 1, int(slot) - 1))
        levels[idx] = float(np.clip(value, 0.0, 1.0))
        ch.send_slot = idx + 1
        ch.send_level = levels[idx]

    def _fader_value_direction(self, axis_value: float) -> int:
        # Single source of truth for every fader-like value adjustment.
        # SpaceMouse clockwise/left turn arrives as a positive axis value here.
        # Clockwise raises fader/send/master level; counterclockwise lowers it.
        return 1 if float(axis_value) > 0 else -1

    def _adjust_top_fader_circle(self, val: float) -> None:
        value_direction = self._fader_value_direction(val)
        bank_direction = 1 if val > 0 else -1
        idx = int(np.clip(getattr(self, "top_control_focus", getattr(self, "selected_channel", 0)), 0, self.TOP_CONTROL_COUNT - 1))
        if idx == self.TOP_BANK_INDEX:
            self._adjust_fader_bank(bank_direction)
            self._sync_from_engine()
            return
        if idx == self.TOP_MASTER_VOL_INDEX:
            new_gain = float(np.clip(float(getattr(self.engine, "master_gain", 1.0)) + value_direction * 0.04, 0.0, 2.2))
            self.engine.master_gain = new_gain
            self.engine.master_channel.gain = new_gain
            self.selected_channel = self.editor_channel = self._master_nav_index()
            self._sync_from_engine()
            return
        mode = getattr(self, "target_bank_mode", "ch")
        mapped_idx = self._target_bank_offset(mode) + idx
        self.selected_channel = self.editor_channel = mapped_idx
        if mapped_idx >= self._target_count_for_mode(mode):
            self._sync_from_engine()
            return
        ch = self._target_at(mode, mapped_idx)
        layer = int(getattr(self, "fader_layer", 0))
        with self.engine._lock:
            if layer <= 0 or mode != "ch":
                new_gain = float(np.clip(float(getattr(self.engine, "master_gain", 1.0) if mode == "mst" else getattr(ch, "gain", 1.0)) + value_direction * 0.04, 0.0, 2.2))
                if mode == "mst":
                    self.engine.master_gain = new_gain
                    ch.gain = new_gain
                else:
                    ch.gain = new_gain
            else:
                cur = self._channel_send_level(ch, layer)
                self._set_channel_send_level(ch, layer, cur + value_direction * 0.03)
        self._sync_from_engine()

    def _stage_label(self, key: str, ch: Optional[ChannelState] = None) -> str:
        if key == "pre" and ch is self.engine.master_channel:
            return "Filters"
        return {"pre": "Mic Pre", "harm": "Harmonics", "gate": "Gate", "comp": "Compressor", "eq": "EQ", "trn": "Transient", "xct": "Exciter", "tbe": "Tube"}.get(key, key.upper())

    def _stage_cell_value(self, ch: ChannelState, stage_key: str, label: str) -> Tuple[str, bool]:
        sk_en = f"{stage_key}_enabled"
        if stage_key == "harm": sk_en = "harmonics_enabled"
        active = getattr(ch, sk_en, True)
        
        bp_key = {"gate":"gate_param_bypass","comp":"comp_param_bypass","eq":"eq_param_bypass","harm":"harm_param_bypass","trn":"trn_param_bypass","xct":"xct_param_bypass","tbe":"tbe_param_bypass"}.get(stage_key)
        bp = getattr(ch, bp_key, {}) if bp_key else {}
        if label in bp and bp[label]: active = False
        
        if stage_key == "pre":
            if label == "TBE": return (("ON" if ch.tube else "off") + f" {getattr(ch, 'pre_gain_db', 0.0):+.0f}dB", bool(ch.tube) or bool(ch.pre_enabled))
            if label == "LPF": return ((("CUT " if ch.lpf_enabled else "off ") + f"{ch.lpf_hz:.0f}"), ch.lpf_enabled and active)
            if label == "HPF": return ((("CUT " if ch.hpf_enabled else "off ") + f"{ch.hpf_hz:.0f}"), ch.hpf_enabled and active)
            if label == "48V": return ("ON" if ch.phantom else "off", bool(ch.phantom))
            if label == "PHS": return ("ON" if ch.phase else "off", bool(ch.phase))
            return ("-", False)

        if stage_key in ("gate", "comp"):
            if label == "TBE": return ("ON" if getattr(ch, stage_key+'_tube') else "off", bool(getattr(ch, stage_key+'_tube')))
            if label == "BND":
                if not getattr(ch, stage_key+'_band_enabled'):
                    return ("off", False)
                slot = self._dyn_band_slot(ch, stage_key)
                count = max(1, min(8, int(getattr(ch, f"{stage_key}_dyn_band_count", 1))))
                return (f"B{slot + 1}/{count}", active)
            pre = "gate_" if stage_key=="gate" else "comp_"
            if label == "THR": return (f"{getattr(ch, pre+'threshold_db'):.1f}", active)
            if stage_key == "gate" and label == "DEP": return (f"{float(getattr(ch, 'gate_ratio')) * 4.0:.0f}dB", active)
            if label == "RAT":
                ratio = float(getattr(ch, pre + "ratio"))
                if stage_key == "comp" and ratio >= 19.95:
                    return ("LIM", active)
                return (f"{ratio:.2f}", active)
            if label == "ATK": return (f"{getattr(ch, pre+'attack_ms'):.1f}", active)
            if label == "RLS": return (f"{getattr(ch, pre+'release_ms'):.1f}", active)
            if label == "GAN": return (f"{getattr(ch, pre+'makeup'):.2f}", active)
            if label == "FRQ":
                banded = bool(getattr(ch, stage_key+'_band_enabled'))
                return (f"{getattr(ch, pre+'center_hz'):.0f}", active and banded)
            if label == "WDT":
                banded = bool(getattr(ch, stage_key+'_band_enabled'))
                return (f"{getattr(ch, pre+'width_oct'):.2f}", active and banded)
        if stage_key == "eq":
            if label == "TBE": return ("ON" if ch.eq_tube else "off", bool(ch.eq_tube))
            if label == "FRQ": return (f"{ch.eq_freq:.0f}", active)
            if label == "GAN": return (f"{ch.eq_gain_db:.1f}", active)
            if label == "SHP":
                width = float(getattr(ch, "eq_width", 1.4))
                return ("SHELF" if width <= 0.1 else f"{width:.2f}", active)
            if label == "BND":
                if not ch.eq_band_enabled:
                    return ("off", False)
                count = max(1, min(8, int(getattr(ch, "eq_band_count", 1))))
                slot = max(0, min(count - 1, int(getattr(ch, "eq_ui_band", 0))))
                return (f"B{slot + 1}/{count}", True)
        if stage_key == "trn":
            if label == "ATK": return (f"{ch.trn_attack:+.2f}", active)
            if label == "SUT": return (f"{ch.trn_sustain:+.2f}", active)
            if label == "DRV": return (f"{ch.trn_drive:.2f}", active)
            if label == "FRQ": return (f"{ch.trn_freq:.0f}", active)
            if label == "BND":
                if not ch.trn_band_enabled:
                    return ("off", False)
                count = max(1, min(8, int(getattr(ch, "trn_band_count", 1))))
                slot = max(0, min(count - 1, int(getattr(ch, "trn_ui_band", 0))))
                return (f"B{slot + 1}/{count}", True)
        if stage_key == "xct":
            if label == "ATK": return (f"{ch.xct_attack:+.2f}", active)
            if label == "SUT": return (f"{ch.xct_sustain:+.2f}", active)
            if label == "DRV": return (f"{ch.xct_drive:.2f}", active)
            if label == "FRQ": return (f"{ch.xct_freq:.0f}", active)
            if label == "BND":
                if not ch.xct_band_enabled:
                    return ("off", False)
                count = max(1, min(8, int(getattr(ch, "xct_band_count", 1))))
                slot = max(0, min(count - 1, int(getattr(ch, "xct_ui_band", 0))))
                return (f"B{slot + 1}/{count}", True)
        if stage_key == "tbe":
            if label == "FRQ": return (f"{ch.tbe_freq:.0f}", active)
            if label == "DRV": return (f"{ch.tbe_drive:.2f}", active)
            if label == "BND":
                if not ch.tbe_band_enabled:
                    return ("off", False)
                count = max(1, min(8, int(getattr(ch, "tbe_band_count", 1))))
                slot = max(0, min(count - 1, int(getattr(ch, "tbe_ui_band", 0))))
                return (f"B{slot + 1}/{count}", True)
        if stage_key == "harm":
            if label == "TBE": return ("ON" if ch.harm_tube else "off", bool(ch.harm_tube))
            if label.startswith("H"):
                try:
                    idx = int(label[1:]) - 1
                    return (f"{idx + 2}x {ch.harmonics[idx]:.2f}", active)
                except Exception: pass
            if label == "GAN": return (f"{ch.harmonic_makeup:.2f}", active)
        return ("-", False)

    def _autosize_editor_canvas_height(self) -> None:
        need = 72 + 32 + 8 + 48 + 10
        self.editor_canvas.config(height=int(need))

    def _transport_button_at(self, r: int, c: int) -> Optional[Tuple[str, str, str, str]]:
        return next(((k, l, clr, glyph) for row, col, k, l, clr, glyph in self._TRANSPORT_BUTTONS if row==r and col==c), None)

    def _transport_cols_for_row(self, r: int) -> List[int]:
        cols = [col for row, col, *_ in self._TRANSPORT_BUTTONS if row == r]
        return sorted(cols) if cols else [0]

    def _timeline_channel_for_display(self) -> ChannelState:
        mode = getattr(self, "target_bank_mode", "ch")
        if mode == "ch":
            return self._mixer_channel_at(self._active_channel_index())
        return self._current_channel()

    def _timeline_view_bounds(self) -> tuple[float, float, float]:
        duration = max(0.01, float(self.engine.timeline_duration_seconds()))
        zoom = float(np.clip(getattr(self.engine, "timeline_zoom", 1.0), 1.0, 32.0))
        view_len = max(0.25, duration / zoom)
        playhead = float(np.clip(getattr(self.engine, "playhead_seconds", 0.0), 0.0, duration))
        start = float(np.clip(playhead - view_len * 0.5, 0.0, max(0.0, duration - view_len)))
        end = min(duration, start + view_len)
        return start, end, duration

    def _timeline_clip_for_display(self, clips: Optional[list[np.ndarray]]) -> Optional[np.ndarray]:
        if not clips:
            return None
        idx = self._active_channel_index() if getattr(self, "target_bank_mode", "ch") == "ch" else 0
        idx = max(0, min(len(clips) - 1, int(idx)))
        return clips[idx]

    def _draw_timeline_clip_waveform(
        self,
        c: tk.Canvas,
        clip: Optional[np.ndarray],
        clip_start_s: float,
        clip_end_s: float,
        view_start: float,
        view_end: float,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        color: str,
        *,
        width: int = 2,
    ) -> None:
        if clip is None:
            return
        arr = np.asarray(clip, dtype=np.float32)
        if arr.size <= 1 or clip_end_s <= clip_start_s:
            return
        if arr.ndim > 1:
            mono = np.max(np.abs(arr), axis=1)
        else:
            mono = np.abs(arr.reshape(-1))
        if mono.size <= 1 or float(np.max(mono)) <= 1e-8:
            return
        overlap_a = max(float(clip_start_s), float(view_start))
        overlap_b = min(float(clip_end_s), float(view_end))
        if overlap_b <= overlap_a:
            return
        view_len = max(0.001, float(view_end) - float(view_start))
        clip_len = max(0.001, float(clip_end_s) - float(clip_start_s))
        sample_a = int(np.clip(((overlap_a - clip_start_s) / clip_len) * mono.size, 0, mono.size - 1))
        sample_b = int(np.clip(((overlap_b - clip_start_s) / clip_len) * mono.size, sample_a + 1, mono.size))
        segment = mono[sample_a:sample_b]
        if segment.size <= 1:
            return
        xa = x0 + ((overlap_a - view_start) / view_len) * (x1 - x0)
        xb = x0 + ((overlap_b - view_start) / view_len) * (x1 - x0)
        if xb - xa < 10:
            center = (xa + xb) / 2
            xa = max(x0, center - 5)
            xb = min(x1, center + 5)
        cols = max(2, int(xb - xa))
        edges = np.linspace(0, segment.size, cols + 1, dtype=np.int32)
        cy = (y0 + y1) / 2
        half_h = max(2.0, (y1 - y0) / 2 - 8)
        step = max(1.0, (xb - xa) / cols)
        for i in range(cols):
            a = int(edges[i])
            b = max(a + 1, int(edges[i + 1]))
            amp = float(np.clip(np.max(segment[a:b]), 0.0, 1.0)) * half_h
            if amp <= 0.5:
                continue
            x = xa + i * step
            c.create_line(x, cy - amp, x, cy + amp, fill=color, width=width)

    def _draw_timeline_master_stereo_waveform(
        self,
        c: tk.Canvas,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        view_start: float,
        view_end: float,
        duration: float,
    ) -> bool:
        audio = np.asarray(
            getattr(self.engine, "master_scope_audio", getattr(self.engine.master_channel, "audio", np.zeros((1, 2), dtype=np.float32))),
            dtype=np.float32,
        )
        if audio.ndim == 1:
            audio = np.column_stack([audio, audio]).astype(np.float32)
        if audio.size <= 2:
            return False
        rows = max(16, int(x1 - x0))
        view_a = float(np.clip(view_start / max(0.001, duration), 0.0, 1.0))
        view_b = float(np.clip(view_end / max(0.001, duration), view_a, 1.0))
        sample_a = int(np.clip(view_a * audio.shape[0], 0, max(0, audio.shape[0] - 1)))
        sample_b = int(np.clip(view_b * audio.shape[0], sample_a + 1, audio.shape[0]))
        lane_gap = 5
        lane_h = max(8.0, ((y1 - y0) - lane_gap) / 2.0)
        drew = False
        for lane, color, label in ((0, "#ff8c1a", "L"), (1, "#ff334d", "R")):
            ly0 = y0 + lane * (lane_h + lane_gap)
            ly1 = ly0 + lane_h
            cy = (ly0 + ly1) / 2.0
            half_h = max(2.0, lane_h / 2.0 - 3)
            c.create_text(x0 + 4, ly0 + 8, anchor="w", text=label, fill=color, font=("Segoe UI", 7, "bold"))
            c.create_line(x0 + 18, cy, x1 - 4, cy, fill="#263342", width=1)
            data = np.abs(audio[sample_a:sample_b, min(lane, audio.shape[1] - 1)])
            if data.size <= 1 or float(np.max(data)) <= 1e-8:
                continue
            edges = np.linspace(0, data.size, rows + 1, dtype=np.int32)
            step = (x1 - x0) / rows
            for i in range(rows):
                a = int(edges[i])
                b = max(a + 1, int(edges[i + 1]))
                amp = float(np.clip(np.max(data[a:b]) * 2.2, 0.0, 1.0)) * half_h
                if amp <= 0.4:
                    continue
                x = x0 + i * step
                c.create_line(x, cy - amp, x, cy + amp, fill=color, width=1)
                drew = True
        return drew

    def _draw_timeline(self) -> None:
        c = getattr(self, "timeline_canvas", None)
        if c is None:
            return
        c.delete("all")
        w, h = max(c.winfo_width(), 520), max(c.winfo_height(), 64)
        margin = 14
        x0, x1 = margin, w - margin
        y0, y1 = 18, h - 14
        c.create_rectangle(0, 0, w, h, fill="#0b1016", outline="")
        ch = self._timeline_channel_for_display()
        mode = getattr(self, "target_bank_mode", "ch")
        target_label = f"{self._target_mode_label(mode)} {self._target_display_label(mode, self._active_channel_index())}"
        c.create_text(x0, 8, anchor="w", text=f"TIMELINE  {target_label}", fill="#7dd3fc", font=("Segoe UI", 8, "bold"))
        timeline_focused = getattr(self, "nav_scope", "") == "timeline"
        c.create_rectangle(x0, y0, x1, y1, fill="#101720", outline="#75baff" if timeline_focused else "#2a3848", width=3 if timeline_focused else 1)

        view_start, view_end, duration = self._timeline_view_bounds()
        view_len = max(0.01, view_end - view_start)
        markers = sorted(float(m) for m in getattr(self.engine, "markers", []) if 0.0 <= float(m) <= duration)
        selected = self._selected_timeline_item()
        region_colors = ["#38bdf8", "#a78bfa", "#f472b6", "#fb7185", "#f59e0b", "#84cc16", "#2dd4bf", "#60a5fa"]
        if len(markers) >= 2:
            playhead = float(getattr(self.engine, "playhead_seconds", 0.0))
            pairs = list(zip(markers[:-1], markers[1:]))
            active_pair = next(((idx, a, b) for idx, (a, b) in enumerate(pairs) if a <= playhead <= b), None)
            for region_idx, (a0, b0) in enumerate(pairs):
                clipped_a = float(np.clip(a0, view_start, view_end))
                clipped_b = float(np.clip(b0, view_start, view_end))
                if clipped_b <= clipped_a:
                    continue
                xa = x0 + ((clipped_a - view_start) / view_len) * (x1 - x0)
                xb = x0 + ((clipped_b - view_start) / view_len) * (x1 - x0)
                band_y0 = y1 - 10
                color = region_colors[region_idx % len(region_colors)]
                is_active = bool(active_pair and active_pair[0] == region_idx)
                is_selected_region = bool(selected and selected["kind"] == "region" and int(selected.get("pair_idx", -1)) == region_idx)
                fill = color if is_active or is_selected_region else "#263342"
                c.create_rectangle(xa, band_y0, xb, y1 - 2, fill=fill, stipple="" if is_active or is_selected_region else "gray50", outline="")
                c.create_line(xa, y0 + 2, xa, y1 - 2, fill=color, width=2 if is_selected_region else 1)
                c.create_line(xb, y0 + 2, xb, y1 - 2, fill=color, width=2 if is_selected_region else 1)
                label = f"R{region_idx + 1}"
                c.create_text((xa + xb) / 2, band_y0 - 7, text=label, fill="#ffffff" if is_selected_region else color, font=("Segoe UI", 7, "bold"))
        if ch is self.engine.master_channel and self._draw_timeline_master_stereo_waveform(c, x0, x1, y0 + 3, y1 - 3, view_start, view_end, duration):
            pass
        else:
            pv = np.asarray(getattr(ch, "wave_preview", []), dtype=np.float32).reshape(-1)
            if pv.size > 1 and float(np.max(np.abs(pv))) > 1e-8:
                rows = max(8, int(x1 - x0))
                xp = np.linspace(0.0, 1.0, int(pv.size), dtype=np.float64)
                xd = np.linspace(view_start / duration, view_end / duration, rows, dtype=np.float64)
                peaks = np.interp(xd, xp, pv.astype(np.float64))
                cy = (y0 + y1) / 2
                half_h = (y1 - y0) / 2 - 3
                step = (x1 - x0) / rows
                for i, peak in enumerate(peaks):
                    amp = float(np.clip(abs(peak), 0.0, 1.0)) * half_h
                    if amp <= 0.4:
                        continue
                    x = x0 + i * step
                    c.create_line(x, cy - amp, x, cy + amp, fill="#ff8c1a", width=1)
            else:
                c.create_line(x0 + 4, (y0 + y1) / 2, x1 - 4, (y0 + y1) / 2, fill="#263342", width=1)

        for i, marker in enumerate(markers, start=1):
            if marker < view_start or marker > view_end:
                continue
            x = x0 + ((marker - view_start) / view_len) * (x1 - x0)
            marker_selected = bool(selected and selected["kind"] == "marker" and abs(float(selected["start"]) - marker) < 1e-6)
            c.create_line(x, y0 - 5, x, y1 + 5, fill="#ff4fd8" if marker_selected else "#fbbf24", width=4 if marker_selected else 2)
            c.create_polygon(x, y0 - 5, x + 8, y0, x, y0 + 5, fill="#ff4fd8" if marker_selected else "#fbbf24", outline="")
            c.create_text(x + 10, y0 + 2, anchor="w", text=str(i), fill="#ffe9a8", font=("Segoe UI", 7, "bold"))

        if selected and selected["kind"] == "region":
            a = float(np.clip(float(selected["start"]), view_start, view_end))
            b = float(np.clip(float(selected["end"]), view_start, view_end))
            if b > a:
                xa = x0 + ((a - view_start) / view_len) * (x1 - x0)
                xb = x0 + ((b - view_start) / view_len) * (x1 - x0)
                region_idx = int(selected.get("pair_idx", 0))
                color = region_colors[region_idx % len(region_colors)]
                c.create_rectangle(xa, y0 + 3, xb, y1 - 3, outline="#ffffff", width=5)
                c.create_rectangle(xa + 3, y0 + 6, xb - 3, y1 - 6, outline=color, width=3)
                c.create_text((xa + xb) / 2, y0 + 12, text=f"SELECT R{region_idx + 1}", fill="#ffffff", font=("Segoe UI", 7, "bold"))

        playhead = float(getattr(self.engine, "playhead_seconds", 0.0))
        preview_region = getattr(self, "_edit_preview_region", None)
        if preview_region:
            a0, b0, label = preview_region
            a = float(np.clip(float(a0), view_start, view_end))
            b = float(np.clip(float(b0), view_start, view_end))
            if b > a:
                xa = x0 + ((a - view_start) / view_len) * (x1 - x0)
                xb = x0 + ((b - view_start) / view_len) * (x1 - x0)
                color = "#86efac" if label == "PASTE" else "#fb7185" if label == "CUT" else "#93c5fd"
                self._draw_timeline_clip_waveform(
                    c,
                    self._timeline_clip_for_display(getattr(self, "_edit_preview_audio", None)),
                    float(a0),
                    float(b0),
                    view_start,
                    view_end,
                    x0,
                    x1,
                    y0 + 7,
                    y1 - 7,
                    color,
                    width=2,
                )
                c.create_rectangle(xa, y0 + 7, xb, y1 - 7, outline=color, width=3, dash=(8, 4))
                c.create_text((xa + xb) / 2, y1 - 18, text=label, fill=color, font=("Segoe UI", 7, "bold"))
        if self._has_edit_clipboard():
            clip_len = max(0.0, float(getattr(self, "_edit_clipboard_duration", 0.0)))
            if clip_len > 0.0:
                clip_start = playhead
                clip_end = playhead + clip_len
                clipped_a = float(np.clip(clip_start, view_start, view_end))
                clipped_b = float(np.clip(clip_end, view_start, view_end))
                if clipped_b > clipped_a:
                    xa = x0 + ((clipped_a - view_start) / view_len) * (x1 - x0)
                    xb = x0 + ((clipped_b - view_start) / view_len) * (x1 - x0)
                    action = getattr(self, "_edit_clipboard_action", "")
                    outline = "#fb7185" if action == "cut" else "#93c5fd"
                    self._draw_timeline_clip_waveform(
                        c,
                        self._timeline_clip_for_display(getattr(self, "_edit_clipboard_audio", None)),
                        clip_start,
                        clip_end,
                        view_start,
                        view_end,
                        x0,
                        x1,
                        y0 + 6,
                        y1 - 6,
                        outline,
                        width=2,
                    )
                    c.create_rectangle(xa, y0 + 6, xb, y1 - 6, outline=outline, width=3, dash=(6, 4))
                    c.create_text((xa + xb) / 2, y0 + 12, text=f"{action.upper()} FLOAT", fill=outline, font=("Segoe UI", 7, "bold"))
        ph_x = x0 + float(np.clip((playhead - view_start) / view_len, 0.0, 1.0)) * (x1 - x0)
        c.create_line(ph_x, y0 - 8, ph_x, y1 + 8, fill="#75baff", width=3)
        c.create_polygon(ph_x - 5, y0 - 9, ph_x + 5, y0 - 9, ph_x, y0 - 1, fill="#75baff", outline="")
        c.create_text(x1, 8, anchor="e", text=f"{playhead:0.1f}s / {duration:0.1f}s  ZM {float(getattr(self.engine, 'timeline_zoom', 1.0)):.1f}x", fill="#8fa3b8", font=("Consolas", 8, "bold"))

    def _draw_vertical_waveform(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float, is_master: bool) -> None:
        h, w = y1 - y0, x1 - x0
        if h < 6 or w < 4: return
        cx, half_w = (x0 + x1) / 2, w / 2 - 1
        if is_master or not getattr(ch, "audio", None) is not None or len(ch.audio) == 0:
            c.create_line(cx, y0 + 2, cx, y1 - 2, fill="#2a313b", width=1); return
        pv = np.asarray(getattr(ch, "wave_preview", [0]), dtype=np.float32).reshape(-1)
        rows = max(8, int(h))
        if pv.size <= 1 or float(np.max(pv)) < 1e-10:
            c.create_line(cx, y0 + 2, cx, y1 - 2, fill="#2a313b", width=1); return
        xp = np.linspace(0.0, 1.0, int(pv.size), dtype=np.float64)
        xd = ((np.arange(rows, dtype=np.float64) + 0.5) / float(rows)).clip(0.0, 1.0)
        peaks = np.interp(xd, xp, pv.astype(np.float64)).astype(np.float32)
        step = h / rows
        for i in range(rows):
            yt, yb = y0 + i * step, y0 + (i+1) * step
            ext = float(peaks[i]) * half_w
            if ext > 0.5: c.create_rectangle(cx - ext, yt, cx + ext, yb, fill="#ff8c1a", outline="")
        c.create_line(cx, y0, cx, y1, fill="#3a2410", width=1)
        if len(ch.audio) > 1:
            ph = max(0.0, min(1.0, ch.position / float(len(ch.audio))))
            phy = y0 + ph * h
            c.create_line(x0, phy, x1, phy, fill="#ffd97a", width=2)

    def _draw_stereo_master_waveform(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float) -> None:
        h, w = y1 - y0, x1 - x0
        if h < 12 or w < 4:
            return
        audio = np.asarray(getattr(self.engine, "master_scope_audio", getattr(ch, "audio", np.zeros((1, 2), dtype=np.float32))), dtype=np.float32)
        if audio.ndim == 1:
            audio = np.column_stack([audio, audio]).astype(np.float32)
        rows = max(8, int(h) - 4)
        gap = 6
        lane_w = max(8.0, (w - gap) / 2.0)
        for lane, color, label in ((0, "#ff8c1a", "L"), (1, "#ff334d", "R")):
            lx0 = x0 + lane * (lane_w + gap)
            lx1 = lx0 + lane_w
            center_x = (lx0 + lx1) / 2
            half_w = max(2.0, lane_w / 2 - 2)
            c.create_rectangle(lx0, y0, lx1, y1, fill="", outline="#2d1820")
            c.create_text(lx0 + 4, y0 + 10, anchor="w", text=label, fill=color, font=("Segoe UI", 8, "bold"))
            c.create_line(center_x, y0 + 2, center_x, y1 - 2, fill="#4b2730", width=1)
            if audio.size > 2 and float(np.max(np.abs(audio))) > 1e-8:
                data = np.abs(audio[:, min(lane, audio.shape[1] - 1)])
                xp = np.linspace(0.0, 1.0, int(data.size), dtype=np.float64)
                xd = ((np.arange(rows, dtype=np.float64) + 0.5) / float(rows)).clip(0.0, 1.0)
                peaks = np.interp(xd, xp, data.astype(np.float64)).astype(np.float32)
                step = (y1 - y0) / rows
                for i, peak in enumerate(peaks):
                    ext = float(np.clip(peak * 2.2, 0.0, 1.0)) * half_w
                    if ext > 0.5:
                        yt, yb = y0 + i * step, y0 + (i + 1) * step
                        c.create_rectangle(center_x - ext, yt, center_x + ext, yb, fill=color, outline="")
        c.create_line(x0 + lane_w + gap / 2, y0, x0 + lane_w + gap / 2, y1, fill="#4b2730", width=1)

    def _draw_send_knob(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float, focused: bool = False, channel_idx: int = -1) -> None:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        r = max(8, min((x1 - x0), (y1 - y0)) / 2 - 4)
        layer = int(getattr(self, "fader_layer", 0))
        send_mode = layer > 0 or bool(getattr(self, "knobs_send_mode", False))
        send_muted = bool(getattr(ch, "send_muted", False)) and send_mode
        if focused: c.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4, outline="#7cf0a9", width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1a2330" if not send_muted else "#141a20", outline="#33485e" if not send_muted else "#2a323d", width=1)
        c.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62, fill="#0f161f", outline="#28394d", width=1)
        if send_mode:
            slot = max(1, layer or int(getattr(ch, "send_slot", 1)))
            val = self._channel_send_level(ch, slot)
            angle_deg = -90 - 135 + val * 270.0; ind_color = "#ff8c1a" if not send_muted else "#5b6c80"
        else:
            pan = float(np.clip(getattr(ch, "pan", 0.0), -1.0, 1.0))
            angle_deg = -90 + pan * 135.0; ind_color = "#7cd7ff"
        angle = math.radians(angle_deg)
        c.create_line(cx, cy, cx + math.cos(angle)*(r-3), cy + math.sin(angle)*(r-3), fill=ind_color, width=2)
        face_text = f"S{max(1, layer or int(getattr(ch, 'send_slot', 1)))}" if send_mode else "PAN"
        c.create_text(cx, cy - 1, text=face_text, fill="#9aa6b6" if send_muted else "#d6e1ec", font=("Segoe UI", 7, "bold"))

    def _draw_strip_fader(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float, is_master: bool, focused: bool = False) -> None:
        cx, track_w = (x0 + x1) / 2, max(4, (x1 - x0) - 6)
        if focused: c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#5ef0b0", width=2)
        c.create_rectangle(cx - track_w/2, y0, cx + track_w/2, y1, fill="#10151b", outline="#28323d")
        meter_fill = float(np.clip(getattr(ch, "level", 0.0), 0.0, 1.0))
        if meter_fill > 0.001:
            my = y1 - (y1 - y0) * meter_fill
            mc = "#ef233c" if is_master else ("#5ef0b0" if meter_fill < 0.7 else ("#f7c46f" if meter_fill < 0.9 else "#ff6868"))
            c.create_rectangle(cx - track_w/2 + 2, my, cx + track_w/2 - 2, y1 - 2, fill=mc, outline="")
        layer = int(getattr(self, "fader_layer", 0))
        if layer > 0 and not is_master:
            gain = self._channel_send_level(ch, layer)
            frac = gain
            handle_color = "#ffb757"
        else:
            gain = float(np.clip(getattr(ch, "gain", 1.0), 0.3, 2.2))
            frac = (gain - 0.3) / 0.7 * 0.7 if gain <= 1.0 else 0.7 + (gain - 1.0) / 1.2 * 0.3
            handle_color = "#ff8f3a" if not is_master else "#ef233c"
        ty = y1 - (y1 - y0) * frac; tw = (x1 - x0) + 4
        c.create_rectangle(cx - tw/2, ty - 7, cx + tw/2, ty + 7, fill=handle_color, outline="#1a1a1a")
        c.create_line(cx - tw/2 + 2, ty, cx + tw/2 - 2, ty, fill="#ffd7d3" if is_master else "#1a1a1a", width=2 if is_master else 1)
        if is_master:
            c.create_polygon(cx, ty - 13, cx - 5, ty - 6, cx + 5, ty - 6, fill="#ffd7d3", outline="")
            c.create_text(cx, max(y0 + 10, ty - 22), text=f"{gain:.2f}", fill="#ffd7d3", font=("Consolas", 7, "bold"))

    def _stage_enabled(self, ch: ChannelState, key: str) -> bool:
        if ch is self.engine.master_channel and key == "pre":
            return bool(getattr(ch, "lpf_enabled", False) or getattr(ch, "hpf_enabled", False))
        m = {
            "pre": "pre_enabled",
            "harm": "harmonics_enabled",
            "gate": "gate_enabled",
            "comp": "comp_enabled",
            "eq": "eq_enabled",
            "trn": "trn_enabled",
            "xct": "xct_enabled",
            "tbe": "tbe_enabled",
        }
        return bool(getattr(ch, m.get(key, "eq_enabled"), False))

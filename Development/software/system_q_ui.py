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
    TRANSPORT_COLS = 12
    GRID_HEADER_H_NORMAL = 44
    GRID_CELL_H_NORMAL = 52
    STRIP_WIDTH = 76

    _STAGE_GRID = [
        ("pre",  "PRE", ["TBE", "LPF", "48V", "PHS", "HPF"]),
        ("harm", "HRM", ["TBE", "H1", "H2", "H3", "H4", "H5"]),
        ("gate", "GTE", ["TBE", "THR", "DEP", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("comp", "CMP", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("eq",   "EQ",  ["TBE", "FRQ", "GAN", "SHP", "BND", "TRN", "ATK", "SUT", "BD2"]),
        ("trn",  "TRN", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("xct",  "XCT", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("tbe",  "TBE", ["DRV", "BND"]),
    ]

    STAGE_COLOR = {
        "pre": "#77f0c6", "harm": "#ffb757", "gate": "#ddc270", "comp": "#ff6a53",
        "eq": "#75baff", "trn": "#36e0dc", "xct": "#c06cff", "tbe": "#ff8f3a"
    }

    _TRANSPORT_BUTTONS = [
        (0, 0, "play", "PLY", "#6ff0c1", "▶"),
        (0, 1, "stop", "STP", "#ff6a53", "■"),
        (0, 2, "rewind", "REW", "#89a0b6", "⏪"),
        (0, 3, "forward", "FFD", "#89a0b6", "⏩"),
        (0, 4, "record", "REC", "#ff3b30", "●"),
        (1, 0, "oscillator", "OSC", "#fbbf24", "∿"),
        (1, 1, "pink", "PNK", "#f472c0", "▒"),
        (1, 2, "white", "WHT", "#7dd3fc", "▓"),
        (1, 3, "pink_pulse", "PLS", "#fbcfe8", "⌚"),
        (1, 4, "white_hot", "HOT", "#38bdf8", "🔥"),
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
        self._last_cardinal_nav_at = 0.0
        self._last_editor_adjust_at = 0.0
        self._last_console_adjust_at = 0.0
        self._last_transport_adjust_at = 0.0
        
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
        def _global_click(e):
            transport_widgets = set(getattr(self, "transport_cells", {}).values())
            if e.widget in transport_widgets or e.widget is getattr(self, "transport_panel", None):
                return
            # If clicked on the editor surface, assume editor focus.
            if e.widget is self.editor_canvas or e.widget is self.focus_canvas:
                self.nav_scope = "editor"
        self.root.bind("<Button-1>", _global_click, add="+")
        
        # Transport at the very bottom
        self.transport_panel = self._build_transport_panel(parent)
        self.transport_panel.pack(fill="x", side="bottom", padx=8, pady=(0, 8))

    def _build_transport_panel(self, parent: tk.Frame) -> tk.Frame:
        f = tk.Frame(parent, bg="#0c1118")
        self.transport_cells = {}
        for r, c, k, l, clr, glyph in self._TRANSPORT_BUTTONS:
            btn = tk.Label(f, text=f"{glyph}\n{l}", bg="#151a21", fg=clr, font=("Segoe UI", 9, "bold"), width=8, height=3, relief="flat", bd=2)
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            btn.bind("<Button-1>", lambda _e, row=r, col=c: self._on_transport_click(row, col))
            self.transport_cells[(r, c)] = btn
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
    def _tx_play(self) -> None: self.engine.toggle_play(); self._sync_from_engine()
    def _flash_transport_action(self, key: str) -> None:
        self._transport_flash = (key, time.time())

    def _tx_stop(self) -> None: self._flash_transport_action("stop"); self.engine.stop(); self._sync_from_engine()
    def _tx_rewind(self) -> None: self._flash_transport_action("rewind"); self.engine.rewind(); self._sync_from_engine()
    def _tx_forward(self) -> None: self._flash_transport_action("forward"); self.engine.jump_forward(); self._sync_from_engine()
    def _tx_record(self) -> None:
        ch = self._current_channel()
        if ch is not self.engine.master_channel:
            ch.record_armed = not bool(getattr(ch, "record_armed", False))
        self._sync_from_engine()

    def _set_generator_mode(self, mode: str) -> None:
        self.engine.generator_mode = "none" if self.engine.generator_mode == mode else mode
        self._sync_from_engine()

    def _tx_oscillator(self) -> None: self._set_generator_mode("osc")
    def _tx_pink(self) -> None: self._set_generator_mode("pink")
    def _tx_white(self) -> None: self._set_generator_mode("white")
    def _tx_pink_pulse(self) -> None: self._set_generator_mode("pink_pulse")
    def _tx_white_hot(self) -> None: self._set_generator_mode("white_hot")

    # --- Core Accessors ---
    def _active_channel_index(self) -> int:
        return self.editor_channel if getattr(self, "nav_scope", "console") == "editor" else self.selected_channel

    def _current_channel(self) -> ChannelState:
        idx = self._active_channel_index()
        return self.engine.channels[idx] if idx < len(self.engine.channels) else self.engine.master_channel

    def _console_stage_keys(self, channel_index: Optional[int] = None) -> List[str]:
        idx = self._active_channel_index() if channel_index is None else channel_index
        if idx >= len(self.engine.channels): return ["harm", "gate", "comp", "eq", "trn", "xct", "tbe"]
        return ["pre", "harm", "gate", "comp", "eq", "trn", "xct", "tbe"]

    def _channel_nav_span(self) -> int:
        n = len(self.engine.channels)
        return n if getattr(self, "selected_stage_key", "") == "pre" else n + 1

    # --- Sync & Commit ---
    def _sync_from_engine(self) -> None:
        self._syncing_controls = True
        try:
            ch = self._current_channel()
            self.editor_title.config(text=f"{ch.name}  ·  {self._stage_label(self.selected_stage_key)}")
            sub = f"{self._active_channel_index()+1:02d}  {ch.path.name}" if self._active_channel_index() < len(self.engine.channels) else "MASTER BUS"
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
            self._draw_focus()
            self._draw_editor_controls()
            self._sync_play_transport_glyph()
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
            fg = btn.cget("fg")
            
            key = self._transport_button_at(r, c)
            action = key[0] if key else ""
            flash_key, flash_at = getattr(self, "_transport_flash", ("", 0.0))
            if action == flash_key and time.time() - float(flash_at) < 0.55:
                bg = "#f8d58a" if not is_f else "#ffe9a8"
                fg = "#0b1016"
            # Special case for Play button state
            elif r == 0 and c == 0:
                if is_playing:
                    bg = "#2a4a3e" if not is_f else "#3d6b5a"
                    fg = "#6ff0c1"
                else:
                    fg = "#4a635a" if not is_f else "#6ff0c1"
            elif action == "record":
                ch = self._current_channel()
                if bool(getattr(ch, "record_armed", False)):
                    bg = "#4a1820" if not is_f else "#6a2230"
                    fg = "#ff9aa8"
            elif action in ("oscillator", "pink", "white", "pink_pulse", "white_hot"):
                mode = "osc" if action == "oscillator" else action
                if getattr(self.engine, "generator_mode", "none") == mode:
                    bg = "#3c3340" if not is_f else "#5a4d60"
                    fg = "#ffd37a"
            
            btn.config(bg=bg, fg=fg, relief="sunken" if is_f else "flat", bd=5 if is_f else 0, highlightthickness=3 if is_f else 0, highlightbackground=focus_outline, highlightcolor=focus_outline)

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

    def _draw_focus_gate_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        if not (ch.gate_enabled or ch.gate_band_enabled): return
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
            f_pos = self._freq_to_slider(ch.gate_center_hz)
            width_oct = float(np.clip(getattr(ch, "gate_width_oct", 4.0), 0.1, 6.0))
            band_width = max(2.0, 1.0 + width_oct * 1.4)
            lo_hz = max(POL_LOW_HZ, float(ch.gate_center_hz) / (2.0 ** (width_oct / 2.0)))
            hi_hz = min(POL_HIGH_HZ, float(ch.gate_center_hz) * (2.0 ** (width_oct / 2.0)))
            p_lo = self._freq_to_slider(lo_hz)
            p_hi = self._freq_to_slider(hi_hz)
            rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
            outer_band_rx, outer_band_ry = orx - (orx - irx) * min(p_lo, p_hi), ory - (ory - iry) * min(p_lo, p_hi)
            inner_band_rx, inner_band_ry = orx - (orx - irx) * max(p_lo, p_hi), ory - (ory - iry) * max(p_lo, p_hi)
            hue = freq_rainbow_hue_hz(ch.gate_center_hz)
            if closed > 0.02:
                red_flash = 0.65 + 0.35 * math.sin(time.time() * 9.0)
                steps = max(3, int(3 + depth_t * 5))
                for i in range(steps):
                    t = i / max(1, steps - 1)
                    wrx = inner_band_rx + (outer_band_rx - inner_band_rx) * t
                    wry = inner_band_ry + (outer_band_ry - inner_band_ry) * t
                    value = float(np.clip(0.20 + depth_t * 0.52 + closed * 0.22 + red_flash * 0.10, 0.0, 1.0))
                    c.create_oval(cx - wrx, cy - wry, cx + wrx, cy + wry, outline=hsv_to_hex(0.0, 0.94, value), width=1 + int(depth_t * 3))
            c.create_oval(cx - outer_band_rx, cy - outer_band_ry, cx + outer_band_rx, cy + outer_band_ry, outline="#8f1d24", width=2)
            c.create_oval(cx - inner_band_rx, cy - inner_band_ry, cx + inner_band_rx, cy + inner_band_ry, outline=edge_color, width=4)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=hsv_to_hex(hue, 0.48, 0.42 + pulse * 0.08), width=1)
            c.create_text(cx, cy + ry + 16, text=f"KEY {ch.gate_center_hz:.0f} Hz  WDT {width_oct:.1f}", fill="#ddc270", font=("Consolas", 9, "bold"))

        c.create_text(
            cx,
            cy + ory + 20,
            text=f"{status}  IN {detector_db:.1f} dB  THR {threshold_db:.1f} dB  FLOOR {floor_db:.1f} dB  DEP {depth_db:.0f} dB  ATK {attack_ms:.1f}  RLS {release_ms:.0f}",
            fill=status_color,
            font=("Consolas", 10, "bold"),
        )


    def _draw_focus_harm_shells(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        if not ch.harmonics_enabled:
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
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        # Logic for EQ shells
        f_pos = self._freq_to_slider(ch.eq_freq)
        rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
        gain_abs = abs(ch.eq_gain_db) / 24.0
        width = 1 + gain_abs * 6 + pulse * 2
        color = "#ff8c1a" if ch.eq_gain_db < 0 else "#75baff"
        c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=width)

    def _draw_focus_tone_shells(self, c: tk.Canvas, ch: ChannelState, mode: str, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        pulse = getattr(self, "_pol_pulse_cached", 0.0)
        # Restore the TRN/XCT band shells logic
        pre = mode + "_"
        enabled = getattr(ch, pre + "enabled", False)
        if not enabled: return
        
        hz = getattr(ch, pre + "freq", getattr(ch, pre + "center_hz", 1000.0))
        f_pos = self._freq_to_slider(hz)
        rx, ry = orx - (orx - irx) * f_pos, ory - (ory - iry) * f_pos
        
        color = self.STAGE_COLOR.get(mode, "#fff")
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
        margin, gap, stages = 12, 6, len(self._STAGE_GRID)
        # Row 1: Stages (Top)
        # Row 2 & 3: Parameters (Bottom)
        top_y, hdr_h, cell_h = 10, 32, 48
        focus_col = getattr(self, "editor_stage_col", 0)
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        editor_focused = getattr(self, "nav_scope", "console") == "editor"
        pulse = 0.5 + 0.5 * math.sin(time.time() * 7.0)
        focus_outline = hsv_to_hex((time.time() * 0.18) % 1.0, 0.95, 1.0)
        
        # Draw Row 1: Stage Selection
        sw = (w - margin * 2 - gap * (stages - 1)) / stages
        for i, (sk, hdr, params) in enumerate(self._STAGE_GRID):
            x0 = margin + i * (sw + gap)
            x1 = x0 + sw
            hc = self.STAGE_COLOR.get(sk, "#9aa6b6")
            is_f = editor_focused and hdr_focus and i == focus_col
            en = self._stage_enabled(ch, sk)
            fill = hc if is_f and en else ("#263648" if is_f else ("#1d2c39" if en else "#15202c"))
            outline = "#fff" if is_f else (hc if en else "#2a3848")
            text_fill = "black" if is_f and en else (hc if en or is_f else "#6b7787")
            c.create_rectangle(x0, top_y, x1, top_y + hdr_h, outline=outline, width=2 if is_f or en else 1, fill=fill)
            if is_f:
                c.create_rectangle(x0 - 4, top_y - 4, x1 + 4, top_y + hdr_h + 4, outline=focus_outline, width=4)
                c.create_rectangle(x0 - 8, top_y - 8, x1 + 8, top_y + hdr_h + 8, outline="#ffd400", width=2)
            c.create_text((x0+x1)/2, top_y + hdr_h/2 - 4, text=hdr, fill=text_fill, font=("Segoe UI", 9, "bold"))
            c.create_text((x0+x1)/2, top_y + hdr_h/2 + 10, text="ON" if en else "off", fill=text_fill, font=("Consolas", 7, "bold"))
            self.editor_hitboxes.append((x0, top_y, x1, top_y + hdr_h, ("stage_hdr", i)))

        # Draw Row 2 & 3: Parameters for the selected stage
        sk, hdr, params = self._STAGE_GRID[focus_col]
        pw = (w - margin * 2 - gap * (len(params) - 1)) / len(params)
        py0 = top_y + hdr_h + 8
        for i, lbl in enumerate(params):
            px0 = margin + i * (pw + gap)
            px1 = px0 + pw
            is_f = editor_focused and not hdr_focus and i == focus_param
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
        active_stage = self._STAGE_GRID[focus_col][1]
        active_label = active_stage if hdr_focus else params[focus_param]
        if editor_focused:
            c.create_text(w - 12, h - 8, anchor="se", text=f"FOCUS {active_stage}:{active_label}", fill=focus_outline, font=("Segoe UI", 9, "bold"))

    def _draw_strips(self) -> None:
        c = self.strip_canvas; c.delete("all")
        self.strip_hitboxes = []
        w, h = max(c.winfo_width(), 980), max(c.winfo_height(), 720)
        c.create_rectangle(0, 0, w, h, fill="#0c1014", outline="")
        sw, gap = self.STRIP_WIDTH, 8
        strip_sources = list(self.engine.channels) + [self.engine.master_channel]
        tw = len(strip_sources)*sw + (len(strip_sources)-1)*gap
        sx = max(18, (w - tw)/2)
        top_y, bottom_y = 14, h - 14
        body_h = bottom_y - top_y
        grid_h = 14 + len(self._STAGE_GRID)*16 + 16
        fixed_h = grid_h + 18 + 26 + 50 + 28 + 14
        rem_h = max(80, body_h - fixed_h)
        wf_h, fader_h = int(rem_h*0.55), rem_h - int(rem_h*0.55)
        
        for col, ch in enumerate(strip_sources):
            x0, x1 = sx + col*(sw+gap), sx + col*(sw+gap) + sw
            is_m = col == len(self.engine.channels)
            sel = col == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel)
            c.create_rectangle(x0, top_y+10, x1, bottom_y, fill="#181e25" if not is_m else "#1b1d24", outline="#30404f" if not is_m else "#506071")
            # Waveform
            wfy0, wfy1 = top_y+14, top_y+14+wf_h
            c.create_rectangle(x0+5, wfy0, x1-5, wfy1, fill="#0a0d11", outline="#1d2735")
            self._draw_vertical_waveform(c, ch, x0+7, wfy0+2, x1-7, wfy1-2, is_m)
            # Record
            if not is_m:
                rec_f = sel and getattr(self, "console_row", "") == "record"
                c.create_rectangle(x0+14, wfy1+4, x1-14, wfy1+4+22, fill="#232b34" if rec_f else "#10151b", outline="#f8d58a" if rec_f else "#2b3743")
                rr = 6; cx, cy_r = (x0+x1)/2, wfy1+4+11
                c.create_oval(cx-rr, cy_r-rr, cx+rr, cy_r+rr, fill="#ff3b30" if getattr(ch, "record_armed", False) else "#ff7b73", outline="#ffd7d3" if getattr(ch, "record_armed", False) else "", width=1 if getattr(ch, "record_armed", False) else 0)
        
        # Stages Grid Bridge
        gy0 = top_y + 14 + wf_h + 26
        gy1 = gy0 + grid_h
        c.create_rectangle(sx-12, gy0, sx+tw+12, gy1, fill="#0a0d12", outline="#1f2933")
        c.create_text(sx-4, gy0+4, anchor="nw", text="STAGES", fill="#5ec8ff", font=("Segoe UI", 8, "bold"))
        for r, (key, lbl, _) in enumerate(self._STAGE_GRID):
            cy = gy0 + 14 + 8 + r*16
            c.create_text(sx-4, cy+8, anchor="w", text=lbl, fill="#62748a", font=("Segoe UI", 7, "bold"))
            for col, ch in enumerate(strip_sources):
                cx0, cx1 = sx + col*(sw+gap)+4, sx + col*(sw+gap)+sw-4
                en = self._stage_enabled(ch, key)
                act = col == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel) and self.selected_stage_key == key and (self.nav_scope == "editor" or (self.nav_scope == "console" and getattr(self, "console_row", "") == "stages"))
                bc = self.STAGE_COLOR.get(key, "#1c2530") if en else "#1c2530"
                c.create_rectangle(cx0, cy+2, cx1, cy+14, fill=bc if en else "#10151b", outline="#d9e6f2" if act else ("#2a3848" if not en else bc), width=2 if act else 1)
        
        # ID, Knobs, Faders
        id_y = gy1 + 10
        for col, ch in enumerate(strip_sources):
            x0, x1 = sx + col*(sw+gap), sx + col*(sw+gap) + sw
            is_m = col == len(self.engine.channels)
            sel = col == (self.editor_channel if self.nav_scope == "editor" else self.selected_channel)
            # ID + Status Glyphs (48V, PHS)
            c.create_rectangle(x0+3, id_y+4, x1-3, id_y+4+14, fill="#1e2a36" if not is_m else "#272e38", outline="")
            c.create_text((x0+x1)/2, id_y+4+7, text="MST" if is_m else f"{col+1:02d}", fill="#d6e1ec", font=("Segoe UI", 9, "bold"))
            if not is_m:
                # 48V Glyph
                if getattr(ch, "phantom", False):
                    c.create_text(x0+10, id_y+4+7, text="48V", fill="#ff3b30", font=("Segoe UI", 6, "bold"))
                # Phase Glyph
                if getattr(ch, "phase", False):
                    c.create_text(x1-10, id_y+4+7, text="ø", fill="#ff9500", font=("Segoe UI", 8, "bold"))
            # Knob
            kn_f = not is_m and ((self.nav_scope == "knobs" and self.knob_focus_channel == col) or (self.nav_scope == "console" and getattr(self, "console_row", "") == "knob" and self.selected_channel == col))
            self._draw_send_knob(c, ch, x0+6, id_y+22, x1-6, id_y+22+46, focused=kn_f, channel_idx=col)
            # Fader
            fd_f = not is_m and ((self.nav_scope == "faders" and self.fader_focus_channel == col) or (self.nav_scope == "console" and getattr(self, "console_row", "") in ("fader", "faders") and self.selected_channel == col))
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
                self.strip_hitboxes.append((x0+8, ft_y0, mid-g, ft_y1, ("solo", col)))
                self.strip_hitboxes.append((mid+g, ft_y0, x1-8, ft_y1, ("mute", col)))
        self._draw_master_meter()

    def _draw_master_meter(self) -> None:
        c = self.strip_canvas
        # Simplified master meter overlay
        pass

    # --- Events ---
    def _poll_spacemouse(self) -> None:
        res = self.spacemouse.poll()
        if not res: return
        val, pr, dr = res
        if dr:
            for d in dr:
                if d in ("left", "right", "up", "down", "press", "back"):
                    self._handle_nav(d)
        elif pr and 0 in pr: self._handle_nav("press")
        else:
            self._adjust_focused_axis(val)

    def _handle_nav(self, target: str) -> None:
        if target in ("left", "right", "up", "down"):
            now = time.monotonic()
            if now - float(getattr(self, "_last_cardinal_nav_at", 0.0)) < 0.22:
                return
            self._last_cardinal_nav_at = now
        ns = getattr(self, "nav_scope", "console")
        if ns == "editor": self._handle_unified_editor_nav(target)
        elif ns == "console": self._handle_console_nav(target)
        elif ns == "transport": self._handle_transport_nav(target)

    def _handle_console_nav(self, target: str) -> None:
        r = getattr(self, "console_row", "stages")
        if target == "left":
            if r == "stages":
                sk = self._console_stage_keys(); si = sk.index(self.selected_stage_key)
                if si > 0: self.selected_stage_key = sk[si-1]
            elif r == "footer":
                self.footer_focus_side = "solo"
            else: self.selected_channel = (self.selected_channel - 1) % self._channel_nav_span()
        elif target == "right":
            if r == "stages":
                sk = self._console_stage_keys(); si = sk.index(self.selected_stage_key)
                if si < len(sk)-1: self.selected_stage_key = sk[si+1]
            elif r == "footer":
                self.footer_focus_side = "mute"
            else: self.selected_channel = (self.selected_channel + 1) % self._channel_nav_span()
        elif target == "up":
            if r == "faders": self.console_row = "stages"
            elif r == "footer": self.console_row = "faders"
        elif target == "down":
            if r == "stages": self.console_row = "faders"
            elif r == "faders": self.console_row = "footer"
        elif target == "press":
            if r == "stages": self._open_stage_editor(self.selected_channel, self.selected_stage_key)
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
            if tr < 1: self.transport_focus_row += 1
        elif target == "left":
            self.transport_focus_col = (tc - 1) % 5
        elif target == "right":
            self.transport_focus_col = (tc + 1) % 5
        elif target == "press":
            btn = self._transport_button_at(tr, tc)
            if btn: getattr(self, f"_tx_{btn[0]}", lambda: None)()
        elif target == "back": self._exit_transport_to_console()
        self._sync_from_engine()

    def _on_strip_click(self, event) -> None:
        self.root.after_idle(self.root.focus_set)
        for x0, y0, x1, y1, tag in getattr(self, "strip_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                kind, idx = tag
                self.nav_scope = "console"
                self.console_row = "footer"
                self.selected_channel = idx
                self.footer_focus_side = kind
                self._toggle_channel_footer(idx, kind)
                self._sync_from_engine()
                return
        sw, gap = self.STRIP_WIDTH, 8
        n_strips = len(self.engine.channels) + 1
        total_w = n_strips * sw + (n_strips - 1) * gap
        sx = max(18, (self.strip_canvas.winfo_width() - total_w) / 2)
        idx = int((event.x - sx) / (sw + gap))
        if 0 <= idx < n_strips:
            self.selected_channel = idx; self.nav_scope = "console"; self._sync_from_engine()

    def _toggle_channel_footer(self, idx: int, kind: str) -> None:
        if idx < 0 or idx >= len(self.engine.channels):
            return
        ch = self.engine.channels[idx]
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

    def _on_editor_canvas_click(self, event) -> None:
        self.nav_scope = "editor"
        for x0, y0, x1, y1, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if tag[0] == "stage_hdr":
                    self.editor_stage_col = tag[1]
                    self.editor_unified_header_focus = True
                    self.selected_stage_key = self._STAGE_GRID[tag[1]][0]
                    self._press_unified_editor_cell()
                elif tag[0] == "stage_param":
                    self.editor_stage_col = tag[1]
                    self.editor_param_row = tag[2]
                    self.editor_unified_header_focus = False
                    self.selected_stage_key = self._STAGE_GRID[tag[1]][0]
                    self._press_unified_editor_cell()
                self._sync_from_engine()
                return
        self._sync_from_engine()

    # --- Interaction Logic ---
    def _open_stage_editor(self, idx: int, key: str) -> None:
        self._capture_editor_return_context()
        self.selected_channel = self.editor_channel = idx
        self.selected_stage_key, self.nav_scope = key, "editor"
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

    def _handle_unified_editor_nav(self, target: str) -> None:
        focus_col = getattr(self, "editor_stage_col", 0)
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        params = self._STAGE_GRID[focus_col][2]
        
        if target == "up":
            if hdr_focus: pass # Top boundary
            else: self.editor_unified_header_focus = True
        elif target == "down":
            if hdr_focus:
                self.editor_unified_header_focus = False
                if params and params[0] == "TBE" and len(params) > 1:
                    self.editor_param_row = 1
            else:
                # Dive into transport
                self.nav_scope = "transport"
                self.transport_focus_row = 0
                self.transport_focus_col = focus_param % 5
        elif target == "left":
            if hdr_focus:
                self.editor_stage_col = (focus_col - 1) % len(self._STAGE_GRID)
                self.editor_param_row = 0
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
            else:
                self.editor_param_row = (focus_param - 1) % len(params)
        elif target == "right":
            if hdr_focus:
                self.editor_stage_col = (focus_col + 1) % len(self._STAGE_GRID)
                self.editor_param_row = 0
                self.selected_stage_key = self._STAGE_GRID[self.editor_stage_col][0]
            else:
                self.editor_param_row = (focus_param + 1) % len(params)
        elif target == "press":
            self._press_unified_editor_cell()
        self._sync_from_engine()

    def _press_unified_editor_cell(self) -> None:
        focus_col = getattr(self, "editor_stage_col", 0)
        focus_param = getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", True)
        stage_key, _hdr, params = self._STAGE_GRID[focus_col]; ch = self._current_channel()
        label = params[focus_param]
        
        with self.engine._lock:
            # Visual feedback
            self.editor_title.config(fg="#6ff0c1")
            self.root.after(100, lambda: self.editor_title.config(fg="white"))
            
            if hdr_focus:
                attr = f"{stage_key}_enabled"
                if stage_key == "harm": attr = "harmonics_enabled"
                if hasattr(ch, attr): setattr(ch, attr, not bool(getattr(ch, attr)))
            else:
                if stage_key in ("gate", "comp") and label == "FRQ":
                    if bool(getattr(ch, f"{stage_key}_band_enabled", False)):
                        setattr(ch, f"{stage_key}_band_enabled", False)
                        for band in getattr(ch, f"{stage_key}_dyn_bands"):
                            band["enabled"] = False
                    else:
                        self._enable_stage_band(ch, stage_key, 0)
                    self._sync_from_engine()
                    return
                if stage_key in ("gate", "comp") and label == "BND":
                    self._add_stage_band(ch, stage_key)
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
                            "harm": "harm_param_bypass", "trn": "tone_param_bypass", "xct": "tone_param_bypass", "tbe": "tone_param_bypass"}
                    bp_key = m_bp.get(stage_key)
                    if bp_key:
                        bp = getattr(ch, bp_key, {})
                        bp[label] = not bp.get(label, False)
                        setattr(ch, bp_key, bp)
        self._sync_from_engine()

    def _adjust_unified_editor_cell(self, axis_value: float) -> None:
        if abs(axis_value) < DISCRETE_TWIST_MIN:
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_editor_adjust_at", 0.0)) < 0.075:
            return
        self._last_editor_adjust_at = now
        axis_value = float(np.clip(axis_value, -1.0, 1.0)) * 0.34
        col = max(0, min(len(self._STAGE_GRID) - 1, self.editor_stage_col))
        sk, _, params = self._STAGE_GRID[col]; ch = self._current_channel()
        if getattr(self, "editor_unified_header_focus", False):
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
                    nxt = (cur + (1 if axis_value > 0 else -1)) % count
                    setattr(ch, f"{sk}_dyn_ui_band", nxt)
                    if sk == "gate":
                        self.engine._hydrate_gate_dyn_to_scalars(ch)
                    else:
                        self.engine._hydrate_comp_dyn_to_scalars(ch)
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
            ("eq",   "BND"): ("eq_width", "lin", 0.1, 6.0, 0.1),
            ("eq",   "TRN"): ("trn_freq", "log", 20.0, 20000.0, 0.1),
            ("eq",   "ATK"): ("trn_attack", "lin", -1.0, 1.0, 0.1),
            ("eq",   "SUT"): ("trn_sustain", "lin", -1.0, 1.0, 0.1),
            ("trn",  "FRQ"): ("trn_freq", "log", 20.0, 20000.0, 0.1),
            ("trn",  "ATK"): ("trn_attack", "lin", -1.0, 1.0, 0.1),
            ("trn",  "SUT"): ("trn_sustain", "lin", -1.0, 1.0, 0.1),
            ("trn",  "DRV"): ("trn_drive", "lin", 0.0, 1.0, 0.1),
            ("xct",  "FRQ"): ("xct_freq", "log", 20.0, 20000.0, 0.1),
            ("xct",  "ATK"): ("xct_attack", "lin", -1.0, 1.0, 0.1),
            ("xct",  "SUT"): ("xct_sustain", "lin", -1.0, 1.0, 0.1),
            ("xct",  "DRV"): ("xct_drive", "lin", 0.0, 1.0, 0.1),
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
                _log.info(f"ADJUST: {sk}:{label} -> {final:.4f} (ax={axis_value:.2f})")
        self._sync_from_engine()

    def _adjust_focused_axis(self, axis_value: float) -> None:
        ns = getattr(self, "nav_scope", "console")
        if ns == "transport":
            self._adjust_transport_axis(axis_value)
        elif ns == "console":
            self._adjust_console_channel_axis(axis_value)
        else:
            self._adjust_unified_editor_cell(axis_value)

    def _adjust_transport_axis(self, axis_value: float) -> None:
        if abs(axis_value) < DISCRETE_TWIST_MIN:
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_transport_adjust_at", 0.0)) < 0.09:
            return
        self._last_transport_adjust_at = now
        axis_value = float(np.clip(axis_value, -1.0, 1.0)) * 0.28
        tr = getattr(self, "transport_focus_row", 0)
        tc = getattr(self, "transport_focus_col", 0)
        btn = self._transport_button_at(tr, tc)
        if not btn:
            return
        action = btn[0]
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
        self.selected_channel = (self.selected_channel + (1 if val > 0 else -1)) % self._channel_nav_span()
        self._sync_from_engine()

    # --- Helpers ---
    def _stage_label(self, key: str) -> str:
        return {"pre": "Mic Pre", "harm": "Harmonics", "gate": "Gate", "comp": "Compressor", "eq": "EQ", "trn": "Transient", "xct": "Exciter", "tbe": "Tube"}.get(key, key.upper())

    def _stage_cell_value(self, ch: ChannelState, stage_key: str, label: str) -> Tuple[str, bool]:
        sk_en = f"{stage_key}_enabled"
        if stage_key == "harm": sk_en = "harmonics_enabled"
        active = getattr(ch, sk_en, True)
        
        bp_key = {"gate":"gate_param_bypass","comp":"comp_param_bypass","eq":"eq_param_bypass","harm":"harm_param_bypass","trn":"tone_param_bypass","xct":"tone_param_bypass","tbe":"tone_param_bypass"}.get(stage_key)
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
                return (f"B{slot + 1}/{count}", True)
            pre = "gate_" if stage_key=="gate" else "comp_"
            if label == "THR": return (f"{getattr(ch, pre+'threshold_db'):.1f}", active)
            if stage_key == "gate" and label == "DEP": return (f"{float(getattr(ch, 'gate_ratio')) * 4.0:.0f}dB", active)
            if label == "RAT": return (f"{getattr(ch, pre+'ratio'):.2f}", active)
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
            if label == "BND": return ((("ON " if ch.eq_band_enabled else "off ") + f"{ch.eq_width:.2f}"), bool(ch.eq_band_enabled))
            if label == "SHP": return ("ON" if not bp.get("SHP", False) else "off", not bp.get("SHP", False) and active)
            if label == "TRN": return (f"{ch.trn_freq:.0f}", active)
            if label == "ATK": return (f"{ch.trn_attack:+.2f}", active)
            if label == "SUT": return (f"{ch.trn_sustain:+.2f}", active)
            if label == "BD2": return ("ON" if ch.limit_band_enabled else "off", bool(ch.limit_band_enabled))
        if stage_key == "trn":
            if label == "ATK": return (f"{ch.trn_attack:+.2f}", active)
            if label == "SUT": return (f"{ch.trn_sustain:+.2f}", active)
            if label == "DRV": return (f"{ch.trn_drive:.2f}", active)
            if label == "FRQ": return (f"{ch.trn_freq:.0f}", active)
            if label == "BND": return ("ON" if ch.trn_band_enabled else "off", bool(ch.trn_band_enabled))
        if stage_key == "xct":
            if label == "ATK": return (f"{ch.xct_attack:+.2f}", active)
            if label == "SUT": return (f"{ch.xct_sustain:+.2f}", active)
            if label == "DRV": return (f"{ch.xct_drive:.2f}", active)
            if label == "FRQ": return (f"{ch.xct_freq:.0f}", active)
            if label == "BND": return ("ON" if ch.xct_band_enabled else "off", bool(ch.xct_band_enabled))
        if stage_key == "tbe":
            if label == "DRV": return (f"{ch.tbe_drive:.2f}", active)
            if label == "BND": return ("ON" if ch.tbe_band_enabled else "off", bool(ch.tbe_band_enabled))
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
        need = 10 + 32 + 8 + 48 + 10
        self.editor_canvas.config(height=int(need))

    def _transport_button_at(self, r: int, c: int) -> Optional[Tuple[str, str, str, str]]:
        return next(((k, l, clr, glyph) for row, col, k, l, clr, glyph in self._TRANSPORT_BUTTONS if row==r and col==c), None)

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

    def _draw_send_knob(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float, focused: bool = False, channel_idx: int = -1) -> None:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        r = max(8, min((x1 - x0), (y1 - y0)) / 2 - 4)
        send_mode = bool(getattr(self, "knobs_send_mode", False))
        send_muted = bool(getattr(ch, "send_muted", False)) and send_mode
        if focused: c.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4, outline="#7cf0a9", width=2)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1a2330" if not send_muted else "#141a20", outline="#33485e" if not send_muted else "#2a323d", width=1)
        c.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62, fill="#0f161f", outline="#28394d", width=1)
        if send_mode:
            val = float(np.clip(getattr(ch, "send_level", 0.0), 0.0, 1.0))
            angle_deg = -90 - 135 + val * 270.0; ind_color = "#ff8c1a" if not send_muted else "#5b6c80"
        else:
            pan = float(np.clip(getattr(ch, "pan", 0.0), -1.0, 1.0))
            angle_deg = -90 + pan * 135.0; ind_color = "#7cd7ff"
        angle = math.radians(angle_deg)
        c.create_line(cx, cy, cx + math.cos(angle)*(r-3), cy + math.sin(angle)*(r-3), fill=ind_color, width=2)
        face_text = f"S{getattr(ch, 'send_slot', 1)}" if send_mode else "PAN"
        c.create_text(cx, cy - 1, text=face_text, fill="#9aa6b6" if send_muted else "#d6e1ec", font=("Segoe UI", 7, "bold"))

    def _draw_strip_fader(self, c: tk.Canvas, ch: ChannelState, x0: float, y0: float, x1: float, y1: float, is_master: bool, focused: bool = False) -> None:
        cx, track_w = (x0 + x1) / 2, max(4, (x1 - x0) - 6)
        if focused: c.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#5ef0b0", width=2)
        c.create_rectangle(cx - track_w/2, y0, cx + track_w/2, y1, fill="#10151b", outline="#28323d")
        meter_fill = float(np.clip(getattr(ch, "level", 0.0), 0.0, 1.0))
        if meter_fill > 0.001:
            my = y1 - (y1 - y0) * meter_fill
            mc = "#5ef0b0" if meter_fill < 0.7 else ("#f7c46f" if meter_fill < 0.9 else "#ff6868")
            c.create_rectangle(cx - track_w/2 + 2, my, cx + track_w/2 - 2, y1 - 2, fill=mc, outline="")
        gain = float(np.clip(getattr(ch, "gain", 1.0), 0.3, 2.2))
        frac = (gain - 0.3) / 0.7 * 0.7 if gain <= 1.0 else 0.7 + (gain - 1.0) / 1.2 * 0.3
        ty = y1 - (y1 - y0) * frac; tw = (x1 - x0) + 4
        c.create_rectangle(cx - tw/2, ty - 7, cx + tw/2, ty + 7, fill="#ff8c1a" if not is_master else "#7cf0a9", outline="#1a1a1a")
        c.create_line(cx - tw/2 + 2, ty, cx + tw/2 - 2, ty, fill="#1a1a1a", width=1)

    def _stage_enabled(self, ch: ChannelState, key: str) -> bool:
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

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
    GRID_HEADER_H_NORMAL = 34
    GRID_CELL_H_NORMAL = 42
    STRIP_WIDTH = 72

    _STAGE_GRID = [
        ("pre",  "PRE", ["TBE", "LPF", "48V", "PHS", "HPF"]),
        ("harm", "HRM", ["TBE", "H1", "H2", "H3", "H4", "H5"]),
        ("gate", "GTE", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("comp", "CMP", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]),
        ("eq",   "EQ",  ["TBE", "FRQ", "GAN", "SHP", "BND", "TRN", "ATK", "SUT", "BD2"]),
        ("trn",  "TRN", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("xct",  "XCT", ["FRQ", "ATK", "SUT", "DRV", "BND"]),
        ("tbe",  "TBE", ["DRV", "BND"]),
    ]

    _STAGE_HEADER_FILL = {
        "pre": "#7cf0a9", "harm": "#5cb8ff", "gate": "#ddc270", "comp": "#ff7d6e",
        "eq": "#b08bff", "trn": "#36e0dc", "xct": "#c06cff", "tbe": "#ff8f3a"
    }

    _TRANSPORT_BUTTONS = [
        (0, 0, "play", "PLY", "#6ff0c1", "▶"),
        (0, 1, "stop", "STP", "#ff6a53", "■"),
        (0, 2, "rewind", "REW", "#89a0b6", "«"),
        (0, 3, "fastforward", "FFD", "#89a0b6", "»"),
        (0, 4, "record", "REC", "#ff3b30", "●"),
        (1, 0, "oscillator", "OSC", "#fbbf24", "∿"),
        (1, 1, "pink", "PNK", "#f472c0", "░"),
        (1, 2, "white", "WHT", "#7dd3fc", "▒"),
        (1, 3, "pink_pulse", "PLS", "#fbcfe8", "⌇"),
        (1, 4, "white_hot", "HOT", "#38bdf8", "🔥"),
    ]

    # --- Initialization & Build ---
    def _init_editor_state_vars(self) -> None:
        self.pre_vars = {k: tk.DoubleVar() if k in ("gain", "pan", "lpf_hz", "hpf_hz") else tk.BooleanVar() 
                         for k in ("enabled", "phase", "tube", "lpf_enabled", "hpf_enabled", "phantom", "gain", "pan", "lpf_hz", "hpf_hz")}
        self.harm_vars = {"enabled": tk.BooleanVar(), "makeup": tk.DoubleVar()}
        self.harm_weight_vars = [tk.DoubleVar() for _ in range(5)]
        self.gate_vars = {"enabled": tk.BooleanVar(), "threshold": tk.DoubleVar(), "ratio": tk.DoubleVar(), "attack": tk.DoubleVar(), "release": tk.DoubleVar(), "makeup": tk.DoubleVar()}
        self.comp_vars = {"enabled": tk.BooleanVar(), "threshold": tk.DoubleVar(), "ratio": tk.DoubleVar(), "attack": tk.DoubleVar(), "release": tk.DoubleVar(), "makeup": tk.DoubleVar()}
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
        transport_dock = tk.Frame(left, bg="#0c1118", bd=0, highlightthickness=1, highlightbackground="#283242"); transport_dock.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.transport_panel = self._build_transport_panel(transport_dock); self.transport_panel.pack(fill="x", padx=6, pady=8)
        self.strip_canvas = tk.Canvas(left, bg="#1c222a", highlightthickness=0); self.strip_canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.strip_canvas.bind("<Button-1>", self._on_strip_click)
        self.editor_frame = right; self._build_editor(right)
        self._bind_nav_keys()

    def _build_editor(self, parent: tk.Frame) -> None:
        self.focus_canvas = tk.Canvas(parent, bg="#10151b", highlightthickness=0, height=280); self.focus_canvas.pack(fill="x", padx=8, pady=8)
        self.editor_canvas = tk.Canvas(parent, bg="#10151b", highlightthickness=0); self.editor_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.editor_canvas.bind("<Button-1>", self._on_editor_canvas_click)

    def _build_transport_panel(self, parent: tk.Frame) -> tk.Frame:
        f = tk.Frame(parent, bg="#0c1118")
        self.transport_cells = {}
        for r, c, k, l, clr, glyph in self._TRANSPORT_BUTTONS:
            btn = tk.Label(f, text=f"{glyph}\n{l}", bg="#151a21", fg=clr, font=("Segoe UI", 9, "bold"), width=8, height=3, relief="flat", bd=2)
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            self.transport_cells[(r, c)] = btn
        return f

    def _bind_nav_keys(self) -> None:
        self.root.bind("<Left>", lambda e: self._handle_nav("left"))
        self.root.bind("<Right>", lambda e: self._handle_nav("right"))
        self.root.bind("<Up>", lambda e: self._handle_nav("up"))
        self.root.bind("<Down>", lambda e: self._handle_nav("down"))
        self.root.bind("<Return>", lambda e: self._handle_nav("press"))
        self.root.bind("<Escape>", lambda e: self._handle_nav("back"))

    # --- Transport Actions ---
    def _tx_play(self) -> None: self.engine.toggle_play(); self._sync_from_engine()
    def _tx_stop(self) -> None: self.engine.stop(); self._sync_from_engine()
    def _tx_rewind(self) -> None: self.engine.rewind(); self._sync_from_engine()
    def _tx_forward(self) -> None: self.engine.jump_forward(); self._sync_from_engine()
    def _tx_record(self) -> None: pass # Placeholder

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
            self.pre_vars["lpf_hz"].set(ch.lpf_hz)
            self.pre_vars["hpf_hz"].set(ch.hpf_hz)
            
            self.harm_vars["enabled"].set(ch.harmonics_enabled)
            for i, v in enumerate(ch.harmonics): self.harm_weight_vars[i].set(v)
            
            self.comp_vars["enabled"].set(ch.comp_enabled)
            self.eq_vars["enabled"].set(ch.eq_enabled)
            
            self._draw_strips()
            self._draw_focus()
            self._draw_editor_controls()
            self._sync_play_transport_glyph()
        except Exception: _log.error(traceback.format_exc())
        self._syncing_controls = False

    def _sync_play_transport_glyph(self) -> None:
        p_cell = self.transport_cells.get((0, 0))
        if not p_cell: return
        active = getattr(self.engine, "playing", False)
        p_cell.config(bg="#1c2a26" if active else "#151a21", fg="#6ff0c1" if active else "#4a635a")

    # --- Geometry & Drawing Support ---
    def _focus_geometry(self, w: int, h: int) -> Tuple[float, float, float, float, float, float]:
        cx, cy = w / 2, h / 2
        outer_rx = min(w, h) * 0.46
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

    def _draw_focus_signal(self, c: tk.Canvas, ch: ChannelState, cx: float, cy: float, orx: float, ory: float, irx: float, iry: float) -> None:
        rings = getattr(ch, "band_levels", None)
        if rings is None: return
        for i in range(POL_BANDS):
            val = float(np.clip(rings[i], 0.0, 1.0))
            if val < 0.005: continue
            p = i / (POL_BANDS - 1)
            rx, ry = orx - (orx - irx) * p, ory - (ory - iry) * p
            hue = freq_rainbow_hue_hz(POL_BAND_CENTER_HZ[i])
            color = hsv_to_hex(hue, 0.7, 0.4 + val * 0.5)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=1 + val * 3)

    def _draw_focus(self) -> None:
        c = self.focus_canvas
        if c.winfo_width() <= 1: c.update_idletasks()
        c.delete("all")
        w, h = max(c.winfo_width(), 380), max(c.winfo_height(), 250)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        ch = self._current_channel()
        sk = getattr(self, "selected_stage_key", "pre")
        if sk == "pre": self._draw_focus_mic_pre(c, ch, w, h)
        elif sk == "harm": self._draw_focus_harmonics(c, ch, w, h)
        elif sk == "gate": self._draw_focus_gate(c, ch, w, h)
        elif sk == "comp": self._draw_focus_compressor(c, ch, w, h)
        elif sk == "eq": self._draw_focus_eq(c, ch, w, h)
        else: self._draw_focus_tone(c, ch, w, h)

    def _draw_focus_eq(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        if not ch.eq_enabled:
            c.create_text(cx, h - 40, text="EQ BYPASSED", fill="#5d6b7c", font=("Segoe UI", 10, "bold"))
            return
        c.create_text(cx, h - 40, text="EQ ACTIVE", fill="#b08bff", font=("Segoe UI", 10, "bold"))

    def _draw_focus_mic_pre(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        c.create_text(cx, h - 40, text="MIC PRE", fill="#7cf0a9", font=("Segoe UI", 10, "bold"))

    def _draw_focus_harmonics(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        c.create_text(cx, h - 40, text="HARMONICS", fill="#5cb8ff", font=("Segoe UI", 10, "bold"))

    def _draw_focus_gate(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        c.create_text(cx, h - 40, text="GATE", fill="#ddc270", font=("Segoe UI", 10, "bold"))

    def _draw_focus_compressor(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        c.create_text(cx, h - 40, text="COMPRESSOR", fill="#ff7d6e", font=("Segoe UI", 10, "bold"))

    def _draw_focus_tone(self, c: tk.Canvas, ch: ChannelState, w: int, h: int) -> None:
        cx, cy, orx, ory, irx, iry = self._focus_geometry(w, h)
        self._draw_focus_ring_grid(c, cx, cy, orx, ory, irx, iry)
        self._draw_focus_signal(c, self.engine.master_channel, cx, cy, orx, ory, irx, iry)
        sk = getattr(self, "selected_stage_key", "tbe")
        fill = self._STAGE_HEADER_FILL.get(sk, "#ff8f3a")
        c.create_text(cx, h - 40, text=self._stage_label(sk).upper(), fill=fill, font=("Segoe UI", 10, "bold"))

    # --- Editor Renders ---
    def _draw_editor_controls(self) -> None:
        self._autosize_editor_canvas_height()
        c = self.editor_canvas; c.delete("all")
        w, h = max(c.winfo_width(), 380), max(c.winfo_height(), 340)
        c.create_rectangle(0, 0, w, h, fill="#10151b", outline="")
        self._draw_unified_editor(c, w, h, self._current_channel())

    def _draw_unified_editor(self, c: tk.Canvas, w: int, h: int, ch: ChannelState) -> None:
        self.editor_hitboxes = []
        margin, gap, cols = 12, 4, len(self._STAGE_GRID)
        col_w = (w - margin * 2 - gap * (cols - 1)) / cols
        focus_col, focus_row = getattr(self, "editor_stage_col", 0), getattr(self, "editor_param_row", 0)
        hdr_focus = getattr(self, "editor_unified_header_focus", False)
        for ci, (sk, hdr, params) in enumerate(self._STAGE_GRID):
            x0 = margin + ci * (col_w + gap)
            x1 = x0 + col_w
            hc = self._STAGE_HEADER_FILL.get(sk, "#9aa6b6")
            col_foc = (getattr(self, "nav_scope", "") == "editor" and ci == focus_col)
            c.create_rectangle(x0, 12, x1, 12+34, outline="#e8f0f8" if col_foc and hdr_focus else "#2a3848", width=3 if col_foc and hdr_focus else 1, fill="#15202c")
            c.create_text((x0+x1)/2, 12+17, text=hdr, fill=hc, font=("Segoe UI", 11, "bold"))
            self.editor_hitboxes.append((x0, 12, x1, 12+34, ("stage_hdr", ci)))
            for ri, lbl in enumerate(params):
                cy0, cy1 = 12+34+4 + ri*(42+2), 12+34+4 + ri*(42+2) + 42
                val, en = self._stage_cell_value(ch, sk, lbl)
                is_f = (getattr(self, "nav_scope", "") == "editor" and col_foc and ri == focus_row and not hdr_focus)
                c.create_rectangle(x0, cy0, x1, cy1, outline="#7cf0a9" if is_f else "#2a3848", width=2 if is_f else 1, fill="#1d2c39" if en else "#131a22")
                c.create_text((x0+x1)/2, cy0+11, text=lbl, fill="#f2f3f6" if en else "#7d8a9b", font=("Segoe UI", 9, "bold"))
                c.create_text((x0+x1)/2, cy1-11, text=val, fill=hc if en else "#5d6b7c", font=("Segoe UI", 9))
                self.editor_hitboxes.append((x0, cy0, x1, cy1, ("stage_col", ci, ri)))

    def _draw_strips(self) -> None:
        c = self.strip_canvas; c.delete("all")
        w, h = max(c.winfo_width(), 980), max(c.winfo_height(), 720)
        c.create_rectangle(0, 0, w, h, fill="#0c1014", outline="")
        sw, gap = self.STRIP_WIDTH, 8
        sources = list(self.engine.channels) + [self.engine.master_channel]
        tw = len(sources)*sw + (len(sources)-1)*gap
        sx = max(18, (w - tw)/2)
        for i, ch in enumerate(sources):
            x0, x1 = sx + i*(sw+gap), sx + i*(sw+gap) + sw
            is_s = (i == self.selected_channel)
            c.create_rectangle(x0, 24, x1, h-14, fill="#181e25", outline="#7cf0a9" if is_s and getattr(self, "nav_scope", "")=="console" else "#30404f", width=2 if is_s else 1)

    # --- Events ---
    def _poll_spacemouse(self) -> None:
        res = self.spacemouse.poll()
        if not res: return
        val, pr, dr = res
        if "twist_cw_hold" in dr: self._handle_twist_cw_editor_enter()
        elif "twist_ccw_hold" in dr: self._handle_twist_ccw_editor_exit()
        elif dr: [self._handle_nav(d) for d in dr]
        elif pr and 0 in pr: self._handle_nav("press")
        else:
            ns = getattr(self, "nav_scope", "console")
            if ns == "editor": self._adjust_unified_editor_cell(val)
            elif ns == "console": self._adjust_console_channel_axis(val)

    def _handle_nav(self, target: str) -> None:
        ns = getattr(self, "nav_scope", "console")
        if ns == "editor": self._handle_unified_editor_nav(target)
        elif ns == "console": self._handle_console_nav(target)
        elif ns == "transport": self._handle_transport_nav(target)

    def _handle_console_nav(self, target: str) -> None:
        sk = self._console_stage_keys()
        si = sk.index(self.selected_stage_key) if getattr(self, "console_row", "")=="stages" else 0
        span = self._channel_nav_span()
        if target == "left": self.selected_channel = (self.selected_channel - 1) % span
        elif target == "right": self.selected_channel = (self.selected_channel + 1) % span
        elif target == "up":
            if getattr(self, "console_row", "") == "stages" and si > 0: self.selected_stage_key = sk[si-1]
            else: self.console_row = "record"
        elif target == "down":
            if getattr(self, "console_row", "") == "stages" and si < len(sk)-1: self.selected_stage_key = sk[si+1]
            else: self.console_row = "knob"
        elif target == "press": self._open_stage_editor(self.selected_channel, self.selected_stage_key)
        self._sync_from_engine()

    def _handle_unified_editor_nav(self, target: str) -> None:
        cols = len(self._STAGE_GRID)
        ci, ri = getattr(self, "editor_stage_col", 0), getattr(self, "editor_param_row", 0)
        hn = getattr(self, "editor_unified_header_focus", False)
        if target == "left" and ci > 0: self.editor_stage_col -= 1; self.selected_stage_key = self._STAGE_GRID[ci-1][0]
        elif target == "right" and ci < cols-1: self.editor_stage_col += 1; self.selected_stage_key = self._STAGE_GRID[ci+1][0]
        elif target == "up":
            if not hn:
                if ri > 0: self.editor_param_row -= 1
                else: self.editor_unified_header_focus = True
        elif target == "down":
            if hn: self.editor_unified_header_focus = False; self.editor_param_row = 0
            else: self.editor_param_row = min(len(self._STAGE_GRID[ci][2])-1, ri + 1)
        elif target == "press": self._press_unified_editor_cell()
        elif target == "back": self._exit_editor_to_console()
        self._sync_from_engine()

    def _handle_transport_nav(self, target: str) -> None:
        if target == "back": self._exit_transport_to_console()
        elif target == "press":
            btn = self._transport_button_at(getattr(self, "transport_focus_row", 0), getattr(self, "transport_focus_col", 0))
            if btn: getattr(self, f"_tx_{btn[0]}", lambda: None)()

    def _on_strip_click(self, event) -> None:
        self.root.after_idle(self.root.focus_set)
        sw, gap = self.STRIP_WIDTH, 8
        n_strips = len(self.engine.channels) + 1
        total_w = n_strips * sw + (n_strips - 1) * gap
        sx = max(18, (self.strip_canvas.winfo_width() - total_w) / 2)
        idx = int((event.x - sx) / (sw + gap))
        if 0 <= idx < n_strips:
            self.selected_channel = idx; self.nav_scope = "console"; self._sync_from_engine()

    def _on_editor_canvas_click(self, event) -> None:
        for x0, y0, x1, y1, tag in getattr(self, "editor_hitboxes", []):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                if tag[0] == "stage_hdr":
                    self.editor_stage_col = tag[1]; self.editor_unified_header_focus = True
                    self.selected_stage_key = self._STAGE_GRID[tag[1]][0]
                    self._press_unified_editor_cell()
                elif tag[0] == "stage_col":
                    self.editor_stage_col = tag[1]; self.editor_param_row = tag[2]
                    self.editor_unified_header_focus = False
                    self.selected_stage_key = self._STAGE_GRID[tag[1]][0]
                    self._press_unified_editor_cell()
                self._sync_from_engine(); return

    # --- Interaction Logic ---
    def _open_stage_editor(self, idx: int, key: str) -> None:
        self._capture_editor_return_context()
        self.selected_channel = self.editor_channel = idx
        self.selected_stage_key, self.nav_scope = key, "editor"
        self.editor_stage_col = next((i for i, r in enumerate(self._STAGE_GRID) if r[0]==key), 0)
        self.editor_param_row, self.editor_unified_header_focus = 0, False
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

    def _handle_twist_ccw_editor_exit(self) -> None:
        if getattr(self, "nav_scope", "") == "editor": self._exit_editor_to_console()

    def _press_unified_editor_cell(self) -> None:
        ci, ri = getattr(self, "editor_stage_col", 0), getattr(self, "editor_param_row", 0)
        hn = getattr(self, "editor_unified_header_focus", False)
        sk, _, params = self._STAGE_GRID[ci]; ch = self._current_channel()
        with self.engine._lock:
            if hn: setattr(ch, f"{sk}_enabled", not bool(getattr(ch, f"{sk}_enabled")))
            else:
                lbl = params[ri]
                m = {"TBE": "tube", "LPF": "lpf_enabled", "48V": "phantom", "PHS": "phase", "HPF": "hpf_enabled"}
                attr = m.get(lbl)
                if attr: setattr(ch, attr, not bool(getattr(ch, attr)))
        self._sync_from_engine()

    def _adjust_unified_editor_cell(self, val: float) -> None:
        if getattr(self, "editor_unified_header_focus", False): return
        ci, ri = getattr(self, "editor_stage_col", 0), getattr(self, "editor_param_row", 0)
        sk, _, params = self._STAGE_GRID[ci]; lbl = params[ri]; ch = self._current_channel()
        with self.engine._lock:
            if sk == "pre" and lbl == "LPF": ch.lpf_hz = float(np.clip(ch.lpf_hz * math.exp(val * 0.08), 200.0, POL_HIGH_HZ))
            elif sk == "pre" and lbl == "HPF": ch.hpf_hz = float(np.clip(ch.hpf_hz * math.exp(val * 0.08), POL_LOW_HZ, 1500.0))
        self._sync_from_engine()

    def _adjust_console_channel_axis(self, val: float) -> None:
        if abs(val) < DISCRETE_TWIST_MIN: return
        self.selected_channel = (self.selected_channel + (1 if val > 0 else -1)) % self._channel_nav_span()
        self._sync_from_engine()

    # --- Helpers ---
    def _stage_label(self, key: str) -> str:
        return {"pre": "Mic Pre", "harm": "Harmonics", "gate": "Gate", "comp": "Compressor", "eq": "EQ", "trn": "Transient", "xct": "Exciter", "tbe": "Tube"}.get(key, key.upper())

    def _stage_cell_value(self, ch: ChannelState, stage_key: str, label: str) -> Tuple[str, bool]:
        if stage_key == "pre":
            if label == "TBE": return ("ON" if ch.tube else "off", bool(ch.tube))
            if label == "LPF": return (f"{ch.lpf_hz:.0f}", bool(ch.lpf_enabled))
            if label == "48V": return ("ON" if ch.phantom else "off", bool(ch.phantom))
            if label == "PHS": return ("INV" if ch.phase else "off", bool(ch.phase))
            if label == "HPF": return (f"{ch.hpf_hz:.0f}", bool(ch.hpf_enabled))
        if stage_key == "eq":
            if label == "BND": return ("on" if ch.eq_band_enabled else "off", bool(ch.eq_band_enabled))
            if label == "FRQ": return (f"{ch.eq_freq:.0f}", bool(ch.eq_enabled))
            if label == "GAN": return (f"{ch.eq_gain_db:+.1f}", bool(ch.eq_enabled))
        return ("-", False)

    def _autosize_editor_canvas_height(self) -> None:
        max_rows = max(len(cols[2]) for cols in self._STAGE_GRID)
        need = 12 + self.GRID_HEADER_H_NORMAL + 4 + max_rows * (self.GRID_CELL_H_NORMAL + 2) + 14
        self.editor_canvas.config(height=int(need))

    def _transport_button_at(self, r: int, c: int) -> Optional[Tuple[str, str]]:
        return next(((k, l) for row, col, k, l, *_ in self._TRANSPORT_BUTTONS if row==r and col==c), None)

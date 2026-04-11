import math
import threading
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
import pygame
import sounddevice as sd
import soundfile as sf


TOGGLES = ["48V", "Phase", "Tube"]


@dataclass
class MicPreState:
    gain_db: float = 0.0
    focus_ring: int = 0
    phantom: bool = False
    phase: bool = False
    tube: bool = False


class MicPreProcessor:
    def __init__(self, samplerate: int):
        self.samplerate = samplerate
        self.state = MicPreState()
        self._lock = threading.Lock()
        self.low_lp = np.zeros(2, dtype=np.float32)
        self.high_lp = np.zeros(2, dtype=np.float32)

    def get_state(self) -> MicPreState:
        with self._lock:
            return MicPreState(**self.state.__dict__)

    def set_gain(self, gain_db: float):
        with self._lock:
            self.state.gain_db = float(np.clip(gain_db, -24.0, 36.0))

    def set_focus_ring(self, ring_index: int):
        with self._lock:
            self.state.focus_ring = int(np.clip(ring_index, 0, 3))

    def toggle(self, name: str):
        with self._lock:
            if name == "48V":
                self.state.phantom = not self.state.phantom
            elif name == "Phase":
                self.state.phase = not self.state.phase
            elif name == "Tube":
                self.state.tube = not self.state.tube

    def process(self, block: np.ndarray) -> np.ndarray:
        state = self.get_state()
        x = block.astype(np.float32, copy=True)
        gain = 10 ** (state.gain_db / 20.0)
        x *= gain

        if state.phase:
            x *= -1.0

        x = self._apply_focus(x, state.focus_ring)

        if state.tube:
            drive = 1.8 + state.focus_ring * 0.8
            x = np.tanh(x * drive) / np.tanh(drive)

        return np.clip(x, -1.0, 1.0)

    def _apply_focus(self, x: np.ndarray, ring_index: int) -> np.ndarray:
        if ring_index == 0:
            return x

        low_cutoffs = [140.0, 480.0, 1800.0]
        cutoff = low_cutoffs[ring_index - 1]
        alpha = math.exp(-2.0 * math.pi * cutoff / self.samplerate)
        y = np.empty_like(x)
        for i in range(x.shape[0]):
            self.low_lp = alpha * self.low_lp + (1.0 - alpha) * x[i]
            low = self.low_lp
            high = x[i] - low
            if ring_index == 1:
                y[i] = low * 1.15 + high * 0.82
            elif ring_index == 2:
                mid = x[i] - (low * 0.72 + high * 0.72)
                y[i] = low * 0.78 + mid * 1.28 + high * 0.78
            else:
                y[i] = low * 0.72 + high * 1.18
        return y


class AudioEngine:
    def __init__(self):
        self.audio = np.zeros((1, 2), dtype=np.float32)
        self.samplerate = 48000
        self.position = 0
        self.loop = True
        self.playing = False
        self.stream = None
        self.processor = MicPreProcessor(self.samplerate)
        self._lock = threading.Lock()

    def load_file(self, path: Path):
        data, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
        if data.shape[1] > 2:
            data = data[:, :2]
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        with self._lock:
            self.audio = data
            self.samplerate = samplerate
            self.position = 0
            self.processor = MicPreProcessor(self.samplerate)
        self._restart_stream()

    def toggle_play(self):
        self.playing = not self.playing

    def stop(self):
        self.playing = False
        with self._lock:
            self.position = 0

    def _restart_stream(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=2,
            dtype="float32",
            blocksize=512,
            callback=self._callback,
        )
        self.stream.start()

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            if not self.playing or self.audio.size == 0:
                outdata[:] = 0
                return
            end = self.position + frames
            if end <= len(self.audio):
                block = self.audio[self.position:end]
                self.position = end
            else:
                remaining = len(self.audio) - self.position
                head = self.audio[self.position:] if remaining > 0 else np.zeros((0, 2), dtype=np.float32)
                if self.loop:
                    tail_frames = frames - len(head)
                    tail = self.audio[:tail_frames]
                    block = np.vstack([head, tail])
                    self.position = tail_frames
                else:
                    block = np.vstack([head, np.zeros((frames - len(head), 2), dtype=np.float32)])
                    self.position = len(self.audio)
                    self.playing = False
        outdata[:] = self.processor.process(block)


class JimmyMicPreApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Jimmy Mic Pre Prototype")
        self.root.geometry("980x720")
        self.root.configure(bg="#252a31")
        self.engine = AudioEngine()
        self.spacemouse = self._init_spacemouse()
        self.file_var = tk.StringVar(value="No file loaded")
        self.status_var = tk.StringVar(value="Load a stereo file, then use the SpaceMouse for gain and focus.")
        self.gain_var = tk.DoubleVar(value=0.0)
        self.selected_toggle = tk.StringVar(value="48V")
        self.axis_gain = tk.StringVar(value="+0.00")
        self.axis_focus = tk.StringVar(value="+0.00")
        self.ring_var = tk.StringVar(value="Wide")
        self.toggle_vars = {name: tk.StringVar(value="Off") for name in TOGGLES}
        self.ring_canvas = None
        self._build_ui()
        self._poll_spacemouse()
        self.refresh_ui()

    def _init_spacemouse(self):
        pygame.init()
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            joy = pygame.joystick.Joystick(i)
            joy.init()
            if "SpaceMouse" in joy.get_name() or "3Dconnexion" in joy.get_name():
                self.status_var.set(f"Connected: {joy.get_name()}")
                return joy
        self.status_var.set("SpaceMouse not found. Use the manual controls.")
        return None

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#252a31")
        style.configure("TLabel", background="#252a31", foreground="#eef3f8")
        style.configure("Header.TLabel", font=("Orbitron", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#b9c6d6")
        style.configure("Toggle.TButton", padding=8)

        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Jimmy Mic Pre Prototype", style="Header.TLabel").pack(anchor="w")
        ttk.Label(container, text="Real stereo playback through one Mic Pre stage: gain, polar focus, 48V, phase, tube.", style="Sub.TLabel").pack(anchor="w", pady=(3, 10))

        top = ttk.Frame(container)
        top.pack(fill="x", pady=(0, 12))
        ttk.Button(top, text="Load Audio", command=self.load_audio).pack(side="left")
        ttk.Button(top, text="Play / Pause", command=self.engine.toggle_play).pack(side="left", padx=6)
        ttk.Button(top, text="Stop", command=self.engine.stop).pack(side="left")
        ttk.Checkbutton(top, text="Loop", command=self.toggle_loop).pack(side="left", padx=(10, 0))
        ttk.Label(top, textvariable=self.file_var, style="Sub.TLabel").pack(side="left", padx=12)

        layout = ttk.Frame(container)
        layout.pack(fill="both", expand=True)

        left = ttk.LabelFrame(layout, text="Mic Pre", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ttk.Label(left, text="Gain", style="Sub.TLabel").pack(anchor="w")
        gain_scale = ttk.Scale(left, from_=-24, to=36, variable=self.gain_var, command=self.on_gain)
        gain_scale.pack(fill="x", pady=(4, 8))
        ttk.Label(left, textvariable=self.gain_var).pack(anchor="w")

        ttk.Label(left, text="Polar Focus", style="Sub.TLabel").pack(anchor="w", pady=(10, 4))
        self.ring_canvas = tk.Canvas(left, width=420, height=420, bg="#1e2328", highlightthickness=1, highlightbackground="#6dd9ef")
        self.ring_canvas.pack(pady=(0, 8))
        ttk.Label(left, textvariable=self.ring_var, style="Sub.TLabel").pack(anchor="w")

        toggle_row = ttk.Frame(left)
        toggle_row.pack(fill="x", pady=(12, 0))
        for name in TOGGLES:
            btn = ttk.Button(toggle_row, text=f"{name}: Off", command=lambda n=name: self.toggle_switch(n))
            btn.pack(side="left", padx=(0, 8))
            setattr(self, f"{name.lower().replace(' ', '_')}_button", btn)

        right = ttk.LabelFrame(layout, text="SpaceMouse Logic", padding=12)
        right.pack(side="right", fill="y")

        ttk.Label(right, text="Current Mapping", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(right, text="Turn / horizontal motion -> Gain").pack(anchor="w", pady=(4, 2))
        ttk.Label(right, text="Vertical motion -> Tighten / loosen focus ring").pack(anchor="w", pady=2)
        ttk.Label(right, text="Selected click target -> toggle 48V / Phase / Tube").pack(anchor="w", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Axis Readout", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.axis_gain).pack(anchor="w", pady=(4, 2))
        ttk.Label(right, textvariable=self.axis_focus).pack(anchor="w", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Toggle Selection", style="Sub.TLabel").pack(anchor="w")
        for name in TOGGLES:
            ttk.Radiobutton(right, text=name, value=name, variable=self.selected_toggle).pack(anchor="w", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Status", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.status_var, wraplength=260, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def toggle_loop(self):
        self.engine.loop = not self.engine.loop

    def load_audio(self):
        path = filedialog.askopenfilename(
            title="Choose stereo audio file",
            filetypes=[("Audio", "*.wav *.aiff *.aif *.flac *.ogg *.mp3"), ("All files", "*.*")],
        )
        if not path:
            return
        file_path = Path(path)
        self.engine.load_file(file_path)
        self.file_var.set(file_path.name)
        self.status_var.set(f"Loaded {file_path.name}. Gain and polar focus are now live.")
        self.refresh_ui()

    def on_gain(self, value: str):
        self.engine.processor.set_gain(float(value))
        self.refresh_ui()

    def toggle_switch(self, name: str):
        self.engine.processor.toggle(name)
        self.refresh_ui()

    def refresh_ui(self):
        state = self.engine.processor.get_state()
        self.gain_var.set(state.gain_db)
        ring_names = ["Wide", "Low Focus", "Mid Focus", "High Focus"]
        self.ring_var.set(f"Focus ring: {ring_names[state.focus_ring]}")
        self.toggle_vars["48V"].set("On" if state.phantom else "Off")
        self.toggle_vars["Phase"].set("On" if state.phase else "Off")
        self.toggle_vars["Tube"].set("On" if state.tube else "Off")
        self._set_button_text("48V", state.phantom)
        self._set_button_text("Phase", state.phase)
        self._set_button_text("Tube", state.tube)
        self.draw_polar(state.focus_ring)

    def _set_button_text(self, name: str, enabled: bool):
        btn = getattr(self, f"{name.lower().replace(' ', '_')}_button")
        btn.configure(text=f"{name}: {'On' if enabled else 'Off'}")

    def draw_polar(self, focus_ring: int):
        c = self.ring_canvas
        c.delete("all")
        w = int(c["width"])
        h = int(c["height"])
        cx = w // 2
        cy = h // 2
        radii = [170, 130, 92, 54]
        for idx, radius in enumerate(radii):
            color = "#f1dea4" if idx == focus_ring else "#69dff2"
            width = 3 if idx == focus_ring else 1
            c.create_oval(cx - radius, cy - int(radius * 0.72), cx + radius, cy + int(radius * 0.72), outline=color, width=width)
        c.create_line(cx, 18, cx, h - 18, fill="#6e7683")
        c.create_line(18, cy, w - 18, cy, fill="#6e7683")
        points = []
        for angle in np.linspace(0, math.tau, 120):
            scale = 1.0 + 0.22 * math.sin(4 * angle) + 0.08 * math.sin(9 * angle)
            rx = 84 * scale
            ry = 118 * scale
            x = cx + math.cos(angle) * rx
            y = cy + math.sin(angle) * ry
            points.extend((x, y))
        c.create_polygon(points, fill="#ff9966", outline="", stipple="gray25")
        inner = []
        for angle in np.linspace(0, math.tau, 90):
            scale = 0.72 + 0.12 * math.sin(4 * angle)
            rx = 62 * scale
            ry = 86 * scale
            x = cx + math.cos(angle) * rx
            y = cy + math.sin(angle) * ry
            inner.extend((x, y))
        c.create_polygon(inner, fill="#b66dff", outline="")

    def _poll_spacemouse(self):
        if self.spacemouse is not None:
            pygame.event.pump()
            state = self.engine.processor.get_state()
            horizontal = self.spacemouse.get_axis(0)
            vertical = self.spacemouse.get_axis(1)
            self.axis_gain.set(f"Gain axis: {horizontal:+.2f}")
            self.axis_focus.set(f"Focus axis: {vertical:+.2f}")

            if abs(horizontal) > 0.08:
                self.engine.processor.set_gain(state.gain_db + horizontal * 0.85)
            if abs(vertical) > 0.18:
                next_ring = state.focus_ring + (1 if vertical > 0 else -1)
                self.engine.processor.set_focus_ring(next_ring)
        self.refresh_ui()
        self.root.after(33, self._poll_spacemouse)


def main():
    root = tk.Tk()
    JimmyMicPreApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

import os
import warnings
import math
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*")

import numpy as np
import pygame
import sounddevice as sd
import soundfile as sf

POL_BANDS = 36
POL_LOW_HZ = 20.0
POL_HIGH_HZ = 20000.0
LOG_LOW = math.log10(POL_LOW_HZ)
LOG_HIGH = math.log10(POL_HIGH_HZ)


def invert_ring_frequency(freq: float) -> float:
    freq = float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ))
    pos = (math.log10(freq) - LOG_LOW) / (LOG_HIGH - LOG_LOW)
    inv_pos = 1.0 - pos
    return 10 ** (LOG_LOW + inv_pos * (LOG_HIGH - LOG_LOW))


def hsv_to_hex(h: float, s: float, v: float) -> str:
    h = max(0.0, min(1.0, h))
    s = max(0.0, min(1.0, s))
    v = max(0.0, min(1.0, v))
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    i %= 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    return rgb_to_hex(
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def eq_gain_color(gain_db: float) -> str:
    gain_db = max(-18.0, min(18.0, gain_db))
    if gain_db < 0.0:
        return lerp_color((255, 60, 46), (255, 208, 138), (gain_db + 18.0) / 18.0)
    return lerp_color((255, 208, 138), (105, 223, 242), gain_db / 18.0)


class SpaceMouseController:
    def __init__(self):
        self.available = False
        self.name = "No SpaceMouse"
        self.joystick = None
        self.last_buttons = []
        self.deadzone = 0.12
        self.gain_axis = 5
        self.x_axis = 0
        self.y_axis = 1
        self.z_axis = 2
        self.direction_threshold = 0.52
        self.direction_latch = False
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            pygame.init()
            pygame.joystick.init()
            preferred = None
            fallback = None
            for index in range(pygame.joystick.get_count()):
                stick = pygame.joystick.Joystick(index)
                stick.init()
                name = stick.get_name()
                if "SpaceMouse" in name:
                    preferred = stick
                    break
                if "3Dconnexion" in name or "Universal Receiver" in name:
                    fallback = stick
            self.joystick = preferred or fallback
            if self.joystick is not None:
                self.available = True
                self.name = self.joystick.get_name()
                self.last_buttons = [0] * self.joystick.get_numbuttons()
                if self.joystick.get_numaxes() <= self.gain_axis:
                    self.gain_axis = min(2, max(0, self.joystick.get_numaxes() - 1))
        except Exception:
            self.available = False

    def poll(self):
        if not self.available or self.joystick is None:
            return 0.0, [], []
        pygame.event.pump()
        axis_value = 0.0
        if self.joystick.get_numaxes() > 0:
            raw = float(self.joystick.get_axis(self.gain_axis))
            if abs(raw) >= self.deadzone:
                axis_value = raw

        pressed = []
        button_count = self.joystick.get_numbuttons()
        for idx in range(min(3, button_count)):
            state = self.joystick.get_button(idx)
            if state and not self.last_buttons[idx]:
                pressed.append(idx)
            self.last_buttons[idx] = state

        directional = []
        x_val = 0.0
        y_val = 0.0
        z_val = 0.0
        if self.joystick.get_numaxes() > self.x_axis:
            x_val = float(self.joystick.get_axis(self.x_axis))
        if self.joystick.get_numaxes() > self.y_axis:
            y_val = float(self.joystick.get_axis(self.y_axis))
        if self.joystick.get_numaxes() > self.z_axis:
            z_val = float(self.joystick.get_axis(self.z_axis))

        left = x_val <= -self.direction_threshold
        right = x_val >= self.direction_threshold
        up = y_val <= -self.direction_threshold
        down = y_val >= self.direction_threshold
        press = z_val <= -self.direction_threshold
        back = z_val >= self.direction_threshold

        if not self.direction_latch:
            if press:
                directional.append("press")
                self.direction_latch = True
            elif back:
                directional.append("back")
                self.direction_latch = True
            elif left:
                directional.append("left")
                self.direction_latch = True
            elif right:
                directional.append("right")
                self.direction_latch = True
            elif up:
                directional.append("up")
                self.direction_latch = True
            elif down:
                directional.append("down")
                self.direction_latch = True
        if not left and not right and not up and not down and not press and not back and abs(x_val) < 0.2 and abs(y_val) < 0.2 and abs(z_val) < 0.2:
            self.direction_latch = False

        return axis_value, pressed, directional


class AudioPlayer:
    def __init__(self):
        self.audio = np.zeros((1, 2), dtype=np.float32)
        self.samplerate = 48000
        self.position = 0
        self.loop = True
        self.playing = False
        self.output_stream = None
        self.input_stream = None
        self.mode = "file"
        self.monitor_input = False
        self.input_gain = 1.6
        self.input_device = None
        self.mic_pre_phase_enabled = False
        self.mic_pre_tube_enabled = False
        self.mic_pre_lpf_enabled = False
        self.mic_pre_hpf_enabled = False
        self.mic_pre_lpf_hz = float(POL_LOW_HZ)
        self.mic_pre_hpf_hz = float(POL_HIGH_HZ)
        self.noise_level = 0.18
        self.white_level = 0.18
        self.brown_level = 0.18
        self.tone_level = 0.18
        self.tone_frequency = 1000.0
        self._tone_phase = 0.0
        self._brown_state = 0.0
        self.harmonic_values = np.zeros(5, dtype=np.float32)
        self.harmonic_makeup = 1.35
        self.eq_bands = []
        self.tone_chain = {
            "trn": {"enabled": False, "center_hz": 2500.0, "width_octaves": 1.6, "attack": 0.45, "sustain": 0.35},
            "clr": {"enabled": False, "drive": 0.35, "tone": 0.0, "mix": 0.55, "gain": 1.0},
            "xct": {"enabled": False, "center_hz": 7000.0, "width_octaves": 1.2, "amount": 0.40, "mix": 0.45},
        }
        self.comp_chain = {
            "comp": {"enabled": True, "threshold_db": -18.0, "ratio": 4.0, "attack_ms": 8.0, "release_ms": 120.0, "makeup": 1.0, "center_hz": 3000.0, "width_octaves": 6.0, "band_enabled": False},
            "limit": {"enabled": False, "threshold_db": -6.0, "ratio": 20.0, "attack_ms": 0.8, "release_ms": 80.0, "makeup": 1.0, "center_hz": 3000.0, "width_octaves": 6.0, "band_enabled": False},
            "gate": {"enabled": False, "threshold_db": -30.0, "ratio": 6.0, "attack_ms": 2.0, "release_ms": 80.0, "makeup": 1.0, "center_hz": 7000.0, "width_octaves": 1.2, "band_enabled": False},
        }
        self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
        self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
        self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
        self.levels = np.zeros(POL_BANDS, dtype=np.float32)
        self.hold_levels = np.zeros(POL_BANDS, dtype=np.float32)
        self.hold_timers = np.zeros(POL_BANDS, dtype=np.float32)
        self.wave_points = np.zeros((POL_BANDS, 2), dtype=np.float32)
        self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
        self.reference_level = 0.08
        self.hold_time = 0.75
        self.release_rate = 0.32
        self._lock = threading.Lock()

    def set_harmonic_values(self, values):
        with self._lock:
            self.harmonic_values = np.asarray(values, dtype=np.float32)

    def set_harmonic_makeup(self, makeup):
        with self._lock:
            self.harmonic_makeup = float(makeup)

    def set_compressor_chain(self, chain_config):
        with self._lock:
            for key, settings in chain_config.items():
                if key not in self.comp_chain:
                    continue
                self.comp_chain[key].update(
                    enabled=bool(settings.get("enabled", self.comp_chain[key]["enabled"])),
                    threshold_db=float(settings.get("threshold_db", self.comp_chain[key]["threshold_db"])),
                    ratio=float(settings.get("ratio", self.comp_chain[key]["ratio"])),
                    attack_ms=float(settings.get("attack_ms", self.comp_chain[key]["attack_ms"])),
                    release_ms=float(settings.get("release_ms", self.comp_chain[key]["release_ms"])),
                    makeup=float(settings.get("makeup", self.comp_chain[key]["makeup"])),
                    center_hz=float(settings.get("center_hz", self.comp_chain[key]["center_hz"])),
                    width_octaves=float(settings.get("width_octaves", self.comp_chain[key]["width_octaves"])),
                    band_enabled=bool(settings.get("band_enabled", self.comp_chain[key]["band_enabled"])),
                )

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
            self.levels = np.zeros(POL_BANDS, dtype=np.float32)
            self.hold_levels = np.zeros(POL_BANDS, dtype=np.float32)
            self.hold_timers = np.zeros(POL_BANDS, dtype=np.float32)
            self.wave_points = np.zeros((POL_BANDS, 2), dtype=np.float32)
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
            self.mode = "file"
        self._restart_output_stream()

    def toggle_play(self):
        if self.mode in ("mic", "pink"):
            self.playing = not self.playing
            if self.playing and self.mode == "mic":
                self._restart_input_stream()
            return
        self.playing = not self.playing

    def stop(self):
        self.playing = False
        with self._lock:
            self.position = 0

    def start_microphone(self, device_index=None):
        with self._lock:
            self.mode = "mic"
            self.position = 0
            self.playing = True
            self.input_device = device_index
            self.levels *= 0.0
            self.hold_levels *= 0.0
            self.hold_timers *= 0.0
            self.wave_points *= 0.0
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
        self._restart_input_stream()

    def start_pink_noise(self):
        with self._lock:
            self.mode = "pink"
            self.position = 0
            self.playing = True
            self.levels *= 0.0
            self.hold_levels *= 0.0
            self.hold_timers *= 0.0
            self.wave_points *= 0.0
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
        self._restart_output_stream()

    def start_white_noise(self):
        with self._lock:
            self.mode = "white"
            self.position = 0
            self.playing = True
            self.levels *= 0.0
            self.hold_levels *= 0.0
            self.hold_timers *= 0.0
            self.wave_points *= 0.0
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
        self._restart_output_stream()

    def start_brown_noise(self):
        with self._lock:
            self.mode = "brown"
            self.position = 0
            self.playing = True
            self._brown_state = 0.0
            self.levels *= 0.0
            self.hold_levels *= 0.0
            self.hold_timers *= 0.0
            self.wave_points *= 0.0
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_env = {"comp": 0.0, "limit": 0.0, "gate": 0.0}
            self._comp_gain = {"comp": 1.0, "limit": 1.0, "gate": 1.0}
        self._restart_output_stream()

    def start_test_tone(self):
        with self._lock:
            self.mode = "tone"
            self.position = 0
            self.playing = True
            self._tone_phase = 0.0
            self.levels *= 0.0
            self.hold_levels *= 0.0
            self.hold_timers *= 0.0
            self.wave_points *= 0.0
            self.noise_floor = np.full(POL_BANDS, 0.0015, dtype=np.float32)
            self.comp_gr_db = 0.0
            self._comp_env = 0.0
        self._restart_output_stream()

    def use_file_mode(self):
        with self._lock:
            self.mode = "file"
            self.playing = False
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

    def get_visual_state(self):
        with self._lock:
            return (
                self.levels.copy(),
                self.hold_levels.copy(),
                self.wave_points.copy(),
                self.comp_gr_db,
                self.position,
                len(self.audio),
                self.samplerate,
                self.mode,
            )

    def _restart_output_stream(self):
        if self.output_stream is not None:
            self.output_stream.stop()
            self.output_stream.close()
        self.output_stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=2,
            dtype="float32",
            blocksize=1024,
            callback=self._file_callback,
        )
        self.output_stream.start()

    def _restart_input_stream(self):
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
        if self.output_stream is not None and self.monitor_input:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None

        kwargs = {
            "samplerate": self.samplerate,
            "channels": 1,
            "dtype": "float32",
            "blocksize": 1024,
            "callback": self._mic_callback,
        }
        if self.input_device is not None:
            kwargs["device"] = self.input_device
        self.input_stream = sd.InputStream(**kwargs)
        self.input_stream.start()

        if self.monitor_input and self.output_stream is None:
            self.output_stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=2,
                dtype="float32",
                blocksize=1024,
            )
            self.output_stream.start()

    def _file_callback(self, outdata, frames, time_info, status):
        with self._lock:
            if self.mode == "pink":
                if not self.playing:
                    outdata[:] = 0
                    self.levels *= 0.92
                    self._decay_holds(frames)
                    self.wave_points *= 0.9
                    return
                block = self._generate_pink_noise(frames)
                block = self._apply_mic_pre(block)
                block = self._apply_harmonics(block)
                block = self._apply_compressor(block)
                block = self._apply_eq(block)
                block = self._apply_tone_stage(block)
                outdata[:] = block
                self.position += frames
                self._analyze(block)
                return

            if self.mode == "white":
                if not self.playing:
                    outdata[:] = 0
                    self.levels *= 0.92
                    self._decay_holds(frames)
                    self.wave_points *= 0.9
                    return
                block = self._generate_white_noise(frames)
                block = self._apply_mic_pre(block)
                block = self._apply_harmonics(block)
                block = self._apply_compressor(block)
                block = self._apply_eq(block)
                block = self._apply_tone_stage(block)
                outdata[:] = block
                self.position += frames
                self._analyze(block)
                return

            if self.mode == "brown":
                if not self.playing:
                    outdata[:] = 0
                    self.levels *= 0.92
                    self._decay_holds(frames)
                    self.wave_points *= 0.9
                    return
                block = self._generate_brown_noise(frames)
                block = self._apply_mic_pre(block)
                block = self._apply_harmonics(block)
                block = self._apply_compressor(block)
                block = self._apply_eq(block)
                block = self._apply_tone_stage(block)
                outdata[:] = block
                self.position += frames
                self._analyze(block)
                return

            if self.mode == "tone":
                if not self.playing:
                    outdata[:] = 0
                    self.levels *= 0.92
                    self._decay_holds(frames)
                    self.wave_points *= 0.9
                    return
                block = self._generate_test_tone(frames)
                block = self._apply_mic_pre(block)
                block = self._apply_harmonics(block)
                block = self._apply_compressor(block)
                block = self._apply_eq(block)
                block = self._apply_tone_stage(block)
                outdata[:] = block
                self.position += frames
                self._analyze(block)
                return

            if self.mode != "file" or not self.playing or self.audio.size == 0:
                outdata[:] = 0
                self.levels *= 0.92
                self._decay_holds(frames)
                self.wave_points *= 0.9
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

            block = self._apply_mic_pre(block)
            block = self._apply_harmonics(block)
            block = self._apply_compressor(block)
            block = self._apply_eq(block)
            block = self._apply_tone_stage(block)
            outdata[:] = block
            self._analyze(block)

    def _mic_callback(self, indata, frames, time_info, status):
        with self._lock:
            if self.mode != "mic" or not self.playing:
                self.levels *= 0.92
                self._decay_holds(frames)
                self.wave_points *= 0.9
                return

            mono = np.asarray(indata[:, 0], dtype=np.float32) * self.input_gain
            block = np.column_stack([mono, mono])
            block = self._apply_mic_pre(block)
            block = self._apply_harmonics(block)
            block = self._apply_compressor(block)
            block = self._apply_eq(block)
            block = self._apply_tone_stage(block)
            self.position += frames
            self._analyze(block)

            if self.monitor_input and self.output_stream is not None:
                monitored = np.clip(block, -1.0, 1.0)
                self.output_stream.write(monitored)

    def _generate_pink_noise(self, frames: int) -> np.ndarray:
        white = np.random.randn(frames).astype(np.float32)
        spectrum = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(frames, d=1.0 / self.samplerate)
        shaping = np.ones_like(freqs, dtype=np.float32)
        shaping[1:] = 1.0 / np.sqrt(np.maximum(freqs[1:], 1.0))
        pink = np.fft.irfft(spectrum * shaping, n=frames).astype(np.float32)
        peak = float(np.max(np.abs(pink)))
        if peak > 0:
            pink /= peak
        pink *= self.noise_level
        return np.column_stack([pink, pink]).astype(np.float32)

    def _generate_white_noise(self, frames: int) -> np.ndarray:
        white = np.random.randn(frames).astype(np.float32)
        peak = float(np.max(np.abs(white)))
        if peak > 0:
            white /= peak
        white *= self.white_level
        return np.column_stack([white, white]).astype(np.float32)

    def _generate_brown_noise(self, frames: int) -> np.ndarray:
        white = np.random.randn(frames).astype(np.float32) * 0.035
        brown = np.empty(frames, dtype=np.float32)
        state = float(self._brown_state)
        for i in range(frames):
            state = np.clip(state + float(white[i]), -1.0, 1.0)
            brown[i] = state
        self._brown_state = state
        peak = float(np.max(np.abs(brown)))
        if peak > 0:
            brown /= peak
        brown *= self.brown_level
        return np.column_stack([brown, brown]).astype(np.float32)

    def _generate_test_tone(self, frames: int) -> np.ndarray:
        phase_step = (2.0 * math.pi * self.tone_frequency) / self.samplerate
        phases = self._tone_phase + phase_step * np.arange(frames, dtype=np.float32)
        tone = np.sin(phases).astype(np.float32) * self.tone_level
        self._tone_phase = float((phases[-1] + phase_step) % (2.0 * math.pi))
        return np.column_stack([tone, tone]).astype(np.float32)

    def _apply_mic_pre(self, block: np.ndarray) -> np.ndarray:
        processed = block.astype(np.float32)
        if self.mic_pre_phase_enabled:
            processed[:, 1] *= -1.0
        if self.mic_pre_tube_enabled:
            processed = np.tanh(processed * 1.18).astype(np.float32)
        if self.mic_pre_lpf_enabled:
            # User-specified behavior: LPF label blocks from outer ring (20 Hz) inward to cutoff.
            processed = self._apply_simple_filter(processed, self.mic_pre_lpf_hz, mode="highpass")
        if self.mic_pre_hpf_enabled:
            # User-specified behavior: HPF label blocks from inner ring (20 kHz) outward to cutoff.
            processed = self._apply_simple_filter(processed, self.mic_pre_hpf_hz, mode="lowpass")
        return processed

    def _apply_simple_filter(self, block: np.ndarray, cutoff_hz: float, mode: str) -> np.ndarray:
        cutoff = float(np.clip(cutoff_hz, 20.0, self.samplerate * 0.45))
        freqs = np.fft.rfftfreq(len(block), d=1.0 / self.samplerate)
        spectrum_scale = np.ones_like(freqs, dtype=np.float32)
        if mode == "lowpass":
            spectrum_scale = 1.0 / np.sqrt(1.0 + (freqs / max(cutoff, 1.0)) ** 4)
        elif mode == "highpass":
            ratio = freqs / max(cutoff, 1.0)
            spectrum_scale = np.where(freqs <= 0.0, 0.0, (ratio ** 2) / np.sqrt(1.0 + ratio ** 4))
        filtered = np.zeros_like(block, dtype=np.float32)
        for ch in range(block.shape[1]):
            spec = np.fft.rfft(block[:, ch])
            filtered[:, ch] = np.fft.irfft(spec * spectrum_scale, n=len(block)).astype(np.float32)
        return filtered

    def _apply_harmonics(self, block: np.ndarray) -> np.ndarray:
        weights = self.harmonic_values.copy()
        if not np.any(weights > 0.001):
            return block

        left = self._apply_harmonics_channel(block[:, 0], weights)
        right = self._apply_harmonics_channel(block[:, 1], weights)
        mixed = np.column_stack([left, right]).astype(np.float32)
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.98:
            mixed *= 0.98 / peak
        return mixed

    def _apply_harmonics_channel(self, signal: np.ndarray, weights: np.ndarray) -> np.ndarray:
        x = np.clip(signal.astype(np.float32), -0.98, 0.98)
        base_rms = float(np.sqrt(np.mean(np.square(x))) + 1e-7)
        enhanced = x.copy()
        theta = np.arccos(x)
        for idx, weight in enumerate(weights):
            if weight <= 0.001:
                continue
            order = idx + 2
            partial = np.cos(order * theta).astype(np.float32)
            # Make the overtone content obvious enough to hear on bass and simple loops.
            overtone_gain = 0.52 - idx * 0.05
            enhanced += partial * float(weight) * overtone_gain

        # Preserve the dry core and layer harmonics on top instead of letting the waveshaper
        # hollow out the fundamental.
        shaped = np.tanh(enhanced * 1.45).astype(np.float32)
        resonance = shaped - np.tanh(x * 1.45).astype(np.float32)
        edge = resonance - np.concatenate(([0.0], resonance[:-1])) * 0.90
        mix = x * 0.92 + resonance * 0.72 + edge * 0.16

        mixed_rms = float(np.sqrt(np.mean(np.square(mix))) + 1e-7)
        auto_makeup = min(2.2, max(0.85, base_rms / mixed_rms))
        return np.tanh(mix * auto_makeup * self.harmonic_makeup).astype(np.float32)

    def set_eq_bands(self, bands: list[dict]):
        self.eq_bands = [dict(band) for band in bands]

    def set_tone_chain(self, chain: dict):
        for key, values in chain.items():
            if key in self.tone_chain:
                self.tone_chain[key].update(values)

    def _apply_eq(self, block: np.ndarray) -> np.ndarray:
        if not self.eq_bands:
            return block
        freqs = np.fft.rfftfreq(len(block), d=1.0 / self.samplerate)
        valid = freqs > 0.0
        log_freqs = np.zeros_like(freqs, dtype=np.float32)
        log_freqs[valid] = np.log2(np.maximum(freqs[valid], 1.0))
        total_scale = np.ones_like(freqs, dtype=np.float32)
        for band in self.eq_bands:
            if not band.get("enabled", True):
                continue
            kind = band.get("type", "BELL")
            center = float(np.clip(band.get("freq", 1000.0), POL_LOW_HZ, min(POL_HIGH_HZ, self.samplerate * 0.45)))
            gain_db = float(np.clip(band.get("gain_db", 0.0), -18.0, 18.0))
            width = float(np.clip(band.get("width", 1.0), 0.20, 6.0))
            center_log = math.log2(center)
            sigma = max(0.08, width / 2.355)
            band_scale = np.ones_like(freqs, dtype=np.float32)
            if kind == "BELL":
                shape = np.zeros_like(freqs, dtype=np.float32)
                shape[valid] = np.exp(-0.5 * ((log_freqs[valid] - center_log) / sigma) ** 2)
                band_scale = np.power(10.0, (gain_db * shape) / 20.0).astype(np.float32)
            elif kind == "LOW SHELF":
                shelf = np.zeros_like(freqs, dtype=np.float32)
                shelf[valid] = 1.0 / (1.0 + np.exp((log_freqs[valid] - center_log) / max(0.05, sigma)))
                band_scale = np.power(10.0, (gain_db * shelf) / 20.0).astype(np.float32)
            elif kind == "HIGH SHELF":
                shelf = np.zeros_like(freqs, dtype=np.float32)
                shelf[valid] = 1.0 / (1.0 + np.exp((center_log - log_freqs[valid]) / max(0.05, sigma)))
                band_scale = np.power(10.0, (gain_db * shelf) / 20.0).astype(np.float32)
            elif kind == "LPF":
                band_scale = (1.0 / np.sqrt(1.0 + (freqs / max(center, 1.0)) ** 6)).astype(np.float32)
            elif kind == "HPF":
                ratio = freqs / max(center, 1.0)
                band_scale = np.where(freqs <= 0.0, 0.0, (ratio ** 3) / np.sqrt(1.0 + ratio ** 6)).astype(np.float32)
            total_scale *= band_scale
        filtered = np.zeros_like(block, dtype=np.float32)
        for ch in range(block.shape[1]):
            spec = np.fft.rfft(block[:, ch])
            filtered[:, ch] = np.fft.irfft(spec * total_scale, n=len(block)).astype(np.float32)
        return np.clip(filtered, -1.0, 1.0).astype(np.float32)

    def _apply_tone_stage(self, block: np.ndarray) -> np.ndarray:
        processed = block.astype(np.float32)
        if self.tone_chain["trn"]["enabled"]:
            processed = self._apply_transient_stage(processed, self.tone_chain["trn"])
        if self.tone_chain["clr"]["enabled"]:
            processed = self._apply_color_stage(processed, self.tone_chain["clr"])
        if self.tone_chain["xct"]["enabled"]:
            processed = self._apply_exciter_stage(processed, self.tone_chain["xct"])
        return np.clip(processed, -1.0, 1.0).astype(np.float32)

    def _apply_transient_stage(self, block: np.ndarray, settings: dict) -> np.ndarray:
        band, dry = self._split_compressor_band(block, settings["center_hz"], settings["width_octaves"])
        mono = np.mean(band, axis=1).astype(np.float32)
        detector = np.abs(mono)
        fast_env = np.zeros_like(detector)
        slow_env = np.zeros_like(detector)
        fast = 0.0
        slow = 0.0
        fast_alpha = 0.52
        slow_alpha = 0.012
        for i, sample in enumerate(detector):
            fast += (sample - fast) * fast_alpha
            slow += (sample - slow) * slow_alpha
            fast_env[i] = fast
            slow_env[i] = slow
        transient = np.maximum(0.0, fast_env - slow_env)
        sustain_env = slow_env.copy()
        if float(np.max(transient)) > 1e-6:
            transient /= float(np.max(transient))
        if float(np.max(sustain_env)) > 1e-6:
            sustain_env /= float(np.max(sustain_env))
        attack_amt = float(settings["attack"])
        sustain_amt = float(settings["sustain"])
        # Use the selected frequency band as the detector, but make the audible action happen on the full signal.
        # This version is intentionally exaggerated so a snare loop changes clearly.
        edge_branch = np.zeros_like(block, dtype=np.float32)
        body_branch = np.zeros_like(block, dtype=np.float32)
        for ch in range(block.shape[1]):
            x = block[:, ch].astype(np.float32)
            prev = np.concatenate(([0.0], x[:-1])).astype(np.float32)
            prev2 = np.concatenate(([0.0, 0.0], x[:-2])).astype(np.float32)
            # Fast edge / crack branch.
            edge = x - prev * 0.72 + prev2 * 0.18
            edge_branch[:, ch] = edge * transient * (attack_amt * 14.0)
            # Slow body / sustain branch.
            acc = 0.0
            body = np.zeros(len(x), dtype=np.float32)
            for i, sample in enumerate(x):
                acc = acc * 0.994 + sample * 0.055
                body[i] = acc
            body_branch[:, ch] = body * sustain_env * (sustain_amt * 7.5)

        mixed = block + edge_branch + body_branch
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.98:
            mixed *= 0.98 / peak
        return mixed.astype(np.float32)

    def _apply_color_stage(self, block: np.ndarray, settings: dict) -> np.ndarray:
        drive = 1.0 + float(settings["drive"]) * 5.0
        tone = float(settings["tone"])
        mix = float(settings["mix"])
        gain = float(settings["gain"])
        colored = np.tanh(block * drive).astype(np.float32)
        if abs(tone) > 0.01:
            cutoff = 1800.0 * (2.0 ** (tone * 3.0))
            filt_mode = "lowpass" if tone < 0.0 else "highpass"
            filtered = self._apply_simple_filter(colored, cutoff, filt_mode)
            colored = colored * 0.55 + filtered * 0.45
        return np.clip((block * (1.0 - mix) + colored * mix) * gain, -1.0, 1.0).astype(np.float32)

    def _apply_exciter_stage(self, block: np.ndarray, settings: dict) -> np.ndarray:
        band, dry = self._split_compressor_band(block, settings["center_hz"], settings["width_octaves"])
        amount = float(settings["amount"])
        mix = float(settings["mix"])
        excited = np.tanh(band * (1.0 + amount * 7.0)).astype(np.float32)
        emphasis = excited - np.tanh(band * 0.9).astype(np.float32)
        return np.clip(dry + band * (1.0 - mix) + (band + emphasis * (0.9 + amount)) * mix, -1.0, 1.0).astype(np.float32)

    def _apply_compressor(self, block: np.ndarray) -> np.ndarray:
        processed = block.astype(np.float32)
        for mode in ("comp", "limit", "gate"):
            settings = self.comp_chain[mode]
            if not settings["enabled"]:
                self.comp_gr_db[mode] = 0.0
                continue
            processed = self._apply_processor_stage(processed, mode, settings)
        return processed

    def _apply_processor_stage(self, block: np.ndarray, mode: str, settings: dict) -> np.ndarray:
        if mode == "gate" and not settings.get("band_enabled", False):
            band_block = block.astype(np.float32)
            dry_block = np.zeros_like(block, dtype=np.float32)
        elif not settings.get("band_enabled", False):
            band_block = block.astype(np.float32)
            dry_block = np.zeros_like(block, dtype=np.float32)
        else:
            band_block, dry_block = self._split_compressor_band(block, settings["center_hz"], settings["width_octaves"])
        mono = band_block.mean(axis=1).astype(np.float32)
        out = np.zeros_like(block, dtype=np.float32)
        env = float(self._comp_env[mode])
        gain_state = float(self._comp_gain[mode])
        attack_coeff = math.exp(-1.0 / max(1.0, (settings["attack_ms"] / 1000.0) * self.samplerate))
        release_coeff = math.exp(-1.0 / max(1.0, (settings["release_ms"] / 1000.0) * self.samplerate))
        last_gr = float(self.comp_gr_db[mode])
        threshold = float(settings["threshold_db"])
        ratio = max(1.0, float(settings["ratio"]))
        gains = np.empty(len(mono), dtype=np.float32)
        eps = 1e-7
        for i, sample in enumerate(mono):
            detector = abs(float(sample))
            if detector > env:
                env = attack_coeff * env + (1.0 - attack_coeff) * detector
            else:
                env = release_coeff * env + (1.0 - release_coeff) * detector
            env_db = 20.0 * math.log10(max(env, eps))
            if mode == "gate":
                open_threshold = threshold
                close_threshold = threshold - 3.0
                if gain_state > 0.5:
                    target_gain = settings["makeup"] if env_db >= close_threshold else 0.0
                else:
                    target_gain = settings["makeup"] if env_db >= open_threshold else 0.0
                if target_gain > gain_state:
                    gain_state = attack_coeff * gain_state + (1.0 - attack_coeff) * target_gain
                else:
                    gain_state = release_coeff * gain_state + (1.0 - release_coeff) * target_gain
                gains[i] = gain_state
                gr_db = gain_state * 24.0
            else:
                effective_ratio = max(ratio, 20.0) if mode == "limit" else ratio
                over_db = max(0.0, env_db - threshold)
                gr_db = over_db - (over_db / effective_ratio if over_db > 0.0 else 0.0)
                gains[i] = 10 ** (-gr_db / 20.0) * settings["makeup"]
            last_gr = gr_db
        out[:, 0] = band_block[:, 0] * gains
        out[:, 1] = band_block[:, 1] * gains
        out += dry_block
        self._comp_env[mode] = env
        self._comp_gain[mode] = gain_state
        self.comp_gr_db[mode] = last_gr
        return out

    def _split_compressor_band(self, block: np.ndarray, center_hz: float, width_octaves: float):
        width = float(width_octaves)
        if width >= 5.9:
            return block, np.zeros_like(block)

        center = float(np.clip(center_hz, POL_LOW_HZ, min(self.samplerate / 2, POL_HIGH_HZ)))
        sigma = max(0.08, width / 2.355)
        freqs = np.fft.rfftfreq(len(block), d=1.0 / self.samplerate)
        mask = np.zeros_like(freqs, dtype=np.float32)
        valid = freqs > 0
        if np.any(valid):
            log_dist = np.log2(np.maximum(freqs[valid], 1.0) / center)
            mask[valid] = np.exp(-0.5 * (log_dist / sigma) ** 2).astype(np.float32)
        mask[0] = 0.0
        band = np.zeros_like(block, dtype=np.float32)
        for ch in range(block.shape[1]):
            spectrum = np.fft.rfft(block[:, ch])
            filtered = np.fft.irfft(spectrum * mask, n=len(block)).astype(np.float32)
            band[:, ch] = filtered
        return band, block - band

    def _analyze(self, block: np.ndarray):
        mono = block.mean(axis=1)
        if len(mono) < 32:
            return
        band_edges = np.geomspace(POL_LOW_HZ, min(self.samplerate / 2, POL_HIGH_HZ), num=POL_BANDS + 1)

        if self.mode == "tone":
            self._analyze_test_tone(mono, band_edges)
            return

        window = np.hanning(len(mono))
        spectrum = np.fft.rfft(mono * window)
        mags = np.abs(spectrum) / max(1, len(mono))
        freqs = np.fft.rfftfreq(len(mono), d=1.0 / self.samplerate)
        raw_levels = np.zeros(POL_BANDS, dtype=np.float32)
        for i in range(POL_BANDS):
            mask = (freqs >= band_edges[i]) & (freqs < band_edges[i + 1])
            if np.any(mask):
                energy = float(np.sqrt(np.mean(np.square(mags[mask]))))
            else:
                energy = 0.0
            raw_levels[i] = energy

        frame_rms = float(np.sqrt(np.mean(np.square(mono))))
        if frame_rms < 0.006:
            self.noise_floor = self.noise_floor * 0.995 + raw_levels * 0.005

        effective = np.maximum(0.0, raw_levels - self.noise_floor * 1.8)
        scaled = np.clip(effective / self.reference_level, 0.0, 1.0)
        scaled = np.power(scaled, 0.65)

        attack = 0.42
        release = 0.10
        rising = scaled > self.levels
        self.levels = np.where(
            rising,
            self.levels * (1.0 - attack) + scaled * attack,
            self.levels * (1.0 - release) + scaled * release,
        ).astype(np.float32)
        self.levels[self.levels < 0.012] = 0.0
        self._update_holds(len(mono))

        samples = np.linspace(0, len(mono) - 1, POL_BANDS).astype(int)
        points = mono[samples]
        self.wave_points[:, 0] = self.wave_points[:, 0] * 0.7 + points * 0.3
        self.wave_points[:, 1] = self.wave_points[:, 1] * 0.88 + np.abs(points) * 0.12

    def _analyze_test_tone(self, mono: np.ndarray, band_edges: np.ndarray):
        rms = float(np.sqrt(np.mean(np.square(mono))))
        scaled = float(np.clip(rms / max(0.0001, self.reference_level * 0.45), 0.0, 1.0))
        scaled = float(np.power(scaled, 0.65))

        raw_levels = np.zeros(POL_BANDS, dtype=np.float32)
        tone_hz = float(np.clip(self.tone_frequency, POL_LOW_HZ, min(self.samplerate / 2, POL_HIGH_HZ)))
        band_index = int(np.searchsorted(band_edges, tone_hz, side="right") - 1)
        band_index = max(0, min(POL_BANDS - 1, band_index))
        raw_levels[band_index] = scaled

        attack = 0.55
        release = 0.16
        rising = raw_levels > self.levels
        self.levels = np.where(
            rising,
            self.levels * (1.0 - attack) + raw_levels * attack,
            self.levels * (1.0 - release) + raw_levels * release,
        ).astype(np.float32)
        self.levels[self.levels < 0.012] = 0.0
        self._update_holds(len(mono))

        samples = np.linspace(0, len(mono) - 1, POL_BANDS).astype(int)
        points = mono[samples]
        self.wave_points[:, 0] = 0.0
        self.wave_points[:, 1] = 0.0
        self.wave_points[band_index, 0] = float(np.mean(points))
        self.wave_points[band_index, 1] = float(np.mean(np.abs(points)))

    def _update_holds(self, frames: int):
        frame_seconds = frames / max(1, self.samplerate)
        hotter = self.levels >= self.hold_levels
        self.hold_levels = np.where(hotter, self.levels, self.hold_levels)
        self.hold_timers = np.where(hotter, self.hold_time, np.maximum(0.0, self.hold_timers - frame_seconds))
        expired = self.hold_timers <= 0.0
        decay = self.release_rate * frame_seconds
        self.hold_levels = np.where(
            expired,
            np.maximum(self.levels, self.hold_levels - decay),
            self.hold_levels,
        )
        self.hold_levels[self.hold_levels < 0.012] = 0.0

    def _decay_holds(self, frames: int):
        frame_seconds = frames / max(1, self.samplerate)
        self.hold_timers = np.maximum(0.0, self.hold_timers - frame_seconds)
        expired = self.hold_timers <= 0.0
        decay = self.release_rate * frame_seconds
        self.hold_levels = np.where(
            expired,
            np.maximum(self.levels, self.hold_levels - decay),
            self.hold_levels,
        )
        self.hold_levels[self.hold_levels < 0.012] = 0.0


class PolVisualizerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("POL Visualizer")
        self.root.geometry("980x760")
        self.root.configure(bg="#252a31")
        self.player = AudioPlayer()
        self.spacemouse = SpaceMouseController()
        self.file_var = tk.StringVar(value="No file loaded")
        self.status_var = tk.StringVar(value="Use live mic input or load a file to drive the POL interface.")
        self.stage_var = tk.StringVar(value="mic_pre")
        self.ring_var = tk.IntVar(value=0)
        self.input_gain_var = tk.DoubleVar(value=1.6)
        self.hold_time_var = tk.DoubleVar(value=0.75)
        self.noise_level_var = tk.DoubleVar(value=0.18)
        self.white_level_var = tk.DoubleVar(value=0.18)
        self.brown_level_var = tk.DoubleVar(value=0.18)
        self.tone_level_var = tk.DoubleVar(value=0.18)
        self.tone_frequency_var = tk.DoubleVar(value=1000.0)
        self.tone_position_var = tk.DoubleVar(value=self._freq_to_slider(1000.0))
        self.comp_threshold_var = tk.DoubleVar(value=-18.0)
        self.comp_ratio_var = tk.DoubleVar(value=4.0)
        self.comp_attack_var = tk.DoubleVar(value=8.0)
        self.comp_release_var = tk.DoubleVar(value=120.0)
        self.comp_makeup_var = tk.DoubleVar(value=1.0)
        self.comp_mode_var = tk.StringVar(value="COMP")
        self.comp_freq_position_var = tk.DoubleVar(value=self._freq_to_slider(3000.0))
        self.comp_width_var = tk.DoubleVar(value=4.0)
        self.comp_selected = tk.IntVar(value=0)
        self.comp_nav_row = tk.StringVar(value="bottom")
        self.comp_enabled_vars = {
            "COMP": tk.BooleanVar(value=True),
            "LIMIT": tk.BooleanVar(value=False),
            "GATE": tk.BooleanVar(value=False),
        }
        self.comp_state_by_mode = {
            "COMP": {"threshold": -18.0, "attack": 8.0, "release": 120.0, "ratio": 4.0, "makeup": 1.0, "center": 3000.0, "width": 6.0, "band_enabled": False},
            "GATE": {"threshold": -30.0, "attack": 2.0, "release": 80.0, "ratio": 6.0, "makeup": 1.0, "center": 7000.0, "width": 1.2, "band_enabled": False},
            "LIMIT": {"threshold": -6.0, "attack": 0.8, "release": 80.0, "ratio": 20.0, "makeup": 1.0, "center": 3000.0, "width": 6.0, "band_enabled": False},
        }
        self.harmonic_makeup_var = tk.DoubleVar(value=1.35)
        self.mode_var = tk.StringVar(value="file")
        self.phantom_var = tk.BooleanVar(value=False)
        self.phase_var = tk.BooleanVar(value=False)
        self.tube_var = tk.BooleanVar(value=False)
        self.lpf_var = tk.BooleanVar(value=False)
        self.hpf_var = tk.BooleanVar(value=False)
        self.mic_pre_selected = tk.StringVar(value="")
        self.eq_band_selected = tk.IntVar(value=0)
        self.eq_param_selected = tk.IntVar(value=0)
        self.eq_nav_row = tk.StringVar(value="bottom")
        self.tone_mode_var = tk.StringVar(value="TRN")
        self.tone_nav_row = tk.StringVar(value="bottom")
        self.tone_selected = tk.IntVar(value=0)
        self.tone_state_by_mode = {
            "TRN": {"enabled": False, "freq": 2500.0, "width": 1.6, "attack": 0.45, "sustain": 0.35},
            "CLR": {"enabled": False, "drive": 0.35, "tone": 0.0, "mix": 0.55, "gain": 1.0},
            "XCT": {"enabled": False, "freq": 7000.0, "width": 1.2, "amount": 0.40, "mix": 0.45},
        }
        self.tone_freq_position_var = tk.DoubleVar(value=self._freq_to_slider(2500.0))
        self.tone_width_var = tk.DoubleVar(value=1.6)
        self.trn_attack_var = tk.DoubleVar(value=0.45)
        self.trn_sustain_var = tk.DoubleVar(value=0.35)
        self.clr_drive_var = tk.DoubleVar(value=0.35)
        self.clr_tone_var = tk.DoubleVar(value=0.0)
        self.clr_mix_var = tk.DoubleVar(value=0.55)
        self.clr_gain_var = tk.DoubleVar(value=1.0)
        self.xct_freq_position_var = tk.DoubleVar(value=self._freq_to_slider(7000.0))
        self.xct_width_var = tk.DoubleVar(value=1.2)
        self.xct_amount_var = tk.DoubleVar(value=0.40)
        self.xct_mix_var = tk.DoubleVar(value=0.45)
        self.harmonic_selected = tk.IntVar(value=0)
        self.harmonic_values = [0.0] * 5
        self.harmonic_stored_values = [0.45] * 5
        self._last_up_press = 0.0
        self.spacemouse_var = tk.StringVar(value=self._space_mouse_status())
        self.canvas = None
        self.position_var = tk.StringVar(value="00:00 / 00:00")
        self.eq_bands = [self._default_eq_band()]
        self._build_ui()
        self._sync_mic_pre()
        self._sync_eq()
        self.sync_tone_stage()
        self._tick()

    def _stage_defs(self):
        return [
            ("mic_pre", "Mic Pre"),
            ("harmonics", "Harmonics"),
            ("compressor", "Compressor"),
            ("eq", "EQ"),
            ("tone_stage", "TRN / CLR / XCT"),
        ]

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#252a31")
        style.configure("TLabel", background="#252a31", foreground="#eef3f8")
        style.configure("Header.TLabel", font=("Orbitron", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#b9c6d6")

        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="POL Visualizer", style="Header.TLabel").pack(anchor="w")
        ttk.Label(container, text="Circular analyzer driven by live audio. Fixed mapping: 20 Hz outer ring to 20 kHz inner ring across 36 stable bands.", style="Sub.TLabel").pack(anchor="w", pady=(3, 10))

        top = ttk.Frame(container)
        top.pack(fill="x", pady=(0, 10))
        ttk.Button(top, text="Live Mic", command=self.start_microphone).pack(side="left")
        ttk.Button(top, text="Pink Noise", command=self.start_pink_noise).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="White Noise", command=self.start_white_noise).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Brown Noise", command=self.start_brown_noise).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Test Tone", command=self.start_test_tone).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Load Audio", command=self.load_audio).pack(side="left")
        ttk.Button(top, text="Play / Pause", command=self.player.toggle_play).pack(side="left", padx=6)
        ttk.Button(top, text="Stop", command=self.player.stop).pack(side="left")
        ttk.Checkbutton(top, text="Loop", command=self.toggle_loop).pack(side="left", padx=(10, 0))
        ttk.Label(top, textvariable=self.file_var, style="Sub.TLabel").pack(side="left", padx=12)

        main = ttk.Frame(container)
        main.pack(fill="both", expand=True)

        left = ttk.LabelFrame(main, text="POL Display", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.canvas = tk.Canvas(left, width=620, height=620, bg="#1e2328", highlightthickness=1, highlightbackground="#6dd9ef")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        right = ttk.LabelFrame(main, text="Focus", padding=12)
        right.pack(side="right", fill="y")
        ttk.Label(right, text="Stage", style="Sub.TLabel").pack(anchor="w")
        for value, label in self._stage_defs():
            ttk.Radiobutton(right, text=label, value=value, variable=self.stage_var).pack(anchor="w", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Focus Ring", style="Sub.TLabel").pack(anchor="w")
        ttk.Radiobutton(right, text="Wide / full", value=0, variable=self.ring_var).pack(anchor="w", pady=2)
        ttk.Radiobutton(right, text="Low focus", value=1, variable=self.ring_var).pack(anchor="w", pady=2)
        ttk.Radiobutton(right, text="Mid focus", value=2, variable=self.ring_var).pack(anchor="w", pady=2)
        ttk.Radiobutton(right, text="High focus", value=3, variable=self.ring_var).pack(anchor="w", pady=2)

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Input", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.25, to=8.0, variable=self.input_gain_var, orient="horizontal", command=self.set_input_gain).pack(fill="x", pady=(4, 2))
        ttk.Label(right, textvariable=self._gain_text_var(), style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.02, to=0.50, variable=self.noise_level_var, orient="horizontal", command=self.set_noise_level).pack(fill="x", pady=(10, 2))
        ttk.Label(right, text="Pink noise level", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.02, to=0.50, variable=self.white_level_var, orient="horizontal", command=self.set_white_level).pack(fill="x", pady=(10, 2))
        ttk.Label(right, text="White noise level", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.02, to=0.50, variable=self.brown_level_var, orient="horizontal", command=self.set_brown_level).pack(fill="x", pady=(10, 2))
        ttk.Label(right, text="Brown noise level", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.02, to=0.50, variable=self.tone_level_var, orient="horizontal", command=self.set_tone_level).pack(fill="x", pady=(10, 2))
        ttk.Label(right, text="Test tone level", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.0, to=1.0, variable=self.tone_position_var, orient="horizontal", command=self.set_tone_frequency).pack(fill="x", pady=(10, 2))
        ttk.Label(right, textvariable=self._tone_text_var(), style="Sub.TLabel").pack(anchor="w")

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Mic Pre", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(right, text="Buttons 1-3 map left / center / right under the POL display.", style="Sub.TLabel", wraplength=240).pack(anchor="w", pady=(2, 2))
        ttk.Label(right, textvariable=self.spacemouse_var, style="Sub.TLabel", wraplength=240).pack(anchor="w", pady=(6, 0))

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Hold", style="Sub.TLabel").pack(anchor="w")
        ttk.Scale(right, from_=0.1, to=2.5, variable=self.hold_time_var, orient="horizontal", command=self.set_hold_time).pack(fill="x", pady=(4, 2))
        ttk.Label(right, text="Peak hold time", style="Sub.TLabel").pack(anchor="w")

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Transport", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(right, textvariable=self.position_var, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        ttk.Separator(right).pack(fill="x", pady=12)
        ttk.Label(right, text="Notes", style="Sub.TLabel").pack(anchor="w")
        ttk.Label(
            right,
            text="This pass locks the POL map to 20 Hz through 20 kHz with 36 stable bands. Real audio drives the shape; control grammar comes after the POL language feels right.",
            wraplength=240,
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(container, textvariable=self.status_var, style="Sub.TLabel", wraplength=920).pack(anchor="w", pady=(10, 0))

    def toggle_loop(self):
        self.player.loop = not self.player.loop

    def _gain_text_var(self):
        self.gain_text_var = tk.StringVar(value=f"Gain {self.input_gain_var.get():.2f}x")
        return self.gain_text_var

    def _tone_text_var(self):
        self.tone_text_var = tk.StringVar(value=f"Test tone {self.tone_frequency_var.get():.0f} Hz")
        return self.tone_text_var

    def _freq_to_slider(self, freq: float) -> float:
        freq = float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ))
        return (math.log10(freq) - LOG_LOW) / (LOG_HIGH - LOG_LOW)

    def _slider_to_freq(self, slider_pos: float) -> float:
        slider_pos = float(np.clip(slider_pos, 0.0, 1.0))
        return 10 ** (LOG_LOW + slider_pos * (LOG_HIGH - LOG_LOW))

    def _space_mouse_status(self):
        if self.spacemouse.available:
            return (
                f"SpaceMouse: {self.spacemouse.name}\n"
                "Mic Pre: turn gain, left / up / right = 48V / PHS / TBE, down = focus cycle, back = Wide.\n"
                "Harmonics / Compressor: left-right selects bottom buttons, turn changes selected value, back returns to Mic Pre."
            )
        return "SpaceMouse not detected."

    def set_input_gain(self, _value=None):
        self.player.input_gain = float(self.input_gain_var.get())
        if hasattr(self, "gain_text_var"):
            self.gain_text_var.set(f"Gain {self.input_gain_var.get():.2f}x")

    def _sync_mic_pre(self):
        self.player.mic_pre_phase_enabled = self.phase_var.get()
        self.player.mic_pre_tube_enabled = self.tube_var.get()
        self.player.mic_pre_lpf_enabled = self.lpf_var.get()
        self.player.mic_pre_hpf_enabled = self.hpf_var.get()
        self.player.mic_pre_lpf_hz = float(self.player.mic_pre_lpf_hz)
        self.player.mic_pre_hpf_hz = float(self.player.mic_pre_hpf_hz)

    def _default_eq_band(self):
        return {"enabled": True, "type": "BELL", "freq": 1000.0, "gain_db": 0.0, "width": 1.20}

    def _sync_eq(self):
        self.player.set_eq_bands(self.eq_bands)

    def sync_tone_stage(self):
        self._save_current_tone_mode_state()
        chain = {
            "trn": {
                "enabled": self.tone_state_by_mode["TRN"]["enabled"],
                "center_hz": self.tone_state_by_mode["TRN"]["freq"],
                "width_octaves": self.tone_state_by_mode["TRN"]["width"],
                "attack": self.tone_state_by_mode["TRN"]["attack"],
                "sustain": self.tone_state_by_mode["TRN"]["sustain"],
            },
            "clr": {
                "enabled": self.tone_state_by_mode["CLR"]["enabled"],
                "drive": self.tone_state_by_mode["CLR"]["drive"],
                "tone": self.tone_state_by_mode["CLR"]["tone"],
                "mix": self.tone_state_by_mode["CLR"]["mix"],
                "gain": self.tone_state_by_mode["CLR"]["gain"],
            },
            "xct": {
                "enabled": self.tone_state_by_mode["XCT"]["enabled"],
                "center_hz": self.tone_state_by_mode["XCT"]["freq"],
                "width_octaves": self.tone_state_by_mode["XCT"]["width"],
                "amount": self.tone_state_by_mode["XCT"]["amount"],
                "mix": self.tone_state_by_mode["XCT"]["mix"],
            },
        }
        self.player.set_tone_chain(chain)

    def _save_current_tone_mode_state(self):
        mode = self.tone_mode_var.get()
        if mode == "TRN":
            self.tone_state_by_mode["TRN"].update(
                freq=self._slider_to_freq(self.tone_freq_position_var.get()),
                width=self.tone_width_var.get(),
                attack=self.trn_attack_var.get(),
                sustain=self.trn_sustain_var.get(),
            )
        elif mode == "CLR":
            self.tone_state_by_mode["CLR"].update(
                drive=self.clr_drive_var.get(),
                tone=self.clr_tone_var.get(),
                mix=self.clr_mix_var.get(),
                gain=self.clr_gain_var.get(),
            )
        elif mode == "XCT":
            self.tone_state_by_mode["XCT"].update(
                freq=self._slider_to_freq(self.xct_freq_position_var.get()),
                width=self.xct_width_var.get(),
                amount=self.xct_amount_var.get(),
                mix=self.xct_mix_var.get(),
            )

    def _load_tone_mode_state(self, mode: str):
        self._save_current_tone_mode_state()
        state = self.tone_state_by_mode[mode]
        if mode == "TRN":
            self.tone_freq_position_var.set(self._freq_to_slider(state["freq"]))
            self.tone_width_var.set(state["width"])
            self.trn_attack_var.set(state["attack"])
            self.trn_sustain_var.set(state["sustain"])
        elif mode == "CLR":
            self.clr_drive_var.set(state["drive"])
            self.clr_tone_var.set(state["tone"])
            self.clr_mix_var.set(state["mix"])
            self.clr_gain_var.set(state["gain"])
        elif mode == "XCT":
            self.xct_freq_position_var.set(self._freq_to_slider(state["freq"]))
            self.xct_width_var.set(state["width"])
            self.xct_amount_var.set(state["amount"])
            self.xct_mix_var.set(state["mix"])
        self.tone_mode_var.set(mode)
        self.tone_nav_row.set("bottom")
        self.sync_tone_stage()

    def set_noise_level(self, _value=None):
        self.player.noise_level = float(self.noise_level_var.get())

    def set_white_level(self, _value=None):
        self.player.white_level = float(self.white_level_var.get())

    def set_brown_level(self, _value=None):
        self.player.brown_level = float(self.brown_level_var.get())

    def set_tone_level(self, _value=None):
        self.player.tone_level = float(self.tone_level_var.get())

    def set_tone_frequency(self, _value=None):
        freq = self._slider_to_freq(self.tone_position_var.get())
        self.tone_frequency_var.set(freq)
        self.player.tone_frequency = freq
        if hasattr(self, "tone_text_var"):
            self.tone_text_var.set(f"Test tone {freq:.0f} Hz")

    def set_hold_time(self, _value=None):
        self.player.hold_time = float(self.hold_time_var.get())

    def sync_compressor(self):
        self._save_current_compressor_mode_state()
        chain = {}
        for mode, state in self.comp_state_by_mode.items():
            chain[mode.lower()] = {
                "enabled": self.comp_enabled_vars[mode].get(),
                "threshold_db": state["threshold"],
                "ratio": state["ratio"],
                "attack_ms": state["attack"],
                "release_ms": state["release"],
                "makeup": state["makeup"],
                "center_hz": state["center"],
                "width_octaves": state["width"],
                "band_enabled": state["band_enabled"],
            }
        self.player.set_compressor_chain(chain)

    def _save_current_compressor_mode_state(self):
        mode = self.comp_mode_var.get()
        self.comp_state_by_mode[mode] = {
            "threshold": self.comp_threshold_var.get(),
            "attack": self.comp_attack_var.get(),
            "release": self.comp_release_var.get(),
            "ratio": self.comp_ratio_var.get(),
            "makeup": self.comp_makeup_var.get(),
            "center": self._slider_to_freq(self.comp_freq_position_var.get()),
            "width": self.comp_width_var.get(),
            "band_enabled": self.comp_state_by_mode[mode]["band_enabled"],
        }

    def _load_compressor_mode_state(self, mode: str):
        state = self.comp_state_by_mode[mode]
        self.comp_threshold_var.set(state["threshold"])
        self.comp_attack_var.set(state["attack"])
        self.comp_release_var.set(state["release"])
        self.comp_ratio_var.set(state["ratio"])
        self.comp_makeup_var.set(state["makeup"])
        self.comp_freq_position_var.set(self._freq_to_slider(state["center"]))
        self.comp_width_var.set(state["width"])
        self.comp_mode_var.set(mode)
        self.comp_nav_row.set("bottom")
        self.sync_compressor()

    def start_microphone(self):
        self.player.start_microphone()
        self.mode_var.set("mic")
        self.file_var.set("Live microphone")
        self.status_var.set("Listening to microphone input. Talk into the mic and the POL display should respond immediately.")

    def start_pink_noise(self):
        self.player.start_pink_noise()
        self.mode_var.set("pink")
        self.file_var.set("Pink noise")
        self.status_var.set("Driving the POL analyzer with built-in pink noise so you can test ring behavior without the microphone.")

    def start_white_noise(self):
        self.player.start_white_noise()
        self.mode_var.set("white")
        self.file_var.set("White noise")
        self.status_var.set("Driving the POL analyzer with white noise for a flatter all-band calibration source.")

    def start_brown_noise(self):
        self.player.start_brown_noise()
        self.mode_var.set("brown")
        self.file_var.set("Brown noise")
        self.status_var.set("Driving the POL analyzer with brown noise so you can compare a strongly low-heavy source.")

    def start_test_tone(self):
        self.player.start_test_tone()
        self.mode_var.set("tone")
        self.file_var.set("Test tone")
        self.status_var.set("Driving the POL analyzer with a single sine tone so you can verify exactly which ring the frequency lands on.")

    def load_audio(self):
        path = filedialog.askopenfilename(
            title="Choose stereo audio file",
            filetypes=[("Audio", "*.wav *.aiff *.aif *.flac *.ogg *.mp3"), ("All files", "*.*")],
        )
        if not path:
            return
        file_path = Path(path)
        self.player.use_file_mode()
        self.player.load_file(file_path)
        self.mode_var.set("file")
        self.file_var.set(file_path.name)
        self.status_var.set(f"Loaded {file_path.name}. Press play to drive the POL analyzer.")

    def _tick(self):
        self._poll_spacemouse()
        levels, hold_levels, wave_points, comp_gr_db, position, total, samplerate, mode = self.player.get_visual_state()
        self._draw(levels, hold_levels, wave_points, comp_gr_db, mode)
        if mode == "mic":
            self.position_var.set(f"LIVE {self._fmt_time(position, samplerate)}")
        elif mode == "pink":
            self.position_var.set(f"PINK {self._fmt_time(position, samplerate)}")
        elif mode == "white":
            self.position_var.set(f"WHITE {self._fmt_time(position, samplerate)}")
        elif mode == "brown":
            self.position_var.set(f"BROWN {self._fmt_time(position, samplerate)}")
        elif mode == "tone":
            self.position_var.set(f"TONE {self._fmt_time(position, samplerate)}")
        else:
            self.position_var.set(f"{self._fmt_time(position, samplerate)} / {self._fmt_time(total, samplerate)}")
        self.root.after(33, self._tick)

    def _poll_spacemouse(self):
        axis_value, pressed, directional = self.spacemouse.poll()
        stage = self.stage_var.get()
        if stage == "mic_pre":
            if axis_value != 0.0:
                if self.mic_pre_selected.get() == "lpf" and self.lpf_var.get():
                    current = self.player.mic_pre_lpf_hz
                    updated = float(np.clip(current * (1.0 + axis_value * 0.06), 20.0, 20000.0))
                    if abs(updated - current) > 1e-6:
                        self.player.mic_pre_lpf_hz = updated
                elif self.mic_pre_selected.get() == "hpf" and self.hpf_var.get():
                    current = self.player.mic_pre_hpf_hz
                    updated = float(np.clip(current * (1.0 - axis_value * 0.06), 20.0, 20000.0))
                    if abs(updated - current) > 1e-6:
                        self.player.mic_pre_hpf_hz = updated
                elif self.mic_pre_selected.get() == "":
                    current = float(self.input_gain_var.get())
                    updated = max(0.25, min(8.0, current + axis_value * 0.08))
                    if abs(updated - current) > 1e-6:
                        self.input_gain_var.set(updated)
                        self.set_input_gain()
        elif stage == "harmonics":
            if axis_value != 0.0:
                selected = self.harmonic_selected.get()
                if selected < 5:
                    current = self.harmonic_values[selected]
                    updated = max(0.0, min(1.0, current + axis_value * 0.04))
                    if abs(updated - current) > 1e-6:
                        self.harmonic_values[selected] = updated
                        self.player.set_harmonic_values(self.harmonic_values)
                else:
                    current = self.harmonic_makeup_var.get()
                    updated = max(0.5, min(2.5, current + axis_value * 0.04))
                    if abs(updated - current) > 1e-6:
                        self.harmonic_makeup_var.set(updated)
                        self.player.set_harmonic_makeup(updated)
        elif stage == "compressor":
            if axis_value != 0.0 and self.comp_nav_row.get() == "bottom":
                selected = self.comp_selected.get()
                if selected == 0:
                    self.comp_threshold_var.set(max(-48.0, min(0.0, self.comp_threshold_var.get() + axis_value * 1.2)))
                elif selected == 1:
                    self.comp_attack_var.set(max(0.5, min(100.0, self.comp_attack_var.get() + axis_value * 2.0)))
                elif selected == 2:
                    self.comp_release_var.set(max(15.0, min(600.0, self.comp_release_var.get() + axis_value * 8.0)))
                elif selected == 3:
                    self.comp_ratio_var.set(max(1.0, min(20.0, self.comp_ratio_var.get() + axis_value * 0.35)))
                elif selected == 4:
                    self.comp_makeup_var.set(max(0.5, min(3.0, self.comp_makeup_var.get() + axis_value * 0.05)))
                elif selected == 5:
                    pos = max(0.0, min(1.0, self.comp_freq_position_var.get() + axis_value * 0.012))
                    self.comp_freq_position_var.set(pos)
                elif selected == 6:
                    self.comp_width_var.set(max(0.20, min(6.0, self.comp_width_var.get() + axis_value * 0.06)))
                self.sync_compressor()
        elif stage == "eq":
            if axis_value != 0.0 and self.eq_bands:
                band = self.eq_bands[self.eq_band_selected.get()]
                selected = self.eq_param_selected.get()
                if self.eq_nav_row.get() == "bottom" and selected == 2:
                    band["freq"] = float(np.clip(band["freq"] * (1.0 + axis_value * 0.06), POL_LOW_HZ, POL_HIGH_HZ))
                elif self.eq_nav_row.get() == "bottom" and selected == 3:
                    band["gain_db"] = float(np.clip(band["gain_db"] + axis_value * 0.9, -18.0, 18.0))
                elif self.eq_nav_row.get() == "bottom" and selected == 4:
                    band["width"] = float(np.clip(band["width"] + axis_value * 0.08, 0.20, 6.0))
                self._sync_eq()
        elif stage == "tone_stage":
            if axis_value != 0.0 and self.tone_nav_row.get() == "bottom":
                mode_name = self.tone_mode_var.get()
                selected = self.tone_selected.get()
                if mode_name == "TRN":
                    if selected == 0:
                        pos = max(0.0, min(1.0, self.tone_freq_position_var.get() + axis_value * 0.012))
                        self.tone_freq_position_var.set(pos)
                    elif selected == 1:
                        self.tone_width_var.set(max(0.20, min(6.0, self.tone_width_var.get() + axis_value * 0.06)))
                    elif selected == 2:
                        self.trn_attack_var.set(max(0.0, min(1.0, self.trn_attack_var.get() + axis_value * 0.03)))
                    elif selected == 3:
                        self.trn_sustain_var.set(max(0.0, min(1.0, self.trn_sustain_var.get() + axis_value * 0.03)))
                elif mode_name == "CLR":
                    if selected == 0:
                        self.clr_drive_var.set(max(0.0, min(1.0, self.clr_drive_var.get() + axis_value * 0.03)))
                    elif selected == 1:
                        self.clr_tone_var.set(max(-1.0, min(1.0, self.clr_tone_var.get() + axis_value * 0.04)))
                    elif selected == 2:
                        self.clr_mix_var.set(max(0.0, min(1.0, self.clr_mix_var.get() + axis_value * 0.03)))
                    elif selected == 3:
                        self.clr_gain_var.set(max(0.5, min(2.5, self.clr_gain_var.get() + axis_value * 0.04)))
                elif mode_name == "XCT":
                    if selected == 0:
                        pos = max(0.0, min(1.0, self.xct_freq_position_var.get() + axis_value * 0.012))
                        self.xct_freq_position_var.set(pos)
                    elif selected == 1:
                        self.xct_width_var.set(max(0.20, min(6.0, self.xct_width_var.get() + axis_value * 0.06)))
                    elif selected == 2:
                        self.xct_amount_var.set(max(0.0, min(1.0, self.xct_amount_var.get() + axis_value * 0.03)))
                    elif selected == 3:
                        self.xct_mix_var.set(max(0.0, min(1.0, self.xct_mix_var.get() + axis_value * 0.03)))
                self.sync_tone_stage()

        for button_idx in pressed:
            if stage == "mic_pre":
                if button_idx == 0 and self.mic_pre_selected.get():
                    self._toggle_mic_pre(self.mic_pre_selected.get())
            elif stage == "eq":
                if button_idx == 0:
                    self._handle_eq_direction("press")
            elif stage == "compressor":
                if button_idx == 0:
                    if self.comp_nav_row.get() == "top":
                        self._toggle_selected_compressor_processor()
                    elif self.comp_nav_row.get() == "bottom" and self.comp_selected.get() in (5, 6):
                        self._toggle_selected_compressor_band_target()
            elif stage == "tone_stage":
                if button_idx == 0 and self.tone_nav_row.get() == "top":
                    self._toggle_selected_tone_processor()

        for target in directional:
            if stage == "mic_pre":
                self._handle_mic_pre_direction(target)
            elif stage == "harmonics":
                self._handle_harmonics_direction(target)
            elif stage == "eq":
                self._handle_eq_direction(target)
            elif stage == "compressor":
                self._handle_compressor_direction(target)
            elif stage == "tone_stage":
                self._handle_tone_direction(target)

    def _handle_mic_pre_direction(self, target: str):
        buttons = ["lpf", "phantom", "phase", "tube", "hpf"]
        current = self.mic_pre_selected.get()
        idx = buttons.index(current) if current in buttons else -1
        if target == "left":
            if idx == -1:
                self.mic_pre_selected.set(buttons[-1])
            else:
                self.mic_pre_selected.set(buttons[(idx - 1) % len(buttons)])
        elif target == "right":
            if idx == -1:
                self.mic_pre_selected.set(buttons[0])
            else:
                self.mic_pre_selected.set(buttons[(idx + 1) % len(buttons)])
        elif target == "down":
            if idx != -1:
                self._toggle_mic_pre(self.mic_pre_selected.get())
        elif target == "press":
            if idx != -1:
                self._toggle_mic_pre(self.mic_pre_selected.get())
        elif target == "up":
            self.mic_pre_selected.set("")
        elif target == "back":
            self.ring_var.set(0)

    def _handle_harmonics_direction(self, target: str):
        if target == "left":
            self.harmonic_selected.set((self.harmonic_selected.get() - 1) % 6)
        elif target == "right":
            self.harmonic_selected.set((self.harmonic_selected.get() + 1) % 6)
        elif target == "down":
            idx = self.harmonic_selected.get()
            if idx < 5:
                current = self.harmonic_values[idx]
                if current > 0.001:
                    self.harmonic_stored_values[idx] = current
                    self.harmonic_values[idx] = 0.0
                else:
                    self.harmonic_values[idx] = max(0.18, self.harmonic_stored_values[idx])
                self.player.set_harmonic_values(self.harmonic_values)

    def _set_harmonic(self, index: int):
        self.harmonic_selected.set(index)
        self.player.set_harmonic_values(self.harmonic_values)

    def _handle_eq_direction(self, target: str):
        if target == "left":
            if self.eq_nav_row.get() == "top" and self.eq_bands:
                self.eq_band_selected.set((self.eq_band_selected.get() - 1) % len(self.eq_bands))
            else:
                self.eq_param_selected.set((self.eq_param_selected.get() - 1) % 5)
        elif target == "right":
            if self.eq_nav_row.get() == "top" and self.eq_bands:
                self.eq_band_selected.set((self.eq_band_selected.get() + 1) % len(self.eq_bands))
            else:
                self.eq_param_selected.set((self.eq_param_selected.get() + 1) % 5)
        elif target == "up":
            self.eq_nav_row.set("top")
        elif target == "down":
            if self.eq_nav_row.get() == "top":
                self.eq_nav_row.set("bottom")
            elif self.eq_param_selected.get() == 0:
                self.eq_bands.append(self._default_eq_band())
                self.eq_band_selected.set(len(self.eq_bands) - 1)
                self._sync_eq()
            elif self.eq_param_selected.get() == 1 and self.eq_bands:
                types = ["BELL", "LOW SHELF", "HIGH SHELF", "LPF", "HPF"]
                band = self.eq_bands[self.eq_band_selected.get()]
                idx = types.index(band["type"]) if band["type"] in types else 0
                band["type"] = types[(idx + 1) % len(types)]
                self._sync_eq()
        elif target == "press":
            if self.eq_nav_row.get() == "bottom" and self.eq_param_selected.get() == 0:
                self.eq_bands.append(self._default_eq_band())
                self.eq_band_selected.set(len(self.eq_bands) - 1)
                self._sync_eq()
            elif self.eq_nav_row.get() == "bottom" and self.eq_param_selected.get() == 1 and self.eq_bands:
                types = ["BELL", "LOW SHELF", "HIGH SHELF", "LPF", "HPF"]
                band = self.eq_bands[self.eq_band_selected.get()]
                idx = types.index(band["type"]) if band["type"] in types else 0
                band["type"] = types[(idx + 1) % len(types)]
                self._sync_eq()

    def _handle_compressor_direction(self, target: str):
        modes = ["COMP", "LIMIT", "GATE"]
        if target == "press":
            if self.comp_nav_row.get() == "top":
                self._toggle_selected_compressor_processor()
        elif target == "back":
            if self.comp_nav_row.get() == "bottom" and self.comp_selected.get() in (5, 6):
                self._toggle_selected_compressor_band_target()
        elif target == "up":
            self.comp_nav_row.set("top")
        elif target == "down":
            if self.comp_nav_row.get() == "bottom" and self.comp_selected.get() in (5, 6):
                self._toggle_selected_compressor_band_target()
            else:
                self.comp_nav_row.set("bottom")
        elif target == "left":
            if self.comp_nav_row.get() == "top":
                idx = modes.index(self.comp_mode_var.get())
                self._save_current_compressor_mode_state()
                self._load_compressor_mode_state(modes[(idx - 1) % len(modes)])
                self.comp_nav_row.set("top")
            else:
                self.comp_selected.set((self.comp_selected.get() - 1) % 7)
        elif target == "right":
            if self.comp_nav_row.get() == "top":
                idx = modes.index(self.comp_mode_var.get())
                self._save_current_compressor_mode_state()
                self._load_compressor_mode_state(modes[(idx + 1) % len(modes)])
                self.comp_nav_row.set("top")
            else:
                self.comp_selected.set((self.comp_selected.get() + 1) % 7)

    def _handle_tone_direction(self, target: str):
        modes = ["TRN", "CLR", "XCT"]
        if target == "press":
            if self.tone_nav_row.get() == "top":
                self._toggle_selected_tone_processor()
        elif target == "up":
            self.tone_nav_row.set("top")
        elif target == "down":
            if self.tone_nav_row.get() == "top":
                self.tone_nav_row.set("bottom")
            else:
                self._toggle_selected_tone_processor()
        elif target == "left":
            if self.tone_nav_row.get() == "top":
                idx = modes.index(self.tone_mode_var.get())
                self._load_tone_mode_state(modes[(idx - 1) % len(modes)])
                self.tone_nav_row.set("top")
            else:
                self.tone_selected.set((self.tone_selected.get() - 1) % 4)
        elif target == "right":
            if self.tone_nav_row.get() == "top":
                idx = modes.index(self.tone_mode_var.get())
                self._load_tone_mode_state(modes[(idx + 1) % len(modes)])
                self.tone_nav_row.set("top")
            else:
                self.tone_selected.set((self.tone_selected.get() + 1) % 4)

    def _toggle_selected_tone_processor(self):
        mode = self.tone_mode_var.get()
        current = bool(self.tone_state_by_mode[mode]["enabled"])
        self.tone_state_by_mode[mode]["enabled"] = not current
        self.sync_tone_stage()

    def _toggle_selected_compressor_processor(self):
        mode = self.comp_mode_var.get()
        self.comp_enabled_vars[mode].set(not self.comp_enabled_vars[mode].get())
        self.sync_compressor()

    def _toggle_selected_compressor_band_target(self):
        mode = self.comp_mode_var.get()
        self._set_selected_compressor_band_target(not self.comp_state_by_mode[mode]["band_enabled"])

    def _set_selected_compressor_band_target(self, enabled: bool):
        mode = self.comp_mode_var.get()
        if enabled and self.comp_state_by_mode[mode]["width"] >= 5.9:
            default_width = 1.2 if mode == "GATE" else 1.6
            self.comp_state_by_mode[mode]["width"] = default_width
            self.comp_width_var.set(default_width)
        self.comp_state_by_mode[mode]["band_enabled"] = bool(enabled)
        self.sync_compressor()

    def _toggle_mic_pre(self, target: str):
        if not target:
            return
        if target == "lpf":
            self.lpf_var.set(not self.lpf_var.get())
        elif target == "phantom":
            self.phantom_var.set(not self.phantom_var.get())
        elif target == "phase":
            self.phase_var.set(not self.phase_var.get())
        elif target == "tube":
            self.tube_var.set(not self.tube_var.get())
        elif target == "hpf":
            self.hpf_var.set(not self.hpf_var.get())
        self._sync_mic_pre()

    def _on_canvas_click(self, event):
        width = int(self.canvas["width"])
        height = int(self.canvas["height"])
        stage_y = 30
        stage_defs = self._stage_defs()
        tab_gap = width / (len(stage_defs) + 1)
        if abs(event.y - stage_y) <= 18:
            for idx, (key, _label) in enumerate(stage_defs, start=1):
                x = tab_gap * idx
                if abs(event.x - x) <= 58:
                    self.stage_var.set(key)
                    return

        stage = self.stage_var.get()
        if stage == "compressor" and abs(event.y - 142) <= 22:
            for mode_name, x in zip(["COMP", "LIMIT", "GATE"], [width / 2 - 120, width / 2, width / 2 + 120]):
                if abs(event.x - x) <= 54:
                    self._save_current_compressor_mode_state()
                    self._load_compressor_mode_state(mode_name)
                    self.comp_nav_row.set("top")
                    return
        if stage == "tone_stage" and abs(event.y - 142) <= 22:
            for mode_name, x in zip(["TRN", "CLR", "XCT"], [width / 2 - 120, width / 2, width / 2 + 120]):
                if abs(event.x - x) <= 54:
                    self._load_tone_mode_state(mode_name)
                    self.tone_nav_row.set("top")
                    return

        button_y = height - 64
        if abs(event.y - button_y) > 28:
            return
        if stage == "mic_pre":
            slots = [
                ("lpf", width * 0.16),
                ("phantom", width * 0.33),
                ("phase", width * 0.50),
                ("tube", width * 0.67),
                ("hpf", width * 0.84),
            ]
            for name, x in slots:
                if abs(event.x - x) <= 48:
                    self.mic_pre_selected.set(name if name in ("lpf", "hpf") else "")
                    self._toggle_mic_pre(name)
                    return
        elif stage == "harmonics":
            positions = self._bottom_slot_positions(width, 6)
            for idx, x in enumerate(positions):
                if abs(event.x - x) <= 46:
                    self.harmonic_selected.set(idx)
                    return
        elif stage == "compressor":
            positions = self._bottom_slot_positions(width, 7)
            for idx, x in enumerate(positions):
                if abs(event.x - x) <= 46:
                    self.comp_selected.set(idx)
                    self.comp_nav_row.set("bottom")
                    return
        elif stage == "tone_stage":
            positions = self._bottom_slot_positions(width, 4)
            for idx, x in enumerate(positions):
                if abs(event.x - x) <= 52:
                    self.tone_selected.set(idx)
                    self.tone_nav_row.set("bottom")
                    return

    def _fmt_time(self, samples: int, samplerate: int) -> str:
        if samplerate <= 0:
            return "00:00"
        seconds = int(samples / samplerate)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _draw(self, levels: np.ndarray, hold_levels: np.ndarray, wave_points: np.ndarray, comp_gr_db: dict, mode: str):
        c = self.canvas
        c.delete("all")
        w = int(c["width"])
        h = int(c["height"])
        cx = w // 2
        cy = h // 2

        outer_rx = 252
        outer_ry = 182
        inner_rx = 42
        inner_ry = 30
        ring_bounds = [(outer_rx, outer_ry), (190, 138), (132, 94), (78, 56)]
        active = self.ring_var.get()

        for idx, (rx, ry) in enumerate(ring_bounds):
            color = "#f1dea4" if idx == active else "#69dff2"
            width = 3 if idx == active else 1
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=width)

        c.create_line(cx, 24, cx, h - 24, fill="#626d79")
        c.create_line(24, cy, w - 24, cy, fill="#626d79")

        band_edges = np.geomspace(POL_LOW_HZ, POL_HIGH_HZ, num=POL_BANDS + 1)
        band_centers = np.sqrt(band_edges[:-1] * band_edges[1:])
        threshold = 0.045
        max_expand = 22.0
        focus_mode = self.ring_var.get()
        focus_ranges = {
            0: (0.0, 1.0, "Wide / Full"),
            1: (0.00, 0.38, "Low Focus"),
            2: (0.28, 0.72, "Mid Focus"),
            3: (0.62, 1.00, "High Focus"),
        }
        focus_start, focus_end, focus_label = focus_ranges.get(focus_mode, focus_ranges[0])

        for idx, amp in enumerate(levels):
            band_pos = idx / max(1, len(levels) - 1)
            target_rx = outer_rx - (outer_rx - inner_rx) * band_pos
            target_ry = outer_ry - (outer_ry - inner_ry) * band_pos
            guide_color = "#25445f"
            in_focus = focus_start <= band_pos <= focus_end if focus_mode != 0 else True
            guide_color = "#25445f" if in_focus else "#1d2731"

            c.create_oval(
                cx - target_rx,
                cy - target_ry,
                cx + target_rx,
                cy + target_ry,
                outline=guide_color,
                width=1,
            )

            if amp > threshold:
                heat = min(1.0, (amp - threshold) / (1.0 - threshold))
                if not in_focus:
                    heat *= 0.22
                expand = max_expand * heat
                rx = target_rx + expand
                ry = target_ry + expand * 0.72
                ring_width = 1 + int(heat * 5)
                ring_color = hsv_to_hex(0.66 * (1.0 - heat), 0.9, 0.45 + heat * 0.55)
                c.create_oval(
                    cx - rx,
                    cy - ry,
                    cx + rx,
                    cy + ry,
                    outline=ring_color,
                    width=ring_width,
                )
                c.create_oval(
                    cx - rx - 1,
                    cy - ry - 1,
                    cx + rx + 1,
                    cy + ry + 1,
                    outline=hsv_to_hex(0.66 * (1.0 - heat), 0.45, 0.16 + heat * 0.42),
                    width=1,
                )
                if idx % 6 == 0:
                    tick_x = cx + rx
                    c.create_line(tick_x, cy - 4, tick_x, cy + 4, fill=ring_color)

            hold_amp = hold_levels[idx]
            if hold_amp > threshold:
                hold_heat = min(1.0, (hold_amp - threshold) / (1.0 - threshold))
                if not in_focus:
                    hold_heat *= 0.22
                hold_expand = max_expand * hold_heat
                hold_rx = target_rx + hold_expand
                hold_ry = target_ry + hold_expand * 0.72
                hold_color = hsv_to_hex(0.66 * (1.0 - hold_heat), 0.55, 0.72 + hold_heat * 0.25)
                c.create_oval(
                    cx - hold_rx,
                    cy - hold_ry,
                    cx + hold_rx,
                    cy + hold_ry,
                    outline=hold_color,
                    width=2,
                )

        label_indices = [0, 9, 18, 27, 35]
        for idx in label_indices:
            band_pos = idx / max(1, len(levels) - 1)
            ry = outer_ry - (outer_ry - inner_ry) * band_pos
            hz = band_centers[idx]
            if hz >= 1000:
                text = f"{hz/1000:.1f}k"
            else:
                text = f"{int(hz)}"
            c.create_text(cx, cy - ry - 10, text=text, fill="#9fb6cb", font=("Segoe UI", 9))

        if focus_mode != 0:
            start_rx = outer_rx - (outer_rx - inner_rx) * focus_start
            start_ry = outer_ry - (outer_ry - inner_ry) * focus_start
            end_rx = outer_rx - (outer_rx - inner_rx) * focus_end
            end_ry = outer_ry - (outer_ry - inner_ry) * focus_end
            c.create_oval(cx - start_rx, cy - start_ry, cx + start_rx, cy + start_ry, outline="#f1dea4", width=2)
            c.create_oval(cx - end_rx, cy - end_ry, cx + end_rx, cy + end_ry, outline="#f1dea4", width=2)
            c.create_text(cx, 26, text=focus_label, fill="#f1dea4", font=("Orbitron", 11, "bold"))
        else:
            c.create_text(cx, 26, text=focus_label, fill="#9fb6cb", font=("Orbitron", 11, "bold"))

        stage = self.stage_var.get()
        self._draw_stage_tabs(c, w)
        if stage == "mic_pre":
            self._draw_mic_pre_overlay(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        elif stage == "harmonics":
            self._draw_harmonic_overlay(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry, mode)
        elif stage == "compressor":
            self._draw_compressor_overlay(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry, levels, comp_gr_db)
        elif stage == "tone_stage":
            self._draw_tone_overlay(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
        if stage == "mic_pre":
            self._draw_mic_pre_buttons(c, w, h)
        elif stage == "harmonics":
            self._draw_harmonics_stage(c, w, h)
        elif stage == "compressor":
            selected_gr = float(comp_gr_db.get(self.comp_mode_var.get().lower(), 0.0))
            self._draw_compressor_stage(c, w, h, selected_gr)
        elif stage == "eq":
            self._draw_eq_overlay(c, cx, cy, outer_rx, outer_ry, inner_rx, inner_ry)
            self._draw_eq_stage(c, w, h)
        elif stage == "tone_stage":
            self._draw_tone_stage(c, w, h)

    def _draw_stage_tabs(self, c: tk.Canvas, w: int):
        stage_defs = self._stage_defs()
        gap = w / (len(stage_defs) + 1)
        for idx, (key, label) in enumerate(stage_defs, start=1):
            x = gap * idx
            y = 30
            half_w = 52 if len(label) <= 8 else 76
            active = self.stage_var.get() == key
            fill = "#f1dea4" if active else "#24303a"
            outline = "#ffd490" if active else "#4f667b"
            text_color = "#11151a" if active else "#c9d8e6"
            c.create_rectangle(x - half_w, y - 16, x + half_w, y + 16, fill=fill, outline=outline, width=2)
            c.create_text(x, y, text=label, fill=text_color, font=("Orbitron", 10, "bold"))

    def _draw_mic_pre_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        if self.lpf_var.get():
            band_pos = self._freq_to_slider(self.player.mic_pre_lpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * band_pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * band_pos
            overlay_layers = 14
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                layer_rx = cutoff_rx + (outer_rx - cutoff_rx) * mix
                layer_ry = cutoff_ry + (outer_ry - cutoff_ry) * mix
                layer_color = hsv_to_hex(0.0, 0.94, 0.34 + mix * 0.28)
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3)
            c.create_oval(cx - outer_rx, cy - outer_ry, cx + outer_rx, cy + outer_ry, outline="#ff3c2e", width=4)
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline="#ffd08a", width=3)
            c.create_text(cx, cy - outer_ry - 18, text=f"LPF {self.player.mic_pre_lpf_hz:.0f} Hz", fill="#f6a864", font=("Orbitron", 10, "bold"))

        if self.hpf_var.get():
            band_pos = self._freq_to_slider(self.player.mic_pre_hpf_hz)
            cutoff_rx = outer_rx - (outer_rx - inner_rx) * band_pos
            cutoff_ry = outer_ry - (outer_ry - inner_ry) * band_pos
            overlay_layers = 14
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                layer_rx = inner_rx + (cutoff_rx - inner_rx) * mix
                layer_ry = inner_ry + (cutoff_ry - inner_ry) * mix
                layer_color = hsv_to_hex(0.0, 0.94, 0.34 + mix * 0.28)
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3)
            c.create_oval(cx - inner_rx, cy - inner_ry, cx + inner_rx, cy + inner_ry, outline="#ff3c2e", width=4)
            c.create_oval(cx - cutoff_rx, cy - cutoff_ry, cx + cutoff_rx, cy + cutoff_ry, outline="#ffd08a", width=3)
            c.create_text(cx, cy + outer_ry + 18, text=f"HPF {self.player.mic_pre_hpf_hz:.0f} Hz", fill="#f6a864", font=("Orbitron", 10, "bold"))

    def _bottom_slot_positions(self, width: int, count: int):
        gap = width / (count + 1)
        return [gap * idx for idx in range(1, count + 1)]

    def _draw_mic_pre_buttons(self, c: tk.Canvas, w: int, h: int):
        button_y = h - 64
        buttons = [
            ("lpf", "LPF", self.lpf_var.get(), w * 0.16),
            ("phantom", "48V", self.phantom_var.get(), w * 0.33),
            ("phase", "PHS", self.phase_var.get(), w * 0.50),
            ("tube", "TBE", self.tube_var.get(), w * 0.67),
            ("hpf", "HPF", self.hpf_var.get(), w * 0.84),
        ]
        for key, label, active, x in buttons:
            selected = self.mic_pre_selected.get() == key
            fill = "#f6a864" if active else "#24303a"
            outline = "#ffd490" if active else "#4f667b"
            if selected:
                outline = "#ff8456"
            text_color = "#12161a" if active else "#c9d8e6"
            c.create_rectangle(x - 44, button_y - 18, x + 44, button_y + 18, fill=fill, outline=outline, width=2)
            c.create_text(x, button_y, text=label, fill=text_color, font=("Orbitron", 11, "bold"))

    def _draw_harmonics_stage(self, c: tk.Canvas, w: int, h: int):
        labels = ["H2", "H3", "H4", "H5", "H6", "MAKE"]
        cx = w // 2
        c.create_text(cx, 96, text="Harmonics", fill="#f1dea4", font=("Orbitron", 20, "bold"))
        c.create_text(cx, 118, text="Left/right selects bottom control. Turn changes amount or makeup.", fill="#7da0be", font=("Segoe UI", 10))
        c.create_text(cx, 144, text="Active overtone targets appear on the POL map in Test Tone mode.", fill="#9fb6cb", font=("Segoe UI", 10))
        meter_y = h - 56
        positions = self._bottom_slot_positions(w, 6)
        for idx, (label, x) in enumerate(zip(labels, positions)):
            value = self.harmonic_values[idx] if idx < 5 else self.harmonic_makeup_var.get() / 2.5
            fill_h = value * 64
            selected = self.harmonic_selected.get() == idx
            c.create_rectangle(x - 38, meter_y - 64, x + 38, meter_y, outline="#4f667b", width=2)
            c.create_rectangle(x - 34, meter_y - fill_h, x + 34, meter_y - 2, fill="#f6a864" if selected else "#5b86ff", outline="")
            c.create_text(x, meter_y + 14, text=label, fill="#c9d8e6", font=("Orbitron", 10, "bold"))
            readout = f"{self.harmonic_values[idx]:.2f}" if idx < 5 else f"{self.harmonic_makeup_var.get():.2f}x"
            c.create_text(x, meter_y - 78, text=readout, fill="#11151a" if selected else "#d8e6f2", font=("Segoe UI", 10, "bold"))
            if selected:
                c.create_rectangle(x - 44, meter_y - 70, x + 44, meter_y + 6, outline="#ffd490", width=2)

    def _draw_harmonic_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float, mode: str):
        base_hz = None
        if mode == "tone":
            base_hz = float(self.tone_frequency_var.get())
        if base_hz is None:
            c.create_text(cx, 54, text="Harmonic overlay tracks best with Test Tone", fill="#7da0be", font=("Segoe UI", 9))
            return

        for idx, value in enumerate(self.harmonic_values):
            if value <= 0.01:
                continue
            harmonic_order = idx + 2
            freq = min(POL_HIGH_HZ, base_hz * harmonic_order)
            band_pos = (math.log10(freq) - LOG_LOW) / (LOG_HIGH - LOG_LOW)
            band_pos = max(0.0, min(1.0, band_pos))
            rx = outer_rx - (outer_rx - inner_rx) * band_pos
            ry = outer_ry - (outer_ry - inner_ry) * band_pos
            heat = value
            expand = 8 + heat * 14
            color = hsv_to_hex(0.12 - idx * 0.015, 0.85, 0.55 + heat * 0.4)
            glow = hsv_to_hex(0.16 - idx * 0.012, 0.45, 0.22 + heat * 0.35)
            c.create_oval(cx - rx - expand, cy - ry - expand * 0.72, cx + rx + expand, cy + ry + expand * 0.72, outline=glow, width=1)
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 + int(heat * 3))
            label_y = cy - ry - 18
            c.create_text(cx, label_y, text=f"H{harmonic_order} {freq:.0f} Hz", fill=color, font=("Orbitron", 9, "bold"))

    def _draw_eq_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        if not self.eq_bands:
            return
        freq_selected = self.eq_nav_row.get() == "bottom" and self.eq_param_selected.get() == 2
        width_selected = self.eq_nav_row.get() == "bottom" and self.eq_param_selected.get() == 4
        for idx, band in enumerate(self.eq_bands):
            if not band.get("enabled", True):
                continue
            center = float(np.clip(band["freq"], POL_LOW_HZ, POL_HIGH_HZ))
            band_pos = self._freq_to_slider(center)
            rx = outer_rx - (outer_rx - inner_rx) * band_pos
            ry = outer_ry - (outer_ry - inner_ry) * band_pos
            selected = idx == self.eq_band_selected.get()
            kind = band["type"]
            gain_db = float(band["gain_db"])
            width = float(np.clip(band["width"], 0.20, 6.0))
            if kind == "BELL":
                start_hz = max(POL_LOW_HZ, center / (2 ** (width / 2)))
                end_hz = min(POL_HIGH_HZ, center * (2 ** (width / 2)))
                start_pos = self._freq_to_slider(start_hz)
                end_pos = self._freq_to_slider(end_hz)
                start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
                start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
                end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
                end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
                color = eq_gain_color(gain_db)
                edge = "#fff2d8" if selected and (freq_selected or width_selected) else color
                band_layers = 9 if selected else 6
                for layer in range(band_layers):
                    mix = layer / max(1, band_layers - 1)
                    layer_rx = start_rx + (end_rx - start_rx) * mix
                    layer_ry = start_ry + (end_ry - start_ry) * mix
                    layer_color = "#fff2d8" if selected and freq_selected and abs(mix - 0.5) < 0.18 else color
                    layer_width = 3 if selected else 2
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=layer_width)
                if selected and width_selected:
                    c.create_oval(cx - start_rx, cy - start_ry, cx + start_rx, cy + start_ry, outline=edge, width=2)
                    c.create_oval(cx - end_rx, cy - end_ry, cx + end_rx, cy + end_ry, outline=edge, width=2)
            elif kind in ("LOW SHELF", "HIGH SHELF"):
                color = eq_gain_color(gain_db)
                edge = "#fff2d8" if selected and (freq_selected or width_selected) else color
                transition_oct = max(0.20, min(3.0, width))
                if kind == "LOW SHELF":
                    trans_end_hz = min(POL_HIGH_HZ, center * (2 ** transition_oct))
                    trans_end_pos = self._freq_to_slider(trans_end_hz)
                    trans_end_rx = outer_rx - (outer_rx - inner_rx) * trans_end_pos
                    trans_end_ry = outer_ry - (outer_ry - inner_ry) * trans_end_pos
                    band_layers = 10 if selected else 7
                    for layer in range(band_layers):
                        mix = layer / max(1, band_layers - 1)
                        layer_rx = rx + (trans_end_rx - rx) * mix
                        layer_ry = ry + (trans_end_ry - ry) * mix
                        layer_color = "#fff2d8" if selected and freq_selected and layer == 0 else color
                        c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3 if selected else 2)
                    c.create_oval(cx - outer_rx, cy - outer_ry, cx + outer_rx, cy + outer_ry, outline=color, width=3 if selected else 2)
                    if selected and width_selected:
                        c.create_oval(cx - trans_end_rx, cy - trans_end_ry, cx + trans_end_rx, cy + trans_end_ry, outline=edge, width=2)
                else:
                    trans_start_hz = max(POL_LOW_HZ, center / (2 ** transition_oct))
                    trans_start_pos = self._freq_to_slider(trans_start_hz)
                    trans_start_rx = outer_rx - (outer_rx - inner_rx) * trans_start_pos
                    trans_start_ry = outer_ry - (outer_ry - inner_ry) * trans_start_pos
                    band_layers = 10 if selected else 7
                    for layer in range(band_layers):
                        mix = layer / max(1, band_layers - 1)
                        layer_rx = trans_start_rx + (rx - trans_start_rx) * mix
                        layer_ry = trans_start_ry + (ry - trans_start_ry) * mix
                        layer_color = "#fff2d8" if selected and freq_selected and layer == band_layers - 1 else color
                        c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3 if selected else 2)
                    c.create_oval(cx - inner_rx, cy - inner_ry, cx + inner_rx, cy + inner_ry, outline=color, width=3 if selected else 2)
                    if selected and width_selected:
                        c.create_oval(cx - trans_start_rx, cy - trans_start_ry, cx + trans_start_rx, cy + trans_start_ry, outline=edge, width=2)
            elif kind == "LPF":
                for layer in range(10):
                    mix = layer / 9.0
                    layer_rx = rx + (outer_rx - rx) * mix
                    layer_ry = ry + (outer_ry - ry) * mix
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline="#d22a1c", width=2)
            elif kind == "HPF":
                for layer in range(10):
                    mix = layer / 9.0
                    layer_rx = inner_rx + (rx - inner_rx) * mix
                    layer_ry = inner_ry + (ry - inner_ry) * mix
                    c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline="#d22a1c", width=2)
            if selected:
                c.create_text(cx, cy - ry - 18, text=f"{kind} {center:.0f} Hz", fill="#f6a864", font=("Orbitron", 10, "bold"))

    def _draw_eq_stage(self, c: tk.Canvas, w: int, h: int):
        cx = w // 2
        c.create_text(cx, 88, text="EQ", fill="#f1dea4", font=("Orbitron", 20, "bold"))
        c.create_text(cx, 110, text="Up goes to band row. Left/right selects a band. Down returns to edit row.", fill="#7da0be", font=("Segoe UI", 10))
        if self.eq_bands:
            active = self.eq_bands[self.eq_band_selected.get()]
            c.create_text(cx, 132, text=f"Band {self.eq_band_selected.get() + 1}/{len(self.eq_bands)}  {active['type']}  {active['freq']:.0f} Hz  {active['gain_db']:+.1f} dB", fill="#f6a864", font=("Segoe UI", 10, "bold"))
        top_y = 156
        band_positions = self._bottom_slot_positions(w, max(1, len(self.eq_bands)))
        for idx, x in enumerate(band_positions):
            band = self.eq_bands[idx]
            selected = idx == self.eq_band_selected.get()
            focused = selected and self.eq_nav_row.get() == "top"
            fill = "#f6a864" if selected else "#24303a"
            outline = "#ffd490" if focused else ("#f6a864" if selected else "#4f667b")
            text_color = "#11151a" if selected else "#c9d8e6"
            c.create_rectangle(x - 40, top_y - 18, x + 40, top_y + 18, fill=fill, outline=outline, width=3 if focused else 2)
            c.create_text(x, top_y - 6, text=f"B{idx + 1}", fill=text_color, font=("Orbitron", 9, "bold"))
            c.create_text(x, top_y + 9, text=f"{band['freq']:.0f}", fill=text_color, font=("Segoe UI", 9, "bold"))
        params = [
            ("NEW", "", ""),
            ("TYPE", self.eq_bands[self.eq_band_selected.get()]["type"] if self.eq_bands else "", ""),
            ("FREQ", f"{self.eq_bands[self.eq_band_selected.get()]['freq']:.0f}" if self.eq_bands else "", "Hz"),
            ("GAIN", f"{self.eq_bands[self.eq_band_selected.get()]['gain_db']:+.1f}" if self.eq_bands else "", "dB"),
            ("WIDTH", f"{self.eq_bands[self.eq_band_selected.get()]['width']:.2f}" if self.eq_bands else "", "oct"),
        ]
        positions = self._bottom_slot_positions(w, 5)
        y = h - 64
        for idx, ((label, value, suffix), x) in enumerate(zip(params, positions)):
            selected = self.eq_param_selected.get() == idx and self.eq_nav_row.get() == "bottom"
            fill = "#f6a864" if selected else "#24303a"
            outline = "#ffd490" if selected else "#4f667b"
            text_color = "#11151a" if selected else "#c9d8e6"
            c.create_rectangle(x - 42, y - 24, x + 42, y + 24, fill=fill, outline=outline, width=2)
            c.create_text(x, y - 7, text=label, fill=text_color, font=("Orbitron", 9, "bold"))
            c.create_text(x, y + 10, text=f"{value}{suffix}", fill=text_color, font=("Segoe UI", 10, "bold"))

    def _draw_placeholder_stage(self, c: tk.Canvas, w: int, h: int, title: str, subtitle: str):
        cx = w // 2
        cy = h // 2
        c.create_rectangle(96, 116, w - 96, h - 116, outline="#4f667b", width=2)
        c.create_text(cx, cy - 34, text=title, fill="#f1dea4", font=("Orbitron", 22, "bold"))
        c.create_text(cx, cy + 4, text=subtitle, fill="#9fb6cb", font=("Segoe UI", 13))
        c.create_text(cx, cy + 44, text="Stage view scaffolded. Behavior comes next.", fill="#7da0be", font=("Segoe UI", 11))

    def _draw_tone_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        mode = self.tone_mode_var.get()
        state = self.tone_state_by_mode[mode]
        preview_only = False
        if not state["enabled"]:
            if self.tone_nav_row.get() == "bottom":
                if mode == "TRN" and self.tone_selected.get() in (0, 1, 2, 3):
                    preview_only = True
                elif mode == "XCT" and self.tone_selected.get() in (0, 1, 2, 3):
                    preview_only = True
                elif mode == "CLR" and self.tone_selected.get() in (0, 1, 2, 3):
                    preview_only = True
            if not preview_only:
                return
        if mode == "TRN":
            center = float(state["freq"])
            width = float(state["width"])
            if preview_only:
                center = float(self._slider_to_freq(self.tone_freq_position_var.get()))
                width = float(self.tone_width_var.get())
            start_hz = max(POL_LOW_HZ, center / (2 ** (width / 2)))
            end_hz = min(POL_HIGH_HZ, center * (2 ** (width / 2)))
            start_pos = self._freq_to_slider(start_hz)
            end_pos = self._freq_to_slider(end_hz)
            start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
            start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
            end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
            end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
            layers = 10
            for layer in range(layers):
                mix = layer / max(1, layers - 1)
                layer_rx = start_rx + (end_rx - start_rx) * mix
                layer_ry = start_ry + (end_ry - start_ry) * mix
                if self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 2:
                    attack_heat = float(self.trn_attack_var.get())
                    color = lerp_color((105, 223, 242), (255, 92, 58), attack_heat)
                elif self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 3:
                    sustain_heat = float(self.trn_sustain_var.get())
                    color = lerp_color((105, 223, 242), (255, 92, 58), sustain_heat)
                else:
                    color = "#fff2d8" if preview_only else lerp_color((255, 216, 150), (255, 92, 58), mix)
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=color, width=2 if preview_only else 2)
            label = f"TRN {center:.0f} Hz / {width:.2f} oct"
            label_fill = "#fff2d8" if preview_only else "#f6a864"
            if self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 2:
                label_fill = lerp_color((105, 223, 242), (255, 92, 58), float(self.trn_attack_var.get()))
                label = f"TRN ATTACK {self.trn_attack_var.get():.2f}"
            elif self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 3:
                label_fill = lerp_color((105, 223, 242), (255, 92, 58), float(self.trn_sustain_var.get()))
                label = f"TRN SUSTAIN {self.trn_sustain_var.get():.2f}"
            c.create_text(cx, cy - end_ry - 18, text=label, fill=label_fill, font=("Orbitron", 10, "bold"))
        elif mode == "CLR":
            drive = float(self.clr_drive_var.get()) if preview_only else float(state["drive"])
            tone = float(self.clr_tone_var.get()) if preview_only else float(state["tone"])
            mix = float(self.clr_mix_var.get()) if preview_only else float(state["mix"])
            gain = float(self.clr_gain_var.get()) if preview_only else float(state["gain"])
            outer_glow = 18 + drive * 30
            core_glow = 8 + mix * 22
            brightness = max(0.35, min(1.0, (gain - 0.5) / 2.0))
            warm = (255, int(170 + drive * 50), 92)
            cool = (110, 214, 255)
            tone_t = (tone + 1.0) / 2.0
            tone_color = lerp_color(cool, warm, tone_t)
            edge_color = "#fff2d8" if preview_only else tone_color
            for layer in range(6):
                layer_mix = layer / 5.0
                layer_rx = inner_rx + outer_glow * (0.35 + layer_mix * 0.75)
                layer_ry = inner_ry + outer_glow * 0.72 * (0.35 + layer_mix * 0.75)
                layer_color = edge_color if layer == 0 else lerp_color((40, 62, 86), (255, 110, 66), max(0.0, min(1.0, drive * brightness * (0.3 + layer_mix * 0.7))))
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=layer_color, width=3 if layer == 0 else 2)
            inner_color = lerp_color((120, 210, 255), (255, 170, 95), tone_t)
            c.create_oval(cx - inner_rx - core_glow, cy - inner_ry - core_glow * 0.72, cx + inner_rx + core_glow, cy + inner_ry + core_glow * 0.72, outline=inner_color, width=3)
            label = f"CLR DRIVE {drive:.2f}"
            label_fill = edge_color
            if self.tone_nav_row.get() == "bottom":
                if self.tone_selected.get() == 1:
                    label = f"CLR TONE {tone:+.2f}"
                elif self.tone_selected.get() == 2:
                    label = f"CLR MIX {mix:.2f}"
                elif self.tone_selected.get() == 3:
                    label = f"CLR GAIN {gain:.2f}x"
            c.create_text(cx, cy - inner_ry - outer_glow - 16, text=label, fill=label_fill, font=("Orbitron", 10, "bold"))
        elif mode == "XCT":
            center = float(state["freq"])
            width = float(state["width"])
            amount = float(state["amount"])
            mix_amt = float(state["mix"])
            if preview_only:
                center = float(self._slider_to_freq(self.xct_freq_position_var.get()))
                width = float(self.xct_width_var.get())
                amount = float(self.xct_amount_var.get())
                mix_amt = float(self.xct_mix_var.get())
            start_hz = max(POL_LOW_HZ, center / (2 ** (width / 2)))
            end_hz = min(POL_HIGH_HZ, center * (2 ** (width / 2)))
            start_pos = self._freq_to_slider(start_hz)
            end_pos = self._freq_to_slider(end_hz)
            start_rx = outer_rx - (outer_rx - inner_rx) * start_pos
            start_ry = outer_ry - (outer_ry - inner_ry) * start_pos
            end_rx = outer_rx - (outer_rx - inner_rx) * end_pos
            end_ry = outer_ry - (outer_ry - inner_ry) * end_pos
            layers = 7
            for layer in range(layers):
                mix = layer / max(1, layers - 1)
                layer_rx = start_rx + (end_rx - start_rx) * mix
                layer_ry = start_ry + (end_ry - start_ry) * mix
                if preview_only and self.tone_selected.get() in (0, 1):
                    color = "#fff2d8"
                else:
                    base_color = lerp_color((96, 201, 255), (98, 255, 198), mix)
                    if self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 2:
                        base_color = lerp_color((86, 148, 255), (170, 255, 244), amount)
                    elif self.tone_nav_row.get() == "bottom" and self.tone_selected.get() == 3:
                        base_color = lerp_color((72, 110, 196), (130, 255, 220), mix_amt)
                    color = base_color
                c.create_oval(cx - layer_rx, cy - layer_ry, cx + layer_rx, cy + layer_ry, outline=color, width=2 + int(amount * 2))
            flare = 8 + amount * 18
            c.create_oval(
                cx - end_rx - flare,
                cy - end_ry - flare * 0.72,
                cx + end_rx + flare,
                cy + end_ry + flare * 0.72,
                outline=lerp_color((88, 188, 255), (194, 255, 238), mix_amt),
                width=2,
            )
            label = f"XCT {center:.0f} Hz / {width:.2f} oct"
            label_fill = "#fff2d8" if preview_only and self.tone_selected.get() in (0, 1) else "#9af2ff"
            if self.tone_nav_row.get() == "bottom":
                if self.tone_selected.get() == 2:
                    label = f"XCT AMOUNT {amount:.2f}"
                    label_fill = lerp_color((86, 148, 255), (170, 255, 244), amount)
                elif self.tone_selected.get() == 3:
                    label = f"XCT MIX {mix_amt:.2f}"
                    label_fill = lerp_color((72, 110, 196), (130, 255, 220), mix_amt)
            c.create_text(cx, cy - end_ry - 18, text=label, fill=label_fill, font=("Orbitron", 10, "bold"))

    def _draw_tone_stage(self, c: tk.Canvas, w: int, h: int):
        cx = w // 2
        mode = self.tone_mode_var.get()
        state = self.tone_state_by_mode[mode]
        c.create_text(cx, 88, text="TRN / CLR / XCT", fill="#f1dea4", font=("Orbitron", 20, "bold"))
        c.create_text(cx, 110, text="Use up/down to move between processor and parameter rows. Left/right navigates within the active row. On the top row, SpaceMouse button 1 toggles the selected processor.", fill="#7da0be", font=("Segoe UI", 10))
        c.create_text(cx, 128, text=f"{mode} {'ON' if state['enabled'] else 'OFF'}", fill="#f6a864" if state["enabled"] else "#7da0be", font=("Segoe UI", 10, "bold"))
        top_y = 142
        processor_positions = [cx - 120, cx, cx + 120]
        c.create_text(cx, 166, text="Processor row active" if self.tone_nav_row.get() == "top" else "Parameter row active", fill="#f6a864" if self.tone_nav_row.get() == "top" else "#7da0be", font=("Segoe UI", 10, "bold"))
        for name, x in zip(["TRN", "CLR", "XCT"], processor_positions):
            enabled = self.tone_state_by_mode[name]["enabled"]
            selected = self.tone_mode_var.get() == name
            focused = self.tone_nav_row.get() == "top" and selected
            fill = "#f6a864" if enabled else "#24303a"
            outline = "#ffd490" if focused else ("#f6a864" if selected else "#4f667b")
            text_color = "#11151a" if enabled else "#c9d8e6"
            c.create_rectangle(x - 50, top_y - 18, x + 50, top_y + 18, fill=fill, outline=outline, width=3 if focused else 2)
            c.create_text(x, top_y, text=name, fill=text_color, font=("Orbitron", 10, "bold"))
        if mode == "TRN":
            params = [
                ("FREQ", f"{self._slider_to_freq(self.tone_freq_position_var.get()):.0f}", "Hz"),
                ("WIDTH", f"{self.tone_width_var.get():.2f}", "oct"),
                ("ATTACK", f"{self.trn_attack_var.get():.2f}", ""),
                ("SUSTAIN", f"{self.trn_sustain_var.get():.2f}", ""),
            ]
        elif mode == "CLR":
            params = [
                ("DRIVE", f"{self.clr_drive_var.get():.2f}", ""),
                ("TONE", f"{self.clr_tone_var.get():+.2f}", ""),
                ("MIX", f"{self.clr_mix_var.get():.2f}", ""),
                ("GAIN", f"{self.clr_gain_var.get():.2f}", "x"),
            ]
        else:
            params = [
                ("FREQ", f"{self._slider_to_freq(self.xct_freq_position_var.get()):.0f}", "Hz"),
                ("WIDTH", f"{self.xct_width_var.get():.2f}", "oct"),
                ("AMOUNT", f"{self.xct_amount_var.get():.2f}", ""),
                ("MIX", f"{self.xct_mix_var.get():.2f}", ""),
            ]
        positions = self._bottom_slot_positions(w, 4)
        y = h - 64
        for idx, ((label, value, suffix), x) in enumerate(zip(params, positions)):
            selected = self.tone_selected.get() == idx and self.tone_nav_row.get() == "bottom"
            fill = "#f6a864" if selected else "#24303a"
            outline = "#ffd490" if selected else "#4f667b"
            text_color = "#11151a" if selected else "#c9d8e6"
            c.create_rectangle(x - 48, y - 24, x + 48, y + 24, fill=fill, outline=outline, width=2)
            c.create_text(x, y - 7, text=label, fill=text_color, font=("Orbitron", 9, "bold"))
            c.create_text(x, y + 10, text=f"{value}{suffix}", fill=text_color, font=("Segoe UI", 10, "bold"))

    def _draw_compressor_stage(self, c: tk.Canvas, w: int, h: int, comp_gr_db: float):
        cx = w // 2
        cy = h // 2
        freq_hz = self._slider_to_freq(self.comp_freq_position_var.get())
        width_label = "ALL" if self.comp_width_var.get() >= 5.9 else f"{self.comp_width_var.get():.2f} oct"
        selected_mode = self.comp_mode_var.get()
        band_engaged = self.comp_state_by_mode[selected_mode]["band_enabled"]
        params = [
            ("THR", self.comp_threshold_var.get(), "dB"),
            ("ATT", self.comp_attack_var.get(), "ms"),
            ("REL", self.comp_release_var.get(), "ms"),
            ("RAT", self.comp_ratio_var.get(), ":1"),
            ("MAKE", self.comp_makeup_var.get(), "x"),
            ("FREQ", f"{freq_hz:.0f}", "Hz"),
            ("WIDTH", width_label, ""),
        ]
        c.create_text(cx, 88, text="Compressor", fill="#f1dea4", font=("Orbitron", 20, "bold"))
        c.create_text(cx, 110, text="Use up/down to move between processor and parameter rows. Left/right navigates within the active row. On the top row, SpaceMouse button 1 toggles the selected processor.", fill="#7da0be", font=("Segoe UI", 10))
        if band_engaged:
            c.create_text(cx, 128, text=f"Band target ON: {freq_hz:.0f} Hz / {width_label}", fill="#f6a864", font=("Segoe UI", 10, "bold"))
        else:
            c.create_text(cx, 128, text="Band target OFF: full-range processor (down on FREQ/WIDTH toggles ON/OFF)", fill="#7da0be", font=("Segoe UI", 10))
        top_y = 142
        processor_positions = [cx - 120, cx, cx + 120]
        if self.comp_nav_row.get() == "top":
            c.create_text(cx, 166, text="Processor row active", fill="#f6a864", font=("Segoe UI", 10, "bold"))
        else:
            c.create_text(cx, 166, text="Parameter row active", fill="#7da0be", font=("Segoe UI", 10, "bold"))
        for mode_name, x in zip(["COMP", "LIMIT", "GATE"], processor_positions):
            enabled = self.comp_enabled_vars[mode_name].get()
            selected = selected_mode == mode_name
            focused = self.comp_nav_row.get() == "top" and selected
            fill = "#f6a864" if enabled else "#24303a"
            outline = "#ffd490" if focused else ("#f6a864" if selected else "#4f667b")
            text_color = "#11151a" if enabled else "#c9d8e6"
            c.create_rectangle(x - 50, top_y - 18, x + 50, top_y + 18, fill=fill, outline=outline, width=3 if focused else 2)
            c.create_text(x, top_y, text=mode_name, fill=text_color, font=("Orbitron", 10, "bold"))
        gr = max(0.0, comp_gr_db)
        gr_text = f"GR {gr:.1f} dB"
        c.create_text(cx, cy - 36, text=f"{selected_mode} {gr_text}", fill="#f6a864", font=("Orbitron", 18, "bold"))
        c.create_text(cx, cy + 40, text="Compressor can stay on while limiter or gate are stacked on top.", fill="#9fb6cb", font=("Segoe UI", 11))
        positions = self._bottom_slot_positions(w, 7)
        y = h - 64
        for idx, ((label, value, suffix), x) in enumerate(zip(params, positions)):
            selected = self.comp_selected.get() == idx and self.comp_nav_row.get() == "bottom"
            state_suffix = ""
            if label in ("FREQ", "WIDTH"):
                state_suffix = " ON" if band_engaged else " OFF"
            fill = "#f6a864" if selected else "#24303a"
            outline = "#ffd490" if selected else "#4f667b"
            text_color = "#11151a" if selected else "#c9d8e6"
            if label in ("FREQ", "WIDTH") and band_engaged:
                outline = "#ff8456" if not selected else "#ffd490"
                if not selected:
                    fill = "#2c1e1a"
                    text_color = "#ffd8c8"
            c.create_rectangle(x - 40, y - 24, x + 40, y + 24, fill=fill, outline=outline, width=2)
            c.create_text(x, y - 7, text=f"{label}{state_suffix}", fill=text_color, font=("Orbitron", 9, "bold"))
            if label == "THR":
                value_text = f"{value:.0f}{suffix}"
            elif label == "RAT":
                value_text = f"{value:.1f}{suffix}"
            elif label == "MAKE":
                value_text = f"{value:.2f}{suffix}"
            elif label == "WIDTH":
                value_text = f"{value}{suffix}"
            elif label == "FREQ":
                value_text = f"{value}{suffix}"
            elif isinstance(value, str):
                value_text = f"{value}{suffix}"
            else:
                value_text = f"{value:.0f}{suffix}"
            c.create_text(x, y + 10, text=value_text, fill=text_color, font=("Segoe UI", 10, "bold"))

    def _processor_band_bounds(self, center_hz: float, width: float, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        if width >= 5.9:
            focus_start, focus_end = 0.0, 1.0
        else:
            start_hz = max(POL_LOW_HZ, center_hz / (2 ** (width / 2)))
            end_hz = min(POL_HIGH_HZ, center_hz * (2 ** (width / 2)))
            focus_start = self._freq_to_slider(start_hz)
            focus_end = self._freq_to_slider(end_hz)
        start_rx = outer_rx - (outer_rx - inner_rx) * focus_start
        start_ry = outer_ry - (outer_ry - inner_ry) * focus_start
        end_rx = outer_rx - (outer_rx - inner_rx) * focus_end
        end_ry = outer_ry - (outer_ry - inner_ry) * focus_end
        return start_rx, start_ry, end_rx, end_ry

    def _processor_display_bounds(self, settings: dict, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float):
        if not settings.get("band_enabled", False):
            return outer_rx, outer_ry, inner_rx, inner_ry
        return self._processor_band_bounds(settings["center"], settings["width"], outer_rx, outer_ry, inner_rx, inner_ry)

    def _processor_draw_settings(self, mode: str) -> dict:
        return dict(self.comp_state_by_mode[mode])

    def _draw_single_processor_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float, mode: str, settings: dict, comp_gr_db: float):
        start_rx, start_ry, end_rx, end_ry = self._processor_display_bounds(settings, outer_rx, outer_ry, inner_rx, inner_ry)
        now = time.monotonic()

        if mode != "GATE":
            c.create_oval(cx - start_rx, cy - start_ry, cx + start_rx, cy + start_ry, outline="#5a6f84", width=1)
            c.create_oval(cx - end_rx, cy - end_ry, cx + end_rx, cy + end_ry, outline="#5a6f84", width=1)

        if mode == "COMP":
            pressure = min(1.0, max(0.0, comp_gr_db / 18.0))
            threshold_norm = np.clip((-settings["threshold"]) / 48.0, 0.0, 1.0)
            threshold_pull = threshold_norm * 0.58
            attack_speed = 8.0 / max(0.8, settings["attack"])
            release_speed = 220.0 / max(20.0, settings["release"])
            breathe_rate = 0.9 + attack_speed * 1.2 + release_speed * 0.55
            breathe_depth = 0.012 + pressure * 0.070
            breathe_phase = math.sin(now * breathe_rate)
            darkness = min(1.0, max(0.0, (settings["ratio"] - 1.0) / 19.0))
            ring_fill = hsv_to_hex(0.0, 0.92, 0.88 - darkness * 0.34)
            ring_hot = hsv_to_hex(0.0, 0.05, 1.0 - darkness * 0.10)
            outer_wall_rx = start_rx
            outer_wall_ry = start_ry
            inner_threshold_rx = max(inner_rx, start_rx - (start_rx - end_rx) * threshold_pull)
            inner_threshold_ry = max(inner_ry, start_ry - (start_ry - end_ry) * threshold_pull)
            pulse_pull = pressure * (0.12 + threshold_norm * 0.10) * (1.0 + breathe_phase * breathe_depth)
            pump_rx = max(inner_rx, inner_threshold_rx - (inner_threshold_rx - end_rx) * pulse_pull)
            pump_ry = max(inner_ry, inner_threshold_ry - (inner_threshold_ry - end_ry) * pulse_pull)

            # Permanent threshold overlay: outer edge stays pinned, threshold sets the
            # collapsing inner boundary. The band itself gets wider as threshold goes up.
            overlay_layers = 8 + int(10 * darkness)
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                layer_rx = pump_rx + (outer_wall_rx - pump_rx) * mix
                layer_ry = pump_ry + (outer_wall_ry - pump_ry) * mix
                layer_brightness = 0.28 + mix * 0.18 + darkness * 0.22
                layer_color = hsv_to_hex(0.0, 0.84, min(1.0, layer_brightness))
                layer_width = 1 + int(darkness * 2)
                c.create_oval(
                    cx - layer_rx,
                    cy - layer_ry,
                    cx + layer_rx,
                    cy + layer_ry,
                    outline=layer_color,
                    width=layer_width,
                )
            # Fixed outer zero-dB wall.
            c.create_oval(
                cx - outer_wall_rx,
                cy - outer_wall_ry,
                cx + outer_wall_rx,
                cy + outer_wall_ry,
                outline=ring_fill,
                width=4 + int(darkness * 3),
            )
            # Threshold guide plus pumping inner compression edge.
            guide_color = hsv_to_hex(0.0, 0.58, 0.52 + darkness * 0.18)
            c.create_oval(
                cx - inner_threshold_rx,
                cy - inner_threshold_ry,
                cx + inner_threshold_rx,
                cy + inner_threshold_ry,
                outline=guide_color,
                width=2,
            )
            pulse_width = 4 + int(pressure * 4) + int(darkness * 2)
            c.create_oval(cx - outer_wall_rx - 1, cy - outer_wall_ry - 1, cx + outer_wall_rx + 1, cy + outer_wall_ry + 1, outline=ring_hot, width=1)
            c.create_oval(cx - pump_rx, cy - pump_ry, cx + pump_rx, cy + pump_ry, outline=ring_fill, width=pulse_width)
            c.create_oval(cx - pump_rx - 1, cy - pump_ry - 1, cx + pump_rx + 1, cy + pump_ry + 1, outline=ring_hot, width=1)
        elif mode == "LIMIT":
            pressure = min(1.0, max(0.0, comp_gr_db / 18.0))
            threshold_norm = np.clip((-settings["threshold"]) / 48.0, 0.0, 1.0)
            darkness = min(1.0, max(0.0, (settings["ratio"] - 1.0) / 19.0))
            outer_wall_rx = start_rx
            outer_wall_ry = start_ry
            inner_threshold_rx = max(inner_rx, start_rx - (start_rx - end_rx) * (threshold_norm * 0.92))
            inner_threshold_ry = max(inner_ry, start_ry - (start_ry - end_ry) * (threshold_norm * 0.92))
            strike = max(0.0, pressure)
            if strike > 0.001:
                slam = 1.0 + math.sin(now * 28.0) * (strike * 0.045)
            else:
                slam = 1.0
            slam_rx = max(inner_rx, inner_threshold_rx * slam)
            slam_ry = max(inner_ry, inner_threshold_ry * slam)
            wall = hsv_to_hex(0.0, 0.96, 0.86 - darkness * 0.26)
            wall_hot = hsv_to_hex(0.0, 0.04, 1.0)
            overlay_layers = 10 + int(12 * darkness)
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                layer_rx = slam_rx + (outer_wall_rx - slam_rx) * mix
                layer_ry = slam_ry + (outer_wall_ry - slam_ry) * mix
                layer_color = hsv_to_hex(0.0, 0.92, min(1.0, 0.42 + darkness * 0.24 + mix * 0.16))
                c.create_oval(
                    cx - layer_rx,
                    cy - layer_ry,
                    cx + layer_rx,
                    cy + layer_ry,
                    outline=layer_color,
                    width=2 + int(darkness * 2),
                )
            c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline=wall, width=5 + int(darkness * 3))
            c.create_oval(cx - slam_rx, cy - slam_ry, cx + slam_rx, cy + slam_ry, outline=wall, width=5 + int(strike * 5))
            c.create_oval(cx - outer_wall_rx - 1, cy - outer_wall_ry - 1, cx + outer_wall_rx + 1, cy + outer_wall_ry + 1, outline=wall_hot, width=1)
            if strike > 0.001:
                c.create_oval(cx - slam_rx - 1, cy - slam_ry - 1, cx + slam_rx + 1, cy + slam_ry + 1, outline=wall_hot, width=1)
        elif mode == "GATE":
            gate_open = min(1.0, max(0.0, comp_gr_db / 24.0))
            threshold_norm = np.clip((-settings["threshold"]) / 48.0, 0.0, 1.0)
            openness = gate_open
            darkness = min(1.0, max(0.0, (settings["ratio"] - 1.0) / 19.0))
            closed_red = hsv_to_hex(0.0, 0.94, 0.74 - darkness * 0.16)
            closed_hot = hsv_to_hex(0.06, 0.72, 0.98)
            outer_wall_rx = start_rx
            outer_wall_ry = start_ry
            inner_threshold_rx = max(end_rx, start_rx - (start_rx - end_rx) * (threshold_norm * 0.92))
            inner_threshold_ry = max(end_ry, start_ry - (start_ry - end_ry) * (threshold_norm * 0.92))
            gate_open_rx = inner_threshold_rx + (outer_wall_rx - inner_threshold_rx) * openness
            gate_open_ry = inner_threshold_ry + (outer_wall_ry - inner_threshold_ry) * openness

            # Ring-only field so the gate does not wipe out the analyzer or other processors.
            # Quiet state: red rings from threshold to outer wall.
            # Open state: the red field retreats outward until it disappears at fully open.
            overlay_layers = 10 + int(10 * darkness)
            for layer in range(overlay_layers):
                mix = layer / max(1, overlay_layers - 1)
                inner_layer_rx = gate_open_rx if openness > 0.001 else inner_threshold_rx
                inner_layer_ry = gate_open_ry if openness > 0.001 else inner_threshold_ry
                layer_rx = inner_layer_rx + (outer_wall_rx - inner_layer_rx) * mix
                layer_ry = inner_layer_ry + (outer_wall_ry - inner_layer_ry) * mix
                layer_color = hsv_to_hex(0.0, 0.94, min(1.0, 0.46 + darkness * 0.16 + mix * 0.18))
                c.create_oval(
                    cx - layer_rx,
                    cy - layer_ry,
                    cx + layer_rx,
                    cy + layer_ry,
                    outline=layer_color,
                    width=2 + int(darkness * 2),
                )
            # When the gate is mostly closed, add a darker inner red veil so underlying
            # colors stop showing through inside the closed region.
            closed_amount = 1.0 - openness
            if closed_amount > 0.02:
                veil_rx = inner_threshold_rx + (gate_open_rx - inner_threshold_rx) * 0.55
                veil_ry = inner_threshold_ry + (gate_open_ry - inner_threshold_ry) * 0.55
                veil_layers = 5 + int(closed_amount * 8)
                for layer in range(veil_layers):
                    mix = layer / max(1, veil_layers - 1)
                    layer_rx = inner_threshold_rx + (veil_rx - inner_threshold_rx) * mix
                    layer_ry = inner_threshold_ry + (veil_ry - inner_threshold_ry) * mix
                    veil_color = hsv_to_hex(0.0, 0.98, 0.24 + closed_amount * 0.18 + mix * 0.10)
                    c.create_oval(
                        cx - layer_rx,
                        cy - layer_ry,
                        cx + layer_rx,
                        cy + layer_ry,
                        outline=veil_color,
                        width=3 + int(closed_amount * 3),
                    )
            c.create_oval(cx - outer_wall_rx, cy - outer_wall_ry, cx + outer_wall_rx, cy + outer_wall_ry, outline=closed_red, width=5 + int(darkness * 3))
            if openness > 0.001:
                c.create_oval(cx - gate_open_rx, cy - gate_open_ry, cx + gate_open_rx, cy + gate_open_ry, outline=closed_hot, width=2)
            else:
                c.create_oval(cx - inner_threshold_rx, cy - inner_threshold_ry, cx + inner_threshold_rx, cy + inner_threshold_ry, outline=closed_hot, width=2)
    def _draw_compressor_overlay(self, c: tk.Canvas, cx: int, cy: int, outer_rx: float, outer_ry: float, inner_rx: float, inner_ry: float, levels: np.ndarray, comp_gr_db: dict):
        any_enabled = False
        for mode in ("COMP", "LIMIT", "GATE"):
            if not self.comp_enabled_vars[mode].get():
                continue
            any_enabled = True
            settings = self._processor_draw_settings(mode)
            self._draw_single_processor_overlay(
                c,
                cx,
                cy,
                outer_rx,
                outer_ry,
                inner_rx,
                inner_ry,
                mode,
                settings,
                float(comp_gr_db.get(mode.lower(), 0.0)),
            )
        if not any_enabled:
            c.create_text(cx, 138, text="All processors bypassed", fill="#7da0be", font=("Segoe UI", 10))


def main():
    root = tk.Tk()
    PolVisualizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

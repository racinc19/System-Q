import math
import os
from pathlib import Path
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import butter, sosfilt, sosfilt_zi
from system_q_core import (
    _log, SAMPLE_RATE, BLOCK_SIZE, POL_BANDS, ROOT_DIR, STEMS_DIR,
    CHANNEL_LAYOUT, LOG_LOW, LOG_HIGH, POL_LOW_HZ, POL_HIGH_HZ,
    POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER,
    ChannelState, ensure_demo_stems
)

class ConsoleEngine:
    def __init__(self) -> None:
        ensure_demo_stems()
        self.channels = [self._load_channel(name, STEMS_DIR / filename) for name, filename in CHANNEL_LAYOUT]
        self.master_channel = ChannelState(name="Master", path=ROOT_DIR / "master_bus")
        self.master_channel.pre_enabled = False
        self.stream = None
        self.playing = False
        self.loop = False
        self.recording = False
        self.punch_recording = False
        self.automation_mode = "read"
        self.pre_roll_seconds = 2.0
        self.post_roll_seconds = 2.0
        self.markers: list[float] = []
        self.timeline_zoom = 1.0
        self.ignore_marker_cycle_until = 0.0
        self.scrub_audition_until = 0.0
        self.scrub_audition_freeze = False
        self.master_gain = 0.82
        self.master_level = 0.0
        self.output_device = self._select_output_device()
        self.output_device_name = self._output_device_name(self.output_device)
        self.output_peak = 0.0
        self._lock = threading.Lock()
        self.generator_mode = "none"
        self.osc_hz = 440.0
        self.osc_phase = 0.0
        self._pink_b = np.zeros(6, dtype=np.float64)
        self.generator_gain = 0.11
        self.generator_lfo_hz = 0.55
        self.generator_lfo_phase = 0.0
        self._bootstrap_cleared_mix_state()

    def _bootstrap_cleared_mix_state(self) -> None:
        for ch in getattr(self, "channels", []) or []:
            ch.solo = ch.mute = ch.record_armed = ch.pre_enabled = ch.phantom = ch.phase = ch.tube = False
            ch.pre_gain_db = 0.0
            ch.pre_squeeze = 1.0
            ch.harm_tube = ch.gate_tube = ch.comp_tube = ch.eq_tube = ch.lpf_enabled = ch.hpf_enabled = False
            ch.lpf_hz, ch.hpf_hz = 5000.0, 200.0
            ch.harmonics_enabled = ch.comp_enabled = ch.limit_enabled = ch.gate_enabled = False
            ch.harmonics[:] = 0.0
            ch.harmonic_makeup = 1.0
            ch.comp_band_enabled = ch.limit_band_enabled = ch.gate_band_enabled = False
            ch.gate_dyn_band_count = 1
            ch.gate_dyn_ui_band = 0
            ch.comp_dyn_band_count = 1
            ch.comp_dyn_ui_band = 0
            for db in ch.gate_dyn_bands: db.update(enabled=False, freq=3000.0, width_oct=4.0, threshold_db=-45.0, ratio=8.0, attack_ms=3.0, release_ms=140.0, makeup=1.0)
            for db in ch.comp_dyn_bands: db.update(enabled=False, freq=3000.0, width_oct=4.0, threshold_db=-18.0, ratio=4.0, attack_ms=8.0, release_ms=120.0, makeup=1.0)
            ch.eq_enabled = ch.eq_band_enabled = False
            ch.eq_band_count, ch.eq_ui_band = 1, 0
            ch.eq_freq, ch.eq_gain_db, ch.eq_width, ch.eq_type = 2200.0, 0.0, 1.4, "BELL"
            for b in ch.eq_bands: b.update(enabled=False, freq=2200.0, gain_db=0.0, width=1.4, type="BELL", band_enabled=False)
            ch.eq_param_bypass.clear(); ch.gate_param_bypass.clear(); ch.comp_param_bypass.clear(); ch.harm_param_bypass.clear()
            ch.tone_param_bypass.clear(); ch.trn_param_bypass.clear(); ch.xct_param_bypass.clear(); ch.tbe_param_bypass.clear()
            ch.trn_enabled = ch.xct_enabled = ch.tbe_enabled = ch.trn_band_enabled = ch.xct_band_enabled = ch.tbe_band_enabled = False
            ch.trn_band_count, ch.trn_ui_band = 1, 0
            for b in ch.trn_bands: b.update(enabled=False, freq=136.0, width=1.12, attack=0.0, sustain=0.0, drive=0.0)
            ch.xct_band_count, ch.xct_ui_band = 1, 0
            for b in ch.xct_bands: b.update(enabled=False, freq=7000.0, width=1.20, attack=0.0, sustain=0.0, drive=0.0)
            ch.tbe_band_count, ch.tbe_ui_band = 1, 0
            ch.tbe_freq, ch.tbe_width = 2500.0, 1.40
            for b in ch.tbe_bands: b.update(enabled=False, freq=2500.0, width=1.40, drive=0.0)
            ch.trn_attack = ch.trn_sustain = ch.trn_drive = ch.xct_attack = ch.xct_sustain = ch.xct_drive = ch.tbe_drive = 0.0
            ch.position = 0
        if getattr(self, "master_channel", None):
            mc = self.master_channel
            mc.eq_enabled = mc.eq_band_enabled = mc.trn_enabled = mc.xct_enabled = mc.tbe_enabled = False

    def _load_channel(self, name: str, path: Path) -> ChannelState:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if sr != SAMPLE_RATE: raise ValueError(f"SR mismatch: {sr}")
        if data.shape[1] == 1: data = np.repeat(data, 2, axis=1)
        ch = ChannelState(name=name, path=path, audio=data[:, :2].astype(np.float32))
        ch.wave_preview = self._build_wave_preview(ch.audio)
        return ch

    @staticmethod
    def _build_wave_preview(audio: np.ndarray, buckets: int = 512) -> np.ndarray:
        if audio is None or len(audio) < 2: return np.ones((1,), dtype=np.float32) * 1e-4
        mono = np.mean(np.abs(audio.astype(np.float64)), axis=1)
        n = len(mono); b = max(32, min(buckets, n)); chunk = max(1, n // b); usable = (n // chunk) * chunk
        if usable < chunk: return np.ones((1,), dtype=np.float32) * 1e-4
        peaks = mono[:usable].reshape(-1, chunk).max(axis=1).astype(np.float32)
        mx = float(np.max(peaks))
        return (peaks / (mx if mx > 1e-12 else 1.0)).astype(np.float32)

    def start(self) -> None:
        if self.stream is None:
            _log.info(f"AUDIO_OUTPUT_START: device={self.output_device} name={self.output_device_name}")
            self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=2, dtype="float32", blocksize=BLOCK_SIZE, callback=self._callback, device=self.output_device)
            self.stream.start()
        self.playing = True

    def prime_stream(self) -> None:
        if self.stream is None:
            _log.info(f"AUDIO_OUTPUT_PRIME: device={self.output_device} name={self.output_device_name}")
            self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=2, dtype="float32", blocksize=BLOCK_SIZE, callback=self._callback, device=self.output_device)
            self.stream.start()
        self.playing = False

    def _select_output_device(self) -> int | None:
        requested = os.environ.get("SYSTEM_Q_OUTPUT_DEVICE", "").strip()
        devices = sd.query_devices()
        if requested:
            for i, dev in enumerate(devices):
                if dev.get("max_output_channels", 0) > 0 and requested.lower() in str(dev.get("name", "")).lower():
                    return i
            try:
                return int(requested)
            except ValueError:
                _log.warning(f"AUDIO_OUTPUT_DEVICE_NOT_FOUND: {requested}")
        default_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        try:
            default_name = str(sd.query_devices(int(default_out)).get("name", ""))
        except Exception:
            default_name = ""
        for i, dev in enumerate(devices):
            name = str(dev.get("name", ""))
            hostapi = sd.query_hostapis(int(dev.get("hostapi", -1))).get("name", "") if int(dev.get("hostapi", -1)) >= 0 else ""
            if dev.get("max_output_channels", 0) >= 2 and "WASAPI" in str(hostapi):
                if default_name and default_name.split(",")[0].lower() in name.lower():
                    return i
        for preferred in ("Realtek", "Primary Sound"):
            for i, dev in enumerate(devices):
                name = str(dev.get("name", ""))
                hostapi = sd.query_hostapis(int(dev.get("hostapi", -1))).get("name", "") if int(dev.get("hostapi", -1)) >= 0 else ""
                if dev.get("max_output_channels", 0) >= 2 and "WASAPI" in str(hostapi) and preferred.lower() in name.lower():
                    return i
        for i, dev in enumerate(devices):
            hostapi = sd.query_hostapis(int(dev.get("hostapi", -1))).get("name", "") if int(dev.get("hostapi", -1)) >= 0 else ""
            if dev.get("max_output_channels", 0) >= 2 and "WASAPI" in str(hostapi):
                return i
        try:
            return int(default_out)
        except Exception:
            return None

    def _output_device_name(self, device: int | None) -> str:
        try:
            if device is None:
                return "system default"
            return str(sd.query_devices(device).get("name", f"device {device}"))
        except Exception:
            return f"device {device}"

    def stop(self) -> None:
        self.playing = False
        self.recording = False
        self.punch_recording = False
        with self._lock:
            for ch in self.channels: ch.position = 0

    def toggle_play(self) -> None:
        if not self.playing and self.stream is None: self.start(); return
        self.playing = not self.playing
        if not self.playing:
            self.recording = False
            self.punch_recording = False

    def toggle_record(self) -> None:
        if not self.playing and self.stream is None:
            self.start()
        else:
            self.playing = True
        self.recording = not bool(getattr(self, "recording", False))
        self.punch_recording = bool(self.recording and self.loop)

    def rewind(self) -> None:
        with self._lock:
            for ch in self.channels: ch.position = 0

    def jump_end(self) -> None:
        with self._lock:
            for ch in self.channels:
                ch.position = max(0, len(ch.audio) - 1)

    def jump_forward(self, seconds: float = 5.0) -> None:
        s = int(seconds * SAMPLE_RATE)
        with self._lock:
            for ch in self.channels: ch.position = min(len(ch.audio)-1, ch.position + s)

    def jump_back(self, seconds: float = 5.0) -> None:
        s = int(seconds * SAMPLE_RATE)
        with self._lock:
            for ch in self.channels: ch.position = max(0, ch.position - s)

    def seek_seconds(self, t: float) -> None:
        with self._lock:
            if not self.channels: return
            pos = int(np.clip(t * SAMPLE_RATE, 0, max(0, max(len(ch.audio) for ch in self.channels)-1)))
            for ch in self.channels: ch.position = min(pos, len(ch.audio)-1)

    @property
    def playhead_seconds(self) -> float:
        return float(self.channels[0].position) / SAMPLE_RATE if self.channels else 0.0

    def timeline_duration_seconds(self) -> float:
        return float(len(self.channels[0].audio)) / SAMPLE_RATE if self.channels else 1.0

    def toggle_loop(self) -> None: self.loop = not self.loop

    def add_marker(self) -> None:
        t = self.playhead_seconds
        self.markers.append(t)

    def active_marker_range_samples(self) -> tuple[int, int] | None:
        if len(getattr(self, "markers", [])) < 2 or not self.channels:
            return None
        duration = self.timeline_duration_seconds()
        markers = sorted(float(np.clip(m, 0.0, duration)) for m in self.markers)
        playhead = self.playhead_seconds
        pairs = list(zip(markers[:-1], markers[1:]))
        active = next(((a, b) for a, b in pairs if a <= playhead <= b), None)
        if active is None:
            return None
        start_s, end_s = active
        start = int(np.clip(start_s * SAMPLE_RATE, 0, max(0, len(self.channels[0].audio) - 1)))
        end = int(np.clip(end_s * SAMPLE_RATE, start + 1, max(1, len(self.channels[0].audio))))
        return start, end
    def close(self) -> None:
        if self.stream: self.stream.stop(); self.stream.close(); self.stream = None

    def _generator_pulse_envelope(self, frames: int) -> np.ndarray:
        dt = (2.0 * math.pi * float(np.clip(self.generator_lfo_hz, 0.05, 14.0))) / SAMPLE_RATE
        t = float(self.generator_lfo_phase) + dt * np.arange(frames, dtype=np.float64)
        self.generator_lfo_phase = float((float(self.generator_lfo_phase) + frames * dt) % (2.0 * math.pi))
        return (0.08 + 0.92 * (0.5 + 0.5 * np.cos(t))).astype(np.float32)

    def _synthesize_generator(self, frames: int) -> np.ndarray:
        m, g = self.generator_mode, float(self.generator_gain)
        if m == "none" or frames <= 0: return np.zeros((frames, 2), dtype=np.float32)
        if m in ("white", "white_hot"):
            x = (np.random.randn(frames) * g * (2.35 if m == "white_hot" else 1.0)).astype(np.float32)
            return np.column_stack((x, x))
        if m in ("pink", "pink_pulse"):
            pink = np.empty(frames, dtype=np.float64); b = self._pink_b
            for i in range(frames):
                w = float(np.random.randn()) * 0.11
                b[0] = 0.99886*b[0] + w*0.0555179; b[1] = 0.99332*b[1] + w*0.0750759; b[2] = 0.96900*b[2] + w*0.1538520
                b[3] = 0.86650*b[3] + w*0.3104856; b[4] = 0.55000*b[4] + w*0.5329522; b[5] = -0.7616*b[5] - w*0.0168980
                pink[i] = b[0]+b[1]+b[2]+b[3]+b[4]+b[5] + w*0.5362
            x = (pink * g * 3.2).astype(np.float32)
            if m == "pink_pulse": x *= self._generator_pulse_envelope(frames)
            return np.column_stack((x, x))
        if m == "osc":
            dt = (2.0 * math.pi * float(np.clip(self.osc_hz, 20.0, 20000.0))) / SAMPLE_RATE
            t = float(self.osc_phase) + dt * np.arange(frames, dtype=np.float64)
            self.osc_phase = float((float(self.osc_phase) + frames * dt) % (2.0 * math.pi))
            s = (np.sin(t) * g * 1.15).astype(np.float32)
            return np.column_stack((s, s))
        return np.zeros((frames, 2), dtype=np.float32)

    def _callback(self, outdata, frames, time_info, status) -> None:
        try:
            gen_out = None
            with self._lock:
                if self.generator_mode != "none": gen_out = self._synthesize_generator(frames)
                aux_returns = list(getattr(self, "aux_return_states", []))
                efx_returns = []
                scrub_active = time.monotonic() < float(getattr(self, "scrub_audition_until", 0.0))
                if not self.playing and scrub_active and bool(getattr(self, "scrub_audition_freeze", False)):
                    states = [{"ch": ch, "gain": ch.gain, "pan": ch.pan, "mute": ch.mute, "solo": ch.solo, "pos": ch.position} for ch in self.channels]
                    source_any_solo = any(ch.solo for ch in self.channels)
                    return_any_solo = any(getattr(ch, "solo", False) for ch in aux_returns)
                    any_solo = source_any_solo or return_any_solo
                elif not self.playing and not scrub_active:
                    if gen_out is not None:
                        pk = float(np.max(np.abs(gen_out)))
                        if pk > 0.98: gen_out *= 0.98/pk
                        outdata[:] = gen_out.astype(np.float32)
                        self.master_level = float(pk*2.2)
                        self._analyze_channel(self.master_channel, gen_out.astype(np.float32))
                    else:
                        outdata[:] = 0.0
                        for ch in self.channels: ch.level *= 0.92; ch.comp_gr_db *= 0.75; ch.band_levels *= 0.90
                        self.master_channel.level *= 0.92; self.master_channel.comp_gr_db *= 0.75; self.master_channel.band_levels *= 0.90; self.master_level *= 0.9
                    return
                else:
                    source_any_solo = any(ch.solo for ch in self.channels)
                    return_any_solo = any(getattr(ch, "solo", False) for ch in aux_returns)
                    any_solo = source_any_solo or return_any_solo
                    states = [{"ch": ch, "gain": ch.gain, "pan": ch.pan, "mute": ch.mute, "solo": ch.solo, "pos": ch.position} for ch in self.channels]
            mix = np.zeros((frames, 2), dtype=np.float32)
            aux_inputs = [np.zeros((frames, 2), dtype=np.float32) for _ in aux_returns]
            aux_receives_soloed_source = [False for _ in aux_returns]
            efx_inputs = []
            for s in states:
                ch = s["ch"]
                if scrub_active and not self.playing and bool(getattr(self, "scrub_audition_freeze", False)):
                    block = self._peek_block(ch, frames)
                else:
                    block = self._next_block(ch, frames)
                processed = self._process_channel(ch, block)
                source_for_dry = (not s["mute"]) and (not any_solo or s["solo"])
                source_for_send = (not s["mute"]) and (not source_any_solo or s["solo"] or return_any_solo)
                self._analyze_channel(ch, processed if source_for_dry or source_for_send else np.zeros_like(processed))
                if source_for_dry:
                    mix += self._apply_pan(processed, s["pan"]) * s["gain"]
                send_levels = getattr(ch, "send_levels", [])
                if source_for_send and isinstance(send_levels, list):
                    for slot, level in enumerate(send_levels):
                        send_gain = float(np.clip(level, 0.0, 1.0))
                        if send_gain <= 0.0001:
                            continue
                        if slot < len(aux_inputs):
                            aux_inputs[slot] += processed * send_gain
                            if s["solo"]:
                                aux_receives_soloed_source[slot] = True
                ch.level = float(np.sqrt(np.mean(np.square(processed if source_for_dry or source_for_send else np.zeros_like(processed)))) * 3.4)
            for aux_idx, (aux_ch, aux_block) in enumerate(zip(aux_returns, aux_inputs)):
                has_aux_input = np.max(np.abs(aux_block)) > 0.000001
                has_fx_tail = (
                    (bool(getattr(aux_ch, "rvb_enabled", False)) and isinstance(getattr(aux_ch, "_rvb_state", None), dict))
                    or (bool(getattr(aux_ch, "dly_enabled", False)) and isinstance(getattr(aux_ch, "_dly_state", None), dict))
                )
                if not has_aux_input and not has_fx_tail:
                    aux_ch.level *= 0.92
                    continue
                aux_processed = self._process_channel(aux_ch, aux_block)
                if not has_aux_input and np.max(np.abs(aux_processed)) <= 0.000001:
                    aux_ch.level *= 0.92
                    aux_ch.audio = aux_processed.astype(np.float32)
                    aux_ch.wave_preview = self._build_wave_preview(aux_processed.astype(np.float32), buckets=512)
                    continue
                self._analyze_channel(aux_ch, aux_processed)
                # A soloed source channel must carry its active effects returns
                # with it, matching normal console solo-in-place behavior.
                aux_in_mix = (not getattr(aux_ch, "mute", False)) and (
                    not any_solo
                    or getattr(aux_ch, "solo", False)
                    or (source_any_solo and aux_idx < len(aux_receives_soloed_source) and aux_receives_soloed_source[aux_idx])
                )
                if aux_in_mix:
                    mix += self._apply_pan(aux_processed, getattr(aux_ch, "pan", 0.0)) * float(getattr(aux_ch, "gain", 1.0))
                aux_ch.level = float(np.sqrt(np.mean(np.square(aux_processed))) * 3.4)
                aux_ch.audio = aux_processed.astype(np.float32)
                aux_ch.wave_preview = self._build_wave_preview(aux_processed.astype(np.float32), buckets=512)
            mix *= self.master_gain
            if gen_out is not None: mix = (mix.astype(np.float64) + gen_out.astype(np.float64)).astype(np.float32)
            m_proc = self._process_channel(self.master_channel, mix)
            self.master_channel.level = float(np.sqrt(np.mean(np.square(m_proc))) * 2.8)
            pk = float(np.max(np.abs(m_proc)))
            if pk > 0.98: m_proc *= 0.98/pk
            outdata[:] = m_proc.astype(np.float32)
            self.output_peak = float(np.max(np.abs(outdata)))
            self.master_level = float(np.sqrt(np.mean(np.square(m_proc))) * 2.8)
            scope = getattr(self, "master_scope_audio", None)
            if scope is None or len(scope) != SAMPLE_RATE:
                scope = np.zeros((SAMPLE_RATE, 2), dtype=np.float32)
            n = min(len(m_proc), len(scope))
            if n > 0:
                scope = np.vstack([scope[n:], m_proc[-n:].astype(np.float32)])
            self.master_scope_audio = scope
            self.master_channel.audio = scope
            self.master_channel.wave_preview = self._build_wave_preview(scope, buckets=512)
            self._analyze_channel(self.master_channel, m_proc.astype(np.float32))
            if status: _log.debug(f"Status: {status}")
        except Exception as e:
            _log.error(f"Callback error: {e}"); outdata[:] = 0.0

    def _peek_block(self, ch: ChannelState, frames: int) -> np.ndarray:
        pos = int(np.clip(getattr(ch, "position", 0), 0, max(0, len(ch.audio) - 1)))
        end = min(len(ch.audio), pos + frames)
        head = ch.audio[pos:end] if end > pos else np.zeros((0, 2), dtype=np.float32)
        if len(head) >= frames:
            return head.copy()
        return np.vstack([head, np.zeros((frames - len(head), 2), dtype=np.float32)]).astype(np.float32)

    def _next_block(self, ch: ChannelState, frames: int) -> np.ndarray:
        marker_range = self.active_marker_range_samples() if self.loop and time.monotonic() >= float(getattr(self, "ignore_marker_cycle_until", 0.0)) else None
        if marker_range is not None:
            loop_start, loop_end = marker_range
            loop_end = min(loop_end, len(ch.audio))
            if loop_end > loop_start:
                if ch.position < loop_start or ch.position >= loop_end:
                    ch.position = loop_start
                chunks = []
                tail = frames
                while tail > 0:
                    take = min(loop_end - ch.position, tail)
                    chunks.append(ch.audio[ch.position:ch.position + take])
                    ch.position += take
                    tail -= take
                    if ch.position >= loop_end:
                        ch.position = loop_start
                return np.vstack(chunks).astype(np.float32)
        pos = ch.position; end = pos + frames
        if end <= len(ch.audio):
            ch.position = end; return ch.audio[pos:end].copy()
        head = ch.audio[pos:] if pos < len(ch.audio) else np.zeros((0, 2), dtype=np.float32)
        if not self.loop: ch.position = len(ch.audio); return np.vstack([head, np.zeros((frames-len(head), 2), dtype=np.float32)])
        tail = frames - len(head); wraps = []
        while tail > 0: take = min(len(ch.audio), tail); wraps.append(ch.audio[:take]); tail -= take
        ch.position = sum(len(x) for x in wraps) % len(ch.audio)
        return np.vstack([head, *wraps]).astype(np.float32)

    def _process_channel(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        x = block.astype(np.float32)
        if ch.pre_enabled:
            pre_gain = float(np.clip(getattr(ch, "pre_gain_db", 0.0), -24.0, 24.0))
            squeeze = float(np.clip(getattr(ch, "pre_squeeze", 1.0), 1.0, 8.0))
            x *= float(10.0 ** (pre_gain / 20.0))
            if squeeze > 1.001:
                threshold = 0.32
                mag = np.abs(x)
                over = mag > threshold
                compressed = threshold + (mag - threshold) / squeeze
                x = np.sign(x) * np.where(over, compressed, mag)
        if ch.pre_enabled and ch.phase: x[:, 1] *= -1.0
        if ch.tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.harmonics_enabled and np.any(ch.harmonics > 0.001): x = self._apply_harmonics(x, ch.harmonics, ch.harmonic_makeup, getattr(ch, "harm_param_bypass", {}))
        if ch.harm_tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.gate_enabled or ch.gate_band_enabled: x = self._apply_gate(ch, x)
        if ch.gate_tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.comp_enabled or ch.comp_band_enabled: x = self._apply_compressor(ch, x)
        if ch.comp_tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.eq_enabled:
            bp = getattr(ch, "eq_param_bypass", {})
            if any(bp.get(k, False) for k in ("FRQ", "GAN", "SHP")):
                pass
            elif ch.eq_band_enabled:
                nb = max(1, min(8, int(ch.eq_band_count))); sel = int(np.clip(getattr(ch, "eq_ui_band", 0), 0, nb-1))
                for i in range(nb):
                    b = ch.eq_bands[i]
                    if not b.get("enabled"): continue
                    g = 0.0 if (i==sel and bp.get("GAN")) else float(b.get("gain_db", 0.0))
                    width = float(b.get("width", ch.eq_width)) if not (i==sel and bp.get("SHP")) else 1.4
                    eq_type = str(b.get("type", "SHELF" if width <= 0.1 else "BELL"))
                    if abs(g) > 0.03: x = self._apply_eq(x, float(b.get("freq", ch.eq_freq)), g, width, eq_type)
            elif not bp.get("FRQ"):
                g = float(ch.eq_gain_db) if not bp.get("GAN") else 0.0
                width = float(ch.eq_width) if not bp.get("SHP") else 1.4
                eq_type = "SHELF" if width <= 0.1 else "BELL"
                if abs(g) > 0.03: x = self._apply_eq(x, float(ch.eq_freq), g, width, eq_type)
        if ch.eq_tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.trn_enabled: x = self._apply_trn(x, ch)
        if ch.xct_enabled: x = self._apply_xct(x, ch)
        if ch.tbe_enabled: x = self._apply_tbe(x, ch)
        if getattr(ch, "rvb_enabled", False): x = self._apply_reverb(x, ch)
        if getattr(ch, "dly_enabled", False): x = self._apply_delay(x, ch)
        if getattr(ch, "mod_enabled", False): x = self._apply_modulation(x, ch)
        if ch.lpf_enabled:
            x = self._apply_pre_filter(ch, x, ch.lpf_hz, "lowpass")
        if ch.hpf_enabled:
            x = self._apply_pre_filter(ch, x, ch.hpf_hz, "highpass")
        return np.clip(x, -1.0, 1.0).astype(np.float32)

    def _apply_reverb(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        mix = float(np.clip(getattr(ch, "rvb_mix", 0.22), 0.0, 1.0))
        if mix <= 0.001:
            return block
        time_s = float(np.clip(getattr(ch, "rvb_time_s", 2.4), 0.1, 12.0))
        ref_ms = float(np.clip(getattr(ch, "rvb_ref_ms", 55.0), 5.0, 240.0))
        damp = float(np.clip(getattr(ch, "rvb_damp", 0.35), 0.0, 1.0))
        width = float(np.clip(getattr(ch, "rvb_width", 0.75), 0.0, 1.0))
        predelay_ms = float(np.clip(getattr(ch, "rvb_predelay_ms", 18.0), 0.0, 180.0))
        reverse = bool(getattr(ch, "rvb_reverse", False))
        tail_ms = min(1200.0, 130.0 + time_s * 95.0)
        delays_ms = [
            predelay_ms + ref_ms * 0.67,
            predelay_ms + ref_ms * 1.13,
            predelay_ms + ref_ms * 1.79,
            predelay_ms + ref_ms * 2.71,
            predelay_ms + tail_ms * 0.48,
            predelay_ms + tail_ms * 0.82,
        ]
        delay_samples = [max(8, int(SAMPLE_RATE * d / 1000.0)) for d in delays_ms]
        max_delay = max(delay_samples) + 2
        frames = block.shape[0]
        state = getattr(ch, "_rvb_state", None)
        if not isinstance(state, dict) or state.get("max_delay") != max_delay:
            state = {
                "max_delay": max_delay,
                "hist": np.zeros((max_delay, 2), dtype=np.float32),
                "lp": np.zeros((2,), dtype=np.float32),
            }
            ch._rvb_state = state
        hist = state["hist"]
        combined = np.vstack([hist, block]).astype(np.float32)
        wet = np.zeros_like(block, dtype=np.float32)
        taps = len(delay_samples)
        damp_keep = 1.0 - damp * 0.72
        for t, delay in enumerate(delay_samples):
            delayed = combined[-delay - frames:-delay]
            if delayed.shape[0] != frames:
                continue
            spread = (t / max(1, taps - 1) - 0.5) * width
            tap = delayed.copy()
            tap[:, 0] = delayed[:, 0] * (1.0 - spread) + delayed[:, 1] * spread * 0.35
            tap[:, 1] = delayed[:, 1] * (1.0 + spread) - delayed[:, 0] * spread * 0.35
            if reverse:
                tap = tap[::-1]
            tap_gain = damp_keep * max(0.22, 1.0 - t * 0.105)
            wet += tap * tap_gain
        wet /= max(1, taps)
        if reverse and frames > 1:
            ramp_len = max(64, int(SAMPLE_RATE * np.clip((predelay_ms + ref_ms * 2.0) / 1000.0, 0.08, 0.9)))
            rev_phase = int(state.get("rev_phase", 0)) % ramp_len
            ramp = ((np.arange(frames, dtype=np.float32) + rev_phase) % ramp_len) / float(ramp_len)
            state["rev_phase"] = int((rev_phase + frames) % ramp_len)
            swell = (0.18 + 1.22 * np.power(ramp, 1.7))[:, None]
            wet = wet * swell
        feedback = float(np.clip(0.24 + math.log10(time_s + 1.0) * 0.36, 0.18, 0.78))
        tail_feed = np.clip(block + wet * feedback, -1.0, 1.0)
        state["hist"] = np.vstack([hist, tail_feed])[-max_delay:].astype(np.float32)
        path = str(getattr(ch, "path", ""))
        name = str(getattr(ch, "name", ""))
        is_aux_return = path.startswith("aux_return") or name.lower().startswith("aux ")
        if is_aux_return:
            # Sends already keep the dry source in the main mix; the return
            # should carry the effect, otherwise the wet signal disappears
            # behind another copy of dry audio.
            return np.clip(wet * (0.85 + mix * 2.65), -1.0, 1.0).astype(np.float32)
        return (block * (1.0 - mix) + wet * mix * 2.1).astype(np.float32)

    def _apply_delay(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        mix = float(np.clip(getattr(ch, "dly_mix", 0.75), 0.0, 1.0))
        if mix <= 0.001:
            return block
        delay_ms = float(np.clip(getattr(ch, "dly_time_ms", 360.0), 40.0, 1200.0))
        feedback = float(np.clip(getattr(ch, "dly_feedback", 0.32), 0.0, 0.82))
        width = float(np.clip(getattr(ch, "dly_width", 0.65), 0.0, 1.0))
        damp = float(np.clip(getattr(ch, "dly_damp", 0.35), 0.0, 1.0))
        pingpong = bool(getattr(ch, "dly_pingpong", False))
        delay_samples = max(16, int(SAMPLE_RATE * delay_ms / 1000.0))
        frames = block.shape[0]
        state = getattr(ch, "_dly_state", None)
        if not isinstance(state, dict) or state.get("delay_samples") != delay_samples:
            state = {
                "delay_samples": delay_samples,
                "hist": np.zeros((delay_samples + frames + 2, 2), dtype=np.float32),
                "lp": np.zeros((2,), dtype=np.float32),
            }
            ch._dly_state = state
        hist = state["hist"]
        combined = np.vstack([hist, block]).astype(np.float32)
        delayed = combined[-delay_samples - frames:-delay_samples]
        if delayed.shape[0] != frames:
            delayed = np.zeros_like(block)
        wet = delayed.copy()
        if pingpong:
            wet = np.column_stack((delayed[:, 1], delayed[:, 0])).astype(np.float32)
        side = (wet[:, 0] - wet[:, 1]) * (0.20 + width * 0.80)
        mid = (wet[:, 0] + wet[:, 1]) * 0.5
        wet[:, 0] = mid + side * 0.5
        wet[:, 1] = mid - side * 0.5
        damp_keep = 1.0 - damp * 0.72
        lp = np.asarray(state.get("lp", np.zeros((2,), dtype=np.float32)), dtype=np.float32)
        smoothed = np.empty_like(wet)
        for i in range(frames):
            lp = lp * damp + wet[i] * damp_keep
            smoothed[i] = lp
        state["lp"] = lp.astype(np.float32)
        wet = smoothed
        state["hist"] = np.vstack([hist, np.clip(block + wet * feedback, -1.0, 1.0)])[-(delay_samples + frames + 2):].astype(np.float32)
        path = str(getattr(ch, "path", ""))
        is_aux_return = path.startswith("aux_return") or str(getattr(ch, "name", "")).lower().startswith("aux ")
        if is_aux_return:
            return np.clip(wet * (0.75 + mix * 1.55), -1.0, 1.0).astype(np.float32)
        return (block * (1.0 - mix) + wet * mix).astype(np.float32)

    def _apply_modulation(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        mix = float(np.clip(getattr(ch, "mod_mix", 0.65), 0.0, 1.0))
        if mix <= 0.001:
            return block
        rate = float(np.clip(getattr(ch, "mod_rate_hz", 0.42), 0.05, 8.0))
        depth = float(np.clip(getattr(ch, "mod_depth", 0.55), 0.0, 1.0))
        feedback = float(np.clip(getattr(ch, "mod_feedback", 0.0), 0.0, 0.85))
        width = float(np.clip(getattr(ch, "mod_width", 0.75), 0.0, 1.0))
        mod_type = str(getattr(ch, "mod_type", "CHR") or "CHR").upper()
        frames = block.shape[0]
        phase = float(getattr(ch, "_mod_phase", 0.0))
        t = phase + np.arange(frames, dtype=np.float32) * (2.0 * math.pi * rate / SAMPLE_RATE)
        ch._mod_phase = float((phase + frames * (2.0 * math.pi * rate / SAMPLE_RATE)) % (2.0 * math.pi))
        left_lfo = np.sin(t)
        right_lfo = np.sin(t + math.pi * 0.64)

        if mod_type in ("CHR", "FLG", "VIB"):
            base_ms = 18.0 if mod_type == "CHR" else 3.0 if mod_type == "FLG" else 6.0
            sweep_ms = (16.0 if mod_type == "CHR" else 2.6 if mod_type == "FLG" else 5.0) * depth
            max_delay = max(32, int(SAMPLE_RATE * (base_ms + sweep_ms + 8.0) / 1000.0))
            state = getattr(ch, "_mod_state", None)
            if not isinstance(state, dict) or state.get("type") != mod_type or state.get("max_delay") != max_delay:
                state = {"type": mod_type, "max_delay": max_delay, "hist": np.zeros((max_delay + frames + 2, 2), dtype=np.float32)}
                ch._mod_state = state
            hist = state["hist"]
            combined = np.vstack([hist, block]).astype(np.float32)
            wet = np.zeros_like(block, dtype=np.float32)
            for chan, lfo in enumerate((left_lfo, right_lfo)):
                delay_samples = (base_ms + sweep_ms * (0.5 + 0.5 * lfo)) * SAMPLE_RATE / 1000.0
                idx_float = np.arange(frames, dtype=np.float32) + hist.shape[0] - delay_samples
                idx0 = np.clip(np.floor(idx_float).astype(np.intp), 0, combined.shape[0] - 2)
                frac = (idx_float - idx0).astype(np.float32)
                wet[:, chan] = combined[idx0, chan] * (1.0 - frac) + combined[idx0 + 1, chan] * frac
            if mod_type == "FLG":
                wet = np.clip(wet + block * (0.35 + feedback * 0.55), -1.0, 1.0)
            if mod_type != "VIB":
                side = (wet[:, 0] - wet[:, 1]) * width
                mid = (wet[:, 0] + wet[:, 1]) * 0.5
                wet[:, 0] = mid + side * 0.5
                wet[:, 1] = mid - side * 0.5
            state["hist"] = np.vstack([hist, np.clip(block + wet * feedback, -1.0, 1.0)])[-(max_delay + frames + 2):].astype(np.float32)
        elif mod_type == "PHS":
            mono_lfo = (left_lfo + 1.0) * 0.5
            notched = block.copy()
            notched[:, 0] *= 1.0 - depth * (0.25 + 0.35 * mono_lfo)
            notched[:, 1] *= 1.0 - depth * (0.25 + 0.35 * (1.0 - mono_lfo))
            cross = np.column_stack((notched[:, 1], notched[:, 0])).astype(np.float32) * (0.10 + feedback * 0.30)
            wet = np.clip(notched + cross, -1.0, 1.0)
        elif mod_type == "ROT":
            pan = np.sin(t) * depth
            wet = block.copy()
            wet[:, 0] *= np.sqrt(np.clip(0.5 - pan * 0.5 * width, 0.0, 1.0)) * 1.35
            wet[:, 1] *= np.sqrt(np.clip(0.5 + pan * 0.5 * width, 0.0, 1.0)) * 1.35
        else:
            wet = block.copy()
            wet[:, 0] *= (0.72 + 0.38 * depth * left_lfo)
            wet[:, 1] *= (0.72 + 0.38 * depth * right_lfo)
            wet = np.clip(wet + np.column_stack((wet[:, 1], wet[:, 0])).astype(np.float32) * (0.18 + depth * 0.18), -1.0, 1.0)

        path = str(getattr(ch, "path", ""))
        is_aux_return = path.startswith("aux_return") or str(getattr(ch, "name", "")).lower().startswith("aux ")
        if is_aux_return:
            return np.clip(wet * (0.55 + mix * 1.15), -1.0, 1.0).astype(np.float32)
        return (block * (1.0 - mix) + wet * mix).astype(np.float32)

    @staticmethod
    def _stage_param_bypassed(bp: dict) -> bool:
        return any(bool(v) and k not in ("FRQ", "TBE") for k, v in (bp or {}).items())

    def _analyze_channel(self, ch: ChannelState, block: np.ndarray) -> None:
        if not hasattr(ch, "_analyze_counter"): ch._analyze_counter = 0
        ch._analyze_counter += 1
        if ch._analyze_counter % 4 != 0: ch.band_levels *= 0.962; return
        mono = np.mean(block, axis=1).astype(np.float32)
        if len(mono) < 32: ch.band_levels *= 0.92; return
        if not hasattr(self, "_hanning_cache"): self._hanning_cache = {}
        if len(mono) not in self._hanning_cache: self._hanning_cache[len(mono)] = np.hanning(len(mono)).astype(np.float32)
        spec = np.abs(np.fft.rfft(mono * self._hanning_cache[len(mono)]))
        if not hasattr(self, "_pol_edges"): self._pol_edges = np.logspace(LOG_LOW, LOG_HIGH, POL_BANDS + 1)
        freqs = np.fft.rfftfreq(len(mono), d=1.0 / SAMPLE_RATE)
        bins = np.clip(np.searchsorted(self._pol_edges, freqs, side="right") - 1, 0, POL_BANDS-1).astype(np.intp)
        vals = np.sqrt(np.bincount(bins, weights=spec.astype(np.float64)**2, minlength=POL_BANDS) / np.clip(np.bincount(bins, minlength=POL_BANDS), 1.0, 1e12)).astype(np.float32)
        ch.band_noise_floor = ch.band_noise_floor*0.995 + np.minimum(ch.band_noise_floor, vals+1e-8)*0.005
        ch.band_levels = ch.band_levels*0.58 + np.power(np.clip((vals - ch.band_noise_floor*1.25)/8.0, 0.0, 1.0), 0.55).astype(np.float32)*0.42

    def _apply_harmonics(self, block: np.ndarray, weights: np.ndarray, makeup: float, bp: dict) -> np.ndarray:
        if self._stage_param_bypassed(bp):
            return block
        out = np.zeros_like(block)
        for i in range(block.shape[1]):
            x = np.clip(block[:, i], -0.999, 0.999); rms = np.sqrt(np.mean(x**2)) + 1e-7; theta = np.arccos(x); enh = x.copy()
            for j, w in enumerate(weights):
                if w > 0.001: enh += np.cos((j+2)*theta) * w * (0.54 - j*0.05)
            mix = x*0.94 + (np.tanh(enh*1.4) - np.tanh(x*1.4))*0.68
            out[:, i] = np.tanh(mix * (min(2.1, max(0.9, rms/(np.sqrt(np.mean(mix**2))+1e-7)))) * makeup)
        return out.astype(np.float32)

    def _apply_gate(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        self._hydrate_gate_dyn_to_scalars(ch)
        bp = getattr(ch, "gate_param_bypass", {})
        if self._stage_param_bypassed(bp):
            ch.gate_gr_db = 0.0
            return block
        if ch.gate_band_enabled:
            b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
            if not b.get("enabled"):
                b.update(
                    enabled=True,
                    freq=float(ch.gate_center_hz),
                    width_oct=float(ch.gate_width_oct),
                    threshold_db=float(ch.gate_threshold_db),
                    ratio=float(ch.gate_ratio),
                    attack_ms=float(ch.gate_attack_ms),
                    release_ms=float(ch.gate_release_ms),
                    makeup=float(ch.gate_makeup),
                )
            if b.get("makeup", 1.0) <= 0.001: return block
            atk, rls, thr, rat, mk = b["attack_ms"], b["release_ms"], b["threshold_db"], b["ratio"], b["makeup"]
        elif ch.gate_enabled:
            if ch.gate_makeup <= 0.001: return block
            atk, rls, thr, rat, mk = ch.gate_attack_ms, ch.gate_release_ms, ch.gate_threshold_db, ch.gate_ratio, ch.gate_makeup
        else: return block
        mono = self._mono_for_dynamics_detector(ch, block, kind="gate")
        a_env = math.exp(-1.0 / max(1.0, (atk/1000.0)*SAMPLE_RATE))
        r_env = math.exp(-1.0 / max(1.0, (rls/1000.0)*SAMPLE_RATE))
        ag, rg = math.exp(-1.0 / max(1.0, (atk*0.25/1000.0)*SAMPLE_RATE)), math.exp(-1.0 / max(1.0, (rls*0.3/1000.0)*SAMPLE_RATE))
        thr_db = thr
        # Gate RAT is depth, not a compressor-style bleed ratio. 8:1 is about
        # -32 dB closed; 20:1 is about -80 dB, effectively shut.
        floor = 10.0 ** (-float(np.clip(rat, 1.0, 20.0)) * 4.0 / 20.0)
        mkup = max(0.001, mk)
        env, sm = float(ch.gate_env), float(ch.gate_gain_smooth); gs = np.empty(len(mono), dtype=np.float32)
        for i, s in enumerate(mono):
            env = (a_env if abs(s)>env else r_env)*env + (1.0-(a_env if abs(s)>env else r_env))*abs(s)
            tgt = mkup if (20*math.log10(max(env, 1e-7)) >= thr_db) else mkup*floor
            sm = (ag if tgt>sm else rg)*sm + (1.0-(ag if tgt>sm else rg))*tgt
            gs[i] = sm/mkup
        ch.gate_env, ch.gate_gain_smooth, ch.gate_gr_db = env, sm, -20*math.log10(max(gs[-1], 1e-7))
        return block * gs[:, None]

    def _apply_compressor(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        self._hydrate_comp_dyn_to_scalars(ch)
        bp = getattr(ch, "comp_param_bypass", {})
        if self._stage_param_bypassed(bp):
            ch.comp_gr_db = 0.0
            return block
        if ch.comp_band_enabled:
            b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
            if not b.get("enabled") or b.get("makeup", 1.0) <= 0.001: return block
            atk, rls, rat, thr, mk = b["attack_ms"], b["release_ms"], b["ratio"], b["threshold_db"], b["makeup"]
        elif ch.comp_enabled:
            if ch.comp_makeup <= 0.001: return block
            atk, rls, rat, thr, mk = ch.comp_attack_ms, ch.comp_release_ms, ch.comp_ratio, ch.comp_threshold_db, ch.comp_makeup
        else: return block
        mono = self._mono_for_dynamics_detector(ch, block, kind="comp"); env = float(ch.comp_env)
        a_c = math.exp(-1.0 / max(1.0, (atk/1000.0)*SAMPLE_RATE))
        r_c = math.exp(-1.0 / max(1.0, (rls/1000.0)*SAMPLE_RATE))
        rat, mkup = max(1.0, rat), mk
        limiter = rat >= 19.95
        gs = np.empty(len(mono), dtype=np.float32); last_gr = 0.0
        for i, s in enumerate(mono):
            env = (a_c if abs(s)>env else r_c)*env + (1.0-(a_c if abs(s)>env else r_c))*abs(s)
            odb = max(0.0, 20*math.log10(max(env, 1e-7)) - thr)
            gdb = odb if limiter else odb - (odb/rat if odb>0 else 0.0)
            gs[i] = 10**(-gdb/20.0) * mkup; last_gr = gdb
        ch.comp_env, ch.comp_gr_db = env, last_gr
        out = block * gs[:, None]
        if limiter:
            ceiling = float((10.0 ** (thr / 20.0)) * mkup)
            out = np.clip(out, -ceiling, ceiling)
        return out.astype(np.float32)

    def _apply_eq(self, block: np.ndarray, freq: float, gain: float, width: float, eq_type: str = "BELL") -> np.ndarray:
        fs = np.fft.rfftfreq(len(block), d=1.0/SAMPLE_RATE); v = fs>0; lfs = np.zeros_like(fs); lfs[v] = np.log2(np.maximum(fs[v], 1.0))
        center = math.log2(float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ)))
        if str(eq_type).upper() == "SHELF" or width <= 0.1:
            slope = 8.0
            if freq < 1000.0:
                curve = 1.0 / (1.0 + np.exp((lfs - center) * slope))
            else:
                curve = 1.0 / (1.0 + np.exp((center - lfs) * slope))
        else:
            curve = np.exp(-0.5 * ((lfs - center) / max(0.08, width/2.355))**2)
        scale = np.power(10.0, (gain * curve) / 20.0).astype(np.float32)
        return np.column_stack([np.fft.irfft(np.fft.rfft(block[:, i]) * scale, n=len(block)) for i in range(block.shape[1])]).astype(np.float32)

    def _apply_trn(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "trn_param_bypass", {})
        if bp.get("TRN"): return block
        if any(bp.get(k, False) for k in ("FRQ", "ATK", "SUT", "DRV")):
            return block
        bands = []
        if ch.trn_band_enabled:
            count = max(1, min(8, int(getattr(ch, "trn_band_count", 1))))
            for i in range(count):
                b = ch.trn_bands[i]
                if b.get("enabled", False):
                    bands.append((float(b.get("freq", ch.trn_freq)), float(b.get("width", ch.trn_width)), float(b.get("attack", ch.trn_attack)), float(b.get("sustain", ch.trn_sustain)), float(b.get("drive", ch.trn_drive))))
        else:
            bands.append((float(ch.trn_freq), 1.0, float(ch.trn_attack), float(ch.trn_sustain), float(ch.trn_drive)))
        out = block.copy()
        full_rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2))) + 1e-9
        changed = False
        for freq, width, ta, ts, dr in bands:
            if all(abs(v)<0.01 for v in (ta, ts, dr)):
                continue
            band = self._apply_bandpass_filter(out, freq, width)
            band_rms = float(np.sqrt(np.mean(band.astype(np.float64) ** 2)))
            if band_rms < max(1e-5, full_rms * 0.015):
                continue
            out = (out - band) + self._apply_transient_processor(band, ta, ts, dr)
            changed = True
        return out if changed else block

    def _apply_xct(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "xct_param_bypass", {})
        if bp.get("XCT") or any(bp.get(k, False) for k in ("FRQ", "ATK", "SUT", "DRV")):
            return block
        bands = []
        if ch.xct_band_enabled:
            count = max(1, min(8, int(getattr(ch, "xct_band_count", 1))))
            for i in range(count):
                b = ch.xct_bands[i]
                if b.get("enabled", False):
                    bands.append((float(b.get("freq", ch.xct_freq)), float(b.get("width", ch.xct_width)), float(b.get("attack", ch.xct_attack)), float(b.get("sustain", ch.xct_sustain)), float(b.get("drive", ch.xct_drive))))
        else:
            bands.append((float(ch.xct_freq), 1.0, float(ch.xct_attack), float(ch.xct_sustain), float(ch.xct_drive)))
        out = block.copy()
        full_rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2))) + 1e-9
        changed = False
        for freq, width, atk, sus, drv in bands:
            if abs(drv) < 0.01:
                continue
            band = self._apply_bandpass_filter(out, freq, width)
            band_rms = float(np.sqrt(np.mean(band.astype(np.float64) ** 2)))
            if band_rms < max(1e-5, full_rms * 0.01):
                continue
            excited = self._apply_exciter_processor(band, atk, sus, drv)
            out = np.clip(out + excited, -1.0, 1.0).astype(np.float32)
            changed = True
        return out if changed else block

    def _apply_tbe(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "tbe_param_bypass", {})
        if bp.get("DRV"):
            return block
        bands = []
        if ch.tbe_band_enabled:
            count = max(1, min(8, int(getattr(ch, "tbe_band_count", 1))))
            for i in range(count):
                b = ch.tbe_bands[i]
                if b.get("enabled", False):
                    bands.append((float(b.get("freq", ch.tbe_freq)), float(b.get("width", ch.tbe_width)), float(b.get("drive", ch.tbe_drive))))
        else:
            bands.append((float(ch.tbe_freq), 1.4, float(ch.tbe_drive)))
        out = block.copy()
        changed = False
        for freq, width, drive in bands:
            if abs(drive) < 0.01:
                continue
            drv = 1.0 + float(np.clip(drive, 0.0, 1.0)) * 8.0
            active_width = width if ch.tbe_band_enabled else 2.4
            band = self._apply_bandpass_filter(out, freq, active_width)
            saturated = np.tanh(band * drv).astype(np.float32)
            out = (out - band) + saturated
            changed = True
        return out if changed else block

    def _apply_transient_processor(self, b: np.ndarray, a: float, s: float, d: float) -> np.ndarray:
        x = self._apply_transient(b, a, s)
        return np.tanh(x * (1.0 + d*4.0)).astype(np.float32) if abs(d)>0.01 else x

    def _apply_exciter_processor(self, band: np.ndarray, attack_amt: float, sustain_amt: float, drive: float) -> np.ndarray:
        shaped = self._apply_transient(band, attack_amt * 1.25, sustain_amt * 0.90)
        drive = float(np.clip(drive, 0.0, 1.0))
        gain = 2.0 + drive * 22.0
        saturated = np.tanh(shaped * gain)
        odd = saturated - shaped * 0.35
        even = (np.abs(shaped) - np.mean(np.abs(shaped), axis=0, keepdims=True)) * np.sign(shaped)
        edge = shaped - np.vstack([np.zeros((1, shaped.shape[1]), dtype=np.float32), shaped[:-1]]) * 0.55
        harmonics = odd * 1.35 + even * (0.85 + drive * 1.80) + edge * (0.35 + max(0.0, attack_amt) * 1.35)
        air = self._apply_simple_filter(harmonics.astype(np.float32), 1600.0, "highpass")
        presence = band * (0.45 + drive * 1.85)
        return (presence + air * (1.35 + drive * 3.25)).astype(np.float32)

    def _apply_transient(self, block: np.ndarray, attack_amt: float, sustain_amt: float) -> np.ndarray:
        if abs(attack_amt)<=0.01 and abs(sustain_amt)<=0.01: return block
        det = np.abs(np.mean(block, axis=1)); f_env, s_env = np.zeros_like(det), np.zeros_like(det); f, s = 0.0, 0.0
        for i in range(len(det)): f += (det[i]-f)*0.52; s += (det[i]-s)*0.012; f_env[i], s_env[i] = f, s
        trn, sus = np.maximum(0.0, f_env-s_env), s_env.copy()
        if np.max(trn)>1e-6: trn /= np.max(trn)
        if np.max(sus)>1e-6: sus /= np.max(sus)
        out = block.copy()
        for j in range(block.shape[1]):
            x = block[:, j]; edge = (x - np.concatenate(([0.0], x[:-1]))*0.72)*trn*(attack_amt*12.0)
            body = np.zeros(len(x), dtype=np.float32); acc = 0.0
            for k in range(len(x)): acc = acc*0.994 + x[k]*0.055; body[k] = acc
            out[:, j] = x + edge + body*sus*(sustain_amt*6.0)
        pk = np.max(np.abs(out)); return (out * (0.98/pk if pk>0.98 else 1.0)).astype(np.float32)

    def _apply_pan(self, block: np.ndarray, pan: float) -> np.ndarray:
        ang = (np.clip(pan, -1.0, 1.0)+1.0)*(math.pi/4.0); m = np.mean(block, axis=1)
        return np.column_stack((m*math.cos(ang), m*math.sin(ang))).astype(np.float32)

    def _apply_simple_filter(self, block: np.ndarray, hz: float, mode: str) -> np.ndarray:
        fs = np.fft.rfftfreq(len(block), d=1.0/SAMPLE_RATE); c = float(np.clip(hz, POL_LOW_HZ, SAMPLE_RATE*0.45))
        s = (1.0/np.sqrt(1+(fs/max(c,1.0))**4)) if mode=="lowpass" else np.where(fs<=0, 0, (fs/max(c,1.0))**2/np.sqrt(1+(fs/max(c,1.0))**4))
        return np.column_stack([np.fft.irfft(np.fft.rfft(block[:, i])*s, n=len(block)) for i in range(block.shape[1])]).astype(np.float32)

    def _apply_bandpass_filter(self, block: np.ndarray, hz: float, width_oct: float) -> np.ndarray:
        fs = np.fft.rfftfreq(len(block), d=1.0 / SAMPLE_RATE)
        center = math.log2(float(np.clip(hz, POL_LOW_HZ, POL_HIGH_HZ)))
        lfs = np.zeros_like(fs)
        valid = fs > 0.0
        lfs[valid] = np.log2(np.maximum(fs[valid], 1.0))
        sigma = max(0.035, float(np.clip(width_oct, 0.1, 6.0)) / 3.2)
        mask = np.exp(-0.5 * ((lfs - center) / sigma) ** 2).astype(np.float32)
        mask[~valid] = 0.0
        return np.column_stack([np.fft.irfft(np.fft.rfft(block[:, i]) * mask, n=len(block)) for i in range(block.shape[1])]).astype(np.float32)

    def _butter_sos(self, hz: float, mode: str, order: int = 4) -> np.ndarray:
        if not hasattr(self, "_butter_sos_cache"): self._butter_sos_cache = {}
        c = float(np.clip(hz, POL_LOW_HZ, SAMPLE_RATE*0.4995)); key = (mode, int(round(c)), order)
        if key not in self._butter_sos_cache: self._butter_sos_cache[key] = butter(order, float(np.clip(c/(SAMPLE_RATE*0.5), 1e-4, 0.9999)), btype=mode, output="sos").astype(np.float64)
        return self._butter_sos_cache[key]

    def _apply_pre_filter(self, ch: ChannelState, x: np.ndarray, hz: float, mode: str) -> np.ndarray:
        s_at, c_at = ("lpf_state", "lpf_state_cutoff") if mode=="lowpass" else ("hpf_state", "hpf_state_cutoff")
        sos = self._butter_sos(hz, mode); st = getattr(ch, s_at, None); l_c = float(getattr(ch, c_at, 0.0))
        if st is None or not isinstance(st, np.ndarray) or st.shape != (sos.shape[0], 2, x.shape[1]) or abs(l_c-hz)>0.5:
            zt = sosfilt_zi(sos); dc = np.mean(x, axis=0).astype(np.float64); st = np.empty((sos.shape[0], 2, x.shape[1]), dtype=np.float64)
            for i in range(x.shape[1]): st[:, :, i] = zt * float(dc[i])
            setattr(ch, c_at, float(hz))
        out = np.empty_like(x)
        for i in range(x.shape[1]): y, st[:, :, i] = sosfilt(sos, x[:, i], zi=st[:, :, i]); out[:, i] = y.astype(np.float32)
        setattr(ch, s_at, st); return out

    def _bandpass_mono(self, block: np.ndarray, cen: float, wid: float, mono: np.ndarray) -> np.ndarray:
        lo, hi = max(POL_LOW_HZ, cen/(2.0**(wid/2.0))), min(POL_HIGH_HZ, cen*(2.0**(wid/2.0)))
        if lo >= hi*0.99: return mono
        return np.mean(self._apply_simple_filter(self._apply_simple_filter(block, lo, "highpass"), hi, "lowpass"), axis=1).astype(np.float32)

    def _hydrate_gate_dyn_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "gate_band_enabled", False): return
        b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
        if not b.get("enabled"):
            b.update(
                enabled=True,
                freq=float(ch.gate_center_hz),
                width_oct=float(ch.gate_width_oct),
                threshold_db=float(ch.gate_threshold_db),
                ratio=float(ch.gate_ratio),
                attack_ms=float(ch.gate_attack_ms),
                release_ms=float(ch.gate_release_ms),
                makeup=float(ch.gate_makeup),
            )
        ch.gate_center_hz, ch.gate_width_oct, ch.gate_threshold_db, ch.gate_ratio, ch.gate_attack_ms, ch.gate_release_ms, ch.gate_makeup = b["freq"], b["width_oct"], b["threshold_db"], b["ratio"], b["attack_ms"], b["release_ms"], b["makeup"]

    def _hydrate_comp_dyn_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "comp_band_enabled", False): return
        b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
        ch.comp_center_hz, ch.comp_width_oct, ch.comp_threshold_db, ch.comp_ratio, ch.comp_attack_ms, ch.comp_release_ms, ch.comp_makeup = b["freq"], b["width_oct"], b["threshold_db"], b["ratio"], b["attack_ms"], b["release_ms"], b["makeup"]

    def _flush_gate_scalars_to_dyn_band(self, ch: ChannelState) -> None:
        if getattr(ch, "gate_band_enabled", False):
            b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
            b.update(
                enabled=True,
                freq=float(ch.gate_center_hz),
                width_oct=float(ch.gate_width_oct),
                threshold_db=float(ch.gate_threshold_db),
                ratio=float(ch.gate_ratio),
                attack_ms=float(ch.gate_attack_ms),
                release_ms=float(ch.gate_release_ms),
                makeup=float(ch.gate_makeup),
            )

    def _flush_comp_scalars_to_dyn_band(self, ch: ChannelState) -> None:
        if getattr(ch, "comp_band_enabled", False):
            b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
            b["freq"], b["width_oct"] = float(ch.comp_center_hz), float(ch.comp_width_oct)

    def comp_dynamics_snapshot(self, ch: ChannelState) -> tuple:
        if getattr(ch, "comp_band_enabled", False):
            b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
            return (float(b["threshold_db"]), float(b["ratio"]), float(b["attack_ms"]), float(b["release_ms"]), float(b["makeup"]))
        return (float(ch.comp_threshold_db), float(ch.comp_ratio), float(ch.comp_attack_ms), float(ch.comp_release_ms), float(ch.comp_makeup))

    def write_comp_dynamics(self, ch: ChannelState, thr: float, rat: float, atk: float, rls: float, mk: float) -> None:
        thr = float(np.clip(thr, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER))
        if getattr(ch, "comp_band_enabled", False):
            b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
            b.update(threshold_db=thr, ratio=float(rat), attack_ms=float(atk), release_ms=float(rls), makeup=float(mk), enabled=True)
        ch.comp_threshold_db, ch.comp_ratio, ch.comp_attack_ms, ch.comp_release_ms, ch.comp_makeup = thr, rat, atk, rls, mk

    def write_gate_dynamics(self, ch: ChannelState, thr: float, rat: float, atk: float, rls: float, mk: float) -> None:
        thr = float(np.clip(thr, POL_LEVEL_DB_AXIS_OUTER, POL_LEVEL_DB_AXIS_INNER))
        if getattr(ch, "gate_band_enabled", False):
            b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
            b.update(threshold_db=thr, ratio=float(rat), attack_ms=float(atk), release_ms=float(rls), makeup=float(mk), enabled=True)
        ch.gate_threshold_db, ch.gate_ratio, ch.gate_attack_ms, ch.gate_release_ms, ch.gate_makeup = thr, rat, atk, rls, mk

    def _mono_for_dynamics_detector(self, ch: ChannelState, block: np.ndarray, *, kind: str) -> np.ndarray:
        m_full = np.mean(block, axis=1).astype(np.float32)
        if kind == "gate":
            if not getattr(ch, "gate_band_enabled", False): return m_full
            b = ch.gate_dyn_bands[max(0, min(int(getattr(ch, "gate_dyn_band_count", 1))-1, int(getattr(ch, "gate_dyn_ui_band", 0))))]
            return self._bandpass_mono(block, float(b["freq"]), float(b["width_oct"]), m_full)
        if kind == "comp":
            if not getattr(ch, "comp_band_enabled", False): return m_full
            b = ch.comp_dyn_bands[max(0, min(int(getattr(ch, "comp_dyn_band_count", 1))-1, int(getattr(ch, "comp_dyn_ui_band", 0))))]
            return self._bandpass_mono(block, float(b["freq"]), float(b["width_oct"]), m_full)
        return m_full

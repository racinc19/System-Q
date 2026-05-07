import math
from pathlib import Path
import threading
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
        self.loop = True
        self.master_gain = 0.82
        self.master_level = 0.0
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
            ch.harm_tube = ch.gate_tube = ch.comp_tube = ch.eq_tube = ch.lpf_enabled = ch.hpf_enabled = False
            ch.lpf_hz, ch.hpf_hz = float(POL_HIGH_HZ), float(POL_LOW_HZ)
            ch.harmonics_enabled = ch.comp_enabled = ch.limit_enabled = ch.gate_enabled = False
            ch.harmonics[:] = 0.0
            ch.harmonic_makeup = 1.0
            ch.comp_band_enabled = ch.limit_band_enabled = ch.gate_band_enabled = False
            ch.gate_dyn_band_count = ch.gate_dyn_ui_band = ch.comp_dyn_band_count = ch.comp_dyn_ui_band = 1, 0
            for db in ch.gate_dyn_bands: db.update(enabled=False, freq=3000.0, width_oct=4.0, threshold_db=-45.0, ratio=8.0, attack_ms=3.0, release_ms=140.0, makeup=1.0)
            for db in ch.comp_dyn_bands: db.update(enabled=False, freq=3000.0, width_oct=4.0, threshold_db=-18.0, ratio=4.0, attack_ms=8.0, release_ms=120.0, makeup=1.0)
            ch.eq_enabled = ch.eq_band_enabled = False
            ch.eq_band_count, ch.eq_ui_band = 1, 0
            ch.eq_freq, ch.eq_gain_db, ch.eq_width, ch.eq_type = 2200.0, 0.0, 1.4, "BELL"
            for b in ch.eq_bands: b.update(enabled=False, freq=2200.0, gain_db=0.0, width=1.4, type="BELL", band_enabled=False)
            ch.eq_param_bypass.clear(); ch.gate_param_bypass.clear(); ch.comp_param_bypass.clear(); ch.harm_param_bypass.clear()
            ch.trn_enabled = ch.xct_enabled = ch.tbe_enabled = ch.trn_band_enabled = ch.xct_band_enabled = ch.tbe_band_enabled = False
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
            self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=2, dtype="float32", blocksize=BLOCK_SIZE, callback=self._callback)
            self.stream.start()
        self.playing = True

    def prime_stream(self) -> None:
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=2, dtype="float32", blocksize=BLOCK_SIZE, callback=self._callback)
            self.stream.start()
        self.playing = False

    def stop(self) -> None:
        self.playing = False
        with self._lock:
            for ch in self.channels: ch.position = 0

    def toggle_play(self) -> None:
        if not self.playing and self.stream is None: self.start(); return
        self.playing = not self.playing

    def rewind(self) -> None:
        with self._lock:
            for ch in self.channels: ch.position = 0

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
                if not self.playing:
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
                any_solo = any(ch.solo for ch in self.channels)
                states = [{"ch": ch, "gain": ch.gain, "pan": ch.pan, "mute": ch.mute, "solo": ch.solo, "pos": ch.position} for ch in self.channels]
            mix = np.zeros((frames, 2), dtype=np.float32)
            for s in states:
                ch = s["ch"]; block = self._next_block(ch, frames); processed = self._process_channel(ch, block)
                in_mix = (not s["mute"]) and (not any_solo or s["solo"])
                self._analyze_channel(ch, processed if in_mix else np.zeros_like(processed))
                if not in_mix: processed *= 0.0
                mix += self._apply_pan(processed, s["pan"]) * s["gain"]
                ch.level = float(np.sqrt(np.mean(np.square(processed))) * 3.4)
            mix *= self.master_gain
            if gen_out is not None: mix = (mix.astype(np.float64) + gen_out.astype(np.float64)).astype(np.float32)
            m_proc = self._process_channel(self.master_channel, mix)
            self.master_channel.level = float(np.sqrt(np.mean(np.square(m_proc))) * 2.8)
            pk = float(np.max(np.abs(m_proc)))
            if pk > 0.98: m_proc *= 0.98/pk
            outdata[:] = m_proc.astype(np.float32)
            self.master_level = float(np.sqrt(np.mean(np.square(m_proc))) * 2.8)
            self._analyze_channel(self.master_channel, m_proc.astype(np.float32))
            if status: _log.debug(f"Status: {status}")
        except Exception as e:
            _log.error(f"Callback error: {e}"); outdata[:] = 0.0

    def _next_block(self, ch: ChannelState, frames: int) -> np.ndarray:
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
        x = block.astype(np.float32) * ch.gain
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
            if ch.eq_band_enabled:
                nb = max(1, min(8, int(ch.eq_band_count))); sel = int(np.clip(getattr(ch, "eq_ui_band", 0), 0, nb-1))
                for i in range(nb):
                    b = ch.eq_bands[i]
                    if not b.get("enabled"): continue
                    g = 0.0 if (i==sel and bp.get("GAN")) else float(b.get("gain_db", 0.0))
                    if abs(g) > 0.03: x = self._apply_eq(x, float(b.get("freq", ch.eq_freq)), g, float(b.get("width", ch.eq_width)) if not (i==sel and bp.get("SHP")) else 1.4)
            elif not bp.get("FRQ"):
                g = float(ch.eq_gain_db) if not bp.get("GAN") else 0.0
                if abs(g) > 0.03: x = self._apply_eq(x, float(ch.eq_freq), g, float(ch.eq_width) if not bp.get("SHP") else 1.4)
        if ch.eq_tube: x = np.tanh(x * 1.18).astype(np.float32)
        if ch.trn_enabled: x = self._apply_trn(x, ch)
        if ch.xct_enabled: x = self._apply_xct(x, ch)
        if ch.tbe_enabled: x = self._apply_tbe(x, ch)
        if ch.lpf_enabled: x = self._apply_pre_filter(ch, x, ch.lpf_hz, "lowpass")
        if ch.hpf_enabled: x = self._apply_pre_filter(ch, x, ch.hpf_hz, "highpass")
        return np.clip(x, -1.0, 1.0).astype(np.float32)

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
        out = np.zeros_like(block)
        for i in range(block.shape[1]):
            x = np.clip(block[:, i], -0.999, 0.999); rms = np.sqrt(np.mean(x**2)) + 1e-7; theta = np.arccos(x); enh = x.copy()
            for j, w in enumerate(weights):
                if not bp.get(f"H{j+1}") and w > 0.001: enh += np.cos((j+2)*theta) * w * (0.54 - j*0.05)
            mix = x*0.94 + (np.tanh(enh*1.4) - np.tanh(x*1.4))*0.68
            out[:, i] = np.tanh(mix * (min(2.1, max(0.9, rms/(np.sqrt(np.mean(mix**2))+1e-7)))) * makeup)
        return out.astype(np.float32)

    def _apply_gate(self, ch: ChannelState, block: np.ndarray) -> np.ndarray:
        self._hydrate_gate_dyn_to_scalars(ch)
        if ch.gate_band_enabled:
            b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
            if not b.get("enabled") or b.get("makeup", 1.0) <= 0.001: return block
            atk, rls, thr, rat, mk = b["attack_ms"], b["release_ms"], b["threshold_db"], b["ratio"], b["makeup"]
        elif ch.gate_enabled:
            if ch.gate_makeup <= 0.001: return block
            atk, rls, thr, rat, mk = ch.gate_attack_ms, ch.gate_release_ms, ch.gate_threshold_db, ch.gate_ratio, ch.gate_makeup
        else: return block
        mono = self._mono_for_dynamics_detector(ch, block, kind="gate"); bp = getattr(ch, "gate_param_bypass", {})
        a_env = math.exp(-1.0 / max(1.0, ((0.05 if bp.get("ATK") else atk)/1000.0)*SAMPLE_RATE))
        r_env = math.exp(-1.0 / max(1.0, ((0.05 if bp.get("RLS") else rls)/1000.0)*SAMPLE_RATE))
        ag, rg = math.exp(-1.0 / max(1.0, (atk*0.25/1000.0)*SAMPLE_RATE)), math.exp(-1.0 / max(1.0, (rls*0.3/1000.0)*SAMPLE_RATE))
        thr_db = -168.0 if bp.get("THR") else thr; floor = 1.0 if bp.get("RAT") else 1.0/max(1.001, rat); mkup = 1.0 if bp.get("GAN") else max(0.001, mk)
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
        if ch.comp_band_enabled:
            b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
            if not b.get("enabled") or b.get("makeup", 1.0) <= 0.001: return block
            atk, rls, rat, thr, mk = b["attack_ms"], b["release_ms"], b["ratio"], b["threshold_db"], b["makeup"]
        elif ch.comp_enabled:
            if ch.comp_makeup <= 0.001: return block
            atk, rls, rat, thr, mk = ch.comp_attack_ms, ch.comp_release_ms, ch.comp_ratio, ch.comp_threshold_db, ch.comp_makeup
        else: return block
        bp = getattr(ch, "comp_param_bypass", {})
        if bp.get("THR"): ch.comp_gr_db = 0.0; return block
        mono = self._mono_for_dynamics_detector(ch, block, kind="comp"); env = float(ch.comp_env)
        a_c = math.exp(-1.0 / max(1.0, ((0.05 if bp.get("ATK") else atk)/1000.0)*SAMPLE_RATE))
        r_c = math.exp(-1.0 / max(1.0, ((0.05 if bp.get("RLS") else rls)/1000.0)*SAMPLE_RATE))
        rat, mkup = (1.0 if bp.get("RAT") else max(1.0, rat)), (1.0 if bp.get("GAN") else mk)
        gs = np.empty(len(mono), dtype=np.float32); last_gr = 0.0
        for i, s in enumerate(mono):
            env = (a_c if abs(s)>env else r_c)*env + (1.0-(a_c if abs(s)>env else r_c))*abs(s)
            odb = max(0.0, 20*math.log10(max(env, 1e-7)) - thr); gdb = odb - (odb/rat if odb>0 else 0.0)
            gs[i] = 10**(-gdb/20.0) * mkup; last_gr = gdb
        ch.comp_env, ch.comp_gr_db = env, last_gr
        return block * gs[:, None]

    def _apply_eq(self, block: np.ndarray, freq: float, gain: float, width: float) -> np.ndarray:
        fs = np.fft.rfftfreq(len(block), d=1.0/SAMPLE_RATE); v = fs>0; lfs = np.zeros_like(fs); lfs[v] = np.log2(np.maximum(fs[v], 1.0))
        scale = np.power(10.0, (gain * np.exp(-0.5 * ((lfs - math.log2(float(np.clip(freq, POL_LOW_HZ, POL_HIGH_HZ)))) / max(0.08, width/2.355))**2)) / 20.0).astype(np.float32)
        return np.column_stack([np.fft.irfft(np.fft.rfft(block[:, i]) * scale, n=len(block)) for i in range(block.shape[1])]).astype(np.float32)

    def _apply_trn(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "tone_param_bypass", {})
        if bp.get("TRN"): return block
        ta, ts, dr = [(0.0 if bp.get(k) else v) for k, v in [("ATK", ch.trn_attack), ("SUT", ch.trn_sustain), ("DRV", ch.trn_drive)]]
        if all(abs(v)<0.01 for v in (ta, ts, dr)): return block
        if ch.trn_band_enabled and not bp.get("BND"):
            lo, hi = ch.trn_freq / (2.0**(ch.trn_width/2.0)), ch.trn_freq * (2.0**(ch.trn_width/2.0))
            band = self._apply_simple_filter(self._apply_simple_filter(block, lo, "highpass"), hi, "lowpass")
            return (block - band) + self._apply_transient_processor(band, ta, ts, dr)
        return self._apply_transient_processor(block, ta, ts, dr)

    def _apply_xct(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "tone_param_bypass", {})
        if bp.get("XCT") or abs(ch.xct_drive)<0.01: return block
        hp = float(ch.xct_freq) if (ch.xct_band_enabled and not bp.get("BND")) else 4000.0
        hi = self._apply_simple_filter(block, hp, "highpass")
        ex = np.tanh(hi * (1.0 + ch.xct_drive*6.0)) - np.tanh(hi*0.8)
        return np.clip(block + ex*0.9, -1.0, 1.0).astype(np.float32)

    def _apply_tbe(self, block: np.ndarray, ch: ChannelState) -> np.ndarray:
        bp = getattr(ch, "tone_param_bypass", {})
        if abs(ch.tbe_drive)<0.01: return block
        drv = 1.0 + ch.tbe_drive*5.0
        if ch.tbe_band_enabled and not bp.get("BND"):
            band = self._apply_simple_filter(block, 2500.0, "lowpass")
            return (block-band) + np.tanh(band*drv).astype(np.float32)
        return np.tanh(block*drv).astype(np.float32)

    def _apply_transient_processor(self, b: np.ndarray, a: float, s: float, d: float) -> np.ndarray:
        x = self._apply_transient(b, a, s)
        return np.tanh(x * (1.0 + d*4.0)).astype(np.float32) if abs(d)>0.01 else x

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
        ch.gate_center_hz, ch.gate_width_oct, ch.gate_threshold_db, ch.gate_ratio, ch.gate_attack_ms, ch.gate_release_ms, ch.gate_makeup = b["freq"], b["width_oct"], b["threshold_db"], b["ratio"], b["attack_ms"], b["release_ms"], b["makeup"]

    def _hydrate_comp_dyn_to_scalars(self, ch: ChannelState) -> None:
        if not getattr(ch, "comp_band_enabled", False): return
        b = ch.comp_dyn_bands[max(0, min(int(ch.comp_dyn_band_count)-1, int(ch.comp_dyn_ui_band)))]
        ch.comp_center_hz, ch.comp_width_oct, ch.comp_threshold_db, ch.comp_ratio, ch.comp_attack_ms, ch.comp_release_ms, ch.comp_makeup = b["freq"], b["width_oct"], b["threshold_db"], b["ratio"], b["attack_ms"], b["release_ms"], b["makeup"]

    def _flush_gate_scalars_to_dyn_band(self, ch: ChannelState) -> None:
        if getattr(ch, "gate_band_enabled", False):
            b = ch.gate_dyn_bands[max(0, min(int(ch.gate_dyn_band_count)-1, int(ch.gate_dyn_ui_band)))]
            b["freq"], b["width_oct"] = float(ch.gate_center_hz), float(ch.gate_width_oct)

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

    def _mono_for_dynamics_detector(self, ch: ChannelState, block: np.ndarray, *, kind: str) -> np.ndarray:
        m_full = np.mean(block, axis=1).astype(np.float32)
        if kind == "gate":
            if not getattr(ch, "gate_band_enabled", False): return m_full
            gb = getattr(ch, "gate_param_bypass", {})
            if gb.get("FRQ") or gb.get("WDT"): return m_full
            b = ch.gate_dyn_bands[max(0, min(int(getattr(ch, "gate_dyn_band_count", 1))-1, int(getattr(ch, "gate_dyn_ui_band", 0))))]
            return self._bandpass_mono(block, float(b["freq"]), float(b["width_oct"]), m_full)
        if kind == "comp":
            if not getattr(ch, "comp_band_enabled", False): return m_full
            cb = getattr(ch, "comp_param_bypass", {})
            if cb.get("FRQ") or cb.get("WDT"): return m_full
            b = ch.comp_dyn_bands[max(0, min(int(getattr(ch, "comp_dyn_band_count", 1))-1, int(getattr(ch, "comp_dyn_ui_band", 0))))]
            return self._bandpass_mono(block, float(b["freq"]), float(b["width_oct"]), m_full)
        return m_full

"""
voice/recorder.py
Two recorder classes:
  - AudioRecorder   : push-to-talk recorder
  - StreamRecorder  : real-time always-on recorder with per-utterance callbacks

Key design:
  - Captures at the device's native rate (commonly 48 kHz on WASAPI) and
    resamples on-the-fly to 16 kHz for Whisper / WebRTC VAD.
  - Automatically finds the best streaming-compatible input device by probing
    each candidate with a real RawInputStream (not sd.rec which uses a different
    path and can succeed on WDM-KS devices that RawInputStream can't use).
  - Sensitive energy + WebRTC VAD speech detection tuned for laptop microphones.
"""

from __future__ import annotations

import logging
import queue
import threading
import numpy as np
from typing import Callable, Optional

log = logging.getLogger(__name__)

WHISPER_RATE      = 16000   # Hz — required by Whisper & webrtcvad
CHANNELS          = 1
DTYPE             = "int16"
FRAME_DURATION_MS = 30      # VAD frame size (must be 10/20/30 ms for webrtcvad)

# Cache the probe result so we don't re-probe on every recorder creation
_CACHED_DEVICE: int | None = None
_CACHED_RATE:   int | None = None


def _probe_device_stream(dev_idx: int) -> tuple[bool, int, float]:
    """
    Try to open a RawInputStream on dev_idx and measure average RMS over 0.5 s.
    Returns (success, native_sample_rate, avg_rms).
    """
    import sounddevice as sd

    d = sd.query_devices(dev_idx)
    native_sr = int(d.get("default_samplerate", 16000))
    frame_samples = int(native_sr * FRAME_DURATION_MS / 1000)
    q: queue.Queue[bytes] = queue.Queue()

    def _cb(indata, frames, t, status, _q=q):
        _q.put(bytes(indata))

    import time
    count = 0
    total_rms = 0.0
    try:
        with sd.RawInputStream(
            samplerate=native_sr,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=frame_samples,
            device=dev_idx,
            callback=_cb,
        ):
            t0 = time.time()
            while time.time() - t0 < 0.5:
                try:
                    frame = q.get(timeout=0.1)
                    arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                    total_rms += float(np.sqrt(np.mean(arr ** 2)))
                    count += 1
                except queue.Empty:
                    pass
        avg = total_rms / count if count else 0.0
        return (count > 0), native_sr, avg
    except Exception:
        return False, native_sr, 0.0


def find_active_streaming_device(preferred: int | None = None) -> tuple[int | None, int]:
    """
    Find the best microphone that works with RawInputStream callback streaming.
    Returns (device_index, sample_rate).  device_index=None means use system default.

    Uses a module-level cache so the expensive probe only runs once per process.
    If preferred is specified, use it directly (still probe its native sample rate).
    """
    global _CACHED_DEVICE, _CACHED_RATE

    if preferred is not None:
        try:
            import sounddevice as sd
            d = sd.query_devices(preferred)
            return preferred, int(d.get("default_samplerate", WHISPER_RATE))
        except Exception:
            pass

    if _CACHED_DEVICE is not None and _CACHED_RATE is not None:
        log.debug("Audio: using cached device #%s @ %d Hz", _CACHED_DEVICE, _CACHED_RATE)
        return _CACHED_DEVICE, _CACHED_RATE

    try:
        import sounddevice as sd

        devs = sd.query_devices()

        # Score candidates: prefer "array" mics over headsets; WASAPI (hostapi=2) preferred
        def _score(i: int, d: dict) -> int:
            if d.get("max_input_channels", 0) <= 0:
                return -1
            name = d.get("name", "").lower()
            score = 0
            if d.get("hostapi") == 2:   # WASAPI — most compatible for streaming
                score += 100
            if "array" in name:
                score += 50
            if "microphone" in name and "headset" not in name:
                score += 20
            if "headset" in name:
                score -= 20
            if "speaker" in name or "output" in name or "stereo mix" in name:
                score -= 200
            return score

        ranked = sorted(
            [(i, d) for i, d in enumerate(devs)],
            key=lambda t: _score(t[0], t[1]),
            reverse=True,
        )

        best_dev = None
        best_rate = WHISPER_RATE
        best_rms = -1.0

        for dev_idx, dev_info in ranked:
            if _score(dev_idx, dev_info) < 0:
                continue
            name = dev_info.get("name", "")
            log.debug("Audio probe: testing device #%d '%s'...", dev_idx, name)
            ok, native_sr, avg_rms = _probe_device_stream(dev_idx)
            if not ok:
                log.debug("Audio probe: device #%d skipped (stream failed)", dev_idx)
                continue
            log.info("Audio probe: device #%d '%s' OK — native=%d Hz  avg_rms=%.1f",
                     dev_idx, name, native_sr, avg_rms)
            if best_dev is None:
                # Accept the first working device even if silent (ambient only)
                best_dev = dev_idx
                best_rate = native_sr
                best_rms = avg_rms
            # But always prefer a device with actual signal over a silent one
            if avg_rms > best_rms + 1.0:
                best_dev = dev_idx
                best_rate = native_sr
                best_rms = avg_rms

        if best_dev is not None:
            log.info("Audio: selected streaming device #%d (native=%d Hz, rms=%.1f)",
                     best_dev, best_rate, best_rms)
            _CACHED_DEVICE = best_dev
            _CACHED_RATE = best_rate
            return best_dev, best_rate

        # Fallback: use system default at 16kHz
        log.warning("Audio: no suitable streaming device found — using system default")
        _CACHED_DEVICE = None
        _CACHED_RATE = WHISPER_RATE
        return None, WHISPER_RATE

    except Exception as exc:
        log.warning("Audio device probe failed: %s — using system default", exc)
        return None, WHISPER_RATE


def _resample_to_16k(data: np.ndarray, source_rate: int) -> np.ndarray:
    """Downsample int16 audio from source_rate to 16000 Hz using linear interpolation."""
    if source_rate == WHISPER_RATE:
        return data
    ratio = WHISPER_RATE / source_rate
    target_len = max(1, int(len(data) * ratio))
    x_old = np.linspace(0, 1, len(data))
    x_new = np.linspace(0, 1, target_len)
    return np.interp(x_new, x_old, data.astype(np.float32)).astype(np.int16)


def _make_vad(aggressiveness: int):
    """Return a webrtcvad.Vad object or None if not installed."""
    try:
        import webrtcvad
        vad = webrtcvad.Vad(aggressiveness)
        log.info("VAD: WebRTC VAD ready (aggressiveness=%d)", aggressiveness)
        return vad
    except ImportError:
        log.info("VAD: webrtcvad not installed — using energy threshold only")
        return None


def _calc_visual_level(arr_16k: np.ndarray) -> float:
    """Calculate a responsive, normalized 0.0-1.0 audio level for UI waveforms."""
    if len(arr_16k) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(arr_16k.astype(np.float32) ** 2)))
    # Responsive sensitivity mapping: ambient (~5-10) -> 0.0, normal speech (20-150) -> 0.3-0.9
    level = min(1.0, max(0.0, (rms - 5.0) / 80.0) ** 0.65)
    return level


def _is_speech_frame(frame_16k: bytes, vad, energy_threshold: float = 16.0) -> bool:
    """Return True if this 16 kHz audio frame contains speech."""
    arr = np.frombuffer(frame_16k, dtype=np.int16).astype(np.float32)
    if len(arr) == 0:
        return False
    rms = float(np.sqrt(np.mean(arr ** 2)))

    # Energy above threshold = definitely sound
    if rms > energy_threshold:
        return True

    # WebRTC VAD as secondary check
    if vad is not None:
        frame_bytes_needed = int(WHISPER_RATE * FRAME_DURATION_MS / 1000) * 2
        if len(frame_16k) >= frame_bytes_needed:
            try:
                if vad.is_speech(frame_16k[:frame_bytes_needed], WHISPER_RATE):
                    return True
            except Exception:
                pass

    return False


# ── Push-to-talk AudioRecorder ────────────────────────────────────────────────

class AudioRecorder:
    """
    Captures microphone audio until silence is detected.
    Automatically captures at the device's native rate and resamples to 16 kHz.
    """

    def __init__(
        self,
        level_callback:   Callable[[float], None] | None = None,
        silence_callback: Callable[[], None]       | None = None,
        error_callback:   Callable[[str], None]    | None = None,
        silence_threshold_ms: int = 1200,
        vad_aggressiveness:   int = 1,
        device: int | None = None,
    ) -> None:
        self._level_cb   = level_callback
        self._silence_cb = silence_callback
        self._error_cb   = error_callback

        self._device, self._capture_rate = find_active_streaming_device(device)

        self._audio_q:  queue.Queue[bytes] = queue.Queue()
        self._recorded: list[np.ndarray]   = []
        self._running   = False
        self._thread:   Optional[threading.Thread] = None
        self._stream    = None

        self._vad = _make_vad(vad_aggressiveness)
        self._silent_frames    = 0
        self._max_silent_frames = int(silence_threshold_ms / FRAME_DURATION_MS)
        self._speech_started   = False

        self._frame_samples_native = int(self._capture_rate * FRAME_DURATION_MS / 1000)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._recorded.clear()
        self._drain_queue()
        self._silent_frames  = 0
        self._speech_started = False
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info("AudioRecorder started (device=%s, rate=%d).", self._device, self._capture_rate)

    def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def get_audio(self) -> Optional[np.ndarray]:
        if not self._recorded:
            return None
        return np.concatenate(self._recorded)

    def _capture_loop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self._emit_error("sounddevice not installed.")
            self._running = False
            return

        try:
            with sd.RawInputStream(
                samplerate=self._capture_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self._frame_samples_native,
                device=self._device,
                callback=self._sd_callback,
            ) as self._stream:
                while self._running:
                    try:
                        frame = self._audio_q.get(timeout=0.1)
                        self._process_frame(frame)
                    except queue.Empty:
                        continue
        except Exception as exc:
            log.error("AudioRecorder error: %s", exc)
            self._emit_error(f"Microphone error: {exc}")
        finally:
            self._running = False

    def _sd_callback(self, indata, frames, time_info, status) -> None:
        self._audio_q.put(bytes(indata))

    def _process_frame(self, frame: bytes) -> None:
        # Resample to 16 kHz
        native_arr = np.frombuffer(frame, dtype=np.int16)
        arr_16k    = _resample_to_16k(native_arr, self._capture_rate)
        frame_16k  = arr_16k.tobytes()

        if self._level_cb:
            self._level_cb(_calc_visual_level(arr_16k))

        self._recorded.append(arr_16k)
        is_speech = _is_speech_frame(frame_16k, self._vad)

        if is_speech:
            self._speech_started = True
            self._silent_frames  = 0
        elif self._speech_started:
            self._silent_frames += 1
            if self._silent_frames >= self._max_silent_frames:
                self._running = False
                if self._silence_cb:
                    self._silence_cb()

    def _drain_queue(self) -> None:
        while True:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                return

    def _emit_error(self, msg: str) -> None:
        if self._error_cb:
            self._error_cb(msg)


# ── Always-on StreamRecorder ──────────────────────────────────────────────────

class StreamRecorder:
    """
    Always-on microphone recorder.  Detects per-utterance speech segments and
    fires utterance_callback(audio_16k: np.ndarray) for each complete utterance.
    """

    def __init__(
        self,
        level_callback:     Callable[[float], None]      | None = None,
        utterance_callback: Callable[[np.ndarray], None] | None = None,
        error_callback:     Callable[[str], None]        | None = None,
        silence_threshold_ms: int = 800,
        vad_aggressiveness:   int = 1,
        min_speech_ms:        int = 250,
        max_utterance_ms:     int = 15000,
        device: int | None = None,
    ) -> None:
        self._level_cb     = level_callback
        self._utterance_cb = utterance_callback
        self._error_cb     = error_callback

        self._device, self._capture_rate = find_active_streaming_device(device)

        self._max_silent_frames    = int(silence_threshold_ms / FRAME_DURATION_MS)
        self._min_speech_frames    = int(min_speech_ms        / FRAME_DURATION_MS)
        self._max_utterance_frames = int(max_utterance_ms     / FRAME_DURATION_MS)

        self._running  = False
        self._paused   = False
        self._thread:  Optional[threading.Thread] = None
        self._stream   = None
        self._audio_q: queue.Queue[bytes] = queue.Queue()

        self._recording:      list[np.ndarray] = []
        self._speech_started  = False
        self._silent_frames   = 0
        self._speech_frames   = 0

        self._vad = _make_vad(vad_aggressiveness)
        self._frame_samples_native = int(self._capture_rate * FRAME_DURATION_MS / 1000)

        log.info("StreamRecorder: device=#%s  capture_rate=%d Hz  whisper_rate=16000 Hz",
                 self._device, self._capture_rate)

    def start(self) -> None:
        self._paused = False
        if self._running and self._stream is not None:
            self.resume()
            return
        self._running = True
        self._reset_utterance()
        self._drain_queue()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info("StreamRecorder: started listening.")

    def stop(self) -> None:
        self._running = False
        self._paused  = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def pause(self) -> None:
        self._paused = True
        self._reset_utterance()
        log.debug("StreamRecorder: paused.")

    def resume(self) -> None:
        self._reset_utterance()
        self._drain_queue()
        self._paused = False
        log.debug("StreamRecorder: resumed.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _capture_loop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self._emit_error("sounddevice not installed.")
            self._running = False
            return

        try:
            with sd.RawInputStream(
                samplerate=self._capture_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self._frame_samples_native,
                device=self._device,
                callback=self._sd_callback,
            ) as self._stream:
                log.info("StreamRecorder: stream open on device #%s @ %d Hz.",
                         self._device, self._capture_rate)
                while self._running:
                    try:
                        frame = self._audio_q.get(timeout=0.1)
                        self._process_frame(frame)
                    except queue.Empty:
                        continue
        except Exception as exc:
            log.error("StreamRecorder error: %s", exc)
            self._emit_error(f"Microphone error: {exc}")
        finally:
            self._running = False

    def _sd_callback(self, indata, frames, time_info, status) -> None:
        self._audio_q.put(bytes(indata))

    def _process_frame(self, frame: bytes) -> None:
        # Resample native audio to 16 kHz for VAD and Whisper
        native_arr = np.frombuffer(frame, dtype=np.int16)
        arr_16k    = _resample_to_16k(native_arr, self._capture_rate)
        frame_16k  = arr_16k.tobytes()

        # Emit audio level for UI waveform
        if self._level_cb:
            self._level_cb(_calc_visual_level(arr_16k))

        if self._paused:
            return

        is_speech = _is_speech_frame(frame_16k, self._vad)

        if is_speech:
            self._speech_started = True
            self._silent_frames  = 0
            self._speech_frames += 1
            self._recording.append(arr_16k)

            if self._speech_frames >= self._max_utterance_frames:
                log.debug("StreamRecorder: max utterance length reached.")
                self._emit_utterance()

        elif self._speech_started:
            self._recording.append(arr_16k)
            self._silent_frames += 1

            if self._silent_frames >= self._max_silent_frames:
                if self._speech_frames >= self._min_speech_frames:
                    log.debug("StreamRecorder: utterance end detected (%d speech frames).",
                              self._speech_frames)
                    self._emit_utterance()
                else:
                    log.debug("StreamRecorder: too short (%d frames) — discarding.",
                              self._speech_frames)
                    self._reset_utterance()

    def _emit_utterance(self) -> None:
        if self._recording and self._utterance_cb:
            audio = np.concatenate(self._recording)
            duration_s = len(audio) / WHISPER_RATE
            rms_peak   = int(np.max(np.abs(audio))) if len(audio) else 0
            log.info(
                "VOICE CAPTURE: duration=%.2fs  samples=%d  rms_peak=%d",
                duration_s, len(audio), rms_peak,
            )
            self._reset_utterance()
            try:
                self._utterance_cb(audio)
            except Exception as exc:
                log.error("utterance_callback error: %s", exc)
        else:
            self._reset_utterance()

    def _reset_utterance(self) -> None:
        self._recording      = []
        self._speech_started = False
        self._silent_frames  = 0
        self._speech_frames  = 0

    def _drain_queue(self) -> None:
        while True:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                return

    def _emit_error(self, msg: str) -> None:
        if self._error_cb:
            self._error_cb(msg)

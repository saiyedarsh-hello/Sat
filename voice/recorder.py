"""
voice/recorder.py
sounddevice-based audio capture with WebRTC VAD gating.
Runs in a background thread; emits audio_level floats and signals
AppController when speech ends (VAD silence detected).
"""

from __future__ import annotations

import logging
import queue
import threading
import numpy as np
from typing import Callable, Optional

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000   # Hz — required by Whisper & webrtcvad
CHANNELS = 1
DTYPE = "int16"
FRAME_DURATION_MS = 30   # VAD frame size (10 / 20 / 30 ms)
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
FRAME_BYTES = FRAME_SAMPLES * 2   # int16 = 2 bytes


class AudioRecorder:
    """
    Continuously captures microphone audio.
    - Calls `level_callback(float)` every frame for waveform display.
    - Accumulates audio while speech is detected (VAD).
    - Calls `silence_callback()` when speech ends.
    - `get_audio()` returns the recorded numpy array (int16, 16 kHz).
    """

    def __init__(
        self,
        level_callback: Callable[[float], None] | None = None,
        silence_callback: Callable[[], None] | None = None,
        error_callback: Callable[[str], None] | None = None,
        silence_threshold_ms: int = 1200,
        vad_aggressiveness: int = 2,
        device: int | None = None,
    ) -> None:
        self._level_cb = level_callback
        self._silence_cb = silence_callback
        self._error_cb = error_callback
        self._silence_threshold_ms = silence_threshold_ms
        self._device = device

        self._audio_q: queue.Queue[bytes] = queue.Queue()
        self._recorded: list[bytes] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None

        # VAD
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(vad_aggressiveness)
        except ImportError:
            log.warning("webrtcvad not available — using energy-based VAD")
            self._vad = None

        # Silence counter
        self._silent_frames = 0
        self._max_silent_frames = int(silence_threshold_ms / FRAME_DURATION_MS)
        self._speech_started = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin capturing audio from the microphone."""
        if self._running:
            return
        self._running = True
        self._recorded.clear()
        self._drain_queue()
        self._speech_started = False
        self._silent_frames = 0

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.debug("Recorder started.")

    def stop(self) -> None:
        """Stop capture immediately (without waiting for VAD silence)."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        log.debug("Recorder stopped.")

    def get_audio(self) -> np.ndarray | None:
        """Return recorded audio as int16 numpy array, or None if empty."""
        if not self._recorded:
            return None
        raw = b"".join(self._recorded)
        return np.frombuffer(raw, dtype=np.int16)

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            log.error("sounddevice not installed.")
            self._emit_error("sounddevice is not installed. Microphone capture is unavailable.")
            self._running = False
            return

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SAMPLES,
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
            log.error("Recorder error: %s", exc)
            self._emit_error(f"Microphone error: {exc}")
        finally:
            self._running = False

    def _sd_callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("sounddevice status: %s", status)
        self._audio_q.put(bytes(indata))

    def _process_frame(self, frame: bytes) -> None:
        # Level meter
        arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2))) / 32768.0
        if self._level_cb:
            self._level_cb(min(1.0, rms * 8))

        # VAD
        is_speech = self._is_speech(frame)
        if is_speech:
            self._speech_started = True
            self._silent_frames = 0
            self._recorded.append(frame)
        elif self._speech_started:
            self._recorded.append(frame)
            self._silent_frames += 1
            if self._silent_frames >= self._max_silent_frames:
                log.debug("VAD silence detected — ending recording.")
                self._running = False
                if self._silence_cb:
                    self._silence_cb()

    def _is_speech(self, frame: bytes) -> bool:
        """WebRTC VAD or energy fallback."""
        arr = np.frombuffer(frame[:FRAME_BYTES], dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2)))

        if self._vad:
            try:
                if self._vad.is_speech(frame[:FRAME_BYTES], SAMPLE_RATE):
                    return True
            except Exception:
                pass

        return rms > 350

    def _drain_queue(self) -> None:
        while True:
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                return

    def _emit_error(self, message: str) -> None:
        if self._error_cb:
            self._error_cb(message)

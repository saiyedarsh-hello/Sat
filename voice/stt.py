"""
voice/stt.py
Speech-to-text using faster-whisper with context conditioning for high accuracy.

The transcribe() API is simple:
    engine.load()
    text = engine.transcribe(audio_int16_numpy_array_at_16khz)
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import wave
import numpy as np
from typing import Optional

from config import config

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Initial prompt conditions Whisper to recognize assistant triggers and app names accurately
_WHISPER_PROMPT = (
    "Saturday desktop assistant. Open WhatsApp, Chrome, Edge, Firefox, Brave, YouTube, "
    "Spotify, Discord, VS Code, Notepad, Calculator, Google, Settings, Telegram."
)


class STTEngine:
    """Whisper-based STT engine (faster-whisper primary with fallback)."""

    def __init__(self) -> None:
        self._model_size = config.get("voice", "stt_model",    default="small.en")
        self._device     = config.get("voice", "stt_device",   default="cpu")
        self._language   = config.get("voice", "stt_language", default="en")
        self._model      = None

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load Whisper model (call once from background loader)."""
        try:
            from faster_whisper import WhisperModel
            log.info("Loading Whisper model '%s' on %s …", self._model_size, self._device)
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type="int8",
            )
            self._transcribe_fn = self._transcribe_faster_whisper
            log.info("Whisper model loaded (faster-whisper, model=%s)", self._model_size)
            return
        except Exception as exc:
            log.warning("Primary faster-whisper load failed (%s) — trying RealtimeSTT fallback", exc)

        try:
            from RealtimeSTT import AudioToTextRecorder
            self._load_realtimestt()
        except Exception as exc2:
            log.error("Failed to load any STT model: %s", exc2)

    def _load_realtimestt(self) -> None:
        from RealtimeSTT import AudioToTextRecorder
        log.info("Loading RealtimeSTT model '%s' on %s …", self._model_size, self._device)
        self._model = AudioToTextRecorder(
            model=self._model_size,
            language=self._language,
            device=self._device,
            compute_type="int8",
            use_microphone=False,
            spinner=False,
            enable_realtime_transcription=False,
            silero_sensitivity=0.4,
            post_speech_silence_duration=0.5,
            on_recording_start=None,
            on_recording_stop=None,
        )
        self._transcribe_fn = self._transcribe_realtimestt
        log.info("RealtimeSTT model loaded")

    # ── Transcription dispatch ────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe a numpy int16 array at 16 kHz.
        Returns the transcribed string (empty if nothing detected).
        """
        if self._model is None:
            log.warning("STT model not loaded.")
            return ""
        try:
            fn = getattr(self, "_transcribe_fn", self._transcribe_faster_whisper)
            duration_s = len(audio) / SAMPLE_RATE
            t0 = time.monotonic()
            text = fn(audio)
            elapsed = time.monotonic() - t0
            backend = "realtimestt" if "realtimestt" in str(fn).lower() else "faster-whisper"
            log.info(
                "STT: backend=%s  model=%s  audio=%.2fs  transcribed_in=%.2fs  result=%r",
                backend, self._model_size, duration_s, elapsed, text[:120],
            )
            return text.strip()
        except Exception as exc:
            log.error("Transcription error: %s", exc)
            return ""

    def _transcribe_faster_whisper(self, audio: np.ndarray) -> str:
        audio_f32 = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio_f32,
            language=self._language,
            beam_size=5,
            initial_prompt=_WHISPER_PROMPT,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def _transcribe_realtimestt(self, audio: np.ndarray) -> str:
        """Write audio to a temp WAV and transcribe via RealtimeSTT."""
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp = f.name
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            return (self._model.transcribe_audio_file(tmp) or "").strip()
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    @property
    def is_ready(self) -> bool:
        return self._model is not None

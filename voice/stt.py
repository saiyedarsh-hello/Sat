"""
voice/stt.py
faster-whisper speech-to-text transcription worker.
Loads the model once; transcribe() is called from a QThreadPool worker.
"""

from __future__ import annotations

import logging
import tempfile
import os
import numpy as np
from pathlib import Path

from config import config

log = logging.getLogger(__name__)


class STTEngine:
    """Wraps faster-whisper for offline transcription."""

    def __init__(self) -> None:
        self._model = None
        self._model_size = config.get("voice", "stt_model", default="tiny.en")
        self._device = config.get("voice", "stt_device", default="cpu")
        self._language = config.get("voice", "stt_language", default="en")

    def load(self) -> None:
        """Load the Whisper model (call once at startup in a background thread)."""
        try:
            from faster_whisper import WhisperModel
            log.info("Loading Whisper model '%s' on %s…", self._model_size, self._device)
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type="int8",
            )
            log.info("Whisper model loaded.")
        except ImportError:
            log.warning("faster-whisper not installed — STT disabled.")
        except Exception as exc:
            log.error("Failed to load Whisper model: %s", exc)

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe a numpy int16 array at 16 kHz.
        Returns the transcribed string (empty if nothing detected).
        """
        if self._model is None:
            log.warning("STT model not loaded.")
            return ""

        # faster-whisper needs float32 normalized audio
        audio_f32 = audio.astype(np.float32) / 32768.0

        try:
            segments, info = self._model.transcribe(
                audio_f32,
                language=self._language,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            log.info("STT result: %r", text)
            return text
        except Exception as exc:
            log.error("Transcription error: %s", exc)
            return ""

    @property
    def is_ready(self) -> bool:
        return self._model is not None

"""
voice/tts.py
pyttsx3 (Windows SAPI5) text-to-speech engine.
speak() runs synchronously in a QThreadPool worker thread — never blocks the GUI.
"""

from __future__ import annotations

import logging
import threading

from config import config

log = logging.getLogger(__name__)

_ENGINE_LOCK = threading.Lock()


class TTSEngine:
    """pyttsx3-based TTS; safe to call from worker threads."""

    def __init__(self) -> None:
        self._engine = None
        self._rate = config.get("voice", "tts_rate", default=175)
        self._volume = config.get("voice", "tts_volume", default=1.0)
        self._voice_index = config.get("voice", "tts_voice_index", default=0)

    def load(self) -> None:
        """Initialise pyttsx3 engine (call once at startup)."""
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._apply_settings()
            log.info("TTS engine ready (pyttsx3 / SAPI5).")
        except Exception as exc:
            log.error("TTS init failed: %s", exc)

    def _apply_settings(self) -> None:
        if not self._engine:
            return
        self._engine.setProperty("rate", self._rate)
        self._engine.setProperty("volume", float(self._volume))
        voices = self._engine.getProperty("voices")
        if voices and self._voice_index < len(voices):
            self._engine.setProperty("voice", voices[self._voice_index].id)

    def reload_settings(self) -> None:
        """Re-read config and apply (called after Settings save)."""
        self._rate = config.get("voice", "tts_rate", default=175)
        self._volume = config.get("voice", "tts_volume", default=1.0)
        self._voice_index = config.get("voice", "tts_voice_index", default=0)
        self._apply_settings()

    def speak(self, text: str) -> None:
        """Synthesise and play `text`. Blocks until audio finishes."""
        if not text or not text.strip():
            return
        if self._engine is None:
            log.warning("TTS engine not initialised.")
            return
        with _ENGINE_LOCK:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                log.error("TTS speak error: %s", exc)

    def stop(self) -> None:
        """Interrupt any ongoing TTS synthesis."""
        if self._engine:
            try:
                self._engine.stop()
                log.info("TTS interrupted.")
            except Exception as exc:
                log.error("TTS stop failed: %s", exc)

    def get_voices(self) -> list[str]:
        """Return list of available voice names for the settings UI."""
        if not self._engine:
            return []
        try:
            return [v.name for v in self._engine.getProperty("voices")]
        except Exception:
            return []

    @property
    def is_ready(self) -> bool:
        return self._engine is not None

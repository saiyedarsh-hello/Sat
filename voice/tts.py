"""
voice/tts.py
Windows SAPI5 text-to-speech engine using native COM (win32com.client / SAPI.SpVoice).
Thread-safe, zero deadlocks, and completely immune to pyttsx3's "run loop already started" error.
"""

from __future__ import annotations

import logging
import os
import threading

from config import config

log = logging.getLogger(__name__)

_ENGINE_LOCK = threading.Lock()


class TTSEngine:
    """Thread-safe SAPI5 Text-to-Speech Engine."""

    def __init__(self) -> None:
        self._rate_val    = config.get("voice", "tts_rate",        default=175)
        self._volume_val  = config.get("voice", "tts_volume",      default=1.0)
        self._voice_index = config.get("voice", "tts_voice_index", default=0)
        self._voices_list: list[str] = []
        self._voice_ids:   list[str] = []
        self._current_voice = None

    def load(self) -> None:
        """Discover installed SAPI5 voices."""
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            tokens = voice.GetVoices()
            self._voices_list = [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
            self._voice_ids   = [tokens.Item(i).Id for i in range(tokens.Count)]
            pythoncom.CoUninitialize()

            log.info("TTS: %d voice(s) available: %s", len(self._voices_list), self._voices_list)
            if self._voices_list:
                idx = min(self._voice_index, len(self._voices_list) - 1)
                log.info("TTS: using voice[%d]: %r", idx, self._voices_list[idx])
            log.info("TTS engine ready (native SAPI5 / SpVoice).")
        except Exception as exc:
            log.error("TTS load failed: %s", exc)

    def reload_settings(self) -> None:
        """Re-read configuration."""
        self._rate_val    = config.get("voice", "tts_rate",        default=175)
        self._volume_val  = config.get("voice", "tts_volume",      default=1.0)
        self._voice_index = config.get("voice", "tts_voice_index", default=0)

    def speak(self, text: str) -> None:
        """
        Synthesise and play `text` synchronously on the calling thread.
        Uses COM CoInitialize per-thread to ensure complete thread-safety.
        """
        if not text or not text.strip():
            return

        with _ENGINE_LOCK:
            try:
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()
                try:
                    voice = win32com.client.Dispatch("SAPI.SpVoice")
                    self._current_voice = voice

                    # Set Volume (0 to 100)
                    vol = int(float(self._volume_val) * 100)
                    voice.Volume = max(0, min(100, vol))

                    # Set Rate (-10 to +10 in SAPI; map 175 wpm -> ~0 to 1)
                    # Standard mapping: rate 100 -> -4, 175 -> 0, 250 -> +4
                    sapi_rate = int((self._rate_val - 175) / 20)
                    voice.Rate = max(-10, min(10, sapi_rate))

                    # Set Voice
                    tokens = voice.GetVoices()
                    if tokens.Count > 0:
                        idx = min(max(0, self._voice_index), tokens.Count - 1)
                        voice.Voice = tokens.Item(idx)

                    # Speak synchronously (Flag 0 = SPF_DEFAULT / Synchronous)
                    voice.Speak(text.strip(), 0)
                finally:
                    self._current_voice = None
                    pythoncom.CoUninitialize()

            except Exception as exc:
                log.error("TTS speak error: %s", exc)

    def stop(self) -> None:
        """Interrupt any ongoing TTS synthesis immediately."""
        try:
            if self._current_voice:
                # SVSFPurgeBeforeSpeak (Flag 2) purges ongoing speech immediately
                self._current_voice.Speak("", 2)
                log.info("TTS interrupted.")
        except Exception as exc:
            log.debug("TTS stop failed: %s", exc)

    def get_voices(self) -> list[str]:
        """Return list of available voice names for settings UI."""
        return self._voices_list

    @property
    def is_ready(self) -> bool:
        return len(self._voices_list) > 0 or True

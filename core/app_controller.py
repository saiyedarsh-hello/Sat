"""
core/app_controller.py
Central state machine for Saturday.
"""

from __future__ import annotations

import logging
from enum import Enum, auto

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

log = logging.getLogger(__name__)


class AppState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()
    DISMISS = auto()


class AppController(QObject):
    state_changed = Signal(object)
    transcription_ready = Signal(str)
    response_ready = Signal(str)
    action_completed = Signal(str, bool)
    error_occurred = Signal(str)
    reminder_fired = Signal(str, str)
    show_card = Signal(str, str)
    audio_level = Signal(float)

    # Thread-safe request/result signals.
    activate_requested = Signal()
    deactivate_requested = Signal()
    vad_silence_requested = Signal()
    recorder_error = Signal(str)
    transcription_result = Signal(str)
    agent_result = Signal(str)
    speak_done_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = AppState.IDLE

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._on_dismiss_timeout)

        self._listen_timer = QTimer(self)
        self._listen_timer.setSingleShot(True)
        self._listen_timer.timeout.connect(self._on_listen_timeout)

        self.activate_requested.connect(self.activate)
        self.deactivate_requested.connect(self.deactivate)
        self.vad_silence_requested.connect(self.on_vad_silence)
        self.recorder_error.connect(self.on_error)
        self.transcription_result.connect(self.on_transcription)
        self.agent_result.connect(self.on_response)
        self.speak_done_requested.connect(self.on_speak_done)

        self.recorder = None
        self.stt = None
        self.tts = None
        self.llm = None
        self.agent = None
        self.memory = None

    @property
    def state(self) -> AppState:
        return self._state

    def _transition(self, new_state: AppState) -> None:
        if self._state == new_state:
            return
        log.debug("State: %s -> %s", self._state.name, new_state.name)
        self._state = new_state
        self.state_changed.emit(new_state)

    def activate(self) -> None:
        if self._state != AppState.IDLE:
            log.debug("activate() ignored; already in %s", self._state.name)
            return
        if not self.recorder:
            self.show_card.emit("Saturday", "Still getting ready. Try again in a moment.")
            return
        self._transition(AppState.LISTENING)
        self._start_recording()

    def deactivate(self) -> None:
        self._listen_timer.stop()
        self._dismiss_timer.stop()
        self._stop_recording()
        if self.tts:
            try:
                self.tts.stop()
            except Exception as exc:
                log.debug("Failed to stop TTS: %s", exc)
        self._transition(AppState.DISMISS)
        QTimer.singleShot(250, lambda: self._transition(AppState.IDLE))

    def on_vad_silence(self) -> None:
        if self._state != AppState.LISTENING:
            return
        self._listen_timer.stop()
        self._stop_recording()
        self._transition(AppState.PROCESSING)
        self._run_stt()

    def on_transcription(self, text: str) -> None:
        if self._state not in (AppState.LISTENING, AppState.PROCESSING):
            log.debug("on_transcription() ignored; state is %s", self._state.name)
            return
        self.transcription_ready.emit(text)
        log.info("Transcription: %s", text)
        self._run_llm(text)

    def on_response(self, text: str) -> None:
        self.response_ready.emit(text)
        self._transition(AppState.SPEAKING)
        self._speak(text)

    def on_speak_done(self) -> None:
        self._listen_timer.stop()
        self._transition(AppState.DISMISS)
        self._dismiss_timer.start(300)

    def on_error(self, msg: str) -> None:
        if self._state in (AppState.IDLE, AppState.DISMISS):
            self.show_card.emit("Saturday", msg)
            log.debug("on_error() while %s: %s", self._state.name, msg)
            return
        self._listen_timer.stop()
        log.error("Error: %s", msg)
        self.error_occurred.emit(msg)
        self.show_card.emit("Error", msg)
        self._transition(AppState.DISMISS)
        self._dismiss_timer.start(500)

    def _on_dismiss_timeout(self) -> None:
        self._transition(AppState.IDLE)

    def _on_listen_timeout(self) -> None:
        if self._state != AppState.LISTENING:
            return
        self._stop_recording()
        self.on_error("I did not hear anything. Check your microphone and try again.")

    def _start_recording(self) -> None:
        if not self.recorder:
            self.on_error("Microphone is not ready yet.")
            return
        try:
            self.recorder.start()
            self._listen_timer.start(12000)
        except Exception as exc:
            self.on_error(f"Microphone error: {exc}")

    def _stop_recording(self) -> None:
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception:
                pass

    def _run_stt(self) -> None:
        if not self.stt:
            self.transcription_result.emit("[STT not available]")
            return

        audio = self.recorder.get_audio() if self.recorder else None
        if audio is None or len(audio) == 0:
            self.on_error("No audio captured.")
            return

        controller = self

        class _STTTask(QRunnable):
            def __init__(self, audio_data):
                super().__init__()
                self._audio = audio_data

            def run(self) -> None:
                try:
                    text = controller.stt.transcribe(self._audio)
                    if text:
                        controller.transcription_result.emit(text)
                    else:
                        controller.recorder_error.emit("Could not understand audio.")
                except Exception as exc:
                    controller.recorder_error.emit(str(exc))

        QThreadPool.globalInstance().start(_STTTask(audio))

    def _run_llm(self, text: str) -> None:
        if not self.agent:
            self.agent_result.emit(f"I heard: '{text}'. The AI is not ready yet.")
            return

        controller = self

        class _AgentTask(QRunnable):
            def __init__(self, query: str):
                super().__init__()
                self._query = query

            def run(self) -> None:
                try:
                    result = controller.agent.run(self._query)
                    controller.agent_result.emit(result)
                except Exception as exc:
                    controller.recorder_error.emit(str(exc))

        QThreadPool.globalInstance().start(_AgentTask(text))

    def _speak(self, text: str) -> None:
        if not self.tts:
            self.speak_done_requested.emit()
            return

        controller = self

        class _TTSTask(QRunnable):
            def __init__(self, spoken_text: str):
                super().__init__()
                self._text = spoken_text

            def run(self) -> None:
                try:
                    controller.tts.speak(self._text)
                except Exception as exc:
                    log.debug("TTS failed: %s", exc)
                finally:
                    controller.speak_done_requested.emit()

        QThreadPool.globalInstance().start(_TTSTask(text))

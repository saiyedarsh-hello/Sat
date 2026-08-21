"""
core/app_controller.py
Central state machine for Saturday.

Two operating modes:
  - STREAMING_MODE (default): always-on mic; each utterance is automatically
    detected, transcribed, and responded to. Hotkey toggles the session.
  - PUSH_TO_TALK_MODE: original behaviour — hotkey activates one-shot
    listen → transcribe → respond cycle.

The mode is selected at startup (streaming by default).
"""

from __future__ import annotations

import logging
from enum import Enum, auto

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

log = logging.getLogger(__name__)


class AppState(Enum):
    IDLE = auto()          # Not active / streaming paused
    LISTENING = auto()     # Actively capturing / waiting for speech
    PROCESSING = auto()    # Transcribing + running LLM
    SPEAKING = auto()      # TTS playing back
    DISMISS = auto()       # Brief dismiss animation before returning to IDLE/LISTENING


class AppController(QObject):
    state_changed       = Signal(object)
    transcription_ready = Signal(str)
    response_ready      = Signal(str)
    action_completed    = Signal(str, bool)
    error_occurred      = Signal(str)
    reminder_fired      = Signal(str, str)
    show_card           = Signal(str, str)
    audio_level         = Signal(float)
    utterance_ready     = Signal(object)  # carries numpy ndarray from StreamRecorder
    subsystems_ready    = Signal()        # fired once all voice/AI subsystems finish loading
    init_progress       = Signal(int, str) # (percentage, status_text) for Glassmorphism progress bar

    # Thread-safe cross-thread signals
    activate_requested      = Signal()
    deactivate_requested    = Signal()
    vad_silence_requested   = Signal()
    recorder_error          = Signal(str)
    transcription_result    = Signal(str)
    agent_result            = Signal(str)
    speak_done_requested    = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = AppState.IDLE
        self._streaming_mode = True   # real-time always-on by default
        self._stream_active = False   # whether streaming session is running

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._on_dismiss_timeout)

        self._listen_timer = QTimer(self)
        self._listen_timer.setSingleShot(True)
        self._listen_timer.timeout.connect(self._on_listen_timeout)

        # Safety watchdog — if Saturday stays in PROCESSING or SPEAKING for
        # more than 30 seconds, force-reset back to LISTENING / IDLE so the
        # user is never permanently locked out.
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.setInterval(30_000)  # 30 seconds
        self._watchdog_timer.timeout.connect(self._on_watchdog_timeout)

        self.activate_requested.connect(self.activate)
        self.deactivate_requested.connect(self.deactivate)
        self.vad_silence_requested.connect(self.on_vad_silence)
        self.recorder_error.connect(self.on_error)
        self.transcription_result.connect(self.on_transcription)
        self.agent_result.connect(self.on_response)
        self.speak_done_requested.connect(self.on_speak_done)
        self.utterance_ready.connect(self.on_stream_utterance)

        # Subsystems (populated by _SubsystemLoader)
        self.recorder        = None   # AudioRecorder (push-to-talk)
        self.stream_recorder = None   # StreamRecorder (real-time)
        self.stt             = None
        self.tts             = None
        self.llm             = None
        self.agent           = None
        self.memory          = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def streaming_mode(self) -> bool:
        return self._streaming_mode

    def set_streaming_mode(self, enabled: bool) -> None:
        """Switch between real-time streaming and push-to-talk."""
        if self._streaming_mode == enabled:
            return
        self._streaming_mode = enabled
        # Stop whatever is running
        if not enabled and self._stream_active:
            self._stop_streaming()
        log.info("Mode: %s", "streaming" if enabled else "push-to-talk")

    # ── Activation ────────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Hotkey pressed — reset any previous unfinished task and start fresh."""
        # Stop any ongoing TTS speech immediately
        if self.tts:
            try:
                self.tts.stop()
            except Exception:
                pass

        # Clear any previous pending question/clarification so a new task begins
        if self.agent:
            self.agent.clear_pending_action()

        if self._streaming_mode:
            self._toggle_streaming()
        else:
            self._push_to_talk_activate()

    def deactivate(self) -> None:
        """Stop everything immediately (speech, recording, pending actions) and return to IDLE."""
        self._listen_timer.stop()
        self._watchdog_timer.stop()
        self._dismiss_timer.stop()

        if self.tts:
            try:
                self.tts.stop()
            except Exception as exc:
                log.debug("Failed to stop TTS: %s", exc)

        if self.agent:
            self.agent.clear_pending_action()

        if self._streaming_mode and self._stream_active:
            self._stop_streaming()
        else:
            self._stop_recording()

        self._transition(AppState.DISMISS)
        QTimer.singleShot(200, lambda: self._transition(AppState.IDLE))


    # ── Streaming mode ────────────────────────────────────────────────────────

    def _toggle_streaming(self) -> None:
        if self._stream_active:
            log.info("Streaming deactivated by hotkey.")
            self._stop_streaming()
            self._transition(AppState.DISMISS)
            QTimer.singleShot(250, lambda: self._transition(AppState.IDLE))
        else:
            self._start_streaming()

    def _start_streaming(self) -> None:
        if not self.stream_recorder:
            # Subsystems still loading — fall back to push-to-talk if recorder exists
            if self.recorder:
                log.info("StreamRecorder not ready yet — falling back to push-to-talk.")
                self._streaming_mode = False  # temporarily
                self._push_to_talk_activate()
                self._streaming_mode = True   # restore after activation
            else:
                # Nothing is ready yet — show the bar (handled in main.py)
                # but don't error-out; the command bar lets the user type instead
                log.info("Voice not ready yet — text input available via CommandBar.")
            return

        self._stream_active = True
        self._transition(AppState.LISTENING)

        try:
            self.stream_recorder.start()
            log.info("Real-time streaming started.")
        except Exception as exc:
            self._stream_active = False
            self.on_error(f"Could not start microphone: {exc}")

    def _stop_streaming(self) -> None:
        self._stream_active = False
        if self.stream_recorder:
            try:
                self.stream_recorder.stop()
            except Exception:
                pass
        log.info("Real-time streaming stopped.")

    def on_stream_utterance(self, audio) -> None:
        """
        Called (via signal) when StreamRecorder detects a complete utterance.
        Runs STT + LLM pipeline without changing _stream_active.
        """
        if not self._stream_active:
            return

        # Pause mic while processing (avoid picking up TTS / processing noise)
        if self.stream_recorder:
            self.stream_recorder.pause()

        self._transition(AppState.PROCESSING)
        self._run_stt_on_audio(audio)

    # ── Push-to-talk mode ─────────────────────────────────────────────────────

    def _push_to_talk_activate(self) -> None:
        if self._state != AppState.IDLE:
            log.debug("activate() ignored; already in %s", self._state.name)
            return
        if not self.recorder:
            self.show_card.emit("Saturday", "Still getting ready. Try again in a moment.")
            return
        self._transition(AppState.LISTENING)
        self._start_recording()

    def on_vad_silence(self) -> None:
        """Called by AudioRecorder when VAD silence detected (push-to-talk)."""
        if self._state != AppState.LISTENING:
            return
        self._listen_timer.stop()
        self._stop_recording()
        self._transition(AppState.PROCESSING)
        self._run_stt()

    # ── Shared transcription / LLM / TTS pipeline ─────────────────────────────

    def text_query(self, text: str) -> None:
        """
        Submit a typed command directly into the LLM pipeline.
        Bypasses voice entirely — safe to call from any thread via signal.
        """
        if not text or not text.strip():
            return
        log.info("PIPELINE: typed command=%r → routing to agent", text[:120])
        self._transition(AppState.PROCESSING)
        self._run_llm(text.strip())

    def on_transcription(self, text: str) -> None:
        if self._state not in (AppState.LISTENING, AppState.PROCESSING):
            log.debug("on_transcription() ignored; state is %s", self._state.name)
            return
        self.transcription_ready.emit(text)
        log.info("PIPELINE: transcribed=%r → routing to agent", text[:120])
        self._run_llm(text)

    def on_response(self, text: str) -> None:
        self.response_ready.emit(text)
        self._transition(AppState.SPEAKING)
        self._speak(text)

    def on_speak_done(self) -> None:
        self._watchdog_timer.stop()
        self._listen_timer.stop()


        # Never auto-close — stay open and listening for the next command.
        # Saturday only closes when the user explicitly presses Escape.
        log.info("Speaking done — staying open in LISTENING state.")
        self._transition(AppState.LISTENING)
        if self._streaming_mode and self.stream_recorder:
            try:
                self.stream_recorder.resume()
            except Exception:
                pass


    def on_error(self, msg: str) -> None:
        self._watchdog_timer.stop()
        # Empty message = silent soft resume (used when audio was too short)
        if not msg:
            if self._streaming_mode and self._stream_active:
                self._transition(AppState.LISTENING)
                if self.stream_recorder:
                    self.stream_recorder.resume()
            return

        if self._state in (AppState.IDLE, AppState.DISMISS):
            self.show_card.emit("Saturday", msg)
            log.debug("on_error() while %s: %s", self._state.name, msg)
            return
        self._listen_timer.stop()
        log.error("Error: %s", msg)
        self.error_occurred.emit(msg)
        self.show_card.emit("Error", msg)

        if self._streaming_mode and self._stream_active:
            # Don't stop streaming on error — just resume listening
            self._transition(AppState.LISTENING)
            if self.stream_recorder:
                self.stream_recorder.resume()
        else:
            self._transition(AppState.DISMISS)
            self._dismiss_timer.start(500)

    # ── Timers ────────────────────────────────────────────────────────────────

    def _on_dismiss_timeout(self) -> None:
        self._transition(AppState.IDLE)

    def _on_listen_timeout(self) -> None:
        if self._state != AppState.LISTENING:
            return
        self._stop_recording()
        self.on_error("I did not hear anything. Check your microphone and try again.")

    # ── Push-to-talk recording helpers ────────────────────────────────────────

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

    # ── STT workers ───────────────────────────────────────────────────────────

    def _run_stt(self) -> None:
        """STT from push-to-talk AudioRecorder buffer."""
        if not self.stt:
            self.transcription_result.emit("[STT not available]")
            return

        audio = self.recorder.get_audio() if self.recorder else None
        if audio is None or len(audio) == 0:
            self.on_error("No audio captured.")
            return

        self._run_stt_on_audio(audio)

    def _run_stt_on_audio(self, audio) -> None:
        """Run STT on an already-captured numpy audio array."""
        if not self.stt:
            self.transcription_result.emit("[STT not available]")
            return

        controller = self

        class _STTTask(QRunnable):
            def __init__(self, audio_data):
                super().__init__()
                self._audio = audio_data

            def run(self) -> None:
                try:
                    text = controller.stt.transcribe(self._audio)
                    if text and text.strip():
                        controller.transcription_result.emit(text)
                    else:
                        # Nothing recognised — resume listening in streaming mode
                        if controller._streaming_mode and controller._stream_active:
                            controller.recorder_error.emit("")  # empty = soft resume
                        else:
                            controller.recorder_error.emit("Could not understand audio.")
                except Exception as exc:
                    controller.recorder_error.emit(str(exc))

        QThreadPool.globalInstance().start(_STTTask(audio))

    # ── LLM worker ────────────────────────────────────────────────────────────

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
                import time
                t0 = time.monotonic()
                try:
                    result = controller.agent.run(self._query)
                    elapsed = time.monotonic() - t0
                    log.info(
                        "PIPELINE: agent result in %.2fs → %r",
                        elapsed, result[:120],
                    )
                    controller.agent_result.emit(result)
                except Exception as exc:
                    controller.recorder_error.emit(str(exc))

        QThreadPool.globalInstance().start(_AgentTask(text))

    # ── TTS worker ────────────────────────────────────────────────────────────

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
                import threading
                import time
                import random

                stop_pulse = threading.Event()

                def _pulse_loop():
                    while not stop_pulse.is_set():
                        lvl = random.uniform(0.35, 0.90)
                        controller.audio_level.emit(lvl)
                        time.sleep(random.uniform(0.04, 0.08))

                pulse_thread = threading.Thread(target=_pulse_loop, daemon=True)
                pulse_thread.start()

                try:
                    controller.tts.speak(self._text)
                except Exception as exc:
                    log.debug("TTS failed: %s", exc)
                finally:
                    stop_pulse.set()
                    controller.audio_level.emit(0.0)
                    controller.speak_done_requested.emit()

        QThreadPool.globalInstance().start(_TTSTask(text))

    # ── Safety watchdog ───────────────────────────────────────────────────────

    def _on_watchdog_timeout(self) -> None:
        """Force-reset the state machine if stuck in PROCESSING or SPEAKING."""
        log.warning(
            "Watchdog fired: state=%s has been stuck — force-resetting to LISTENING/IDLE.",
            self._state.name,
        )
        if self._streaming_mode and self._stream_active:
            self._transition(AppState.LISTENING)
            if self.stream_recorder:
                try:
                    self.stream_recorder.resume()
                except Exception:
                    pass
        else:
            self._transition(AppState.DISMISS)
            QTimer.singleShot(300, lambda: self._transition(AppState.IDLE))

    # ── State helper ──────────────────────────────────────────────────────────

    def _transition(self, new_state: AppState) -> None:
        if self._state == new_state:
            return
        log.debug("State: %s -> %s", self._state.name, new_state.name)
        self._state = new_state
        self.state_changed.emit(new_state)

        # Start watchdog when entering a "busy" state; cancel on safe states
        if new_state in (AppState.PROCESSING, AppState.SPEAKING):
            self._watchdog_timer.start()
        else:
            self._watchdog_timer.stop()

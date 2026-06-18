"""
main.py
Saturday — entry point.
Bootstraps the Qt application, system tray, global hotkey,
all subsystems, and wires everything to AppController signals.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# ── Logging setup (before any imports that might log) ────────────────────────
_APP_DATA = Path(os.getenv("APPDATA", Path.home())) / "Saturday"
_APP_DATA.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _APP_DATA / "saturday.log"

_root_log = logging.getLogger()
_root_log.setLevel(logging.DEBUG)

_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
)
_file_handler.setLevel(logging.DEBUG)
_root_log.addHandler(_file_handler)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s — %(message)s"))
_console_handler.setLevel(logging.INFO)
_root_log.addHandler(_console_handler)

log = logging.getLogger("saturday.main")

# ── Qt must be imported after logging ─────────────────────────────────────────
from PySide6.QtCore import Qt, QTimer, QThreadPool, QRunnable
from PySide6.QtGui import QIcon, QAction, QPixmap, QColor, QPainter
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from config import config
from database import initialize as db_init
from core import AppController, AppState
from ui import OverlayWidget, OrbWidget, WaveformWidget, CardManager, SettingsPanel


# ── Tray icon generator (no asset file needed) ────────────────────────────────

def _make_tray_icon(color: str = "#6C63FF", size: int = 64) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)
    painter.end()
    return QIcon(px)


_TRAY_COLORS = {
    AppState.IDLE:       "#6C63FF",
    AppState.LISTENING:  "#818CF8",
    AppState.PROCESSING: "#F59E0B",
    AppState.SPEAKING:   "#34D399",
    AppState.DISMISS:    "#6C63FF",
}


# ── Startup registry ──────────────────────────────────────────────────────────

def _register_startup(enabled: bool) -> None:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path,
            0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        )
        app_name = "Saturday"
        exe = sys.executable
        script = str(Path(__file__).resolve())
        value = f'"{exe}" "{script}"'

        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, value)
            log.info("Auto-startup enabled.")
        else:
            try:
                winreg.DeleteValue(key, app_name)
                log.info("Auto-startup disabled.")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as exc:
        log.warning("Could not set startup registry: %s", exc)


# ── Background loader ─────────────────────────────────────────────────────────

class _SubsystemLoader(QRunnable):
    """Load heavy subsystems in a background thread so UI starts instantly."""

    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self._ctrl = controller

    def run(self) -> None:
        from voice import AudioRecorder, STTEngine, TTSEngine
        from ai import LLMClient, Agent
        from memory import MemoryManager
        from automation import AppControl, FileOps, BrowserControl, SystemActions, ReminderEngine

        ctrl = self._ctrl

        # Memory
        mem = MemoryManager()
        mem.load()
        ctrl.memory = mem

        # TTS
        tts = TTSEngine()
        tts.load()
        ctrl.tts = tts

        # STT
        stt = STTEngine()
        stt.load()
        ctrl.stt = stt

        # Automation
        app_ctrl = AppControl()
        file_ops = FileOps()
        browser  = BrowserControl()
        system   = SystemActions()

        def _reminder_callback(title: str, body: str) -> None:
            ctrl.reminder_fired.emit(title, body)

        reminders = ReminderEngine(fire_callback=_reminder_callback)
        reminders.start()

        # LLM + Agent
        llm = LLMClient()
        agent = Agent(
            llm=llm,
            memory=mem,
            app_control=app_ctrl,
            file_ops=file_ops,
            browser=browser,
            system=system,
            reminders=reminders,
        )
        ctrl.agent = agent

        # Recorder (needs VAD silence → controller callback)
        def _on_level(level: float) -> None:
            ctrl.audio_level.emit(level)

        def _on_silence() -> None:
            ctrl.vad_silence_requested.emit()

        def _on_recorder_error(message: str) -> None:
            ctrl.recorder_error.emit(message)

        recorder = AudioRecorder(
            level_callback=_on_level,
            silence_callback=_on_silence,
            error_callback=_on_recorder_error,
            silence_threshold_ms=config.get("voice", "silence_threshold_ms", default=1200),
            vad_aggressiveness=config.get("voice", "vad_aggressiveness", default=2),
            device=config.get("voice", "input_device", default=None),
        )
        ctrl.recorder = recorder

        log.info("All subsystems loaded.")


# ── Hotkey listener ───────────────────────────────────────────────────────────

def _start_hotkey(hotkey_str: str, callback) -> None:
    """Start a global hotkey listener in a daemon thread."""
    import threading
    def _listen():
        try:
            import keyboard
            keyboard.add_hotkey(hotkey_str, callback)
            log.info("Hotkey registered: %s", hotkey_str)
            keyboard.wait()
        except Exception as exc:
            log.warning("Hotkey listener error: %s", exc)
    t = threading.Thread(target=_listen, daemon=True)
    t.start()


# ── Main application class ────────────────────────────────────────────────────

class SaturdayApp:
    def __init__(self) -> None:
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("Saturday")
        self.app.setApplicationVersion("1.0.0")

        # Load config + DB
        config.load()
        db_init()

        # Core controller
        self.controller = AppController()

        # UI components
        self.overlay   = OverlayWidget()
        self.orb       = OrbWidget()
        self.waveform  = WaveformWidget()
        self.cards     = CardManager(
            duration_ms=config.get("auto_dismiss_seconds", default=4) * 1000
        )
        self.settings  = SettingsPanel()

        # Tray
        self._build_tray()

        # Wire signals
        self._connect_signals()

        # Startup registry
        if config.get("auto_startup", default=True):
            _register_startup(True)

        # Load heavy subsystems in background
        QThreadPool.globalInstance().start(_SubsystemLoader(self.controller))

        # Global hotkey
        hotkey = config.get("hotkey", default="ctrl+space")
        _start_hotkey(hotkey, self._on_hotkey)
        _start_hotkey("esc", self._on_esc)

        log.info("Saturday started. Hotkey: %s", hotkey)

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(_make_tray_icon())
        self.tray.setToolTip("Saturday — AI Assistant\nCtrl+Space to activate")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #0A0A14;
                color: #F0F0FF;
                border: 1px solid rgba(108,99,255,0.4);
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI';
                font-size: 13px;
            }
            QMenu::item { padding: 8px 20px; border-radius: 4px; }
            QMenu::item:selected { background: rgba(108,99,255,0.3); }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.1); margin: 4px 10px; }
        """)

        act_activate = QAction("🎙  Activate Saturday", self.app)
        act_activate.triggered.connect(self.controller.activate_requested.emit)
        menu.addAction(act_activate)

        menu.addSeparator()

        act_settings = QAction("⚙  Settings", self.app)
        act_settings.triggered.connect(self.settings.show)
        menu.addAction(act_settings)

        act_log = QAction("📋  Open Log", self.app)
        act_log.triggered.connect(lambda: os.startfile(str(_LOG_FILE)))
        menu.addAction(act_log)

        menu.addSeparator()

        act_quit = QAction("✕  Quit Saturday", self.app)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        ctrl = self.controller

        ctrl.state_changed.connect(self.overlay.on_state_changed)
        ctrl.state_changed.connect(self.orb.on_state_changed)
        ctrl.state_changed.connect(self.waveform.on_state_changed)
        ctrl.state_changed.connect(self._on_state_changed)

        ctrl.audio_level.connect(self.orb.on_audio_level)
        ctrl.audio_level.connect(self.waveform.on_audio_level)

        ctrl.transcription_ready.connect(
            lambda text: self.cards.show("I heard", text)
        )
        ctrl.show_card.connect(self.cards.show)
        ctrl.reminder_fired.connect(
            lambda t, b: (
                self.cards.show(f"⏰ {t}", b),
                self.tray.showMessage(t, b, QSystemTrayIcon.MessageIcon.Information, 5000),
            )
        )
        ctrl.response_ready.connect(
            lambda text: self.cards.show("Saturday", text)
        )
        ctrl.error_occurred.connect(
            lambda msg: self.cards.show("Error", msg)
        )

        self.settings.settings_saved.connect(self._on_settings_saved)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_hotkey(self) -> None:
        # Called from background thread — schedule on Qt main thread
        self.controller.activate_requested.emit()

    def _on_esc(self) -> None:
        # Called from background thread — schedule on Qt main thread
        if self.controller.state != AppState.IDLE:
            log.info("Escape pressed, deactivating Saturday.")
            self.controller.deactivate_requested.emit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.controller.activate_requested.emit()

    def _on_state_changed(self, state: AppState) -> None:
        self.tray.setIcon(_make_tray_icon(_TRAY_COLORS.get(state, "#6C63FF")))
        if state == AppState.DISMISS:
            self.cards.dismiss_all()
        tooltips = {
            AppState.IDLE:       "Saturday — Idle  (Ctrl+Space to activate)",
            AppState.LISTENING:  "Saturday — Listening…",
            AppState.PROCESSING: "Saturday — Thinking…",
            AppState.SPEAKING:   "Saturday — Speaking…",
            AppState.DISMISS:    "Saturday — Done",
        }
        self.tray.setToolTip(tooltips.get(state, "Saturday"))

    def _on_settings_saved(self) -> None:
        _register_startup(config.get("auto_startup", default=True))
        if self.controller.tts:
            self.controller.tts.reload_settings()

        # (Re)initialize LLM + Agent whenever settings change so a freshly-entered
        # API key is picked up immediately without restarting Saturday.
        def _reinit_agent():
            try:
                from ai import LLMClient, Agent
                from automation import AppControl, FileOps, BrowserControl, SystemActions, ReminderEngine

                llm = LLMClient()

                # Reuse existing subsystems if already loaded, else create stubs
                mem       = self.controller.memory
                app_ctrl  = AppControl()
                file_ops  = FileOps()
                browser   = BrowserControl()
                system    = SystemActions()

                # Reuse existing reminder engine if running
                if self.controller.agent and hasattr(self.controller.agent, '_reminders'):
                    reminders = self.controller.agent._reminders
                else:
                    def _reminder_cb(title: str, body: str) -> None:
                        self.controller.reminder_fired.emit(title, body)
                    reminders = ReminderEngine(fire_callback=_reminder_cb)
                    reminders.start()

                self.controller.agent = Agent(
                    llm=llm,
                    memory=mem,
                    app_control=app_ctrl,
                    file_ops=file_ops,
                    browser=browser,
                    system=system,
                    reminders=reminders,
                )
                log.info("Agent (re)initialized with updated settings.")
            except Exception as exc:
                log.error("Failed to reinitialize agent: %s", exc)

        QThreadPool.globalInstance().start(
            type("_Task", (QRunnable,), {"run": lambda self: _reinit_agent()})()
        )
        log.info("Settings applied.")

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self) -> None:
        log.info("Saturday shutting down.")
        self.controller.deactivate()
        if self.controller.recorder:
            self.controller.recorder.stop()
        from automation import ReminderEngine
        # stop reminder scheduler if available
        if self.controller.agent and hasattr(self.controller.agent, '_reminders'):
            r = self.controller.agent._reminders
            if r:
                r.stop()
        self.tray.hide()
        self.app.quit()

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> int:
        return self.app.exec()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Allow --test-ui flag to skip subsystem loading
    test_ui = "--test-ui" in sys.argv

    saturday = SaturdayApp()

    if test_ui:
        log.info("--test-ui mode: rendering UI without audio hardware.")
        # Show settings panel for visual inspection
        QTimer.singleShot(500, saturday.settings.show)

    sys.exit(saturday.run())


if __name__ == "__main__":
    main()

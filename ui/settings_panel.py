"""
ui/settings_panel.py
Settings window — API key, voice config, memory, startup options.
Frameless acrylic-style panel centered on screen.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSlider, QCheckBox, QTabWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QScrollArea,
    QFrame, QApplication
)

from config import config

log = logging.getLogger(__name__)

# ── Stylesheet ────────────────────────────────────────────────────────────────
_STYLE = """
QWidget {
    background: transparent;
    color: #F0F0FF;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(108,99,255,0.4);
    border-radius: 8px;
    padding: 6px 10px;
    color: #F0F0FF;
    selection-background-color: #6C63FF;
}
QLineEdit:focus, QComboBox:focus {
    border-color: #A78BFA;
}
QComboBox::drop-down { border: none; }
QComboBox::down-arrow { image: none; width: 12px; }
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #6C63FF, stop:1 #A78BFA);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 600;
}
QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 #7C74FF, stop:1 #B79BFB); }
QPushButton:pressed { background: #5A52EE; }
QPushButton#danger {
    background: rgba(248,113,113,0.8);
}
QPushButton#secondary {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
}
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255,255,255,0.15);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #A78BFA;
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal { background: #6C63FF; border-radius: 2px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 1px solid rgba(108,99,255,0.5);
    border-radius: 4px;
    background: rgba(255,255,255,0.05);
}
QCheckBox::indicator:checked {
    background: #6C63FF;
    border-color: #6C63FF;
}
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: rgba(255,255,255,0.05);
    color: rgba(240,240,255,0.55);
    padding: 8px 18px;
    border-radius: 8px 8px 0 0;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: rgba(108,99,255,0.3);
    color: #F0F0FF;
}
QGroupBox {
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    color: rgba(167,139,250,0.9);
    font-weight: 600;
}
QScrollArea { border: none; }
QScrollBar:vertical {
    background: rgba(255,255,255,0.04);
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(108,99,255,0.5);
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class SettingsPanel(QWidget):
    """Main settings window."""

    settings_saved = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(580, 650)
        self._center()
        self.setStyleSheet(_STYLE)
        self._build_ui()
        self._load_values()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(52)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(20, 0, 12, 0)

        icon_lbl = QLabel("⚙  Saturday Settings")
        icon_lbl.setStyleSheet(
            "font-family: 'Outfit','Segoe UI'; font-size: 15px; "
            "font-weight: 700; color: #F0F0FF;"
        )
        tb_layout.addWidget(icon_lbl)
        tb_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setObjectName("secondary")
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.06);border:none;"
            "border-radius:16px;color:#F0F0FF;font-size:13px;}"
            "QPushButton:hover{background:rgba(248,113,113,0.7);}"
        )
        close_btn.clicked.connect(self.hide)
        tb_layout.addWidget(close_btn)
        outer.addWidget(title_bar)

        # Tabs
        self._tabs = QTabWidget()
        outer.addWidget(self._tabs)

        self._build_ai_tab()
        self._build_voice_tab()
        self._build_memory_tab()
        self._build_system_tab()

        # Save button
        save_row = QHBoxLayout()
        save_row.setContentsMargins(20, 10, 20, 16)
        save_row.addStretch()
        save_btn = QPushButton("  Save Settings")
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        outer.addLayout(save_row)

    # ── AI Tab ────────────────────────────────────────────────────────────────

    def _build_ai_tab(self) -> None:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        inner = QWidget()
        tab.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Ollama status badge ────────────────────────────────────────────────
        self._ollama_status = QLabel("⬤  Ollama status: checking…")
        self._ollama_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ollama_status.setStyleSheet(
            "background: rgba(255,255,255,0.06);"
            "border: 1px solid rgba(255,255,255,0.12);"
            "border-radius: 8px;"
            "color: rgba(240,240,255,0.6);"
            "font-size: 13px; font-weight: 600;"
            "padding: 10px 16px;"
        )
        layout.addWidget(self._ollama_status)

        # ── Ollama connection group ────────────────────────────────────────────
        conn_grp = QGroupBox("Ollama Connection")
        conn_form = QFormLayout(conn_grp)
        conn_form.setSpacing(10)

        url_row = QHBoxLayout()
        self._ollama_url_edit = QLineEdit()
        self._ollama_url_edit.setPlaceholderText("http://localhost:11434")
        url_row.addWidget(self._ollama_url_edit, 1)

        test_btn = QPushButton("Test")
        test_btn.setFixedWidth(70)
        test_btn.setFixedHeight(34)
        test_btn.setStyleSheet(
            "QPushButton { background: rgba(108,99,255,0.25);"
            "border: 1px solid rgba(108,99,255,0.5);"
            "border-radius: 8px; color: #A78BFA; font-weight: 600; padding: 0; }"
            "QPushButton:hover { background: rgba(108,99,255,0.45); }"
        )
        test_btn.clicked.connect(self._test_ollama)
        url_row.addWidget(test_btn)

        conn_form.addRow("Server URL:", url_row)

        # Model selector + refresh
        model_row = QHBoxLayout()
        self._ollama_model_combo = QComboBox()
        self._ollama_model_combo.setEditable(True)
        self._ollama_model_combo.setPlaceholderText("e.g. llama3.1")
        model_row.addWidget(self._ollama_model_combo, 1)

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(40)
        refresh_btn.setFixedHeight(34)
        refresh_btn.setToolTip("Fetch available models from Ollama")
        refresh_btn.setStyleSheet(
            "QPushButton { background: rgba(108,99,255,0.25);"
            "border: 1px solid rgba(108,99,255,0.5);"
            "border-radius: 8px; color: #A78BFA; font-size: 15px; }"
            "QPushButton:hover { background: rgba(108,99,255,0.45); }"
        )
        refresh_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(refresh_btn)

        conn_form.addRow("Model:", model_row)

        hint = QLabel("Click ↻ to load models from your local Ollama server.")
        hint.setStyleSheet("color: rgba(240,240,255,0.45); font-size: 11px;")
        conn_form.addRow("", hint)

        layout.addWidget(conn_grp)

        # ── Generation settings ────────────────────────────────────────────────
        gen_grp = QGroupBox("Generation")
        gen_form = QFormLayout(gen_grp)
        gen_form.setSpacing(10)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.1)
        gen_form.addRow("Temperature:", self._temp_spin)

        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(128, 8192)
        self._max_tokens_spin.setSingleStep(128)
        gen_form.addRow("Max Tokens:", self._max_tokens_spin)

        layout.addWidget(gen_grp)
        layout.addStretch()
        self._tabs.addTab(tab, "🤖  AI")

        # Trigger status check after UI is built
        QTimer.singleShot(400, self._test_ollama)

    # ── Ollama helpers ────────────────────────────────────────────────────────

    def _set_ollama_status(self, ok: bool, detail: str = "") -> None:
        """Update the status badge on the main thread."""
        if ok:
            self._ollama_status.setText("⬤  Ollama connected ✓" + (f"  —  {detail}" if detail else ""))
            self._ollama_status.setStyleSheet(
                "background: rgba(52,211,153,0.12);"
                "border: 1px solid rgba(52,211,153,0.4);"
                "border-radius: 8px;"
                "color: #34D399;"
                "font-size: 13px; font-weight: 600;"
                "padding: 10px 16px;"
            )
        else:
            self._ollama_status.setText("⬤  Ollama not reachable" + (f"  —  {detail}" if detail else ""))
            self._ollama_status.setStyleSheet(
                "background: rgba(248,113,113,0.10);"
                "border: 1px solid rgba(248,113,113,0.35);"
                "border-radius: 8px;"
                "color: #F87171;"
                "font-size: 13px; font-weight: 600;"
                "padding: 10px 16px;"
            )

    def _test_ollama(self) -> None:
        """Ping Ollama in a thread — never blocks the UI."""
        url = self._ollama_url_edit.text().strip() or "http://localhost:11434"
        self._ollama_status.setText("⬤  Ollama status: checking…")
        self._ollama_status.setStyleSheet(
            "background: rgba(255,255,255,0.06);"
            "border: 1px solid rgba(255,255,255,0.12);"
            "border-radius: 8px;"
            "color: rgba(240,240,255,0.6);"
            "font-size: 13px; font-weight: 600;"
            "padding: 10px 16px;"
        )

        def _check():
            try:
                import urllib.request, json
                req = urllib.request.Request(
                    f"{url}/api/tags",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                count  = len(models)
                QTimer.singleShot(0, lambda: self._on_ollama_ok(models, f"{count} model{'s' if count != 1 else ''} found"))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._set_ollama_status(False, str(exc)[:60]))

        threading.Thread(target=_check, daemon=True).start()

    def _on_ollama_ok(self, models: list[str], detail: str) -> None:
        self._set_ollama_status(True, detail)
        self._populate_models(models)

    def _fetch_models(self) -> None:
        """Refresh model list from Ollama."""
        url = self._ollama_url_edit.text().strip() or "http://localhost:11434"

        def _get():
            try:
                import urllib.request, json
                with urllib.request.urlopen(f"{url}/api/tags", timeout=4) as r:
                    data   = json.loads(r.read())
                    models = [m["name"] for m in data.get("models", [])]
                QTimer.singleShot(0, lambda: self._populate_models(models))
            except Exception as exc:
                log.warning("Fetch models failed: %s", exc)

        threading.Thread(target=_get, daemon=True).start()

    def _populate_models(self, models: list[str]) -> None:
        """Fill the model combo from Ollama /api/tags response."""
        current = self._ollama_model_combo.currentText()
        self._ollama_model_combo.clear()
        if models:
            self._ollama_model_combo.addItems(models)
        # Restore selection if still present
        idx = self._ollama_model_combo.findText(current)
        if idx >= 0:
            self._ollama_model_combo.setCurrentIndex(idx)
        elif current:
            self._ollama_model_combo.setEditText(current)


    # ── Voice Tab ─────────────────────────────────────────────────────────────

    def _build_voice_tab(self) -> None:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        inner = QWidget()
        tab.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # TTS group
        tts_grp = QGroupBox("Text-to-Speech")
        tts_form = QFormLayout(tts_grp)
        tts_form.setSpacing(10)

        self._tts_rate_slider = QSlider(Qt.Orientation.Horizontal)
        self._tts_rate_slider.setRange(80, 300)
        self._tts_rate_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._tts_rate_label = QLabel("175 wpm")
        self._tts_rate_slider.valueChanged.connect(
            lambda v: self._tts_rate_label.setText(f"{v} wpm")
        )
        rate_row = QHBoxLayout()
        rate_row.addWidget(self._tts_rate_slider)
        rate_row.addWidget(self._tts_rate_label)
        tts_form.addRow("Speech Rate:", rate_row)

        self._tts_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._tts_volume_slider.setRange(0, 100)
        self._tts_volume_label = QLabel("100%")
        self._tts_volume_slider.valueChanged.connect(
            lambda v: self._tts_volume_label.setText(f"{v}%")
        )
        vol_row = QHBoxLayout()
        vol_row.addWidget(self._tts_volume_slider)
        vol_row.addWidget(self._tts_volume_label)
        tts_form.addRow("Volume:", vol_row)

        test_btn = QPushButton("▶  Test Voice")
        test_btn.clicked.connect(self._test_tts)
        tts_form.addRow("", test_btn)
        layout.addWidget(tts_grp)

        # STT group
        stt_grp = QGroupBox("Speech Recognition")
        stt_form = QFormLayout(stt_grp)
        stt_form.setSpacing(10)

        self._stt_model_combo = QComboBox()
        self._stt_model_combo.addItems(["tiny.en", "base.en", "small.en", "medium.en"])
        stt_form.addRow("Whisper Model:", self._stt_model_combo)

        self._stt_device_combo = QComboBox()
        self._stt_device_combo.addItems(["cpu", "cuda"])
        stt_form.addRow("Device:", self._stt_device_combo)

        layout.addWidget(stt_grp)
        layout.addStretch()
        self._tabs.addTab(tab, "🎙  Voice")

    # ── Memory Tab ────────────────────────────────────────────────────────────

    def _build_memory_tab(self) -> None:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        inner = QWidget()
        tab.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        mem_grp = QGroupBox("Memory Settings")
        mem_form = QFormLayout(mem_grp)
        mem_form.setSpacing(10)

        self._short_term_spin = QSpinBox()
        self._short_term_spin.setRange(5, 100)
        mem_form.addRow("Short-term buffer size:", self._short_term_spin)

        clear_btn = QPushButton("🗑  Clear All Memories")
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(self._clear_memories)
        mem_form.addRow("", clear_btn)

        layout.addWidget(mem_grp)
        layout.addStretch()
        self._tabs.addTab(tab, "🧠  Memory")

    # ── System Tab ────────────────────────────────────────────────────────────

    def _build_system_tab(self) -> None:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        inner = QWidget()
        tab.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        sys_grp = QGroupBox("System")
        sys_form = QFormLayout(sys_grp)
        sys_form.setSpacing(10)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("e.g. ctrl+space")
        sys_form.addRow("Activation Hotkey:", self._hotkey_edit)

        self._auto_startup_chk = QCheckBox("Launch Saturday on Windows login")
        sys_form.addRow("", self._auto_startup_chk)

        self._animations_chk = QCheckBox("Enable animations")
        sys_form.addRow("", self._animations_chk)

        self._waveform_chk = QCheckBox("Show waveform visualizer")
        sys_form.addRow("", self._waveform_chk)

        self._dismiss_spin = QSpinBox()
        self._dismiss_spin.setRange(1, 30)
        self._dismiss_spin.setSuffix(" seconds")
        sys_form.addRow("Card auto-dismiss:", self._dismiss_spin)

        layout.addWidget(sys_grp)

        # Voice mode group
        voice_mode_grp = QGroupBox("Voice Mode")
        voice_mode_form = QFormLayout(voice_mode_grp)
        voice_mode_form.setSpacing(10)

        self._streaming_mode_chk = QCheckBox("Real-time always-on listening (recommended)")
        self._streaming_mode_chk.setToolTip(
            "When enabled: press hotkey once to start listening continuously.\n"
            "Saturday detects your voice automatically and responds immediately.\n"
            "When disabled: push-to-talk — press hotkey each time to speak."
        )
        voice_mode_form.addRow("", self._streaming_mode_chk)

        mode_info = QLabel(
            "🎤  Real-time: hotkey starts session, Saturday listens continuously\n"
            "🔴  Push-to-talk: press hotkey each time you want to speak"
        )
        mode_info.setStyleSheet(
            "color: rgba(240,240,255,0.5);"
            "font-size: 11px;"
            "padding: 4px;"
        )
        voice_mode_form.addRow("", mode_info)

        layout.addWidget(voice_mode_grp)
        layout.addStretch()
        self._tabs.addTab(tab, "⚙  System")

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load_values(self) -> None:
        self._ollama_url_edit.setText(
            config.get("ai", "ollama_base_url", default="http://localhost:11434")
        )
        saved_model = config.get("ai", "model", default="llama3.1")
        self._ollama_model_combo.setEditText(saved_model)

        self._temp_spin.setValue(config.get("ai", "temperature", default=0.7))
        self._max_tokens_spin.setValue(config.get("ai", "max_tokens", default=1024))

        self._tts_rate_slider.setValue(config.get("voice", "tts_rate", default=175))
        self._tts_volume_slider.setValue(int(config.get("voice", "tts_volume", default=1.0) * 100))
        self._stt_model_combo.setCurrentText(config.get("voice", "stt_model", default="base.en"))
        self._stt_device_combo.setCurrentText(config.get("voice", "stt_device", default="cpu"))

        self._short_term_spin.setValue(config.get("memory", "short_term_max", default=20))
        self._hotkey_edit.setText(config.get("hotkey", default="ctrl+space"))
        self._auto_startup_chk.setChecked(config.get("auto_startup", default=True))
        self._animations_chk.setChecked(config.get("ui", "animations_enabled", default=True))
        self._waveform_chk.setChecked(config.get("ui", "show_waveform", default=True))
        self._dismiss_spin.setValue(config.get("auto_dismiss_seconds", default=4))
        self._streaming_mode_chk.setChecked(config.get("voice", "streaming_mode", default=True))

    def _save(self) -> None:
        url   = self._ollama_url_edit.text().strip() or "http://localhost:11434"
        model = self._ollama_model_combo.currentText().strip() or "llama3.1"

        config.set("ai", "provider",         "ollama")
        config.set("ai", "ollama_base_url",  url)
        config.set("ai", "openai_base_url",  url.rstrip("/") + "/v1")
        config.set("ai", "model",            model)
        config.set("ai", "api_key",          "")
        config.set("ai", "temperature",      self._temp_spin.value())
        config.set("ai", "max_tokens",       self._max_tokens_spin.value())

        config.set("voice", "tts_rate",      self._tts_rate_slider.value())
        config.set("voice", "tts_volume",    self._tts_volume_slider.value() / 100.0)
        config.set("voice", "stt_model",     self._stt_model_combo.currentText())
        config.set("voice", "stt_device",    self._stt_device_combo.currentText())
        config.set("voice", "streaming_mode",self._streaming_mode_chk.isChecked())

        config.set("memory", "short_term_max", self._short_term_spin.value())
        config.set("hotkey",                 self._hotkey_edit.text().strip())
        config.set("auto_startup",           self._auto_startup_chk.isChecked())
        config.set("ui", "animations_enabled",self._animations_chk.isChecked())
        config.set("ui", "show_waveform",    self._waveform_chk.isChecked())
        config.set("auto_dismiss_seconds",   self._dismiss_spin.value())

        config.save()
        self.settings_saved.emit()
        log.info("Settings saved — Ollama @ %s, model=%s", url, model)
        self.hide()



    def _test_tts(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._tts_rate_slider.value())
            engine.setProperty("volume", self._tts_volume_slider.value() / 100.0)
            engine.say("Hello! I am Saturday, your AI assistant.")
            engine.runAndWait()
        except Exception as e:
            log.error("TTS test failed: %s", e)

    def _clear_memories(self) -> None:
        try:
            from database import models
            from database.db import get_connection
            conn = get_connection()
            conn.execute("DELETE FROM memories")
            conn.commit()
            log.info("All memories cleared.")
        except Exception as e:
            log.error("Clear memories failed: %s", e)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 18, 18)

        # Glass background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 10, 24, 240))
        painter.drawPath(path)

        # Border
        from PySide6.QtGui import QPen
        painter.setPen(QPen(QColor(108, 99, 255, 60), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.end()

    # ── Drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ── Center ────────────────────────────────────────────────────────────────

    def _center(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

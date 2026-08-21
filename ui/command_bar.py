"""
ui/command_bar.py
Minimal all-black assistant window — Saturday name, AI question/response display,
properly padded text input, and Send button.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, Signal,
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath,
    QPen, QFont, QKeyEvent, QBrush,
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QLabel, QApplication,
)

from core.app_controller import AppState

log = logging.getLogger(__name__)

_STYLE = """
QWidget#AssistantWindow {
    background: transparent;
}

QLineEdit#CommandInput {
    background: #111111;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    padding: 9px 14px;
    color: #FFFFFF;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 15px;
    selection-background-color: #333333;
}
QLineEdit#CommandInput:focus {
    border: 1px solid #555555;
    background: #161616;
}

QPushButton#SendBtn {
    background: #1a1a1a;
    color: #FFFFFF;
    border: 1px solid #333333;
    border-radius: 10px;
    padding: 9px 24px;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 14px;
    font-weight: 600;
    min-width: 65px;
}
QPushButton#SendBtn:hover {
    background: #252525;
    border-color: #555555;
}
QPushButton#SendBtn:pressed {
    background: #0f0f0f;
}
QPushButton#SendBtn:disabled {
    color: #444444;
    border-color: #222222;
}

QLabel#TitleLabel {
    color: #FFFFFF;
    font-family: 'Segoe UI', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

QLabel#ResponseLabel {
    color: #E2E8F0;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13.5px;
    background: #0c0c0c;
    border: 1px solid #222222;
    border-radius: 8px;
    padding: 9px 13px;
}
"""

_WINDOW_W = 560
_RADIUS   = 14


class CommandBar(QWidget):
    """Minimal black command bar — name, AI question/response, text input, Send."""

    text_submitted = Signal(str)
    dismissed      = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setObjectName("AssistantWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)

        self._voice_active = False
        self._state        = AppState.IDLE
        self._is_ready     = False

        self._build_ui()
        self._update_window_size()

        # Slide-in / fade-out animations
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(260)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.finished.connect(self._on_slide_done)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(200)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_done)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(18, 14, 18, 14)
        self._root_layout.setSpacing(10)

        # ── Title ─────────────────────────────────────────────────────────────
        self._title_lbl = QLabel("Saturday")
        self._title_lbl.setObjectName("TitleLabel")
        self._root_layout.addWidget(self._title_lbl)

        # ── AI Question / Response Message Label (visible when AI responds/asks)
        self._reply_lbl = QLabel("")
        self._reply_lbl.setObjectName("ResponseLabel")
        self._reply_lbl.setWordWrap(True)
        self._reply_lbl.hide()
        self._root_layout.addWidget(self._reply_lbl)

        # ── Input row ─────────────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setObjectName("CommandInput")
        self._input.setPlaceholderText("Type a command or reply…")
        self._input.returnPressed.connect(self._on_submit)
        self._input.textChanged.connect(lambda t: self._send_btn.setEnabled(bool(t.strip())))
        self._input.installEventFilter(self)
        row.addWidget(self._input, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("SendBtn")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_submit)
        row.addWidget(self._send_btn, 0)

        self._root_layout.addLayout(row)

    def _update_window_size(self) -> None:
        """Dynamically size window so letters and any AI question fit with no clipping."""
        h = 110
        if self._reply_lbl.isVisible() and self._reply_lbl.text().strip():
            h = 165
        self.setFixedSize(_WINDOW_W, h)
        self._reposition()
        self.update()

    # ── Public API ────────────────────────────────────────────────────────────

    def on_init_progress(self, percent: int, status_text: str) -> None:
        pass

    def set_voice_loading(self) -> None:
        self._is_ready = False

    def set_voice_ready(self) -> None:
        self._is_ready = True

    def on_state_changed(self, state: AppState) -> None:
        self._state = state
        if state in (AppState.LISTENING, AppState.IDLE):
            if self.isVisible():
                QTimer.singleShot(100, self._input.setFocus)

    def on_audio_level(self, level: float) -> None:
        pass

    def show_response(self, text: str) -> None:
        """Display questions or answers asked by Saturday."""
        if text and text.strip():
            self._reply_lbl.setText(text.strip())
            self._reply_lbl.show()
            self._input.setEnabled(True)
            self._update_window_size()
            if not self.is_active:
                self.activate()
            else:
                QTimer.singleShot(100, self._input.setFocus)

    @property
    def is_active(self) -> bool:
        return self.isVisible() and self.windowOpacity() > 0.1

    def clear(self) -> None:
        """Reset text input and response display for a fresh task."""
        self._input.clear()
        self._send_btn.setEnabled(False)
        self._reply_lbl.hide()
        self._reply_lbl.setText("")
        self._update_window_size()

    # ── Show / Hide ───────────────────────────────────────────────────────────

    def activate(self) -> None:
        self.clear()
        self._update_window_size()
        self._fade_anim.stop()
        self._slide_anim.stop()
        screen = QApplication.primaryScreen().availableGeometry()
        start = QPoint(self.pos().x(), screen.bottom() + 20)
        end   = self.pos()
        self.move(start)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self._slide_anim.setStartValue(start)
        self._slide_anim.setEndValue(end)
        self._slide_anim.start()
        # Focus set again in _on_slide_done after animation completes

    def _on_slide_done(self) -> None:
        """After slide-in animation: ensure keyboard focus is on the input."""
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def deactivate(self) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_done(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        self._reply_lbl.hide()
        self._reply_lbl.setText("")
        self._update_window_size()
        self.dismissed.emit()

    # ── Submit ────────────────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        log.info("CommandBar submitted: %r", text)
        self._input.clear()
        self._send_btn.setEnabled(False)
        self.text_submitted.emit(text)

    # ── Position ──────────────────────────────────────────────────────────────

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - self.width() // 2
        y = screen.center().y() - self.height() // 2 - 60
        self.move(x, y)

    # ── Paint — pure black rounded rect ──────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, _RADIUS, _RADIUS)

        # Solid black fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 252)))
        painter.drawPath(path)

        # Subtle dark border
        painter.setPen(QPen(QColor(50, 50, 50, 200), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.end()

    # ── Key events ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.deactivate()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.deactivate()
        else:
            super().keyPressEvent(event)


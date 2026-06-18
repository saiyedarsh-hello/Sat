"""
ui/overlay.py
Full-screen translucent dimming layer shown when Saturday is active.
Sits above all windows (always-on-top) but passes mouse events through so the
user can still interact with the desktop if needed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QApplication

from core.app_controller import AppState


class OverlayWidget(QWidget):
    """Full-screen semi-transparent dim overlay."""

    def __init__(self) -> None:
        super().__init__(None)
        self._opacity: float = 0.0

        # Window flags: frameless, always-on-top, transparent to input
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowOpacity(0.0)

        # Cover the entire primary screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Fade animation
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # ── Public ────────────────────────────────────────────────────────────────

    def show_overlay(self) -> None:
        self.show()
        self.raise_()
        self._animate_to(0.55)

    def hide_overlay(self) -> None:
        self._animate_to(0.0)
        QTimer.singleShot(320, self.hide)

    def on_state_changed(self, state: AppState) -> None:
        if state in (AppState.IDLE, AppState.DISMISS):
            self.hide_overlay()
        elif state == AppState.LISTENING:
            self.show_overlay()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 8, 20))
        painter.end()

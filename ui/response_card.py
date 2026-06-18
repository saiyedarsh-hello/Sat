"""
ui/response_card.py
Floating notification / response card that slides in from the bottom-right.
Auto-dismisses after a configurable timeout with a fade-out animation.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect
)
from PySide6.QtGui import QColor, QPainter, QFont, QFontMetrics, QPainterPath
from PySide6.QtWidgets import QWidget, QApplication, QLabel, QVBoxLayout


class ResponseCard(QWidget):
    """Slide-in floating card anchored to the bottom-right of the screen."""

    _CARD_W = 400
    _MARGIN = 24
    _PADDING = 20
    _RADIUS = 16

    def __init__(self, title: str, body: str, duration_ms: int = 4000) -> None:
        super().__init__(None)
        self._title = title
        self._body = body
        self._duration_ms = duration_ms

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._build_ui()
        self._calc_size()
        self._start_position = self._end_position = QPoint(0, 0)
        self._set_positions()

        # Slide-in animation
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(350)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Auto-dismiss
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

        # Fade-out
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(300)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.close)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self._PADDING, self._PADDING, self._PADDING, self._PADDING
        )
        layout.setSpacing(6)

        self._title_lbl = QLabel(self._title, self)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet(
            "color: #F0F0FF; font-family: 'Outfit', 'Segoe UI'; "
            "font-size: 14px; font-weight: 700; background: transparent;"
        )

        self._body_lbl = QLabel(self._body, self)
        self._body_lbl.setWordWrap(True)
        self._body_lbl.setStyleSheet(
            "color: rgba(240,240,255,0.75); font-family: 'Inter', 'Segoe UI'; "
            "font-size: 12px; background: transparent;"
        )
        self._body_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2)

        layout.addWidget(self._title_lbl)
        layout.addWidget(self._body_lbl)

    def _calc_size(self) -> None:
        self._title_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2)
        self._body_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2)
        self.adjustSize()
        if self.width() < self._CARD_W:
            self.setFixedWidth(self._CARD_W)

    def _set_positions(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - self._MARGIN
        y_end = screen.bottom() - self.height() - self._MARGIN
        y_start = y_end + 60  # start below final position
        self._start_position = QPoint(x, y_start)
        self._end_position = QPoint(x, y_end)

    # ── Public ────────────────────────────────────────────────────────────────

    def show_card(self) -> None:
        self.move(self._start_position)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._slide_anim.setStartValue(self._start_position)
        self._slide_anim.setEndValue(self._end_position)
        self._slide_anim.start()
        self._dismiss_timer.start(self._duration_ms)

    def dismiss(self) -> None:
        self._dismiss_timer.stop()
        self._fade_anim.start()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), self._RADIUS, self._RADIUS)

        # Glass background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 10, 24, 220))
        painter.drawPath(path)

        # Subtle border
        from PySide6.QtGui import QPen
        painter.setPen(QPen(QColor(108, 99, 255, 80), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Accent top strip
        accent_path = QPainterPath()
        accent_path.addRoundedRect(0, 0, self.width(), 3, 1.5, 1.5)
        from PySide6.QtGui import QLinearGradient
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor("#6C63FF"))
        grad.setColorAt(1.0, QColor("#A78BFA"))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(accent_path)

        painter.end()


# ── Card Manager ──────────────────────────────────────────────────────────────

class CardManager:
    """Creates and stacks response cards from the bottom-right."""

    _STACK_OFFSET = 8  # vertical gap between stacked cards

    def __init__(self, duration_ms: int = 4000) -> None:
        self._duration_ms = duration_ms
        self._cards: list[ResponseCard] = []

    def show(self, title: str, body: str) -> None:
        card = ResponseCard(title, body, self._duration_ms)
        card.show_card()

        # Shift existing cards up
        card_h = card.height() + self._STACK_OFFSET
        for existing in self._cards:
            pos = existing.pos()
            anim = QPropertyAnimation(existing, b"pos", existing)
            anim.setDuration(200)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(pos)
            anim.setEndValue(QPoint(pos.x(), pos.y() - card_h))
            anim.start()

        self._cards.append(card)

        # Clean up closed cards
        self._cards = [c for c in self._cards if c.isVisible()]

    def dismiss_all(self) -> None:
        """Dismiss all currently visible cards."""
        for card in self._cards:
            try:
                card.dismiss()
            except Exception:
                pass
        self._cards.clear()

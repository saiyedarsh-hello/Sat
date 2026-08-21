"""
ui/response_card.py
Floating notification cards — left-side, bottom-anchored, glassmorphism style.

Architecture (crash-proof):
  - WA_DeleteOnClose is NOT used — the Python object controls its own lifetime.
  - ResponseCard emits `closed` signal when fully faded; CardManager removes it then.
  - No C++ object can be deleted while still in the _cards list.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, Signal
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient, QPen
)
from PySide6.QtWidgets import QWidget, QApplication, QLabel, QVBoxLayout, QHBoxLayout


class ResponseCard(QWidget):
    """
    Glassmorphism floating card — slides in from the LEFT side of the screen.
    Emits `closed` when fully dismissed so CardManager can safely remove it.
    """

    closed = Signal()   # emitted AFTER fade completes — safe for list removal

    _CARD_W   = 380
    _MARGIN   = 20
    _PADDING  = 18
    _RADIUS   = 14
    _ACCENT_H = 3

    # State → accent gradient colours
    _ACCENT = {
        "default":  ("#6C63FF", "#A78BFA"),
        "error":    ("#EF4444", "#F87171"),
        "reminder": ("#F59E0B", "#FCD34D"),
        "heard":    ("#34D399", "#6EE7B7"),
    }

    def __init__(self, title: str, body: str, duration_ms: int = 4000) -> None:
        super().__init__(None)
        self._title       = title
        self._body        = body
        self._duration_ms = duration_ms
        self._dismissed   = False   # guard against double-dismiss

        # Determine accent type from title keyword
        t_lower = title.lower()
        if "error" in t_lower:
            self._accent = self._ACCENT["error"]
        elif "⏰" in title or "reminder" in t_lower:
            self._accent = self._ACCENT["reminder"]
        elif "heard" in t_lower:
            self._accent = self._ACCENT["heard"]
        else:
            self._accent = self._ACCENT["default"]

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # NOTE: WA_DeleteOnClose intentionally NOT set — we manage lifetime ourselves

        self._build_ui()
        self._calc_size()
        self._start_pos = QPoint(0, 0)
        self._end_pos   = QPoint(0, 0)
        self._set_positions()

        # ── Animations ────────────────────────────────────────────────────────
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(320)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(280)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_done)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            self._PADDING,
            self._PADDING + self._ACCENT_H,
            self._PADDING,
            self._PADDING,
        )
        root.setSpacing(5)

        # Header row: icon dot + title
        header = QHBoxLayout()
        header.setSpacing(8)

        dot = QLabel("●")
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"color: {self._accent[0]}; font-size: 9px; background: transparent;"
        )
        header.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title_lbl = QLabel(self._title)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet(
            "color: #F0F0FF;"
            "font-family: 'Outfit', 'Segoe UI', sans-serif;"
            "font-size: 13px; font-weight: 700;"
            "background: transparent;"
        )
        header.addWidget(self._title_lbl, 1)
        root.addLayout(header)

        # Body text
        self._body_lbl = QLabel(self._body)
        self._body_lbl.setWordWrap(True)
        self._body_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2)
        self._body_lbl.setStyleSheet(
            "color: rgba(220, 220, 255, 0.82);"
            "font-family: 'Inter', 'Segoe UI', sans-serif;"
            "font-size: 12px; line-height: 1.4;"
            "background: transparent;"
        )
        root.addWidget(self._body_lbl)

    def _calc_size(self) -> None:
        self._title_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2 - 20)
        self._body_lbl.setMaximumWidth(self._CARD_W - self._PADDING * 2)
        self.adjustSize()
        if self.width() < self._CARD_W:
            self.setFixedWidth(self._CARD_W)

    def _set_positions(self) -> None:
        """Position card on the LEFT side of the screen, bottom-anchored."""
        screen = QApplication.primaryScreen().availableGeometry()
        x_end   = screen.left() + self._MARGIN
        x_start = x_end - self._CARD_W - 20   # slide in from off-left-edge
        y_end   = screen.bottom() - self.height() - self._MARGIN
        self._start_pos = QPoint(x_start, y_end)
        self._end_pos   = QPoint(x_end,   y_end)

    # ── Public API ────────────────────────────────────────────────────────────

    def show_card(self) -> None:
        self.move(self._start_pos)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._slide_anim.setStartValue(self._start_pos)
        self._slide_anim.setEndValue(self._end_pos)
        self._slide_anim.start()
        self._dismiss_timer.start(self._duration_ms)

    def dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self._dismiss_timer.stop()
        self._slide_anim.stop()
        self._fade_anim.start()

    def shift_up(self, amount: int) -> None:
        """Animate this card upward by `amount` pixels."""
        try:
            pos = self.pos()
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(200)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(pos)
            anim.setEndValue(QPoint(pos.x(), pos.y() - amount))
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_fade_done(self) -> None:
        self.hide()
        self.closed.emit()   # tell CardManager to remove us
        # Schedule deleteLater so Qt cleans up after the signal returns
        self.deleteLater()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # ── Glassmorphism body ──────────────────────────────────────────────
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, self._RADIUS, self._RADIUS)

        # Dark translucent fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 8, 20, 230))
        painter.drawPath(path)

        # Soft inner glow border
        painter.setPen(QPen(QColor(108, 99, 255, 55), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # ── Left accent bar (vertical) ──────────────────────────────────────
        accent_path = QPainterPath()
        accent_path.addRoundedRect(0, 0, 4, h, 2, 2)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(self._accent[0]))
        grad.setColorAt(1.0, QColor(self._accent[1]))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(accent_path)

        # ── Top shimmer line ────────────────────────────────────────────────
        shimmer = QLinearGradient(0, 0, w, 0)
        shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
        shimmer.setColorAt(0.4, QColor(255, 255, 255, 18))
        shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(shimmer, 1))
        painter.drawLine(self._RADIUS, 0, w - self._RADIUS, 0)

        painter.end()


# ── Card Manager ──────────────────────────────────────────────────────────────

class CardManager:
    """
    Creates and stacks response cards on the LEFT side.

    Crash-proof: cards are removed from the list via their `closed` signal,
    so the list never holds a dead C++ object.
    """

    _STACK_GAP = 10   # px gap between stacked cards

    def __init__(self, duration_ms: int = 4000) -> None:
        self._duration_ms = duration_ms
        self._cards: list[ResponseCard] = []

    def show(self, title: str, body: str) -> None:
        card = ResponseCard(title, body, self._duration_ms)
        card.closed.connect(lambda c=card: self._on_card_closed(c))
        card.show_card()

        # Shift all existing live cards up to make room
        shift = card.height() + self._STACK_GAP
        for existing in list(self._cards):
            existing.shift_up(shift)

        self._cards.append(card)

    def _on_card_closed(self, card: ResponseCard) -> None:
        """Slot called when a card fully fades out — safe to remove."""
        try:
            self._cards.remove(card)
        except ValueError:
            pass

    def dismiss_all(self) -> None:
        """Dismiss all currently visible cards."""
        for card in list(self._cards):
            try:
                card.dismiss()
            except Exception:
                pass
        # List will be cleared by _on_card_closed callbacks

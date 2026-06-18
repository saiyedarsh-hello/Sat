"""
ui/orb_widget.py
Animated orb widget — the visual face of Saturday.
Uses QWidget + QPainter with radial gradients and QPropertyAnimation.
States drive color, scale, and ring animations without OpenGL dependency.
"""

from __future__ import annotations

import math
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    Property, QPointF, QRectF, Signal, QObject
)
from PySide6.QtGui import (
    QColor, QPainter, QRadialGradient, QPen, QFont,
    QLinearGradient, QBrush, QConicalGradient
)
from PySide6.QtWidgets import QWidget, QApplication

from core.app_controller import AppState


class OrbWidget(QWidget):
    """Animated orb — bottom-center of screen, always-on-top frameless window."""

    COLORS = {
        AppState.IDLE:       ("#6C63FF", "#A78BFA", "#1A1A2E"),
        AppState.LISTENING:  ("#818CF8", "#C4B5FD", "#1E1B4B"),
        AppState.PROCESSING: ("#F59E0B", "#FCD34D", "#1C1410"),
        AppState.SPEAKING:   ("#34D399", "#6EE7B7", "#0D2018"),
        AppState.DISMISS:    ("#6C63FF", "#A78BFA", "#1A1A2E"),
    }

    def __init__(self) -> None:
        super().__init__(None)
        self._state = AppState.IDLE
        self._scale: float = 1.0
        self._ring_alpha: int = 0
        self._ring_radius: float = 0.0
        self._arc_angle: int = 0
        self._audio_level: float = 0.0
        self._tick = 0

        # Window setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        orb_size = 220
        self.setFixedSize(orb_size + 80, orb_size + 80)

        # Position bottom-center
        self._reposition()

        # Animation timer (60fps)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick_animation)
        self._timer.start()

        # Scale pulse animation
        self._scale_anim = QPropertyAnimation(self, b"orb_scale", self)
        self._scale_anim.setDuration(3000)
        self._scale_anim.setLoopCount(-1)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._scale_anim.setKeyValueAt(0.0, 0.95)
        self._scale_anim.setKeyValueAt(0.5, 1.0)
        self._scale_anim.setKeyValueAt(1.0, 0.95)
        self._scale_anim.start()

    # ── Qt Property for scale animation ──────────────────────────────────────

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = v
        self.update()

    orb_scale = Property(float, _get_scale, _set_scale)

    # ── Public ────────────────────────────────────────────────────────────────

    def on_state_changed(self, state: AppState) -> None:
        self._state = state
        self._tick = 0
        if state in (AppState.IDLE, AppState.DISMISS):
            self._scale_anim.setDuration(3000)
            self.hide()
        elif state == AppState.LISTENING:
            self._scale_anim.setDuration(1200)
            self.show()
            self.raise_()
        elif state == AppState.PROCESSING:
            self._scale_anim.setDuration(800)
            self.show()
        elif state == AppState.SPEAKING:
            self._scale_anim.setDuration(600)
            self.show()
        self.update()

    def on_audio_level(self, level: float) -> None:
        self._audio_level = level
        self.update()

    # ── Animation tick ────────────────────────────────────────────────────────

    def _tick_animation(self) -> None:
        self._tick += 1
        if self._state == AppState.PROCESSING:
            self._arc_angle = (self._arc_angle + 6) % 360
        if self._state == AppState.LISTENING:
            self._ring_alpha = max(0, int(180 * abs(math.sin(self._tick * 0.05))))
            self._ring_radius = 10 + 20 * abs(math.sin(self._tick * 0.04))
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        orb_r = 90 * self._scale

        colors = self.COLORS.get(self._state, self.COLORS[AppState.IDLE])
        c1 = QColor(colors[0])
        c2 = QColor(colors[1])
        bg = QColor(colors[2])

        # ── Outer glow ring (LISTENING state) ─────────────────────────────
        if self._state == AppState.LISTENING:
            for i in range(3):
                ring_r = orb_r + 20 + i * (self._ring_radius + i * 8)
                glow = QColor(c1)
                glow.setAlpha(max(0, self._ring_alpha - i * 50))
                pen = QPen(glow, 2 - i * 0.5)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        # ── Spinning arc (PROCESSING state) ───────────────────────────────
        if self._state == AppState.PROCESSING:
            pen = QPen(QColor("#F59E0B"), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - orb_r - 16, cy - orb_r - 16,
                              (orb_r + 16) * 2, (orb_r + 16) * 2)
            painter.drawArc(arc_rect, self._arc_angle * 16, 120 * 16)

        # ── Audio bloom (SPEAKING state) ──────────────────────────────────
        if self._state == AppState.SPEAKING and self._audio_level > 0.05:
            bloom_r = orb_r + 10 + self._audio_level * 40
            bloom_color = QColor(c2)
            bloom_color.setAlpha(80)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bloom_color))
            painter.drawEllipse(QPointF(cx, cy), bloom_r, bloom_r)

        # ── Drop shadow ───────────────────────────────────────────────────
        shadow = QRadialGradient(cx, cy + 10, orb_r * 1.2)
        shadow.setColorAt(0, QColor(0, 0, 0, 100))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(shadow))
        painter.drawEllipse(QPointF(cx, cy + 10), orb_r * 1.2, orb_r * 0.5)

        # ── Main orb body ────────────────────────────────────────────────
        gradient = QRadialGradient(cx - orb_r * 0.3, cy - orb_r * 0.3, orb_r * 1.5)
        gradient.setColorAt(0.0, c2)
        gradient.setColorAt(0.5, c1)
        gradient.setColorAt(1.0, QColor(bg))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        # ── Inner highlight ───────────────────────────────────────────────
        highlight = QRadialGradient(cx - orb_r * 0.25, cy - orb_r * 0.35, orb_r * 0.55)
        highlight.setColorAt(0.0, QColor(255, 255, 255, 90))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        # ── State label ───────────────────────────────────────────────────
        labels = {
            AppState.IDLE:       "",
            AppState.LISTENING:  "Listening…",
            AppState.PROCESSING: "Thinking…",
            AppState.SPEAKING:   "Speaking…",
            AppState.DISMISS:    "",
        }
        label = labels.get(self._state, "")
        if label:
            font = QFont("Outfit", 11, QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(240, 240, 255, 200))
            painter.drawText(
                QRectF(0, cy + orb_r + 8, w, 30),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )

        painter.end()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        x = screen.center().x() - self.width() // 2
        y = screen.bottom() - self.height() - 40
        self.move(x, y)

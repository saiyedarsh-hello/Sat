"""
ui/orb_widget.py
Animated orb widget — the visual voice face of Saturday.
Uses QWidget + QPainter with radial gradients, pulsing rings, and loading progress ring.
"""

from __future__ import annotations

import math
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    Property, QPointF, QRectF, Signal, QObject,
)
from PySide6.QtGui import (
    QColor, QPainter, QRadialGradient, QPen, QFont,
    QLinearGradient, QBrush, QConicalGradient,
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

        # Subsystems loading progress state
        self._is_loading = False
        self._loading_progress = 0
        self._loading_status = "Initializing..."

        # Window setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        orb_size = 220
        self.setFixedSize(orb_size + 100, orb_size + 100)

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

    # ── Public API ────────────────────────────────────────────────────────────

    def on_init_progress(self, percent: int, status_text: str) -> None:
        """Show loading progress ring around the orb during startup."""
        self._loading_progress = percent
        self._loading_status = status_text

        if percent < 100:
            self._is_loading = True
            self.show()
            self.raise_()
            self.update()
        else:
            self._is_loading = False
            self.update()
            # Fade/hide when idle after 1.5s
            QTimer.singleShot(1500, self._check_hide_after_init)

    def _check_hide_after_init(self) -> None:
        if self._state in (AppState.IDLE, AppState.DISMISS) and not self._is_loading:
            self.hide()

    def on_state_changed(self, state: AppState) -> None:
        self._state = state
        self._tick = 0
        if state in (AppState.IDLE, AppState.DISMISS):
            self._scale_anim.setDuration(3000)
            if not self._is_loading:
                self.hide()
        elif state == AppState.LISTENING:
            self._scale_anim.setDuration(1200)
            self.show()
            self.raise_()
        elif state == AppState.PROCESSING:
            self._scale_anim.setDuration(800)
            self.show()
            self.raise_()
        elif state == AppState.SPEAKING:
            self._scale_anim.setDuration(600)
            if not self._is_loading:
                self.hide()
        self.update()

    def on_audio_level(self, level: float) -> None:
        self._audio_level = level
        self.update()

    # ── Animation tick ────────────────────────────────────────────────────────

    def _tick_animation(self) -> None:
        try:
            self._tick += 1
            if self._state == AppState.PROCESSING or self._is_loading:
                self._arc_angle = (self._arc_angle + 5) % 360
            if self._state == AppState.LISTENING:
                self._ring_alpha = max(0, int(180 * abs(math.sin(self._tick * 0.05))))
                self._ring_radius = 10 + 20 * abs(math.sin(self._tick * 0.04))
            self.update()
        except RuntimeError:
            self._timer.stop()
        except Exception:
            pass

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 - 10
        orb_r = 85 * self._scale

        colors = self.COLORS.get(self._state, self.COLORS[AppState.IDLE])
        c1 = QColor(colors[0])
        c2 = QColor(colors[1])
        bg = QColor(colors[2])

        # ── 1. Loading Progress Ring (around orb during startup) ──────────────
        if self._is_loading:
            ring_rect = QRectF(cx - orb_r - 18, cy - orb_r - 18, (orb_r + 18) * 2, (orb_r + 18) * 2)
            
            # Subtle background track
            track_pen = QPen(QColor(255, 255, 255, 25), 3)
            painter.setPen(track_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), orb_r + 18, orb_r + 18)

            # Active glowing progress arc
            prog_pen = QPen(QColor("#A855F7"), 4.5)
            prog_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(prog_pen)
            angle_span = int((self._loading_progress / 100.0) * 360 * 16)
            painter.drawArc(ring_rect, -90 * 16 - (self._arc_angle * 4), -angle_span)

        # ── 2. Outer glow ring (LISTENING state) ──────────────────────────────
        if self._state == AppState.LISTENING and not self._is_loading:
            for i in range(3):
                ring_r = orb_r + 20 + i * (self._ring_radius + i * 8)
                glow = QColor(c1)
                glow.setAlpha(max(0, self._ring_alpha - i * 50))
                pen = QPen(glow, 2 - i * 0.5)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        # ── 3. Spinning arc (PROCESSING state) ────────────────────────────────
        if self._state == AppState.PROCESSING and not self._is_loading:
            pen = QPen(QColor("#F59E0B"), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - orb_r - 16, cy - orb_r - 16,
                              (orb_r + 16) * 2, (orb_r + 16) * 2)
            painter.drawArc(arc_rect, self._arc_angle * 16, 120 * 16)

        # ── 4. Audio bloom (SPEAKING state) ───────────────────────────────────
        if self._state == AppState.SPEAKING and self._audio_level > 0.05:
            bloom_r = orb_r + 10 + self._audio_level * 40
            bloom_color = QColor(c2)
            bloom_color.setAlpha(80)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bloom_color))
            painter.drawEllipse(QPointF(cx, cy), bloom_r, bloom_r)

        # ── 5. Drop shadow ────────────────────────────────────────────────────
        shadow = QRadialGradient(cx, cy + 12, orb_r * 1.2)
        shadow.setColorAt(0, QColor(0, 0, 0, 110))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(shadow))
        painter.drawEllipse(QPointF(cx, cy + 12), orb_r * 1.2, orb_r * 0.5)

        # ── 6. Main orb body ──────────────────────────────────────────────────
        gradient = QRadialGradient(cx - orb_r * 0.3, cy - orb_r * 0.3, orb_r * 1.5)
        gradient.setColorAt(0.0, c2)
        gradient.setColorAt(0.5, c1)
        gradient.setColorAt(1.0, QColor(bg))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        # ── 7. Inner highlight ────────────────────────────────────────────────
        highlight = QRadialGradient(cx - orb_r * 0.25, cy - orb_r * 0.35, orb_r * 0.55)
        highlight.setColorAt(0.0, QColor(255, 255, 255, 95))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(QPointF(cx, cy), orb_r, orb_r)

        # ── 8. Status & Loading Label ─────────────────────────────────────────
        if self._is_loading:
            font_title = QFont("Segoe UI", 11, QFont.Weight.Bold)
            painter.setFont(font_title)
            painter.setPen(QColor(240, 240, 255, 230))
            painter.drawText(
                QRectF(0, cy + orb_r + 14, w, 22),
                Qt.AlignmentFlag.AlignHCenter,
                f"Loading… {self._loading_progress}%",
            )

            font_sub = QFont("Segoe UI", 9)
            painter.setFont(font_sub)
            painter.setPen(QColor(180, 190, 220, 180))
            painter.drawText(
                QRectF(10, cy + orb_r + 34, w - 20, 20),
                Qt.AlignmentFlag.AlignHCenter,
                self._loading_status[:40],
            )
        else:
            labels = {
                AppState.IDLE:       "",
                AppState.LISTENING:  "Listening…",
                AppState.PROCESSING: "Thinking…",
                AppState.SPEAKING:   "Speaking…",
                AppState.DISMISS:    "",
            }
            label = labels.get(self._state, "")
            if label:
                font = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
                painter.setFont(font)
                painter.setPen(QColor(240, 240, 255, 210))
                painter.drawText(
                    QRectF(0, cy + orb_r + 14, w, 26),
                    Qt.AlignmentFlag.AlignHCenter,
                    label,
                )

        painter.end()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        x = screen.center().x() - self.width() // 2
        y = screen.bottom() - self.height() - 30
        self.move(x, y)

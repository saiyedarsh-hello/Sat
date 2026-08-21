"""
ui/waveform_widget.py
Live microphone waveform bar-chart widget rendered with QPainter.
Consumes audio_level signals from AppController and draws a symmetric
bar visualization centered on the orb.
"""

from __future__ import annotations

import math
import random
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QBrush
from PySide6.QtWidgets import QWidget, QApplication

from core.app_controller import AppState

_BAR_COUNT = 32
_BAR_MAX_H = 60
_BAR_W = 4
_BAR_GAP = 3


class WaveformWidget(QWidget):
    """Symmetric bar-chart waveform; appears during LISTENING / SPEAKING states."""

    def __init__(self) -> None:
        super().__init__(None)
        self._bars: deque[float] = deque([0.0] * _BAR_COUNT, maxlen=_BAR_COUNT)
        self._state = AppState.IDLE
        self._active = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        total_w = _BAR_COUNT * (_BAR_W + _BAR_GAP)
        self.setFixedSize(total_w + 40, _BAR_MAX_H + 20)
        self._reposition()

        # Decay timer for smooth fall-off
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(30)
        self._decay_timer.timeout.connect(self._decay)

    # ── Public ────────────────────────────────────────────────────────────────

    def on_state_changed(self, state: AppState) -> None:
        self._state = state
        if state in (AppState.LISTENING, AppState.SPEAKING):
            self._active = True
            self._decay_timer.start()
            self.show()
            self.raise_()
        else:
            self._active = False
            self._decay_timer.stop()
            self.hide()

    def on_audio_level(self, level: float) -> None:
        """Push a new sample (0-1) and add subtle noise for visual richness."""
        if not self._active:
            return
        # Main bar with variation
        for i in range(3):
            noise = random.uniform(0.4, 1.0)
            self._bars.append(min(1.0, level * noise))
        self.update()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decay(self) -> None:
        if not self._active:
            return
        self._bars = deque([max(0.0, v * 0.85) for v in self._bars], maxlen=_BAR_COUNT)
        self.update()

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        x = screen.center().x() - self.width() // 2
        y = screen.bottom() - 120
        self.move(x, y)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx = w / 2
        cy = h / 2

        bars = list(self._bars)
        n = len(bars)
        total_w = n * (_BAR_W + _BAR_GAP)
        x_start = cx - total_w / 2

        for i, amp in enumerate(bars):
            bar_h = max(3, amp * _BAR_MAX_H)
            x = x_start + i * (_BAR_W + _BAR_GAP)
            y = cy - bar_h / 2

            # Color gradient per bar
            alpha = int(180 + 75 * amp)
            if self._state == AppState.LISTENING:
                color_top = QColor(129, 140, 248, alpha)    # #818CF8
                color_bot = QColor(108, 99, 255, alpha // 2)
            else:
                color_top = QColor(52, 211, 153, alpha)     # #34D399
                color_bot = QColor(16, 185, 129, alpha // 2)

            grad = QLinearGradient(x, y, x, y + bar_h)
            grad.setColorAt(0.0, color_top)
            grad.setColorAt(1.0, color_bot)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            rect = QRectF(x, y, _BAR_W, bar_h)
            painter.drawRoundedRect(rect, _BAR_W / 2, _BAR_W / 2)

        painter.end()

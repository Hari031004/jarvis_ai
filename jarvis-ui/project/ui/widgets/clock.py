"""Animated HUD clock with time, date and orbiting seconds indicator.

Polish:
- Driven by the shared AnimationClock so it ticks in sync with the rest of
  the HUD instead of its own 1/30s timer.
- Seconds dot has a soft pulsing halo for a more "alive" feel.
- Orbiting dot leaves a faint trailing arc for motion clarity.
"""
from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui.animations import shared_clock
from ui.theme import Colors
from ui.utils import neon_pen


class HUDClock(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(150)
        self._phase = 0.0
        shared_clock().subscribe(self._tick)

    def _tick(self, dt: float) -> None:
        # Update ~30 FPS is enough for a clock; halve the shared 60fps cadence.
        self._phase += dt
        if int(self._phase * 30) != int((self._phase - dt) * 30):
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect())
            now = datetime.now()

            # Ring
            center = QPointF(rect.width() / 2, rect.height() / 2 - 6)
            r = min(rect.width(), rect.height()) / 2 - 18
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(neon_pen(Colors.NEON, 1.0, 70))
            painter.drawEllipse(center, r, r)

            # Seconds arc
            secs = now.second + now.microsecond / 1_000_000
            span = 360.0 * (secs / 60.0)
            painter.setPen(neon_pen(Colors.NEON, 2.2, 220))
            painter.drawArc(
                QRectF(center.x() - r, center.y() - r, r * 2, r * 2),
                int(90 * 16),
                int(-span * 16),
            )

            # Orbiting seconds dot with pulsing halo
            rad = math.radians(90 - span)
            sx = center.x() + r * math.cos(rad)
            sy = center.y() + r * math.sin(rad)
            pulse = 0.6 + 0.4 * math.sin(secs * math.tau)
            halo = QRadialGradient(QPointF(sx, sy), 9)
            hc = QColor(Colors.NEON); hc.setAlpha(int(140 * pulse))
            hc2 = QColor(Colors.NEON); hc2.setAlpha(0)
            halo.setColorAt(0.0, hc)
            halo.setColorAt(1.0, hc2)
            painter.setBrush(halo)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(sx, sy), 9, 9)
            painter.setBrush(QColor(Colors.NEON))
            painter.drawEllipse(QPointF(sx, sy), 4, 4)

            # Inner ticks (hours)
            painter.setPen(neon_pen(Colors.NEON, 1.0, 120))
            for h in range(12):
                ang = math.radians(h * 30 - 90)
                r1 = r - 6
                r2 = r - (10 if h % 3 == 0 else 6)
                painter.drawLine(
                    QPointF(center.x() + r1 * math.cos(ang), center.y() + r1 * math.sin(ang)),
                    QPointF(center.x() + r2 * math.cos(ang), center.y() + r2 * math.sin(ang)),
                )

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(220, 150)


class DigitalClock(QWidget):
    """Digital clock readout with date — pairs with HUDClock visuals."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        self._last_sec = -1
        shared_clock().subscribe(self._tick)

    def _tick(self, dt: float) -> None:
        s = datetime.now().second
        if s != self._last_sec:
            self._last_sec = s
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            now = datetime.now()
            time_str = now.strftime("%H:%M:%S")
            date_str = now.strftime("%A, %d %B %Y").upper()

            rect = QRectF(self.rect())
            painter.setPen(QColor(Colors.NEON))
            painter.setFont(QFont("Orbitron", 28, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left(), rect.top(), rect.width(), 48),
                Qt.AlignmentFlag.AlignCenter,
                time_str,
            )
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.setFont(QFont("Rajdhani", 10, QFont.Weight.Medium))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 48, rect.width(), 20),
                Qt.AlignmentFlag.AlignCenter,
                date_str,
            )

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(240, 80)

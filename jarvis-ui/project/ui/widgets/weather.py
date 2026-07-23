"""Weather widget with animated neon sun glyph (static placeholder data).

Polish:
- Driven by the shared AnimationClock (was its own 60ms timer).
- Sun glyph gets a pulsing inner core + smoother ray phase for a livelier
  feel.
- Spacing/typography tightened to match the rest of the HUD hierarchy.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from ui.animations import shared_clock
from ui.theme import Colors
from ui.utils import neon_pen, paint_hud_frame


class WeatherWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(170)
        self._phase = 0.0
        shared_clock().subscribe(self._tick)

        # Placeholder static data
        self.condition = "CLEAR SKY"
        self.temp = 23
        self.humidity = 48
        self.wind = 12
        self.city = "MALIBU, CA"

    def _tick(self, dt: float) -> None:
        # Sun rays + core pulse; 30 FPS is plenty for a slow glyph.
        self._phase += dt * 1.6
        if int(self._phase * 30) != int((self._phase - dt) * 30):
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(6, 6, -6, -6)

            paint_hud_frame(painter, rect)

            # Header
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.setFont(QFont("Rajdhani", 8, QFont.Weight.Medium))
            painter.drawText(
                QRectF(rect.left() + 14, rect.top() + 8, 200, 14),
                Qt.AlignmentFlag.AlignLeft,
                "ATMOSPHERIC SCAN",
            )

            # City
            painter.setPen(QColor(Colors.NEON))
            painter.setFont(QFont("Orbitron", 9, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 14, rect.top() + 24, 200, 14),
                Qt.AlignmentFlag.AlignLeft,
                self.city,
            )

            # Animated sun glyph on the right
            gx = rect.right() - 50
            gy = rect.top() + 56
            self._draw_sun(painter, QPointF(gx, gy), 18)

            # Temperature
            painter.setPen(QColor(Colors.NEON))
            painter.setFont(QFont("Orbitron", 26, QFont.Weight.Bold))
            painter.drawText(
                QRectF(rect.left() + 14, rect.top() + 44, 120, 40),
                Qt.AlignmentFlag.AlignLeft,
                f"{self.temp}°",
            )

            # Condition
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            painter.setFont(QFont("Rajdhani", 11, QFont.Weight.Medium))
            painter.drawText(
                QRectF(rect.left() + 14, rect.top() + 86, 200, 18),
                Qt.AlignmentFlag.AlignLeft,
                self.condition,
            )

            # Metrics row
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.setFont(QFont("Rajdhani", 9))
            metrics = f"HUM {self.humidity}%   WIND {self.wind} KM/H"
            painter.drawText(
                QRectF(rect.left() + 14, rect.top() + 112, rect.width() - 28, 18),
                Qt.AlignmentFlag.AlignLeft,
                metrics,
            )

            # Mini bar showing humidity
            bar = QRectF(rect.left() + 14, rect.top() + 134, rect.width() - 28, 6)
            painter.setBrush(QColor(2, 8, 18))
            painter.setPen(neon_pen(Colors.NEON, 0.8, 80))
            painter.drawRoundedRect(bar, 3, 3)
            fill = QRectF(bar)
            fill.setWidth(bar.width() * (self.humidity / 100.0))
            painter.setBrush(QColor(Colors.NEON))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(fill, 3, 3)

    def _draw_sun(self, painter: QPainter, center: QPointF, radius: float) -> None:
        # Multi-layer glow halo
        for i in range(3):
            alpha = 60 - i * 18
            painter.setBrush(QColor(0, 229, 255, alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, radius + 4 + i * 3, radius + 4 + i * 3)
        # Pulsing core
        pulse = 0.85 + 0.15 * math.sin(self._phase * 1.5)
        painter.setBrush(QColor(Colors.ACCENT))
        painter.setPen(neon_pen(Colors.NEON, 1.2, 200))
        painter.drawEllipse(center, radius * 0.55 * pulse, radius * 0.55 * pulse)
        # Rays
        painter.setPen(neon_pen(Colors.NEON, 1.4, 220))
        for i in range(8):
            ang = self._phase + i * (math.pi / 4)
            x0 = center.x() + (radius * 0.7) * math.cos(ang)
            y0 = center.y() + (radius * 0.7) * math.sin(ang)
            x1 = center.x() + (radius * 1.15) * math.cos(ang)
            y1 = center.y() + (radius * 1.15) * math.sin(ang)
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 170)

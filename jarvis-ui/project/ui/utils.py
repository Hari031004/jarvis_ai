"""Helper utilities for the JARVIS HUD."""
import math
import random
from typing import Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ui.theme import Colors


def neon_pen(color: str = Colors.NEON, width: float = 1.5, alpha: int = 255) -> QPen:
    c = QColor(color)
    c.setAlpha(alpha)
    pen = QPen(c, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def glow_paint(
    painter: QPainter, center: QPointF, radius: float, color: str = Colors.NEON
) -> QRadialGradient:
    gradient = QRadialGradient(center, radius)
    c0 = QColor(color)
    c0.setAlpha(90)
    c1 = QColor(color)
    c1.setAlpha(0)
    gradient.setColorAt(0.0, c0)
    gradient.setColorAt(1.0, c1)
    return gradient


def draw_arc_text(
    painter: QPainter,
    text: str,
    center: QPointF,
    radius: float,
    start_deg: float,
    span_deg: float,
    color: str = Colors.NEON,
    font_size: int = 9,
) -> None:
    painter.save()
    painter.translate(center)
    painter.rotate(start_deg)
    painter.setPen(QColor(color))
    painter.setFont(QFont("Orbitron", font_size, QFont.Weight.Bold))
    step = span_deg / max(1, len(text))
    for ch in text:
        painter.drawText(
            QRectF(-radius - 20, -8, 40, 20),
            Qt.AlignmentFlag.AlignCenter,
            ch,
        )
        painter.rotate(step)
    painter.restore()


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def point_on_circle(
    center: QPointF, radius: float, angle_deg: float
) -> QPointF:
    rad = math.radians(angle_deg)
    return QPointF(
        center.x() + radius * math.cos(rad),
        center.y() + radius * math.sin(rad),
    )


def random_in_bounds(bounds: QRectF, margin: float = 20.0) -> Tuple[QPointF, QPointF]:
    p = QPointF(
        random.uniform(bounds.left() + margin, bounds.right() - margin),
        random.uniform(bounds.top() + margin, bounds.bottom() - margin),
    )
    v = QPointF(
        random.uniform(-0.4, 0.4),
        random.uniform(-0.4, 0.4),
    )
    return p, v


def paint_hud_frame(
    painter: QPainter, rect: QRectF, color: str = Colors.NEON
) -> None:
    """Draw a stylized HUD frame with clipped corners (Iron Man style)."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = neon_pen(color, 1.2, 120)
    painter.setPen(pen)

    clip = 14
    path = QPainterPath()
    path.moveTo(rect.left(), rect.top() + clip)
    path.lineTo(rect.left() + clip, rect.top())
    path.lineTo(rect.right() - clip, rect.top())
    path.lineTo(rect.right(), rect.top() + clip)
    path.lineTo(rect.right(), rect.bottom() - clip)
    path.lineTo(rect.right() - clip, rect.bottom())
    path.lineTo(rect.left() + clip, rect.bottom())
    path.lineTo(rect.left(), rect.bottom() - clip)
    path.closeSubpath()
    painter.drawPath(path)

    # Accent ticks at corners
    pen2 = neon_pen(color, 2.0, 220)
    painter.setPen(pen2)
    tick = 10
    painter.drawLine(
        rect.left(), rect.top() + clip,
        rect.left(), rect.top() + clip + tick,
    )
    painter.drawLine(
        rect.left() + clip, rect.top(),
        rect.left() + clip + tick, rect.top(),
    )
    painter.drawLine(
        rect.right(), rect.top() + clip,
        rect.right(), rect.top() + clip + tick,
    )
    painter.drawLine(
        rect.right() - clip, rect.top(),
        rect.right() - clip - tick, rect.top(),
    )


def paint_glow_backdrop(widget: QWidget, color: str = Colors.NEON) -> None:
    """Paint a soft radial glow filling the widget (for behind visualizers)."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect())
    grad = glow_paint(painter, rect.center(), max(rect.width(), rect.height()) * 0.6, color)
    painter.fillRect(rect, grad)
    painter.end()

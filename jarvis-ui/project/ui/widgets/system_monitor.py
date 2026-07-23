"""System monitor: CPU, RAM and Network gauges + live sparkline graph.

Upgrades:
- Gauges now animate on the shared 60 FPS clock with frame-rate-independent
  damping (damp()). Previously the value was mutated inside paintEvent, which
  tied animation speed to repaint rate and caused visible jumps when the
  widget wasn't being painted.
- Target values are sampled on a slow 900ms timer; interpolation runs on the
  fast clock so the needles glide smoothly between samples.
- Sparkline also interpolates the latest sample so the line glides rather than
  stepping.
- Pens are cached on the widget to avoid per-frame allocation.
"""
from __future__ import annotations

import collections
import random

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.animations import damp, shared_clock
from ui.theme import Colors
from ui.utils import neon_pen, paint_hud_frame


def _make_pen(color: str, width: float, alpha: int) -> QPen:
    c = QColor(color); c.setAlpha(alpha)
    p = QPen(c, width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


class RadialGauge(QWidget):
    """Circular gauge that displays a percentage 0-100 with a glowing arc."""

    def __init__(self, label: str, color: str = Colors.NEON,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._label = label
        self._color = color
        self._value = 0.0
        self._target = 0.0
        # Cached pens reused every frame.
        self._track_pen = _make_pen(Colors.NEON, 2.0, 50)
        self._value_pen = _make_pen(color, 2.6, 230)
        self._glow_pen = _make_pen(color, 5.0, 40)
        shared_clock().subscribe(self._tick)

    def set_value(self, pct: float) -> None:
        self._target = max(0.0, min(100.0, pct))

    def _tick(self, dt: float) -> None:
        # ~140ms time constant -> smooth glide without lag.
        new = damp(self._value, self._target, 0.14, dt)
        if abs(new - self._value) > 0.05:
            self._value = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect())
            center = rect.center()
            r = min(rect.width(), rect.height()) / 2 - 10
            arc_rect = QRectF(center.x() - r, center.y() - r, r * 2, r * 2)

            # Track
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self._track_pen)
            painter.drawArc(arc_rect, int(225 * 16), int(-270 * 16))

            # Value arc (glow underlay + crisp top stroke)
            span = 270.0 * (self._value / 100.0)
            painter.setPen(self._glow_pen)
            painter.drawArc(arc_rect, int(225 * 16), int(-span * 16))
            painter.setPen(self._value_pen)
            painter.drawArc(arc_rect, int(225 * 16), int(-span * 16))

            # Value text
            painter.setPen(QColor(Colors.NEON))
            painter.setFont(QFont("Orbitron", 14, QFont.Weight.Bold))
            painter.drawText(
                QRectF(center.x() - 30, center.y() - 12, 60, 24),
                Qt.AlignmentFlag.AlignCenter,
                f"{int(self._value)}",
            )
            # Label
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.setFont(QFont("Rajdhani", 7, QFont.Weight.Medium))
            painter.drawText(
                QRectF(center.x() - 40, center.y() + 14, 80, 12),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )


class Sparkline(QWidget):
    """Live scrolling line graph with a glowing gradient fill."""

    def __init__(self, color: str = Colors.NEON, parent: QWidget | None = None,
                 maxlen: int = 80) -> None:
        super().__init__(parent)
        self.setMinimumHeight(90)
        self._color = color
        self._data: collections.deque[float] = collections.deque(maxlen=maxlen)
        for _ in range(maxlen):
            self._data.append(0.0)
        self._latest_target = 0.0
        self._latest_display = 0.0
        self._grid_pen = _make_pen(Colors.NEON, 0.6, 30)
        self._line_pen = _make_pen(color, 1.6, 220)
        shared_clock().subscribe(self._tick)

    def push(self, value: float) -> None:
        v = max(0.0, min(100.0, value))
        self._latest_target = v
        self._data.append(v)

    def _tick(self, dt: float) -> None:
        # Smooth the displayed latest point so the head of the line glides.
        new = damp(self._latest_display, self._latest_target, 0.18, dt)
        if abs(new - self._latest_display) > 0.05:
            self._latest_display = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)

            # Grid
            painter.setPen(self._grid_pen)
            for i in range(1, 4):
                y = rect.top() + rect.height() * (i / 4)
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

            data = list(self._data)
            # Replace the last point with the smoothed display value so the head
            # glides between pushes instead of stepping.
            if data:
                data[-1] = self._latest_display
            n = len(data)
            if n < 2:
                return
            step = rect.width() / (n - 1)

            # Fill path
            path = QPainterPath()
            path.moveTo(rect.left(), rect.bottom())
            for i, v in enumerate(data):
                x = rect.left() + i * step
                y = rect.bottom() - (v / 100.0) * rect.height()
                path.lineTo(x, y)
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()

            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            c0 = QColor(self._color); c0.setAlpha(80)
            c1 = QColor(self._color); c1.setAlpha(0)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

            # Line path
            line = QPainterPath()
            for i, v in enumerate(data):
                x = rect.left() + i * step
                y = rect.bottom() - (v / 100.0) * rect.height()
                if i == 0:
                    line.moveTo(x, y)
                else:
                    line.lineTo(x, y)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self._line_pen)
            painter.drawPath(line)

            # Latest dot with soft halo
            last_v = data[-1]
            lx = rect.right()
            ly = rect.bottom() - (last_v / 100.0) * rect.height()
            painter.setBrush(QColor(self._color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(lx, ly), 3, 3)


class SystemMonitor(QFrame):
    """CPU / RAM / Network panel with gauges and a network sparkline."""

    SAMPLE_MS = 900

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(230)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("SYSTEM DIAGNOSTICS")
        title.setObjectName("Title")
        sub = QLabel("REAL-TIME")
        sub.setObjectName("Subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(sub)
        outer.addLayout(header)

        gauges = QHBoxLayout()
        gauges.setSpacing(18)
        self._cpu = RadialGauge("CPU", Colors.NEON)
        self._ram = RadialGauge("RAM", Colors.ACCENT)
        self._net = RadialGauge("NET", Colors.SUCCESS)
        for g in (self._cpu, self._ram, self._net):
            g_wrapper = QVBoxLayout()
            g_wrapper.addWidget(g, alignment=Qt.AlignmentFlag.AlignCenter)
            gauges.addLayout(g_wrapper)
        gauges.addStretch()
        self._spark = Sparkline(Colors.SUCCESS)
        gauges.addWidget(self._spark, 1)
        outer.addLayout(gauges)

        # Only the sampler runs on its own (slow) timer; animation is on the
        # shared clock via the gauges/sparkline themselves.
        from PySide6.QtCore import QTimer
        self._sampler = QTimer(self)
        self._sampler.setInterval(self.SAMPLE_MS)
        self._sampler.timeout.connect(self._sample)
        self._sampler.start()
        self._sample()

    def _sample(self) -> None:
        cpu = 25 + random.random() * 45
        ram = 45 + random.random() * 25
        net = random.random() * 80
        self._cpu.set_value(cpu)
        self._ram.set_value(ram)
        self._net.set_value(net)
        self._spark.push(net)

    def update_real(self, cpu: float, ram: float, gpu: float, disk: float) -> None:
        """Public API to push real metrics from SystemMonitorService to HUD widgets.

        Stops the local random sampler timer permanently on first call so mock data
        never overwrites real telemetry.
        """
        if self._sampler.isActive():
            self._sampler.stop()
            # Dynamically rename the third gauge label from "NET" to "GPU"
            self._net._label = "GPU"
            self._net.update()
        
        self._cpu.set_value(cpu)
        self._ram.set_value(ram)
        self._net.set_value(gpu)
        self._spark.push(gpu)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(460, 230)


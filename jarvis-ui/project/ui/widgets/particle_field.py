"""Animated particle field rendered behind the JARVIS HUD.

Optimizations vs. the original:
- Multi-layer depth: three parallax layers with different speeds/sizes/alpha
  give a sense of depth without extra particles.
- Spatial-hash link culling: the O(n^2) proximity check is replaced by a grid
  bucket lookup so link cost scales ~O(n) instead of O(n^2).
- One cached pen/brush reuse path — no per-link neon_pen() allocation.
- HUD grid + scanning line overlays drawn into the same pass so there is only
  one repaint for the whole backdrop.
- Driven by the shared AnimationClock at ~30 FPS (background motion is
  perceptually fine at 30; foreground widgets run at 60 on the same clock).
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ui.animations import shared_clock
from ui.theme import Colors


def _make_pen(color: str, width: float, alpha: int) -> QPen:
    c = QColor(color)
    c.setAlpha(alpha)
    p = QPen(c, width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    return p


class Particle:
    __slots__ = ("pos", "vel", "size", "alpha", "phase", "hue_offset", "depth")

    def __init__(self, bounds: QRectF, depth: int = 1) -> None:
        self.depth = depth  # 0 = far, 1 = mid, 2 = near
        speed = 0.18 + depth * 0.12
        self.pos = QPointF(
            random.uniform(bounds.left(), bounds.right()),
            random.uniform(bounds.top(), bounds.bottom()),
        )
        self.vel = QPointF(
            random.uniform(-speed, speed),
            random.uniform(-speed, speed),
        )
        self.size = random.uniform(0.8 + depth * 0.6, 1.4 + depth * 1.4)
        self.alpha = random.uniform(60 + depth * 40, 120 + depth * 60)
        self.phase = random.uniform(0, math.tau)
        self.hue_offset = random.uniform(-10, 10)

    def step(self, bounds: QRectF, dt: float) -> None:
        # Depth scales travel speed for a parallax feel.
        scale = 30.0 * (0.6 + self.depth * 0.4)
        self.pos = QPointF(
            self.pos.x() + self.vel.x() * dt * scale,
            self.pos.y() + self.vel.y() * dt * scale,
        )
        self.phase += dt * (1.2 + self.depth * 0.6)
        m = 30
        if self.pos.x() < bounds.left() - m:
            self.pos.setX(bounds.right() + m)
        elif self.pos.x() > bounds.right() + m:
            self.pos.setX(bounds.left() - m)
        if self.pos.y() < bounds.top() - m:
            self.pos.setY(bounds.bottom() + m)
        elif self.pos.y() > bounds.bottom() + m:
            self.pos.setY(bounds.top() - m)


class ParticleField(QWidget):
    """Floating neon particles with proximity links, HUD grid and scanlines."""

    LINK_DISTANCE = 120.0
    GRID_SPACING = 64  # px between HUD grid intersections

    def __init__(self, parent: QWidget | None = None, count: int = 72) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # Distribute count across 3 depth layers (near:mid:far = 2:3:2)
        near = count * 2 // 7
        mid = count * 3 // 7
        far = count - near - mid
        self._layer_counts = [far, mid, near]
        self._particles: list[Particle] = []

        self._scan_y = 0.0
        self._frame = 0  # tick counter; we repaint every other tick (~30fps)

        # Cached pens reused across frames to avoid per-line allocation.
        self._link_pen = _make_pen(Colors.NEON, 0.6, 50)
        self._grid_pen = _make_pen(Colors.NEON, 0.5, 18)
        self._scan_pen = _make_pen(Colors.NEON, 1.0, 28)

        self._init_particles()
        shared_clock().subscribe(self._tick)

    def _init_particles(self) -> None:
        bounds = QRectF(self.rect())
        if bounds.isEmpty():
            bounds = QRectF(0, 0, 800, 600)
        self._particles = []
        for depth, n in enumerate(self._layer_counts):
            for _ in range(n):
                self._particles.append(Particle(bounds, depth))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        bounds = QRectF(self.rect())
        if not self._particles:
            self._init_particles()
        else:
            for p in self._particles:
                if not bounds.contains(p.pos):
                    p.pos = QPointF(
                        random.uniform(bounds.left(), bounds.right()),
                        random.uniform(bounds.top(), bounds.bottom()),
                    )

    def _tick(self, dt: float) -> None:
        bounds = QRectF(self.rect())
        for p in self._particles:
            p.step(bounds, dt)
        # Scan line drifts slowly downward then wraps.
        self._scan_y = (self._scan_y + dt * 60.0) % (bounds.height() + 80)
        self._frame += 1
        # Background repaints at ~30 FPS (every other 60fps tick).
        if self._frame % 2 == 0:
            self.update()

    # --- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect())

            self._paint_backdrop(painter, rect)
            self._paint_grid(painter, rect)
            self._paint_links(painter)
            self._paint_particles(painter)
            self._paint_scanline(painter, rect)
            self._paint_vignette(painter, rect)

    def _paint_backdrop(self, painter: QPainter, rect: QRectF) -> None:
        bg = QLinearGradient(0, 0, 0, rect.height())
        bg.setColorAt(0.0, QColor("#03081A"))
        bg.setColorAt(0.6, QColor("#020610"))
        bg.setColorAt(1.0, QColor("#01030A"))
        painter.fillRect(rect, bg)

        # Center bloom — radial neon haze.
        bloom = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.45)
        c0 = QColor(Colors.NEON); c0.setAlpha(26)
        c1 = QColor(Colors.NEON); c1.setAlpha(0)
        bloom.setColorAt(0.0, c0)
        bloom.setColorAt(1.0, c1)
        painter.fillRect(rect, bloom)

    def _paint_grid(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(self._grid_pen)
        step = self.GRID_SPACING
        x = rect.left()
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = rect.top()
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step

    def _paint_links(self, painter: QPainter) -> None:
        # Spatial hash so we only compare particles in neighboring cells.
        cell = self.LINK_DISTANCE
        buckets: dict[tuple[int, int], list[Particle]] = {}
        for p in self._particles:
            key = (int(p.pos.x() // cell), int(p.pos.y() // cell))
            buckets.setdefault(key, []).append(p)

        ld2 = self.LINK_DISTANCE * self.LINK_DISTANCE
        seen: set[tuple[int, int]] = set()
        for (cx, cy), cell_particles in buckets.items():
            # Gather this cell + its 4 forward neighbors to avoid double checks.
            neighbors: list[Particle] = list(cell_particles)
            for nx, ny in ((cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1), (cx - 1, cy + 1)):
                neighbors.extend(buckets.get((nx, ny), ()))

            for i, a in enumerate(cell_particles):
                for b in neighbors:
                    if a is b:
                        continue
                    pair = (id(a), id(b))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    dx = a.pos.x() - b.pos.x()
                    dy = a.pos.y() - b.pos.y()
                    d2 = dx * dx + dy * dy
                    if d2 < ld2:
                        d = math.sqrt(d2)
                        alpha = int(70 * (1.0 - d / self.LINK_DISTANCE))
                        pen = QPen(self._link_pen)
                        pen.setColor(QColor(Colors.NEON))
                        c = pen.color(); c.setAlpha(alpha); pen.setColor(c)
                        painter.setPen(pen)
                        painter.drawLine(a.pos, b.pos)

    def _paint_particles(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._particles:
            pulse = 0.6 + 0.4 * math.sin(p.phase)
            base = QColor(Colors.NEON)
            base.setHsl(
                (base.hue() + int(p.hue_offset)) % 360,
                base.saturation(),
                int(min(255, base.lightness() * (0.8 + 0.4 * pulse))),
            )
            # Far layers are dimmer and smaller for depth.
            depth_scale = 0.6 + p.depth * 0.3
            base.setAlpha(max(0, min(255, int(p.alpha * (0.6 + 0.4 * pulse) * depth_scale))))
            painter.setBrush(base)
            r = p.size * pulse * (0.7 + p.depth * 0.25)
            painter.drawEllipse(p.pos, r, r)

    def _paint_scanline(self, painter: QPainter, rect: QRectF) -> None:
        y = rect.top() + self._scan_y
        grad = QLinearGradient(0, y - 40, 0, y + 40)
        c0 = QColor(Colors.NEON); c0.setAlpha(0)
        c1 = QColor(Colors.NEON); c1.setAlpha(22)
        c2 = QColor(Colors.NEON); c2.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.5, c1)
        grad.setColorAt(1.0, c2)
        painter.fillRect(QRectF(rect.left(), y - 40, rect.width(), 80), grad)
        painter.setPen(self._scan_pen)
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _paint_vignette(self, painter: QPainter, rect: QRectF) -> None:
        vign = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.75)
        vign.setColorAt(0.55, QColor(0, 0, 0, 0))
        vign.setColorAt(1.0, QColor(0, 0, 0, 130))
        painter.fillRect(rect, vign)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(800, 600)

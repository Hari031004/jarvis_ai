"""Animated circular voice visualizer (Iron Man HUD style).

Upgrades:
- Breathing pulse: the whole orb slowly expands/contracts on its own rhythm
  so it feels alive even when idle.
- Layered energy rings: three counter-rotating rings (solid, dashed, ticked)
  at different radii and speeds for depth.
- Neon bloom: a multi-stop radial glow behind the core.
- Animated inner core: a pulsing bright center with a slow color shimmer.
- Anti-jitter: bar levels use frame-rate-independent damping (damp()) so the
  smoothing speed is identical regardless of frame rate, and the random
  component is bounded to avoid popping.
- Shared clock: one driver for the whole app, 60 FPS.
- AssistantState: Maps assistant state directly to visual animation parameters.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ui.animations import damp, shared_clock
from ui.theme import Colors
from ui.utils import neon_pen, glow_paint, draw_arc_text

from assistant.core.events import AssistantState


@dataclass(frozen=True, slots=True)
class OrbStateConfig:
    """Animation parameters for the visualizer mapping to an AssistantState."""
    active: bool
    speaking: bool
    label: str
    primary: str
    secondary: str
    speed_mul: float
    bar_gain: float
    breath_rate: float


# ════════════════════════════════════════════════════════════════════════════
# Configuration table — maps AssistantState directly to visual parameters
# ════════════════════════════════════════════════════════════════════════════

_ORB_CONFIGS: dict[AssistantState, OrbStateConfig] = {
    AssistantState.SLEEPING: OrbStateConfig(
        active=False, speaking=False,
        label="STANDBY",
        primary=Colors.TEXT_MUTED,
        secondary=Colors.TEXT_MUTED,
        speed_mul=0.30,
        bar_gain=0.25,
        breath_rate=0.40,
    ),
    AssistantState.IDLE: OrbStateConfig(
        active=True, speaking=False,
        label="IDLE",
        primary=Colors.NEON,
        secondary=Colors.ACCENT,
        speed_mul=1.00,
        bar_gain=1.00,
        breath_rate=1.00,
    ),
    AssistantState.LISTENING: OrbStateConfig(
        active=True, speaking=True,
        label="LISTENING",
        primary=Colors.NEON,
        secondary=Colors.ACCENT,
        speed_mul=1.20,
        bar_gain=1.20,
        breath_rate=1.20,
    ),
    AssistantState.THINKING: OrbStateConfig(
        active=True, speaking=False,
        label="PROCESSING",
        primary=Colors.WARNING,
        secondary=Colors.WARNING,
        speed_mul=1.50,
        bar_gain=0.55,
        breath_rate=1.60,
    ),
    AssistantState.SPEAKING: OrbStateConfig(
        active=True, speaking=True,
        label="SPEAKING",
        primary=Colors.ACCENT,
        secondary=Colors.NEON,
        speed_mul=1.00,
        bar_gain=1.50,
        breath_rate=1.00,
    ),
    AssistantState.EXECUTING: OrbStateConfig(
        active=True, speaking=False,
        label="EXECUTING",
        primary=Colors.WARNING,
        secondary=Colors.WARNING,
        speed_mul=1.80,
        bar_gain=0.70,
        breath_rate=1.40,
    ),
    AssistantState.ERROR: OrbStateConfig(
        active=True, speaking=False,
        label="FAULT",
        primary=Colors.DANGER,
        secondary=Colors.DANGER,
        speed_mul=0.70,
        bar_gain=0.45,
        breath_rate=0.80,
    ),
}


class VoiceVisualizer(QWidget):
    """Concentric ring visualizer with reactive bars, orbiting dots and arc text."""

    BARS = 72

    def __init__(self, parent: QWidget | None = None, size: int = 320) -> None:
        super().__init__(parent)
        self._fixed = QSize(size, size)
        self.setFixedSize(size, size)

        self._levels = [0.0] * self.BARS
        self._targets = [0.0] * self.BARS
        self._phase = 0.0
        self._breath = 0.0          # slow breathing cycle 0..1
        self._orbit_phase = 0.0
        self._ring_rot_a = 0.0      # outer ring rotation
        self._ring_rot_b = 0.0      # middle ring rotation (counter)
        self._ring_rot_c = 0.0      # inner tick ring rotation
        self._active = True
        self._speaking = True

        self._current_state: AssistantState = AssistantState.IDLE
        self._cfg: OrbStateConfig = _ORB_CONFIGS[AssistantState.IDLE]
        self._primary: str = self._cfg.primary
        self._secondary: str = self._cfg.secondary

        shared_clock().subscribe(self._tick)

    # ── Public state API ──────────────────────────────────────────────────────

    def set_state(self, state: AssistantState) -> None:
        """Switch visual style and configuration based on AssistantState.

        Reuses the existing set_active() and set_speaking() contracts.
        """
        if state == self._current_state:
            return
        self._current_state = state
        cfg = _ORB_CONFIGS.get(state, _ORB_CONFIGS[AssistantState.IDLE])
        self._cfg = cfg
        self._primary = cfg.primary
        self._secondary = cfg.secondary
        self.set_active(cfg.active)
        self.set_speaking(cfg.speaking)

    # ── Existing public API (preserved) ──────────────────────────────────────

    def set_active(self, active: bool) -> None:
        """Enable or disable energised bar animation."""
        self._active = active
        self.update()

    def set_speaking(self, speaking: bool) -> None:
        """Enable or disable the speech-energy bar pattern."""
        self._speaking = speaking

    # ── Clock tick ───────────────────────────────────────────────────────────

    def _tick(self, dt: float) -> None:
        s = self._cfg.speed_mul
        b = self._cfg.breath_rate

        self._phase += dt * 3.6 * s
        self._breath = (self._breath + dt * (1.0 / 6.0) * b) % 1.0
        self._orbit_phase += dt * 1.2 * s
        self._ring_rot_a = (self._ring_rot_a + dt *  9.0 * s) % 360.0
        self._ring_rot_b = (self._ring_rot_b - dt * 14.0 * s) % 360.0
        self._ring_rot_c = (self._ring_rot_c + dt * 20.0 * s) % 360.0

        breath_gain = 0.75 + 0.25 * (0.5 - 0.5 * math.cos(self._breath * math.tau))
        gain = self._cfg.bar_gain

        for i in range(self.BARS):
            if self._active and self._speaking:
                wave = 0.5 + 0.5 * math.sin(self._phase + i * 0.25)
                noise = random.random() * 0.6
                base = 0.3 + 0.7 * wave
                self._targets[i] = max(
                    0.05, min(1.0, (base * 0.5 + noise * 0.5) * breath_gain * gain)
                )
            else:
                self._targets[i] = (
                    0.08 + 0.05 * math.sin(self._phase + i * 0.4)
                ) * breath_gain * gain
            self._levels[i] = damp(self._levels[i], self._targets[i], 0.09, dt)
        self.update()

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(self.rect())
            center = rect.center()
            min_side = min(rect.width(), rect.height())
            breath = 0.97 + 0.06 * (0.5 - 0.5 * math.cos(self._breath * math.tau))
            r_outer = min_side * 0.46 * breath
            r_mid   = min_side * 0.40 * breath
            r_inner = min_side * 0.30
            r_core  = min_side * 0.16 * (0.9 + 0.2 * (0.5 - 0.5 * math.cos(self._breath * math.tau)))

            self._paint_bloom(painter, center, min_side)
            self._paint_ring_a(painter, center, r_outer + 10)
            self._paint_ring_b(painter, center, r_mid + 4)
            self._paint_outer_ring(painter, center, r_outer)
            self._paint_bars(painter, center, r_inner, r_outer)
            self._paint_inner_ring(painter, center, r_inner)
            self._paint_orbiters(painter, center, r_inner - 6)
            self._paint_core(painter, center, r_core)
            self._paint_arc_text(painter, center, r_outer + 4)
            self._paint_ticks(painter, center, r_outer)
            self._paint_status(painter, center, r_core)

    def _paint_bloom(self, painter: QPainter, center: QPointF, min_side: float) -> None:
        for r_mul, _ in ((0.62, 18), (0.5, 28), (0.38, 40)):
            painter.setBrush(glow_paint(painter, center, min_side * r_mul, self._primary))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, min_side * r_mul, min_side * r_mul)

    def _paint_ring_a(self, painter: QPainter, center: QPointF, r: float) -> None:
        painter.save()
        painter.translate(center)
        painter.rotate(self._ring_rot_a)
        pen = neon_pen(self._primary, 1.2, 90)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([2, 6])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r, r)
        painter.restore()

    def _paint_ring_b(self, painter: QPainter, center: QPointF, r: float) -> None:
        painter.save()
        painter.translate(center)
        painter.rotate(self._ring_rot_b)
        pen = neon_pen(self._secondary, 1.0, 70)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r, r)
        painter.restore()

    def _paint_outer_ring(self, painter: QPainter, center: QPointF, r: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(neon_pen(self._primary, 1.0, 70))
        painter.drawEllipse(center, r, r)

    def _paint_bars(self, painter: QPainter, center: QPointF,
                    r_inner: float, r_outer: float) -> None:
        span = r_outer - r_inner
        for i in range(self.BARS):
            angle = (i / self.BARS) * 360.0
            rad = math.radians(angle - 90)
            lvl = self._levels[i]
            bar_len = span * lvl
            x0 = center.x() + r_inner * math.cos(rad)
            y0 = center.y() + r_inner * math.sin(rad)
            x1 = center.x() + (r_inner + bar_len) * math.cos(rad)
            y1 = center.y() + (r_inner + bar_len) * math.sin(rad)
            alpha = int(120 + 135 * lvl)
            painter.setPen(neon_pen(self._primary, 2.2, alpha))
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    def _paint_inner_ring(self, painter: QPainter, center: QPointF, r: float) -> None:
        painter.setPen(neon_pen(self._secondary, 1.4, 160))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, r, r)

    def _paint_orbiters(self, painter: QPainter, center: QPointF, r: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for k in range(3):
            ang = self._orbit_phase * (1 + k * 0.3) * 360.0 + k * 120.0
            rad = math.radians(ang - 90)
            ox = center.x() + r * math.cos(rad)
            oy = center.y() + r * math.sin(rad)
            halo = QRadialGradient(QPointF(ox, oy), 6)
            hc  = QColor(self._primary); hc.setAlpha(120)
            hc2 = QColor(self._primary); hc2.setAlpha(0)
            halo.setColorAt(0.0, hc)
            halo.setColorAt(1.0, hc2)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(ox, oy), 6, 6)
            painter.setBrush(QColor(self._primary))
            painter.drawEllipse(QPointF(ox, oy), 2.6, 2.6)

    def _paint_core(self, painter: QPainter, center: QPointF, r_core: float) -> None:
        pulse = 0.7 + 0.3 * math.sin(self._phase * 1.5)
        hue = (int(self._breath * 360 * 0.15)) % 360
        core_color = QColor(self._primary)
        core_color.setHsl(hue, core_color.saturation(), core_color.lightness())

        core_grad = QRadialGradient(center, r_core * 1.4)
        c0 = QColor(core_color); c0.setAlpha(int(220 * pulse))
        c1 = QColor(core_color); c1.setAlpha(0)
        core_grad.setColorAt(0.0, c0)
        core_grad.setColorAt(1.0, c1)
        painter.setBrush(core_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, r_core * 1.4, r_core * 1.4)

        painter.setBrush(QColor(self._secondary))
        painter.drawEllipse(center, r_core * 0.45, r_core * 0.45)

    def _paint_arc_text(self, painter: QPainter, center: QPointF, r: float) -> None:
        draw_arc_text(
            painter,
            "J.A.R.V.I.S -- AUDIO ACTIVE -- ",
            center,
            r,
            start_deg=-110,
            span_deg=220,
            color=Colors.NEON_DIM,
            font_size=8,
        )

    def _paint_ticks(self, painter: QPainter, center: QPointF, r_outer: float) -> None:
        painter.save()
        painter.translate(center)
        painter.rotate(self._ring_rot_c)
        painter.setPen(neon_pen(self._primary, 1.0, 120))
        ticks = 24
        for t in range(ticks):
            ang = math.radians((t / ticks) * 360.0 - 90)
            r1 = r_outer + 2
            r2 = r_outer + (6 if t % 3 == 0 else 3)
            painter.drawLine(
                QPointF(r1 * math.cos(ang), r1 * math.sin(ang)),
                QPointF(r2 * math.cos(ang), r2 * math.sin(ang)),
            )
        painter.restore()

    def _paint_status(self, painter: QPainter, center: QPointF, r_core: float) -> None:
        painter.setPen(QColor(self._primary))
        painter.setFont(QFont("Orbitron", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(center.x() - 60, center.y() + r_core + 6, 120, 16),
            Qt.AlignmentFlag.AlignCenter,
            self._cfg.label,
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._fixed

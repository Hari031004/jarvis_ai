"""Shared animation primitives for the JARVIS HUD.

Centralizes time-based easing and a single driver so that every animated
widget advances from the same clock instead of running its own QTimer.
This keeps repaints synchronized and makes 60 FPS achievable with one
rhythm rather than five independent ones.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QObject
from PySide6.QtGui import QColor, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


def ease_out_cubic(t: float) -> float:
    """Decelerating curve — fast start, smooth landing."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_quint(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 5


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def damp(current: float, target: float, smoothing: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing toward a target.

    smoothing ~ how many seconds to close ~63% of the gap. Lower = snappier.
    """
    if dt <= 0:
        return current
    t = 1.0 - math.exp(-dt / max(smoothing, 1e-4))
    return current + (target - current) * t


def neon_ramp(color: str, steps: int = 6, peak_alpha: int = 220) -> list[QColor]:
    """Build a vertical neon glow ramp (top bright -> bottom transparent)."""
    out: list[QColor] = []
    base = QColor(color)
    for i in range(steps):
        c = QColor(base)
        c.setAlpha(int(peak_alpha * (1.0 - i / max(1, steps - 1))))
        out.append(c)
    return out


def vertical_glow(x: float, top: float, w: float, h: float, color: str,
                  peak_alpha: int = 120) -> QLinearGradient:
    g = QLinearGradient(x, top, x, top + h)
    c0 = QColor(color); c0.setAlpha(peak_alpha)
    c1 = QColor(color); c1.setAlpha(0)
    g.setColorAt(0.0, c0)
    g.setColorAt(1.0, c1)
    return g


def radial_glow(cx: float, cy: float, r: float, color: str,
                peak_alpha: int = 120) -> QRadialGradient:
    g = QRadialGradient(QPointF(cx, cy), r)
    c0 = QColor(color); c0.setAlpha(peak_alpha)
    c1 = QColor(color); c1.setAlpha(0)
    g.setColorAt(0.0, c0)
    g.setColorAt(1.0, c1)
    return g


class AnimationClock(QObject):
    """Single shared clock that drives all registered subscribers.

    Subscribers receive a tick carrying the elapsed seconds since the last
    frame. This replaces N independent QTimers with one ~60 FPS driver,
    cutting timer overhead and synchronizing repaints.
    """

    FRAME_MS = 16  # ~60 FPS target

    tick = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._emit)
        self._last: float = 0.0
        self._subscribers: list[Callable[[float], None]] = []

    def subscribe(self, fn: Callable[[float], None]) -> None:
        if fn not in self._subscribers:
            self._subscribers.append(fn)
        if not self._timer.isActive():
            self._timer.start()

    def unsubscribe(self, fn: Callable[[float], None]) -> None:
        if fn in self._subscribers:
            self._subscribers.remove(fn)
        if not self._subscribers and self._timer.isActive():
            self._timer.stop()

    def _emit(self) -> None:
        # Use frame interval as a stable dt to avoid jitter from system clock.
        dt = self.FRAME_MS / 1000.0
        for fn in list(self._subscribers):
            fn(dt)

    def stop(self) -> None:
        self._timer.stop()


# Global singleton — one clock for the whole app.
_clock: AnimationClock | None = None


def shared_clock() -> AnimationClock:
    global _clock
    if _clock is None:
        _clock = AnimationClock()
    return _clock


def fade_in(widget: QWidget, duration_ms: int = 350,
            target_opacity: float = 1.0) -> None:
    """Apply a simple opacity fade-in using QGraphicsOpacityEffect.

    Uses a QTimer-driven ramp rather than QPropertyAnimation so it stays
    compatible with translucent WA_TranslucentBackground widgets.
    """
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)

    state = {"t": 0.0}
    step_ms = 16

    def _step() -> None:
        state["t"] += step_ms / duration_ms
        p = ease_out_cubic(state["t"])
        eff.setOpacity(target_opacity * p)
        if state["t"] >= 1.0:
            eff.setOpacity(target_opacity)
            t.stop()
            # Release the effect once settled so paint performance is unaffected.
            widget.setGraphicsEffect(None)

    t = QTimer(widget)
    t.setInterval(step_ms)
    t.timeout.connect(_step)
    t.start()


def slide_in(widget: QWidget, duration_ms: int = 400,
             direction: str = "right") -> None:
    """Slide a page in from the given direction with a gentle ease."""
    target_pos = widget.pos()
    w = widget.width()
    h = widget.height()
    # Entry offset — page starts displaced and settles into place.
    offsets = {
        "right":  (-w // 5, 0),
        "left":   ( w // 5, 0),
        "down":   (0, -h // 5),
        "up":     (0,  h // 5),
    }
    offset_x, offset_y = offsets.get(direction, (-w // 5, 0))

    state = {"t": 0.0}
    step_ms = 16

    def _step() -> None:
        state["t"] += step_ms / duration_ms
        p = ease_out_cubic(state["t"])
        inv = 1.0 - p
        widget.move(target_pos.x() + int(offset_x * inv),
                    target_pos.y() + int(offset_y * inv))
        if state["t"] >= 1.0:
            widget.move(target_pos)
            t.stop()

    t = QTimer(widget)
    t.setInterval(step_ms)
    t.timeout.connect(_step)
    t.start()

"""Sidebar navigation with brand, nav buttons and status footer.

Polish:
- Icon glyph vertically centered inside its 22px slot (was top-clipped).
- Nav button spacing harmonized with the 16px content gutter.
- Status footer: a small custom-painted pulsing dot paired with the ONLINE
  label, driven by the shared clock so it breathes in sync with the rest of
  the HUD instead of being a static character glyph.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ui.animations import shared_clock
from ui.theme import Colors


class _PulseDot(QWidget):
    """A tiny breathing status dot."""

    def __init__(self, color: str = Colors.SUCCESS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = color
        self._phase = 0.0
        shared_clock().subscribe(self._tick)

    def _tick(self, dt: float) -> None:
        self._phase += dt * 2.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            pulse = 0.5 + 0.5 * math.sin(self._phase)
            # Outer halo
            halo = QColor(self._color); halo.setAlpha(int(60 + 60 * pulse))
            painter.setBrush(halo)
            painter.drawEllipse(0, 0, 14, 14)
            # Core
            painter.setBrush(QColor(self._color))
            painter.drawEllipse(4, 4, 6, 6)


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)
        ic = QLabel(icon)
        ic.setFixedSize(22, 22)
        ic.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        ic.setStyleSheet(f"color:{Colors.NEON}; font-size:16px;")
        lbl = QLabel(label)
        lbl.setStyleSheet("color:inherit; font-size:13px; letter-spacing:2px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(ic)
        lay.addWidget(lbl)
        lay.addStretch()


class SideBar(QFrame):
    nav_requested = Signal(str)

    PAGES = [
        ("◆", "DASHBOARD", "dashboard"),
        ("✦", "AI CHAT", "chat"),
        ("◉", "VOICE LOG", "voice"),
        ("▌", "SYSTEMS", "systems"),
        ("≈", "WEATHER", "weather"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SideBar")
        self.setFixedWidth(220)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 18, 16, 18)
        outer.setSpacing(10)

        # Brand
        brand_wrap = QVBoxLayout()
        brand_wrap.setSpacing(2)
        brand = QLabel("J.A.R.V.I.S")
        brand.setObjectName("Brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag = QLabel("JUST A RATHER VERY INTELLIGENT SYSTEM")
        tag.setObjectName("Subtitle")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setWordWrap(True)
        brand_wrap.addWidget(brand)
        brand_wrap.addWidget(tag)
        outer.addLayout(brand_wrap)

        outer.addSpacing(14)

        # Nav
        self._buttons: dict[str, NavButton] = {}
        for icon, label, key in self.PAGES:
            btn = NavButton(icon, label)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self._buttons[key] = btn
            outer.addWidget(btn)

        outer.addStretch()

        # Status footer: pulsing dot + ONLINE label + version
        status_wrap = QVBoxLayout()
        status_wrap.setSpacing(6)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        dot = _PulseDot(Colors.SUCCESS)
        status_lbl = QLabel("ONLINE")
        status_lbl.setStyleSheet(
            f"color:{Colors.SUCCESS}; font-size:11px; letter-spacing:2px;"
        )
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch()
        status_row.addWidget(dot)
        status_row.addWidget(status_lbl)
        status_row.addStretch()
        status_wrap.addLayout(status_row)
        version = QLabel("v 4.2.0  //  STARK IND.")
        version.setObjectName("Subtitle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_wrap.addWidget(version)
        outer.addLayout(status_wrap)

        self._select("dashboard")

    def _select(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
        self.nav_requested.emit(key)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(220, 600)

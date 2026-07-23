"""Voice command history panel with status badges and filter chips."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import Colors


class _StatusDot(QWidget):
    def __init__(self, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = status
        self.setFixedSize(12, 12)

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = {
                "ok": Colors.SUCCESS,
                "warn": Colors.WARNING,
                "err": Colors.DANGER,
            }.get(self._status, Colors.NEON)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(1, 1, 10, 10)
            # Outer ring
            ring = QColor(color)
            ring.setAlpha(80)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ring, 1.4))
            painter.drawEllipse(0, 0, 12, 12)


class VoiceHistoryPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("VOICE LOG")
        title.setObjectName("Title")
        sub = QLabel("COMMAND ARCHIVE")
        sub.setObjectName("Subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(sub)
        outer.addLayout(header)

        # Filter chips
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label, key in [("ALL", "all"), ("OK", "ok"), ("WARN", "warn"), ("FAIL", "err")]:
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setProperty("chip", key)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(26)
            chips.addWidget(chip)
        chips.addStretch()
        outer.addLayout(chips)

        self.list = QListWidget()
        self.list.setObjectName("HistoryList")
        outer.addWidget(self.list, 1)

        footer = QHBoxLayout()
        count = QLabel("0 COMMANDS")
        count.setObjectName("Subtitle")
        self._count = count
        clear = QPushButton("CLEAR LOG")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.addWidget(count)
        footer.addStretch()
        footer.addWidget(clear)
        outer.addLayout(footer)

        self._seed()

    def _seed(self) -> None:
        sample = [
            ("Turn on the workshop lights", "09:42:11", "ok"),
            ("Run diagnostic on Mark 42", "09:41:58", "ok"),
            ("Open suit deployment bay", "09:41:30", "ok"),
            ("Sync with Stark Industries servers", "09:40:12", "warn"),
            ("Initiate flight protocol delta", "09:38:04", "ok"),
            ("Recharge arc reactor to full", "09:36:55", "ok"),
            ("Engage perimeter defenses", "09:35:21", "err"),
            ("Play AC/DC highway to hell", "09:33:10", "ok"),
        ]
        for cmd, ts, status in sample:
            self._add(cmd, ts, status)
        self._count.setText(f"{self.list.count()} COMMANDS")

    def add_entry(self, command: str, timestamp: str, status: str) -> None:
        """Public API to append a new voice log entry and update the HUD count label."""
        self._add(command, timestamp, status)
        self._count.setText(f"{self.list.count()} COMMANDS")


    def _add(self, command: str, timestamp: str, status: str) -> None:
        row = QWidget()
        row.setMinimumHeight(48)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)
        dot = _StatusDot(status)
        lay.addWidget(dot)
        col = QVBoxLayout()
        col.setSpacing(2)
        cmd_lbl = QLabel(command)
        cmd_lbl.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; font-size:13px;")
        ts_lbl = QLabel(timestamp)
        ts_lbl.setStyleSheet(f"color:{Colors.TEXT_MUTED}; font-size:10px; letter-spacing:1px;")
        col.addWidget(cmd_lbl)
        col.addWidget(ts_lbl)
        lay.addLayout(col)
        lay.addStretch()
        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(420, 520)

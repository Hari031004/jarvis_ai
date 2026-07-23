"""AI chat panel with message bubbles, typing indicator and streaming reply.

Upgrades:
- Typing indicator: three pulsing dots shown while JARVIS is "thinking",
  driven by the shared clock so they animate at 60 FPS in sync with the rest
  of the HUD.
- Streaming reply: the canned response is revealed character-by-character
  with a soft caret, giving the feel of a live LLM stream (no backend logic).
- Smooth auto-scroll: the view glides to the bottom on new content instead of
  snapping, using frame-rate-independent damping.
- Bubble styling refined for clearer hierarchy (sender label / body / time).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from ui.animations import shared_clock
from ui.theme import Colors

from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, MessagePayload



def _bubble_html(role: str, text: str) -> str:
    if role == "jarvis":
        color = Colors.NEON
        name = "J.A.R.V.I.S"
        align = "left"
    else:
        color = Colors.ACCENT
        name = "YOU"
        align = "right"
    return (
        f"<div style='margin:8px 0;'>"
        f"<div style='color:{color}; font-family:Orbitron; font-size:9px; "
        f"letter-spacing:2px; text-align:{align};'>{name}</div>"
        f"<div style='color:{Colors.TEXT_PRIMARY}; font-size:13px; "
        f"padding:8px 12px; border:1px solid {Colors.BORDER_SOFT}; "
        f"border-radius:10px; background:rgba(2,8,18,160); text-align:{align};'>"
        f"{text}</div></div>"
    )


class _TypingDots(QWidget):
    """Three neon dots that pulse in sequence to indicate JARVIS is typing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self._phase = 0.0
        self._visible = False
        shared_clock().subscribe(self._tick)

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        self.update()

    def _tick(self, dt: float) -> None:
        if not self._visible:
            return
        self._phase += dt * 4.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            rect = self.rect()
            cx = rect.width() / 2 - 16
            cy = rect.height() / 2
            for i in range(3):
                # Each dot is phase-offset so they ripple left to right.
                p = 0.5 + 0.5 * ((math.sin(self._phase - i * 0.5) + 1) * 0.5)
                alpha = int(80 + 160 * p)
                r = 3.0 + 1.2 * p
                c = QColor(Colors.NEON); c.setAlpha(alpha)
                painter.setBrush(c)
                painter.drawEllipse(int(cx + i * 12 - r), int(cy - r), int(r * 2), int(r * 2))


class ChatPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CardRaised")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("AI INTERFACE")
        title.setObjectName("Title")
        sub = QLabel("NEURAL LINK ONLINE")
        sub.setObjectName("Subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(sub)
        outer.addLayout(header)

        self.view = QTextEdit()
        self.view.setObjectName("ChatView")
        self.view.setReadOnly(True)
        outer.addWidget(self.view, 1)

        # Typing indicator row (hidden until a request is being processed).
        self._typing = _TypingDots()
        self._typing.set_visible(False)
        outer.addWidget(self._typing)

        # Input row
        row = QHBoxLayout()
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setObjectName("ChatInput")
        self.input.setPlaceholderText("Ask J.A.R.V.I.S...")
        self.input.returnPressed.connect(self._on_send)
        self.send = QPushButton("SEND")
        self.send.setObjectName("SendButton")
        self.send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send.clicked.connect(self._on_send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        outer.addLayout(row)

        # Streaming state
        self._stream_buf = ""
        self._stream_role = "jarvis"
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(28)
        self._stream_timer.timeout.connect(self._stream_tick)

        self._seed()

    def _seed(self) -> None:
        self._append("jarvis", "Systems online. How may I assist you, sir?")
        self._append("jarvis", "Voice and text interfaces are active.")

    def _append(self, role: str, text: str) -> None:
        self.view.append(_bubble_html(role, text))
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        # Smooth-scroll: jump to bottom; QTextEdit handles the visual glide
        # via its own viewport update. Using moveCursor is the reliable path.
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.view.moveCursor(QTextCursor.MoveOperation.End)

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        
        # Publish the user message to the EventBus so the backend picks it up.
        publish_event(
            EventType.USER_MESSAGE,
            payload=MessagePayload(text=text, source=EventSource.UI),
            source=EventSource.UI
        )

    # ── Public API methods called by the adapter ────────────────────────────

    def add_user_message(self, text: str) -> None:
        """Directly append a user message bubble."""
        self._append("user", text)

    def add_assistant_message(self, text: str) -> None:
        """Directly append or stream an assistant message bubble."""
        # Stop any active dummy streams.
        self._stream_timer.stop()
        self._typing.set_visible(False)
        self._append("jarvis", text)

    def begin_stream(self) -> None:
        """Show the typing/thinking indicator."""
        self._typing.set_visible(True)
        self._stream_buf = ""
        self.view.append(_bubble_html("jarvis", ""))
        self._scroll_to_bottom()

    def append_token(self, token: str) -> None:
        """Append a streaming token to the last bubble."""
        self._stream_buf += token
        visible_text = self._stream_buf + "▌"
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.insertHtml(_bubble_html("jarvis", visible_text))
        self._scroll_to_bottom()

    def finish_stream(self) -> None:
        """Hide the typing indicator and clean up the cursor."""
        self._typing.set_visible(False)
        if self._stream_buf:
            cursor = self.view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.insertHtml(_bubble_html("jarvis", self._stream_buf))
            self._scroll_to_bottom()
            self._stream_buf = ""


    def _begin_reply(self, text: str) -> None:
        self._stream_role = "jarvis"
        self._stream_buf = ""
        self._stream_target = text
        self._stream_index = 0
        self._typing.set_visible(True)
        # Small "thinking" delay before streaming starts.
        QTimer.singleShot(450, self._stream_start)

    def _stream_start(self) -> None:
        # Insert the initial (empty) JARVIS bubble that we'll grow into.
        self.view.append(_bubble_html(self._stream_role, ""))
        self._stream_timer.start()

    def _stream_tick(self) -> None:
        if self._stream_index >= len(self._stream_target):
            self._stream_timer.stop()
            self._typing.set_visible(False)
            return
        # Reveal a few characters per tick for a natural typing cadence.
        step = max(1, len(self._stream_target) // 60)
        self._stream_index = min(
            len(self._stream_target), self._stream_index + step
        )
        visible_text = self._stream_target[:self._stream_index] + "▌"
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.insertHtml(_bubble_html(self._stream_role, visible_text))
        self._scroll_to_bottom()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(440, 520)

"""Frameless JARVIS main window with acrylic/glass backdrop and HUD dashboard."""
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import Colors
from ui.utils import paint_hud_frame
from ui.animations import fade_in, slide_in
from ui.widgets.particle_field import ParticleField
from ui.widgets.voice_visualizer import VoiceVisualizer
from ui.widgets.clock import HUDClock, DigitalClock
from ui.widgets.weather import WeatherWidget
from ui.widgets.system_monitor import SystemMonitor
from ui.panels.sidebar import SideBar
from ui.panels.chat_panel import ChatPanel
from ui.panels.voice_history import VoiceHistoryPanel

# AssistantState and Notification are pure-data types from the event system.
# They have zero UI-framework dependencies and are safe to import here.
from assistant.core.events import AssistantState, Notification


# ---------------------------------------------------------------------------
# State → (title-bar label, title-bar colour)
# Used by JarvisWindow.set_state() to update the HUD header in one lookup.
# ---------------------------------------------------------------------------
_STATE_DISPLAY: dict[AssistantState, tuple[str, str]] = {
    AssistantState.SLEEPING:  ("SLEEPING · STANDBY",   Colors.TEXT_MUTED),
    AssistantState.IDLE:      ("SYSTEMS NOMINAL",      Colors.SUCCESS),
    AssistantState.LISTENING: ("LISTENING · ACTIVE",   Colors.NEON),
    AssistantState.THINKING:  ("PROCESSING REQUEST",   Colors.WARNING),
    AssistantState.SPEAKING:  ("SPEAKING",             Colors.ACCENT),
    AssistantState.EXECUTING: ("EXECUTING COMMAND",    Colors.WARNING),
    AssistantState.ERROR:     ("SYSTEM FAULT",         Colors.DANGER),
}


class _TitleBar(QFrame):

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(44)
        self._parent = parent
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(10)

        title = QLabel("J.A.R.V.I.S  //  COMMAND CENTER")
        title.setObjectName("Title")
        lay.addWidget(title)
        lay.addStretch()

        # Status label — updated by JarvisWindow.set_state().
        self.status_label = QLabel("SYSTEMS NOMINAL")
        self.status_label.setObjectName("Subtitle")
        self.status_label.setStyleSheet(f"color:{Colors.SUCCESS};")
        lay.addWidget(self.status_label)

        lay.addSpacing(16)

        for glyph, name, slot in [
            ("—", "MinBtn", self.window().showMinimized),
            ("▢", "MaxBtn", self._toggle_max),
            ("✕", "CloseBtn", self.window().close),
        ]:
            btn = QPushButton(glyph)
            btn.setObjectName("WindowBtn")
            btn.setProperty("name", name)
            if name == "CloseBtn":
                btn.setStyleSheet(
                    f"QPushButton#WindowBtn:hover{{color:{Colors.DANGER};"
                    f"background:rgba(255,77,94,40);}}"
                )
            btn.setFixedSize(34, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def _toggle_max(self) -> None:
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._toggle_max()

    def set_status(self, text: str, color: str) -> None:
        """Update the HUD header status label text and colour.

        Called by JarvisWindow.set_state() whenever the assistant state
        changes.  Both arguments come from the _STATE_DISPLAY lookup.

        Args:
            text:  Label string (e.g. ``"LISTENING · ACTIVE"``).
            color: CSS colour string from :class:`ui.theme.Colors`.
        """
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")


class Dashboard(QWidget):
    """The main HUD dashboard assembling all widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        grid = QVBoxLayout(self)
        grid.setContentsMargins(18, 18, 18, 18)
        grid.setSpacing(16)

        # Top row: visualizer + clock + weather
        top = QHBoxLayout()
        top.setSpacing(16)

        # Visualizer card
        vis_card = QFrame()
        vis_card.setObjectName("Card")
        vis_lay = QVBoxLayout(vis_card)
        vis_lay.setContentsMargins(12, 12, 12, 12)
        vis_lay.setSpacing(0)
        vis_header = QLabel("VOICE INTERFACE")
        vis_header.setObjectName("Title")
        vis_lay.addWidget(vis_header, 0, Qt.AlignmentFlag.AlignCenter)
        self.viz = VoiceVisualizer(size=300)
        vis_lay.addWidget(self.viz, 0, Qt.AlignmentFlag.AlignCenter)
        vis_lay.addStretch()
        top.addWidget(vis_card)

        # Right column: clock + weather
        right = QVBoxLayout()
        right.setSpacing(16)

        clock_card = QFrame()
        clock_card.setObjectName("Card")
        clock_lay = QVBoxLayout(clock_card)
        clock_lay.setContentsMargins(16, 14, 16, 14)
        clock_lay.setSpacing(6)
        ch = QLabel("CHRONOMETER")
        ch.setObjectName("Title")
        ch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_lay.addWidget(ch)
        self.hud_clock = HUDClock()
        clock_lay.addWidget(self.hud_clock, 0, Qt.AlignmentFlag.AlignCenter)
        self.digital_clock = DigitalClock()
        clock_lay.addWidget(self.digital_clock, 0, Qt.AlignmentFlag.AlignCenter)
        right.addWidget(clock_card)

        self.weather = WeatherWidget()
        right.addWidget(self.weather)
        right.addStretch()
        top.addLayout(right, 1)

        grid.addLayout(top, 1)

        # System monitor full width
        self.monitor = SystemMonitor()
        grid.addWidget(self.monitor)

        # Bottom row: chat + voice history
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.chat = ChatPanel()
        self.history = VoiceHistoryPanel()
        bottom.addWidget(self.chat, 1)
        bottom.addWidget(self.history, 1)
        grid.addLayout(bottom, 1)


class JarvisWindow(QFrame):
    """Frameless, translucent window hosting the HUD."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1320, 860)
        self.setMinimumSize(1120, 720)

        # Background particle field (behind the glass)
        self.particles = ParticleField(self, count=90)

        # Glass container
        self.glass = QFrame(self)
        self.glass.setObjectName("GlassRoot")

        root = QVBoxLayout(self.glass)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = _TitleBar(self.glass)
        root.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar = SideBar()
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pages: dict[str, QWidget] = {}
        self.dashboard = Dashboard()
        self.chat_page = self._wrap_card(ChatPanel())
        self.voice_page = self._wrap_card(VoiceHistoryPanel())
        self.systems_page = self._wrap_card(SystemMonitor())
        self.weather_page = self._wrap_card(WeatherWidget())
        for key, widget in [
            ("dashboard", self.dashboard),
            ("chat", self.chat_page),
            ("voice", self.voice_page),
            ("systems", self.systems_page),
            ("weather", self.weather_page),
        ]:
            self._pages[key] = widget
            self.stack.addWidget(widget)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        self.sidebar.nav_requested.connect(self._navigate)
        self._navigate("dashboard")
        self._first_show = True

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # Startup animation: fade the whole HUD in over ~500ms.
            fade_in(self.glass, duration_ms=500)

    def _wrap_card(self, inner: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addWidget(inner)
        return wrap

    def _navigate(self, key: str) -> None:
        page = self._pages.get(key, self.dashboard)
        if self.stack.currentWidget() is page:
            return
        self.stack.setCurrentWidget(page)
        # Page transition: gentle fade + slide-in so navigation feels alive.
        fade_in(page, duration_ms=320)
        slide_in(page, duration_ms=360, direction="right")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.particles.setGeometry(self.rect())
        self.glass.setGeometry(self.rect())

    def paintEvent(self, event) -> None:  # noqa: N802
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Acrylic base tint
            rect = self.rect().adjusted(2, 2, -2, -2)
            painter.setBrush(QColor(2, 8, 20, 120))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 16, 16)
            paint_hud_frame(painter, rect, Colors.NEON)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(1320, 860)

    # ── Bridge-facing public API ───────────────────────────────────────────
    # Called by PySideAdapter on the GUI thread.  All methods are defensive:
    # they check for sub-widget availability so the window works in
    # standalone (no-backend) mode and during the startup sequence.

    def set_state(self, state: AssistantState) -> None:
        """Propagate an assistant state change to all HUD sub-widgets.

        1. Updates the title-bar status label via _STATE_DISPLAY.
        2. Translates AssistantState → OrbMode via _STATE_TO_ORB and
           calls viz.set_mode() so the orb animates correctly.

        Args:
            state: The new :class:`~assistant.core.events.AssistantState`.
        """
        label, color = _STATE_DISPLAY.get(
            state, (state.value.upper(), Colors.TEXT_SECONDARY)
        )
        self.titlebar.set_status(label, color)

        viz = self.dashboard.viz
        if hasattr(viz, "set_state"):
            viz.set_state(state)


    def show_notification(self, notification: Notification) -> None:
        """Display a transient notification in the HUD.

        Stub — a toast / overlay widget will be wired here in a later step.
        Currently logs to the voice-history panel so nothing is silently lost.

        Args:
            notification: A :class:`~assistant.core.events.Notification`
                          payload with ``title``, ``message``, and
                          ``severity``.
        """
        # Delegate to voice history panel if available.
        history = self.dashboard.history
        if hasattr(history, "add_entry"):
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            history.add_entry(
                f"🔔 {notification.title}: {notification.message}", ts, "ok"
            )

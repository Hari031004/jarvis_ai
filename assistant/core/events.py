"""Strongly typed event types and payload models for JARVIS.

This module contains **only pure data definitions** — enums, dataclasses,
and the type alias for event handlers.  It has zero imports from the rest
of the project and zero framework dependencies (no PySide6, no psutil,
no Tkinter).

The EventBus and singleton are in ``assistant.core.event_bus``.

Contents
────────
  EventType              – StrEnum of every event kind (28 members)
  EventSource            – StrEnum of every publishing component
  AssistantState         – StrEnum of all operating states
  LogLevel               – StrEnum for log severity
  NotificationSeverity   – StrEnum for notification importance

  Typed payload dataclasses (13):
    StateChangePayload    BrowserPayload
    MessagePayload        AppPayload
    TokenPayload          MemoryPayload
    CommandPayload        SystemDiagnostics
    PlannerPayload        LogEntry
    AutomationPayload     Notification
    ErrorPayload

  AssistantEvent         – The single object flowing through the bus
  EventHandler           – Callable[[AssistantEvent], None]
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


# ════════════════════════════════════════════════════════════════════════════
# Enumerations
# ════════════════════════════════════════════════════════════════════════════


class EventType(str, Enum):
    """All canonical event types that flow through the JARVIS EventBus.

    Using ``(str, Enum)`` makes members directly comparable to their
    string values and usable as dict keys, while remaining fully typed.
    Compatible with Python 3.8 + (unlike StrEnum which requires 3.11).

    Grouped by subsystem:
        State · Wake · Recording · STT · LLM · Planner · TTS
        Messages · Automation · Browser · Memory · Diagnostics · Logging
    """

    # ── State ────────────────────────────────────────────────────────────────
    STATE_CHANGED     = "state.changed"
    SLEEP_ENTERED     = "state.sleep_entered"
    SLEEP_EXITED      = "state.sleep_exited"

    # ── Wake word ────────────────────────────────────────────────────────────
    WAKE_DETECTED     = "wake.detected"
    WAKE_LOST         = "wake.lost"

    # ── Recording / VAD ──────────────────────────────────────────────────────
    RECORDING_START   = "recording.start"
    RECORDING_END     = "recording.end"
    VOICE_INTERRUPTED = "voice.interrupted"

    # ── Speech-to-Text ───────────────────────────────────────────────────────
    STT_START         = "stt.start"
    STT_END           = "stt.end"

    # ── LLM ──────────────────────────────────────────────────────────────────
    LLM_START         = "llm.start"
    LLM_TOKEN         = "llm.token"
    LLM_END           = "llm.end"

    # ── Planner / intent ─────────────────────────────────────────────────────
    PLANNER_START     = "planner.start"
    PLANNER_END       = "planner.end"
    COMMAND_PARSED    = "command.parsed"

    # ── Text-to-Speech ───────────────────────────────────────────────────────
    TTS_START         = "tts.start"
    TTS_END           = "tts.end"

    # ── Messages ─────────────────────────────────────────────────────────────
    USER_MESSAGE      = "message.user"
    ASSISTANT_MESSAGE = "message.assistant"

    # ── Automation ───────────────────────────────────────────────────────────
    AUTOMATION_START  = "automation.start"
    AUTOMATION_END    = "automation.end"
    APP_OPENED        = "app.opened"

    # ── Browser ──────────────────────────────────────────────────────────────
    BROWSER_OPENED       = "browser.opened"
    BROWSER_NAVIGATED    = "browser.navigated"
    BROWSER_TAB_CHANGED  = "browser.tab_changed"

    # ── Memory ───────────────────────────────────────────────────────────────
    MEMORY_UPDATED    = "memory.updated"

    # ── Diagnostics ──────────────────────────────────────────────────────────
    SYSTEM_DIAG       = "system.diag"

    # ── Logging / Errors / Notifications ─────────────────────────────────────
    LOG               = "log"
    ERROR             = "error"
    NOTIFICATION      = "notification"


class EventSource(str, Enum):
    """Identifies the JARVIS component that published an AssistantEvent.

    Using an enum instead of a plain string prevents typos in source
    attribution and makes it easy to filter events by origin.
    """

    BRAIN      = "brain"        # AIBrain central loop
    WAKE_WORD  = "wake_word"    # WakeWordDetector
    LISTENER   = "listener"     # WakeListener (recording)
    STT        = "stt"          # SpeechToText (Whisper / NVIDIA)
    LLM        = "llm"          # LLMClient (Groq / OpenAI / …)
    TTS        = "tts"          # TextToSpeech (Edge TTS / SAPI)
    PLANNER    = "planner"      # AgentOrchestrator
    ROUTER     = "router"       # CommandRouter (intent matching)
    AUTOMATION = "automation"   # AutomationManager
    BROWSER    = "browser"      # BrowserController
    MEMORY     = "memory"       # ConversationMemory
    SYSTEM     = "system"       # SystemMonitorService
    VISION     = "vision"       # VisionService
    PLUGINS    = "plugins"      # PluginManager
    SECURITY   = "security"     # PermissionManager / AuditLogger
    UI         = "ui"           # UI layer (user typed into chat panel)
    BRIDGE     = "bridge"       # JarvisBridge
    UNKNOWN    = "unknown"      # Fallback / unspecified


class AssistantState(str, Enum):
    """All possible operating states of the JARVIS assistant.

    These are the states that drive orb animation, status labels, and
    toolbar button enable/disable logic.
    """

    SLEEPING  = "Sleeping"    # Waiting for wake word; low-power mic
    IDLE      = "Idle"        # Awake but not doing anything
    LISTENING = "Listening"   # Recording user utterance
    THINKING  = "Thinking"    # STT done; LLM / router processing
    SPEAKING  = "Speaking"    # TTS is playing audio
    EXECUTING = "Executing"   # Running automation / browser / system cmd
    ERROR     = "Error"       # Something went wrong


class LogLevel(str, Enum):
    """Severity levels for :class:`LogEntry` payloads."""

    DEBUG   = "debug"
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"


class NotificationSeverity(str, Enum):
    """Visual severity for user-facing :class:`Notification` payloads."""

    INFO    = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR   = "error"


# ════════════════════════════════════════════════════════════════════════════
# Typed payload dataclasses
# ════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class StateChangePayload:
    """Emitted with :attr:`EventType.STATE_CHANGED`."""

    new_state: AssistantState
    previous_state: Optional[AssistantState] = None
    context: str = ""                   # Human-readable reason / label


@dataclass(slots=True)
class MessagePayload:
    """Emitted with USER_MESSAGE and ASSISTANT_MESSAGE."""

    text: str
    source: EventSource = EventSource.UNKNOWN


@dataclass(slots=True)
class TokenPayload:
    """Emitted with :attr:`EventType.LLM_TOKEN` during streaming.

    Deferred to Phase 2; dataclass defined now for forward compatibility.
    """

    token: str
    index: int = 0                      # Position in the token stream


@dataclass(slots=True)
class CommandPayload:
    """Emitted with :attr:`EventType.COMMAND_PARSED`."""

    raw_text: str
    intent: str = ""
    handled: bool = False
    should_sleep: bool = False


@dataclass(slots=True)
class PlannerPayload:
    """Emitted with PLANNER_START and PLANNER_END."""

    agent_name: str
    prompt: str = ""
    response: str = ""                  # Populated on PLANNER_END


@dataclass(slots=True)
class AutomationPayload:
    """Emitted with AUTOMATION_START and AUTOMATION_END."""

    description: str
    success: bool = True
    result: str = ""


@dataclass(slots=True)
class BrowserPayload:
    """Emitted with BROWSER_OPENED, BROWSER_NAVIGATED, BROWSER_TAB_CHANGED."""

    url: str = ""
    tab_title: str = ""
    action: str = ""                    # "open" | "navigate" | "tab_change"


@dataclass(slots=True)
class AppPayload:
    """Emitted with :attr:`EventType.APP_OPENED`."""

    app_name: str
    success: bool = True


@dataclass(slots=True)
class MemoryPayload:
    """Emitted with :attr:`EventType.MEMORY_UPDATED`."""

    operation: str = ""                 # "add_user" | "add_assistant" | "summarise"
    entry_count: int = 0


@dataclass(slots=True)
class SystemDiagnostics:
    """Live hardware / OS metrics. Emitted with :attr:`EventType.SYSTEM_DIAG`.

    All ``*_percent`` fields are in the range 0.0–100.0.
    Network fields are cumulative bytes; use deltas to compute bandwidth rate.
    ``mic_level`` is a normalised 0.0–1.0 amplitude value.
    """

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_percent: float = 0.0
    disk_percent: float = 0.0
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0
    mic_level: float = 0.0
    gpu_name: str = ""
    gpu_vram_used_mb: float = 0.0
    gpu_vram_total_mb: float = 0.0


@dataclass(slots=True)
class LogEntry:
    """Emitted with :attr:`EventType.LOG`."""

    message: str
    level: LogLevel = LogLevel.INFO
    module: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(slots=True)
class Notification:
    """Emitted with :attr:`EventType.NOTIFICATION`. Shown as a UI toast."""

    title: str
    message: str
    severity: NotificationSeverity = NotificationSeverity.INFO
    duration_ms: int = 4000


@dataclass(slots=True)
class ErrorPayload:
    """Emitted with :attr:`EventType.ERROR`."""

    message: str
    module: str = ""
    recoverable: bool = True
    exception_type: str = ""


# ════════════════════════════════════════════════════════════════════════════
# Core event object
# ════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class AssistantEvent:
    """The single object that flows through the EventBus.

    Every event — from STT, LLM, TTS, the brain loop, or the UI — is
    wrapped in this dataclass before publishing.  **No raw strings or
    dicts flow through the bus.**

    Attributes
    ──────────
    type             The :class:`EventType` of this event.
    payload          A typed payload dataclass or ``None``.
    timestamp        UTC creation time (auto-populated).
    source           The :class:`EventSource` component that published this.
    correlation_id   UUID linking related events (e.g. STT_START ↔ STT_END).
    session_id       Active conversation session identifier.
    """

    type: EventType
    payload: Any = field(default=None)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: EventSource = EventSource.UNKNOWN
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""


# ════════════════════════════════════════════════════════════════════════════
# Handler type alias
# ════════════════════════════════════════════════════════════════════════════

#: Type alias for any callable that accepts an :class:`AssistantEvent`.
EventHandler = Callable[[AssistantEvent], None]

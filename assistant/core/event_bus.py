"""Thread-safe publish/subscribe EventBus for JARVIS.

This module provides the runtime infrastructure for the event system.
Type definitions (EventType, AssistantEvent, payloads) live in
``assistant.core.events`` to keep this file focused on mechanics.

Public API
──────────
  get_event_bus()   → EventBus     # Process-wide singleton accessor
  publish_event(…)  → AssistantEvent  # Build + publish in one call

  EventBus
    .subscribe(event_type, handler)
    .subscribe_all(handler)
    .unsubscribe(event_type, handler)
    .unsubscribe_all(handler)
    .publish(AssistantEvent)
    .handler_count(event_type) → int
    .wildcard_count            → int
    .clear()                   # (for tests)

Design constraints
──────────────────
  • Zero UI-framework dependencies — no PySide6, no Tkinter.
  • Zero optional library dependencies — no psutil, no numpy.
  • Thread-safe: all public methods may be called from any thread.
  • Non-blocking: the lock is released before handlers are invoked,
    preventing deadlocks when a handler calls publish() recursively.
  • Fail-safe: a crashing handler is caught and logged; it never
    silences other handlers or terminates the bus.
  • Async-ready: handlers are plain callables; wrapping them in
    ``asyncio.run_coroutine_threadsafe()`` requires no changes here.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from assistant.core.events import (
    AssistantEvent,
    EventHandler,
    EventSource,
    EventType,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# EventBus
# ════════════════════════════════════════════════════════════════════════════


class EventBus:
    """Thread-safe publish/subscribe event bus.

    Subscribers register typed handler callables; publishers emit
    :class:`~assistant.core.events.AssistantEvent` objects.  The bus
    is the **only** channel through which backend components communicate
    with the UI layer.

    Handler execution
    ─────────────────
    Handlers run synchronously inside :meth:`publish`, but the internal
    lock is released before any handler is called.  This means:

    * Handlers must not block for significant time (enqueue work instead).
    * A handler may safely call ``publish()`` without deadlocking.
    * The order of handler invocation is: specific handlers in registration
      order, then wildcard handlers in registration order.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        # Maps EventType → ordered list of handlers for that specific type.
        self._handlers: dict[EventType, list[EventHandler]] = {}
        # Handlers that receive every published event, regardless of type.
        self._wildcard: list[EventHandler] = []

    # ── Subscription ─────────────────────────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register *handler* to be called whenever *event_type* is published.

        If *handler* is already registered for *event_type* it is not added
        a second time (idempotent).
        """
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register *handler* to receive **every** published event.

        Useful for audit loggers, debug monitors, and the bridge itself
        when it needs to forward all events.
        """
        with self._lock:
            if handler not in self._wildcard:
                self._wildcard.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove *handler* from *event_type* subscriptions.

        No-op if *handler* is not registered for *event_type*.
        """
        with self._lock:
            bucket = self._handlers.get(event_type)
            if bucket and handler in bucket:
                bucket.remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Remove *handler* from the wildcard list.

        No-op if *handler* is not in the wildcard list.
        """
        with self._lock:
            if handler in self._wildcard:
                self._wildcard.remove(handler)

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, event: AssistantEvent) -> None:
        """Dispatch *event* to all matching handlers.

        The handler list is **snapshotted** while the lock is held, then
        the lock is released before any handler executes.  Each handler
        is wrapped in a try/except to prevent one failing handler from
        blocking or silencing subsequent ones.

        Args:
            event: A fully constructed :class:`AssistantEvent`.  Use
                   :func:`publish_event` to build and publish in one call.
        """
        # Snapshot under lock, release before calling handlers.
        with self._lock:
            specific = list(self._handlers.get(event.type, []))
            wildcard = list(self._wildcard)

        for handler in specific + wildcard:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus: handler %r raised for event type %r (source=%r)",
                    getattr(handler, "__qualname__", repr(handler)),
                    event.type,
                    event.source,
                )

    # ── Introspection ─────────────────────────────────────────────────────────

    def handler_count(self, event_type: EventType) -> int:
        """Return the number of specific handlers registered for *event_type*."""
        with self._lock:
            return len(self._handlers.get(event_type, []))

    @property
    def wildcard_count(self) -> int:
        """Number of wildcard (subscribe_all) handlers currently registered."""
        with self._lock:
            return len(self._wildcard)

    def registered_types(self) -> list[EventType]:
        """Return a sorted list of EventTypes that have at least one subscriber."""
        with self._lock:
            return sorted(
                (et for et, handlers in self._handlers.items() if handlers),
                key=lambda e: e.value,
            )

    def clear(self) -> None:
        """Remove **all** subscriptions.

        Primarily for use in unit tests between test cases.  Do not call
        in production code; subscribers will silently stop receiving events.
        """
        with self._lock:
            self._handlers.clear()
            self._wildcard.clear()


# ════════════════════════════════════════════════════════════════════════════
# Process-wide singleton
# ════════════════════════════════════════════════════════════════════════════

_bus: EventBus | None = None
_bus_lock: threading.Lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide :class:`EventBus` singleton.

    Thread-safe via double-checked locking.  The singleton is created
    lazily on first access and never replaced or reset during normal
    operation.

    Returns:
        The single shared :class:`EventBus` instance for this process.
    """
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:        # second check inside the lock
                _bus = EventBus()
    return _bus


# ════════════════════════════════════════════════════════════════════════════
# Convenience helpers
# ════════════════════════════════════════════════════════════════════════════


def publish_event(
    event_type: EventType,
    payload: Any = None,
    source: EventSource = EventSource.UNKNOWN,
    session_id: str = "",
    correlation_id: str = "",
) -> AssistantEvent:
    """Build an :class:`AssistantEvent` and publish it in a single call.

    This is the **preferred** way to emit events from backend components.
    It automatically populates ``timestamp`` and generates a unique
    ``correlation_id`` if one is not supplied.

    Returns the published event so callers can reuse its ``correlation_id``
    to link paired events (e.g. STT_START → STT_END for the same utterance).

    Example::

        # Emit STT_START and capture the correlation ID.
        corr_id = publish_event(
            EventType.STT_START,
            source=EventSource.STT,
            session_id=current_session,
        ).correlation_id

        text = stt.transcribe(audio)

        # Emit STT_END linked to the same pair.
        publish_event(
            EventType.STT_END,
            payload=MessagePayload(text=text, source=EventSource.STT),
            source=EventSource.STT,
            session_id=current_session,
            correlation_id=corr_id,
        )

    Args:
        event_type:     The :class:`EventType` to publish.
        payload:        A typed payload dataclass or ``None``.
        source:         The :class:`EventSource` component publishing this.
        session_id:     Current conversation session ID (optional).
        correlation_id: Link to a related event (auto-generated if omitted).

    Returns:
        The :class:`AssistantEvent` that was published.
    """
    event = AssistantEvent(
        type=event_type,
        payload=payload,
        source=source,
        session_id=session_id,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )
    get_event_bus().publish(event)
    return event

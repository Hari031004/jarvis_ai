"""Lightweight desktop GUI for status, transcript, settings, and performance."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Any

import psutil

from assistant.config import Settings
from assistant.utils.logger import get_logger





@dataclass(slots=True)
class GUIEvent:
    kind: str
    text: str


class AssistantGUI:
    """Tkinter control panel that can run beside the voice assistant."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.events: queue.Queue[GUIEvent] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.root: tk.Tk | None = None

    def start_background(self) -> None:
        if not self.settings.enable_gui or self.thread is not None:
            return
        
        from assistant.core.event_bus import get_event_bus
        from assistant.core.events import AssistantEvent, EventType, StateChangePayload, MessagePayload

        def listener(event: AssistantEvent) -> None:
            if event.type in (EventType.SLEEP_ENTERED, EventType.SLEEP_EXITED, EventType.STATE_CHANGED):
                p = event.payload
                if isinstance(p, StateChangePayload):
                    self.events.put(GUIEvent("status", p.context or p.new_state.value.title()))
            elif event.type == EventType.RECORDING_START:
                self.events.put(GUIEvent("mic", "Microphone: listening"))
            elif event.type in (EventType.RECORDING_END, EventType.STT_START):
                self.events.put(GUIEvent("mic", "Microphone: processing"))
            elif event.type == EventType.USER_MESSAGE:
                p = event.payload
                if isinstance(p, MessagePayload):
                    self.events.put(GUIEvent("user", p.text))
            elif event.type == EventType.ASSISTANT_MESSAGE:
                p = event.payload
                if isinstance(p, MessagePayload):
                    self.events.put(GUIEvent("assistant", p.text))

        get_event_bus().subscribe_all(listener)
        self.thread = threading.Thread(target=self._run, name="jarvis-gui", daemon=True)
        self.thread.start()

    def publish(self, kind: str, text: str) -> None:
        """Deprecated legacy call. Kept as no-op for backward compatibility."""
        pass


    def _run(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title(f"{self.settings.assistant_name} Control Center")
        root.geometry("720x520")
        dark = self.settings.gui_theme.lower() == "dark"
        bg = "#111318" if dark else "#f7f7f7"
        fg = "#f1f5f9" if dark else "#111827"
        root.configure(bg=bg)

        status = tk.StringVar(value="Sleeping")
        mic = tk.StringVar(value="Microphone: standby")
        perf = tk.StringVar(value="CPU 0% | RAM 0%")

        tk.Label(root, text=self.settings.assistant_name, font=("Segoe UI", 22, "bold"), bg=bg, fg=fg).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(root, textvariable=status, font=("Segoe UI", 12), bg=bg, fg=fg).pack(anchor="w", padx=18)
        tk.Label(root, textvariable=mic, font=("Segoe UI", 10), bg=bg, fg=fg).pack(anchor="w", padx=18, pady=(0, 8))

        transcript = tk.Text(root, wrap="word", bg="#1f2937" if dark else "#ffffff", fg=fg, insertbackground=fg)
        transcript.pack(fill="both", expand=True, padx=18, pady=8)

        footer = tk.Label(root, textvariable=perf, font=("Segoe UI", 10), bg=bg, fg=fg)
        footer.pack(anchor="w", padx=18, pady=(0, 12))

        def pump() -> None:
            while not self.events.empty():
                event = self.events.get()
                if event.kind == "status":
                    status.set(event.text)
                elif event.kind == "mic":
                    mic.set(event.text)
                else:
                    transcript.insert("end", f"[{event.kind}] {event.text}\n")
                    transcript.see("end")
            perf.set(f"CPU {psutil.cpu_percent(interval=None):.0f}% | RAM {psutil.virtual_memory().percent:.0f}%")
            root.after(750, pump)

        pump()
        root.mainloop()

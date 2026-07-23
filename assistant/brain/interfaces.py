"""Protocol interfaces between the AI Brain and subsystem modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable


@dataclass(slots=True)
class IntentResult:
    """Outcome of intent detection and local command routing."""

    handled: bool
    message: str
    should_sleep: bool = False


@dataclass(slots=True)
class PlannerResponse:
    """Response from the task planner / agent orchestrator."""

    agent: str
    content: str


@runtime_checkable
class WakeWordService(Protocol):
    def wait_for_wake_word(self, stop_event: Any) -> bool: ...

    def list_microphones(self) -> list[dict]: ...

    def select_microphone(self, device_name: str) -> int | None: ...

    def reload_model(self) -> None: ...


@runtime_checkable
class SpeechInput(Protocol):
    def record_utterance(self) -> Any: ...

    def transcribe(self, audio: Any) -> str: ...

    def transcribe_stream(self, chunks: Iterable[Any], min_seconds: float) -> Iterable[str]: ...

    def transcribe_partial(self, chunks: Iterable[Any], partial_interval: float | None) -> Iterable[str]: ...

    def transcribe_with_language(self, audio: Any, language: str | None) -> str: ...

    def warmup(self) -> None: ...

    def reload_model(self, model_size: str | None) -> None: ...


@runtime_checkable
class IntentDetector(Protocol):
    def route(self, text: str) -> IntentResult | None: ...


@runtime_checkable
class TaskPlanner(Protocol):
    def answer(self, prompt: str) -> PlannerResponse: ...

    def messages_for(self, prompt: str) -> list[dict[str, str]]: ...

    def set_mode(self, mode: str) -> str: ...


@runtime_checkable
class LLMService(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str: ...

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterable[str]: ...


@runtime_checkable
class MemoryService(Protocol):
    def add_user(self, text: str) -> None: ...

    def add_assistant(self, text: str) -> None: ...


@runtime_checkable
class SpeechOutput(Protocol):
    def speak(self, text: str) -> None: ...

    def speak_stream(self, chunks: Iterable[str]) -> str: ...

    def speak_interruptible(self, text: str) -> None: ...

    def play_startup_sound(self) -> None: ...

    def stop(self) -> None: ...

    def interrupt(self) -> None: ...

    def list_voices(self) -> list[dict[str, str]]: ...

    def set_voice(self, voice_name: str) -> None: ...

    def stop_queue(self) -> None: ...

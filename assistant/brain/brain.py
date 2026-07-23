"""Central AI Brain coordinating wake, speech, intent, planning, actions, LLM, and memory."""

from __future__ import annotations

import json
import signal
import threading
import time
from typing import TYPE_CHECKING

from assistant.agents.llm import LLMClient, LLMError
from assistant.agents.orchestrator import AgentOrchestrator
from assistant.automation.manager import AutomationManager
from assistant.browser.controller import BrowserController
from assistant.config import Settings
from assistant.desktop.application import ApplicationController
from assistant.desktop.file_agent import FileAgent
from assistant.desktop.input_agent import InputAgent
from assistant.desktop.gui import AssistantGUI
from assistant.desktop.system import SystemController
from assistant.memory.conversation import ConversationMemory
from assistant.memory.database import SQLiteStore
from assistant.memory.rag import DocumentIntelligence
from assistant.plugins.manager import PluginManager
from assistant.plugins.mcp_client import MCPClient, MCPServerConfig
from assistant.security import AuditLogger, PermissionManager, RateLimiter, SecretVault
from assistant.speech.audio_processing import VoiceProfileStore, WakeWordMatcher
from assistant.speech.speech_to_text import SpeechToText
from assistant.speech.text_to_speech import TextToSpeech
from assistant.speech.speech_agent import SpeechAgent
from assistant.speech.wake_listener import WakeListener
from assistant.speech.wake_word import WakeWordDetector
from assistant.utils.helpers import truncate_for_speech
from assistant.utils.logger import configure_logging, get_logger
from assistant.vision.service import VisionService

from assistant.brain.intent import CommandRouter
from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, StateChangePayload, MessagePayload, AssistantState

if TYPE_CHECKING:
    pass


class ConversationState:
    """Tracks the current conversation context, state, and history with enhanced error recovery and context management."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.active = False
        self.last_activity: float = 0.0
        self.current_mode: str = "natural"
        self.pending_confirmation: str | None = None
        self.pending_tool: str | None = None
        self.conversation_history: list[dict[str, str]] = []
        self.error_count: int = 0
        self.last_error: str | None = None
        self.recovery_attempts: int = 0
        self.max_recovery_attempts: int = 3
        self.backoff_base: float = 1.0
        self.session_count: int = 0
        self.total_utterances: int = 0
        self.context_summary: str | None = None

    def start_session(self) -> None:
        self.active = True
        self.last_activity = time.monotonic()
        self.error_count = 0
        self.recovery_attempts = 0
        self.session_count += 1
        self.logger.info("Session #%d started", self.session_count)

    def end_session(self) -> None:
        self.active = False
        self.pending_confirmation = None
        self.pending_tool = None
        self.logger.info("Session #%d ended (%d utterances)", self.session_count, self.total_utterances)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def is_timed_out(self, timeout: float) -> bool:
        return self.active and (time.monotonic() - self.last_activity) > timeout

    def record_error(self, error: str) -> None:
        self.error_count += 1
        self.last_error = error
        self.logger.warning("Conversation error #%d: %s", self.error_count, error)

    def should_recover(self) -> bool:
        return self.error_count > 0 and self.recovery_attempts < self.max_recovery_attempts

    def get_backoff_delay(self) -> float:
        """Exponential backoff for retry delays."""
        delay = self.backoff_base * (2 ** self.recovery_attempts)
        return min(delay, 8.0)

    def add_to_history(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})
        if role == "user":
            self.total_utterances += 1
        max_history = self.settings.conversation_max_messages
        if len(self.conversation_history) > max_history:
            self.conversation_history = self.conversation_history[-max_history:]

    def get_context_window(self) -> list[dict[str, str]]:
        """Return the last N messages for LLM context, with optional summary prefix."""
        if self.context_summary and self.conversation_history:
            return [{"role": "system", "content": f"Previous context: {self.context_summary}"}] + self.conversation_history[-10:]
        return self.conversation_history[-15:]

    def summarize_context(self, summary: str) -> None:
        """Store a compressed summary of earlier conversation for long sessions."""
        self.context_summary = summary
        # Keep only recent messages after summarization
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-10:]
            self.logger.info("Context summarized, trimmed to %d messages", len(self.conversation_history))


class AIBrain:
    """Coordinates wake detection, speech I/O, intent routing, agents, memory, tools, and TTS."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        configure_logging(settings)
        self.logger = get_logger(__name__)
        self.stop_event = threading.Event()
        self.state = ConversationState(settings)

        self.store = SQLiteStore(settings.database_path)
        self.audit = AuditLogger(self.store)
        self.permissions = PermissionManager(settings, self.audit)
        self.rate_limiter = RateLimiter(settings.rate_limit_max_events, settings.rate_limit_window_seconds)
        self.vault = SecretVault(settings)

        self.tts = TextToSpeech(settings)
        self.wake_word_detector = WakeWordDetector(settings)
        self.wake_listener = WakeListener(settings)
        self.speech_to_text = SpeechToText(settings)
        self.wake_words = WakeWordMatcher(settings)
        self.voice_profiles = VoiceProfileStore(settings)
        self.memory = ConversationMemory(settings, self.store)
        self.llm = LLMClient(settings)
        self.orchestrator = AgentOrchestrator(settings, self.llm, self.memory)

        self.browser = BrowserController()
        self.applications = ApplicationController(settings)
        self.system = SystemController(settings, self.permissions)
        self.file_agent = FileAgent(settings)
        self.input_agent = InputAgent(settings)
        self.automation = AutomationManager(settings, self.browser, self.tts.speak, self.store)
        self.rag = DocumentIntelligence(settings, self.store) if settings.enable_rag else None
        self.vision = VisionService(settings) if settings.enable_vision else None
        self.mcp = MCPClient(settings)
        self._start_mcp_servers()
        self.plugins = PluginManager(settings, self.permissions, self.store)
        self.plugins.load_all()
        self.speech_agent = SpeechAgent(settings, self.speech_to_text, self.tts)
        self.gui = AssistantGUI(settings)
        self.router = CommandRouter(
            applications=self.applications,
            browser=self.browser,
            system=self.system,
            automation=self.automation,
            memory=self.memory,
            orchestrator=self.orchestrator,
            plugins=self.plugins,
            rag=self.rag,
            vision=self.vision,
            mcp=self.mcp,
            file_agent=self.file_agent,
            input_agent=self.input_agent,
            llm=self.llm,
            speech_agent=self.speech_agent,
        )

    def run_forever(self) -> None:
        self.logger.info("Session loop entry.")
        self._install_signal_handlers()
        self.gui.start_background()
        self._warmup_background()
        while not self.stop_event.is_set():
            try:
                publish_event(
                    EventType.SLEEP_ENTERED,
                    payload=StateChangePayload(new_state=AssistantState.SLEEPING, context=f"Sleeping. Say '{self.settings.wake_word}'."),
                    source=EventSource.BRAIN
                )
                self.logger.info("Waiting for wake word (Sleeping).")
                if not self.wait_for_wake_word():
                    self.logger.info("wait_for_wake_word returned False. stop_event set: %s", self.stop_event.is_set())
                    time.sleep(1.0)
                    continue
                if self.stop_event.is_set():
                    self.logger.info("stop_event is set after wake word check. Exiting loop.")
                    break
                self.logger.info("Wake word detected. Entering active session.")
                self._active_session()
                self.logger.info("Returned from active session. Checking stop_event: %s", self.stop_event.is_set())
            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt caught in run_forever. Stopping.")
                self.stop()
                return
            except Exception as exc:
                self.logger.exception("Assistant loop error: %s", exc)
                time.sleep(1.0)
        self.logger.info("Session loop exit. stop_event set: %s", self.stop_event.is_set())

    def stop(self) -> None:
        self.logger.info("stop() called. Reason for exit: Stop requested.")
        self.stop_event.set()
        self.tts.stop()
        self.mcp.stop_all()
        self.state.end_session()
        self.logger.info("Stopping assistant. stop_event is set.")

    def wait_for_wake_word(self) -> bool:
        return self.wake_word_detector.wait_for_wake_word(self.stop_event)

    def _present(self, text: str, already_spoken: bool = False) -> None:
        if not text.strip():
            return

        self.logger.info("Response generated: %r", text)

        # 1. Text response (GUI/Console/Chat output and history)
        try:
            publish_event(
                EventType.ASSISTANT_MESSAGE,
                payload=MessagePayload(text=text, source=EventSource.LLM),
                source=EventSource.LLM
            )
            publish_event(
                EventType.LLM_END,
                source=EventSource.LLM
            )
            self.state.add_to_history("assistant", text)
            self.logger.info("Response displayed as text.")
        except Exception as exc:
            self.logger.error("Failed to display text response: %s", exc)

        # 2. Spoken response (TTS)
        if not already_spoken:
            self.logger.info("Response sent to TTS: %r", text)
            try:
                self.tts.speak(text)
            except Exception as exc:
                self.logger.error("Failed to speak response: %s", exc)

    def _active_session(self) -> None:
        self.logger.info("Active session entry. Session count: %d", self.state.session_count)
        self.state.start_session()
        
        # Publish SLEEP_EXITED event
        publish_event(
            EventType.SLEEP_EXITED,
            payload=StateChangePayload(new_state=AssistantState.IDLE, context="Awake"),
            source=EventSource.BRAIN
        )
        
        self.tts.play_startup_sound()
        self._present(f"Hello {self.settings.user_name}, I'm listening.")
        last_activity = time.monotonic()

        # Warm up STT model so first utterance is fast
        try:
            self.speech_to_text.warmup()
        except Exception:
            pass

        while not self.stop_event.is_set():
            try:
                if self.state.is_timed_out(self.settings.conversation_timeout_seconds):
                    self._present("Conversation timed out. Returning to sleep mode.")
                    self.state.end_session()
                    self.logger.info("Active session exit. Reason: Timeout.")
                    return

                # Publish RECORDING_START event
                publish_event(
                    EventType.RECORDING_START,
                    payload=StateChangePayload(new_state=AssistantState.LISTENING, context="Microphone: listening"),
                    source=EventSource.LISTENER
                )
                
                audio = self.wake_listener.record_utterance()
                
                # Publish RECORDING_END event
                publish_event(
                    EventType.RECORDING_END,
                    source=EventSource.LISTENER
                )
                
                if audio is None or (hasattr(audio, 'size') and audio.size == 0):
                    continue

                if self.settings.enable_voice_auth and not self.voice_profiles.authenticate(
                    self.settings.voice_auth_user, audio
                ):
                    self.audit.record("voice_auth", False, "Speaker did not match enrolled profile.")
                    self._present("Voice authentication failed.")
                    self.logger.info("Active session exit. Reason: Voice Auth Failure.")
                    return

                text = self.speech_to_text.transcribe(audio)
                if not text:
                    continue
                import uuid
                request_id = str(uuid.uuid4())
                last_activity = time.monotonic()
                self.state.touch()
                
                # Publish USER_MESSAGE event
                publish_event(
                    EventType.USER_MESSAGE,
                    payload=MessagePayload(text=text, source=EventSource.STT),
                    source=EventSource.STT,
                    session_id=request_id
                )
                
                self.state.add_to_history("user", text)

                if self.settings.enable_wake_word and self.wake_words.matches(text):
                    text = self._remove_wake_words(text)
                    if not text:
                        self._present("Yes?")
                        continue

                if not self.rate_limiter.allow("voice-command"):
                    self._present("Rate limit reached. Give me a moment.")
                    continue

                command = self.router.route(text, request_id)
                if command:
                    self._present(command.message)
                    if command.should_sleep:
                        self.state.end_session()
                        self.logger.info("Active session exit. Reason: Sleep Command.")
                        return
                    continue

                self._handle_ai_prompt(text, request_id)
            except LLMError as exc:
                self.logger.exception("LLM error: %s", exc)
                self.state.record_error(str(exc))
                if self.state.should_recover():
                    self.state.recovery_attempts += 1
                    delay = self.state.get_backoff_delay()
                    self.logger.info("LLM recovery attempt #%d with %.1fs backoff", self.state.recovery_attempts, delay)
                    time.sleep(delay)
                    self._present("I had trouble reaching the AI provider. Let me try a different one.")
                    self._handle_ai_prompt_with_fallback(text)
                else:
                    self._present("I had trouble reaching the selected AI provider.")
            except KeyboardInterrupt:
                self.logger.info("KeyboardInterrupt caught in _active_session. Returning to sleep mode.")
                self.state.end_session()
                return
            except Exception as exc:
                self.logger.exception("Active session error: %s", exc)
                self.state.record_error(str(exc))
                self._present("I ran into a problem with that request.")
                # Brief pause before retrying to avoid tight error loops
                time.sleep(0.5)

    def _handle_ai_prompt(self, text: str, request_id: str = "") -> None:
        self.memory.add_user(text)
        response = ""
        already_spoken = False
        if self.settings.enable_streaming_responses:
            messages = self.orchestrator.messages_for(text)
            try:
                chunks = self.llm.stream_chat(messages)
                chunks_list = []
                
                # Helper generator to record yielded chunks
                def chunk_recorder():
                    for chunk in chunks:
                        chunks_list.append(chunk)
                        yield chunk

                try:
                    self.logger.info("Response sent to TTS: (streaming stream)")
                    response = self.tts.speak_stream(chunk_recorder())
                    already_spoken = True
                except Exception as tts_exc:
                    self.logger.error("TTS stream failed: %s", tts_exc)
                    # Consume any remaining chunks
                    for chunk in chunks:
                        chunks_list.append(chunk)
                    response = "".join(chunks_list).strip()
                    already_spoken = False

                if not response:
                    response = self.llm.chat(messages)
                    response = truncate_for_speech(response, max_chars=1200)
                    already_spoken = False
            except Exception as exc:
                self.logger.error("AI prompt error: %s", exc)
                self._handle_ai_prompt_with_fallback(text, request_id)
                return
        else:
            try:
                response = self.orchestrator.answer(text).content
                response = truncate_for_speech(response, max_chars=1200)
            except Exception as exc:
                self.logger.error("AI prompt error: %s", exc)
                self._handle_ai_prompt_with_fallback(text, request_id)
                return

        self._present(response, already_spoken=already_spoken)
        self.memory.add_assistant(response)

    def _handle_ai_prompt_with_fallback(self, text: str, request_id: str = "") -> None:
        """Try fallback providers when the primary LLM fails."""
        self.logger.info("Attempting LLM fallback for: %s", text)
        try:
            messages = self.orchestrator.messages_for(text)
            response = self.llm.chat(messages)
            if response:
                response = truncate_for_speech(response, max_chars=1200)
                self._present(response)
                self.memory.add_assistant(response)
                return
        except Exception as exc:
            self.logger.warning("Fallback LLM also failed: %s", exc)

        self._present("I'm sorry, I couldn't process that request right now.")

    def _remove_wake_words(self, text: str) -> str:
        cleaned = text
        for wake_word in self.settings.wake_words:
            pattern = wake_word.strip()
            if pattern:
                cleaned = cleaned.replace(pattern, "", 1).replace(pattern.title(), "", 1).strip(" ,.")
        return cleaned.strip()

    def _start_mcp_servers(self) -> None:
        if not self.settings.enable_mcp or not self.settings.mcp_config_file.exists():
            return
        try:
            raw = json.loads(self.settings.mcp_config_file.read_text(encoding="utf-8"))
            for item in raw.get("servers", []):
                command = item.get("command") or []
                if isinstance(command, str):
                    command = command.split()
                if not command:
                    continue
                config = MCPServerConfig(
                    name=str(item["name"]),
                    command=[str(part) for part in command],
                    cwd=None,
                    env={str(k): str(v) for k, v in item.get("env", {}).items()},
                )
                self.mcp.start(config)
        except Exception as exc:
            self.logger.warning("MCP startup failed: %s", exc)

    def _warmup_background(self) -> None:
        def warmup() -> None:
            try:
                self.speech_to_text.warmup()
            except Exception as exc:
                self.logger.debug("Speech model warmup deferred: %s", exc)

        threading.Thread(target=warmup, name="whisper-warmup", daemon=True).start()

    def _install_signal_handlers(self) -> None:
        def handle_signal(signum, frame) -> None:  # type: ignore[no-untyped-def]
            self.stop()

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except ValueError:
            self.logger.debug("Signal handlers must be installed from the main thread.")


JarvisAssistant = AIBrain
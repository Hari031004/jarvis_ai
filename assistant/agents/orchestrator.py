"""Multi-agent orchestration layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from assistant.config import Settings
from assistant.agents.llm import LLMClient
from assistant.memory.conversation import ConversationMemory
from assistant.utils.helpers import normalize_text
from assistant.utils.logger import get_logger
from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, PlannerPayload


@dataclass(slots=True)
class AgentResponse:
    agent: str
    content: str


class Agent(ABC):
    """Base class for specialized reasoning agents."""

    name: str
    mode: str
    prompt: str

    def __init__(self, llm: LLMClient, memory: ConversationMemory) -> None:
        self.llm = llm
        self.memory = memory

    @abstractmethod
    def can_handle(self, prompt: str) -> bool:
        """Return whether this agent is a good fit for the prompt."""

    def run(self, prompt: str) -> AgentResponse:
        messages = self.memory.messages(mode_prompt=self.prompt)
        messages.append({"role": "user", "content": prompt})
        return AgentResponse(agent=self.name, content=self.llm.chat(messages))


class PlannerAgent(Agent):
    name = "planner"
    mode = "planning"
    prompt = "Break complex tasks into concise, ordered plans with dependencies and risks."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["plan", "roadmap", "steps", "architecture"])


class ReasoningAgent(Agent):
    name = "reasoning"
    mode = "reasoning"
    prompt = "Think carefully, check assumptions, and answer with rigorous reasoning."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["why", "reason", "analyze", "compare", "decide"])


class CodingAgent(Agent):
    name = "coding"
    mode = "coding"
    prompt = "Act as a senior software engineer. Produce correct, maintainable code and explain tradeoffs briefly."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(
            word in normalized
            for word in ["code", "python", "javascript", "debug", "refactor", "test", "error", "sql"]
        )


class ResearchAgent(Agent):
    name = "research"
    mode = "research"
    prompt = "Answer as a research assistant. Separate facts, uncertainty, and next verification steps."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["research", "latest", "news", "source", "find out"])


class VisionAgent(Agent):
    name = "vision"
    mode = "vision"
    prompt = "Analyze visual context, OCR text, screenshots, images, and user interface state."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["image", "screenshot", "screen", "webcam", "ocr", "face"])


class AutomationAgent(Agent):
    name = "automation"
    mode = "automation"
    prompt = "Translate user goals into safe desktop, browser, and system automation steps."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["open", "close", "move", "schedule", "automate", "run"])


class MemoryAgent(Agent):
    name = "memory"
    mode = "memory"
    prompt = "Manage memories, preferences, summaries, and context retrieval."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["remember", "forget", "preference", "memory"])


class SecurityAgent(Agent):
    name = "security"
    mode = "security"
    prompt = "Review requests for security, permissions, privacy, and operational risk."

    def can_handle(self, prompt: str) -> bool:
        normalized = normalize_text(prompt)
        return any(word in normalized for word in ["secure", "permission", "secret", "audit", "risk"])


class AgentOrchestrator:
    """Routes prompts to specialized agents while preserving a simple chat interface."""

    def __init__(self, settings: Settings, llm: LLMClient, memory: ConversationMemory) -> None:
        self.settings = settings
        self.llm = llm
        self.memory = memory
        self.logger = get_logger(__name__)
        self.active_mode = settings.default_ai_mode
        self.agents: dict[str, Agent] = {
            agent.name: agent
            for agent in [
                PlannerAgent(llm, memory),
                ReasoningAgent(llm, memory),
                CodingAgent(llm, memory),
                ResearchAgent(llm, memory),
                VisionAgent(llm, memory),
                AutomationAgent(llm, memory),
                MemoryAgent(llm, memory),
                SecurityAgent(llm, memory),
            ]
        }

    def set_mode(self, mode: str) -> str:
        normalized = normalize_text(mode)
        aliases = {
            "plan": "planning",
            "planner": "planning",
            "reason": "reasoning",
            "code": "coding",
            "coder": "coding",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = {"natural", "reasoning", "coding", "research", "planning", "vision", "automation", "memory", "security"}
        if normalized not in allowed:
            return f"I do not recognize {mode} mode."
        self.active_mode = normalized
        return f"{normalized.title()} mode is active."

    def answer(self, prompt: str) -> AgentResponse:
        agent = self._select_agent(prompt)
        self.logger.info("Selected agent: %s", agent.name)
        
        # Publish PLANNER_START event
        corr = publish_event(
            EventType.PLANNER_START,
            payload=PlannerPayload(agent_name=agent.name, prompt=prompt),
            source=EventSource.PLANNER
        )
        
        response = agent.run(prompt)
        
        # Publish PLANNER_END event
        publish_event(
            EventType.PLANNER_END,
            payload=PlannerPayload(agent_name=agent.name, prompt=prompt, response=response.content),
            source=EventSource.PLANNER,
            correlation_id=corr.correlation_id
        )
        
        return response

    def messages_for(self, prompt: str) -> list[dict[str, str]]:
        agent = self._select_agent(prompt)
        self.logger.info("Selected agent: %s", agent.name)
        return self.memory.messages(mode_prompt=agent.prompt)
    def _select_agent(self, prompt: str) -> Agent:
        if self.active_mode != "natural":
            for agent in self.agents.values():
                if agent.mode == self.active_mode or agent.name == self.active_mode:
                    return agent
        for agent in self.agents.values():
            if agent.can_handle(prompt):
                return agent
        return GeneralAgent(self.llm, self.memory)


class GeneralAgent(Agent):
    name = "general"
    mode = "natural"
    prompt = "Respond naturally, concisely, and helpfully as the primary JARVIS assistant."

    def can_handle(self, prompt: str) -> bool:
        return True


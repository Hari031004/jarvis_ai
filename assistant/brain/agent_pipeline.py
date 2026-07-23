"""Context-driven Intent Analyzer, Task Planner, and Execution Engine for JARVIS."""

from __future__ import annotations

import re
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pyautogui

from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, PlannerPayload

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# 1. SHARED EXECUTION CONTEXT
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class SharedContext:
    """Thread-safe, lightweight shared execution context containing active session variables.

    Agents read this context to make context-aware execution choices.
    """
    active_browser: str = ""
    active_tab: int = 1
    current_url: str = ""
    latest_observation: dict[str, Any] = field(default_factory=dict)
    active_application: str = ""
    active_window: str = ""
    current_file: str = ""
    current_folder: str = ""
    current_directory: str = ""
    last_mouse_position: tuple[int, int] = (0, 0)
    last_keyboard_action: str = ""
    active_session: str = ""
    last_memory: str = ""
    provider: str = ""
    model: str = ""
    token_usage: int = 0
    voice: str = ""
    language: str = ""
    speaking_state: bool = False
    listening_state: bool = False
    last_intent: ParsedIntent | None = None
    current_task: AgentTask | None = None
    execution_history: list[AgentTask] = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════════
# 2. GENERIC TASK MODEL
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentTask:
    """A strongly typed task step representing a plan goal for an agent."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent: str = "general"                 # Target agent identifier
    action: str = "none"                   # Action name
    parameters: dict = field(default_factory=dict)
    priority: int = 1                      # Task priority
    status: str = "pending"                # pending, running, completed, failed
    result: str = ""
    timestamp: float = field(default_factory=time.time)


# ════════════════════════════════════════════════════════════════════════════
# 3. AGENT CONTRACT INTERFACE
# ════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class AgentInterface(Protocol):
    """Universal interface contract for all specialized JARVIS agents."""

    def execute(self, task: AgentTask) -> str:
        """Execute the specified task action and return output."""
        ...

    def supports(self, task: AgentTask) -> bool:
        """Check if the agent supports executing the target task's action."""
        ...

    def state(self) -> dict[str, Any]:
        """Expose the current internal state variables of the agent."""
        ...

    def health(self) -> str:
        """Return status indicating 'healthy' or 'unhealthy' operational state."""
        ...

    def reset(self) -> None:
        """Reset internal memory or navigation states."""
        ...


# ════════════════════════════════════════════════════════════════════════════
# 4. INTENT ANALYZER
# ════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class ParsedIntent:
    """The structured representation of parsed user goals and actions."""
    goal: str          # e.g. "search", "play_result", "media_control", "open_application", "general"
    action: str        # e.g. "open", "search", "play", "pause", "resume", "next", "previous", "close", "back"
    target: str        # Target query, application name, or index number
    parameters: dict   # Detailed payload parameters
    context: str       # Active context (e.g., "youtube", "google", "browser", "desktop", "general")


class IntentAnalyzer:
    """Analyzes voice/text inputs in context of current active browser state to detect goals."""

    def __init__(self, browser: Any) -> None:
        self.browser = browser

    def analyze(self, text: str, context: SharedContext | None = None) -> ParsedIntent:
        normalized = text.lower().strip()
        browser_state = self.browser.get_state() if hasattr(self.browser, "get_state") else {}
        current_domain = browser_state.get("current_domain", "")

        # A. Media control hotkeys: "pause", "resume", "play", "stop", "next", "prev"
        if normalized in ("pause", "pause video", "pause music", "stop video"):
            return ParsedIntent(
                goal="media_control", action="pause", target="media", parameters={}, context="browser"
            )
        if normalized in ("resume", "resume video", "resume music", "play", "play video", "continue"):
            return ParsedIntent(
                goal="media_control", action="resume", target="media", parameters={}, context="browser"
            )
        if normalized in ("next", "next video", "next song", "next result"):
            return ParsedIntent(
                goal="media_control", action="next", target="media", parameters={}, context="browser"
            )
        if normalized in ("previous", "previous video", "previous song", "prev"):
            return ParsedIntent(
                goal="media_control", action="previous", target="media", parameters={}, context="browser"
            )

        # B. Contextual index select: "play first video", "open first result", "click result 1"
        play_match = re.search(r"^(?:play|open|click)\s+(?:the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|last)\s+(?:video|result|link|song)", normalized)
        if play_match or normalized.startswith("play result") or normalized.startswith("click result") or normalized.startswith("open result"):
            val = play_match.group(1) if play_match else "first"
            index = 1
            if "second" in val or "2nd" in val:
                index = 2
            elif "third" in val or "3rd" in val:
                index = 3
            elif "fourth" in val or "4th" in val:
                index = 4

            ctx = "youtube" if "youtube" in current_domain else ("google" if "google" in current_domain else "browser")
            return ParsedIntent(
                goal="play_result", action="play", target=str(index), parameters={"index": index}, context=ctx
            )

        # C. Navigation matching: "go back", "back", "go forward", "forward"
        if normalized in ("go back", "back", "back page", "previous page"):
            return ParsedIntent(
                goal="browser_navigation", action="back", target="history", parameters={}, context="browser"
            )
        if normalized in ("go forward", "forward", "forward page"):
            return ParsedIntent(
                goal="browser_navigation", action="forward", target="history", parameters={}, context="browser"
            )

        # D. Close actions: "close it", "close that tab", "close tab", "close browser tab"
        if normalized in ("close it", "close tab", "close that tab", "close browser tab"):
            return ParsedIntent(
                goal="close_tab", action="close", target="current", parameters={}, context="browser"
            )

        # E. Explicit search: "search youtube for <query>", "search google for <query>"
        search_match = re.search(r"^(?:search|play|look up)\s+(?:on\s+)?(youtube|yt|google|github|wikipedia)\s+(?:for\s+)?(.+)$", normalized)
        if search_match:
            site = search_match.group(1).strip()
            if site == "yt":
                site = "youtube"
            query = search_match.group(2).strip()
            return ParsedIntent(
                goal="search", action="search", target=query, parameters={"site": site, "query": query}, context=site
            )

        # F. Double Goal: "open youtube and search <query>"
        open_and_search = re.search(r"^(?:open|go to)\s+(youtube|google|github)\s+and\s+(?:search|find|play)\s+(?:for\s+)?(.+)$", normalized)
        if open_and_search:
            site = open_and_search.group(1).strip()
            query = open_and_search.group(2).strip()
            return ParsedIntent(
                goal="search", action="search", target=query, parameters={"site": site, "query": query}, context=site
            )

        # G. Contextual searches: "search <query>"
        context_search = re.search(r"^(?:search|look up|find)\s+(?:for\s+)?(.+)$", normalized)
        if context_search:
            query = context_search.group(1).strip()
            # Confirm query is not just a site name
            if query not in ("youtube", "google", "github", "wikipedia"):
                site = "google"
                if "youtube" in current_domain:
                    site = "youtube"
                elif "github" in current_domain:
                    site = "github"
                elif "wikipedia" in current_domain:
                    site = "wikipedia"
                return ParsedIntent(
                    goal="search", action="search", target=query, parameters={"site": site, "query": query}, context=site
                )

        # H. Open site patterns: "open youtube", "open google"
        open_match = re.match(r"^(?:open|go to|navigate to|launch)\s+(youtube|google|github|wikipedia|gmail|claude|chatgpt)$", normalized)
        if open_match:
            site = open_match.group(1).strip()
            return ParsedIntent(
                goal="open_site", action="open", target=site, parameters={"site": site}, context="browser"
            )

        # I. Application Launches: "open vs code", "open notepad"
        open_app = re.match(r"^(?:open|launch|start|run)\s+(vs code|notepad|chrome|edge|firefox|calculator|paint)$", normalized)
        if open_app:
            app_name = open_app.group(1).strip()
            return ParsedIntent(
                goal="open_application", action="open", target=app_name, parameters={"app_name": app_name}, context="desktop"
            )

        # Default fallback
        return ParsedIntent(
            goal="general", action="none", target=text, parameters={"query": text}, context="general"
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. TASK PLANNER
# ════════════════════════════════════════════════════════════════════════════

class TaskPlanner:
    """Generates structured execution plans (list of AgentTasks) from ParsedIntents."""

    def plan(
        self,
        intent: ParsedIntent,
        planning_context: dict | None = None,
    ) -> list[AgentTask]:
        """Translate a parsed intent into an ordered list of AgentTasks.

        Args:
            intent: Parsed user intent from IntentAnalyzer.
            planning_context: Optional memory-retrieved context dict, produced
                by CommandRouter._retrieve_planning_context().  When non-empty
                it is injected verbatim as ``memory_context`` into the parameters
                of every task that benefits from it.  Agents may use or ignore
                the key.  Planning structure is identical when absent or empty,
                preserving full backward compatibility.
        """
        tasks: list[AgentTask] = []
        ctx = planning_context or {}

        if intent.goal == "media_control":
            # Deterministic hotkey — memory context cannot help.
            tasks.append(AgentTask(
                agent="AutomationAgent",
                action="control_media",
                parameters={"action": intent.action}
            ))

        elif intent.goal == "play_result":
            # Index-based selection — memory context cannot help.
            index = intent.parameters.get("index", 1)
            tasks.append(AgentTask(
                agent="BrowserAgent",
                action="play_result",
                parameters={"index": index}
            ))

        elif intent.goal == "browser_navigation":
            # Deterministic navigation — memory context cannot help.
            tasks.append(AgentTask(
                agent="BrowserAgent",
                action="go_back" if intent.action == "back" else "go_forward"
            ))

        elif intent.goal == "close_tab":
            # Deterministic close — memory context cannot help.
            tasks.append(AgentTask(
                agent="BrowserAgent",
                action="close_tab"
            ))

        elif intent.goal == "search" and "site" in intent.parameters:
            site = intent.parameters["site"]
            query = intent.parameters["query"]
            open_params: dict = {"name": site}
            search_params: dict = {"query": query}
            if ctx:
                open_params["memory_context"] = ctx
                search_params["memory_context"] = ctx
            tasks.append(AgentTask(agent="BrowserAgent", action="open", parameters=open_params))
            tasks.append(AgentTask(agent="BrowserAgent", action="search", parameters=search_params))

        elif intent.goal == "open_site":
            site = intent.parameters["site"]
            params: dict = {"name": site}
            if ctx:
                params["memory_context"] = ctx
            tasks.append(AgentTask(agent="BrowserAgent", action="open", parameters=params))

        elif intent.goal == "open_application":
            app_name = intent.parameters["app_name"]
            params = {"name": app_name}
            if ctx:
                params["memory_context"] = ctx
            tasks.append(AgentTask(agent="DesktopAgent", action="open_application", parameters=params))

        else:
            params = {"prompt": intent.target}
            if ctx:
                params["memory_context"] = ctx
            tasks.append(AgentTask(agent="Orchestrator", action="run", parameters=params))

        return tasks


# ════════════════════════════════════════════════════════════════════════════
# 6. EXECUTION ENGINE
# ════════════════════════════════════════════════════════════════════════════

class ExecutionEngine:
    """Executes AgentTasks sequentially, maintaining context, history, and retry logs."""

    def __init__(
        self,
        browser: Any,
        applications: Any,
        system: Any,
        automation: Any,
        orchestrator: Any,
        vision: Any = None,
        file_agent: Any = None,
        input_agent: Any = None,
        memory: Any = None,
        llm: Any = None,
        speech_agent: Any = None
    ) -> None:
        self.browser = browser
        self.applications = applications
        self.system = system
        self.automation = automation
        self.orchestrator = orchestrator
        self.vision = vision
        self.file_agent = file_agent
        self.input_agent = input_agent
        self.memory = memory
        self.llm = llm
        self.speech_agent = speech_agent
        self.context = SharedContext()

    def execute(self, tasks: list[AgentTask], request_id: str = "") -> str:
        # Publish PLANNER_START event
        corr = publish_event(
            EventType.PLANNER_START,
            payload=PlannerPayload(agent_name="TaskPlanner", prompt="Execute structured plan"),
            source=EventSource.PLANNER,
            session_id=request_id
        )

        results: list[str] = []
        _last_structured: Any = None  # preserves rich AgentResult for single-task vision calls
        for task in tasks:
            started_at = time.perf_counter()
            task.status = "running"
            self.context.current_task = task
            logger.info("Routing task ID %s to agent '%s'", task.id, task.agent)

            result = ""
            retries = 2
            timeout = 10.0

            # Route to respective agent implementation with robust retry and timeout safety
            for attempt in range(retries):
                try:
                    if task.agent == "BrowserAgent":
                        result = self._execute_browser(task, request_id)
                        break
                    elif task.agent == "DesktopAgent":
                        result = self._execute_desktop(task)
                        break
                    elif task.agent == "SystemAgent":
                        result = self._execute_system(task)
                        break
                    elif task.agent == "AutomationAgent":
                        result = self._execute_automation(task, request_id)
                        break
                    elif task.agent == "VisionAgent":
                        result = self._execute_vision(task)
                        break
                    elif task.agent == "FileAgent":
                        result = self._execute_file(task)
                        break
                    elif task.agent == "InputAgent":
                        result = self._execute_input(task)
                        break
                    elif task.agent == "MemoryAgent":
                        result = self._execute_memory(task)
                        break
                    elif task.agent == "LLMAgent":
                        result = self._execute_llm(task)
                        break
                    elif task.agent == "SpeechAgent":
                        result = self._execute_speech(task)
                        break
                    elif task.agent == "Orchestrator":
                        result = self._execute_orchestrator(task)
                        break
                    else:
                        result = f"Unsupported task agent: {task.agent}"
                        break
                except Exception as exc:
                    logger.warning("Task execution attempt %d failed: %s", attempt + 1, exc)
                    if attempt == retries - 1:
                        result = f"Execution failed: {exc}"
                        task.status = "failed"

            # Normalize result: structured AgentResult vs plain string.
            # _execute_vision returns a rich AgentResult so the coordinator can
            # preserve the structured error field.  All other helpers return str.
            if hasattr(result, "success") and hasattr(result, "message") and hasattr(result, "error"):
                _last_structured = result
                if not result.success:
                    task.status = "failed"
                result_str: str = result.message
            else:
                _last_structured = None
                result_str = str(result) if result is not None else ""

            task.result = result_str
            if task.status != "failed":
                task.status = "completed"

            results.append(result_str)
            self.context.execution_history.append(task)

            self._update_shared_context(task.agent)
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "Agent=%s Action=%s DurationMs=%.1f Success=%s Failure=%s",
                task.agent,
                task.action,
                duration_ms,
                task.status == "completed",
                "" if task.status == "completed" else result,
            )

        final_response = " ".join(results)

        # Publish PLANNER_END event
        publish_event(
            EventType.PLANNER_END,
            payload=PlannerPayload(agent_name="TaskPlanner", prompt="Plan execution complete", response=final_response),
            source=EventSource.PLANNER,
            correlation_id=corr.correlation_id,
            session_id=request_id
        )

        # For single-task vision calls return the rich AgentResult so that
        # AgentCoordinator.execute_step() takes the structured branch and
        # preserves error / data fields intact across the engine boundary.
        if _last_structured is not None and len(tasks) == 1:
            return _last_structured
        return final_response

    def _update_shared_context(self, agent_name: str) -> None:
        """Copy the current agent state into the existing shared context."""
        agent_map = {
            "BrowserAgent": self.browser,
            "VisionAgent": self.vision,
            "DesktopAgent": self.applications,
            "FileAgent": self.file_agent,
            "InputAgent": self.input_agent,
            "MemoryAgent": self.memory,
            "LLMAgent": self.llm,
            "SpeechAgent": self.speech_agent,
        }
        agent = agent_map.get(agent_name)
        if not hasattr(agent, "get_state"):
            return
        try:
            state = agent.get_state()
        except Exception as exc:
            logger.warning("Unable to update shared context from %s: %s", agent_name, exc)
            return

        if agent_name == "BrowserAgent":
            self.context.active_browser = state.get("current_domain", "")
            self.context.active_tab = state.get("active_tab", state.get("current_tab", 1))
            self.context.current_url = state.get("current_url", "")
        elif agent_name == "VisionAgent":
            self.context.latest_observation = state.get("latest_observation", {})
        elif agent_name == "DesktopAgent":
            self.context.active_application = state.get("active_application", state.get("active_app", ""))
            self.context.active_window = state.get("active_window", "")
        elif agent_name == "FileAgent":
            self.context.current_file = state.get("current_file", "")
            self.context.current_directory = state.get("current_directory", "")
            self.context.current_folder = self.context.current_directory
        elif agent_name == "InputAgent":
            self.context.last_mouse_position = state.get("last_mouse_position", state.get("mouse_position", (0, 0)))
            self.context.last_keyboard_action = state.get("last_keyboard_action", "")
        elif agent_name == "MemoryAgent":
            self.context.active_session = state.get("active_session", "")
            self.context.last_memory = state.get("last_memory", "")
        elif agent_name == "LLMAgent":
            self.context.provider = state.get("provider", "")
            self.context.model = state.get("model", state.get("active_model", ""))
            self.context.token_usage = state.get("token_usage", 0)
        elif agent_name == "SpeechAgent":
            self.context.voice = state.get("voice", state.get("active_voice", ""))
            self.context.language = state.get("language", state.get("active_language", ""))
            self.context.speaking_state = state.get("speaking_state", False)
            self.context.listening_state = state.get("listening_state", False)

    # ── Internal Agent Execution Helpers ─────────────────────────────────────

    def _execute_browser(self, task: AgentTask, request_id: str) -> str:
        if task.action == "open":
            name = task.parameters.get("name", "")
            return self.browser.open_site(name, request_id)
        elif task.action == "search":
            query = task.parameters.get("query", "")
            return self.browser.search(query, request_id)
        elif task.action == "play_result":
            index = task.parameters.get("index", 1)
            result = self.browser.play_result(index, request_id)
            if hasattr(result, "success"):
                if not result.success:
                    task.status = "failed"
                return result.message
            return result
        elif task.action == "go_back":
            return self.browser.go_back(request_id)
        elif task.action == "go_forward":
            if hasattr(self.browser, "go_forward"):
                return self.browser.go_forward(request_id)
            pyautogui.hotkey("alt", "right")
            return "Navigated forward."
        elif task.action == "close_tab":
            return self.browser.close_tab(request_id)
        return f"BrowserAgent does not support action: {task.action}"

    def _execute_desktop(self, task: AgentTask) -> str:
        if task.action == "open_application":
            name = task.parameters.get("name", "")
            return self.applications.open_application(name)
        return f"DesktopAgent does not support action: {task.action}"

    def _execute_system(self, task: AgentTask) -> str:
        method = getattr(self.system, task.action, None)
        if method:
            return method()
        return f"SystemAgent does not support action: {task.action}"

    def _execute_automation(self, task: AgentTask, request_id: str) -> str:
        if task.action == "control_media":
            action = task.parameters.get("action", "")
            if action in ("pause", "resume"):
                pyautogui.press("space")
                return f"Sent media {action} command."
            elif action == "next":
                return self.browser.next_result(request_id)
            elif action == "previous":
                return self.browser.previous_result(request_id)
        return f"AutomationAgent does not support action: {task.action}"

    def _execute_orchestrator(self, task: AgentTask) -> str:
        if self.orchestrator:
            prompt = task.parameters.get("prompt", "")
            ans = self.orchestrator.answer(prompt)
            return ans.content
        return "LLM Orchestrator fallback failed."

    def _execute_vision(self, task: AgentTask) -> Any:
        """Execute a VisionAgent task and return its full AgentResult.

        Returns the AgentResult object (not just .message) so that the
        AgentCoordinator can preserve structured error / data fields across
        the ExecutionEngine boundary.
        """
        if self.vision:
            res = self.vision.execute(task)
            # Do NOT set task.status here; execute() normalizes it from res.success.
            return res
        return "VisionAgent unavailable."

    def _execute_file(self, task: AgentTask) -> str:
        if self.file_agent:
            res = self.file_agent.execute(task)
            if not res.success:
                task.status = "failed"
            return res.message
        return "FileAgent unavailable."

    def _execute_input(self, task: AgentTask) -> str:
        if self.input_agent:
            res = self.input_agent.execute(task)
            if not res.success:
                task.status = "failed"
            return res.message
        return "InputAgent unavailable."

    def _execute_memory(self, task: AgentTask) -> Any:
        """Execute a MemoryAgent task and return its full AgentResult.

        Returns the AgentResult object (not just .message) so that callers
        such as CommandRouter._retrieve_planning_context() can read structured
        search data (e.g. results list) for memory-assisted planning.
        Same pattern as _execute_vision introduced in Phase 2.3.
        """
        if self.memory:
            res = self.memory.execute(task)
            # Do NOT set task.status here; execute() normalises it from res.success.
            return res
        return "MemoryAgent unavailable."

    def _execute_llm(self, task: AgentTask) -> str:
        if self.llm:
            res = self.llm.execute(task)
            if not res.success:
                task.status = "failed"
            return res.message
        return "LLMAgent unavailable."

    def _execute_speech(self, task: AgentTask) -> str:
        if self.speech_agent:
            res = self.speech_agent.execute(task)
            if not res.success:
                task.status = "failed"
            return res.message
        return "SpeechAgent unavailable."

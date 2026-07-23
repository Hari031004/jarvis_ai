"""Routes recognized speech to local commands using fuzzy matching, aliases, and natural language understanding."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assistant.automation.manager import AutomationManager
from assistant.browser.controller import BrowserController
from assistant.desktop.application import ApplicationController
from assistant.desktop.system import SystemController
from assistant.utils.helpers import contains_stop_phrase, normalize_text, strip_command_prefix, strip_name_words
from assistant.utils.logger import get_logger
from assistant.brain.agent_pipeline import IntentAnalyzer, TaskPlanner, ExecutionEngine, AgentTask, ParsedIntent
from assistant.brain.agent_coordinator import AgentCoordinator



@dataclass(slots=True)
class CommandResult:
    handled: bool
    message: str
    should_sleep: bool = False


class CommandRouter:
    """Command router with fuzzy matching, aliases, and natural language understanding."""

    # Goals for which memory context meaningfully enriches planning.
    # Deterministic goals (media_control, play_result, browser_navigation,
    # close_tab) are excluded: memory cannot improve index-based or hotkey actions.
    _MEMORY_ASSISTED_GOALS: frozenset[str] = frozenset({
        "open_site",
        "open_application",
        "search",
    })

    def __init__(
        self,
        applications: ApplicationController,
        browser: BrowserController,
        system: SystemController,
        automation: AutomationManager,
        memory: Any | None = None,
        orchestrator: Any | None = None,
        plugins: Any | None = None,
        rag: Any | None = None,
        vision: Any | None = None,
        mcp: Any | None = None,
        file_agent: Any | None = None,
        input_agent: Any | None = None,
        llm: Any | None = None,
        speech_agent: Any | None = None,
    ) -> None:
        self.applications = applications
        self.browser = browser
        self.system = system
        self.automation = automation
        self.memory = memory
        self.orchestrator = orchestrator
        self.plugins = plugins
        self.rag = rag
        self.vision = vision
        self.mcp = mcp
        self.file_agent = file_agent
        self.input_agent = input_agent
        self.llm = llm
        self.speech_agent = speech_agent
        self.logger = get_logger(__name__)

        self.intent_analyzer = IntentAnalyzer(self.browser)
        self.planner = TaskPlanner()
        self.execution_engine = ExecutionEngine(
            browser=self.browser,
            applications=self.applications,
            system=self.system,
            automation=self.automation,
            orchestrator=self.orchestrator,
            vision=self.vision,
            file_agent=self.file_agent,
            input_agent=self.input_agent,
            memory=self.memory,
            llm=self.llm,
            speech_agent=self.speech_agent
        )
        self.coordinator = AgentCoordinator(self.execution_engine)

        # Application aliases for fuzzy matching
        self._app_aliases: dict[str, list[str]] = {
            "chrome": ["google chrome", "browser", "web browser"],
            "edge": ["microsoft edge", "ms edge"],
            "firefox": ["mozilla firefox", "fire fox"],
            "vs code": ["visual studio code", "vscode", "code editor", "vs code editor"],
            "cursor": ["cursor editor", "cursor ai"],
            "notepad": ["notepad++", "text editor"],
            "calculator": ["calc", "calculate"],
            "paint": ["mspaint", "paint app"],
            "terminal": ["command prompt", "cmd", "powershell", "console", "shell"],
            "task manager": ["taskmgr", "task mgr"],
            "settings": ["windows settings", "system settings"],
            "control panel": ["controlpanel", "windows control panel"],
            "file explorer": ["explorer", "windows explorer", "my computer", "this pc"],
        }

        # Folder aliases
        self._folder_aliases: dict[str, list[str]] = {
            "downloads": ["download folder", "my downloads"],
            "documents": ["my documents", "docs", "document folder"],
            "desktop": ["my desktop", "desktop folder"],
            "pictures": ["my pictures", "photos", "images"],
            "videos": ["my videos", "video folder"],
            "music": ["my music", "audio", "songs"],
        }

        # System command aliases
        self._system_aliases: dict[str, list[str]] = {
            "increase volume": ["turn up volume", "volume up", "louder", "make it louder", "raise volume", "increase sound"],
            "decrease volume": ["turn down volume", "volume down", "quieter", "make it quieter", "lower volume", "decrease sound"],
            "mute": ["mute volume", "mute audio", "silence", "turn off sound"],
            "unmute": ["unmute volume", "unmute audio", "turn on sound", "restore sound"],
            "brightness up": ["increase brightness", "make screen brighter", "brighten screen", "raise brightness"],
            "brightness down": ["decrease brightness", "make screen dimmer", "dim screen", "lower brightness"],
            "take screenshot": ["take a screenshot", "screenshot", "capture screen", "screen capture", "print screen"],
            "lock pc": ["lock computer", "lock my pc", "lock my computer", "lock screen", "lock workstation"],
            "sleep pc": ["sleep computer", "put pc to sleep", "put computer to sleep", "hibernate"],
            "restart pc": ["restart computer", "reboot pc", "reboot computer", "restart system"],
            "shutdown pc": ["shut down pc", "shutdown computer", "shut down computer", "power off", "turn off pc"],
            "empty recycle bin": ["clear recycle bin", "empty trash", "clear trash", "clean recycle bin"],
            "show battery": ["battery status", "battery level", "battery percentage", "check battery"],
            "show cpu usage": ["cpu usage", "processor usage", "cpu load", "processor load"],
            "show ram usage": ["ram usage", "memory usage", "ram load", "memory load"],
            "show disk usage": ["disk usage", "storage usage", "disk space", "storage space"],
        }

        # Automation aliases
        self._automation_aliases: dict[str, list[str]] = {
            "list todos": ["show todos", "list to dos", "show to do list", "show my tasks", "list tasks", "what are my todos"],
            "read calendar": ["show calendar", "calendar", "my schedule", "what's on my calendar", "today's schedule"],
            "open outlook": ["launch outlook", "start outlook", "open microsoft outlook"],
            "read notifications": ["show notifications", "check notifications", "my notifications", "notification center"],
            "news": ["latest news", "read news", "show news", "what's in the news", "headlines", "top stories"],
        }

        # Browser site aliases
        self._site_aliases: dict[str, list[str]] = {
            "youtube": ["yt", "you tube"],
            "github": ["git hub", "gh"],
            "google": ["google search"],
            "wikipedia": ["wiki", "wikipedia"],
        }

    def _retrieve_planning_context(self, intent: ParsedIntent) -> dict:
        """Retrieve relevant memory for planning via ExecutionEngine.

        Design rules:
        - Only called for goals listed in ``_MEMORY_ASSISTED_GOALS``.
        - Executes through ``self.execution_engine`` — never calls MemoryAgent directly.
        - Returns ``{}`` on any failure so planning always continues unchanged.
        - Injects ``retrieved_memories`` + ``query`` keys into the returned dict;
          downstream ``TaskPlanner.plan()`` attaches this as ``memory_context``
          in task parameters for agents to optionally consume.
        """
        if intent.goal not in self._MEMORY_ASSISTED_GOALS:
            return {}
        if not getattr(self.execution_engine, "memory", None):
            return {}
        query = (intent.target or intent.context or "").strip()
        if not query:
            return {}
        try:
            task = AgentTask(
                agent="MemoryAgent",
                action="search",
                parameters={"query": query},
            )
            engine_result = self.execution_engine.execute([task])
            # execute() returns a structured AgentResult for single MemoryAgent tasks
            # (via the _last_structured mechanism introduced in Phase 2.3/2.4).
            if hasattr(engine_result, "data"):
                retrieved = (engine_result.data or {}).get("results", [])
                if retrieved:
                    self.logger.debug(
                        "Memory-assisted planning: %d context item(s) for goal=%s query=%r",
                        len(retrieved), intent.goal, query,
                    )
                    return {"retrieved_memories": retrieved, "query": query}
            return {}
        except Exception as exc:
            self.logger.debug(
                "Memory context retrieval skipped for goal=%s: %s", intent.goal, exc
            )
            return {}

    def route(self, text: str, request_id: str = "") -> CommandResult | None:
        normalized = normalize_text(text)
        if not normalized:
            return None

        # ── Day 1 Evolution: Goal-driven Intent & Planner Pipeline ───────────
        try:
            intent = self.intent_analyzer.analyze(text)
            if intent.goal != "general":
                self.logger.info("Goal-driven pipeline triggered: Goal=%s, Context=%s", intent.goal, intent.context)
                planning_context = self._retrieve_planning_context(intent)
                steps = self.planner.plan(intent, planning_context=planning_context)
                coordinated = self.coordinator.coordinate(steps, request_id)
                result_message = " ".join(result.message for result in coordinated.results)
                return CommandResult(coordinated.success, result_message or coordinated.error)
        except Exception as exc:
            self.logger.exception("Goal-driven pipeline failed, falling back: %s", exc)

        if self.automation.has_pending_confirmation():
            local_result = self.automation.execute_local_command(normalized)
            if local_result is not None:
                self.logger.info("Command handled: %s", normalized)
                return CommandResult(True, local_result)

        if contains_stop_phrase(normalized):
            return CommandResult(True, "Going back to wake word listening mode.", should_sleep=True)

        if self.plugins is not None:
            plugin_result = self.plugins.dispatch(text)
            if plugin_result is not None:
                return CommandResult(True, plugin_result)

        for handler in (
            self._route_ai_modes,
            self._route_memory,
            self._route_vision,
            self._route_rag,
            self._route_mcp,
            self._route_automation,
            self._route_application,
            self._route_web,
            self._route_system,
            self._route_productivity,
        ):
            if handler == self._route_web:
                result = handler(text, normalized, request_id)
            else:
                result = handler(text, normalized)
            if result is not None:
                self.logger.info("Command handled: %s", normalized)
                return CommandResult(True, result)

        return None

    def _fuzzy_match(self, text: str, target: str, threshold: float = 0.75) -> bool:
        """Check if text fuzzy-matches target using ratio and partial ratio."""
        ratio = difflib.SequenceMatcher(None, text, target).ratio()
        if ratio >= threshold:
            return True
        partial = difflib.SequenceMatcher(None, text, target).find_longest_match(0, len(text), 0, len(target)).size
        if partial / max(len(text), len(target)) >= threshold:
            return True
        return False

    def _match_aliases(self, text: str, normalized: str, aliases: dict[str, list[str]]) -> str | None:
        """Match text against a set of aliases and return the canonical key."""
        for canonical, alias_list in aliases.items():
            if normalized == canonical or self._fuzzy_match(normalized, canonical):
                return canonical
            for alias in alias_list:
                if normalized == alias or self._fuzzy_match(normalized, alias):
                    return canonical
        return None

    def _route_ai_modes(self, text: str, normalized: str) -> str | None:
        if self.orchestrator is None:
            return None
        prefixes = ["switch to", "use", "enable", "activate", "enter", "go to", "change to"]
        for prefix in prefixes:
            if normalized.startswith(prefix + " ") and normalized.endswith(" mode"):
                mode = normalized[len(prefix) + 1 : -5].strip()
                return self.orchestrator.set_mode(mode)
        mode_aliases = {
            "reasoning mode": "reasoning",
            "coding mode": "coding",
            "research mode": "research",
            "planning mode": "planning",
            "creative mode": "creative",
            "debug mode": "debug",
        }
        for phrase, mode in mode_aliases.items():
            if normalized == phrase or self._fuzzy_match(normalized, phrase):
                return self.orchestrator.set_mode(mode)
        return None

    def _route_memory(self, text: str, normalized: str) -> str | None:
        if self.memory is None:
            return None
        remember = strip_command_prefix(text, ["remember that", "remember", "save that", "keep in mind", "note that"])
        if remember:
            self.memory.remember(remember, kind="preference", importance=0.75)
            return "I will remember that."
        forget = strip_command_prefix(text, ["forget that", "forget memory", "forget", "delete memory", "remove memory"])
        if forget:
            count = self.memory.forget(forget)
            return f"Forgot {count} matching memory item{'s' if count != 1 else ''}."
        search = strip_command_prefix(text, ["search memory for", "memory search for", "search memory", "find in memory", "look up memory"])
        if search:
            results = self.memory.search(search)
            if not results:
                return "I did not find a matching memory."
            return "Memory matches: " + "; ".join((item.summary or item.content) for item in results[:5]) + "."
        if normalized in {"backup memory", "memory backup", "save memory", "export memory"}:
            path = self.memory.backup()
            return f"Memory backup saved to {path}."
        return None

    def _route_vision(self, text: str, normalized: str) -> str | None:
        if self.vision is None:
            return None
        vision_commands = {
            "analyze screen": ["analyze screen", "read screen", "screen understanding", "analyze screenshot", "what's on screen", "what is on screen", "describe screen", "look at screen"],
            "analyze webcam": ["analyze webcam", "open webcam", "webcam support", "look through webcam", "camera", "what do you see"],
        }
        for command, phrases in vision_commands.items():
            if normalized in phrases or any(self._fuzzy_match(normalized, p) for p in phrases):
                if command == "analyze screen":
                    result = self.vision.analyze_screen()
                    if result.text:
                        return result.summary + " Text: " + result.text[:700]
                    return result.summary
                else:
                    return self.vision.analyze_webcam().summary
        image_path = strip_command_prefix(text, ["analyze image", "read image", "ocr image", "describe image", "look at image"])
        if image_path:
            result = self.vision.analyze_image(Path(image_path).expanduser())
            if result.text:
                return result.summary + " Text: " + result.text[:700]
            return result.summary
        return None

    def _route_rag(self, text: str, normalized: str) -> str | None:
        if self.rag is None:
            return None
        path_text = strip_command_prefix(text, ["index document", "ingest document", "index file", "ingest file", "add document", "add file"])
        if path_text:
            document_id = self.rag.ingest_path(Path(path_text).expanduser())
            return f"Document indexed with id {document_id}."
        query = strip_command_prefix(text, ["search documents for", "search document for", "document search for", "search documents", "find in documents", "look up document"])
        if query:
            results = self.rag.search(query)
            if not results:
                return "I did not find matching document context."
            return "Document matches: " + "; ".join(f"{item.citation}: {item.content[:180]}" for item in results) + "."
        context_query = strip_command_prefix(text, ["document context for", "chat with documents about", "ask documents about", "query documents"])
        if context_query:
            return self.rag.answer_context(context_query)
        return None

    def _route_mcp(self, text: str, normalized: str) -> str | None:
        if self.mcp is None:
            return None
        match = re.search(r"list mcp tools(?: from)?\s+(.+)$", normalized)
        if match:
            server = match.group(1).strip()
            tools = self.mcp.list_tools(server)
            if not tools:
                return f"No MCP tools were reported by {server}."
            names = [str(tool.get("name", "unknown")) for tool in tools]
            return f"MCP tools on {server}: " + ", ".join(names[:12]) + "."
        match = re.search(r"call mcp\s+(.+?)\s+tool\s+(.+?)(?:\s+with\s+(.+))?$", normalized)
        if match:
            import json

            server = match.group(1).strip()
            tool = match.group(2).strip()
            raw_args = match.group(3) or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"input": raw_args}
            result = self.mcp.call_tool(server, tool, args)
            return "MCP tool result: " + str(result)[:900]
        return None

    def _route_application(self, text: str, normalized: str) -> str | None:
        # Check exact app commands
        app_commands = {
            "open chrome": "chrome",
            "open edge": "edge",
            "open microsoft edge": "edge",
            "open firefox": "firefox",
            "open vs code": "vs code",
            "open visual studio code": "vs code",
            "open cursor": "cursor",
            "open notepad": "notepad",
            "open calculator": "calculator",
            "open paint": "paint",
            "open terminal": "terminal",
            "open windows terminal": "terminal",
            "open task manager": "task manager",
            "open settings": "settings",
            "open control panel": "control panel",
            "open file explorer": "file explorer",
        }
        folder_commands = {
            "open downloads": "downloads",
            "open documents": "documents",
            "open desktop": "desktop",
            "open pictures": "pictures",
            "open videos": "videos",
            "open music": "music",
        }

        # Check exact matches first
        for phrase, app_name in app_commands.items():
            if normalized == phrase:
                return self.applications.open_application(app_name)
        for phrase, folder in folder_commands.items():
            if normalized == phrase:
                return self.applications.open_folder(folder)

        # Fuzzy match: "open <app>" patterns
        open_match = re.match(r"^(?:open|launch|start|run)\s+(.+)$", normalized)
        if open_match:
            app_name = open_match.group(1).strip()
            # Check app aliases
            matched = self._match_aliases(app_name, app_name, self._app_aliases)
            if matched:
                return self.applications.open_application(matched)
            # Check folder aliases
            matched = self._match_aliases(app_name, app_name, self._folder_aliases)
            if matched:
                return self.applications.open_folder(matched)
            # Try direct open
            result = self.applications.open_application(app_name)
            if "not found" not in result.lower():
                return result

        # Restart, kill, close, minimize, maximize, switch
        restart = strip_command_prefix(text, ["restart application", "restart app", "relaunch"])
        if restart:
            return self.applications.restart_application(restart)
        kill = strip_command_prefix(text, ["kill process", "terminate process", "force close", "stop process", "end process"])
        if kill:
            return self.applications.kill_process(kill)
        if normalized in {"close current application", "close current app", "close window", "close app", "close program"}:
            return self.applications.close_current_application()
        if normalized in {"minimize window", "minimise window", "minimize", "minimise"}:
            return self.applications.minimize_window()
        if normalized in {"maximize window", "maximise window", "maximize", "maximise", "full screen"}:
            return self.applications.maximize_window()
        if normalized in {"switch windows", "switch window", "switch app", "switch application", "alt tab"}:
            return self.applications.switch_windows()
        return None

    def _route_web(self, text: str, normalized: str, request_id: str = "") -> str | None:
        # Check exact site matches
        for site in sorted(self.browser.sites, key=len, reverse=True):
            if normalized == f"open {site}":
                return self.browser.open_site(site, request_id)

        # Fuzzy site open: "open <site>"
        open_match = re.match(r"^(?:open|go to|navigate to|launch|take me to)\s+(.+)$", normalized)
        if open_match:
            site_name = open_match.group(1).strip()
            # Check site aliases
            matched = self._match_aliases(site_name, site_name, self._site_aliases)
            if matched:
                return self.browser.open_site(matched, request_id)
            # Try direct site open
            for site in sorted(self.browser.sites, key=len, reverse=True):
                if site_name == site or self._fuzzy_match(site_name, site):
                    return self.browser.open_site(site, request_id)

        # Search engines
        searchers = {
            "google": self.browser.search_google,
            "youtube": self.browser.search_youtube,
            "wikipedia": self.browser.search_wikipedia,
            "github": self.browser.search_github,
        }
        for engine, searcher in searchers.items():
            prefixes = [
                f"search {engine} for",
                f"search on {engine} for",
                f"{engine} search for",
                f"search {engine}",
                f"look up on {engine}",
                f"find on {engine}",
            ]
            query = strip_command_prefix(text, prefixes)
            if query or any(normalized == prefix for prefix in prefixes):
                return searcher(query, request_id)

        # Exact music phrase checks first
        if normalized in {"song", "search song", "search songs", "play song", "play music"}:
            self.logger.info("Music command received")
            self.logger.info("BrowserController invoked")
            return self.browser.open_site("youtube", request_id)

        music_patterns = [
            r"^(?:play|search)\s+(.+?)\s+on\s+youtube$",
            r"^(?:play|search)\s+songs?\s+for\s+(.+)$",
            r"^(?:play|search)\s+songs?\s+(.+)$",
            r"^(?:play|search)\s+music\s+for\s+(.+)$",
            r"^(?:play|search)\s+music\s+(.+)$",
            r"^play\s+(.+)$",
            r"^search\s+(.+)$",
        ]

        for pattern in music_patterns:
            match = re.match(pattern, normalized)
            if match:
                song_name = match.group(1).strip()
                if song_name and song_name not in self.browser.sites:
                    self.logger.info("Music command received")
                    self.logger.info("BrowserController invoked")
                    return self.browser.search_youtube(song_name, request_id)

        return None

    def _route_system(self, text: str, normalized: str) -> str | None:
        # Check exact and aliased system commands
        system_commands = {
            "increase volume": self.system.increase_volume,
            "decrease volume": self.system.decrease_volume,
            "mute": self.system.mute,
            "unmute": self.system.unmute,
            "brightness up": self.system.brightness_up,
            "brightness down": self.system.brightness_down,
            "take screenshot": self.system.take_screenshot,
            "lock pc": self.system.lock_pc,
            "sleep pc": self.system.sleep_pc,
            "restart pc": self.system.restart_pc,
            "shutdown pc": self.system.shutdown_pc,
            "empty recycle bin": self.system.empty_recycle_bin,
            "show battery": self.system.show_battery,
            "show cpu usage": self.system.show_cpu_usage,
            "show ram usage": self.system.show_ram_usage,
            "show disk usage": self.system.show_disk_usage,
        }

        for canonical, func in system_commands.items():
            if normalized == canonical:
                return func()
            matched = self._match_aliases(text, normalized, self._system_aliases)
            if matched == canonical:
                return func()

        # Windows search
        query = strip_command_prefix(text, ["windows search for", "search windows for", "search my computer for", "find on my computer"])
        if query:
            return self.system.windows_search(query)

        # Environment variables
        env_name = strip_command_prefix(text, ["get environment variable", "show environment variable", "read environment variable"])
        if env_name:
            return self.system.get_environment_variable(env_name)
        env_match = re.search(r"set environment variable\s+(.+?)\s+to\s+(.+)$", normalized)
        if env_match:
            return self.system.set_environment_variable(env_match.group(1), env_match.group(2))
        return None

    def _route_productivity(self, text: str, normalized: str) -> str | None:
        folder_name = strip_command_prefix(text, ["create folder", "make folder", "new folder", "create directory", "make directory"])
        if folder_name or normalized in {"create folder", "make folder", "new folder"}:
            return self.system.create_folder(strip_name_words(folder_name) or "New Folder")

        file_name = strip_command_prefix(text, ["create file", "make file", "new file", "create document", "create text file"])
        if file_name or normalized in {"create file", "make file", "new file"}:
            return self.system.create_file(strip_name_words(file_name) or "new_file.txt")

        rename_match = re.search(r"rename file\s+(.+?)\s+to\s+(.+)$", normalized)
        if rename_match:
            return self.system.rename_file(rename_match.group(1), rename_match.group(2))
        move_match = re.search(r"move file\s+(.+?)\s+to\s+(.+)$", normalized)
        if move_match:
            return self.system.move_file(move_match.group(1), move_match.group(2))

        delete_name = strip_command_prefix(text, ["delete file", "remove file", "erase file", "delete document"])
        if delete_name or normalized in {"delete file", "remove file", "erase file"}:
            return self.system.delete_file(strip_name_words(delete_name))

        search_query = strip_command_prefix(text, ["search files for", "search files", "find file", "find files", "search for file", "locate file"])
        if search_query or normalized in {"search files", "find files", "locate files"}:
            return self.system.search_files(search_query)

        if normalized in {"open recent files", "recent files", "recent documents", "recently used"}:
            return self.system.open_recent_files()
        if normalized in {"read clipboard", "what is on clipboard", "clipboard content", "show clipboard"}:
            return self.system.read_clipboard()
        if normalized in {"clipboard manager", "clipboard history", "clipboard"}:
            return self.system.clipboard_manager()

        copy_text = strip_command_prefix(text, ["copy text", "copy", "copy to clipboard"])
        if copy_text or normalized in {"copy text", "copy"}:
            return self.system.copy_text(copy_text)
        if normalized in {"paste text", "paste", "paste from clipboard"}:
            return self.system.paste_text()
        return None

    def _route_automation(self, text: str, normalized: str) -> str | None:
        local_result = self.automation.execute_local_command(normalized)
        if local_result is not None:
            return local_result

        # Timer
        if normalized.startswith("set timer") or normalized.startswith("create timer") or normalized.startswith("start timer"):
            return self.automation.set_timer(text)
        # Reminder
        if normalized.startswith("set reminder") or normalized.startswith("remind me") or normalized.startswith("create reminder"):
            return self.automation.set_reminder(text)
        # Alarm
        if normalized.startswith("set alarm") or normalized.startswith("create alarm") or normalized.startswith("wake me up"):
            return self.automation.set_alarm(text)
        # Todo
        if normalized.startswith("add todo") or normalized.startswith("create todo") or normalized.startswith("add to do") or normalized.startswith("add task"):
            return self.automation.add_todo(text)

        # Check automation aliases
        matched = self._match_aliases(text, normalized, self._automation_aliases)
        if matched == "list todos":
            return self.automation.list_todos()
        if matched == "read calendar":
            return self.automation.read_calendar()
        if matched == "open outlook":
            return self.automation.open_outlook()
        if matched == "read notifications":
            return self.automation.read_notifications()
        if matched == "news":
            return self.automation.news()

        # Notes
        if normalized.startswith("create note") or normalized.startswith("take note") or normalized.startswith("write note") or normalized.startswith("make a note"):
            return self.automation.create_note(text)
        if normalized.startswith("meeting note") or normalized.startswith("meeting assistant") or normalized.startswith("meeting summary"):
            return self.automation.meeting_summary_note(text)

        # Weather, currency, stocks, crypto
        if normalized.startswith("weather") or normalized.startswith("forecast"):
            return self.automation.weather(text)
        if normalized in {"news", "latest news", "read news", "show news", "headlines", "top stories"}:
            return self.automation.news()
        if normalized.startswith("currency") or normalized.startswith("exchange rate") or normalized.startswith("convert "):
            return self.automation.currency(text)
        if normalized.startswith("stock price") or normalized.startswith("show stock price") or normalized.startswith("price of stock"):
            return self.automation.stock_price(text)
        if normalized.startswith("crypto price") or normalized.endswith(" bitcoin price") or normalized in {"bitcoin price", "ethereum price"}:
            return self.automation.crypto_price(text)
        return None

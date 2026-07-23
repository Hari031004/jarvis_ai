"""Browser agent with context-aware session, multi-tab state tracking, and generic automation APIs."""

from __future__ import annotations

import re
import time
import urllib.parse
import webbrowser
import logging
from dataclasses import dataclass, field
from typing import Any

import pyautogui
import requests

try:
    import pygetwindow as gw
except ImportError:
    gw = None

from assistant.utils.logger import get_logger
from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, BrowserPayload

logger = logging.getLogger(__name__)


@dataclass
class TabState:
    """Represents the context and history of an individual browser tab."""
    id: int
    url: str = ""
    domain: str = ""
    page_type: str = "none"         # none, homepage, search, video
    last_query: str = ""
    history: list[str] = field(default_factory=list)
    current_index: int = 0          # Result pointer index (1-based)


@dataclass
class AgentResult:
    """Structured result returned by the Browser Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class BrowserController:
    """Upgraded Swappable Browser Agent.

    Manages multiple tabs, active session state, navigation histories, and executes
    generic UI automation tasks using pywin32/pyautogui fallback controllers.
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self.sites = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "github": "https://github.com",
            "chatgpt": "https://chatgpt.com",
            "claude": "https://claude.ai",
            "stack overflow": "https://stackoverflow.com",
            "linkedin": "https://www.linkedin.com",
            "whatsapp web": "https://web.whatsapp.com",
            "google calendar": "https://calendar.google.com",
            "google drive": "https://drive.google.com",
            "google docs": "https://docs.google.com",
            "google sheets": "https://sheets.google.com",
            "google meet": "https://meet.google.com",
            "telegram": "https://web.telegram.org",
            "discord": "https://discord.com/app",
            "slack": "https://app.slack.com/client",
            "microsoft teams": "https://teams.microsoft.com",
            "twitter": "https://x.com",
            "x": "https://x.com",
            "instagram": "https://www.instagram.com",
            "facebook": "https://www.facebook.com",
            "netflix": "https://www.netflix.com",
            "spotify": "https://open.spotify.com",
            "prime video": "https://www.primevideo.com",
        }

        # ── Multi-Tab & Session State Model ──────────────────────────────────
        self.tabs: list[TabState] = [TabState(id=1)]
        self.active_tab_id: int = 1
        self.search_history: list[str] = []
        self.session_start_time: float = time.time()

    # ── Backward Compatible Property Redirects ───────────────────────────────

    @property
    def current_url(self) -> str:
        active = self._get_active_tab()
        return active.url if active else ""

    @current_url.setter
    def current_url(self, val: str) -> None:
        active = self._get_active_tab()
        if active:
            active.url = val

    @property
    def current_domain(self) -> str:
        active = self._get_active_tab()
        return active.domain if active else ""

    @current_domain.setter
    def current_domain(self, val: str) -> None:
        active = self._get_active_tab()
        if active:
            active.domain = val

    @property
    def current_page_type(self) -> str:
        active = self._get_active_tab()
        return active.page_type if active else "none"

    @current_page_type.setter
    def current_page_type(self, val: str) -> None:
        active = self._get_active_tab()
        if active:
            active.page_type = val

    @property
    def last_query(self) -> str:
        active = self._get_active_tab()
        return active.last_query if active else ""

    @last_query.setter
    def last_query(self, val: str) -> None:
        active = self._get_active_tab()
        if active:
            active.last_query = val

    @property
    def current_index(self) -> int:
        active = self._get_active_tab()
        return active.current_index if active else 0

    @current_index.setter
    def current_index(self, val: int) -> None:
        active = self._get_active_tab()
        if active:
            active.current_index = val

    @property
    def navigation_history(self) -> list[str]:
        active = self._get_active_tab()
        return active.history if active else []

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Check if the action is a supported generic browser command."""
        supported_actions = {
            "open", "search", "navigate", "click", "scroll",
            "go_back", "go_forward", "refresh", "new_tab",
            "switch_tab", "close_tab", "play_result", "open_result"
        }
        return task.action in supported_actions

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}
        
        # Verify active tab existence
        active_tab = self._get_active_tab()
        if not active_tab:
            return AgentResult(success=False, message="No active tab available.", error="missing_active_tab")

        try:
            if action == "open":
                name = params.get("name") or params.get("site") or ""
                msg = self.open(name)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "search":
                query = params.get("query") or ""
                msg = self.search(query)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "navigate":
                url = params.get("url") or ""
                msg = self.navigate(url)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "click":
                x = int(params.get("x", 0))
                y = int(params.get("y", 0))
                msg = self.click(x, y)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "scroll":
                direction = params.get("direction", "down")
                msg = self.scroll(direction)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "go_back":
                msg = self.go_back()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "go_forward":
                msg = self.go_forward()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "refresh":
                msg = self.refresh()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "new_tab":
                url = params.get("url", "")
                msg = self.new_tab(url)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "switch_tab":
                tab_id = int(params.get("tab_id", 1))
                msg = self.switch_tab(tab_id)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "close_tab":
                msg = self.close_tab()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action in ("play_result", "open_result"):
                index = int(params.get("index", 1))
                result = self.play_result(index)
                if isinstance(result, AgentResult):
                    return result
                return AgentResult(success=True, message=result, data=self.get_state())

            else:
                return AgentResult(
                    success=False, 
                    message=f"Unsupported action: {action}", 
                    error="unsupported_action"
                )

        except ModuleNotFoundError as exc:
            self.logger.warning("Agent=BrowserAgent Action=%s Failure=missing_dependency: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            self.logger.warning("Agent=BrowserAgent Action=%s Failure=timeout: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            logger.exception("BrowserAgent execution error")
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        """Conforms to AgentInterface state reporting."""
        return self.get_state()

    def health(self) -> str:
        """Report agent status."""
        return "healthy"

    def reset(self) -> None:
        """Reset internal tabs and states to defaults."""
        self.tabs = [TabState(id=1)]
        self.active_tab_id = 1
        self.search_history = []
        self.session_start_time = time.time()

    # ── State Awareness Queries ──────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """Expose current multi-tab context and history logs."""
        active_tab = self._get_active_tab()
        return {
            "current_url": active_tab.url if active_tab else "",
            "current_domain": active_tab.domain if active_tab else "",
            "current_page_type": active_tab.page_type if active_tab else "none",
            "last_query": active_tab.last_query if active_tab else "",
            "active_tab": self.active_tab_id,
            "current_tab": self.active_tab_id,
            "current_index": active_tab.current_index if active_tab else 0,
            "history_count": len(active_tab.history) if active_tab else 0,
            "total_tabs": len(self.tabs),
            "tabs": [
                {
                    "id": tab.id,
                    "url": tab.url,
                    "domain": tab.domain,
                    "page_type": tab.page_type
                } for tab in self.tabs
            ]
        }

    # ── Generic swappable automation actions ──────────────────────────────────

    def open(self, name: str, request_id: str = "") -> str:
        """Open site name or search query if domain is missing."""
        if not name:
            return "No URL or site name provided."
        
        # Check if name is in site keys
        url = self.sites.get(name.lower().strip())
        if not url:
            if name.startswith("http://") or name.startswith("https://") or "." in name:
                return self.navigate(name, request_id)
            return self.search(name, request_id)
        
        active_tab = self._get_active_tab()
        is_initial_navigation = bool(active_tab and not active_tab.url)
        if is_initial_navigation:
            navigated = bool(webbrowser.open(url))
        else:
            navigated = self._navigate_active_tab(url)
        if not navigated:
            return f"Could not navigate the active browser tab to {name.title()}."
        if active_tab:
            active_tab.url = url
            active_tab.domain = name.lower().strip()
            active_tab.page_type = "homepage"
            active_tab.history.append(url)

        publish_event(
            EventType.BROWSER_OPENED,
            payload=BrowserPayload(url=url, tab_title=name.title(), action="open"),
            source=EventSource.BROWSER,
            session_id=request_id
        )
        return f"{name.title()} is open."

    def search(self, query: str, request_id: str = "") -> str:
        """Perform search query contextually on active tab domain."""
        if not query:
            return "Tell me what to search for."
        
        active_tab = self._get_active_tab()
        domain = active_tab.domain if active_tab else "google"

        # Construct target URL
        if "youtube" in domain:
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            title = "YouTube Search"
        elif "github" in domain:
            url = f"https://github.com/search?q={urllib.parse.quote_plus(query)}"
            title = "GitHub Search"
        elif "wikipedia" in domain:
            url = f"https://en.wikipedia.org/wiki/Special:Search?search={urllib.parse.quote_plus(query)}"
            title = "Wikipedia Search"
        else:
            domain = "google.com"
            url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
            title = "Google Search"

        if not self._navigate_active_tab(url):
            return f"Could not navigate the active browser tab to search for {query}."

        self.search_history.append(query)
        if active_tab:
            active_tab.last_query = query
            active_tab.current_index = 0
            active_tab.page_type = "search"
            active_tab.url = url
            active_tab.domain = domain
            active_tab.history.append(url)

        publish_event(
            EventType.BROWSER_NAVIGATED,
            payload=BrowserPayload(url=url, tab_title=title, action="navigate"),
            source=EventSource.BROWSER,
            session_id=request_id
        )
        return f"Searching {domain.split('.')[0].title()} for {query}."

    def navigate(self, url: str, request_id: str = "") -> str:
        """Directly navigate active tab to raw destination URL."""
        if not url:
            return "No URL provided."
        
        target_url = url
        if not (url.startswith("http://") or url.startswith("https://")):
            target_url = "https://" + url

        parsed = urllib.parse.urlparse(target_url)
        domain = parsed.netloc or parsed.path

        active_tab = self._get_active_tab()
        if not self._navigate_active_tab(target_url):
            return f"Could not navigate the active browser tab to {target_url}."
        if active_tab:
            active_tab.url = target_url
            active_tab.domain = domain
            active_tab.page_type = "homepage"
            active_tab.history.append(target_url)

        publish_event(
            EventType.BROWSER_NAVIGATED,
            payload=BrowserPayload(url=target_url, tab_title="Direct Navigation", action="navigate"),
            source=EventSource.BROWSER,
            session_id=request_id
        )
        return f"Navigated to {target_url}."

    def click(self, x: int, y: int) -> str:
        """Execute click action at coordinates (x, y) on desktop window."""
        pyautogui.click(x, y)
        return f"Clicked browser at coordinate ({x}, {y})."

    def scroll(self, direction: str) -> str:
        """Execute mouse wheel scroll."""
        amount = -400 if direction == "down" else 400
        pyautogui.scroll(amount)
        return f"Scrolled browser page {direction}."

    def go_back(self, request_id: str = "") -> str:
        """Navigate backwards in current active tab navigation history."""
        active_tab = self._get_active_tab()
        if active_tab and len(active_tab.history) > 1:
            active_tab.history.pop()
            prev_url = active_tab.history[-1]
            active_tab.url = prev_url
            active_tab.domain = urllib.parse.urlparse(prev_url).netloc
            active_tab.page_type = "search" if "search" in prev_url or "results" in prev_url else "homepage"
        
        pyautogui.hotkey("alt", "left")
        return "Navigated back to the previous page."

    def go_forward(self, request_id: str = "") -> str:
        """Simulate browser forward action."""
        pyautogui.hotkey("alt", "right")
        return "Navigated forward."

    def refresh(self) -> str:
        """Simulate browser page refresh."""
        pyautogui.hotkey("ctrl", "r")
        return "Refreshed browser page."

    def new_tab(self, url: str = "") -> str:
        """Open a new stateful tab, opening raw URL if specified."""
        new_id = max(tab.id for tab in self.tabs) + 1
        new_tab_state = TabState(id=new_id)
        
        if url:
            target_url = url if (url.startswith("http://") or url.startswith("https://")) else "https://" + url
            new_tab_state.url = target_url
            new_tab_state.domain = urllib.parse.urlparse(target_url).netloc
            new_tab_state.page_type = "homepage"
            new_tab_state.history.append(target_url)
            webbrowser.open(target_url)
        else:
            pyautogui.hotkey("ctrl", "t")

        self.tabs.append(new_tab_state)
        self.active_tab_id = new_id
        return f"Opened new browser tab #{new_id}."

    def switch_tab(self, tab_id: int) -> str:
        """Switch active focus tab identifier."""
        exists = any(tab.id == tab_id for tab in self.tabs)
        if not exists:
            return f"Tab ID {tab_id} does not exist."
        
        idx = next(i for i, tab in enumerate(self.tabs) if tab.id == tab_id)
        pyautogui.hotkey("ctrl", str(min(9, idx + 1)))
        
        self.active_tab_id = tab_id
        return f"Switched focus to tab #{tab_id}."

    def close_tab(self, request_id: str = "") -> str:
        """Close active tab index and fallback focus."""
        pyautogui.hotkey("ctrl", "w")
        
        active_idx = next(i for i, tab in enumerate(self.tabs) if tab.id == self.active_tab_id)
        self.tabs.pop(active_idx)
        
        if not self.tabs:
            self.tabs = [TabState(id=1)]
        
        self.active_tab_id = self.tabs[-1].id
        return "Closed the active browser tab."

    def play_result(self, index: int = 1, request_id: str = "") -> AgentResult | str:
        """Open a normal YouTube video result, excluding Shorts shelves."""
        active_tab = self._get_active_tab()
        if not active_tab or not active_tab.last_query:
            return AgentResult(False, "No active search context query.", error="result_not_found")

        domain = active_tab.domain

        if "youtube" in domain:
            if index < 1:
                return AgentResult(False, "Result index must be greater than zero.", error="result_not_found")

            try:
                response = requests.get(
                    active_tab.url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                return AgentResult(False, f"Unable to retrieve YouTube results: {exc}", error="result_not_found")

            # YouTube represents standard search cards as ``videoRenderer``;
            # Shorts shelves use reel renderers and are deliberately excluded.
            video_ids = re.findall(
                r'"videoRenderer"\s*:\s*\{\s*"videoId"\s*:\s*"([^"]+)"',
                response.text,
            )
            video_ids = list(dict.fromkeys(video_ids))
            if index > len(video_ids):
                return AgentResult(False, f"Video result #{index} was not found.", error="result_not_found")

            watch_url = f"https://www.youtube.com/watch?v={video_ids[index - 1]}"
            if not self._navigate_active_tab(watch_url):
                return AgentResult(False, f"Browser could not open video result #{index}.", error="navigation_failed")

            active_tab.current_index = index
            active_tab.url = watch_url
            active_tab.domain = "youtube.com"
            active_tab.page_type = "video"
            active_tab.history.append(watch_url)

            publish_event(
                EventType.BROWSER_NAVIGATED,
                payload=BrowserPayload(url=watch_url, tab_title="Playing Video", action="navigate"),
                source=EventSource.BROWSER,
                session_id=request_id
            )
            return AgentResult(
                True,
                f"Playing video result #{index} for '{active_tab.last_query}'.",
                data=self.get_state(),
            )

        else:
            lucky_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(active_tab.last_query)}&btnI=I"
            active_tab.url = lucky_url
            active_tab.page_type = "homepage"
            active_tab.history.append(lucky_url)

            publish_event(
                EventType.BROWSER_NAVIGATED,
                payload=BrowserPayload(url=lucky_url, tab_title="Opening Search Result", action="navigate"),
                source=EventSource.BROWSER,
                session_id=request_id
            )
            self._navigate_active_tab(lucky_url)
            return f"Opening search link result #{index} for '{active_tab.last_query}'."

    def open_result(self, index: int, request_id: str = "") -> str:
        """Alias for play_result to align generic names."""
        result = self.play_result(index, request_id)
        return result.message if isinstance(result, AgentResult) else result

    # ── Backward Compatibility Methods ───────────────────────────────────────

    def open_site(self, name: str, request_id: str = "") -> str:
        return self.open(name, request_id)

    def search_google(self, query: str, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        if active_tab:
            active_tab.domain = "google.com"
        return self.search(query, request_id)

    def search_youtube(self, query: str, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        if active_tab:
            active_tab.domain = "youtube.com"
        return self.search(query, request_id)

    def search_wikipedia(self, query: str, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        if active_tab:
            active_tab.domain = "wikipedia.org"
        return self.search(query, request_id)

    def search_github(self, query: str, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        if active_tab:
            active_tab.domain = "github.com"
        return self.search(query, request_id)

    def next_result(self, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        next_idx = (active_tab.current_index + 1) if (active_tab and active_tab.current_index > 0) else 1
        if active_tab:
            active_tab.current_index = next_idx
            if "youtube" in active_tab.domain and active_tab.page_type == "video":
                pyautogui.hotkey("shift", "n")
                return "Playing next video on YouTube."
        result = self.play_result(next_idx, request_id)
        return result.message if isinstance(result, AgentResult) else result

    def previous_result(self, request_id: str = "") -> str:
        active_tab = self._get_active_tab()
        prev_idx = max(1, (active_tab.current_index - 1) if active_tab else 1)
        if active_tab:
            active_tab.current_index = prev_idx
            if "youtube" in active_tab.domain and active_tab.page_type == "video":
                pyautogui.hotkey("shift", "p")
                return "Playing previous video on YouTube."
        result = self.play_result(prev_idx, request_id)
        return result.message if isinstance(result, AgentResult) else result

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _get_active_tab(self) -> TabState | None:
        for tab in self.tabs:
            if tab.id == self.active_tab_id:
                return tab
        if self.tabs:
            return self.tabs[0]
        return None

    def _navigate_active_tab(self, url: str) -> bool:
        """Navigate the current browser tab without creating a new one."""
        active_tab = self._get_active_tab()
        if active_tab and active_tab.url:
            try:
                self._focus_browser_window(active_tab.domain)
                pyautogui.hotkey("ctrl", "l")
                pyautogui.write(url, interval=0.001)
                pyautogui.press("enter")
                return True
            except Exception as exc:
                self.logger.warning("Could not navigate active browser tab: %s", exc)
                return False
        return bool(webbrowser.open(url))

    @staticmethod
    def _focus_browser_window(domain: str) -> None:
        """Bring the active browser window forward before address-bar navigation."""
        if gw is None:
            return
        try:
            browser_titles = ("Google Chrome", "Microsoft Edge", "Mozilla Firefox")
            windows = [window for window in gw.getAllWindows() if window.title and any(name in window.title for name in browser_titles)]
            matching = next((window for window in windows if domain and domain.lower() in window.title.lower()), None)
            window = matching or (gw.getActiveWindow() if gw.getActiveWindow() in windows else (windows[0] if windows else None))
            if window:
                if window.isMinimized:
                    window.restore()
                window.activate()
        except Exception:
            # Keyboard navigation remains the fallback for platforms without a
            # window manager API or where focus changes are restricted.
            pass

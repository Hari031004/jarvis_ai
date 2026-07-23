"""Windows application and window control Desktop Agent V1."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import psutil
import pyautogui

try:
    import pygetwindow as gw
except ImportError:
    gw = None

from assistant.config import Settings
from assistant.utils.helpers import open_path
from assistant.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentResult:
    """Structured result returned by the Desktop Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class ApplicationController:
    """Upgraded Desktop Agent V1.

    Manages operating system applications, window states, and lists running tasks.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self._apps: dict[str, list[str | Path]] = {
            "chrome": ["chrome.exe", Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe"],
            "edge": ["msedge.exe"],
            "firefox": ["firefox.exe"],
            "vs code": ["code.cmd", "code.exe"],
            "cursor": ["cursor.cmd", "cursor.exe"],
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "paint": ["mspaint.exe"],
            "terminal": ["wt.exe", "powershell.exe", "cmd.exe"],
            "task manager": ["taskmgr.exe"],
            "control panel": ["control.exe"],
            "file explorer": ["explorer.exe"],
            "outlook": ["outlook.exe"],
        }

        # ── Desktop Agent State variables ────────────────────────────────────
        self.active_app: str = ""
        self.active_window_title: str = ""
        self.recently_opened_apps: list[str] = []

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Check if action is a supported desktop application task."""
        supported = {
            "open_application", "close_application", "focus_application",
            "minimize", "maximize", "restore", "switch_window",
            "list_running_apps", "get_active_window"
        }
        return task.action in supported

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}
        name = params.get("name", "")

        try:
            if action == "open_application":
                msg = self.open_app(name)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "close_application":
                msg = self.close_app(name)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "focus_application":
                msg = self.focus_app(name)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "minimize":
                msg = self.minimize()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "maximize":
                msg = self.maximize()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "restore":
                msg = self.restore()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "switch_window":
                msg = self.switch_window()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "list_running_apps":
                apps = self.list_running_apps()
                return AgentResult(
                    success=True,
                    message=f"Detected {len(apps)} running applications.",
                    data={"running_applications": apps}
                )

            elif action == "get_active_window":
                win = self.get_active_window()
                return AgentResult(
                    success=True,
                    message=f"Active window title: '{win}'.",
                    data={"active_window": win}
                )

            else:
                return AgentResult(
                    success=False,
                    message=f"Unsupported action: {action}",
                    error="unsupported_action"
                )

        except ModuleNotFoundError as exc:
            self.logger.warning("Agent=DesktopAgent Action=%s Failure=missing_dependency: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            self.logger.warning("Agent=DesktopAgent Action=%s Failure=timeout: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            logger.exception("DesktopAgent execution failure")
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        return self.get_state()

    def health(self) -> str:
        return "healthy"

    def reset(self) -> None:
        self.active_app = ""
        self.active_window_title = ""
        self.recently_opened_apps = []

    # ── Desktop Agent APIs ───────────────────────────────────────────────────

    def open_app(self, name: str) -> str:
        """Launch desktop application by name and update state."""
        normalized = name.lower().strip()
        if normalized == "settings":
            self._open_uri("ms-settings:")
            self._update_active_state("Settings", "Settings Window")
            return "Settings is open."

        commands = self._apps.get(normalized)
        if not commands:
            # Try launching raw command directly
            try:
                subprocess.Popen([name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._update_active_state(name, name)
                return f"{name.title()} is open."
            except Exception:
                return f"Application '{name}' not found."

        for command in commands:
            try:
                executable = self._resolve_command(command)
                if executable:
                    subprocess.Popen([str(executable)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self._update_active_state(name, name.title())
                    return f"{name.title()} is open."
            except Exception as exc:
                self.logger.debug("Failed to launch %s with %s: %s", name, command, exc)

        try:
            subprocess.Popen(["cmd", "/c", "start", "", str(commands[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._update_active_state(name, name.title())
            return f"{name.title()} is open."
        except Exception as exc:
            self.logger.exception("Failed to open application %s", name)
            return f"I could not open {name}: {exc}"

    def close_app(self, name: str) -> str:
        """Terminate application process by name."""
        target = name.lower().strip().replace(".exe", "")
        aliases = {
            "chrome": "chrome",
            "edge": "msedge",
            "firefox": "firefox",
            "vs code": "code",
            "visual studio code": "code",
            "cursor": "cursor",
            "notepad": "notepad",
            "calculator": "calculator",
            "paint": "mspaint",
            "terminal": "WindowsTerminal",
            "outlook": "outlook",
        }
        process_name = aliases.get(target, target)
        count = 0
        for process in psutil.process_iter(["name"]):
            try:
                current = (process.info.get("name") or "").lower().replace(".exe", "")
                if current == process_name.lower():
                    process.terminate()
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if count == 0:
            return f"I did not find a running process named {name}."
        
        if self.active_app == name:
            self.active_app = ""
            self.active_window_title = ""
        return f"Terminated {count} {name} process{'es' if count != 1 else ''}."

    def focus_app(self, name: str) -> str:
        """Set window focus to named application."""
        if gw:
            try:
                windows = gw.getWindowsWithTitle(name)
                if windows:
                    windows[0].activate()
                    self._update_active_state(name, windows[0].title)
                    return f"Focused window: '{windows[0].title}'."
            except Exception:
                pass
        
        # Fallback to switch windows hotkey
        pyautogui.hotkey("alt", "tab")
        return f"Focused application '{name}'."

    def minimize(self) -> str:
        """Minimize currently focused window."""
        if gw:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.minimize()
                    return f"Minimized window '{active.title}'."
            except Exception:
                pass
        pyautogui.hotkey("win", "down")
        return "Window minimized."

    def maximize(self) -> str:
        """Maximize currently focused window."""
        if gw:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.maximize()
                    return f"Maximized window '{active.title}'."
            except Exception:
                pass
        pyautogui.hotkey("win", "up")
        return "Window maximized."

    def restore(self) -> str:
        """Restore currently focused window."""
        if gw:
            try:
                active = gw.getActiveWindow()
                if active:
                    active.restore()
                    return f"Restored window '{active.title}'."
            except Exception:
                pass
        pyautogui.hotkey("win", "down")
        return "Window restored."

    def switch_window(self) -> str:
        """Switch current workspace active window focus."""
        pyautogui.hotkey("alt", "tab")
        return "Switched windows."

    def list_running_apps(self) -> list[str]:
        """Expose list of running processes."""
        apps = set()
        for process in psutil.process_iter(["name"]):
            try:
                name = process.info.get("name")
                if name and name.endswith(".exe"):
                    apps.add(name.replace(".exe", ""))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(list(apps))

    def get_active_window(self) -> str:
        """Scan active window title."""
        if gw:
            try:
                active = gw.getActiveWindow()
                if active:
                    self.active_window_title = active.title
                    return active.title
            except Exception:
                pass
        return self.active_window_title or "Active Window"

    def get_state(self) -> dict[str, Any]:
        """Expose current state map to SharedContext."""
        return {
            "active_application": self.active_app,
            "active_app": self.active_app,
            "active_window": self.get_active_window(),
            "recently_opened_apps": self.recently_opened_apps
        }

    # ── Backward Compatibility Method Redirects ──────────────────────────────

    def open_application(self, name: str) -> str:
        return self.open_app(name)

    def open_folder(self, folder_name: str) -> str:
        folders = {
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "desktop": Path.home() / "Desktop",
            "pictures": Path.home() / "Pictures",
            "videos": Path.home() / "Videos",
            "music": Path.home() / "Music",
        }
        key = folder_name.lower().strip()
        if key == "file explorer":
            return self.open_app("file explorer")
        path = folders.get(key)
        if not path:
            return f"I do not know the folder {folder_name}."
        path.mkdir(parents=True, exist_ok=True)
        open_path(path)
        return f"{folder_name.title()} is open."

    def close_current_application(self) -> str:
        pyautogui.hotkey("alt", "f4")
        return "Closed the current application."

    def minimize_window(self) -> str:
        return self.minimize()

    def maximize_window(self) -> str:
        return self.maximize()

    def switch_windows(self) -> str:
        return self.switch_window()

    def restart_application(self, name: str) -> str:
        killed = self.close_app(name)
        opened = self.open_app(name)
        return f"{killed} {opened}"

    def kill_process(self, name: str) -> str:
        return self.close_app(name)

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _update_active_state(self, app_name: str, win_title: str) -> None:
        self.active_app = app_name
        self.active_window_title = win_title
        if app_name not in self.recently_opened_apps:
            self.recently_opened_apps.append(app_name)
            if len(self.recently_opened_apps) > 5:
                self.recently_opened_apps.pop(0)

    @staticmethod
    def _resolve_command(command: str | Path) -> str | Path | None:
        if isinstance(command, Path):
            return command if command.exists() else None
        found = shutil.which(command)
        return found or command

    @staticmethod
    def _open_uri(uri: str) -> None:
        if os.name == "nt":
            os.startfile(uri)  # type: ignore[attr-defined]
            return
        webbrowser.open(uri)

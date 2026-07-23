"""Input Agent V1: Responsible for desktop keyboard, mouse, and clipboard interactions."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any

import pyautogui
import pyperclip

from assistant.config import Settings
from assistant.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentResult:
    """Structured result returned by the Input Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class InputAgent:
    """Evolved Input Agent V1.

    Executes hardware-level simulation commands for mouse, keyboard, and clipboard operations.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)

        # ── Input Agent State ────────────────────────────────────────────────
        self.mouse_position: tuple[int, int] = (0, 0)
        self.last_clicked_position: tuple[int, int] | None = None
        self.last_typed_text: str = ""
        self.last_hotkey: str = ""
        self.last_keyboard_action: str = ""
        self.clipboard_status: str = "empty"

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Check if action is a supported input command."""
        supported = {
            "move_mouse", "click", "double_click", "right_click", "drag",
            "scroll", "type_text", "press_key", "release_key", "hotkey",
            "copy", "paste", "select_all", "get_mouse_position", "get_keyboard_state"
        }
        return task.action in supported

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}

        try:
            if action == "move_mouse":
                x = int(params.get("x", 0))
                y = int(params.get("y", 0))
                msg = self.move_mouse(x, y)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "click":
                x = params.get("x")
                y = params.get("y")
                msg = self.click(int(x) if x is not None else None, int(y) if y is not None else None)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "double_click":
                x = params.get("x")
                y = params.get("y")
                msg = self.double_click(int(x) if x is not None else None, int(y) if y is not None else None)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "right_click":
                x = params.get("x")
                y = params.get("y")
                msg = self.right_click(int(x) if x is not None else None, int(y) if y is not None else None)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "drag":
                x1 = int(params.get("x1", 0))
                y1 = int(params.get("y1", 0))
                x2 = int(params.get("x2", 0))
                y2 = int(params.get("y2", 0))
                msg = self.drag(x1, y1, x2, y2)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "scroll":
                amount = int(params.get("amount", -400))
                msg = self.scroll(amount)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "type_text":
                text = params.get("text", "")
                msg = self.type_text(text)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "press_key":
                key = params.get("key", "")
                msg = self.press_key(key)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "release_key":
                key = params.get("key", "")
                msg = self.release_key(key)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "hotkey":
                keys = params.get("keys", [])
                if isinstance(keys, str):
                    keys = [keys]
                msg = self.hotkey(keys)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "copy":
                text = params.get("text", "")
                msg = self.copy(text)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "paste":
                msg = self.paste()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "select_all":
                msg = self.select_all()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "get_mouse_position":
                pos = self.get_mouse_position()
                return AgentResult(
                    success=True,
                    message=f"Mouse position retrieved: {pos}.",
                    data={"x": pos[0], "y": pos[1]}
                )

            elif action == "get_keyboard_state":
                state = self.get_keyboard_state()
                return AgentResult(
                    success=True,
                    message="Keyboard state retrieved.",
                    data=state
                )

            else:
                return AgentResult(
                    success=False,
                    message=f"Unsupported action: {action}",
                    error="unsupported_action"
                )

        except ValueError as exc:
            return AgentResult(success=False, message=str(exc), error="invalid_coordinates")
        except KeyError as exc:
            return AgentResult(success=False, message=str(exc), error="unsupported_key")
        except ModuleNotFoundError as exc:
            self.logger.warning("Agent=InputAgent Action=%s Failure=missing_dependency: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            self.logger.warning("Agent=InputAgent Action=%s Failure=timeout: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            logger.exception("InputAgent task execution failure")
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        return self.get_state()

    def health(self) -> str:
        return "healthy"

    def reset(self) -> None:
        self.mouse_position = (0, 0)
        self.last_clicked_position = None
        self.last_typed_text = ""
        self.last_hotkey = ""
        self.last_keyboard_action = ""
        self.clipboard_status = "empty"

    # ── Input Agent APIs ─────────────────────────────────────────────────────

    def move_mouse(self, x: int, y: int) -> str:
        w, h = pyautogui.size()
        if x < 0 or x > w or y < 0 or y > h:
            raise ValueError(f"Coordinates ({x}, {y}) out of screen bounds ({w}x{h}).")
        
        pyautogui.moveTo(x, y, duration=0.25)
        self.mouse_position = (x, y)
        return f"Moved mouse to ({x}, {y})."

    def click(self, x: int | None = None, y: int | None = None) -> str:
        if x is not None and y is not None:
            self.move_mouse(x, y)
        pyautogui.click()
        pos = pyautogui.position()
        self.mouse_position = (pos.x, pos.y)
        self.last_clicked_position = self.mouse_position
        return f"Left clicked mouse at {self.mouse_position}."

    def double_click(self, x: int | None = None, y: int | None = None) -> str:
        if x is not None and y is not None:
            self.move_mouse(x, y)
        pyautogui.doubleClick()
        pos = pyautogui.position()
        self.mouse_position = (pos.x, pos.y)
        self.last_clicked_position = self.mouse_position
        return f"Double clicked mouse at {self.mouse_position}."

    def right_click(self, x: int | None = None, y: int | None = None) -> str:
        if x is not None and y is not None:
            self.move_mouse(x, y)
        pyautogui.rightClick()
        pos = pyautogui.position()
        self.mouse_position = (pos.x, pos.y)
        self.last_clicked_position = self.mouse_position
        return f"Right clicked mouse at {self.mouse_position}."

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> str:
        self.move_mouse(x1, y1)
        pyautogui.dragTo(x2, y2, duration=0.5)
        self.mouse_position = (x2, y2)
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})."

    def scroll(self, amount: int) -> str:
        pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return f"Scrolled page {direction}."

    def type_text(self, text: str) -> str:
        if not text:
            return "No text to type."
        pyautogui.write(text, interval=0.01)
        self.last_typed_text = text
        return f"Typed text: '{text}'."

    def press_key(self, key: str) -> str:
        try:
            pyautogui.keyDown(key)
        except ValueError:
            raise KeyError(f"Unsupported key: {key}")
        self.last_keyboard_action = f"press:{key}"
        return f"Pressed key down: {key}."

    def release_key(self, key: str) -> str:
        try:
            pyautogui.keyUp(key)
        except ValueError:
            raise KeyError(f"Unsupported key: {key}")
        self.last_keyboard_action = f"release:{key}"
        return f"Released key up: {key}."

    def hotkey(self, keys: list[str]) -> str:
        if not keys:
            return "No hotkey combination provided."
        pyautogui.hotkey(*keys)
        self.last_hotkey = "+".join(keys)
        self.last_keyboard_action = f"hotkey:{self.last_hotkey}"
        return f"Executed hotkey: {self.last_hotkey}."

    def copy(self, text: str) -> str:
        if not text:
            return "No text to copy."
        pyperclip.copy(text)
        self.clipboard_status = "has_text"
        return "Copied text to clipboard."

    def paste(self) -> str:
        pyautogui.hotkey("ctrl", "v")
        return "Pasted clipboard content."

    def select_all(self) -> str:
        pyautogui.hotkey("ctrl", "a")
        return "Selected all text."

    def get_mouse_position(self) -> tuple[int, int]:
        pos = pyautogui.position()
        self.mouse_position = (pos.x, pos.y)
        return self.mouse_position

    def get_keyboard_state(self) -> dict[str, Any]:
        return {
            "num_lock": False,
            "caps_lock": False,
            "scroll_lock": False
        }

    def get_state(self) -> dict[str, Any]:
        """Expose current state variables to SharedContext."""
        return {
            "last_mouse_position": self.get_mouse_position(),
            "mouse_position": self.get_mouse_position(),
            "last_clicked_position": self.last_clicked_position,
            "last_typed_text": self.last_typed_text,
            "last_hotkey": self.last_hotkey,
            "last_keyboard_action": self.last_keyboard_action,
            "clipboard_status": self.clipboard_status
        }

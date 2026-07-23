"""File Agent V1: Responsible for file, directory, and search operations."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from assistant.config import Settings
from assistant.utils.helpers import resolve_user_path, clean_filename, open_path
from assistant.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentResult:
    """Structured result returned by the File Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class FileAgent:
    """Evolved File Agent V1.

    Executes operations on the filesystem including creating, reading, writing, moving,
    renaming, and deleting files/directories, conforming to AgentInterface.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.workspace_dir = settings.user_workspace_dir.expanduser()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # ── File Agent State ─────────────────────────────────────────────────
        self.current_directory: str = str(self.workspace_dir)
        self.current_file: str = ""
        self.recent_files: list[str] = []
        self.recent_folders: list[str] = []

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Verify action is a supported file agent command."""
        supported = {
            "create_file", "create_folder", "open_file", "read_file",
            "write_file", "append_file", "rename", "move", "copy",
            "delete", "list_directory", "search", "file_info"
        }
        return task.action in supported

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}
        path = params.get("path", "")

        try:
            if action == "create_file":
                content = params.get("content", "")
                msg = self.create_file(path, content)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "create_folder":
                msg = self.create_folder(path)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "open_file":
                msg = self.open_file(path)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "read_file":
                content = self.read_file(path)
                return AgentResult(
                    success=True,
                    message=f"Successfully read file content from {path}.",
                    data={"content": content}
                )

            elif action == "write_file":
                content = params.get("content", "")
                msg = self.write_file(path, content)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "append_file":
                content = params.get("content", "")
                msg = self.append_file(path, content)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "rename":
                new_path = params.get("new_path", "")
                msg = self.rename(path, new_path)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "move":
                dest = params.get("destination", "")
                msg = self.move(path, dest)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "copy":
                dest = params.get("destination", "")
                msg = self.copy(path, dest)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "delete":
                msg = self.delete(path)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "list_directory":
                items = self.list_directory(path)
                return AgentResult(
                    success=True,
                    message=f"Found {len(items)} items in folder.",
                    data={"items": items}
                )

            elif action == "search":
                query = params.get("query", "")
                results = self.search(query)
                return AgentResult(
                    success=True,
                    message=f"Found {len(results)} files matching query '{query}'.",
                    data={"results": results}
                )

            elif action == "file_info":
                info = self.file_info(path)
                return AgentResult(
                    success=True,
                    message=f"File info retrieved successfully for '{path}'.",
                    data={"info": info}
                )

            else:
                return AgentResult(
                    success=False,
                    message=f"Unsupported action: {action}",
                    error="unsupported_action"
                )

        except FileNotFoundError as exc:
            return AgentResult(success=False, message=str(exc), error="file_not_found")
        except PermissionError as exc:
            return AgentResult(success=False, message=str(exc), error="permission_denied")
        except FileExistsError as exc:
            return AgentResult(success=False, message=str(exc), error="already_exists")
        except ModuleNotFoundError as exc:
            self.logger.warning("Agent=FileAgent Action=%s Failure=missing_dependency: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            self.logger.warning("Agent=FileAgent Action=%s Failure=timeout: %s", action, exc)
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            logger.exception("FileAgent task execution failed")
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        return self.get_state()

    def health(self) -> str:
        return "healthy"

    def reset(self) -> None:
        self.current_directory = str(self.workspace_dir)
        self.current_file = ""
        self.recent_files = []
        self.recent_folders = []

    # ── File Agent APIs ──────────────────────────────────────────────────────

    def create_file(self, path_str: str, content: str = "") -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if path.exists():
            raise FileExistsError(f"File already exists at: {path}")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._update_file_state(path)
        return f"File created at {path}."

    def create_folder(self, path_str: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if path.exists():
            raise FileExistsError(f"Folder already exists at: {path}")
        
        path.mkdir(parents=True, exist_ok=True)
        self._update_folder_state(path)
        return f"Folder created at {path}."

    def open_file(self, path_str: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        open_path(path)
        self._update_file_state(path)
        return f"Opened file {path.name}."

    def read_file(self, path_str: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        content = path.read_text(encoding="utf-8")
        self._update_file_state(path)
        return content

    def write_file(self, path_str: str, content: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._update_file_state(path)
        return f"Wrote content to {path}."

    def append_file(self, path_str: str, content: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        self._update_file_state(path)
        return f"Appended content to {path}."

    def rename(self, path_str: str, new_path_str: str) -> str:
        old_path = resolve_user_path(path_str, self.workspace_dir)
        if not old_path.exists():
            raise FileNotFoundError(f"File not found: {old_path}")
        
        new_name = clean_filename(new_path_str, old_path.name)
        new_path = old_path.with_name(new_name)
        old_path.rename(new_path)
        
        if old_path.is_dir():
            self._update_folder_state(new_path)
        else:
            self._update_file_state(new_path)
        return f"Renamed {old_path.name} to {new_path.name}."

    def move(self, source_str: str, destination_str: str) -> str:
        source = resolve_user_path(source_str, self.workspace_dir)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        
        destination = resolve_user_path(destination_str, self.workspace_dir)
        if destination.suffix == "" or destination_str.endswith(("/", "\\")):
            destination = destination / source.name
            
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        
        if destination.is_dir():
            self._update_folder_state(destination)
        else:
            self._update_file_state(destination)
        return f"Moved {source.name} to {destination}."

    def copy(self, source_str: str, destination_str: str) -> str:
        source = resolve_user_path(source_str, self.workspace_dir)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        
        destination = resolve_user_path(destination_str, self.workspace_dir)
        if destination.suffix == "" or destination_str.endswith(("/", "\\")):
            destination = destination / source.name
            
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(str(source), str(destination))
            self._update_folder_state(destination)
        else:
            shutil.copy2(str(source), str(destination))
            self._update_file_state(destination)
        return f"Copied {source.name} to {destination}."

    def delete(self, path_str: str) -> str:
        path = resolve_user_path(path_str, self.workspace_dir)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
            
        if self.current_file == str(path):
            self.current_file = ""
        return f"Deleted {path.name}."

    def list_directory(self, path_str: str = "") -> list[str]:
        path = resolve_user_path(path_str, self.workspace_dir) if path_str else self.workspace_dir
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        self._update_folder_state(path)
        return [str(item.name) for item in path.iterdir()]

    def search(self, query: str) -> list[str]:
        normalized = query.lower().strip()
        if not normalized:
            return []

        matches = []
        excluded = {".git", ".venv", "node_modules", "__pycache__"}
        for current_root, dirs, files in os.walk(self.workspace_dir):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
            for filename in files:
                if normalized in filename.lower():
                    matches.append(str(Path(current_root) / filename))
                    if len(matches) >= 10:
                        break
            if len(matches) >= 10:
                break
        return matches

    def file_info(self, path_str: str) -> dict[str, Any]:
        path = resolve_user_path(path_str, self.workspace_dir)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        stat = path.stat()
        return {
            "name": path.name,
            "absolute_path": str(path.resolve()),
            "size_bytes": stat.st_size,
            "is_directory": path.is_dir(),
            "modified_time": stat.st_mtime,
            "created_time": stat.st_ctime
        }

    def get_state(self) -> dict[str, Any]:
        """Expose current state to SharedContext."""
        return {
            "current_directory": self.current_directory,
            "current_file": self.current_file,
            "recent_files": self.recent_files,
            "recent_folders": self.recent_folders
        }

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _update_file_state(self, path: Path) -> None:
        self.current_file = str(path)
        path_str = str(path)
        if path_str not in self.recent_files:
            self.recent_files.append(path_str)
            if len(self.recent_files) > 5:
                self.recent_files.pop(0)
        self._update_folder_state(path.parent)

    def _update_folder_state(self, path: Path) -> None:
        self.current_directory = str(path)
        path_str = str(path)
        if path_str not in self.recent_folders:
            self.recent_folders.append(path_str)
            if len(self.recent_folders) > 5:
                self.recent_folders.pop(0)

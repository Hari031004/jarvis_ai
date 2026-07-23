"""System, productivity, file, clipboard, registry, and environment control."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import psutil
import pyautogui
import pyperclip
from send2trash import send2trash

from assistant.config import Settings
from assistant.security import PermissionManager
from assistant.utils.helpers import clean_filename, open_path, resolve_user_path, run_process, sentence_join, truncate_for_speech
from assistant.utils.logger import get_logger


class SystemController:
    """Controls Windows system features and productivity actions."""

    def __init__(self, settings: Settings, permissions: PermissionManager | None = None) -> None:
        self.settings = settings
        self.permissions = permissions
        self.logger = get_logger(__name__)
        self.clipboard_history: list[str] = []
        self.settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.settings.user_workspace_dir.mkdir(parents=True, exist_ok=True)
        self.settings.notes_dir.mkdir(parents=True, exist_ok=True)

    def increase_volume(self) -> str:
        pyautogui.press("volumeup", presses=5, interval=0.04)
        return "Volume increased."

    def decrease_volume(self) -> str:
        pyautogui.press("volumedown", presses=5, interval=0.04)
        return "Volume decreased."

    def mute(self) -> str:
        pyautogui.press("volumemute")
        return "Audio muted."

    def unmute(self) -> str:
        pyautogui.press("volumeup")
        return "Audio unmuted."

    def brightness_up(self) -> str:
        return self._adjust_brightness(10)

    def brightness_down(self) -> str:
        return self._adjust_brightness(-10)

    def take_screenshot(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.settings.screenshots_dir / f"screenshot_{timestamp}.png"
        image = pyautogui.screenshot()
        image.save(path)
        return f"Screenshot saved to {path}."

    def lock_pc(self) -> str:
        if os.name != "nt":
            return "Lock PC is only supported on Windows."
        run_process(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "PC locked."

    def sleep_pc(self) -> str:
        allowed = self._allowed("power")
        if not allowed:
            return "Power commands are disabled. Set ENABLE_POWER_COMMANDS=true to allow sleep."
        run_process(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Putting the PC to sleep."

    def restart_pc(self) -> str:
        allowed = self._allowed("destructive_system")
        if not allowed:
            return "Restart is disabled. Set ENABLE_DESTRUCTIVE_SYSTEM_COMMANDS=true to allow it."
        run_process(["shutdown.exe", "/r", "/t", "5", "/c", "Restart requested by JARVIS."])
        return "Restarting the PC in five seconds."

    def shutdown_pc(self) -> str:
        allowed = self._allowed("destructive_system")
        if not allowed:
            return "Shutdown is disabled. Set ENABLE_DESTRUCTIVE_SYSTEM_COMMANDS=true to allow it."
        run_process(["shutdown.exe", "/s", "/t", "5", "/c", "Shutdown requested by JARVIS."])
        return "Shutting down the PC in five seconds."

    def empty_recycle_bin(self) -> str:
        allowed = self._allowed("destructive_system")
        if not allowed:
            return "Empty Recycle Bin is disabled. Set ENABLE_DESTRUCTIVE_SYSTEM_COMMANDS=true to allow it."
        result = run_process(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"])
        if result.returncode != 0:
            return f"I could not empty the Recycle Bin: {result.stderr.strip()}"
        return "Recycle Bin emptied."

    def show_battery(self) -> str:
        battery = psutil.sensors_battery()
        if battery is None:
            return "Battery information is not available on this device."
        plugged = "plugged in" if battery.power_plugged else "on battery"
        return f"Battery is at {battery.percent:.0f} percent and {plugged}."

    def show_cpu_usage(self) -> str:
        usage = psutil.cpu_percent(interval=1)
        return f"CPU usage is {usage:.0f} percent."

    def show_ram_usage(self) -> str:
        memory = psutil.virtual_memory()
        return f"RAM usage is {memory.percent:.0f} percent. {memory.available / (1024**3):.1f} gigabytes are available."

    def show_disk_usage(self) -> str:
        disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
        return f"Disk usage is {disk.percent:.0f} percent. {disk.free / (1024**3):.1f} gigabytes are free."

    def create_folder(self, raw_name: str) -> str:
        path = resolve_user_path(raw_name, self.settings.user_workspace_dir)
        decision = self._path_decision("filesystem_write", str(path))
        if not decision:
            return f"I cannot create that folder: {decision.reason}"
        path.mkdir(parents=True, exist_ok=True)
        return f"Folder created at {path}."

    def create_file(self, raw_name: str) -> str:
        path = resolve_user_path(raw_name, self.settings.user_workspace_dir)
        decision = self._path_decision("filesystem_write", str(path))
        if not decision:
            return f"I cannot create that file: {decision.reason}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return f"File created at {path}."

    def rename_file(self, old_raw: str, new_raw: str) -> str:
        old_path = self._find_file(old_raw)
        if old_path is None:
            return f"I could not find {old_raw}."
        decision = self._path_decision("filesystem_write", str(old_path))
        if not decision:
            return f"I cannot rename that file: {decision.reason}"
        new_name = clean_filename(new_raw, old_path.name)
        new_path = old_path.with_name(new_name)
        old_path.rename(new_path)
        return f"Renamed {old_path.name} to {new_path.name}."

    def move_file(self, raw_name: str, destination_raw: str) -> str:
        source = self._find_file(raw_name)
        if source is None:
            return f"I could not find {raw_name}."
        destination = resolve_user_path(destination_raw, self.settings.user_workspace_dir)
        if destination.suffix == "" or destination_raw.endswith(("/", "\\")):
            destination = destination / source.name
        source_decision = self._path_decision("filesystem_write", str(source))
        dest_decision = self._path_decision("filesystem_write", str(destination))
        if not source_decision:
            return f"I cannot move that file: {source_decision.reason}"
        if not dest_decision:
            return f"I cannot move the file there: {dest_decision.reason}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return f"Moved {source.name} to {destination}."

    def delete_file(self, raw_name: str) -> str:
        if not self._allowed("file_delete"):
            return "File deletion is disabled. Set ENABLE_FILE_DELETE=true to allow it."
        path = self._find_file(raw_name)
        if path is None:
            return f"I could not find {raw_name}."
        decision = self._path_decision("filesystem_write", str(path))
        if not decision:
            return f"I cannot delete that file: {decision.reason}"
        send2trash(str(path))
        return f"Moved {path.name} to the Recycle Bin."

    def search_files(self, query: str, max_results: int = 8) -> str:
        normalized = query.lower().strip()
        if not normalized:
            return "Tell me what file to search for."

        matches: list[Path] = []
        excluded = {".git", ".venv", "node_modules", "__pycache__", "AppData", "Windows", "Program Files", "Program Files (x86)"}
        root = self.settings.search_root_dir
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
            for filename in files:
                if normalized in filename.lower():
                    matches.append(Path(current_root) / filename)
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"I did not find files matching {query}."
        names = [str(path) for path in matches]
        return "I found " + sentence_join(names, limit=max_results) + "."

    def windows_search(self, query: str) -> str:
        if not query.strip():
            return "Tell me what to search for."
        pyautogui.hotkey("win", "s")
        pyperclip.copy(query.strip())
        pyautogui.hotkey("ctrl", "v")
        return f"Searching Windows for {query}."

    def open_recent_files(self) -> str:
        recent = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft/Windows/Recent"
        if not recent.exists():
            return "Recent files folder is not available."
        open_path(recent)
        return "Recent files are open."

    def read_clipboard(self) -> str:
        text = pyperclip.paste()
        if text and (not self.clipboard_history or self.clipboard_history[-1] != text):
            self.clipboard_history.append(text)
            self.clipboard_history = self.clipboard_history[-25:]
        if not text:
            return "The clipboard is empty."
        return "Clipboard contains: " + truncate_for_speech(text)

    def copy_text(self, text: str) -> str:
        if not text.strip():
            return "Tell me what text to copy."
        pyperclip.copy(text.strip())
        self.clipboard_history.append(text.strip())
        self.clipboard_history = self.clipboard_history[-25:]
        return "Copied to clipboard."

    def paste_text(self) -> str:
        pyautogui.hotkey("ctrl", "v")
        return "Pasted the clipboard text."

    def clipboard_manager(self) -> str:
        if not self.clipboard_history:
            self.read_clipboard()
        if not self.clipboard_history:
            return "Clipboard history is empty."
        snippets = [truncate_for_speech(item, 80) for item in self.clipboard_history[-5:]]
        return "Recent clipboard entries: " + sentence_join(snippets, limit=5) + "."

    def read_registry(self, hive_name: str, subkey: str, value_name: str = "") -> str:
        if os.name != "nt":
            return "Registry reading is only supported on Windows."
        try:
            import winreg

            hives = {
                "hkcu": winreg.HKEY_CURRENT_USER,
                "hkey_current_user": winreg.HKEY_CURRENT_USER,
                "hklm": winreg.HKEY_LOCAL_MACHINE,
                "hkey_local_machine": winreg.HKEY_LOCAL_MACHINE,
            }
            hive = hives.get(hive_name.lower())
            if hive is None:
                return "I support HKCU and HKLM registry reads."
            with winreg.OpenKey(hive, subkey) as key:
                if value_name:
                    value, value_type = winreg.QueryValueEx(key, value_name)
                else:
                    value = winreg.QueryValue(key, "")
                    value_type = "default"
            return f"Registry value is {value} of type {value_type}."
        except Exception as exc:
            return f"I could not read that registry value: {exc}"

    def get_environment_variable(self, name: str) -> str:
        if not name.strip():
            return "Tell me the environment variable name."
        value = os.getenv(name.strip())
        return f"{name} is {value}." if value is not None else f"{name} is not set."

    def set_environment_variable(self, name: str, value: str) -> str:
        if not name.strip():
            return "Tell me the environment variable name."
        os.environ[name.strip()] = value
        if os.name == "nt":
            run_process(["setx", name.strip(), value])
        return f"Environment variable {name.strip()} is set."

    def _adjust_brightness(self, delta: int) -> str:
        current = self._get_brightness()
        if current is None:
            return "Brightness control is not available for this display."
        target = max(0, min(100, current + delta))
        command = f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1,{target})"
        result = run_process(["powershell", "-NoProfile", "-Command", command])
        if result.returncode != 0:
            return "Brightness control is not available for this display."
        return f"Brightness set to {target} percent."

    def _get_brightness(self) -> int | None:
        command = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"
        try:
            result = run_process(["powershell", "-NoProfile", "-Command", command])
            if result.returncode != 0:
                return None
            match = re.search(r"\d+", result.stdout)
            return int(match.group(0)) if match else None
        except Exception:
            return None

    def _find_file(self, raw_name: str) -> Path | None:
        candidate = resolve_user_path(raw_name, self.settings.user_workspace_dir)
        if candidate.exists():
            return candidate

        filename = clean_filename(raw_name, "")
        if not filename:
            return None
        for root in [self.settings.user_workspace_dir, Path.home() / "Downloads", Path.home() / "Desktop", self.settings.notes_dir]:
            if not root.exists():
                continue
            direct = root / filename
            if direct.exists():
                return direct
            try:
                for path in root.rglob("*"):
                    if path.name.lower() == filename.lower():
                        return path
            except OSError:
                continue
        return None

    def _allowed(self, permission: str) -> bool:
        if self.permissions is None:
            if permission == "power":
                return self.settings.enable_power_commands
            if permission == "destructive_system":
                return self.settings.enable_destructive_system_commands
            if permission == "file_delete":
                return self.settings.enable_file_delete
            return True
        return self.permissions.check(permission).allowed

    def _path_decision(self, permission: str, target: str):  # type: ignore[no-untyped-def]
        if self.permissions is None:
            class Decision:
                allowed = True
                reason = ""

                def __bool__(self) -> bool:
                    return self.allowed

            return Decision()
        return self.permissions.check(permission, target)


"""Timers, reminders, notes, to-dos, calendar, and online information commands."""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import threading
import uuid
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pyautogui
import requests

from assistant.browser.controller import BrowserController
from assistant.config import Settings
from assistant.memory.database import SQLiteStore, utc_now
from assistant.utils.helpers import human_timedelta, normalize_text, parse_alarm_time, parse_duration, run_process, truncate_for_speech
from assistant.utils.logger import get_logger


@dataclass(slots=True)
class ScheduledTask:
    id: str
    label: str
    due_at: datetime
    timer: threading.Timer


@dataclass(slots=True)
class LocalCommand:
    intent: str
    execute: Callable[[], str]
    confirmation_prompt: str | None = None


def local_command(*phrases: str, intent: str | None = None, confirmation_prompt: str | None = None):  # type: ignore[no-untyped-def]
    def decorate(func):  # type: ignore[no-untyped-def]
        func._automation_phrases = phrases
        func._automation_intent = intent or func.__name__
        func._automation_confirmation_prompt = confirmation_prompt
        return func

    return decorate


class AutomationManager:
    """Handles reminders, timers, alarms, notes, tasks, and lightweight online information."""

    def __init__(
        self,
        settings: Settings,
        browser: BrowserController,
        speaker: Callable[[str], None],
        store: SQLiteStore | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser
        self.speaker = speaker
        self.store = store
        self.logger = get_logger(__name__)
        self.tasks: dict[str, ScheduledTask] = {}
        self.todo_items: list[str] = []
        self.command_registry = self._build_command_registry()
        self._pending_confirmation: LocalCommand | None = None
        self.settings.notes_dir.mkdir(parents=True, exist_ok=True)

    def has_pending_confirmation(self) -> bool:
        return self._pending_confirmation is not None

    def execute_local_command(self, normalized: str) -> str | None:
        if normalized in {"confirm", "yes", "yes confirm", "confirm action", "do it", "proceed"}:
            return self._execute_pending_confirmation()
        if normalized in {"cancel", "cancel action", "no", "never mind", "nevermind"}:
            return self._cancel_pending_confirmation()

        command = self.command_registry.get(normalized)
        if command is None:
            return None

        self.logger.info("Intent detected:\n%s", command.intent)
        if command.confirmation_prompt:
            self._pending_confirmation = command
            return command.confirmation_prompt
        return self._execute_command(command)

    @local_command("open notepad", intent="open_notepad")
    def open_notepad(self) -> str:
        subprocess.Popen(["notepad.exe"])
        return "Notepad is open."

    @local_command("open calculator", "open calc", intent="open_calculator")
    def open_calculator(self) -> str:
        subprocess.Popen(["calc.exe"])
        return "Calculator is open."

    @local_command("open paint", "open ms paint", intent="open_paint")
    def open_paint(self) -> str:
        subprocess.Popen(["mspaint.exe"])
        return "Paint is open."

    @local_command("open vs code", "open visual studio code", intent="open_vscode")
    def open_vscode(self) -> str:
        command = self._first_existing_command(
            [
                shutil.which("code.cmd"),
                shutil.which("code.exe"),
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
                Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "Code.exe",
            ]
        )
        subprocess.Popen([str(command or "code.exe")])
        return "VS Code is open."

    @local_command("open chrome", intent="open_chrome")
    def open_chrome(self) -> str:
        chrome_path = self._find_chrome_exe()
        command = [str(chrome_path)] if chrome_path else ["chrome.exe"]
        subprocess.Popen(command)
        return "Chrome is open."

    @local_command("open file explorer", "open explorer", intent="open_file_explorer")
    def open_file_explorer(self) -> str:
        subprocess.Popen(["explorer.exe"])
        return "File Explorer is open."

    @local_command("open task manager", intent="open_task_manager")
    def open_task_manager(self) -> str:
        subprocess.Popen(["taskmgr.exe"])
        return "Task Manager is open."

    @local_command("open control panel", intent="open_control_panel")
    def open_control_panel(self) -> str:
        subprocess.Popen(["control.exe"])
        return "Control Panel is open."

    @local_command("open downloads", "open downloads folder", intent="open_downloads")
    def open_downloads(self) -> str:
        self._open_folder(Path.home() / "Downloads")
        return "Downloads folder is open."

    @local_command("open documents", "open documents folder", intent="open_documents")
    def open_documents(self) -> str:
        self._open_folder(Path.home() / "Documents")
        return "Documents folder is open."

    @local_command("lock pc", "lock computer", "lock my pc", intent="lock_pc")
    def lock_pc(self) -> str:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        return "PC locked."

    @local_command(
        "shutdown",
        "shutdown pc",
        "shut down pc",
        "shutdown computer",
        "shut down computer",
        intent="shutdown_pc",
        confirmation_prompt="Shutdown requires confirmation. Say confirm to shut down.",
    )
    def shutdown_pc(self) -> str:
        subprocess.Popen(["shutdown.exe", "/s", "/t", "5", "/c", "Shutdown requested by JARVIS."])
        return "Shutting down the PC in five seconds."

    @local_command(
        "restart",
        "restart pc",
        "restart computer",
        "reboot",
        "reboot pc",
        intent="restart_pc",
        confirmation_prompt="Restart requires confirmation. Say confirm to restart.",
    )
    def restart_pc(self) -> str:
        subprocess.Popen(["shutdown.exe", "/r", "/t", "5", "/c", "Restart requested by JARVIS."])
        return "Restarting the PC in five seconds."

    @local_command(
        "empty recycle bin",
        "clear recycle bin",
        intent="empty_recycle_bin",
        confirmation_prompt="Emptying the Recycle Bin requires confirmation. Say confirm to empty it.",
    )
    def empty_recycle_bin(self) -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Clear-RecycleBin failed.")
        return "Recycle Bin emptied."

    @local_command("open youtube", "youtube", intent="open_youtube")
    def open_youtube(self) -> str:
        return self.open_url("https://youtube.com")

    @local_command("open google", "google", intent="open_google")
    def open_google(self) -> str:
        return self.open_url("https://google.com")

    @local_command("open gmail", "gmail", intent="open_gmail")
    def open_gmail(self) -> str:
        return self.open_url("https://mail.google.com")

    @local_command("open github", "github", intent="open_github")
    def open_github(self) -> str:
        return self.open_url("https://github.com")

    @local_command("open chatgpt", "open chat gpt", "chatgpt", "chat gpt", intent="open_chatgpt")
    def open_chatgpt(self) -> str:
        return self.open_url("https://chatgpt.com")

    @local_command("open linkedin", "linkedin", "linked in", "open linked in", intent="open_linkedin")
    def open_linkedin(self) -> str:
        return self.open_url("https://www.linkedin.com")

    def open_url(self, url: str) -> str:
        self.logger.info("Browser navigation: assistant/automation/manager.py:open_url request_id: N/A destination URL: %s", url)
        webbrowser.open(url)
        return f"Opened {url}."

    def set_timer(self, text: str) -> str:
        duration = parse_duration(text)
        if duration is None:
            return "Tell me a timer duration, for example five minutes."
        label = f"Timer for {human_timedelta(duration)}"
        self._schedule(label, datetime.now() + duration, f"{label} is complete.", "timer")
        return f"Timer set for {human_timedelta(duration)}."

    def set_reminder(self, text: str) -> str:
        duration = parse_duration(text)
        if duration is None:
            return "Tell me when to remind you, for example in ten minutes."
        reminder_text = self._extract_reminder_text(text)
        due_at = datetime.now() + duration
        spoken = f"Reminder: {reminder_text}" if reminder_text else "This is your reminder."
        self._schedule(spoken, due_at, spoken, "reminder")
        return f"Reminder set for {human_timedelta(duration)} from now."

    def set_alarm(self, text: str) -> str:
        due_at = parse_alarm_time(text)
        if due_at is None:
            return "Tell me a time for the alarm, for example seven thirty AM."
        self._schedule("Alarm", due_at, "Alarm.", "alarm")
        return f"Alarm set for {due_at.strftime('%I:%M %p')}."

    def add_todo(self, text: str) -> str:
        item = re.sub(r"^(add|create)\s+(a\s+)?(todo|to do)\s*", "", text, flags=re.IGNORECASE).strip()
        if not item:
            return "Tell me the to-do item."
        self.todo_items.append(item)
        self._record_task("todo", item, "open")
        return f"Added to your to-do list: {item}."

    def list_todos(self) -> str:
        if not self.todo_items:
            rows = self.store.query("SELECT content FROM task_history WHERE task_type = 'todo' AND status = 'open' ORDER BY id DESC LIMIT 10") if self.store else []
            self.todo_items = [str(row["content"]) for row in rows]
        if not self.todo_items:
            return "Your to-do list is empty."
        return "Your to-do items are: " + "; ".join(self.todo_items[-10:]) + "."

    def create_note(self, text: str, title: str = "voice_note") -> str:
        content = re.sub(r"^(create|take|write)\s+(a\s+)?(note|voice note)\s*", "", text, flags=re.IGNORECASE).strip()
        if not content:
            return "Tell me the note content."
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_") or "voice_note"
        path = self.settings.notes_dir / f"{safe_title}_{timestamp}.md"
        path.write_text(f"# {safe_title.replace('_', ' ').title()}\n\n{content}\n", encoding="utf-8")
        return f"Note saved to {path}."

    def meeting_summary_note(self, text: str) -> str:
        return self.create_note(text, title="meeting_note")

    def create_scheduled_task(self, name: str, command: str, time_text: str) -> str:
        due_at = parse_alarm_time(time_text)
        if due_at is None:
            return "Tell me a valid time for the scheduled task."
        if not command.strip():
            return "Tell me the command to schedule."
        task_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "JarvisTask"
        result = run_process(
            [
                "schtasks",
                "/Create",
                "/SC",
                "ONCE",
                "/TN",
                task_name,
                "/TR",
                command,
                "/ST",
                due_at.strftime("%H:%M"),
                "/F",
            ]
        )
        if result.returncode != 0:
            return f"I could not create the scheduled task: {result.stderr.strip()}"
        self._record_task("scheduled_task", f"{task_name}: {command}", "scheduled", due_at)
        return f"Scheduled task {task_name} for {due_at.strftime('%I:%M %p')}."

    def read_calendar(self) -> str:
        try:
            import win32com.client

            outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            calendar = outlook.GetDefaultFolder(9)
            items = calendar.Items
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            start = datetime.now()
            end = start + timedelta(days=7)
            restriction = (
                "[Start] >= '"
                + start.strftime("%m/%d/%Y %I:%M %p")
                + "' AND [Start] <= '"
                + end.strftime("%m/%d/%Y %I:%M %p")
                + "'"
            )
            appointments = items.Restrict(restriction)
            summaries: list[str] = []
            for item in appointments:
                when = item.Start.strftime("%A at %I:%M %p")
                summaries.append(f"{item.Subject} on {when}")
                if len(summaries) >= 5:
                    break
            if not summaries:
                return "You have no Outlook calendar events in the next seven days."
            return "Your next calendar items are: " + "; ".join(summaries) + "."
        except Exception as exc:
            self.logger.debug("Outlook calendar read failed: %s", exc)
            return "I could not read Outlook calendar items. Make sure Outlook is installed and configured."

    def open_outlook(self) -> str:
        try:
            import subprocess

            subprocess.Popen(["outlook.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Outlook is open."
        except Exception:
            self.browser.open_site("gmail")
            return "I could not open Outlook directly, so I opened Gmail."

    def read_notifications(self) -> str:
        pyautogui.hotkey("win", "n")
        return "Notification Center is open. Windows notification history text is not exposed to normal desktop apps without a dedicated listener."

    def weather(self, text: str) -> str:
        location = self._extract_after(text, ["weather in", "weather for", "forecast in", "forecast for"])
        if not location:
            location = self.settings.weather_location
        url = f"https://wttr.in/{requests.utils.quote(location)}"
        response = requests.get(url, params={"format": "j1"}, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        current = data["current_condition"][0]
        condition = current["weatherDesc"][0]["value"]
        temp_c = current["temp_C"]
        feels_c = current["FeelsLikeC"]
        humidity = current["humidity"]
        return f"Weather in {location}: {condition}, {temp_c} degrees Celsius, feels like {feels_c}, humidity {humidity} percent."

    def news(self) -> str:
        region = self.settings.news_region.upper()
        url = f"https://news.google.com/rss?hl=en-{region}&gl={region}&ceid={region}:en"
        response = requests.get(url, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        titles = [item.findtext("title", "") for item in root.findall(".//item")[:5]]
        titles = [title for title in titles if title]
        if not titles:
            return "I could not find current news headlines."
        return "Top headlines: " + "; ".join(truncate_for_speech(title, 140) for title in titles) + "."

    def currency(self, text: str) -> str:
        normalized = normalize_text(text).upper()
        match = re.search(r"(?:(\d+(?:\.\d+)?)\s*)?([A-Z]{3})\s+(?:TO|IN)\s+([A-Z]{3})", normalized)
        if not match:
            return "Tell me the currency pair, for example convert 100 USD to INR."
        amount = float(match.group(1) or 1)
        base = match.group(2)
        quote = match.group(3)
        response = requests.get("https://api.frankfurter.app/latest", params={"amount": amount, "from": base, "to": quote}, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        value = data["rates"][quote]
        return f"{amount:g} {base} is {value:g} {quote}."

    def stock_price(self, text: str) -> str:
        symbol = self._extract_symbol(text, ["stock price", "price of stock", "show stock price"])
        if not symbol:
            return "Tell me the stock symbol, for example stock price MSFT."
        stooq_symbol = symbol.lower()
        if "." not in stooq_symbol:
            stooq_symbol += ".us"
        response = requests.get("https://stooq.com/q/l/", params={"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        row = next(reader, None)
        if not row or row.get("Close") in {None, "N/D"}:
            return f"I could not find a stock price for {symbol}."
        return f"{symbol.upper()} last traded at {row['Close']}."

    def crypto_price(self, text: str) -> str:
        asset = self._extract_symbol(text, ["crypto price", "price of crypto", "bitcoin price", "ethereum price"])
        normalized = normalize_text(text)
        if "bitcoin price" in normalized:
            asset = "bitcoin"
        elif "ethereum price" in normalized:
            asset = "ethereum"
        if not asset:
            return "Tell me the crypto asset, for example Bitcoin price."

        coin_id = self._resolve_coin_id(asset)
        response = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": coin_id, "vs_currencies": "usd"}, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        price = data.get(coin_id, {}).get("usd")
        if price is None:
            return f"I could not find a crypto price for {asset}."
        return f"{asset.title()} is trading at {price:g} US dollars."

    def _build_command_registry(self) -> dict[str, LocalCommand]:
        registry: dict[str, LocalCommand] = {}
        for attribute_name in dir(self):
            method = getattr(self, attribute_name)
            phrases = getattr(method, "_automation_phrases", None)
            if not phrases:
                continue
            intent = str(getattr(method, "_automation_intent", attribute_name))
            confirmation_prompt = getattr(method, "_automation_confirmation_prompt", None)
            command = LocalCommand(intent=intent, execute=method, confirmation_prompt=confirmation_prompt)
            for phrase in phrases:
                registry[normalize_text(phrase)] = command
        return registry

    def _execute_command(self, command: LocalCommand) -> str:
        self.logger.info("Executing:\n%s", command.intent)
        try:
            result = command.execute()
            self.logger.info("Success:\n%s", command.intent)
            return result
        except Exception as exc:
            print(exc)
            self.logger.exception("Failed:\n%s", command.intent)
            return f"I could not execute {command.intent.replace('_', ' ')}: {exc}"

    def _execute_pending_confirmation(self) -> str | None:
        if self._pending_confirmation is None:
            return None
        command = self._pending_confirmation
        self._pending_confirmation = None
        self.logger.info("Intent detected:\n%s", command.intent)
        return self._execute_command(command)

    def _cancel_pending_confirmation(self) -> str | None:
        if self._pending_confirmation is None:
            return None
        intent = self._pending_confirmation.intent
        self._pending_confirmation = None
        self.logger.info("Failed:\n%s cancelled", intent)
        return f"Cancelled {intent.replace('_', ' ')}."

    @staticmethod
    def _first_existing_command(candidates: list[str | Path | None]) -> str | Path | None:
        for candidate in candidates:
            if not candidate:
                continue
            if isinstance(candidate, Path):
                if candidate.exists():
                    return candidate
                continue
            return candidate
        return None

    @staticmethod
    def _open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(path)])

    def _find_chrome_exe(self) -> Path | None:
        candidates: list[Path] = []
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        found = shutil.which("chrome.exe")
        return Path(found) if found else None

    def _schedule(self, label: str, due_at: datetime, message: str, task_type: str) -> None:
        delay = max(0.0, (due_at - datetime.now()).total_seconds())
        task_id = str(uuid.uuid4())

        def fire() -> None:
            self.tasks.pop(task_id, None)
            self._complete_task(label)
            self.speaker(message)

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        self.tasks[task_id] = ScheduledTask(task_id, label, due_at, timer)
        self._record_task(task_type, label, "scheduled", due_at)
        timer.start()

    def _record_task(self, task_type: str, content: str, status: str, due_at: datetime | None = None) -> None:
        if not self.store:
            return
        self.store.insert_json(
            "task_history",
            {
                "task_type": task_type,
                "content": content,
                "status": status,
                "due_at": due_at.isoformat() if due_at else None,
                "created_at": utc_now(),
                "completed_at": None,
            },
        )

    def _complete_task(self, content: str) -> None:
        if not self.store:
            return
        self.store.execute(
            "UPDATE task_history SET status = 'completed', completed_at = ? WHERE content = ? AND status = 'scheduled'",
            (utc_now(), content),
        )

    @staticmethod
    def _extract_reminder_text(text: str) -> str:
        match = re.search(r"\bto\s+(.+)$", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_after(text: str, prefixes: list[str]) -> str:
        normalized = normalize_text(text)
        for prefix in prefixes:
            if normalized.startswith(prefix + " "):
                return normalized[len(prefix) + 1 :].strip()
        return ""

    @staticmethod
    def _extract_symbol(text: str, prefixes: list[str]) -> str:
        normalized = normalize_text(text)
        for prefix in prefixes:
            if normalized.startswith(prefix):
                value = normalized[len(prefix) :].strip()
                value = re.sub(r"^(for|of|is)\s+", "", value)
                return value.split()[0] if value else ""
        words = normalized.split()
        return words[-1] if words else ""

    def _resolve_coin_id(self, asset: str) -> str:
        aliases = {
            "btc": "bitcoin",
            "bitcoin": "bitcoin",
            "eth": "ethereum",
            "ethereum": "ethereum",
            "sol": "solana",
            "solana": "solana",
            "ada": "cardano",
            "cardano": "cardano",
            "doge": "dogecoin",
            "dogecoin": "dogecoin",
            "xrp": "ripple",
            "ripple": "ripple",
            "dot": "polkadot",
            "polkadot": "polkadot",
            "link": "chainlink",
            "chainlink": "chainlink",
        }
        cleaned = normalize_text(asset)
        if cleaned in aliases:
            return aliases[cleaned]
        response = requests.get("https://api.coingecko.com/api/v3/search", params={"query": cleaned}, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        coins = response.json().get("coins", [])
        if coins:
            return coins[0]["id"]
        return cleaned.replace(" ", "-")

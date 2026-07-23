"""Security, permissions, rate limiting, secrets, and audit logging."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assistant.config import Settings
from assistant.memory.database import SQLiteStore, utc_now
from assistant.utils.logger import get_logger


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str = ""


class AuditLogger:
    """Writes security-relevant events into SQLite."""

    def __init__(self, store: SQLiteStore | None) -> None:
        self.store = store
        self.logger = get_logger(__name__)

    def record(
        self,
        action: str,
        allowed: bool,
        reason: str = "",
        actor: str = "voice-user",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = metadata or {}
        self.logger.info("audit action=%s allowed=%s reason=%s", action, allowed, reason)
        if self.store is None:
            return
        self.store.insert_json(
            "audit_events",
            {
                "action": action,
                "actor": actor,
                "allowed": 1 if allowed else 0,
                "reason": reason,
                "metadata": payload,
                "created_at": utc_now(),
            },
        )


class PermissionManager:
    """Central permission policy for risky local actions."""

    def __init__(self, settings: Settings, audit: AuditLogger | None = None) -> None:
        self.settings = settings
        self.audit = audit

    def check(self, permission: str, target: str = "") -> PermissionDecision:
        decision = self._check(permission, target)
        if self.audit:
            self.audit.record(
                action=permission,
                allowed=decision.allowed,
                reason=decision.reason,
                metadata={"target": target},
            )
        return decision

    def require(self, permission: str, target: str = "") -> None:
        decision = self.check(permission, target)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _check(self, permission: str, target: str) -> PermissionDecision:
        if permission == "power":
            return PermissionDecision(
                self.settings.enable_power_commands,
                "Power commands are disabled." if not self.settings.enable_power_commands else "",
            )
        if permission == "destructive_system":
            return PermissionDecision(
                self.settings.enable_destructive_system_commands,
                "Destructive system commands are disabled."
                if not self.settings.enable_destructive_system_commands
                else "",
            )
        if permission == "file_delete":
            return PermissionDecision(
                self.settings.enable_file_delete,
                "File deletion is disabled." if not self.settings.enable_file_delete else "",
            )
        if permission == "filesystem_write":
            return self._path_allowed(target, write=True)
        if permission == "filesystem_read":
            return self._path_allowed(target, write=False)
        if permission == "plugin":
            return PermissionDecision(self.settings.enable_plugins, "Plugins are disabled.")
        return PermissionDecision(True, "")

    def _path_allowed(self, target: str, write: bool) -> PermissionDecision:
        if not target:
            return PermissionDecision(True, "")
        try:
            resolved = Path(target).expanduser().resolve()
        except OSError as exc:
            return PermissionDecision(False, f"Invalid path: {exc}")

        roots = self.settings.allowed_write_roots if write else self.settings.allowed_read_roots
        if not roots:
            return PermissionDecision(True, "")
        for root in roots:
            try:
                root_resolved = root.expanduser().resolve()
                if resolved == root_resolved or root_resolved in resolved.parents:
                    return PermissionDecision(True, "")
            except OSError:
                continue
        mode = "write" if write else "read"
        return PermissionDecision(False, f"Path is outside allowed {mode} roots: {resolved}")


class RateLimiter:
    """Simple in-process sliding-window rate limiter."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max(1, max_events)
        self.window_seconds = max(1.0, window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.max_events:
            return False
        events.append(now)
        return True


class SecretVault:
    """Encrypted local secret vault backed by Fernet when cryptography is installed."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.secrets_file.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(__name__)

    def set_secret(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = self._encrypt(value)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_secret(self, key: str) -> str | None:
        data = self._load()
        encrypted = data.get(key)
        if encrypted is None:
            return None
        return self._decrypt(encrypted)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.logger.warning("Secret vault is invalid JSON; ignoring it.")
            return {}

    def _encrypt(self, value: str) -> str:
        try:
            from cryptography.fernet import Fernet

            return Fernet(self._fernet_key()).encrypt(value.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            self.logger.warning("Fernet encryption unavailable; using OS-user obfuscation: %s", exc)
            key = hashlib.sha256(self._raw_key()).digest()
            raw = value.encode("utf-8")
            encrypted = bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))
            return "xor:" + base64.urlsafe_b64encode(encrypted).decode("ascii")

    def _decrypt(self, value: str) -> str:
        if value.startswith("xor:"):
            key = hashlib.sha256(self._raw_key()).digest()
            raw = base64.urlsafe_b64decode(value[4:].encode("ascii"))
            return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw)).decode("utf-8")
        from cryptography.fernet import Fernet

        return Fernet(self._fernet_key()).decrypt(value.encode("utf-8")).decode("utf-8")

    def _fernet_key(self) -> bytes:
        raw = self._raw_key()
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)

    def _raw_key(self) -> bytes:
        configured = os.getenv("JARVIS_MASTER_KEY")
        if configured:
            return configured.encode("utf-8")
        user = os.getenv("USERNAME") or os.getenv("USER") or "jarvis-user"
        machine = f"{user}:{self.path.parent}".encode("utf-8", errors="ignore")
        return machine



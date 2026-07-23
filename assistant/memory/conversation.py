"""Session, long-term, semantic, and preference memory Agent V1."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assistant.config import Settings
from assistant.memory.database import SQLiteStore, utc_now
from assistant.memory.rag import cosine, embed_text
from assistant.core.event_bus import publish_event
from assistant.core.events import EventType, EventSource, MemoryPayload

@dataclass
class AgentResult:
    """Structured result returned by the Memory Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class MemoryRecord:
    id: int
    kind: str
    content: str
    summary: str
    importance: float
    score: float = 0.0


class ConversationMemory:
    """Keeps short-term context and persistent long-term memory."""

    def __init__(self, settings: Settings, store: SQLiteStore | None = None) -> None:
        self.settings = settings
        self.store = store or SQLiteStore(settings.database_path)
        self.session_id = str(uuid.uuid4())
        self._messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self._build_system_prompt(settings))
        ]

        # ── Memory Agent State ────────────────────────────────────────────────
        self.active_session: str = self.session_id
        self.recent_memories: list[dict[str, Any]] = []
        self.memory_count: int = 0
        self.last_stored_item: str = ""
        self.last_retrieved_item: str = ""

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Verify action is a supported memory agent command."""
        supported = {
            "store", "retrieve", "update", "delete", "search",
            "list_memories", "recent", "clear", "stats"
        }
        return task.action in supported

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}

        try:
            if action == "store":
                content = params.get("content", "")
                kind = params.get("kind", "semantic")
                importance = float(params.get("importance", 0.6))
                msg = self.store_mem(content, kind, importance)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "retrieve":
                key = params.get("key", "")
                val = self.retrieve(key)
                if val is not None:
                    return AgentResult(
                        success=True,
                        message=f"Retrieved memory value for key: {key}.",
                        data={"value": val}
                    )
                return AgentResult(
                    success=False,
                    message=f"Memory not found for key: {key}.",
                    error="memory_not_found"
                )

            elif action == "update":
                mem_id = int(params.get("id", 0))
                content = params.get("content", "")
                msg = self.update(mem_id, content)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "delete":
                mem_id = int(params.get("id", 0))
                msg = self.delete(mem_id)
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "search":
                query = params.get("query", "")
                results = self.search_list(query)
                return AgentResult(
                    success=True,
                    message=f"Found {len(results)} memories matching query '{query}'.",
                    data={"results": results}
                )

            elif action == "list_memories":
                kind = params.get("kind")
                results = self.list_memories(kind)
                return AgentResult(
                    success=True,
                    message=f"Retrieved {len(results)} memories.",
                    data={"memories": results}
                )

            elif action == "recent":
                limit = int(params.get("limit", 5))
                results = self.recent(limit)
                return AgentResult(
                    success=True,
                    message=f"Retrieved {len(results)} recent memories.",
                    data={"recent": results}
                )

            elif action == "clear":
                msg = self.clear()
                return AgentResult(success=True, message=msg, data=self.get_state())

            elif action == "stats":
                data = self.stats()
                return AgentResult(
                    success=True,
                    message="Memory stats retrieved.",
                    data=data
                )

            else:
                return AgentResult(
                    success=False,
                    message=f"Unsupported action: {action}",
                    error="unsupported_action"
                )

        except ValueError as exc:
            return AgentResult(success=False, message=str(exc), error="invalid_key")
        except ModuleNotFoundError as exc:
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        return self.get_state()

    def health(self) -> str:
        return "healthy"

    # ── Memory Agent APIs ────────────────────────────────────────────────────

    def store_mem(self, content: str, kind: str = "semantic", importance: float = 0.6) -> str:
        """Store a new semantic or conversation memory entry."""
        if not content.strip():
            raise ValueError("Memory content cannot be empty.")
        
        rec_id = self.remember(content, kind, importance)
        self.last_stored_item = content
        self._sync_stats()
        return f"Stored memory ID {rec_id} successfully."

    def retrieve(self, key: str) -> str | None:
        """Retrieve preference value or search matching content."""
        if not key.strip():
            raise ValueError("Key name cannot be empty.")
            
        val = self.get_preference(key)
        if val is not None:
            self.last_retrieved_item = val
            return val
            
        # Fallback to search best match
        matches = self.search(key, limit=1)
        if matches:
            res = matches[0].content
            self.last_retrieved_item = res
            return res
        return None

    def update(self, memory_id: int, content: str) -> str:
        """Update an existing memory entry."""
        row = self.store.query_one("SELECT id FROM memories WHERE id = ?", (memory_id,))
        if not row:
            raise ValueError(f"Memory not found for ID: {memory_id}")
            
        summary = self.summarize_text(content)
        vector = embed_text(content, self.settings.rag_vector_dimensions)
        self.store.execute(
            "UPDATE memories SET content = ?, summary = ?, vector = ?, updated_at = ? WHERE id = ?",
            (content, summary, json.dumps(vector), utc_now(), memory_id)
        )
        self._sync_stats()
        return f"Updated memory ID {memory_id}."

    def delete(self, memory_id: int) -> str:
        """Delete an existing memory entry."""
        row = self.store.query_one("SELECT id FROM memories WHERE id = ?", (memory_id,))
        if not row:
            raise ValueError(f"Memory not found for ID: {memory_id}")
            
        self.store.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._sync_stats()
        return f"Deleted memory ID {memory_id}."

    def search_list(self, query: str) -> list[dict[str, Any]]:
        """Return dict representation of search matches."""
        records = self.search(query)
        results = []
        for r in records:
            results.append({
                "id": r.id,
                "kind": r.kind,
                "content": r.content,
                "summary": r.summary,
                "score": r.score
            })
        return results

    def list_memories(self, kind: str | None = None) -> list[dict[str, Any]]:
        """List stored memories matching option filter."""
        query = "SELECT id, kind, content, summary, importance, created_at FROM memories"
        params = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
            
        rows = self.store.query(query, params)
        return [dict(row) for row in rows]

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        """List most recently added memory logs."""
        rows = self.store.query("SELECT id, kind, content, summary FROM memories ORDER BY id DESC LIMIT ?", (limit,))
        res = [dict(row) for row in rows]
        self.recent_memories = res
        return res

    def clear(self) -> str:
        """Wipe memories table."""
        self.store.execute("DELETE FROM memories")
        self._sync_stats()
        return "Cleared all long-term memories."

    def stats(self) -> dict[str, Any]:
        """Expose memory usage count stats."""
        self._sync_stats()
        return {
            "session_id": self.session_id,
            "memory_count": self.memory_count,
            "conversations_count": len(self._messages)
        }

    def get_state(self) -> dict[str, Any]:
        """Expose active metrics to SharedContext."""
        return {
            "active_session": self.session_id,
            "last_memory": self.last_retrieved_item or self.last_stored_item,
            "recent_memories": self.recent_memories,
            "memory_count": self.memory_count,
            "last_stored_item": self.last_stored_item,
            "last_retrieved_item": self.last_retrieved_item
        }

    # ── Backward Compatibility Methods ───────────────────────────────────────

    def add_user(self, content: str) -> None:
        self._add_message("user", content)

    def add_assistant(self, content: str) -> None:
        self._add_message("assistant", content)

    def messages(self, mode_prompt: str | None = None) -> list[dict[str, str]]:
        messages = [{"role": message.role, "content": message.content} for message in self._messages]
        if mode_prompt:
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"] + "\n\nActive specialist mode: " + mode_prompt,
            }
        semantic = self.search("\n".join(message.content for message in self._messages[-4:]), limit=4)
        if semantic:
            memory_text = "\n".join(f"- {record.summary or record.content}" for record in semantic)
            messages.insert(1, {"role": "system", "content": "Relevant long-term memory:\n" + memory_text})
        return messages

    def remember(self, content: str, kind: str = "semantic", importance: float = 0.6, tags: list[str] | None = None) -> int:
        summary = self.summarize_text(content)
        vector = embed_text(content, self.settings.rag_vector_dimensions)
        rec_id = self.store.insert_json(
            "memories",
            {
                "kind": kind,
                "content": content,
                "summary": summary,
                "importance": max(0.0, min(1.0, importance)),
                "vector": vector,
                "tags": tags or [],
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )
        # Publish MEMORY_UPDATED event
        publish_event(
            EventType.MEMORY_UPDATED,
            payload=MemoryPayload(operation="remember", entry_count=1),
            source=EventSource.MEMORY
        )
        return rec_id

    def forget(self, query: str) -> int:
        matches = self.search(query, limit=10)
        deleted = 0
        for record in matches:
            if record.score >= 0.55 or query.lower() in record.content.lower():
                self.store.execute("DELETE FROM memories WHERE id = ?", (record.id,))
                deleted += 1
        if deleted > 0:
            # Publish MEMORY_UPDATED event
            publish_event(
                EventType.MEMORY_UPDATED,
                payload=MemoryPayload(operation="forget", entry_count=deleted),
                source=EventSource.MEMORY
            )
        return deleted

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        if not query.strip():
            return []
        query_vector = embed_text(query, self.settings.rag_vector_dimensions)
        rows = self.store.query("SELECT id, kind, content, summary, importance, vector FROM memories")
        records: list[MemoryRecord] = []
        for row in rows:
            vector = json.loads(row["vector"] or "[]")
            score = cosine(query_vector, vector) * 0.8 + float(row["importance"]) * 0.2
            if query.lower() in str(row["content"]).lower():
                score += 0.25
            if score > 0.05:
                records.append(
                    MemoryRecord(
                        id=int(row["id"]),
                        kind=str(row["kind"]),
                        content=str(row["content"]),
                        summary=str(row["summary"]),
                        importance=float(row["importance"]),
                        score=score,
                    )
                )
        records.sort(key=lambda item: item.score, reverse=True)
        return records[:limit]

    def set_preference(self, key: str, value: str) -> None:
        self.store.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, utc_now()),
        )

    def get_preference(self, key: str) -> str | None:
        row = self.store.query_one("SELECT value FROM user_preferences WHERE key = ?", (key,))
        return str(row["value"]) if row else None

    def backup(self, destination: Path | None = None) -> Path:
        destination = destination or self.settings.data_dir / f"memory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.settings.database_path, destination)
        return destination

    def reset(self) -> None:
        system = self._messages[0]
        self._messages = [system]
        # Publish MEMORY_UPDATED event
        publish_event(
            EventType.MEMORY_UPDATED,
            payload=MemoryPayload(operation="reset", entry_count=0),
            source=EventSource.MEMORY
        )

    @staticmethod
    def summarize_text(text: str, max_chars: int = 240) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= max_chars:
            return cleaned
        sentence_end = cleaned.find(".", 0, max_chars)
        if 80 <= sentence_end <= max_chars:
            return cleaned[: sentence_end + 1]
        return cleaned[: max_chars - 3].rstrip() + "..."

    def _add_message(self, role: str, content: str) -> None:
        self._messages.append(ChatMessage(role=role, content=content))
        self.store.insert_json(
            "conversations",
            {
                "session_id": self.session_id,
                "role": role,
                "content": content,
                "mode": self.settings.default_ai_mode,
                "created_at": utc_now(),
            },
        )
        if role == "user" and self._looks_memorable(content):
            self.remember(content, kind="conversation", importance=0.45)
        self._trim()

    def _trim(self) -> None:
        max_messages = max(4, self.settings.conversation_max_messages)
        if len(self._messages) <= max_messages:
            return
        system = self._messages[0]
        overflow = self._messages[1 : -(max_messages - 1)]
        if overflow:
            summary = self.summarize_text(" ".join(message.content for message in overflow), 500)
            self.remember(summary, kind="summary", importance=0.5)
        self._messages = [system] + self._messages[-(max_messages - 1) :]

    @staticmethod
    def _looks_memorable(content: str) -> bool:
        normalized = content.lower()
        cues = ["remember", "my name", "i prefer", "i like", "i work", "my project", "note that"]
        return any(cue in normalized for cue in cues)

    @staticmethod
    def _build_system_prompt(settings: Settings) -> str:
        return (
            f"You are {settings.assistant_name}, a calm, capable AI operating system for "
            f"{settings.user_name}. Behave like a practical JARVIS-inspired assistant: concise, "
            "technically sharp, proactive, and composed. Local modules handle Windows control, "
            "browser automation, memory, vision, RAG, plugins, MCP tools, and security policy. "
            "When answering, use relevant memory, ask focused follow-up questions when needed, "
            "and keep spoken responses compact unless the user asks for depth."
        )

    # ── Private Helpers ──────────────────────────────────────────────────────

    def _sync_stats(self) -> None:
        row = self.store.query_one("SELECT COUNT(*) as count FROM memories")
        self.memory_count = int(row["count"]) if row else 0

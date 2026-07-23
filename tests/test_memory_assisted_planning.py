"""Phase 2.4 — Memory-Assisted Planning regression tests.

Coverage matrix
---------------
1. Backward compatibility — plan() without planning_context is identical.
2. Backward compatibility — plan(intent, planning_context=None) identical.
3. Memory context injected into open_site task.
4. Memory context injected into open_application task.
5. Memory context injected into both search tasks.
6. Memory context injected into general/Orchestrator fallback task.
7. Empty planning_context ({}) does NOT add memory_context key.
8. Deterministic goals (media_control, play_result, browser_navigation,
   close_tab) bypass memory retrieval entirely.
9. _retrieve_planning_context routes through engine.execute() — not MemoryAgent
   directly — and returns the structured data dict.
10. No-memory engine (memory=None) -> {} returned, zero engine calls.
11. Engine failure -> {} returned, plan proceeds normally (graceful degradation).
12. SharedContext active_session unchanged after memory retrieval.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from assistant.brain.agent_coordinator import AgentResult
from assistant.brain.agent_pipeline import AgentTask, ParsedIntent, TaskPlanner


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _intent(
    goal: str,
    action: str = "none",
    target: str = "",
    context: str = "general",
    parameters: dict | None = None,
) -> ParsedIntent:
    return ParsedIntent(
        goal=goal,
        action=action,
        target=target,
        parameters=parameters or {},
        context=context,
    )


class MemoryEngine:
    """Fake ExecutionEngine that returns structured MemoryAgent search results."""

    def __init__(
        self,
        memories: list[dict] | None = None,
        fail: bool = False,
    ) -> None:
        self.memory = object()          # non-None means memory is available
        self.vision = None
        self.context = SimpleNamespace(active_session="sess-42", last_memory="")
        self.calls: list[AgentTask] = []
        self._memories = memories if memories is not None else [
            {"content": "preferred email: gmail", "id": 1, "score": 0.95},
        ]
        self._fail = fail

    def execute(self, tasks: list[AgentTask], request_id: str = "") -> Any:
        task = tasks[0]
        self.calls.append(task)
        if self._fail:
            raise RuntimeError("memory store unreachable")
        if task.agent == "MemoryAgent" and task.action == "search":
            return AgentResult(
                success=True,
                message=f"Found {len(self._memories)} memories.",
                data={"results": self._memories},
            )
        task.status = "completed"
        return f"{task.action}:completed"


class NoMemoryEngine:
    """Fake ExecutionEngine where memory is explicitly None."""

    def __init__(self) -> None:
        self.memory = None
        self.vision = None
        self.context = SimpleNamespace(active_session="sess-00", last_memory="")
        self.calls: list[AgentTask] = []

    def execute(self, tasks: list[AgentTask], request_id: str = "") -> str:
        task = tasks[0]
        self.calls.append(task)
        task.status = "completed"
        return f"{task.action}:completed"


def _make_router(engine: Any) -> Any:
    """Build a minimal CommandRouter shell for unit-testing _retrieve_planning_context.

    Uses object.__new__ to bypass __init__ (which requires real agent objects).
    Only the attributes used by _retrieve_planning_context and
    _MEMORY_ASSISTED_GOALS are populated.
    """
    from assistant.brain.intent import CommandRouter

    router = object.__new__(CommandRouter)
    router.execution_engine = engine
    router.logger = logging.getLogger("test.router")
    return router


# ---------------------------------------------------------------------------
# 1-2. Backward compatibility
# ---------------------------------------------------------------------------

def test_planner_backward_compatible_no_context_arg():
    """plan() called without planning_context arg produces identical output."""
    planner = TaskPlanner()
    tasks = planner.plan(_intent("open_site", parameters={"site": "youtube"}))
    assert len(tasks) == 1
    assert tasks[0].agent == "BrowserAgent"
    assert tasks[0].action == "open"
    assert tasks[0].parameters == {"name": "youtube"}
    assert "memory_context" not in tasks[0].parameters


def test_planner_backward_compatible_explicit_none():
    """plan(intent, planning_context=None) is identical to omitting the arg."""
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("open_application", parameters={"app_name": "vs code"}),
        planning_context=None,
    )
    assert len(tasks) == 1
    assert tasks[0].parameters == {"name": "vs code"}
    assert "memory_context" not in tasks[0].parameters


# ---------------------------------------------------------------------------
# 3-6. Memory context injected for benefiting goals
# ---------------------------------------------------------------------------

def test_memory_context_injected_into_open_site_task():
    ctx = {"retrieved_memories": [{"content": "preferred email: gmail"}], "query": "email"}
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("open_site", parameters={"site": "gmail"}),
        planning_context=ctx,
    )
    assert len(tasks) == 1
    assert tasks[0].parameters["name"] == "gmail"
    assert tasks[0].parameters["memory_context"] == ctx


def test_memory_context_injected_into_open_application_task():
    ctx = {"retrieved_memories": [{"content": "project path: F:/Jarvis-AI"}], "query": "project"}
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("open_application", parameters={"app_name": "vs code"}),
        planning_context=ctx,
    )
    assert len(tasks) == 1
    assert tasks[0].agent == "DesktopAgent"
    assert tasks[0].parameters["memory_context"] == ctx


def test_memory_context_injected_into_both_search_tasks():
    ctx = {"retrieved_memories": [{"content": "research topic: AI safety"}], "query": "AI"}
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("search", parameters={"site": "google", "query": "AI safety papers"}),
        planning_context=ctx,
    )
    assert len(tasks) == 2
    assert all(t.parameters.get("memory_context") == ctx for t in tasks)
    assert tasks[0].action == "open"
    assert tasks[1].action == "search"


def test_memory_context_injected_into_general_fallback_task():
    ctx = {"retrieved_memories": [{"content": "user timezone: IST"}], "query": "time"}
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("general", target="what time is it"),
        planning_context=ctx,
    )
    assert len(tasks) == 1
    assert tasks[0].agent == "Orchestrator"
    assert tasks[0].parameters["prompt"] == "what time is it"
    assert tasks[0].parameters["memory_context"] == ctx


# ---------------------------------------------------------------------------
# 7. Empty context guard
# ---------------------------------------------------------------------------

def test_empty_planning_context_does_not_inject_memory_key():
    """plan(intent, planning_context={}) leaves task params unchanged."""
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("open_site", parameters={"site": "youtube"}),
        planning_context={},
    )
    assert "memory_context" not in tasks[0].parameters
    assert tasks[0].parameters == {"name": "youtube"}


# ---------------------------------------------------------------------------
# 8. Deterministic goals bypass memory retrieval entirely
# ---------------------------------------------------------------------------

def test_deterministic_goals_skip_memory_retrieval():
    """media_control, play_result, browser_navigation, close_tab get no engine call."""
    engine = MemoryEngine()
    router = _make_router(engine)
    for goal in ("media_control", "play_result", "browser_navigation", "close_tab"):
        ctx = router._retrieve_planning_context(_intent(goal, target="video"))
        assert ctx == {}, f"Expected {{}} for deterministic goal '{goal}', got {ctx!r}"
    assert len(engine.calls) == 0, "MemoryAgent must not be called for deterministic goals"


def test_deterministic_goals_produce_no_memory_context_in_tasks():
    """play_result task has no memory_context key regardless of engine state."""
    planner = TaskPlanner()
    tasks = planner.plan(
        _intent("play_result", parameters={"index": 1}),
        planning_context={"retrieved_memories": [{"content": "foo"}], "query": "bar"},
    )
    assert len(tasks) == 1
    assert "memory_context" not in tasks[0].parameters


# ---------------------------------------------------------------------------
# 9. Engine-routed memory retrieval
# ---------------------------------------------------------------------------

def test_retrieve_context_calls_engine_not_memory_directly():
    """_retrieve_planning_context creates MemoryAgent/search task and routes through engine."""
    engine = MemoryEngine(memories=[{"content": "email: gmail", "id": 1}])
    router = _make_router(engine)
    intent = _intent("open_site", target="email", parameters={"site": "gmail"})
    ctx = router._retrieve_planning_context(intent)

    assert len(engine.calls) == 1
    task = engine.calls[0]
    assert task.agent == "MemoryAgent"
    assert task.action == "search"
    assert task.parameters["query"] == "email"

    assert "retrieved_memories" in ctx
    assert ctx["retrieved_memories"] == [{"content": "email: gmail", "id": 1}]
    assert ctx["query"] == "email"


def test_retrieve_context_returns_empty_when_no_results():
    """Memory search returning empty list produces {} context."""
    engine = MemoryEngine(memories=[])
    router = _make_router(engine)
    ctx = router._retrieve_planning_context(_intent("open_site", target="youtube"))
    assert ctx == {}


# ---------------------------------------------------------------------------
# 10. No-memory graceful degradation
# ---------------------------------------------------------------------------

def test_retrieve_context_returns_empty_when_memory_is_none():
    """engine.memory is None -> {} returned, zero engine calls."""
    engine = NoMemoryEngine()
    router = _make_router(engine)
    ctx = router._retrieve_planning_context(_intent("open_site", target="youtube"))
    assert ctx == {}
    assert len(engine.calls) == 0


def test_planning_proceeds_normally_without_memory():
    """Full planner invocation with {} context produces identical baseline tasks."""
    planner = TaskPlanner()
    intent = _intent("open_site", target="youtube", parameters={"site": "youtube"})
    tasks_no_ctx = planner.plan(intent)
    tasks_empty_ctx = planner.plan(intent, planning_context={})
    assert tasks_no_ctx[0].parameters == tasks_empty_ctx[0].parameters


# ---------------------------------------------------------------------------
# 11. Engine failure -> graceful degradation
# ---------------------------------------------------------------------------

def test_retrieve_context_returns_empty_on_engine_failure():
    """RuntimeError from engine is caught; {} returned; no exception propagated."""
    engine = MemoryEngine(fail=True)
    router = _make_router(engine)
    ctx = router._retrieve_planning_context(
        _intent("open_application", target="github", parameters={"app_name": "github"})
    )
    assert ctx == {}


def test_planning_proceeds_after_memory_failure():
    """Even after retrieval failure, planner produces the correct task structure."""
    planner = TaskPlanner()
    intent = _intent("open_application", parameters={"app_name": "vs code"})
    tasks = planner.plan(intent, planning_context={})
    assert len(tasks) == 1
    assert tasks[0].agent == "DesktopAgent"
    assert tasks[0].parameters["name"] == "vs code"
    assert "memory_context" not in tasks[0].parameters


# ---------------------------------------------------------------------------
# 12. SharedContext preservation
# ---------------------------------------------------------------------------

def test_shared_context_session_unchanged_after_retrieval():
    """engine.context.active_session is not mutated by _retrieve_planning_context."""
    engine = MemoryEngine()
    original_session = engine.context.active_session
    router = _make_router(engine)
    router._retrieve_planning_context(
        _intent("search", target="iron man", parameters={"site": "youtube", "query": "iron man"})
    )
    assert engine.context.active_session == original_session

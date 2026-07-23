from types import SimpleNamespace

from assistant.brain.agent_coordinator import AgentCoordinator, CoordinatorResult
from assistant.brain.agent_pipeline import AgentTask


class FakeExecutionEngine:
    def __init__(self, fail_actions: set[str] | None = None, vision=None) -> None:
        self.context = SimpleNamespace(updated=0)
        self.calls: list[str] = []
        self.task_batch_sizes: list[int] = []
        self.fail_actions = fail_actions or set()
        self.vision = vision

    def execute(self, tasks, request_id=""):
        task = tasks[0]
        self.task_batch_sizes.append(len(tasks))
        self.calls.append(task.action)
        task.status = "failed" if task.action in self.fail_actions else "completed"
        self.context.updated += 1
        return f"{task.action}:{task.status}"


def test_coordinate_single_task_uses_execution_engine():
    engine = FakeExecutionEngine()
    result = AgentCoordinator(engine).coordinate([AgentTask(action="one")])
    assert isinstance(result, CoordinatorResult)
    assert result.success and result.completed_steps == 1
    assert engine.calls == ["one"]
    assert result.results[0].success


def test_coordinate_preserves_multi_task_order_and_context():
    engine = FakeExecutionEngine()
    coordinator = AgentCoordinator(engine)
    result = coordinator.execute_plan([AgentTask(action="one"), AgentTask(action="two")])
    assert result.success and engine.calls == ["one", "two"]
    assert result.shared_context is engine.context
    assert engine.context.updated == 2


def test_coordinate_executes_three_step_workflow_sequentially():
    engine = FakeExecutionEngine()
    result = AgentCoordinator(engine).coordinate([AgentTask(action="one"), AgentTask(action="two"), AgentTask(action="three")])
    assert result.success and result.completed_steps == 3
    assert engine.calls == ["one", "two", "three"]
    assert engine.task_batch_sizes == [1, 1, 1]
    assert [task.action for task in result.execution_history] == engine.calls
    assert engine.context.updated == 3


def test_coordinate_executes_four_step_workflow_and_preserves_result_order():
    engine = FakeExecutionEngine()
    result = AgentCoordinator(engine).execute_plan([AgentTask(action=action) for action in ("one", "two", "three", "four")])
    assert result.success and len(result.results) == 4
    assert engine.calls == ["one", "two", "three", "four"]
    assert [step.data["action"] for step in result.results] == engine.calls
    assert engine.task_batch_sizes == [1, 1, 1, 1]
    assert engine.context.updated == 4


def test_coordinate_stops_on_critical_failure():
    engine = FakeExecutionEngine({"fail"})
    result = AgentCoordinator(engine).coordinate([AgentTask(action="one"), AgentTask(action="fail"), AgentTask(action="three")])
    assert not result.success and result.failed_step.action == "fail"
    assert result.error == "fail:failed"
    assert engine.calls == ["one", "fail"]


def test_coordinate_continues_after_noncritical_failure():
    engine = FakeExecutionEngine({"fail"})
    result = AgentCoordinator(engine).coordinate([
        AgentTask(action="fail", parameters={"critical": False}),
        AgentTask(action="two"),
    ])
    assert not result.success
    assert engine.calls == ["fail", "two"]


def test_cancel_plan_stops_before_next_step():
    engine = FakeExecutionEngine()
    coordinator = AgentCoordinator(engine)
    original_execute = engine.execute

    def cancel_after_first(tasks, request_id=""):
        response = original_execute(tasks, request_id)
        coordinator.cancel_plan()
        return response

    engine.execute = cancel_after_first
    result = coordinator.coordinate([AgentTask(action="one"), AgentTask(action="two")])
    assert not result.success and result.error == "plan_cancelled"
    assert engine.calls == ["one"]


def test_coordinate_returns_result_when_execution_engine_raises():
    class RaisingEngine:
        context = SimpleNamespace(updated=0)

        def execute(self, tasks, request_id=""):
            raise RuntimeError("engine boom")

    result = AgentCoordinator(RaisingEngine()).coordinate([AgentTask(action="one")])
    assert not result.success
    assert result.results[0].error == "unexpected_exception"
    assert result.error == "unexpected_exception"


def test_coordinate_preserves_structured_engine_result_and_context():
    class StructuredResult:
        success = False
        message = "Video result missing"
        data = {"query": "iron man"}
        error = "result_not_found"

    class StructuredEngine:
        def __init__(self):
            self.context = SimpleNamespace(version=0)

        def execute(self, tasks, request_id=""):
            self.context.version += 1
            tasks[0].status = "failed"
            return StructuredResult()

    engine = StructuredEngine()
    result = AgentCoordinator(engine).coordinate([AgentTask(action="play_result")])
    step_result = result.results[0]
    assert step_result.error == "result_not_found"
    assert step_result.data == {"query": "iron man"}
    assert result.shared_context is engine.context and engine.context.version == 1


def test_coordinate_retains_known_error_from_unstructured_engine_output():
    engine = FakeExecutionEngine({"fail"})

    def execute_with_timeout(tasks, request_id=""):
        tasks[0].status = "failed"
        return "Request timed out"

    engine.execute = execute_with_timeout
    result = AgentCoordinator(engine).coordinate([AgentTask(action="fail")])
    assert result.results[0].error == "timeout"


def test_coordinator_result_remains_constructible_with_phase_21_fields():
    context = SimpleNamespace()
    result = CoordinatorResult(True, 1, None, [], context)
    assert result.success and result.execution_history == []


def test_browser_task_is_followed_by_vision_verification():
    engine = FakeExecutionEngine(vision=object())
    result = AgentCoordinator(engine).coordinate([
        AgentTask(agent="BrowserAgent", action="open", parameters={"name": "YouTube"}),
    ])
    assert result.success
    assert engine.calls == ["open", "find_text"]
    assert engine.task_batch_sizes == [1, 1]
    assert len(result.verification_results) == 1 and result.verification_results[0].success
    assert [task.agent for task in result.execution_history] == ["BrowserAgent", "VisionAgent"]
    assert engine.context.updated == 2


def test_browser_vision_verification_failure_stops_critical_plan():
    engine = FakeExecutionEngine({"find_text"}, vision=object())
    result = AgentCoordinator(engine).coordinate([
        AgentTask(agent="BrowserAgent", action="search", parameters={"query": "Avengers"}),
        AgentTask(action="after_verification"),
    ])
    assert not result.success and result.failed_step.agent == "VisionAgent"
    assert engine.calls == ["search", "find_text"]
    assert len(result.verification_results) == 1 and not result.verification_results[0].success


def test_noncritical_browser_verification_allows_next_task():
    engine = FakeExecutionEngine({"find_text"}, vision=object())
    result = AgentCoordinator(engine).coordinate([
        AgentTask(agent="BrowserAgent", action="play_result", parameters={"verification_critical": False}),
        AgentTask(action="after_verification"),
    ])
    assert not result.success
    assert engine.calls == ["play_result", "find_text", "after_verification"]
    assert [task.action for task in result.execution_history] == ["play_result", "find_text", "after_verification"]


# ── Phase 2.3 regression tests ────────────────────────────────────────────────


def test_play_result_verification_uses_watch_path():
    """play_result must generate a VisionAgent task that looks for '/watch', not 'YouTube'."""
    engine = FakeExecutionEngine(vision=object())
    coordinator = AgentCoordinator(engine)
    result = coordinator.coordinate([
        AgentTask(agent="BrowserAgent", action="play_result", parameters={"index": 1}),
    ])
    assert result.success
    assert engine.calls == ["play_result", "find_text"]
    verification_task = next(t for t in coordinator.execution_history if t.agent == "VisionAgent")
    assert verification_task.parameters["text"] == "/watch"
    assert verification_task.parameters["verification_for"] == "play_result"


def test_open_result_verification_uses_watch_path():
    """open_result must generate a VisionAgent task that looks for '/watch', not 'YouTube'."""
    engine = FakeExecutionEngine(vision=object())
    coordinator = AgentCoordinator(engine)
    result = coordinator.coordinate([
        AgentTask(agent="BrowserAgent", action="open_result", parameters={"index": 1}),
    ])
    assert result.success
    assert engine.calls == ["open_result", "find_text"]
    verification_task = next(t for t in coordinator.execution_history if t.agent == "VisionAgent")
    assert verification_task.parameters["text"] == "/watch"


def test_vision_error_preserved_across_execution_boundary():
    """Structured VisionAgent errors (text_not_found, timeout, …) must not be
    collapsed into generic strings when crossing the ExecutionEngine boundary."""
    from assistant.brain.agent_coordinator import AgentResult

    class VisionStructuredEngine:
        def __init__(self):
            self.context = SimpleNamespace(updated=0)
            self.vision = object()  # signals vision is available

        def execute(self, tasks, request_id=""):
            self.context.updated += 1
            tasks[0].status = "failed"
            return AgentResult(
                success=False,
                message="Expected text '/watch' not found on screen.",
                data={"region": "full_screen"},
                error="text_not_found",
            )

    engine = VisionStructuredEngine()
    result = AgentCoordinator(engine).coordinate([
        AgentTask(agent="VisionAgent", action="find_text", parameters={"text": "/watch"}),
    ])
    assert not result.success
    step = result.results[0]
    assert step.error == "text_not_found", f"expected 'text_not_found', got '{step.error}'"
    assert step.data == {"region": "full_screen"}
    assert "not found" in step.message


def test_verification_lifecycle_logging(caplog):
    """All three verification log events must be emitted during a coordinator run."""
    import logging

    engine = FakeExecutionEngine(vision=object())
    with caplog.at_level(logging.INFO, logger="assistant.brain.agent_coordinator"):
        AgentCoordinator(engine).coordinate([
            AgentTask(agent="BrowserAgent", action="open", parameters={"name": "youtube"}),
        ])

    messages = [r.message for r in caplog.records]
    assert any("Verification started" in m for m in messages), "Missing 'Verification started' log"
    assert any("Verification completed" in m for m in messages), "Missing 'Verification completed' log"


def test_verification_failure_logging(caplog):
    """When verification fails, 'Verification failed' must appear in the log."""
    import logging

    engine = FakeExecutionEngine({"find_text"}, vision=object())
    with caplog.at_level(logging.WARNING, logger="assistant.brain.agent_coordinator"):
        AgentCoordinator(engine).coordinate([
            AgentTask(agent="BrowserAgent", action="open", parameters={"name": "youtube"}),
        ])

    messages = [r.message for r in caplog.records]
    assert any("Verification failed" in m for m in messages), "Missing 'Verification failed' log"


"""Phase 2.5 — Autonomous Workflows V1 regression tests.

Coverage matrix
---------------
1.  Successful multi-step workflow: execute_workflow() returns CoordinatorResult
    with workflow_state.status == COMPLETED.
2.  workflow_state.steps records every executed task in order.
3.  Workflow stops on critical failure and status == FAILED.
4.  Non-critical failure: workflow continues, status == FAILED (not COMPLETED).
5.  SharedContext is preserved across all workflow steps (same object reference).
6.  Execution history identical between coordinate() and execute_workflow().
7.  Backward compatibility: CoordinatorResult from coordinate() has
    workflow_state == None.
8.  Backward compatibility: CoordinatorResult still constructible positionally.
9.  Arbitrary-length workflow (10 steps) executes all steps in order.
10. WorkflowState duration_ms >= 0 and workflow_id is a valid UUID.
11. WorkflowStep fields are correctly populated (agent, action, success, error).
12. Cancelled workflow produces status == CANCELLED.
13. execute_workflow() name parameter sets WorkflowState.name.
14. execute_workflow() still uses ExecutionEngine (not direct agent calls).
15. WorkflowState.is_complete and is_failed convenience properties.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from assistant.brain.agent_coordinator import (
    AgentCoordinator,
    AgentResult,
    CoordinatorResult,
    WorkflowState,
    WorkflowStatus,
    WorkflowStep,
)
from assistant.brain.agent_pipeline import AgentTask


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

class FakeEngine:
    """Minimal ExecutionEngine fake: no vision, tracks call order."""

    def __init__(self, fail_actions: set[str] | None = None) -> None:
        self.context = SimpleNamespace(updated=0)
        self.calls: list[str] = []
        self.fail_actions = fail_actions or set()
        self.vision = None

    def execute(self, tasks, request_id=""):
        task = tasks[0]
        self.calls.append(task.action)
        task.status = "failed" if task.action in self.fail_actions else "completed"
        self.context.updated += 1
        return f"{task.action}:{task.status}"


def _plan(*actions: str, fail_set: set[str] | None = None, **kwargs) -> list[AgentTask]:
    """Helper: build a plan from action names, optionally marking some non-critical."""
    tasks = []
    for action in actions:
        params = {}
        if fail_set and action in fail_set:
            params.update(kwargs)
        tasks.append(AgentTask(action=action, parameters=params or None))
    return tasks


# ---------------------------------------------------------------------------
# 1. Successful multi-step workflow
# ---------------------------------------------------------------------------

def test_workflow_success_sets_completed_status():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action="one"), AgentTask(action="two"), AgentTask(action="three")],
        name="test-success",
    )
    assert result.success
    assert result.workflow_state is not None
    assert result.workflow_state.status == WorkflowStatus.COMPLETED
    assert result.workflow_state.is_complete
    assert not result.workflow_state.is_failed


def test_workflow_step_count_matches_plan():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action=f"step{i}") for i in range(5)],
    )
    assert result.workflow_state.step_count == 5


# ---------------------------------------------------------------------------
# 2. WorkflowState.steps records every executed task in order
# ---------------------------------------------------------------------------

def test_workflow_steps_recorded_in_order():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action="alpha"), AgentTask(action="beta"), AgentTask(action="gamma")],
    )
    actions = [s.action for s in result.workflow_state.steps]
    assert actions == ["alpha", "beta", "gamma"]


def test_workflow_steps_have_correct_step_indices():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action=f"step{i}") for i in range(4)],
    )
    indices = [s.step_index for s in result.workflow_state.steps]
    assert indices == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# 3. Critical failure stops workflow and marks status FAILED
# ---------------------------------------------------------------------------

def test_workflow_stops_on_critical_failure():
    engine = FakeEngine(fail_actions={"fail"})
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action="one"), AgentTask(action="fail"), AgentTask(action="three")],
    )
    assert not result.success
    assert result.workflow_state.status == WorkflowStatus.FAILED
    assert result.workflow_state.is_failed
    # "three" must NOT have been executed
    assert engine.calls == ["one", "fail"]
    assert len(result.workflow_state.steps) == 2


# ---------------------------------------------------------------------------
# 4. Non-critical failure: workflow continues, status FAILED
# ---------------------------------------------------------------------------

def test_workflow_continues_after_noncritical_failure():
    engine = FakeEngine(fail_actions={"fail"})
    result = AgentCoordinator(engine).execute_workflow([
        AgentTask(action="fail", parameters={"critical": False}),
        AgentTask(action="two"),
    ])
    assert not result.success
    assert result.workflow_state.status == WorkflowStatus.FAILED
    assert engine.calls == ["fail", "two"]
    assert len(result.workflow_state.steps) == 2


# ---------------------------------------------------------------------------
# 5. SharedContext preserved across all workflow steps
# ---------------------------------------------------------------------------

def test_workflow_shared_context_propagated():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action=f"step{i}") for i in range(4)],
    )
    # shared_context must reference the same engine context object
    assert result.shared_context is engine.context
    # context updated once per step
    assert engine.context.updated == 4


# ---------------------------------------------------------------------------
# 6. Execution history identical between coordinate() and execute_workflow()
# ---------------------------------------------------------------------------

def test_workflow_execution_history_matches_coordinate():
    tasks = [AgentTask(action="a"), AgentTask(action="b"), AgentTask(action="c")]

    engine1 = FakeEngine()
    result_coord = AgentCoordinator(engine1).coordinate(tasks)

    engine2 = FakeEngine()
    result_wf = AgentCoordinator(engine2).execute_workflow(tasks)

    coord_actions = [t.action for t in result_coord.execution_history]
    wf_actions = [t.action for t in result_wf.execution_history]
    assert coord_actions == wf_actions == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 7. Backward compatibility: coordinate() workflow_state is None
# ---------------------------------------------------------------------------

def test_coordinate_has_no_workflow_state():
    engine = FakeEngine()
    result = AgentCoordinator(engine).coordinate([AgentTask(action="one")])
    assert result.workflow_state is None


# ---------------------------------------------------------------------------
# 8. Backward compatibility: CoordinatorResult still positionally constructible
# ---------------------------------------------------------------------------

def test_coordinator_result_positional_construction_still_works():
    ctx = SimpleNamespace()
    result = CoordinatorResult(True, 1, None, [], ctx)
    assert result.success
    assert result.workflow_state is None
    assert result.execution_history == []
    assert result.verification_results == []


# ---------------------------------------------------------------------------
# 9. Arbitrary-length workflow (10 steps)
# ---------------------------------------------------------------------------

def test_workflow_arbitrary_length():
    engine = FakeEngine()
    n = 10
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action=f"task{i}") for i in range(n)],
        name="long-workflow",
    )
    assert result.success
    assert len(result.workflow_state.steps) == n
    assert result.workflow_state.completed_count == n
    assert engine.calls == [f"task{i}" for i in range(n)]


# ---------------------------------------------------------------------------
# 10. WorkflowState timing and UUID validity
# ---------------------------------------------------------------------------

def test_workflow_state_timing_and_uuid():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow([AgentTask(action="one")])
    state = result.workflow_state
    assert state.duration_ms >= 0
    # workflow_id must be a valid UUID4 string
    parsed = uuid.UUID(state.workflow_id, version=4)
    assert str(parsed) == state.workflow_id


# ---------------------------------------------------------------------------
# 11. WorkflowStep fields are correctly populated
# ---------------------------------------------------------------------------

def test_workflow_step_fields_success():
    engine = FakeEngine()
    task = AgentTask(agent="BrowserAgent", action="open")
    result = AgentCoordinator(engine).execute_workflow([task])
    step = result.workflow_state.steps[0]
    assert step.agent == "BrowserAgent"
    assert step.action == "open"
    assert step.success is True
    assert step.error == ""
    assert step.duration_ms >= 0
    assert step.task_id == task.id


def test_workflow_step_fields_failure():
    engine = FakeEngine(fail_actions={"fail"})
    task = AgentTask(agent="DesktopAgent", action="fail")
    result = AgentCoordinator(engine).execute_workflow([task])
    step = result.workflow_state.steps[0]
    assert step.agent == "DesktopAgent"
    assert step.action == "fail"
    assert step.success is False


# ---------------------------------------------------------------------------
# 12. Cancelled workflow produces status CANCELLED
# ---------------------------------------------------------------------------

def test_workflow_cancelled_sets_cancelled_status():
    engine = FakeEngine()
    coordinator = AgentCoordinator(engine)
    original_execute = engine.execute

    def cancel_after_first(tasks, request_id=""):
        response = original_execute(tasks, request_id)
        coordinator.cancel_plan()
        return response

    engine.execute = cancel_after_first
    result = coordinator.execute_workflow(
        [AgentTask(action="one"), AgentTask(action="two")]
    )
    assert not result.success
    assert result.workflow_state.status == WorkflowStatus.CANCELLED
    assert result.workflow_state.is_failed
    assert engine.calls == ["one"]


# ---------------------------------------------------------------------------
# 13. execute_workflow() name parameter propagates to WorkflowState
# ---------------------------------------------------------------------------

def test_workflow_name_parameter_set_in_state():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action="one")],
        name="my-named-workflow",
    )
    assert result.workflow_state.name == "my-named-workflow"


def test_workflow_auto_name_when_not_provided():
    engine = FakeEngine()
    result = AgentCoordinator(engine).execute_workflow([AgentTask(action="one")])
    # Auto-generated name starts with "workflow-"
    assert result.workflow_state.name.startswith("workflow-")


# ---------------------------------------------------------------------------
# 14. execute_workflow() still uses ExecutionEngine exclusively
# ---------------------------------------------------------------------------

def test_workflow_routes_through_engine_exclusively():
    """Every step must go through engine.execute() — batch size always 1."""
    engine = FakeEngine()
    n = 5
    result = AgentCoordinator(engine).execute_workflow(
        [AgentTask(action=f"s{i}") for i in range(n)]
    )
    assert result.success
    assert len(engine.calls) == n


# ---------------------------------------------------------------------------
# 15. WorkflowState convenience properties
# ---------------------------------------------------------------------------

def test_is_complete_and_is_failed_properties():
    from assistant.brain.agent_coordinator import WorkflowStatus, WorkflowState
    import time

    now = time.perf_counter()
    make = lambda status: WorkflowState(
        workflow_id="test-id", name="x", status=status,
        step_count=1, completed_count=1, started_at=now, completed_at=now,
    )
    assert make(WorkflowStatus.COMPLETED).is_complete is True
    assert make(WorkflowStatus.COMPLETED).is_failed is False
    assert make(WorkflowStatus.FAILED).is_complete is False
    assert make(WorkflowStatus.FAILED).is_failed is True
    assert make(WorkflowStatus.CANCELLED).is_failed is True
    assert make(WorkflowStatus.RUNNING).is_complete is False
    assert make(WorkflowStatus.RUNNING).is_failed is False

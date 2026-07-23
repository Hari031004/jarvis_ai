"""Sequential coordination layer between the task planner and execution engine."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from assistant.brain.agent_pipeline import AgentTask, SharedContext
from assistant.utils.logger import get_logger


@dataclass(slots=True)
class AgentResult:
    """ExecutionEngine output normalized for coordinated plan reporting."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(slots=True)
class CoordinatorResult:
    """Final outcome of a sequentially coordinated task plan."""

    success: bool
    completed_steps: int
    failed_step: AgentTask | None
    results: list[AgentResult]
    shared_context: SharedContext | Any
    error: str = ""
    execution_history: list[AgentTask] = field(default_factory=list)
    verification_results: list[AgentResult] = field(default_factory=list)
    # Phase 2.5: populated by execute_workflow(); None for coordinate() calls.
    workflow_state: WorkflowState | None = None


# ── Phase 2.5 — Autonomous Workflow Tracking ─────────────────────────────────

class WorkflowStatus:
    """String constants for WorkflowState.status.  Not an enum to keep slots=True."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class WorkflowStep:
    """Immutable record of a single step executed inside a workflow.

    Populated by execute_workflow(); absent from coordinate() paths.
    """
    step_index: int
    agent: str
    action: str
    success: bool
    error: str
    duration_ms: float
    task_id: str


@dataclass
class WorkflowState:
    """Lifecycle record for one execute_workflow() invocation.

    Tracks identity, progress, timing, and per-step detail for the full
    workflow.  Attached to CoordinatorResult.workflow_state so callers
    can inspect the complete execution trace without parsing execution_history.
    """
    workflow_id: str
    name: str
    status: str
    step_count: int
    completed_count: int
    started_at: float
    completed_at: float
    steps: list[WorkflowStep] = field(default_factory=list)

    # ── Convenience helpers ───────────────────────────────────────────────────

    @property
    def duration_ms(self) -> float:
        """Total wall-clock time for the workflow in milliseconds."""
        return (self.completed_at - self.started_at) * 1000

    @property
    def is_complete(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status in (WorkflowStatus.FAILED, WorkflowStatus.CANCELLED)



class AgentCoordinator:
    """Orchestrates planned tasks exclusively through an ExecutionEngine."""

    # Centralized mapping: BrowserAgent action → expected page-content indicator.
    # Used by _verification_task() as the default when no per-task
    # ``verification_text`` parameter is supplied.
    # Callers may override per-task via the ``verification_text`` parameter.
    _VERIFICATION_CRITERIA: dict[str, str] = {
        "open": "",          # resolved from task parameters (name/site)
        "search": "",        # resolved from task parameters (query)
        "play_result": "/watch",  # URL path segment present only on watch pages
        "open_result": "/watch",  # URL path segment present only on watch pages
    }

    def __init__(self, execution_engine: Any) -> None:
        self.execution_engine = execution_engine
        self.logger = get_logger(__name__)
        self._cancelled = False
        self._request_id = ""
        self.shared_context: SharedContext | Any = getattr(execution_engine, "context", None)
        self.execution_history: list[AgentTask] = []
        self.verification_results: list[AgentResult] = []

    def coordinate(self, tasks: list[AgentTask], request_id: str = "") -> CoordinatorResult:
        """Execute tasks in order and stop when a critical task fails."""
        self._cancelled = False
        self._request_id = request_id
        self.execution_history = []
        self.verification_results = []
        results: list[AgentResult] = []
        completed_steps = 0
        failed_step: AgentTask | None = None
        error = ""
        self.logger.info("Plan started: %d task(s)", len(tasks))

        for task in tasks:
            if self._cancelled:
                error = "plan_cancelled"
                break

            self.logger.info("Task started: id=%s agent=%s action=%s", task.id, task.agent, task.action)
            try:
                result = self.execute_step(task)
            except Exception as exc:
                # Defensive boundary: coordination must always produce a plan
                # outcome, even if an Engine implementation violates its
                # exception-containment contract.
                result = AgentResult(
                    success=False,
                    message=str(exc),
                    data={"task_id": task.id, "agent": task.agent, "action": task.action},
                    error="unexpected_exception",
                )
            results.append(result)
            self.update_context(result)
            self.execution_history.append(task)

            if result.success:
                completed_steps += 1
                self.logger.info("Task completed: id=%s", task.id)
                verification_task = self._verification_task(task)
                if verification_task is not None and not self._cancelled:
                    self.logger.info(
                        "Verification started: id=%s for_action=%s text=%s",
                        verification_task.id,
                        task.action,
                        (verification_task.parameters or {}).get("text", ""),
                    )
                    verification = self.execute_step(verification_task)
                    results.append(verification)
                    self.verification_results.append(verification)
                    self.update_context(verification)
                    self.execution_history.append(verification_task)
                    if verification.success:
                        completed_steps += 1
                        self.logger.info(
                            "Verification completed: id=%s for_action=%s",
                            verification_task.id,
                            task.action,
                        )
                    else:
                        self.logger.warning(
                            "Verification failed: id=%s for_action=%s error=%s",
                            verification_task.id,
                            task.action,
                            verification.error or verification.message,
                        )
                        failed_step = verification_task
                        error = verification.error or verification.message
                        if self.handle_failure(verification) and (verification_task.parameters or {}).get("critical", True):
                            break
                continue

            self.logger.warning("Task failed: id=%s error=%s", task.id, result.error)
            failed_step = task
            error = result.error or result.message
            if self.handle_failure(result) and (task.parameters or {}).get("critical", True):
                break

        success = not self._cancelled and failed_step is None
        if self._cancelled and not error:
            error = "plan_cancelled"
        self.logger.info("Plan completed: success=%s completed_steps=%d", success, completed_steps)
        return CoordinatorResult(
            success=success,
            completed_steps=completed_steps,
            failed_step=failed_step,
            results=results,
            shared_context=self.shared_context,
            error=error,
            execution_history=self.execution_history,
            verification_results=self.verification_results,
        )

    def execute_plan(self, plan: list[AgentTask], request_id: str = "") -> CoordinatorResult:
        """Backward-friendly alias for coordinating a planned task list."""
        return self.coordinate(plan, request_id)

    def execute_workflow(
        self,
        plan: list[AgentTask],
        name: str = "",
        request_id: str = "",
    ) -> CoordinatorResult:
        """Execute a planner-generated task list as a named, tracked workflow.

        Phase 2.5 entry-point.  Delegates sequentially to ``coordinate()``
        and wraps the outcome in a ``WorkflowState`` lifecycle record.

        Design rules (invariants):
        - Orchestration only — does NOT modify ExecutionEngine or agents.
        - Every step is timed and recorded in ``WorkflowState.steps``.
        - SharedContext is propagated identically to ``coordinate()``.
        - Failures stop the workflow immediately (critical) or continue
          (non-critical) — same semantics as ``coordinate()``.
        - Returns a ``CoordinatorResult`` with ``workflow_state`` populated;
          all other fields are identical to a ``coordinate()`` call.
        - Backward compatible: callers that do not use ``workflow_state``
          see no change.

        Args:
            plan:       Ordered list of AgentTasks from TaskPlanner.
            name:       Optional human-readable workflow name for logging.
            request_id: Forwarded to the engine for event correlation.

        Returns:
            CoordinatorResult with workflow_state attached.
        """
        workflow_id = str(uuid.uuid4())
        label = name or f"workflow-{workflow_id[:8]}"
        started_at = time.perf_counter()

        state = WorkflowState(
            workflow_id=workflow_id,
            name=label,
            status=WorkflowStatus.RUNNING,
            step_count=len(plan),
            completed_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        self.logger.info(
            "Workflow started: id=%s name=%r steps=%d",
            workflow_id, label, len(plan),
        )

        # Instrument each task with per-step timing via a thin wrapper.
        # All actual routing, failure logic, and SharedContext updates
        # remain inside coordinate() / execute_step().
        step_index = 0
        original_execute_step = self.execute_step

        def _timed_execute_step(task: AgentTask) -> AgentResult:
            nonlocal step_index
            t0 = time.perf_counter()
            result = original_execute_step(task)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            state.steps.append(WorkflowStep(
                step_index=step_index,
                agent=task.agent or "",
                action=task.action or "",
                success=result.success,
                error=result.error,
                duration_ms=elapsed_ms,
                task_id=task.id or "",
            ))
            if result.success:
                state.completed_count += 1
            step_index += 1
            return result

        # Temporarily bind the instrumented step dispatcher.
        self.execute_step = _timed_execute_step  # type: ignore[method-assign]
        try:
            coordinator_result = self.coordinate(plan, request_id)
        finally:
            # Always restore original method — even if coordinate() raises.
            self.execute_step = original_execute_step  # type: ignore[method-assign]

        state.completed_at = time.perf_counter()
        if self._cancelled:
            state.status = WorkflowStatus.CANCELLED
        elif coordinator_result.success:
            state.status = WorkflowStatus.COMPLETED
        else:
            state.status = WorkflowStatus.FAILED

        self.logger.info(
            "Workflow finished: id=%s status=%s steps_done=%d/%d duration_ms=%.1f",
            workflow_id, state.status, state.completed_count, state.step_count,
            state.duration_ms,
        )

        coordinator_result.workflow_state = state
        return coordinator_result

    def execute_step(self, task: AgentTask) -> AgentResult:
        """Delegate exactly one task to the existing ExecutionEngine."""
        try:
            engine_result = self.execution_engine.execute([task], self._request_id)
        except Exception as exc:
            return AgentResult(
                success=False,
                message=str(exc),
                data={"task_id": task.id, "agent": task.agent, "action": task.action},
                error="unexpected_exception",
            )

        if all(hasattr(engine_result, field) for field in ("success", "message", "data", "error")):
            return AgentResult(
                success=bool(engine_result.success),
                message=str(engine_result.message),
                data=engine_result.data,
                error=str(engine_result.error or ""),
            )

        message = str(engine_result)
        success = task.status == "completed"
        return AgentResult(
            success=success,
            message=message,
            data={"task_id": task.id, "agent": task.agent, "action": task.action},
            error="" if success else self._task_error(task, message),
        )

    @staticmethod
    def handle_failure(result: AgentResult) -> bool:
        """Identify a failed Engine result for sequential-plan control flow."""
        return not result.success

    def update_context(self, result: AgentResult) -> SharedContext | Any:
        """Synchronize the coordinator view with Engine-maintained context."""
        try:
            self.shared_context = getattr(self.execution_engine, "context", self.shared_context)
        except Exception as exc:
            self.logger.warning("Unable to synchronize SharedContext: %s", exc)
        return self.shared_context

    def cancel_plan(self) -> None:
        """Request cancellation before the next planned task starts."""
        self._cancelled = True

    def _verification_task(self, task: AgentTask) -> AgentTask | None:
        """Create a single Vision verification task for a qualifying browser step.

        Expected verification text is resolved in priority order:
        1. Per-task override via ``verification_text`` parameter.
        2. Param-derived text for ``open`` (name/site) and ``search`` (query).
        3. Default from ``_VERIFICATION_CRITERIA`` class mapping.
        """
        if task.agent != "BrowserAgent" or getattr(self.execution_engine, "vision", None) is None:
            return None
        params = task.parameters or {}
        if not params.get("verify", task.action in self._VERIFICATION_CRITERIA):
            return None

        # Priority 1: explicit per-task override
        expected_text = params.get("verification_text", "")

        # Priority 2: param-derived text (open / search)
        if not expected_text:
            if task.action == "open":
                expected_text = params.get("name", "") or params.get("site", "")
            elif task.action == "search":
                expected_text = params.get("query", "")

        # Priority 3: centralized default from _VERIFICATION_CRITERIA
        if not expected_text:
            expected_text = self._VERIFICATION_CRITERIA.get(task.action, "")

        if not expected_text:
            return None

        return AgentTask(
            agent="VisionAgent",
            action="find_text",
            parameters={
                "text": str(expected_text),
                "critical": params.get("verification_critical", True),
                "verification_for": task.action,
            },
        )

    @staticmethod
    def _task_error(task: AgentTask, message: str) -> str:
        """Retain task-provided errors and classify only unstructured output."""
        task_error = getattr(task, "error", "")
        if task_error:
            return str(task_error)
        normalized = message.lower()
        if "result" in normalized and "not found" in normalized:
            return "result_not_found"
        if "timeout" in normalized or "timed out" in normalized:
            return "timeout"
        if "permission" in normalized or "access is denied" in normalized:
            return "permission_denied"
        return message

from __future__ import annotations

import threading
import uuid
from typing import Any

from .budget import CognitiveBudgetManager
from .capabilities import CapabilityRegistry
from .memory import StructuredMemory
from .models import (
    AgentEvent,
    CapabilityResult,
    EventStatus,
    ExecutionPath,
    ResidentRunResult,
    WorkingState,
)
from .runtime import ZNKernelRuntime


class ZNResidentRuntime:
    """Long-lived, restart-safe resident agent runtime.

    System 1 is deterministic and token-free: structured memory plus compiled
    local capabilities. System 2 is the model-backed ZN Kernel and is invoked
    only when System 1 cannot solve the event and the cognitive budget permits
    it. The resident itself remains alive even when no System 2 model exists.
    """

    def __init__(
        self,
        *,
        kernel: ZNKernelRuntime,
        capabilities: CapabilityRegistry | None = None,
        budget: CognitiveBudgetManager | None = None,
    ):
        self.kernel = kernel
        self.store = kernel.store
        self.identity = kernel.identity
        self.capabilities = capabilities or CapabilityRegistry()
        self.budget = budget or CognitiveBudgetManager()
        self.memory = StructuredMemory(self.store)
        self.store.recover_interrupted_events()
        self.store.get_working_state()

    def enqueue(
        self,
        task: str,
        *,
        kind: str = "user_task",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        if not task or not task.strip():
            raise ValueError("task must not be empty")
        event = AgentEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            task=task.strip(),
            kind=str(kind or "user_task").strip() or "user_task",
            priority=int(priority),
            payload=dict(payload or {}),
        )
        self.store.enqueue_event(event)
        return event

    def submit(
        self,
        task: str,
        *,
        kind: str = "user_task",
        priority: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> ResidentRunResult:
        event = self.enqueue(task, kind=kind, priority=priority, payload=payload)
        while True:
            result = self.run_once()
            if result is None:
                raise RuntimeError("resident event was enqueued but could not be processed")
            if result.event.event_id == event.event_id:
                return result

    def run_once(self) -> ResidentRunResult | None:
        event = self.store.claim_next_event()
        if event is None:
            return None
        state = WorkingState(
            current_event_id=event.event_id,
            stage="orient",
            next_action="resolve_system1",
            data={"event_kind": event.kind, "event_attempt": event.attempts},
        )
        self.store.save_working_state(state)

        try:
            result = self._handle_event(event, state)
            self.store.finish_event(
                event.event_id,
                success=result.success,
                error=None if result.success else (result.reason or "event failed"),
            )
            persisted = self.store.get_event(event.event_id)
            if persisted is not None:
                result.event = persisted
            return result
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.store.finish_event(event.event_id, success=False, error=message)
            self.store.record_runtime_task(model_invocations=0)
            persisted = self.store.get_event(event.event_id) or event
            return ResidentRunResult(
                event=persisted,
                execution_path=ExecutionPath.BUDGET_BLOCKED,
                success=False,
                reason=message,
            )
        finally:
            self.store.save_working_state(WorkingState(stage="idle"))

    def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        stopper = stop_event or threading.Event()
        sleep_for = max(0.05, float(poll_interval))
        while not stopper.is_set():
            result = self.run_once()
            if result is None:
                stopper.wait(sleep_for)

    def load_promoted_capabilities(self, root=None):
        from .capability_loader import PromotedCapabilityLoader

        return PromotedCapabilityLoader(root).load_into(self.capabilities)

    def status(self) -> dict[str, Any]:
        metrics = self.store.get_runtime_metrics()
        return {
            "identity": {
                "name": self.identity.name,
                "version": self.identity.version,
                "created_at": self.identity.created_at,
            },
            "working_state": self.store.get_working_state(),
            "queue_depth": len(self.store.list_events(EventStatus.PENDING, limit=10000)),
            "model_dependency": {
                "tasks_total": metrics.tasks_total,
                "tasks_model": metrics.tasks_model,
                "model_invocations": metrics.model_invocations,
                "ratio": metrics.model_dependency_ratio,
                "prompt_tokens": metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens,
            },
            "local_capabilities": self.capabilities.names(),
            "resident_lease": self.store.get_resident_lease(),
        }

    def _handle_event(self, event: AgentEvent, state: WorkingState) -> ResidentRunResult:
        memory_match = None
        if bool(event.payload.get("allow_memory", True)):
            memory_match = self.memory.recall(event.task)
        if memory_match is not None:
            state.stage = "system1_memory"
            state.next_action = "complete"
            self.store.save_working_state(state)
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MEMORY,
                success=True,
                response=self._render_memory_value(memory_match.value),
                reason=f"recalled structured fact '{memory_match.key}'",
            )

        resolved = self.capabilities.resolve(event)
        if resolved is not None:
            capability, confidence = resolved
            state.stage = "system1_capability"
            state.next_action = capability.name
            state.data["capability_match"] = confidence
            self.store.save_working_state(state)
            try:
                local_result = capability.execute(event, state)
            except Exception as exc:
                local_result = CapabilityResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if local_result.success:
                self.store.record_runtime_task(model_invocations=0)
                return ResidentRunResult(
                    event=event,
                    execution_path=ExecutionPath.CAPABILITY,
                    success=True,
                    response=local_result.response,
                    capability_name=capability.name,
                    reason="resolved by compiled local capability",
                )
            state.data["local_failure"] = local_result.error or "local capability failed"
            self.store.save_working_state(state)

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BUDGET_BLOCKED,
                success=False,
                reason=decision.reason,
            )

        state.stage = "system2_model"
        state.next_action = "invoke_model_worker"
        state.data["cognitive_budget"] = {
            "max_model_calls": decision.max_model_calls,
            "reason": decision.reason,
        }
        self.store.save_working_state(state)

        required = event.payload.get("required_capabilities") or ("general",)
        if isinstance(required, str):
            required = (required,)
        else:
            required = tuple(str(item) for item in required if str(item).strip()) or ("general",)

        kernel_result = self.kernel.run_goal(
            event.task,
            required_capabilities=required,
            priority=event.priority,
            metadata={"resident_event_id": event.event_id, **dict(event.payload)},
            max_attempts_override=decision.max_model_calls,
        )
        invocations = sum(
            1
            for experience in kernel_result.experiences
            if experience.metrics.get("model_invoked", True) is not False
        )
        prompt_tokens, completion_tokens = self._sum_tokens(kernel_result)
        self.store.record_runtime_task(
            model_invocations=invocations,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        state.current_goal_id = kernel_result.goal.goal_id
        state.stage = "complete" if kernel_result.assessment.success else "failed"
        state.next_action = None
        self.store.save_working_state(state)
        reason = decision.reason
        if not kernel_result.assessment.success and kernel_result.worker_result.error:
            reason = kernel_result.worker_result.error
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=kernel_result.assessment.success,
            response=kernel_result.worker_result.response,
            model_invocations=invocations,
            reason=reason,
            kernel_result=kernel_result,
        )

    @staticmethod
    def _render_memory_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _sum_tokens(kernel_result) -> tuple[int, int]:
        prompt = 0
        completion = 0
        for experience in kernel_result.experiences:
            metrics = experience.metrics or {}
            usage = metrics.get("usage") if isinstance(metrics.get("usage"), dict) else metrics
            for key in ("prompt_tokens", "input_tokens"):
                try:
                    prompt += max(0, int(usage.get(key, 0)))
                    if usage.get(key) is not None:
                        break
                except (TypeError, ValueError, AttributeError):
                    continue
            for key in ("completion_tokens", "output_tokens"):
                try:
                    completion += max(0, int(usage.get(key, 0)))
                    if usage.get(key) is not None:
                        break
                except (TypeError, ValueError, AttributeError):
                    continue
        return prompt, completion

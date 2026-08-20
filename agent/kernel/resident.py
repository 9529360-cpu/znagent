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

    The resident owns the continuous ZN self. Structured memory, local
    capabilities and external models are abilities available to that self; none
    of them is the identity itself. The resident remains alive when no model is
    configured.

    ``live_once`` is the normal control entry point: ZN senses and forms a
    ThoughtFrame first, then the body executes the action selected by that
    thought. ``run_once`` remains the lower-level event executor.
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
        self._cycle_lock = threading.RLock()
        self.store.recover_interrupted_events()
        self.store.get_working_state()

        from .life import ZNLifeCore

        self.life = ZNLifeCore(self)
        self.life.wake()

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
            result = self.live_once()
            if result is None:
                persisted = self.store.get_event(event.event_id)
                if persisted is not None and persisted.status in {
                    EventStatus.COMPLETED,
                    EventStatus.FAILED,
                }:
                    raise RuntimeError(
                        "resident event reached a terminal state without a run result"
                    )
                continue
            if result.event.event_id == event.event_id:
                return result

    def pulse(self):
        return self.life.pulse()

    def live_once(self) -> ResidentRunResult | None:
        """Let ZN think once and execute exactly the action it selected."""
        with self._cycle_lock:
            pulse = self.pulse()
            thought = pulse.thought
            if thought is None:
                return None

            if thought.action_kind == "event" and thought.action_target:
                return self.run_once(
                    thought=thought,
                    target_event_id=thought.action_target,
                )

            # Impasse inspection, reflection, recovery and body inspection are
            # native internal actions. They do not silently escalate to a model
            # or mutate the computer until ZN has a concrete action path.
            return None

    def run_once(
        self,
        *,
        thought=None,
        target_event_id: str | None = None,
    ) -> ResidentRunResult | None:
        """Execute one pending event as a low-level body action."""
        event = (
            self.store.claim_event(target_event_id)
            if target_event_id
            else self.store.claim_next_event()
        )
        if event is None:
            return None

        thought_data: dict[str, Any] = {}
        if thought is not None:
            thought_data = {
                "thought_sequence": getattr(thought, "sequence", None),
                "thought_focus": getattr(thought, "focus", None),
                "thought_action": getattr(thought, "chosen_action", None),
                "thought_action_kind": getattr(thought, "action_kind", None),
                "thought_action_target": getattr(thought, "action_target", None),
                "thought_reason": getattr(thought, "reason", None),
                "thought_confidence": getattr(thought, "confidence", None),
            }

        state = WorkingState(
            current_event_id=event.event_id,
            stage="orient",
            next_action=(
                str(getattr(thought, "chosen_action", "") or "resolve_system1")
                if thought is not None
                else "resolve_system1"
            ),
            data={
                "event_kind": event.kind,
                "event_attempt": event.attempts,
                **thought_data,
            },
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
            self.life.observe_action(result)
            return result
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.life.mark_impasse_unresolved(event, message)
            self.store.finish_event(event.event_id, success=False, error=message)
            self.store.record_runtime_task(model_invocations=0)
            persisted = self.store.get_event(event.event_id) or event
            result = ResidentRunResult(
                event=persisted,
                execution_path=ExecutionPath.BUDGET_BLOCKED,
                success=False,
                reason=message,
            )
            self.life.observe_action(result)
            return result
        finally:
            self.store.save_working_state(WorkingState(stage="idle"))

    def run_forever(
        self,
        *,
        poll_interval: float = 1.0,
        pulse_interval: float = 2.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        stopper = stop_event or threading.Event()
        sleep_for = max(0.05, float(poll_interval))
        cycle_every = max(0.25, float(pulse_interval))
        import time

        next_cycle = 0.0
        while not stopper.is_set():
            now = time.monotonic()
            if now >= next_cycle:
                self.live_once()
                next_cycle = now + cycle_every
            stopper.wait(min(sleep_for, max(0.05, next_cycle - time.monotonic())))

    def load_promoted_capabilities(self, root=None):
        from .capability_loader import PromotedCapabilityLoader

        return PromotedCapabilityLoader(root).load_into(self.capabilities)

    def status(self) -> dict[str, Any]:
        metrics = self.store.get_runtime_metrics()
        profile = self.kernel.self_model.profile()
        return {
            "identity": {
                "name": self.identity.name,
                "version": self.identity.version,
                "created_at": self.identity.created_at,
            },
            "self": self.life.snapshot_dict(),
            "self_model": {
                key: [
                    {
                        "domain": estimate.name,
                        "score": estimate.score,
                        "evidence_count": estimate.evidence_count,
                        "confidence": estimate.confidence,
                        "updated_at": estimate.updated_at,
                    }
                    for estimate in values
                ]
                for key, values in profile.items()
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

    @staticmethod
    def _required_capabilities(event: AgentEvent) -> tuple[str, ...]:
        required = event.payload.get("required_capabilities") or ("general",)
        if isinstance(required, str):
            return (required,)
        return tuple(
            str(item) for item in required if str(item).strip()
        ) or ("general",)

    def _handle_event(self, event: AgentEvent, state: WorkingState) -> ResidentRunResult:
        required = self._required_capabilities(event)
        memory_match = None
        if bool(event.payload.get("allow_memory", True)):
            memory_match = self.memory.recall(event.task)
        if memory_match is not None:
            state.stage = "native_memory"
            state.next_action = "complete"
            self.store.save_working_state(state)
            self.kernel.self_model.observe_knowledge_use(
                event.task,
                required,
                quality=1.0,
            )
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MEMORY,
                success=True,
                response=self._render_memory_value(memory_match.value),
                reason=f"recalled structured fact '{memory_match.key}'",
            )

        local_failure: str | None = None
        resolved = self.capabilities.resolve(event)
        if resolved is not None:
            capability, confidence = resolved
            state.stage = "native_capability"
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
                domains = self.kernel.self_model.observe_native_outcome(
                    event.task,
                    required,
                    success=True,
                    quality=max(0.5, min(1.0, float(confidence))),
                )
                state.data["native_domains"] = list(domains)
                self.store.save_working_state(state)
                self.store.record_runtime_task(model_invocations=0)
                return ResidentRunResult(
                    event=event,
                    execution_path=ExecutionPath.CAPABILITY,
                    success=True,
                    response=local_result.response,
                    capability_name=capability.name,
                    reason="resolved by compiled local capability",
                )
            self.kernel.self_model.observe_native_outcome(
                event.task,
                required,
                success=False,
            )
            local_failure = local_result.error or "local capability failed"
            state.data["local_failure"] = local_failure
            self.store.save_working_state(state)

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        impasse = self.life.begin_impasse(
            event,
            reason=(
                local_failure
                or "native memory and compiled capabilities could not resolve this event"
            ),
            required_capabilities=required,
            local_failure=local_failure,
        )
        state.data["impasse_id"] = impasse.impasse_id
        state.data["cognitive_budget"] = {
            "use_external_cognition": decision.use_model,
            "max_model_calls": decision.max_model_calls,
            "reason": decision.reason,
        }
        self.store.save_working_state(state)

        if not decision.use_model:
            self.life.mark_impasse_unresolved(event, decision.reason)
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BUDGET_BLOCKED,
                success=False,
                reason=decision.reason,
            )

        state.stage = "external_cognition"
        state.next_action = "consult_external_brain"
        self.store.save_working_state(state)

        kernel_result = self.kernel.run_goal(
            event.task,
            required_capabilities=required,
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "impasse_id": impasse.impasse_id,
                **dict(event.payload),
            },
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

        run = ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=kernel_result.assessment.success,
            response=kernel_result.worker_result.response,
            model_invocations=invocations,
            reason=reason,
            kernel_result=kernel_result,
        )
        if run.success:
            route_id = kernel_result.goal.route_id or "external"
            self.life.resolve_impasse(
                event,
                run,
                resolution_source=f"external:{route_id}",
            )
            domains = self.kernel.self_model.integrate_external_learning(
                event.task,
                required,
                quality=kernel_result.assessment.quality,
                confidence=kernel_result.assessment.confidence,
            )
            state.data["integrated_learning_domains"] = list(domains)
            self.store.save_working_state(state)
        else:
            self.life.mark_impasse_unresolved(event, reason)
        return run

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
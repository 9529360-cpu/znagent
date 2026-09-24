from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from .budget import CognitiveBudgetManager
from .capabilities import CapabilityRegistry
from .completion_observation import CompletionObservationJournal
from .investigation import InvestigationResult, NativeInvestigator
from .memory import StructuredMemory
from .models import (
    AgentEvent,
    CapabilityResult,
    CognitionRequest,
    EventOutcome,
    EventStatus,
    ExecutionPath,
    ResidentRunResult,
    WorkingState,
)
from .runtime import ZNKernelRuntime
from .self_model import TaskReadiness


class ZNResidentRuntime:
    """Long-lived, restart-safe resident agent runtime.

    ZN owns the continuing self. Memory, body abilities and external models are
    resources available to it; none of them is the identity itself.

    Normal resident execution advances one cognitive/body step per life pulse:
    sense -> situation -> thought -> orient/investigate/deliberate/act -> new
    evidence -> next thought. External cognition is only another later step
    after native investigation can no longer derive a useful local probe.
    """

    _ACTIVE_THOUGHT_KINDS = {
        "event",
        "investigate",
        "deliberate",
        "external_cognition",
    }

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
        self.completion_observations = CompletionObservationJournal(self.store)
        self.completion_observations.repair_life(self)
        self.investigator = NativeInvestigator(self)

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

    def result_for(self, event_id: str) -> ResidentRunResult | None:
        """Reconstruct a completed action result regardless of which loop ran it."""
        outcome = self.store.get_event_outcome(event_id)
        event = self.store.get_event(event_id)
        if outcome is None or event is None:
            return None
        return ResidentRunResult(
            event=event,
            execution_path=outcome.execution_path,
            success=outcome.success,
            response=outcome.response,
            model_invocations=outcome.model_invocations,
            capability_name=outcome.capability_name,
            reason=outcome.reason,
            kernel_result=None,
            cancelled=outcome.cancelled,
        )

    def request_event_cancellation(
        self,
        event_id: str,
        *,
        reason: str = "user requested Work stop",
    ) -> dict[str, str]:
        """Persist a cooperative stop request without guessing about in-flight effects."""

        return self.store.request_event_cancellation(event_id, reason=reason)

    def _requested_cancellation_result(
        self,
        event: AgentEvent,
    ) -> ResidentRunResult | None:
        request = self.store.get_event_cancellation_request(event.event_id)
        if request is None:
            return None
        reason = str(request.get("reason") or "user requested Work stop")

        state = self.store.get_working_state()
        if (
            str(state.current_event_id or "") == event.event_id
            and str(state.stage or "").strip().lower() == "side_effect_recovery"
            and str(state.blocked_by or "").strip().lower()
            == "outside_world_effect_uncertain"
        ):
            cancel_uncertain = getattr(self, "cancel_uncertain_event", None)
            if not callable(cancel_uncertain):
                raise RuntimeError(
                    "resident cannot safely cancel an uncertain outside-world effect"
                )
            run = cancel_uncertain(event.event_id, reason=reason)
            self.store.clear_event_cancellation_request(event.event_id)
            return run

        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.CONTROL,
            success=False,
            response="Work stopped.",
            reason=reason,
            cancelled=True,
        )

    def repair_completion_observations(self, *, limit: int = 128) -> int:
        """Retry resident self-observation without reopening completed Work."""
        return self.completion_observations.repair_life(self, limit=limit)

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
            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed

            result = self.live_once()
            if result is not None and result.event.event_id == event.event_id:
                return result

            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed

            persisted = self.store.get_event(event.event_id)
            if persisted is not None and persisted.status in {
                EventStatus.COMPLETED,
                EventStatus.FAILED,
            }:
                raise RuntimeError(
                    "resident event reached a terminal state without a durable outcome"
                )

    def pulse(self):
        return self.life.pulse()

    def live_once(self) -> ResidentRunResult | None:
        """Form one Thought and advance exactly one resident cognition step."""
        with self._cycle_lock:
            pulse = self.pulse()
            thought = pulse.thought
            if thought is None:
                return None

            if thought.action_kind not in self._ACTIVE_THOUGHT_KINDS:
                return None
            if not thought.action_target:
                return None

            event = self.store.get_event(thought.action_target)
            if event is None or event.status in {EventStatus.COMPLETED, EventStatus.FAILED}:
                return None

            required = self._required_capabilities(event)
            readiness = self.kernel.self_model.assess_task(event.task, required)
            learning_evidence = self._related_learning_evidence(event, readiness)
            self._enrich_thought_with_readiness(
                thought,
                readiness,
                learning_evidence,
            )
            self._enrich_thought_with_working_stage(thought, event)
            self._persist_enriched_thought(thought)
            return self.run_once(
                thought=thought,
                target_event_id=event.event_id,
                readiness=readiness,
                learning_evidence=learning_evidence,
            )

    def run_once(
        self,
        *,
        thought=None,
        target_event_id: str | None = None,
        readiness: TaskReadiness | None = None,
        learning_evidence: list[dict[str, Any]] | None = None,
    ) -> ResidentRunResult | None:
        """Advance an event.

        Calls coming from ``live_once`` advance exactly one stage. Direct legacy
        calls without a Thought keep driving the same event to a terminal result,
        while still forming fresh native Thoughts between internal stages.
        """
        event = (
            self.store.claim_event(target_event_id)
            if target_event_id
            else self.store.claim_next_event()
        )
        if event is None:
            return None

        requested_cancel = self._requested_cancellation_result(event)
        if requested_cancel is not None:
            durable_cancel = self.result_for(event.event_id)
            if durable_cancel is not None and durable_cancel.cancelled:
                return durable_cancel
            return self._complete_result(event, requested_cancel)

        drive_to_terminal = thought is None
        required = self._required_capabilities(event)
        if readiness is None:
            readiness = self.kernel.self_model.assess_task(event.task, required)
        if learning_evidence is None:
            learning_evidence = self._related_learning_evidence(event, readiness)

        state = self._state_for_event(
            event,
            thought=thought,
            readiness=readiness,
            learning_evidence=learning_evidence,
        )

        try:
            while True:
                requested_cancel = self._requested_cancellation_result(event)
                if requested_cancel is not None:
                    durable_cancel = self.result_for(event.event_id)
                    if durable_cancel is not None and durable_cancel.cancelled:
                        return durable_cancel
                    return self._complete_result(event, requested_cancel)

                result = self._advance_event_step(
                    event,
                    state,
                    readiness=readiness,
                    learning_evidence=learning_evidence,
                    thought=thought,
                )

                requested_cancel = self._requested_cancellation_result(event)
                if requested_cancel is not None:
                    durable_cancel = self.result_for(event.event_id)
                    if durable_cancel is not None and durable_cancel.cancelled:
                        return durable_cancel
                    return self._complete_result(event, requested_cancel)
                if result is not None:
                    return self._complete_result(event, result)
                if not drive_to_terminal:
                    return None

                pulse = self.pulse()
                thought = pulse.thought
                required = self._required_capabilities(event)
                readiness = self.kernel.self_model.assess_task(event.task, required)
                learning_evidence = self._related_learning_evidence(event, readiness)
                if thought is not None:
                    self._enrich_thought_with_readiness(
                        thought,
                        readiness,
                        learning_evidence,
                    )
                    self._enrich_thought_with_working_stage(thought, event)
                    self._persist_enriched_thought(thought)
                state = self.store.get_working_state()
                self._update_state_context(
                    state,
                    event,
                    thought=thought,
                    readiness=readiness,
                    learning_evidence=learning_evidence,
                )
                self.store.save_working_state(state)
        except Exception as exc:
            completed = self.result_for(event.event_id)
            if completed is not None:
                return completed
            current = self.store.get_working_state()
            if self._preserve_working_truth_on_exception(event, current):
                raise
            message = f"{type(exc).__name__}: {exc}"
            self.life.mark_impasse_unresolved(event, message)
            failure = self._checkpoint_terminal_failure(
                event,
                current,
                reason=message,
            )
            return self._complete_result(event, failure)

    def _state_for_event(
        self,
        event: AgentEvent,
        *,
        thought,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
    ) -> WorkingState:
        current = self.store.get_working_state()
        if (
            current.current_event_id == event.event_id
            and current.stage not in {"idle", "complete", "failed"}
        ):
            state = current
        else:
            state = WorkingState(
                current_event_id=event.event_id,
                stage="orient",
                next_action="orient to current event",
                data={},
            )
        self._update_state_context(
            state,
            event,
            thought=thought,
            readiness=readiness,
            learning_evidence=learning_evidence,
        )
        self.store.save_working_state(state)
        return state

    def _update_state_context(
        self,
        state: WorkingState,
        event: AgentEvent,
        *,
        thought,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
    ) -> None:
        state.current_event_id = event.event_id
        state.data["event_kind"] = event.kind
        state.data["event_attempt"] = event.attempts
        state.data["self_readiness"] = self._readiness_data(readiness)
        state.data["related_learning"] = learning_evidence
        if thought is not None:
            state.data.update(
                {
                    "thought_sequence": getattr(thought, "sequence", None),
                    "thought_focus": getattr(thought, "focus", None),
                    "thought_action": getattr(thought, "chosen_action", None),
                    "thought_action_kind": getattr(thought, "action_kind", None),
                    "thought_action_target": getattr(thought, "action_target", None),
                    "thought_reason": getattr(thought, "reason", None),
                    "thought_confidence": getattr(thought, "confidence", None),
                }
            )

    def _complete_result(
        self,
        event: AgentEvent,
        result: ResidentRunResult,
    ) -> ResidentRunResult:
        outcome = EventOutcome(
            event_id=event.event_id,
            success=result.success,
            execution_path=result.execution_path,
            response=result.response,
            model_invocations=result.model_invocations,
            capability_name=result.capability_name,
            reason=result.reason,
            cancelled=result.cancelled,
        )
        result.event = self.store.complete_event(
            outcome,
            error=None if result.success or result.cancelled else (result.reason or "event failed"),
        )

        durable = self.store.get_event_outcome(event.event_id)
        if durable is None:
            raise RuntimeError("resident terminal transition did not publish a durable outcome")
        result.success = durable.success
        result.cancelled = durable.cancelled
        result.execution_path = durable.execution_path
        result.response = durable.response
        result.model_invocations = durable.model_invocations
        result.capability_name = durable.capability_name
        result.reason = durable.reason

        if not result.cancelled:
            self.completion_observations.observe_life(self, result)
        return result

    @staticmethod
    def _preserve_working_truth_on_exception(
        event: AgentEvent,
        state: WorkingState,
    ) -> bool:
        if str(state.current_event_id or "") != str(event.event_id):
            return False
        stage = str(state.stage or "").strip().lower()
        blocked_by = str(state.blocked_by or "").strip().lower()
        if blocked_by == "outside_world_effect_uncertain" or stage == "side_effect_recovery":
            return True
        if stage in {"complete", "failed", "terminal_failure"}:
            return True
        return stage.endswith("_completion")

    def _resident_accounting_journal(self):
        journal = getattr(self, "resident_accounting", None)
        if journal is None:
            from .resident_accounting import ResidentAccountingJournal

            journal = ResidentAccountingJournal(self.store)
            self.resident_accounting = journal
        return journal

    def _checkpoint_terminal_failure(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        reason: str,
    ) -> ResidentRunResult:
        completion = {
            "execution_path": ExecutionPath.BUDGET_BLOCKED.value,
            "success": False,
            "response": None,
            "model_invocations": 0,
            "reason": str(reason or "resident task failed"),
        }
        state.current_event_id = event.event_id
        state.stage = "terminal_failure"
        state.next_action = "publish terminal EventOutcome"
        state.data["terminal_failure"] = {
            **completion,
            "native_action_failure_records": list(
                state.data.get("native_action_failure_records") or []
            )[-8:],
        }
        self.store.save_working_state(state)
        self._resident_accounting_journal().record_terminal_failure(
            event_id=event.event_id,
            model_invocations=0,
        )
        return self._terminal_failure_result(event, completion)

    def _resume_terminal_failure(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult:
        raw = state.data.get("terminal_failure")
        if not isinstance(raw, dict):
            raise RuntimeError("durable terminal failure checkpoint is incomplete")
        try:
            result = self._terminal_failure_result(event, raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("durable terminal failure checkpoint is malformed") from exc
        self._resident_accounting_journal().record_terminal_failure(
            event_id=event.event_id,
            model_invocations=0,
        )
        return result

    @staticmethod
    def _terminal_failure_result(
        event: AgentEvent,
        raw: dict[str, Any],
    ) -> ResidentRunResult:
        if raw.get("success") is not False:
            raise ValueError("terminal failure checkpoint must record failure")
        execution_path = ExecutionPath(str(raw.get("execution_path") or ""))
        if execution_path is not ExecutionPath.BUDGET_BLOCKED:
            raise ValueError("terminal failure checkpoint must use budget-blocked path")
        model_invocations = raw.get("model_invocations")
        if isinstance(model_invocations, bool) or int(model_invocations) != 0:
            raise ValueError("terminal failure checkpoint cannot claim model use")
        return ResidentRunResult(
            event=event,
            execution_path=execution_path,
            success=False,
            response=raw.get("response"),
            model_invocations=0,
            reason=str(raw.get("reason") or "resident task failed"),
        )

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
        latest_investigation = self.investigator.recent(1)
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
            "latest_investigation": (
                self._investigation_data(latest_investigation[0])
                if latest_investigation
                else None
            ),
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

    @staticmethod
    def _readiness_data(readiness: TaskReadiness) -> dict[str, Any]:
        return {
            "domains": list(readiness.domains),
            "knowledge_score": readiness.knowledge_score,
            "ability_score": readiness.ability_score,
            "knowledge_confidence": readiness.knowledge_confidence,
            "ability_confidence": readiness.ability_confidence,
            "posture": readiness.posture,
            "reason": readiness.reason,
            "domain_states": [
                {
                    "domain": item.domain,
                    "knowledge_score": item.knowledge_score,
                    "knowledge_evidence": item.knowledge_evidence,
                    "knowledge_confidence": item.knowledge_confidence,
                    "ability_score": item.ability_score,
                    "ability_evidence": item.ability_evidence,
                    "ability_confidence": item.ability_confidence,
                }
                for item in readiness.domain_states
            ],
        }

    @staticmethod
    def _investigation_data(state) -> dict[str, Any]:
        return {
            "investigation_id": state.investigation_id,
            "event_id": state.event_id,
            "task": state.task,
            "domains": list(state.domains),
            "hypotheses": list(state.hypotheses),
            "probes": list(state.probes),
            "probe_keys": list(state.probe_keys),
            "evidence": list(state.evidence),
            "unresolved": state.unresolved,
            "next_probe": state.next_probe,
            "rounds": state.rounds,
            "status": state.status,
            "resolution": state.resolution,
            "updated_at": state.updated_at,
        }

    @staticmethod
    def _task_tokens(value: str) -> set[str]:
        text = str(value or "").lower()
        return {
            token
            for token in re.findall(r"[a-z0-9_+.-]{2,}|[\u4e00-\u9fff]{2,}", text)
            if token
        }

    def _related_learning_evidence(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Recall a bounded amount of relevant experience entirely resident-side."""
        current_tokens = self._task_tokens(event.task)
        current_domains = set(readiness.domains)
        ranked: list[tuple[float, Any, tuple[str, ...]]] = []

        for candidate in self.life.recent_learning_candidates(64):
            if candidate.event_id == event.event_id:
                continue
            candidate_domains = self.kernel.self_model.infer_domains(
                candidate.task,
                candidate.required_capabilities,
            )
            domain_overlap = current_domains.intersection(candidate_domains)
            if not domain_overlap:
                continue

            candidate_tokens = self._task_tokens(candidate.task)
            union = current_tokens.union(candidate_tokens)
            lexical = (
                len(current_tokens.intersection(candidate_tokens)) / len(union)
                if union
                else 0.0
            )
            domain_score = len(domain_overlap) / max(
                1,
                len(current_domains.union(candidate_domains)),
            )
            score = (0.65 * lexical) + (0.35 * domain_score)
            if score < 0.12:
                continue
            ranked.append((score, candidate, candidate_domains))

        ranked.sort(key=lambda item: item[0], reverse=True)
        evidence: list[dict[str, Any]] = []
        for score, candidate, candidate_domains in ranked[: max(1, int(limit))]:
            evidence.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "similarity": round(score, 4),
                    "domains": list(candidate_domains),
                    "task": candidate.task[:240],
                    "resolution_summary": candidate.resolution_summary[:320],
                    "resolution_source": candidate.resolution_source,
                }
            )
        return evidence

    @staticmethod
    def _enrich_thought_with_readiness(
        thought,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
    ) -> None:
        domain_text = ", ".join(readiness.domains)
        readiness_text = (
            f"task domains: {domain_text}; posture={readiness.posture}; "
            f"knowledge={readiness.knowledge_score:.2f}; "
            f"independent ability={readiness.ability_score:.2f}"
        )
        if readiness_text not in thought.known:
            thought.known = (*thought.known, readiness_text)
        if learning_evidence:
            evidence_text = f"I remember {len(learning_evidence)} related prior learning record(s)"
            if evidence_text not in thought.known:
                thought.known = (*thought.known, evidence_text)

        gap = None
        if readiness.posture == "familiar" and readiness.ability_score < 0.6:
            gap = (
                "I understand relevant parts of this domain better than I can "
                "execute this task independently"
            )
        elif readiness.posture == "partial":
            gap = "my retained understanding of the relevant domain is incomplete"
        elif readiness.posture == "novel":
            gap = "I have little retained knowledge for the relevant domain"
        if gap and gap not in thought.unknown:
            thought.unknown = (*thought.unknown, gap)

        thought.reason = f"{readiness.reason}; {thought.reason}"

    def _enrich_thought_with_working_stage(self, thought, event: AgentEvent) -> None:
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return

        if state.stage == "native_investigation":
            investigation = self.investigator.current(event.event_id)
            if investigation is None:
                action = "begin native investigation"
                thought.reason = f"{thought.reason}; concrete local evidence has not been collected yet"
            else:
                known = (
                    f"native investigation rounds={investigation.rounds}; "
                    f"evidence={len(investigation.evidence)}"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                if investigation.unresolved and investigation.unresolved not in thought.unknown:
                    thought.unknown = (*thought.unknown, investigation.unresolved)
                if investigation.next_probe:
                    action = f"run native probe: {investigation.next_probe}"
                else:
                    action = "evaluate accumulated native evidence"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "investigate"
            thought.action_target = event.event_id
            thought.reason = f"{thought.reason}; continue evidence-driven native investigation"
            return

        if state.stage == "native_deliberation":
            action = "integrate native evidence and identify the remaining gap"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "deliberate"
            thought.action_target = event.event_id
            thought.reason = f"{thought.reason}; native probes are exhausted for the current hypothesis set"
            return

        if state.stage == "external_cognition":
            cognition = state.data.get("cognition_request")
            question = cognition.get("question") if isinstance(cognition, dict) else None
            if question and str(question) not in thought.unknown:
                thought.unknown = (*thought.unknown, str(question))
            action = "consult an external cognitive resource for the isolated gap"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "external_cognition"
            thought.action_target = event.event_id
            thought.reason = f"{thought.reason}; native cognition isolated a specific unresolved gap"

    def _persist_enriched_thought(self, thought) -> None:
        state = self.life.snapshot()
        state.current_thought = thought
        state.attention = None if thought.focus == "environment" else thought.focus
        state.intention = thought.chosen_action
        self.life._save_state(state)
        self.life._append_thought(thought)
        self.life._state = state

    @staticmethod
    def _merge_investigation_into_thought(
        thought,
        investigation: InvestigationResult,
    ) -> None:
        if thought is None:
            return
        count = len(investigation.state.evidence)
        if count:
            known = f"native investigation collected {count} concrete observation(s)"
            if known not in thought.known:
                thought.known = (*thought.known, known)
        if investigation.performed_probe:
            known = f"completed native probe: {investigation.performed_probe}"
            if known not in thought.known:
                thought.known = (*thought.known, known)
        for hypothesis in investigation.state.hypotheses[-3:]:
            action = f"test hypothesis: {hypothesis}"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
        if investigation.state.unresolved and investigation.state.unresolved not in thought.unknown:
            thought.unknown = (*thought.unknown, investigation.state.unresolved)
        if investigation.can_continue and investigation.state.next_probe:
            next_action = f"run native probe: {investigation.state.next_probe}"
            if next_action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, next_action)
        thought.reason = f"{thought.reason}; concrete evidence updated the current investigation"

    @staticmethod
    def _merge_deliberation_into_thought(
        thought,
        deliberation: dict[str, Any],
    ) -> None:
        if thought is None:
            return
        unknown = str(deliberation.get("unknown") or "").strip()
        if unknown and unknown not in thought.unknown:
            thought.unknown = (*thought.unknown, unknown)
        if deliberation.get("related_learning_count"):
            action = "compare current problem with related internal experience"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
        thought.reason = (
            f"{thought.reason}; native checks completed before any external cognition"
        )

    @staticmethod
    def _native_deliberation(
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        memory_checked: bool,
        local_capability_checked: bool,
        local_failure: str | None,
        learning_evidence: list[dict[str, Any]],
        investigation: InvestigationResult,
    ) -> dict[str, Any]:
        checks: list[str] = []
        if memory_checked:
            checks.append("structured memory did not directly answer the task")
        if local_failure:
            checks.append(f"local execution failed: {local_failure}")
        elif local_capability_checked:
            checks.append("no compiled local capability matched the task")
        if learning_evidence:
            checks.append(
                f"reviewed {len(learning_evidence)} related resident-side learning record(s)"
            )
        if investigation.state.probes:
            checks.append(
                f"ran {investigation.state.rounds} native investigation round(s)"
            )

        explicit = str(
            event.payload.get("cognition_question")
            or event.payload.get("unknown")
            or ""
        ).strip()
        if explicit:
            unknown = explicit
        elif local_failure:
            unknown = (
                "I inspected local state and need the smallest missing explanation or "
                f"procedure that resolves this specific failure: {local_failure}"
            )
        elif investigation.state.unresolved:
            unknown = investigation.state.unresolved
        elif readiness.posture == "familiar":
            unknown = (
                "I know the relevant domain and inspected concrete local state, but I "
                "do not yet have a verified native procedure for this case; identify "
                "the smallest missing step"
            )
        elif learning_evidence and readiness.posture == "partial":
            unknown = (
                "I remember related prior resolutions and inspected current local state, "
                "but I still need the smallest missing concept or procedure for this case"
            )
        elif readiness.posture == "partial":
            unknown = (
                "I recognize parts of the relevant domain, but I need the smallest "
                "missing concept or procedure required to make progress"
            )
        else:
            unknown = (
                "I have little retained knowledge for this domain; identify the first "
                "minimal concept or procedure needed to make progress"
            )

        return {
            "domains": list(readiness.domains),
            "posture": readiness.posture,
            "knowledge_score": readiness.knowledge_score,
            "ability_score": readiness.ability_score,
            "checks": checks,
            "related_learning_count": len(learning_evidence),
            "related_learning": learning_evidence,
            "investigation_id": investigation.state.investigation_id,
            "investigation_rounds": investigation.state.rounds,
            "investigation_evidence_count": len(investigation.state.evidence),
            "bounded_native_evidence": NativeInvestigator.bounded_evidence(investigation),
            "unknown": unknown,
            "next": "resolve the remaining gap and continue native action",
        }

    @staticmethod
    def _build_cognition_request(
        event: AgentEvent,
        impasse,
        required: tuple[str, ...],
        deliberation: dict[str, Any] | None = None,
    ) -> CognitionRequest:
        explicit = str(
            event.payload.get("cognition_question")
            or event.payload.get("unknown")
            or ""
        ).strip()
        context: dict[str, Any] = {"event_kind": event.kind}
        deliberation = dict(deliberation or {})

        if explicit:
            question = explicit
        elif deliberation.get("unknown"):
            question = str(deliberation["unknown"])
            checks = [str(item) for item in deliberation.get("checks") or () if str(item)]
            if checks:
                context["native_checks"] = checks[:6]
            native_evidence = [
                str(item)
                for item in deliberation.get("bounded_native_evidence") or ()
                if str(item).strip()
            ]
            if native_evidence:
                context["native_evidence"] = native_evidence[:6]
            context["task_excerpt"] = event.task[:500]
        elif impasse.local_failure:
            question = (
                "Explain how to resolve this specific failure: "
                f"{impasse.local_failure}"
            )
            context["task_excerpt"] = event.task[:500]
        else:
            question = event.task

        return CognitionRequest(
            request_id=f"cog-{uuid.uuid4().hex[:12]}",
            impasse_id=impasse.impasse_id,
            event_id=event.event_id,
            question=question,
            required_capabilities=required,
            context=context,
        )

    def _advance_event_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        if state.stage == "orient":
            return self._orient_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if state.stage == "resident_completion":
            return self._resume_resident_completion(event, state)
        if state.stage == "native_investigation":
            return self._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        if state.stage == "investigation_completion":
            return self._resume_investigation_completion(event, state)
        if state.stage == "native_deliberation":
            return self._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        if state.stage == "external_cognition":
            return self._external_cognition_step(event, state)
        if state.stage == "terminal_failure":
            return self._resume_terminal_failure(event, state)

        state.stage = "orient"
        state.next_action = "orient to current event"
        self.store.save_working_state(state)
        return None

    def _orient_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        required = self._required_capabilities(event)
        memory_checked = bool(event.payload.get("allow_memory", True))
        state.data["memory_checked"] = memory_checked
        memory_match = self.memory.recall(event.task) if memory_checked else None
        if memory_match is not None:
            response = self._render_memory_value(memory_match.value)
            reason = f"recalled structured fact '{memory_match.key}'"
            self.kernel.self_model.observe_knowledge_use(
                event.task,
                required,
                quality=1.0,
            )
            self.store.record_runtime_task(model_invocations=0)
            completion = {
                "execution_path": ExecutionPath.MEMORY.value,
                "success": True,
                "response": response,
                "model_invocations": 0,
                "reason": reason,
            }
            state.stage = "resident_completion"
            state.next_action = "publish terminal EventOutcome"
            state.data["resident_completion"] = completion
            # The memory answer and ordinary accounting are already established.
            # Once this checkpoint is durable, restart must publish only the
            # terminal outcome instead of recalling and accounting a second time.
            self.store.save_working_state(state)
            return self._resident_completion_result(event, completion)

        local_failure: str | None = None
        resolved = self.capabilities.resolve(event)
        state.data["local_capability_checked"] = True
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
                completion = {
                    "execution_path": ExecutionPath.CAPABILITY.value,
                    "success": True,
                    "response": local_result.response,
                    "model_invocations": 0,
                    "capability_name": capability.name,
                    "reason": "resolved by compiled local capability",
                }
                state.stage = "resident_completion"
                state.next_action = "publish terminal EventOutcome"
                state.data["native_domains"] = list(domains)
                state.data["resident_completion"] = completion
                self.store.record_runtime_task(model_invocations=0)
                # The capability has already returned success. Persist that fact
                # before EventOutcome so a restart never re-enters the compiled
                # capability merely to reconstruct an already-established result.
                self.store.save_working_state(state)
                return self._resident_completion_result(event, completion)
            self.kernel.self_model.observe_native_outcome(
                event.task,
                required,
                success=False,
            )
            local_failure = local_result.error or "local capability failed"
            state.data["local_failure"] = local_failure

        state.stage = "native_investigation"
        state.next_action = "select the next native probe"
        if thought is not None:
            action = "inspect concrete local state before declaring an impasse"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = f"{thought.reason}; orientation found no terminal native answer"
            self._persist_enriched_thought(thought)
        self.store.save_working_state(state)
        return None

    def _resume_resident_completion(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult:
        raw = state.data.get("resident_completion")
        if not isinstance(raw, dict):
            return self._invalid_resident_completion(
                event,
                "durable resident completion checkpoint is incomplete",
            )
        try:
            return self._resident_completion_result(event, raw)
        except (TypeError, ValueError):
            return self._invalid_resident_completion(
                event,
                "durable resident completion checkpoint is malformed",
            )

    @staticmethod
    def _invalid_resident_completion(
        event: AgentEvent,
        reason: str,
    ) -> ResidentRunResult:
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BUDGET_BLOCKED,
            success=False,
            model_invocations=0,
            reason=reason,
        )

    @staticmethod
    def _resident_completion_result(
        event: AgentEvent,
        raw: dict[str, Any],
    ) -> ResidentRunResult:
        if raw.get("success") is not True:
            raise ValueError("resident completion checkpoint must record success")
        execution_path = ExecutionPath(str(raw.get("execution_path") or ""))
        if execution_path not in {ExecutionPath.MEMORY, ExecutionPath.CAPABILITY}:
            raise ValueError(
                "resident completion checkpoint must use memory or capability path"
            )
        model_invocations = raw.get("model_invocations")
        if isinstance(model_invocations, bool) or int(model_invocations) != 0:
            raise ValueError("resident completion checkpoint cannot claim model use")

        capability_name = None
        if execution_path is ExecutionPath.CAPABILITY:
            capability_name = str(raw.get("capability_name") or "").strip()
            if not capability_name:
                raise ValueError(
                    "capability completion checkpoint must identify the capability"
                )

        return ResidentRunResult(
            event=event,
            execution_path=execution_path,
            success=True,
            response=raw.get("response"),
            model_invocations=0,
            capability_name=capability_name,
            reason=str(raw.get("reason") or ""),
        )

    def _investigation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        local_failure = str(state.data.get("local_failure") or "").strip() or None
        investigation = self.investigator.investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        state.data["native_investigation"] = self._investigation_data(investigation.state)
        self._merge_investigation_into_thought(thought, investigation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        if investigation.resolved:
            domains = self.kernel.self_model.observe_native_outcome(
                event.task,
                self._required_capabilities(event),
                success=True,
                quality=0.95,
            )
            completion = {
                "execution_path": ExecutionPath.INVESTIGATION.value,
                "success": True,
                "response": str(investigation.response or ""),
                "model_invocations": 0,
                "reason": "resolved from ZN's own body and environment evidence",
            }
            state.stage = "investigation_completion"
            state.next_action = "publish terminal EventOutcome"
            state.data["native_domains"] = list(domains)
            state.data["investigation_completion"] = completion
            self.store.record_runtime_task(model_invocations=0)
            # Once this checkpoint is durable, the investigation result is
            # established. Restart must publish it without running another
            # native probe or repeating ordinary task accounting.
            self.store.save_working_state(state)
            return self._investigation_completion_result(event, completion)

        if investigation.can_continue:
            state.stage = "native_investigation"
            state.next_action = f"run native probe {investigation.state.next_probe}"
            self.store.save_working_state(state)
            return None

        state.stage = "native_deliberation"
        state.next_action = "integrate native evidence and identify remaining gap"
        self.store.save_working_state(state)
        return None

    def _resume_investigation_completion(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult:
        raw = state.data.get("investigation_completion")
        if not isinstance(raw, dict):
            return self._invalid_investigation_completion(
                event,
                "durable investigation completion checkpoint is incomplete",
            )
        try:
            return self._investigation_completion_result(event, raw)
        except (TypeError, ValueError):
            return self._invalid_investigation_completion(
                event,
                "durable investigation completion checkpoint is malformed",
            )

    @staticmethod
    def _invalid_investigation_completion(
        event: AgentEvent,
        reason: str,
    ) -> ResidentRunResult:
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.INVESTIGATION,
            success=False,
            model_invocations=0,
            reason=reason,
        )

    @staticmethod
    def _investigation_completion_result(
        event: AgentEvent,
        raw: dict[str, Any],
    ) -> ResidentRunResult:
        if raw.get("success") is not True:
            raise ValueError("investigation completion checkpoint must record success")
        execution_path = ExecutionPath(str(raw.get("execution_path") or ""))
        if execution_path is not ExecutionPath.INVESTIGATION:
            raise ValueError("investigation completion checkpoint must use investigation path")
        model_invocations = raw.get("model_invocations")
        if isinstance(model_invocations, bool) or int(model_invocations) != 0:
            raise ValueError("investigation completion checkpoint cannot claim model use")
        return ResidentRunResult(
            event=event,
            execution_path=execution_path,
            success=True,
            response=str(raw.get("response") or ""),
            model_invocations=0,
            reason=str(raw.get("reason") or ""),
        )

    def _deliberation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        investigation_state = self.investigator.current(event.event_id)
        if investigation_state is None:
            state.stage = "native_investigation"
            state.next_action = "begin native investigation"
            self.store.save_working_state(state)
            return None

        investigation = InvestigationResult(state=investigation_state)
        local_failure = str(state.data.get("local_failure") or "").strip() or None
        deliberation = self._native_deliberation(
            event,
            readiness,
            memory_checked=bool(state.data.get("memory_checked")),
            local_capability_checked=bool(state.data.get("local_capability_checked")),
            local_failure=local_failure,
            learning_evidence=learning_evidence,
            investigation=investigation,
        )
        state.data["native_deliberation"] = deliberation
        self._merge_deliberation_into_thought(thought, deliberation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        impasse = self.life.begin_impasse(
            event,
            reason=str(deliberation["unknown"]),
            required_capabilities=self._required_capabilities(event),
            local_failure=local_failure,
        )
        state.data["impasse_id"] = impasse.impasse_id
        state.data["cognitive_budget"] = {
            "use_external_cognition": decision.use_model,
            "max_model_calls": decision.max_model_calls,
            "reason": decision.reason,
        }

        if not decision.use_model:
            self.life.mark_impasse_unresolved(event, str(deliberation["unknown"]))
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=decision.reason,
            )

        cognition = self._build_cognition_request(
            event,
            impasse,
            self._required_capabilities(event),
            deliberation,
        )
        state.stage = "external_cognition"
        state.next_action = "consult_external_brain"
        state.data["cognition_request"] = {
            "request_id": cognition.request_id,
            "impasse_id": cognition.impasse_id,
            "event_id": cognition.event_id,
            "question": cognition.question,
            "required_capabilities": list(cognition.required_capabilities),
            "context": cognition.context,
            "created_at": cognition.created_at,
        }
        self.store.save_working_state(state)
        return None

    def _external_cognition_step(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult:
        raw = state.data.get("cognition_request")
        if not isinstance(raw, dict):
            raise RuntimeError("external cognition stage has no cognition request")
        required = tuple(raw.get("required_capabilities") or self._required_capabilities(event))
        cognition = CognitionRequest(
            request_id=str(raw.get("request_id") or f"cog-{uuid.uuid4().hex[:12]}"),
            impasse_id=str(raw.get("impasse_id") or state.data.get("impasse_id") or ""),
            event_id=event.event_id,
            question=str(raw.get("question") or event.task),
            required_capabilities=required,
            context=dict(raw.get("context") or {}),
            created_at=str(raw.get("created_at") or "") or CognitionRequest.__dataclass_fields__["created_at"].default_factory(),
        )
        budget = state.data.get("cognitive_budget")
        max_calls = 1
        decision_reason = "native investigation exhausted its current probes"
        if isinstance(budget, dict):
            try:
                max_calls = max(1, int(budget.get("max_model_calls") or 1))
            except (TypeError, ValueError):
                max_calls = 1
            decision_reason = str(budget.get("reason") or decision_reason)

        delta_handler = getattr(self, "cognitive_delta_handler", None)
        on_cognitive_delta = None
        on_cognitive_reset = None
        if callable(delta_handler):
            on_cognitive_delta = lambda delta: delta_handler(event.event_id, delta)
            reset_handler = getattr(self, "cognitive_response_reset_handler", None)
            if callable(reset_handler):
                on_cognitive_reset = lambda: reset_handler(event.event_id)
        kernel_result = self.kernel.run_goal(
            cognition.question,
            required_capabilities=cognition.required_capabilities,
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "impasse_id": cognition.impasse_id,
                "cognition_request": {
                    "request_id": cognition.request_id,
                    "context": cognition.context,
                },
            },
            max_attempts_override=max_calls,
            on_cognitive_delta=on_cognitive_delta,
            on_cognitive_reset=on_cognitive_reset,
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

        reason = decision_reason
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
            self.investigator.resolve_from_external(
                event.event_id,
                run.response or "external cognition resolved the remaining gap",
            )
            domains = self.kernel.self_model.integrate_external_learning(
                event.task,
                self._required_capabilities(event),
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
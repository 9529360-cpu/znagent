from __future__ import annotations

import json
import threading
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent, derive_native_action_intent
from .budget import CognitiveBudgetManager
from .capabilities import CapabilityRegistry
from .cognition import CognitiveIncrement
from .memory import StructuredMemory
from .models import AgentEvent, ExecutionPath, ResidentRunResult, WorkingState
from .resident import ZNResidentRuntime
from .self_model import TaskReadiness


class EmbodiedResidentRuntime(ZNResidentRuntime):
    """Resident runtime whose native cognition can produce concrete body action.

    The compatibility base class still provides the mature event/action methods,
    but this resident owns its birth sequence so it never instantiates a legacy
    LifeCore and then swaps in a richer one. Body, Investigation and embodied
    Life are present from the first loaded durable state.

        Situation -> Thought -> Body -> evidence/outcome -> Situation
        Impasse -> external cognition -> CognitiveIncrement -> Thought -> result

    It does not turn tools into skills and it does not add policy gates. Body
    and external brains remain resources; the resident decides how to use and
    integrate them.
    """

    _ACTIVE_THOUGHT_KINDS = {
        *ZNResidentRuntime._ACTIVE_THOUGHT_KINDS,
        "body_action",
        "integrate_cognition",
    }

    def __init__(self, *, kernel, capabilities=None, budget=None):
        # Do not call ZNResidentRuntime.__init__: it deliberately constructs the
        # compatibility ZNLifeCore first, which cannot deserialize the richer
        # CognitiveSituation persisted by this resident. An embodied resident is
        # born once with the correct organs instead of being assembled after a
        # temporary legacy birth.
        self.kernel = kernel
        self.store = kernel.store
        self.identity = kernel.identity
        self.capabilities = capabilities or CapabilityRegistry()
        self.budget = budget or CognitiveBudgetManager()
        self.memory = StructuredMemory(self.store)
        self._cycle_lock = threading.RLock()
        self.store.recover_interrupted_events()
        self.store.get_working_state()

        from .body import NativeBody
        from .embodied_investigation import EmbodiedInvestigator
        from .embodied_life import EmbodiedLifeCore

        self.body = NativeBody(resident=self)
        self.investigator = EmbodiedInvestigator(self)
        self.life = EmbodiedLifeCore(self)
        self.life.wake()

    def _advance_event_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        if state.stage == "native_action":
            return self._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if state.stage == "cognition_integration":
            return self._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
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
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)

        if intent is not None:
            signature = self._intent_signature(intent)
            failed_signature = str(
                state.data.get("native_action_failure_signature") or ""
            )
            # A failed movement may return to investigation for more evidence.
            # If that evidence produces the exact same action again, do not
            # blindly repeat it; let the normal impasse/cognition path reason
            # about the observed failure instead.
            if signature != failed_signature:
                state.stage = "native_action"
                state.next_action = f"move body: {intent.kind}"
                state.data["native_action_intent"] = intent.to_dict()
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform body action: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; native evidence supports a concrete body movement"
                    )
                    self._persist_enriched_thought(thought)
                return None

        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _native_action_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        raw = state.data.get("native_action_intent")
        if not isinstance(raw, dict):
            state.stage = "native_deliberation"
            state.next_action = "reconstruct missing native action intent"
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent.from_dict(raw)
        result = self.body.act(
            intent.kind,
            event_id=event.event_id,
            **dict(intent.args),
        )
        state.data["native_action_result"] = asdict(result)

        if result.success:
            domains = self.kernel.self_model.observe_native_outcome(
                event.task,
                self._required_capabilities(event),
                success=True,
                quality=0.95,
            )
            state.stage = "complete"
            state.next_action = None
            state.data["native_domains"] = list(domains)
            self.store.save_working_state(state)
            self.store.record_runtime_task(model_invocations=0)
            response = result.output.strip()
            if not response:
                response = json.dumps(result.data, ensure_ascii=False, sort_keys=True)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BODY,
                success=True,
                response=response,
                model_invocations=0,
                reason=f"ZN completed the task through its body: {intent.kind}",
            )

        self.kernel.self_model.observe_native_outcome(
            event.task,
            self._required_capabilities(event),
            success=False,
        )
        failure = result.error or f"body action {intent.kind} failed"
        state.data["local_failure"] = failure
        state.data["native_action_failure_signature"] = self._intent_signature(intent)
        state.stage = "native_investigation"
        state.next_action = "inspect the failed body movement and update the hypothesis"
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; the attempted body movement produced new failure evidence"
            )
            self._persist_enriched_thought(thought)
        return None

    def _external_cognition_step(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult | None:
        """Borrow cognition without accepting or learning it yet."""
        raw = state.data.get("cognition_request")
        if not isinstance(raw, dict):
            raise RuntimeError("external cognition stage has no cognition request")

        required = tuple(raw.get("required_capabilities") or self._required_capabilities(event))
        question = str(raw.get("question") or event.task)
        context = dict(raw.get("context") or {})
        impasse_id = str(raw.get("impasse_id") or state.data.get("impasse_id") or "")

        budget = state.data.get("cognitive_budget")
        max_calls = 1
        decision_reason = "native investigation exhausted its current probes"
        if isinstance(budget, dict):
            try:
                max_calls = max(1, int(budget.get("max_model_calls") or 1))
            except (TypeError, ValueError):
                max_calls = 1
            decision_reason = str(budget.get("reason") or decision_reason)

        kernel_result = self.kernel.run_goal(
            question,
            required_capabilities=required,
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "impasse_id": impasse_id,
                "cognition_request": {
                    "request_id": raw.get("request_id"),
                    "context": context,
                },
            },
            max_attempts_override=max_calls,
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

        reason = decision_reason
        if not kernel_result.assessment.success and kernel_result.worker_result.error:
            reason = kernel_result.worker_result.error
        if not kernel_result.assessment.success:
            state.stage = "failed"
            state.next_action = None
            self.store.save_working_state(state)
            self.life.mark_impasse_unresolved(event, reason)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MODEL,
                success=False,
                response=kernel_result.worker_result.response,
                model_invocations=invocations,
                reason=reason,
                kernel_result=kernel_result,
            )

        route_id = kernel_result.goal.route_id or "external"
        increment = CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id=impasse_id or None,
            source=f"external:{route_id}",
            question=question,
            content=kernel_result.worker_result.response,
            quality=kernel_result.assessment.quality,
            confidence=kernel_result.assessment.confidence,
        )
        # The increment is durable working state, but the impasse remains open
        # and SelfModel is not credited yet. Acceptance belongs to the next ZN
        # Thought, not to the external worker's success flag.
        state.data["cognitive_increment"] = increment.to_dict()
        state.data["external_cognition_result"] = {
            "model_invocations": invocations,
            "reason": reason,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.stage = "cognition_integration"
        state.next_action = "judge and integrate borrowed cognition"
        self.store.save_working_state(state)
        return None

    def _cognition_integration_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        raw = state.data.get("cognitive_increment")
        if not isinstance(raw, dict):
            state.stage = "native_deliberation"
            state.next_action = "recover missing cognitive increment"
            self.store.save_working_state(state)
            return None

        increment = CognitiveIncrement.from_dict(raw)
        if thought is not None:
            known = (
                f"I received a bounded cognitive increment from {increment.source} "
                f"with confidence={increment.confidence:.2f}"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; borrowed cognition has returned to my own state for integration"
            )
            self._persist_enriched_thought(thought)

        external = state.data.get("external_cognition_result")
        external_data = external if isinstance(external, dict) else {}
        invocations = max(0, int(external_data.get("model_invocations") or 0))

        integration = state.data.get("cognition_integration")
        integration_data = integration if isinstance(integration, dict) else {}
        if not integration_data.get("accepted"):
            # This is the point where ZN accepts the borrowed increment. Only
            # now do we close the impasse, stage learning evidence, and update
            # ZN's knowledge profile.
            accepted_run = ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MODEL,
                success=True,
                response=increment.content,
                model_invocations=invocations,
                reason=f"accepted cognitive increment from {increment.source}",
            )
            self.life.resolve_impasse(
                event,
                accepted_run,
                resolution_source=increment.source,
            )
            self.investigator.resolve_from_external(
                event.event_id,
                increment.content or "external cognition supplied the missing increment",
            )
            domains = self.kernel.self_model.integrate_external_learning(
                event.task,
                self._required_capabilities(event),
                quality=increment.quality,
                confidence=increment.confidence,
            )
            integration_data = {
                "increment_id": increment.increment_id,
                "accepted": True,
                "source": increment.source,
                "quality": increment.quality,
                "confidence": increment.confidence,
            }
            state.data["cognition_integration"] = integration_data
            state.data["integrated_learning_domains"] = list(domains)
            self.store.save_working_state(state)

        # Re-check whether the accepted increment accompanies a concrete native
        # body intent. The action stays ZN-owned; external text is never passed
        # straight through as a shell/tool instruction.
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)
        if intent is not None:
            signature = self._intent_signature(intent)
            failed_signature = str(
                state.data.get("native_action_failure_signature") or ""
            )
            if signature != failed_signature:
                state.data["native_action_intent"] = intent.to_dict()
                state.stage = "native_action"
                state.next_action = f"move body after cognition: {intent.kind}"
                self.store.save_working_state(state)
                return None

        state.stage = "complete"
        state.next_action = None
        self.store.save_working_state(state)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=True,
            response=increment.content,
            model_invocations=invocations,
            reason=(
                f"ZN accepted and integrated a bounded cognitive increment from "
                f"{increment.source} before completing the event"
            ),
        )

    def _enrich_thought_with_working_stage(self, thought, event: AgentEvent) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return

        if state.stage == "native_action":
            raw = state.data.get("native_action_intent")
            if not isinstance(raw, dict):
                return
            intent = NativeActionIntent.from_dict(raw)
            action = f"perform body action: {intent.kind}"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "body_action"
            thought.action_target = event.event_id
            thought.reason = "native cognition has selected a concrete movement of my body"
            return

        if state.stage == "cognition_integration":
            raw = state.data.get("cognitive_increment")
            increment = raw if isinstance(raw, dict) else {}
            source = str(increment.get("source") or "external cognition")
            action = "judge and integrate borrowed cognition into my own state"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "integrate_cognition"
            thought.action_target = event.event_id
            thought.reason = f"a bounded increment from {source} has returned for my judgment"

    @staticmethod
    def _intent_signature(intent: NativeActionIntent) -> str:
        return json.dumps(
            {"kind": intent.kind, "args": intent.args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

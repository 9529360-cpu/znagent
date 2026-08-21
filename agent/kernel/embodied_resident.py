from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent, derive_native_action_intent
from .models import AgentEvent, ExecutionPath, ResidentRunResult, WorkingState
from .resident import ZNResidentRuntime
from .self_model import TaskReadiness


class EmbodiedResidentRuntime(ZNResidentRuntime):
    """Resident runtime whose native cognition can produce concrete body action.

    The base resident owns continuity, memory, impasses and external cognition.
    This embodied resident is born with its Body, embodied Investigation and
    stage-aware Life core already attached, then closes the native loop:

        Situation -> Thought -> Body -> evidence/outcome -> Situation

    It does not turn tools into skills and it does not add policy gates. Body
    remains an organ; the resident decides when and why to move it.
    """

    _ACTIVE_THOUGHT_KINDS = {
        *ZNResidentRuntime._ACTIVE_THOUGHT_KINDS,
        "body_action",
    }

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(
            kernel=kernel,
            capabilities=capabilities,
            budget=budget,
        )
        # The compatibility base constructor establishes the durable self and
        # wake transition first. The embodied organs then replace the base
        # implementations while retaining exactly the same persistent state.
        from .body import NativeBody
        from .embodied_investigation import EmbodiedInvestigator
        from .embodied_life import EmbodiedLifeCore

        self.body = NativeBody(resident=self)
        self.investigator = EmbodiedInvestigator(self)
        self.life = EmbodiedLifeCore(self)

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

    def _enrich_thought_with_working_stage(self, thought, event: AgentEvent) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id or state.stage != "native_action":
            return
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

    @staticmethod
    def _intent_signature(intent: NativeActionIntent) -> str:
        return json.dumps(
            {"kind": intent.kind, "args": intent.args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

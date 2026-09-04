from __future__ import annotations

"""Keep recoverable provider checkpoints non-terminal for criterion-bound Broad Work.

CapabilityRecoveryResidentRuntime deliberately checkpoints a successful external
model call as ``external_completion`` before it performs resident accounting.
That is correct for ordinary model-answer events, but a Broad Work model result
is only a proposed next step. This narrow adapter preserves the mature durable
checkpoint/accounting and then promotes the recovered result into the existing
CognitiveIncrement integration stage. No second scheduler, router, or work store
is introduced.
"""

from .broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from .cognition import CognitiveIncrement


class BroadGoalRecoverableCodingResidentRuntime(BroadGoalCodingResidentRuntime):
    """Turn durable model completion into a non-terminal Broad Work increment."""

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage == "external_completion" and self._criterion_bound_root(event) is not None:
            run = self._resume_external_completion(event, state)
            if not run.success:
                return run
            return self._promote_external_completion(event, state, run)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _external_cognition_step(self, event, state):
        root = self._criterion_bound_root(event)
        run = super()._external_cognition_step(event, state)
        if root is None or run is None or not run.success:
            return run
        return self._promote_external_completion(event, state, run)

    def _promote_external_completion(self, event, state, run):
        raw_completion = state.data.get(self._EXTERNAL_COMPLETION_KEY)
        completion = raw_completion if isinstance(raw_completion, dict) else {}
        kernel_result = run.kernel_result
        if kernel_result is None:
            goal_id = str(completion.get("goal_id") or state.current_goal_id or "").strip()
            if goal_id:
                kernel_result = self.kernel.load_goal_result(goal_id)

        quality = 0.5
        confidence = 0.5
        route_id = str(completion.get("route_id") or "external").strip() or "external"
        if kernel_result is not None:
            quality = float(kernel_result.assessment.quality)
            confidence = float(kernel_result.assessment.confidence)
            route_id = str(kernel_result.route.route_id or route_id).strip() or route_id

        raw_request = state.data.get("cognition_request")
        request = raw_request if isinstance(raw_request, dict) else {}
        impasse_id = str(request.get("impasse_id") or state.data.get("impasse_id") or "").strip()
        question = str(request.get("question") or event.task)
        increment = CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id=impasse_id or None,
            source=f"external:{route_id}",
            question=question,
            content=str(run.response or ""),
            quality=quality,
            confidence=confidence,
        )

        # CapabilityRecovery already applied the durable provider accounting,
        # resolved the impasse, and integrated learning exactly once. Mark this
        # increment accepted so the normal Broad Work integration can materialize
        # a WorkItem/Body movement without double-accounting that same model call.
        state.data["cognitive_increment"] = increment.to_dict()
        state.data["external_cognition_result"] = {
            "model_invocations": int(run.model_invocations),
            "reason": str(run.reason or ""),
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.data["cognition_integration"] = {
            "increment_id": increment.increment_id,
            "accepted": True,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
            "accepted_via": "recoverable_external_completion",
        }
        state.data.pop(self._EXTERNAL_COMPLETION_KEY, None)
        state.data.pop(self._EXTERNAL_COMPLETION_ACCOUNTING_KEY, None)
        state.stage = "cognition_integration"
        state.next_action = "judge and execute one bounded Broad Work proposal"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _accept_borrowed_increment(self, event, state, increment: CognitiveIncrement) -> None:
        integration = state.data.get("cognition_integration")
        if (
            isinstance(integration, dict)
            and integration.get("accepted") is True
            and str(integration.get("increment_id") or "") == increment.increment_id
        ):
            return
        super()._accept_borrowed_increment(event, state, increment)

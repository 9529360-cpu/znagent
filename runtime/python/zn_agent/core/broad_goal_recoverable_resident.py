from __future__ import annotations

"""Keep recoverable provider checkpoints non-terminal for criterion-bound Broad Work.

CapabilityRecoveryResidentRuntime deliberately checkpoints a successful external
model call as ``external_completion`` before it performs resident accounting.
That is correct for ordinary model-answer events, but a Broad Work model result
is only a proposed next step. This narrow adapter preserves the mature durable
checkpoint/accounting and then promotes the recovered result into the existing
CognitiveIncrement integration stage. No second scheduler, router, or work store
is introduced.

Guarded commands are deliberately non-replayable inside one action identity.
Broad Work binds each run_python movement to its durable WorkItem via the
existing NativeBody ``task_id`` command context. Crash replay of the same child
keeps the same identity and remains blocked, while a later child admitted after
new evidence gets a distinct stable identity. Child acceptance validates the
one durable observed process result instead of executing that guarded command a
second time. A later Root verifier remains a separate Work step.
"""

from .action import NativeActionIntent
from .broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from .cognition import CognitiveIncrement
from .result_semantics import normalize_action_result


class BroadGoalRecoverableCodingResidentRuntime(BroadGoalCodingResidentRuntime):
    """Turn durable model completion into a non-terminal Broad Work increment."""

    _OBSERVED_COMMAND_RESULT_KIND = "broad_observed_command_result"

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

    def _cognition_integration_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        result = super()._cognition_integration_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if result is not None:
            return result

        rolling = state.data.get(self._ROLLING_STEP_KEY)
        raw_intent = state.data.get("native_action_intent")
        if (
            state.stage != "native_action"
            or not isinstance(rolling, dict)
            or str(rolling.get("action_kind") or "") != "run_python"
            or not isinstance(raw_intent, dict)
        ):
            return None

        child_id = str(rolling.get("work_item_id") or "").strip()
        intent = NativeActionIntent.from_dict(raw_intent)
        if (
            not child_id
            or intent.source != "resident_broad_goal_choice"
            or intent.kind != "command"
        ):
            return None

        # ``task_id`` is an existing NativeBody command context field. Because
        # SideEffectAwareBody hashes all command args before dispatch, this gives
        # one stable replay identity per durable child without changing the
        # actual command string or weakening generic command recovery.
        if str(intent.args.get("task_id") or "").strip() != child_id:
            intent.args["task_id"] = child_id
            state.data["native_action_intent"] = intent.to_dict()
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        return None

    def _verification_contract(self, event, intent, *, result=None):
        contract = super()._verification_contract(event, intent, result=result)
        if (
            intent.source == "resident_broad_goal_choice"
            and intent.kind == "command"
            and isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "command"
        ):
            return {
                **contract,
                "kind": self._OBSERVED_COMMAND_RESULT_KIND,
            }
        return contract

    def _native_verification_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_contract = state.data.get("native_verification")
        if (
            not isinstance(raw_contract, dict)
            or str(raw_contract.get("kind") or "").strip().lower()
            != self._OBSERVED_COMMAND_RESULT_KIND
        ):
            return super()._native_verification_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        raw_intent = state.data.get("native_action_intent")
        raw_action = state.data.get("native_action_result")
        if not isinstance(raw_intent, dict) or not isinstance(raw_action, dict):
            return self._fail_observed_command_result(
                event,
                state,
                None,
                failure="rolling command verification lost its durable observed process result",
                thought=thought,
            )

        intent = NativeActionIntent.from_dict(raw_intent)
        data = raw_action.get("data") if isinstance(raw_action.get("data"), dict) else {}
        output = str(raw_action.get("output") or "")
        observed_exit = data.get("exit_code")
        timed_out = bool(data.get("timed_out", False))
        dispatch_observed = bool(data.get("side_effect_dispatch_observed", False))
        expected_exit = int(raw_contract.get("expected_exit_code", 0))
        expected_output = [
            str(item)
            for item in raw_contract.get("output_contains") or ()
            if str(item)
        ]
        missing_output = [fragment for fragment in expected_output if fragment not in output]
        command = str(intent.args.get("command") or "").strip()
        result_features = normalize_action_result(raw_action, command=command)
        masked_success = bool(result_features.get("masked_success"))
        verified = bool(
            raw_action.get("success") is True
            and dispatch_observed
            and not timed_out
            and observed_exit == expected_exit
            and not missing_output
            and not masked_success
        )
        verification_result = {
            "verified": verified,
            "kind": self._OBSERVED_COMMAND_RESULT_KIND,
            "expected_exit_code": expected_exit,
            "observed_exit_code": observed_exit,
            "expected_output_contains": expected_output,
            "missing_output_contains": missing_output,
            "dispatch_observed": dispatch_observed,
            "timed_out": timed_out,
            "result_features": result_features,
            "observation": raw_action,
        }
        state.data["native_verification_result"] = verification_result
        self._record_verified_experience(
            event,
            state,
            intent,
            verification_result=verification_result,
        )
        self._sync_execution_context(event, state)

        if verified:
            response = output.strip() or f"observed command exit code {observed_exit}"
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=(
                    "ZN accepted the rolling command child only after validating the durable "
                    "observed process result, without replaying the guarded command"
                ),
            )

        problems: list[str] = []
        if raw_action.get("success") is not True:
            problems.append(str(raw_action.get("error") or "command action was not successful"))
        if not dispatch_observed:
            problems.append("guarded command dispatch was not durably observed")
        if timed_out:
            problems.append("command timed out")
        if observed_exit != expected_exit:
            problems.append(f"expected exit code {expected_exit}, observed {observed_exit}")
        if missing_output:
            problems.append(
                "missing expected output fragment(s): "
                + ", ".join(repr(item) for item in missing_output)
            )
        if masked_success:
            problems.append("command status was masked by deterministic failure evidence")
        return self._fail_observed_command_result(
            event,
            state,
            intent,
            failure=(
                "observed command result did not satisfy the rolling acceptance contract: "
                + ("; ".join(problems) or "unknown mismatch")
            ),
            thought=thought,
        )

    def _fail_observed_command_result(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ):
        if intent is None:
            raw_intent = state.data.get("native_action_intent")
            if not isinstance(raw_intent, dict):
                state.data["local_failure"] = failure
                state.stage = "native_investigation"
                state.next_action = "reconstruct the missing rolling command evidence"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                self._reconcile_failed_rolling_step(event, state)
                return None
            intent = NativeActionIntent.from_dict(raw_intent)
        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

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

from __future__ import annotations

"""Resident ownership for modern focused text state and managed web browsing."""

import json
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .automation_text_state_sense import NativeFocusedAutomationTextSense
from .focused_text_entry_resident import FocusedTextEntryResidentRuntime
from .managed_browser import PlaywrightManagedBrowser
from .models import ExecutionPath
from .resident import ResidentRunResult
from .side_effect_body import SideEffectAwareBody


class FocusedModernTextResidentRuntime(FocusedTextEntryResidentRuntime):
    """Own modern read-only text state plus lazy managed external resources.

    The inherited ``keyboard_text`` competence remains limited to already-focused
    native Win32 Edit controls. ``automation_text_state`` is read-only evidence
    for a focused writable UIA Edit and is intentionally not consulted as input
    authority by the existing mutation lifecycle.

    ``managed_browser`` is resident-owned but lazy: constructing or booting ZN
    does not start Chromium and does not require Playwright to be installed.
    Browser engines remain replaceable resources behind ZN-owned browser
    session/action/authority/effect contracts.

    The final active Body remains a ``KeyboardTextBody`` subtype so the typed
    keyboard ownership contract stays intact. This subtype adds only a durable
    pre-dispatch uncertainty boundary for generic command and append side effects;
    richer pointer-click and keyboard-text non-replay contracts remain unchanged.

    Generic side-effect uncertainty is a resident recovery state, not ordinary
    failure evidence. Exact append goals may be re-observed before any retry;
    generic commands remain blocked until a future explicit recovery/cancel path
    can establish what happened without replaying the command itself.
    """

    _SIDE_EFFECT_RECOVERY_KEY = "side_effect_recovery"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = SideEffectAwareBody(resident=self)
        self.automation_text_state = NativeFocusedAutomationTextSense()
        self.managed_browser = PlaywrightManagedBrowser()

    @staticmethod
    def _generic_guarded_side_effect(intent: NativeActionIntent) -> bool:
        kind = str(intent.kind or "").strip().lower()
        if kind in {"command", "terminal", "shell"}:
            return True
        return kind in {"write_text", "write_file"} and bool(
            intent.args.get("append", False)
        )

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("native_action_intent")
        if not isinstance(raw, dict):
            return super()._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        intent = NativeActionIntent.from_dict(raw)
        if not self._generic_guarded_side_effect(intent):
            return super()._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        result = self.body.act(
            intent.kind,
            event_id=event.event_id,
            **dict(intent.args),
        )
        state.data["native_action_result"] = asdict(result)

        if (
            not result.success
            and isinstance(result.data, dict)
            and bool(result.data.get("side_effect_uncertain"))
        ):
            return self._begin_side_effect_recovery(
                event,
                state,
                intent,
                result,
                thought=thought,
            )

        if result.success:
            verification = self._verification_contract(event, intent, result=result)
            if verification is not None:
                state.data["native_verification"] = verification
                state.stage = "native_verification"
                state.next_action = "verify the requested postcondition from current reality"
                state.blocked_by = None
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "verify the body action against the requested postcondition"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the body movement returned successfully but task "
                        "completion still requires independent observation"
                    )
                    self._persist_enriched_thought(thought)
                return None

            self._sync_execution_context(event, state)
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=result.output.strip()
                or json.dumps(result.data, ensure_ascii=False, sort_keys=True),
                reason=f"ZN completed the task through its body: {intent.kind}",
            )

        self.kernel.self_model.observe_native_outcome(
            event.task,
            self._required_capabilities(event),
            success=False,
        )
        failure = result.error or f"body action {intent.kind} failed"
        state.data["local_failure"] = failure
        self._record_failed_action(
            event,
            state,
            intent,
            source="body",
            failure=failure,
        )
        state.stage = "native_investigation"
        state.next_action = "inspect the failed body movement and update the hypothesis"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; the attempted body movement produced new failure evidence"
            )
            self._persist_enriched_thought(thought)
        return None

    def _begin_side_effect_recovery(
        self,
        event,
        state,
        intent: NativeActionIntent,
        result,
        *,
        thought=None,
    ):
        data = result.data if isinstance(result.data, dict) else {}
        attempt_id = str(data.get("side_effect_attempt_id") or "").strip()
        contract = self._verification_contract(event, intent, result=result)
        can_reverify = bool(
            intent.kind in {"write_text", "write_file"}
            and bool(intent.args.get("append", False))
            and isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "text_equals"
            and str(contract.get("path") or "").strip()
            == str(intent.args.get("path") or "").strip()
        )
        recovery = {
            "status": "uncertain",
            "kind": str(intent.kind or "").strip().lower(),
            "intent_id": intent.intent_id,
            "attempt_id": attempt_id,
            "replay_blocked": True,
            "signature": str(data.get("side_effect_signature") or "")[:16],
            "verification_kind": "text_equals" if can_reverify else None,
            "decision": "reverify_effect" if can_reverify else "user_decision_required",
        }
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.data.pop("local_failure", None)
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "re-observe the exact append postcondition before any retry"
            if can_reverify
            else "await explicit recovery or cancellation decision; do not replay the side effect"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            message = (
                "outside-world effect is uncertain after an interrupted non-replayable action; "
                "replay is blocked until current reality proves what happened"
            )
            if message not in thought.unknown:
                thought.unknown = (*thought.unknown, message)
            thought.reason = (
                f"{thought.reason}; the action crossed a durable non-replayable boundary, so "
                "I am treating uncertainty as recovery state rather than failure evidence"
            )
            self._persist_enriched_thought(thought)
        return None

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage == "side_effect_recovery":
            return self._side_effect_recovery_step(
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

    def _side_effect_recovery_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        del readiness
        raw_recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_recovery, dict) or not isinstance(raw_intent, dict):
            return self._hold_side_effect_recovery(
                event,
                state,
                reason="durable side-effect recovery metadata is incomplete",
            )

        recovery = dict(raw_recovery)
        if str(recovery.get("decision") or "") != "reverify_effect":
            return None

        intent = NativeActionIntent.from_dict(raw_intent)
        contract = self._verification_contract(event, intent, result=None)
        if not self._recoverable_append_contract(intent, contract):
            return self._hold_side_effect_recovery(
                event,
                state,
                reason="no exact read-only append postcondition is available for recovery",
            )
        assert isinstance(contract, dict)

        path = str(contract.get("path") or "")
        expected = str(contract.get("expected_text") or "")
        observed = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=path,
            max_chars=max(1, len(expected) + 1),
        )
        observation = {
            "action_id": observed.action_id,
            "success": observed.success,
            "truncated": bool(observed.data.get("truncated")) if observed.success else None,
            "observed_chars": (
                int(observed.data.get("chars") or len(observed.output))
                if observed.success
                else None
            ),
        }
        recovery["verification"] = observation

        if (
            observed.success
            and not bool(observed.data.get("truncated"))
            and observed.output == expected
        ):
            if not self.body.resolve_uncertain_attempt(
                str(recovery.get("attempt_id") or ""),
                event_id=event.event_id,
                status="verified_effect",
                evidence_action_id=observed.action_id,
            ):
                return self._hold_side_effect_recovery(
                    event,
                    state,
                    reason="the durable side-effect attempt no longer matches recovery state",
                    recovery=recovery,
                )
            recovery.update(
                {
                    "status": "verified_effect",
                    "decision": "complete_without_replay",
                    "replay_blocked": False,
                }
            )
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "complete"
            state.next_action = None
            state.blocked_by = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BODY,
                success=True,
                response=path,
                model_invocations=0,
                reason=(
                    "ZN independently observed the exact requested append postcondition after "
                    "an interrupted non-replayable dispatch and completed without replay or "
                    "causal learning from the uncertain action"
                ),
            )

        baseline = self._resident_derived_append_baseline(intent, contract)
        if (
            baseline is not None
            and observed.success
            and not bool(observed.data.get("truncated"))
            and observed.output == baseline
        ):
            if not self.body.resolve_uncertain_attempt(
                str(recovery.get("attempt_id") or ""),
                event_id=event.event_id,
                status="verified_absent",
                evidence_action_id=observed.action_id,
            ):
                return self._hold_side_effect_recovery(
                    event,
                    state,
                    reason="the durable side-effect attempt no longer matches recovery state",
                    recovery=recovery,
                )
            recovery.update(
                {
                    "status": "verified_absent",
                    "decision": "retry_authorized",
                    "replay_blocked": False,
                }
            )
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "native_action"
            state.next_action = "retry append after exact pre-dispatch baseline was re-observed"
            state.blocked_by = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if not observed.success:
            reason = observed.error or "current text state could not be observed"
        elif bool(observed.data.get("truncated")):
            reason = "current text state is truncated and cannot prove append recovery"
        else:
            reason = (
                "current text is neither the exact requested append result nor a proven "
                "resident-derived pre-dispatch baseline"
            )
        return self._hold_side_effect_recovery(
            event,
            state,
            reason=reason,
            recovery=recovery,
        )

    @staticmethod
    def _recoverable_append_contract(
        intent: NativeActionIntent,
        contract: dict[str, Any] | None,
    ) -> bool:
        return bool(
            intent.kind in {"write_text", "write_file"}
            and bool(intent.args.get("append", False))
            and isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "text_equals"
            and str(contract.get("path") or "").strip()
            == str(intent.args.get("path") or "").strip()
            and "expected_text" in contract
        )

    @staticmethod
    def _resident_derived_append_baseline(
        intent: NativeActionIntent,
        contract: dict[str, Any],
    ) -> str | None:
        if intent.source != "resident_choice":
            return None
        if str(contract.get("action_variant") or "").strip().lower() != "append":
            return None
        raw_goal = intent.expected_outcome
        if not isinstance(raw_goal, dict):
            return None
        if str(raw_goal.get("kind") or "").strip().lower() != "text_equals":
            return None
        path = str(contract.get("path") or "")
        if str(raw_goal.get("path") or "") != path:
            return None
        expected = str(contract.get("expected_text") or "")
        if str(raw_goal.get("expected_text") or "") != expected:
            return None
        suffix = str(intent.args.get("content") or "")
        if not suffix or not expected.endswith(suffix):
            return None
        return expected[: -len(suffix)]

    def _hold_side_effect_recovery(
        self,
        event,
        state,
        *,
        reason: str,
        recovery: dict[str, Any] | None = None,
    ):
        current = dict(recovery or state.data.get(self._SIDE_EFFECT_RECOVERY_KEY) or {})
        current.update(
            {
                "status": "decision_required",
                "decision": "user_decision_required",
                "replay_blocked": True,
                "reason": str(reason or "side-effect recovery is unresolved")[:500],
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = current
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = "await explicit recovery or cancellation decision; do not replay the side effect"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

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

    The inherited ``keyboard_text`` competence accepts either an already-focused
    native Win32 Edit or an explicitly scoped focused writable UIA Edit. Modern
    targets remain bounded to non-password, empty-or-already-matching controls;
    ``automation_text_state`` supplies privacy-safe identity/digest evidence and
    never mutates a control itself.

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
    generic commands remain blocked until an explicit recovery/cancel path can
    establish the Work lifecycle without guessing what happened outside ZN.
    """

    _SIDE_EFFECT_RECOVERY_KEY = "side_effect_recovery"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = SideEffectAwareBody(resident=self)
        self.automation_text_state = NativeFocusedAutomationTextSense()
        self.managed_browser = PlaywrightManagedBrowser()

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["completion_observations"] = self.completion_observations.health()
        return data

    def result_for(self, event_id: str) -> ResidentRunResult | None:
        """Reconstruct cancellation explicitly instead of collapsing it into failure."""
        result = super().result_for(event_id)
        if result is None:
            return None
        outcome = self.store.get_event_outcome(event_id)
        if outcome is not None:
            result.cancelled = bool(outcome.cancelled)
        return result

    def cancel_uncertain_event(
        self,
        event_id: str,
        *,
        reason: str = "user cancelled Work while outside-world effect remained uncertain",
    ) -> ResidentRunResult:
        """Stop one proven recovery Work without learning an action failure.

        Store owns the atomic lifecycle transition. This resident method owns the
        control decision and deliberately bypasses ``_complete_result`` and
        ``life.observe_action``: cancellation says ZN will stop this Work, not
        that the attempted outside-world action failed or succeeded.
        """

        normalized = str(event_id or "").strip()
        if not normalized:
            raise ValueError("resident cancellation requires event_id")
        with self._cycle_lock:
            event = self.store.get_event(normalized)
            if event is None:
                raise ValueError(f"unknown resident event: {normalized}")
            terminal = self.store.cancel_uncertain_event(
                normalized,
                reason=reason,
            )
            outcome = self.store.get_event_outcome(normalized)
            if outcome is None or not outcome.cancelled:
                raise RuntimeError("resident cancellation did not publish a durable outcome")

            result = ResidentRunResult(
                event=terminal,
                execution_path=outcome.execution_path,
                success=outcome.success,
                response=outcome.response,
                model_invocations=outcome.model_invocations,
                capability_name=outcome.capability_name,
                reason=outcome.reason,
                cancelled=True,
            )

            intention_id = str(event.payload.get("intention_id") or "").strip()
            if intention_id:
                try:
                    self.will.observe_event_outcome(
                        intention_id,
                        event_id=normalized,
                        success=False,
                        summary=outcome.reason or "step cancelled",
                        cancelled=True,
                    )
                except KeyError:
                    # Imported/manual payloads may reference an intention that
                    # does not exist in this resident. The durable Work/event
                    # cancellation remains valid independently of that metadata.
                    pass
            return result

    def resolve_uncertain_event(
        self,
        event_id: str,
        *,
        attempt_id: str,
        decision: str,
    ):
        """Consume one explicit user decision without dispatching a new mutation.

        Store first commits the user evidence and checkpoint transition atomically.
        ``retry_authorized`` stops there: the next normal resident pulse must pass
        through ``SideEffectAwareBody.act`` and therefore creates a new attempt.
        ``effect_happened`` may advance only to read-only verification or a
        completion checkpoint; it never calls the original mutation again.
        """

        normalized = str(event_id or "").strip()
        if not normalized:
            raise ValueError("resident uncertain-effect resolution requires event_id")
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"effect_happened", "retry_authorized"}:
            raise ValueError("resident uncertain-effect resolution requires a supported decision")

        with self._cycle_lock:
            event = self.store.get_event(normalized)
            if event is None:
                raise ValueError(f"unknown resident event: {normalized}")
            state = self.store.resolve_uncertain_event(
                normalized,
                attempt_id=attempt_id,
                decision=normalized_decision,
            )
            if normalized_decision == "retry_authorized":
                return None
            return self._resume_user_confirmed_side_effect(event, state)

    def _resume_user_confirmed_side_effect(self, event, state):
        raw = state.data.get("native_action_intent")
        recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        if not isinstance(raw, dict) or not isinstance(recovery, dict):
            return self._hold_side_effect_recovery(
                event,
                state,
                reason="user-confirmed side-effect recovery metadata is incomplete",
            )
        if (
            str(recovery.get("status") or "") != "user_confirmed_effect"
            or str(recovery.get("decision") or "") != "effect_happened"
            or recovery.get("replay_blocked") is not False
        ):
            return self._hold_side_effect_recovery(
                event,
                state,
                reason="user-confirmed side-effect recovery is not durably resolved",
            )

        intent = NativeActionIntent.from_dict(raw)
        contract = self._verification_contract(event, intent, result=None)
        if contract is not None:
            state.data["native_verification"] = contract
            state.stage = "native_verification"
            state.next_action = "independently verify current reality after explicit user confirmation"
            state.blocked_by = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        self._sync_execution_context(event, state)
        return self._complete_successful_body_action(
            event,
            state,
            intent,
            response="outside-world effect confirmed by explicit user resolution",
            reason=(
                "The user explicitly confirmed that the replay-sensitive outside-world effect "
                "happened after an indeterminate dispatch; ZN completed without replay and "
                "did not record that confirmation as machine verification"
            ),
        )

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
            "user_resolution_supported": True,
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
        decision = str(recovery.get("decision") or "")
        if decision == "effect_happened":
            return self._resume_user_confirmed_side_effect(event, state)
        if decision != "reverify_effect":
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
            # ``EventOutcome`` is the only durable terminal truth. Keep the last
            # replay-safe recovery checkpoint on disk until ``complete_event``
            # atomically publishes terminal event + outcome + idle state.
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

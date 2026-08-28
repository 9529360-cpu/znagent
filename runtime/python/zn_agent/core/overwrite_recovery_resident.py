from __future__ import annotations

"""Reality-gated crash recovery for exact overwrite text mutations."""

from typing import Any

from .action import NativeActionIntent
from .durable_body_accounting_resident import DurableBodyAccountingResidentRuntime
from .file_identity import compare_file_identities, observe_file_identity
from .models import ExecutionPath, ResidentRunResult
from .side_effect_body import SideEffectAwareBody


class OverwriteAwareBody(SideEffectAwareBody):
    """Active-product Body guard that adds exact overwrite dispatch ownership.

    The shared ``SideEffectAwareBody`` keeps its historical command + append
    contract for existing callers. ZN's active resident layers overwrite
    protection on top without silently broadening that reusable base contract.
    """

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in {"write_text", "write_file"}:
            return True
        return super()._requires_guard(kind, args)

    def overwrite_replay_blocked(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
    ) -> bool:
        """Read only whether this exact overwrite already crossed dispatch ownership.

        A fresh overwrite must continue through the existing repo/baseline/verifier
        owners before Body dispatch. Only an already-started/observed exact
        signature is diverted into recovery.
        """

        normalized_kind = str(kind or "").strip().lower()
        normalized_event = str(event_id or "").strip()
        if normalized_kind not in {"write_text", "write_file"} or not normalized_event:
            return False
        signature_hash = self._signature_hash(normalized_kind, args)
        return (
            self._replay_blocking_attempt(
                normalized_event,
                signature_hash,
                include_observed=True,
            )
            is not None
        )


class OverwriteRecoveryResidentRuntime(DurableBodyAccountingResidentRuntime):
    """Treat overwrite dispatch as replay-sensitive outside-world mutation.

    Ordinary exact replace/create text writes have a strong postcondition: the
    current file can be re-read and compared with the intended complete text.
    That makes it safe to establish that an interrupted write *did* happen, but
    it does not make a mismatch authority to overwrite again. A mismatch may be
    the old pre-state, a partial write, or a user/external edit after the crash.

    The active product also owns one bounded pre-dispatch file-identity
    checkpoint. It is deliberately content-free apart from a SHA-256 digest and
    never authorizes replay after a side-effect attempt exists. Its purpose is to
    prevent an accepted but not-yet-dispatched overwrite from silently resuming
    across restart after the target changed meanwhile.

    Recovery remains asymmetric:

    - current text == intended text -> complete without replay;
    - no durable dispatch attempt + exact pre-state identity still current -> the
      original fresh lifecycle may continue;
    - anything else -> hold uncertainty / refresh Investigation and do not mutate.
    """

    _OVERWRITE_PRESTATE_KEY = "overwrite_prestate_identity"
    _OVERWRITE_PRESTATE_RECHECK_KEY = "overwrite_prestate_recheck"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.body = OverwriteAwareBody(resident=self)

    @staticmethod
    def _is_overwrite_intent(intent: NativeActionIntent) -> bool:
        return bool(
            str(intent.kind or "").strip().lower() in {"write_text", "write_file"}
            and not bool(intent.args.get("append", False))
        )

    def _prepare_overwrite_prestate(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ) -> bool:
        """Persist/recheck bounded pre-dispatch identity before fresh overwrite.

        ``SideEffectAwareBody`` durably starts the replay-sensitive attempt before
        dispatch. Therefore if restart sees this pre-state checkpoint but no
        matching attempt, ZN knows its guarded overwrite did not cross the Body
        dispatch boundary. It still re-observes the target: changed reality blocks
        the stale action instead of silently continuing it.
        """

        path = str(intent.args.get("path") or "").strip()
        if not path:
            return True
        current = observe_file_identity(path)
        raw = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        same_intent = bool(
            isinstance(raw, dict)
            and str(raw.get("intent_id") or "") == intent.intent_id
            and str(raw.get("action_signature") or "") == self._intent_signature(intent)
        )

        if not same_intent:
            state.data[self._OVERWRITE_PRESTATE_KEY] = {
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
                "identity": current,
            }
            state.data.pop(self._OVERWRITE_PRESTATE_RECHECK_KEY, None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return True

        prior_identity = raw.get("identity") if isinstance(raw, dict) else None
        comparison = compare_file_identities(
            prior_identity if isinstance(prior_identity, dict) else None,
            current,
        )
        state.data[self._OVERWRITE_PRESTATE_RECHECK_KEY] = {
            "intent_id": intent.intent_id,
            "comparable": bool(comparison.get("comparable")),
            "exact": bool(comparison.get("exact")),
            "reason": str(comparison.get("reason") or "identity_unknown")[:120],
            "current_identity": current,
        }
        self._sync_execution_context(event, state)

        if comparison.get("exact") is True:
            self.store.save_working_state(state)
            return True

        failure = (
            "overwrite pre-dispatch identity no longer matches current file reality; "
            "the prior intent was checkpointed before Body dispatch, so ZN will refresh "
            "Investigation instead of overwriting a target that may have changed externally"
        )
        state.data["local_failure"] = failure
        self._record_failed_action(
            event,
            state,
            intent,
            source="precondition",
            failure=failure,
        )
        state.stage = "native_investigation"
        state.next_action = "refresh current file/repository evidence before another overwrite"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; durable pre-dispatch file identity no longer matches "
                "current reality, so the stale overwrite is not allowed to continue"
            )
            self._persist_enriched_thought(thought)
        return False

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
        if not self._is_overwrite_intent(intent):
            return super()._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        # Once durable dispatch ownership exists, pre-state evidence is no longer
        # replay authority. The existing effect-recovery path exclusively owns the
        # decision and will perform only read-only current-world verification.
        if self.body.overwrite_replay_blocked(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        ):
            result = self.body.act(
                intent.kind,
                event_id=event.event_id,
                **dict(intent.args),
            )
            if not (
                not result.success
                and isinstance(result.data, dict)
                and bool(result.data.get("side_effect_uncertain"))
            ):
                raise RuntimeError(
                    "durable overwrite attempt existed but Body did not return replay-blocked uncertainty"
                )
            state.data["native_action_result"] = {
                "action_id": result.action_id,
                "kind": result.kind,
                "success": result.success,
                "data": dict(result.data or {}),
                "output": result.output,
                "error": result.error,
                "event_id": result.event_id,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
            }
            return self._begin_side_effect_recovery(
                event,
                state,
                intent,
                result,
                thought=thought,
            )

        # Fresh overwrites stay on the inherited most-specific lifecycle so repo
        # baseline/Git-delta/targeted-test ownership is preserved. The pre-state
        # checkpoint is an additional restart guard, not a replacement verifier.
        if not self._prepare_overwrite_prestate(
            event,
            state,
            intent,
            thought=thought,
        ):
            return None
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _begin_side_effect_recovery(
        self,
        event,
        state,
        intent: NativeActionIntent,
        result,
        *,
        thought=None,
    ):
        kind = str(intent.kind or "").strip().lower()
        if kind not in {"write_text", "write_file"} or bool(intent.args.get("append", False)):
            return super()._begin_side_effect_recovery(
                event,
                state,
                intent,
                result,
                thought=thought,
            )

        data = result.data if isinstance(result.data, dict) else {}
        contract = self._verification_contract(event, intent, result=result)
        can_reverify = bool(
            isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "text_equals"
            and str(contract.get("path") or "").strip()
            == str(intent.args.get("path") or "").strip()
            and "expected_text" in contract
        )
        recovery = {
            "status": "uncertain",
            "kind": kind,
            "intent_id": intent.intent_id,
            "attempt_id": str(data.get("side_effect_attempt_id") or "").strip(),
            "replay_blocked": True,
            "signature": str(data.get("side_effect_signature") or "")[:16],
            "verification_kind": "text_equals" if can_reverify else None,
            "decision": "reverify_effect" if can_reverify else "user_decision_required",
            "recovery_policy": "overwrite_effect_only",
        }
        raw_prestate = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        if (
            isinstance(raw_prestate, dict)
            and str(raw_prestate.get("intent_id") or "") == intent.intent_id
        ):
            recovery["prestate_checkpointed"] = True
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.data.pop("local_failure", None)
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "re-observe the exact overwrite postcondition without replay"
            if can_reverify
            else "await explicit recovery or cancellation decision; do not replay the side effect"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            message = (
                "overwrite effect is uncertain after interruption; I will inspect current "
                "reality and will not replay a stale write intent"
            )
            if message not in thought.unknown:
                thought.unknown = (*thought.unknown, message)
            thought.reason = (
                f"{thought.reason}; overwrite crossed a durable side-effect boundary, so "
                "current file state must decide recovery rather than stale intent"
            )
            self._persist_enriched_thought(thought)
        return None

    def _side_effect_recovery_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_recovery, dict) or not isinstance(raw_intent, dict):
            return super()._side_effect_recovery_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        recovery = dict(raw_recovery)
        if str(recovery.get("recovery_policy") or "") != "overwrite_effect_only":
            return super()._side_effect_recovery_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if str(recovery.get("decision") or "") != "reverify_effect":
            return None

        intent = NativeActionIntent.from_dict(raw_intent)
        contract = self._verification_contract(event, intent, result=None)
        if not (
            isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "text_equals"
            and str(contract.get("path") or "").strip()
            == str(intent.args.get("path") or "").strip()
            and "expected_text" in contract
        ):
            return self._hold_side_effect_recovery(
                event,
                state,
                reason="no exact read-only overwrite postcondition is available for recovery",
                recovery=recovery,
            )

        path = str(contract.get("path") or "")
        expected = str(contract.get("expected_text") or "")
        observed = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=path,
            max_chars=max(1, len(expected) + 1),
        )
        recovery["verification"] = {
            "action_id": observed.action_id,
            "success": observed.success,
            "truncated": bool(observed.data.get("truncated")) if observed.success else None,
            "observed_chars": (
                int(observed.data.get("chars") or len(observed.output))
                if observed.success
                else None
            ),
        }

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
                    reason="the durable overwrite attempt no longer matches recovery state",
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
            self.store.record_runtime_task(model_invocations=0)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BODY,
                success=True,
                response=path,
                model_invocations=0,
                reason=(
                    "ZN independently observed the exact requested overwrite state after "
                    "interruption and completed without replaying the stale mutation"
                ),
            )

        raw_prestate = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        prestate_identity = (
            raw_prestate.get("identity")
            if isinstance(raw_prestate, dict)
            and str(raw_prestate.get("intent_id") or "") == intent.intent_id
            else None
        )
        current_identity = observe_file_identity(path)
        prestate_comparison = compare_file_identities(
            prestate_identity if isinstance(prestate_identity, dict) else None,
            current_identity,
        )
        recovery["prestate_recheck"] = {
            "checkpointed": isinstance(prestate_identity, dict),
            "comparable": bool(prestate_comparison.get("comparable")),
            "exact": bool(prestate_comparison.get("exact")),
            "reason": str(prestate_comparison.get("reason") or "identity_unknown")[:120],
            "current_identity": current_identity,
        }

        if prestate_comparison.get("exact") is True:
            reason = (
                "current file matches the durable pre-dispatch identity, but a durable Body "
                "attempt also exists; the overwrite may have happened and later been restored "
                "externally, so automatic replay remains forbidden"
            )
        elif not observed.success:
            reason = observed.error or "current text state could not be observed"
        elif bool(observed.data.get("truncated")):
            reason = (
                "current text exceeds the exact overwrite recovery observation bound; it may "
                "reflect a partial or user/external change, so replay is forbidden"
            )
        else:
            reason = (
                "current text does not equal the intended overwrite result and does not retain "
                "the exact durable pre-dispatch identity; partial mutation or user/external "
                "change remains possible, so replay is forbidden"
            )
        return self._hold_side_effect_recovery(
            event,
            state,
            reason=reason,
            recovery=recovery,
        )

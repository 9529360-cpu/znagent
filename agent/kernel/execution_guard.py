from __future__ import annotations

import hashlib
import json
from typing import Any

from .action import NativeActionIntent, derive_native_action_intent
from .models import AgentEvent, WorkingState, utc_now
from .world_closed_loop import WorldAwareTransferResidentRuntime


class EvidenceGuardedResidentRuntime(WorldAwareTransferResidentRuntime):
    """Final resident runtime with evidence-bound failed-action suppression.

    A failed movement is not a permanent ban and it is not merely "the last
    thing that failed". ZN retains a bounded record of which concrete movement
    failed against which observed Investigation facts. The same movement stays
    blocked while reality evidence is unchanged, even if another action fails in
    between. Genuinely changed native facts create a new evidence version and
    allow cognition to reconsider the movement.

    This is an execution invariant on the existing resident loop. It is not a
    planner, retry scheduler, or separate agent.
    """

    _FAILED_ACTION_RECORDS_KEY = "native_action_failure_records"
    _MAX_FAILED_ACTION_RECORDS = 16
    _VOLATILE_FACT_KEYS = frozenset(
        {
            "captured_at",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "observed_at",
            "checked_at",
            "sampled_at",
            "timestamp",
        }
    )

    def _deliberation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ):
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)
        if intent is not None:
            self._apply_parent_failure_shim(event, state, intent)
        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _cognition_integration_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness,
        thought=None,
    ):
        # External cognition may change ZN's understanding, but model text is
        # not new reality evidence. If the same concrete movement is still
        # derived from unchanged native facts, keep the inherited guard engaged.
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)
        if intent is not None:
            self._apply_parent_failure_shim(event, state, intent)
        return super()._cognition_integration_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _begin_native_action_cycle(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
    ) -> None:
        super()._begin_native_action_cycle(event, state, intent)
        # The inherited single-signature field remains only as a compatibility
        # shim for parent methods. Once the evidence ledger admits a movement,
        # that one-slot value must not veto it again.
        state.data.pop("native_action_failure_signature", None)
        self._sync_execution_context(event, state)

    def _native_action_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness,
        thought=None,
    ):
        raw_intent = state.data.get("native_action_intent")
        intent = (
            NativeActionIntent.from_dict(raw_intent)
            if isinstance(raw_intent, dict)
            else None
        )
        run = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        raw_result = state.data.get("native_action_result")
        action_result = raw_result if isinstance(raw_result, dict) else {}
        if (
            intent is not None
            and state.stage == "native_investigation"
            and action_result.get("success") is False
        ):
            self._record_failed_action(
                event,
                state,
                intent,
                source="body",
                failure=str(state.data.get("local_failure") or "body action failed"),
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        return run

    def _fail_postcondition_verification(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        failure: str,
        thought=None,
    ) -> None:
        super()._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )
        self._record_failed_action(
            event,
            state,
            intent,
            source="verification",
            failure=failure,
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _apply_parent_failure_shim(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
    ) -> bool:
        """Map the evidence ledger onto the inherited one-slot guard."""
        blocked = self._action_blocked_by_current_evidence(event, state, intent)
        signature = self._intent_signature(intent)
        if blocked:
            state.data["native_action_failure_signature"] = signature
        elif str(state.data.get("native_action_failure_signature") or "") == signature:
            state.data.pop("native_action_failure_signature", None)
        return blocked

    def _action_blocked_by_current_evidence(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
    ) -> bool:
        evidence_fingerprint = self._evidence_fingerprint(event.event_id)
        signature_hash = self._signature_hash(intent)
        records = self._failure_records(state)
        if any(
            str(item.get("signature_hash") or "") == signature_hash
            and str(item.get("evidence_fingerprint") or "") == evidence_fingerprint
            for item in records
        ):
            return True

        # Lazy migration applies only when no ledger exists yet. Once any
        # evidence-bound record is present, the old one-slot signature is merely
        # a parent compatibility shim; re-migrating it after evidence changes
        # would accidentally turn a temporary failure into a permanent ban.
        legacy = str(state.data.get("native_action_failure_signature") or "")
        if not records and legacy and legacy == self._intent_signature(intent):
            self._record_failed_action(
                event,
                state,
                intent,
                source="legacy",
                failure=str(state.data.get("local_failure") or "prior body action failed"),
                evidence_fingerprint=evidence_fingerprint,
            )
            return True
        return False

    def _record_failed_action(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        source: str,
        failure: str,
        evidence_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = evidence_fingerprint or self._evidence_fingerprint(event.event_id)
        signature_hash = self._signature_hash(intent)
        record = {
            "signature_hash": signature_hash,
            "kind": intent.kind,
            "evidence_fingerprint": fingerprint,
            "source": str(source or "body")[:80],
            "failure": str(failure or "body action failed")[:1000],
            "at": utc_now(),
        }
        records = [
            item
            for item in self._failure_records(state)
            if not (
                str(item.get("signature_hash") or "") == signature_hash
                and str(item.get("evidence_fingerprint") or "") == fingerprint
            )
        ]
        records.append(record)
        state.data[self._FAILED_ACTION_RECORDS_KEY] = records[
            -self._MAX_FAILED_ACTION_RECORDS :
        ]
        return record

    def _sync_execution_context(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> dict[str, Any]:
        context = super()._sync_execution_context(event, state)
        records = self._failure_records(state)
        fingerprint = self._evidence_fingerprint(event.event_id)
        current = [
            item
            for item in records
            if str(item.get("evidence_fingerprint") or "") == fingerprint
        ]
        context["failed_actions"] = {
            "total": len(records),
            "current_evidence_count": len(current),
            "evidence_version": fingerprint[:16],
            "recent": [self._failure_summary(item) for item in records[-8:]],
        }
        state.data["execution_context"] = context
        return context

    def _evidence_fingerprint(self, event_id: str) -> str:
        investigation = self.investigator.current(event_id)
        facts = investigation.facts if investigation is not None else {}
        stable = self._stable_fact_value(facts)
        encoded = json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _stable_fact_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._stable_fact_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if not cls._volatile_fact_key(str(key))
            }
        if isinstance(value, (list, tuple)):
            return [cls._stable_fact_value(item) for item in value]
        if isinstance(value, set):
            normalized = [cls._stable_fact_value(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @classmethod
    def _volatile_fact_key(cls, key: str) -> bool:
        normalized = str(key or "").strip().lower()
        return normalized in cls._VOLATILE_FACT_KEYS or normalized.endswith("_at")

    @classmethod
    def _failure_records(cls, state: WorkingState) -> list[dict[str, Any]]:
        raw = state.data.get(cls._FAILED_ACTION_RECORDS_KEY)
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)][
            -cls._MAX_FAILED_ACTION_RECORDS :
        ]

    @classmethod
    def _failure_summary(cls, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "signature": str(raw.get("signature_hash") or "")[:16],
            "kind": str(raw.get("kind") or "unknown"),
            "evidence_version": str(raw.get("evidence_fingerprint") or "")[:16],
            "source": str(raw.get("source") or "unknown")[:80],
            "failure": str(raw.get("failure") or "")[:500] or None,
        }

    @classmethod
    def _signature_hash(cls, intent: NativeActionIntent) -> str:
        raw = cls._intent_signature(intent).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

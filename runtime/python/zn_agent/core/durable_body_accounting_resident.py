from __future__ import annotations

"""Crash-safe cumulative accounting around active resident Body outcomes."""

from contextlib import contextmanager
from typing import Any, Iterator

from .capability_recovery_resident import CapabilityRecoveryResidentRuntime
from .models import ExecutionPath
from .self_model import SelfModel


class DurableBodyAccountingResidentRuntime(CapabilityRecoveryResidentRuntime):
    """Persist Body semantic truth before updating cumulative self evidence.

    The mature embodied loop historically updated SelfModel/task counters before
    its next WorkingState save. A process death in that narrow window could make
    restart learn the same outcome twice. This active wrapper leaves the Body,
    verification, pointer/text and procedural loops unchanged while moving their
    cumulative accounting behind durable semantic facts.

    Fresh failures are identified by the resident's existing action-signature +
    evidence-fingerprint record. Legacy failure records intentionally carry no
    accounting descriptor and are treated as already accounted during upgrade.
    """

    _BODY_ACCOUNTING_VERSION = 1
    _BODY_SUCCESS_ACCOUNTING_KEY = "native_body_completion_accounting"
    _BODY_FAILURE_ACCOUNTING_KEY = "resident_accounting"

    @contextmanager
    def _defer_native_failure_learning(self) -> Iterator[None]:
        """Let the inherited loop persist a failure before cumulative learning.

        Only failure observations are deferred. Any success observation from a
        path not owned by the Body completion override keeps its existing
        semantics. The resident cycle is the ownership boundary for this narrow
        temporary interception.
        """

        self_model = self.kernel.self_model
        had_instance_override = "observe_native_outcome" in vars(self_model)
        previous_instance = vars(self_model).get("observe_native_outcome")
        original = self_model.observe_native_outcome

        def observe_after_checkpoint(
            task: str,
            capabilities=(),
            *,
            success: bool,
            quality: float = 1.0,
        ):
            if success:
                return original(
                    task,
                    capabilities,
                    success=success,
                    quality=quality,
                )
            return SelfModel.infer_domains(task, capabilities)

        self_model.observe_native_outcome = observe_after_checkpoint
        try:
            yield
        finally:
            if had_instance_override:
                self_model.observe_native_outcome = previous_instance
            else:
                delattr(self_model, "observe_native_outcome")

    def _record_failed_action(
        self,
        event,
        state,
        intent,
        *,
        source: str,
        failure: str,
        evidence_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        record = super()._record_failed_action(
            event,
            state,
            intent,
            source=source,
            failure=failure,
            evidence_fingerprint=evidence_fingerprint,
        )
        # Upgrade compatibility: a legacy record was already eagerly learned.
        # Only records produced by a fresh active failure receive a retryable
        # accounting descriptor.
        if str(source or "").strip().lower() != "legacy":
            domains = SelfModel.infer_domains(
                event.task,
                self._required_capabilities(event),
            )
            signature = str(record.get("signature_hash") or "").strip()
            fingerprint = str(record.get("evidence_fingerprint") or "").strip()
            if signature and fingerprint:
                record[self._BODY_FAILURE_ACCOUNTING_KEY] = {
                    "version": self._BODY_ACCOUNTING_VERSION,
                    "kind": "native_body_failure",
                    "domains": list(domains),
                    "failure_identity": f"{signature}\0{fingerprint}",
                    "applied": False,
                }
        return record

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        with self._defer_native_failure_learning():
            result = super()._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        self._apply_pending_body_failure_accounting(event, state)
        return result

    def _fail_postcondition_verification(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ) -> None:
        with self._defer_native_failure_learning():
            result = super()._fail_postcondition_verification(
                event,
                state,
                intent,
                failure=failure,
                thought=thought,
            )
        self._apply_pending_body_failure_accounting(event, state)
        return result

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        domains = SelfModel.infer_domains(
            event.task,
            self._required_capabilities(event),
        )
        completion = {
            "execution_path": ExecutionPath.BODY.value,
            "success": True,
            "response": str(response or ""),
            "model_invocations": 0,
            "reason": str(reason or ""),
        }
        state.stage = "native_completion"
        state.next_action = "publish terminal EventOutcome"
        state.data["native_domains"] = list(domains)
        state.data["native_completion"] = completion
        state.data[self._BODY_SUCCESS_ACCOUNTING_KEY] = {
            "version": self._BODY_ACCOUNTING_VERSION,
            "kind": "native_body_success",
            "domains": list(domains),
            "quality": 0.95,
        }
        self._sync_execution_context(event, state)
        # Semantic success first. The accounting journal is event-idempotent and
        # can be retried from native_completion without replaying the Body.
        self.store.save_working_state(state)
        self._apply_body_success_accounting(event, state)
        return self._native_completion_result(event, completion)

    def _resume_native_completion(self, event, state):
        result = super()._resume_native_completion(event, state)
        if result is not None and result.success:
            self._apply_body_success_accounting(event, state)
        return result

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        self._apply_pending_body_failure_accounting(event, state)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _apply_body_success_accounting(self, event, state) -> None:
        raw = state.data.get(self._BODY_SUCCESS_ACCOUNTING_KEY)
        # A native_completion persisted by an older build already used eager
        # Body accounting. Absence therefore means "already accounted" during
        # upgrade, matching the existing resident completion migration rule.
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise RuntimeError("native Body completion accounting checkpoint is malformed")
        if int(raw.get("version") or 0) != self._BODY_ACCOUNTING_VERSION:
            raise RuntimeError("native Body completion accounting version is unsupported")
        if str(raw.get("kind") or "") != "native_body_success":
            raise RuntimeError("native Body completion accounting kind is unsupported")
        self.resident_accounting.record_native_body_success(
            event_id=event.event_id,
            domains=tuple(raw.get("domains") or ()),
            quality=float(raw.get("quality", 0.95)),
        )

    def _apply_pending_body_failure_accounting(self, event, state) -> None:
        if str(state.current_event_id or "") != str(event.event_id):
            return
        raw_records = state.data.get(self._FAILED_ACTION_RECORDS_KEY)
        if not isinstance(raw_records, list):
            return
        changed = False
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            raw = item.get(self._BODY_FAILURE_ACCOUNTING_KEY)
            if not isinstance(raw, dict) or raw.get("applied") is True:
                continue
            if int(raw.get("version") or 0) != self._BODY_ACCOUNTING_VERSION:
                raise RuntimeError("native Body failure accounting version is unsupported")
            if str(raw.get("kind") or "") != "native_body_failure":
                raise RuntimeError("native Body failure accounting kind is unsupported")
            failure_identity = str(raw.get("failure_identity") or "").strip()
            if not failure_identity:
                raise RuntimeError("native Body failure accounting identity is missing")
            self.resident_accounting.record_native_body_failure(
                event_id=event.event_id,
                domains=tuple(raw.get("domains") or ()),
                failure_identity=failure_identity,
            )
            raw["applied"] = True
            changed = True
        if changed:
            # If this save is interrupted after the journal commit, restart sees
            # applied=False and safely retries the same journal key as a no-op.
            self.store.save_working_state(state)

    def _has_pending_body_failure_accounting(self, event, state) -> bool:
        if str(state.current_event_id or "") != str(event.event_id):
            return False
        raw_records = state.data.get(self._FAILED_ACTION_RECORDS_KEY)
        if not isinstance(raw_records, list):
            return False
        return any(
            isinstance(item, dict)
            and isinstance(item.get(self._BODY_FAILURE_ACCOUNTING_KEY), dict)
            and item[self._BODY_FAILURE_ACCOUNTING_KEY].get("applied") is not True
            for item in raw_records
        )

    def _preserve_working_truth_on_exception(self, event, state) -> bool:
        if self._has_pending_body_failure_accounting(event, state):
            return True
        return super()._preserve_working_truth_on_exception(event, state)

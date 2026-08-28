from __future__ import annotations

"""Crash-safe cumulative accounting around active resident Body outcomes."""

from contextlib import contextmanager
from typing import Any, Iterator

from .capability_recovery_resident import CapabilityRecoveryResidentRuntime
from .self_model import SelfModel


class DurableBodyAccountingResidentRuntime(CapabilityRecoveryResidentRuntime):
    """Persist Body semantic truth before updating cumulative self evidence.

    The inherited Body hierarchy contains deliberately different completion
    owners. Ordinary verified Body work credits native competence, while narrow
    pointer/UI effect owners may count a completed task without generalizing that
    local effect into ability. This wrapper therefore does not construct Body
    completion truth. It lets the existing most-specific owner build and persist
    its semantic checkpoint while temporarily deferring only the cumulative
    writes that owner actually attempted.

    Failure learning follows the same rule: only an inherited path that actually
    called ``observe_native_outcome(..., success=False)`` receives a retryable
    failure-accounting descriptor. Merely recording a failure/recovery fact does
    not create new learning semantics.
    """

    _BODY_ACCOUNTING_VERSION = 1
    _BODY_SUCCESS_ACCOUNTING_KEY = "native_body_completion_accounting"
    _BODY_FAILURE_ACCOUNTING_KEY = "resident_accounting"

    @contextmanager
    def _defer_native_failure_learning(self) -> Iterator[dict[str, Any]]:
        """Capture inherited failure learning until its semantic fact is durable."""

        self_model = self.kernel.self_model
        had_instance_override = "observe_native_outcome" in vars(self_model)
        previous_instance = vars(self_model).get("observe_native_outcome")
        original = self_model.observe_native_outcome
        capture: dict[str, Any] = {"pending_failure_domains": None}

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
            domains = SelfModel.infer_domains(task, capabilities)
            capture["pending_failure_domains"] = tuple(domains)
            return domains

        self_model.observe_native_outcome = observe_after_checkpoint
        previous_capture = getattr(self, "_body_failure_capture", None)
        self._body_failure_capture = capture
        try:
            yield capture
        finally:
            if previous_capture is None:
                try:
                    delattr(self, "_body_failure_capture")
                except AttributeError:
                    pass
            else:
                self._body_failure_capture = previous_capture
            if had_instance_override:
                self_model.observe_native_outcome = previous_instance
            else:
                delattr(self_model, "observe_native_outcome")

    @contextmanager
    def _defer_native_success_accounting(
        self,
        state,
    ) -> Iterator[dict[str, Any]]:
        """Let the inherited completion owner persist truth before accounting.

        ``observe_native_outcome(success=True)`` and ``record_runtime_task`` are
        the two cumulative writes used by existing Body completion owners. Their
        interception happens before those owners call ``save_working_state``, so
        the accounting descriptor is included in the same first durable semantic
        checkpoint rather than being attached in a later crash window.
        """

        self_model = self.kernel.self_model
        store = self.store
        had_model_override = "observe_native_outcome" in vars(self_model)
        previous_model = vars(self_model).get("observe_native_outcome")
        original_model = self_model.observe_native_outcome
        had_store_override = "record_runtime_task" in vars(store)
        previous_store = vars(store).get("record_runtime_task")
        original_store = store.record_runtime_task
        capture: dict[str, Any] = {
            "success_domains": None,
            "success_quality": None,
            "task_accounting_requested": False,
        }

        def observe_after_checkpoint(
            task: str,
            capabilities=(),
            *,
            success: bool,
            quality: float = 1.0,
        ):
            if not success:
                return original_model(
                    task,
                    capabilities,
                    success=success,
                    quality=quality,
                )
            domains = SelfModel.infer_domains(task, capabilities)
            capture["success_domains"] = tuple(domains)
            capture["success_quality"] = max(0.0, min(1.0, float(quality)))
            return domains

        def record_after_checkpoint(
            *,
            model_invocations: int,
            prompt_tokens: int = 0,
            completion_tokens: int = 0,
        ) -> None:
            # Body completion owners currently count native work only. Preserve
            # that contract fail-closed if a future caller tries to smuggle model
            # accounting through this interception point.
            if (
                int(model_invocations) != 0
                or int(prompt_tokens) != 0
                or int(completion_tokens) != 0
            ):
                return original_store(
                    model_invocations=model_invocations,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            capture["task_accounting_requested"] = True
            domains = capture.get("success_domains")
            if domains:
                state.data[self._BODY_SUCCESS_ACCOUNTING_KEY] = {
                    "version": self._BODY_ACCOUNTING_VERSION,
                    "kind": "native_body_success",
                    "domains": list(domains),
                    "quality": float(capture.get("success_quality") or 0.95),
                }
            else:
                state.data[self._BODY_SUCCESS_ACCOUNTING_KEY] = {
                    "version": self._BODY_ACCOUNTING_VERSION,
                    "kind": "native_body_task",
                }

        self_model.observe_native_outcome = observe_after_checkpoint
        store.record_runtime_task = record_after_checkpoint
        try:
            yield capture
        finally:
            if had_store_override:
                store.record_runtime_task = previous_store
            else:
                delattr(store, "record_runtime_task")
            if had_model_override:
                self_model.observe_native_outcome = previous_model
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
        capture = getattr(self, "_body_failure_capture", None)
        domains = (
            capture.get("pending_failure_domains")
            if isinstance(capture, dict)
            else None
        )
        if domains:
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
                capture["pending_failure_domains"] = None
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
        with self._defer_native_success_accounting(state):
            result = super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )
        if result is not None and result.success:
            self._apply_body_success_accounting(event, state)
        return result

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
        kind = str(raw.get("kind") or "")
        if kind == "native_body_success":
            self.resident_accounting.record_native_body_success(
                event_id=event.event_id,
                domains=tuple(raw.get("domains") or ()),
                quality=float(raw.get("quality", 0.95)),
            )
            return
        if kind == "native_body_task":
            self.resident_accounting.record_native_body_task(event_id=event.event_id)
            return
        raise RuntimeError("native Body completion accounting kind is unsupported")

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

from __future__ import annotations

"""Add one narrow, read-only verified UI-state completion scope to pointer clicks."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from .models import ExecutionPath, ResidentRunResult, utc_now
from .pointer_click_completion_resident import EffectScopedPointerClickResidentRuntime
from .pointer_click_resident import VerifiedPointerClickResidentRuntime


class SemanticPointerClickResidentRuntime(EffectScopedPointerClickResidentRuntime):
    """Complete only a typed foreground-window state proven by fresh OS evidence."""

    _UI_EVENT_KIND = "ui_state_transition"
    _UI_SCOPE_KIND = "foreground_window_matches"
    _SEMANTIC_PRECONDITION_KEY = "native_pointer_click_semantic_precondition"
    _SEMANTIC_VERIFICATION_KEY = "native_pointer_click_semantic_verification"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.foreground_window = NativeForegroundWindowSense()

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw_scope = event.payload.get("completion_scope")
        scope_kind = (
            str(raw_scope.get("kind") or "").strip().lower()
            if isinstance(raw_scope, dict)
            else ""
        )
        if scope_kind != self._UI_SCOPE_KIND:
            return super()._pointer_click_contract(event, intent)

        contract, error = VerifiedPointerClickResidentRuntime._pointer_click_contract(
            self,
            event,
            intent,
        )
        if error:
            return contract, error
        assert contract is not None

        scope, scope_error = self._ui_completion_scope(event)
        if scope_error:
            return None, scope_error
        assert scope is not None
        event_kind = str(event.kind or "").strip().lower()
        if event_kind != self._UI_EVENT_KIND:
            return None, (
                "foreground_window_matches pointer_click completion is permitted only for "
                "ui_state_transition events"
            )
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, (
                "ui_state_transition pointer_click requires the resident-owned foreground "
                "window Sense before any pointer movement or input"
            )
        action_precondition, precondition_error = self._ui_action_precondition(event)
        if precondition_error:
            return None, precondition_error
        return {
            **contract,
            "completion_scope": scope,
            "completion_event_kind": event_kind,
            "action_precondition": action_precondition,
        }, None

    def _pointer_click_action_step(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ):
        contract, error = self._pointer_click_contract(event, intent)
        if error:
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                error,
                thought=thought,
            )
        assert contract is not None
        scope = contract.get("completion_scope")
        if not isinstance(scope, dict) or scope.get("kind") != self._UI_SCOPE_KIND:
            return super()._pointer_click_action_step(
                event,
                state,
                intent,
                thought=thought,
            )

        action_precondition = contract.get("action_precondition")
        prepared = state.data.get(self._POINTER_CLICK_PRECONDITION_KEY)
        same_preparation = (
            isinstance(prepared, dict)
            and str(prepared.get("intent_id") or "") == intent.intent_id
            and bool(prepared.get("position_verified"))
        )

        if not same_preparation:
            observed, probe_error = self._probe_foreground_window()
            if observed is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window preflight was unavailable: "
                    + str(probe_error or "unknown foreground-window error"),
                    thought=thought,
                )
            if self._foreground_window_matches(observed, scope):
                state.data[self._SEMANTIC_VERIFICATION_KEY] = self._verification(
                    observed,
                    scope,
                    verified=True,
                    before_input=True,
                )
                return self._complete_ui_scope(
                    event,
                    state,
                    scope,
                    response=self._response(observed),
                    reason=(
                        "ZN completed this ui_state_transition because fresh foreground-window "
                        "evidence already matched the exact structured completion scope; no "
                        "pointer input was sent"
                    ),
                )
            if not isinstance(action_precondition, dict):
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "ui_state_transition pointer input requires an explicit exact "
                    "action_precondition.kind=foreground_window_matches",
                    thought=thought,
                )

            admitted = self._semantic_admission(
                event,
                intent,
                scope,
                action_precondition,
                observed,
                verified=self._foreground_window_matches(observed, action_precondition),
            )
            state.data[self._SEMANTIC_PRECONDITION_KEY] = admitted
            if not admitted["verified"]:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window evidence did not match the exact structured "
                    "action_precondition before pointer movement: "
                    + self._response(observed),
                    thought=thought,
                )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        else:
            admission_error = self._semantic_admission_error(
                event,
                state,
                intent,
                scope,
                action_precondition,
            )
            if admission_error:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    admission_error,
                    thought=thought,
                )

        return super()._pointer_click_action_step(
            event,
            state,
            intent,
            thought=thought,
        )

    def _pointer_click_final_input_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        contract: dict[str, Any],
        prepared: dict[str, Any],
    ) -> str | None:
        scope = contract.get("completion_scope")
        if not isinstance(scope, dict) or scope.get("kind") != self._UI_SCOPE_KIND:
            return super()._pointer_click_final_input_precondition(
                event,
                state,
                intent,
                contract,
                prepared,
            )

        action_precondition = contract.get("action_precondition")
        admission_error = self._semantic_admission_error(
            event,
            state,
            intent,
            scope,
            action_precondition,
        )
        if admission_error:
            return admission_error
        assert isinstance(action_precondition, dict)

        observed, probe_error = self._probe_foreground_window()
        if observed is None:
            return (
                "final foreground-window recheck before pointer input was unavailable: "
                + str(probe_error or "unknown foreground-window error")
            )

        verified = self._foreground_window_matches(observed, action_precondition)
        admission = dict(state.data[self._SEMANTIC_PRECONDITION_KEY])
        admission["reverified"] = bool(verified)
        admission["reverified_observation"] = asdict(observed)
        admission["reverified_at"] = utc_now()
        admission["reverified_phase"] = "final_before_pointer_input"
        state.data[self._SEMANTIC_PRECONDITION_KEY] = admission
        if not verified:
            return (
                "foreground window drifted at the final input boundary after the visual baseline; "
                "refusing pointer input because fresh evidence no longer matches "
                "action_precondition: "
                + self._response(observed)
            )
        return None

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult | None:
        raw_scope = event.payload.get("completion_scope")
        if (
            intent.kind != "pointer_click"
            or not isinstance(raw_scope, dict)
            or str(raw_scope.get("kind") or "").strip().lower() != self._UI_SCOPE_KIND
        ):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        scope, scope_error = self._ui_completion_scope(event)
        if scope_error or scope is None:
            return self._fail_ui_completion(
                event,
                state,
                intent,
                str(scope_error or "unknown completion-scope error"),
            )
        action_precondition, precondition_error = self._ui_action_precondition(event)
        if precondition_error:
            return self._fail_ui_completion(
                event,
                state,
                intent,
                precondition_error,
            )

        admitted = state.data.get("native_verification")
        admitted_scope = admitted.get("completion_scope") if isinstance(admitted, dict) else None
        admitted_kind = (
            str(admitted.get("completion_event_kind") or "").strip().lower()
            if isinstance(admitted, dict)
            else ""
        )
        admitted_precondition = (
            admitted.get("action_precondition") if isinstance(admitted, dict) else None
        )
        semantic_admission = state.data.get(self._SEMANTIC_PRECONDITION_KEY)
        semantic_scope = (
            semantic_admission.get("completion_scope")
            if isinstance(semantic_admission, dict)
            else None
        )
        semantic_precondition = (
            semantic_admission.get("action_precondition")
            if isinstance(semantic_admission, dict)
            else None
        )
        semantic_kind = (
            str(semantic_admission.get("completion_event_kind") or "").strip().lower()
            if isinstance(semantic_admission, dict)
            else ""
        )
        semantic_intent_id = (
            str(semantic_admission.get("intent_id") or "")
            if isinstance(semantic_admission, dict)
            else ""
        )
        semantic_reverified = bool(
            semantic_admission.get("reverified")
            if isinstance(semantic_admission, dict)
            else False
        )
        current_event_kind = str(event.kind or "").strip().lower()
        if (
            not isinstance(action_precondition, dict)
            or not isinstance(admitted_scope, dict)
            or dict(admitted_scope) != scope
            or admitted_kind != current_event_kind
            or not isinstance(admitted_precondition, dict)
            or dict(admitted_precondition) != action_precondition
            or semantic_intent_id != intent.intent_id
            or not isinstance(semantic_scope, dict)
            or dict(semantic_scope) != scope
            or semantic_kind != current_event_kind
            or not isinstance(semantic_precondition, dict)
            or dict(semantic_precondition) != action_precondition
            or not semantic_reverified
        ):
            return self._fail_ui_completion(
                event,
                state,
                intent,
                "the admitted event kind/completion_scope/action_precondition drifted after "
                "pointer input",
            )

        observed, probe_error = self._probe_foreground_window()
        verified = observed is not None and self._foreground_window_matches(observed, scope)
        state.data[self._SEMANTIC_VERIFICATION_KEY] = (
            self._verification(observed, scope, verified=verified, before_input=False)
            if observed is not None
            else {
                "verified": False,
                "kind": self._UI_SCOPE_KIND,
                "before_input": False,
                "error": str(probe_error or "foreground-window observation unavailable"),
            }
        )
        if observed is not None and verified:
            return self._complete_ui_scope(
                event,
                state,
                scope,
                response=self._response(observed),
                reason=(
                    "ZN completed this ui_state_transition only after the bounded click effect "
                    "was independently observed and a fresh foreground-window Sense exactly "
                    "matched the structured process/title completion scope; task prose was not "
                    "used as completion evidence"
                ),
            )

        detail = self._response(observed) if observed is not None else str(probe_error)
        return self._fail_ui_completion(
            event,
            state,
            intent,
            "fresh foreground-window evidence did not match the exact structured scope: " + detail,
        )

    def _complete_ui_scope(
        self,
        event,
        state,
        scope: dict[str, str],
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult:
        completion = {
            "execution_path": ExecutionPath.BODY.value,
            "success": True,
            "response": str(response or ""),
            "model_invocations": 0,
            "reason": str(reason or ""),
        }
        state.stage = "native_completion"
        state.next_action = "publish terminal EventOutcome"
        state.data["native_completion_scope"] = dict(scope)
        state.data["native_completion"] = completion
        self._sync_execution_context(event, state)
        self.store.record_runtime_task(model_invocations=0)
        # Semantic/focused/UIA/text completion is already established by each
        # caller's fresh typed evidence. Persist only that established result so
        # restart can reach terminal EventOutcome without re-entering UI sensing,
        # input, verification, or ordinary runtime task accounting.
        self.store.save_working_state(state)
        return self._native_completion_result(event, completion)

    def _fail_ui_completion(self, event, state, intent: NativeActionIntent, failure: str) -> None:
        message = "pointer click semantic completion failed: " + str(failure)
        state.data["local_failure"] = message
        self._record_failed_action(
            event,
            state,
            intent,
            source="verification",
            failure=message,
        )
        state.stage = "native_investigation"
        state.next_action = (
            "investigate the contradicted semantic UI state without replaying pointer input"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _ui_completion_scope(
        self,
        event,
    ) -> tuple[dict[str, str] | None, str | None]:
        raw = event.payload.get("completion_scope")
        return self._foreground_window_scope(raw, field_name="completion_scope")

    def _ui_action_precondition(
        self,
        event,
    ) -> tuple[dict[str, str] | None, str | None]:
        if "action_precondition" not in event.payload or event.payload.get("action_precondition") is None:
            return None, None
        raw = event.payload.get("action_precondition")
        return self._foreground_window_scope(raw, field_name="action_precondition")

    def _foreground_window_scope(
        self,
        raw: Any,
        *,
        field_name: str,
    ) -> tuple[dict[str, str] | None, str | None]:
        if not isinstance(raw, dict) or str(raw.get("kind") or "").strip().lower() != self._UI_SCOPE_KIND:
            if field_name == "completion_scope":
                return None, (
                    "ui_state_transition requires completion_scope.kind=foreground_window_matches"
                )
            return None, (
                "ui_state_transition action_precondition must use "
                "kind=foreground_window_matches"
            )
        unknown = sorted(
            str(key)
            for key in raw
            if key not in {"kind", "process_name", "title_equals"}
        )
        if unknown:
            return None, (
                f"foreground_window_matches {field_name} contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        if not process_name or not title:
            return None, (
                f"foreground_window_matches {field_name} requires exact non-empty "
                "process_name and title_equals"
            )
        return {
            "kind": self._UI_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
        }, None

    def _semantic_admission(
        self,
        event,
        intent: NativeActionIntent,
        scope: dict[str, str],
        action_precondition: dict[str, str],
        observed: ForegroundWindowObservation,
        *,
        verified: bool,
    ) -> dict[str, Any]:
        return {
            "intent_id": intent.intent_id,
            "verified": bool(verified),
            "completion_event_kind": str(event.kind or "").strip().lower(),
            "completion_scope": dict(scope),
            "action_precondition": dict(action_precondition),
            "initial_observation": asdict(observed),
            "admitted_at": utc_now(),
        }

    def _semantic_admission_error(
        self,
        event,
        state,
        intent: NativeActionIntent,
        scope: dict[str, str],
        action_precondition: Any,
    ) -> str | None:
        if not isinstance(action_precondition, dict):
            return (
                "ui_state_transition pointer input lost its explicit exact "
                "action_precondition before click delivery"
            )
        admitted = state.data.get(self._SEMANTIC_PRECONDITION_KEY)
        if not isinstance(admitted, dict) or not bool(admitted.get("verified")):
            return "pointer click lost its admitted foreground action precondition"
        admitted_scope = admitted.get("completion_scope")
        admitted_precondition = admitted.get("action_precondition")
        admitted_kind = str(admitted.get("completion_event_kind") or "").strip().lower()
        if (
            str(admitted.get("intent_id") or "") != intent.intent_id
            or not isinstance(admitted_scope, dict)
            or dict(admitted_scope) != scope
            or not isinstance(admitted_precondition, dict)
            or dict(admitted_precondition) != action_precondition
            or admitted_kind != str(event.kind or "").strip().lower()
        ):
            return (
                "the admitted event kind/completion_scope/action_precondition drifted after "
                "pointer preparation; refusing input"
            )
        return None

    def _probe_foreground_window(
        self,
    ) -> tuple[ForegroundWindowObservation | None, str | None]:
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned foreground window Sense is unavailable"
        try:
            return sense.probe(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _foreground_window_matches(
        observed: ForegroundWindowObservation,
        scope: dict[str, str],
    ) -> bool:
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and str(observed.title or "").strip() == scope["title_equals"]
        )

    @staticmethod
    def _response(observed: ForegroundWindowObservation) -> str:
        return f"foreground window process={observed.process_name!s} title={observed.title!r}"

    def _verification(
        self,
        observed: ForegroundWindowObservation,
        scope: dict[str, str],
        *,
        verified: bool,
        before_input: bool,
    ) -> dict[str, Any]:
        return {
            "verified": bool(verified),
            "kind": self._UI_SCOPE_KIND,
            "before_input": bool(before_input),
            "expected_process_name": scope["process_name"],
            "expected_title": scope["title_equals"],
            "observed_process_id": int(observed.process_id),
            "observed_process_name": observed.process_name,
            "observed_title": observed.title,
            "observed_class_name": observed.class_name,
            "observation": asdict(observed),
        }

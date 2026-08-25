from __future__ import annotations

"""Bind a semantic pointer click to exact focused native-control evidence."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .focused_control_sense import FocusedControlObservation, NativeFocusedControlSense
from .models import ResidentRunResult, utc_now
from .pointer_click_resident import VerifiedPointerClickResidentRuntime
from .pointer_click_semantic_resident import SemanticPointerClickResidentRuntime


class FocusedControlPointerClickResidentRuntime(SemanticPointerClickResidentRuntime):
    """Verify one deeper native UI state without widening click authority."""

    _FOCUSED_SCOPE_KIND = "focused_control_matches"
    _FOCUSED_VERIFICATION_KEY = "native_pointer_click_focused_control_verification"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.focused_control = NativeFocusedControlSense()

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
        if scope_kind != self._FOCUSED_SCOPE_KIND:
            return super()._pointer_click_contract(event, intent)

        contract, error = VerifiedPointerClickResidentRuntime._pointer_click_contract(
            self,
            event,
            intent,
        )
        if error:
            return contract, error
        assert contract is not None

        scope, scope_error = self._focused_completion_scope(event)
        if scope_error:
            return None, scope_error
        assert scope is not None
        event_kind = str(event.kind or "").strip().lower()
        if event_kind != self._UI_EVENT_KIND:
            return None, (
                "focused_control_matches pointer_click completion is permitted only for "
                "ui_state_transition events"
            )
        foreground = getattr(self, "foreground_window", None)
        if foreground is None or not callable(getattr(foreground, "probe", None)):
            return None, (
                "focused-control pointer_click requires the resident-owned foreground "
                "window Sense before any pointer movement or input"
            )
        focused = getattr(self, "focused_control", None)
        if focused is None or not callable(getattr(focused, "probe", None)):
            return None, (
                "focused-control pointer_click requires the resident-owned focused-control "
                "Sense before any pointer movement or input"
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
        if not isinstance(scope, dict) or scope.get("kind") != self._FOCUSED_SCOPE_KIND:
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
            focused, focused_error = self._probe_focused_control()
            if focused is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh focused-control preflight was unavailable: "
                    + str(focused_error or "unknown focused-control error"),
                    thought=thought,
                )
            if self._focused_control_matches(focused, scope):
                state.data[self._FOCUSED_VERIFICATION_KEY] = self._focused_verification(
                    focused,
                    scope,
                    verified=True,
                    before_input=True,
                )
                return self._complete_ui_scope(
                    event,
                    state,
                    scope,
                    response=self._focused_response(focused),
                    reason=(
                        "ZN completed this ui_state_transition because fresh resident-owned "
                        "GUI-thread evidence already matched the exact focused native-control "
                        "scope; no pointer input was sent"
                    ),
                )
            if not isinstance(action_precondition, dict):
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "focused-control pointer input requires an explicit exact "
                    "action_precondition.kind=foreground_window_matches",
                    thought=thought,
                )

            foreground, foreground_error = self._probe_foreground_window()
            if foreground is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window source preflight was unavailable: "
                    + str(foreground_error or "unknown foreground-window error"),
                    thought=thought,
                )
            admitted = self._semantic_admission(
                event,
                intent,
                scope,
                action_precondition,
                foreground,
                verified=self._foreground_window_matches(
                    foreground,
                    action_precondition,
                ),
            )
            state.data[self._SEMANTIC_PRECONDITION_KEY] = admitted
            if not admitted["verified"]:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window evidence did not match the exact structured "
                    "action_precondition before pointer movement: "
                    + self._response(foreground),
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
        if not isinstance(scope, dict) or scope.get("kind") != self._FOCUSED_SCOPE_KIND:
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
                "final foreground-window recheck before focused-control pointer input was "
                "unavailable: "
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
                "foreground window drifted at the final focused-control input boundary after "
                "the visual baseline; refusing pointer input because fresh evidence no longer "
                "matches action_precondition: "
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
            or str(raw_scope.get("kind") or "").strip().lower()
            != self._FOCUSED_SCOPE_KIND
        ):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        scope, scope_error = self._focused_completion_scope(event)
        if scope_error or scope is None:
            return self._fail_ui_completion(
                event,
                state,
                intent,
                str(scope_error or "unknown focused-control completion-scope error"),
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

        observed, probe_error = self._probe_focused_control()
        verified = observed is not None and self._focused_control_matches(observed, scope)
        state.data[self._FOCUSED_VERIFICATION_KEY] = (
            self._focused_verification(
                observed,
                scope,
                verified=verified,
                before_input=False,
            )
            if observed is not None
            else {
                "verified": False,
                "kind": self._FOCUSED_SCOPE_KIND,
                "before_input": False,
                "error": str(probe_error or "focused-control observation unavailable"),
            }
        )
        if observed is not None and verified:
            return self._complete_ui_scope(
                event,
                state,
                scope,
                response=self._focused_response(observed),
                reason=(
                    "ZN completed this ui_state_transition only after the bounded click effect "
                    "was independently observed and fresh resident-owned GUI-thread evidence "
                    "exactly matched the structured foreground process/title plus focused "
                    "native-control class/id scope; task prose was not used as completion evidence"
                ),
            )

        detail = self._focused_response(observed) if observed is not None else str(probe_error)
        return self._fail_ui_completion(
            event,
            state,
            intent,
            "fresh focused-control evidence did not match the exact structured scope: "
            + detail,
        )

    def _focused_completion_scope(
        self,
        event,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = event.payload.get("completion_scope")
        if not isinstance(raw, dict) or str(raw.get("kind") or "").strip().lower() != self._FOCUSED_SCOPE_KIND:
            return None, (
                "ui_state_transition requires "
                "completion_scope.kind=focused_control_matches"
            )
        unknown = sorted(
            str(key)
            for key in raw
            if key
            not in {
                "kind",
                "process_name",
                "title_equals",
                "control_class_name",
                "control_id",
            }
        )
        if unknown:
            return None, (
                "focused_control_matches completion_scope contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        control_class_name = str(raw.get("control_class_name") or "").strip()
        raw_control_id = raw.get("control_id")
        if isinstance(raw_control_id, bool):
            return None, "focused_control_matches control_id must be a positive integer"
        try:
            control_id = int(raw_control_id)
        except (TypeError, ValueError):
            control_id = 0
        if not process_name or not title or not control_class_name or control_id <= 0:
            return None, (
                "focused_control_matches requires exact non-empty process_name, title_equals, "
                "control_class_name, and a positive control_id"
            )
        return {
            "kind": self._FOCUSED_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
            "control_class_name": control_class_name,
            "control_id": control_id,
        }, None

    def _probe_focused_control(
        self,
    ) -> tuple[FocusedControlObservation | None, str | None]:
        sense = getattr(self, "focused_control", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned focused-control Sense is unavailable"
        try:
            return sense.probe(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _focused_control_matches(
        observed: FocusedControlObservation,
        scope: dict[str, Any],
    ) -> bool:
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and str(observed.foreground_title or "").strip() == scope["title_equals"]
            and str(observed.control_class_name or "").strip()
            == scope["control_class_name"]
            and int(observed.control_id) == int(scope["control_id"])
            and bool(observed.enabled)
            and bool(observed.visible)
        )

    @staticmethod
    def _focused_response(observed: FocusedControlObservation) -> str:
        return (
            f"foreground process={observed.process_name!s} "
            f"title={observed.foreground_title!r} focused_control="
            f"{observed.control_class_name!r}#{observed.control_id} "
            f"enabled={observed.enabled} visible={observed.visible}"
        )

    def _focused_verification(
        self,
        observed: FocusedControlObservation,
        scope: dict[str, Any],
        *,
        verified: bool,
        before_input: bool,
    ) -> dict[str, Any]:
        return {
            "verified": bool(verified),
            "kind": self._FOCUSED_SCOPE_KIND,
            "before_input": bool(before_input),
            "expected_process_name": scope["process_name"],
            "expected_title": scope["title_equals"],
            "expected_control_class_name": scope["control_class_name"],
            "expected_control_id": int(scope["control_id"]),
            "observation": asdict(observed),
        }

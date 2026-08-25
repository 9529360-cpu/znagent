from __future__ import annotations

"""Verify one click by read-only Windows UI Automation focus evidence."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .automation_element_sense import AutomationElementObservation, NativeAutomationElementSense
from .models import ResidentRunResult, utc_now
from .pointer_click_focused_control_resident import FocusedControlPointerClickResidentRuntime
from .pointer_click_resident import VerifiedPointerClickResidentRuntime


class AutomationFocusPointerClickResidentRuntime(FocusedControlPointerClickResidentRuntime):
    """Require focus to land on the exact UIA element captured before input.

    UI Automation is a read-only Sense. The target is identified by an opaque
    RuntimeId for the current action cycle and may be narrowed by exact cached
    control type/class evidence. AutomationId remains bounded diagnostic evidence,
    not durable identity or execution authority. No UIA tree walk, event
    subscription, control pattern, dynamic Name read, or mutation method is used.
    """

    _AUTOMATION_SCOPE_KIND = "focused_automation_element_at_pointer"
    _AUTOMATION_TARGET_KEY = "native_pointer_click_automation_target"
    _AUTOMATION_VERIFICATION_KEY = "native_pointer_click_automation_verification"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.automation_element = NativeAutomationElementSense()

    def _pointer_click_contract(
        self, event, intent: NativeActionIntent
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw_scope = event.payload.get("completion_scope")
        scope_kind = (
            str(raw_scope.get("kind") or "").strip().lower()
            if isinstance(raw_scope, dict)
            else ""
        )
        if scope_kind != self._AUTOMATION_SCOPE_KIND:
            return super()._pointer_click_contract(event, intent)

        contract, error = VerifiedPointerClickResidentRuntime._pointer_click_contract(
            self, event, intent
        )
        if error:
            return contract, error
        assert contract is not None

        scope, error = self._automation_completion_scope(event)
        if error:
            return None, error
        assert scope is not None
        if str(event.kind or "").strip().lower() != self._UI_EVENT_KIND:
            return None, (
                "focused_automation_element_at_pointer is permitted only for "
                "ui_state_transition pointer_click events"
            )
        foreground = getattr(self, "foreground_window", None)
        if foreground is None or not callable(getattr(foreground, "probe", None)):
            return None, "automation-focus pointer_click requires the foreground-window Sense"
        automation = getattr(self, "automation_element", None)
        if (
            automation is None
            or not callable(getattr(automation, "probe_at_point", None))
            or not callable(getattr(automation, "probe_focused", None))
        ):
            return None, (
                "automation-focus pointer_click requires the resident-owned read-only "
                "automation-element Sense"
            )

        action_precondition, error = self._ui_action_precondition(event)
        if error:
            return None, error
        if not isinstance(action_precondition, dict):
            return None, (
                "focused_automation_element_at_pointer requires an explicit exact "
                "action_precondition.kind=foreground_window_matches"
            )
        if (
            action_precondition.get("process_name") != scope["process_name"]
            or action_precondition.get("title_equals") != scope["title_equals"]
        ):
            return None, (
                "focused_automation_element_at_pointer requires action_precondition to match "
                "the same exact foreground process/title as completion_scope"
            )
        return {
            **contract,
            "completion_scope": scope,
            "completion_event_kind": self._UI_EVENT_KIND,
            "action_precondition": action_precondition,
        }, None

    def _pointer_click_action_step(
        self, event, state, intent: NativeActionIntent, *, thought=None
    ):
        contract, error = self._pointer_click_contract(event, intent)
        if error:
            return self._fail_pointer_click_precondition(
                event, state, intent, error, thought=thought
            )
        assert contract is not None
        scope = contract.get("completion_scope")
        if not isinstance(scope, dict) or scope.get("kind") != self._AUTOMATION_SCOPE_KIND:
            return super()._pointer_click_action_step(event, state, intent, thought=thought)

        action_precondition = contract["action_precondition"]
        prepared = state.data.get(self._POINTER_CLICK_PRECONDITION_KEY)
        same_preparation = (
            isinstance(prepared, dict)
            and str(prepared.get("intent_id") or "") == intent.intent_id
            and bool(prepared.get("position_verified"))
        )
        if not same_preparation:
            foreground, probe_error = self._probe_foreground_window()
            if foreground is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window preflight for automation focus was unavailable: "
                    + str(probe_error or "unknown foreground-window error"),
                    thought=thought,
                )

            if self._foreground_window_matches(foreground, scope):
                target, _ = self._probe_target_element_from_contract(event, contract)
                focused, _ = self._probe_focused_automation_element()
                if (
                    target is not None
                    and focused is not None
                    and self._automation_element_eligible(target, scope)
                    and self._automation_element_eligible(focused, scope)
                    and focused.has_keyboard_focus
                    and self._same_runtime_id(target, focused)
                ):
                    state.data[self._AUTOMATION_VERIFICATION_KEY] = (
                        self._automation_verification(
                            target, focused, scope, verified=True, before_input=True
                        )
                    )
                    return self._complete_ui_scope(
                        event,
                        state,
                        scope,
                        response=self._automation_response(focused),
                        reason=(
                            "ZN completed this ui_state_transition because the exact UI "
                            "Automation element at the structured pointer target already had "
                            "keyboard focus; no pointer movement or input was sent"
                        ),
                    )

            admitted = self._semantic_admission(
                event,
                intent,
                scope,
                action_precondition,
                foreground,
                verified=self._foreground_window_matches(
                    foreground, action_precondition
                ),
            )
            state.data[self._SEMANTIC_PRECONDITION_KEY] = admitted
            if not admitted["verified"]:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window evidence did not match the exact structured "
                    "action_precondition before automation-focus pointer movement: "
                    + self._response(foreground),
                    thought=thought,
                )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        else:
            error = self._semantic_admission_error(
                event, state, intent, scope, action_precondition
            )
            if error:
                return self._fail_pointer_click_precondition(
                    event, state, intent, error, thought=thought
                )

        return super()._pointer_click_action_step(event, state, intent, thought=thought)

    def _pointer_click_final_input_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        contract: dict[str, Any],
        prepared: dict[str, Any],
    ) -> str | None:
        scope = contract.get("completion_scope")
        if not isinstance(scope, dict) or scope.get("kind") != self._AUTOMATION_SCOPE_KIND:
            return super()._pointer_click_final_input_precondition(
                event, state, intent, contract, prepared
            )

        action_precondition = contract["action_precondition"]
        error = self._semantic_admission_error(
            event, state, intent, scope, action_precondition
        )
        if error:
            return error

        foreground, probe_error = self._probe_foreground_window()
        if foreground is None:
            return (
                "final foreground-window recheck before automation-focus pointer input was "
                "unavailable: " + str(probe_error or "unknown foreground-window error")
            )
        verified_source = self._foreground_window_matches(
            foreground, action_precondition
        )
        admission = dict(state.data[self._SEMANTIC_PRECONDITION_KEY])
        admission.update(
            {
                "reverified": bool(verified_source),
                "reverified_observation": asdict(foreground),
                "reverified_at": utc_now(),
                "reverified_phase": "final_before_pointer_input",
            }
        )
        state.data[self._SEMANTIC_PRECONDITION_KEY] = admission
        if not verified_source:
            return (
                "foreground window drifted at the final automation-focus input boundary after "
                "the visual baseline; refusing pointer input because fresh evidence no longer "
                "matches action_precondition: " + self._response(foreground)
            )

        target_x = prepared.get("target_x")
        target_y = prepared.get("target_y")
        if (
            isinstance(target_x, bool)
            or isinstance(target_y, bool)
            or not isinstance(target_x, int)
            or not isinstance(target_y, int)
        ):
            return "automation-focus click lost its exact prepared target coordinates"
        target, error = self._probe_automation_element_at_point(target_x, target_y)
        if target is None:
            return "final UI Automation target probe before pointer input was unavailable: " + str(error)
        if not self._automation_element_eligible(target, scope):
            return (
                "the UI Automation element at the final pointer target does not match the exact "
                "typed completion scope or is not enabled, on-screen and keyboard-focusable; "
                "refusing pointer input"
            )
        state.data[self._AUTOMATION_TARGET_KEY] = {
            "intent_id": intent.intent_id,
            "runtime_id": list(target.runtime_id),
            "observation": asdict(target),
            "captured_at": utc_now(),
            "phase": "final_before_pointer_input",
        }
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
            != self._AUTOMATION_SCOPE_KIND
        ):
            return super()._complete_successful_body_action(
                event, state, intent, response=response, reason=reason
            )

        scope, error = self._automation_completion_scope(event)
        if error or scope is None:
            return self._fail_ui_completion(
                event, state, intent, str(error or "invalid automation-focus scope")
            )
        action_precondition, error = self._ui_action_precondition(event)
        if error or not isinstance(action_precondition, dict):
            return self._fail_ui_completion(
                event, state, intent, str(error or "missing source action_precondition")
            )
        error = self._post_admission_error(
            event, state, intent, scope, action_precondition
        )
        if error:
            return self._fail_ui_completion(event, state, intent, error)

        target_record = state.data.get(self._AUTOMATION_TARGET_KEY)
        if (
            not isinstance(target_record, dict)
            or str(target_record.get("intent_id") or "") != intent.intent_id
            or not isinstance(target_record.get("runtime_id"), list)
            or not target_record["runtime_id"]
        ):
            return self._fail_ui_completion(
                event,
                state,
                intent,
                "the exact pre-click UI Automation target evidence is unavailable",
            )

        foreground, foreground_error = self._probe_foreground_window()
        if foreground is None or not self._foreground_window_matches(foreground, scope):
            detail = (
                self._response(foreground)
                if foreground is not None
                else str(foreground_error or "foreground observation unavailable")
            )
            return self._fail_ui_completion(
                event,
                state,
                intent,
                "fresh destination foreground evidence did not match the exact automation-focus "
                "scope: " + detail,
            )

        focused, focused_error = self._probe_focused_automation_element()
        target_runtime_id = tuple(int(value) for value in target_record["runtime_id"])
        verified = bool(
            focused is not None
            and tuple(focused.runtime_id) == target_runtime_id
            and self._automation_element_eligible(focused, scope)
            and focused.has_keyboard_focus
        )
        state.data[self._AUTOMATION_VERIFICATION_KEY] = (
            {
                "verified": verified,
                "kind": self._AUTOMATION_SCOPE_KIND,
                "before_input": False,
                "target_runtime_id": list(target_runtime_id),
                "focused_observation": asdict(focused),
            }
            if focused is not None
            else {
                "verified": False,
                "kind": self._AUTOMATION_SCOPE_KIND,
                "before_input": False,
                "target_runtime_id": list(target_runtime_id),
                "error": str(focused_error or "focused automation element unavailable"),
            }
        )
        if verified and focused is not None:
            return self._complete_ui_scope(
                event,
                state,
                scope,
                response=self._automation_response(focused),
                reason=(
                    "ZN completed this ui_state_transition only after the bounded click effect "
                    "was independently observed and fresh read-only UI Automation evidence "
                    "proved that keyboard focus landed on the exact opaque element captured at "
                    "the final pointer target before input and still matched the typed target "
                    "scope; no UI Automation control pattern or task prose was used as execution "
                    "or completion authority"
                ),
            )
        detail = (
            self._automation_response(focused)
            if focused is not None
            else str(focused_error)
        )
        return self._fail_ui_completion(
            event,
            state,
            intent,
            "fresh focused UI Automation evidence did not match the exact pre-click target "
            "runtime identity and typed target scope: " + detail,
        )

    def _post_admission_error(
        self,
        event,
        state,
        intent: NativeActionIntent,
        scope: dict[str, Any],
        action_precondition: dict[str, str],
    ) -> str | None:
        error = self._semantic_admission_error(
            event, state, intent, scope, action_precondition
        )
        if error:
            return error
        semantic = state.data.get(self._SEMANTIC_PRECONDITION_KEY)
        if not isinstance(semantic, dict) or not bool(semantic.get("reverified")):
            return "the exact source foreground was not reverified at the final input boundary"
        admitted = state.data.get("native_verification")
        if not isinstance(admitted, dict):
            return "the completed click lost its admitted verification contract"
        if (
            admitted.get("completion_scope") != scope
            or admitted.get("action_precondition") != action_precondition
            or str(admitted.get("completion_event_kind") or "").strip().lower()
            != self._UI_EVENT_KIND
        ):
            return "the admitted event/scope/source authority drifted after pointer input"
        return None

    def _automation_completion_scope(
        self, event
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = event.payload.get("completion_scope")
        if (
            not isinstance(raw, dict)
            or str(raw.get("kind") or "").strip().lower()
            != self._AUTOMATION_SCOPE_KIND
        ):
            return None, (
                "ui_state_transition requires "
                "completion_scope.kind=focused_automation_element_at_pointer"
            )
        unknown = sorted(
            str(key)
            for key in raw
            if key
            not in {
                "kind",
                "process_name",
                "title_equals",
                "control_type",
                "class_name_equals",
            }
        )
        if unknown:
            return None, (
                "focused_automation_element_at_pointer completion_scope contains unsupported "
                "authority fields: " + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        if not process_name or not title:
            return None, (
                "focused_automation_element_at_pointer requires exact non-empty process_name "
                "and title_equals"
            )

        control_type = raw.get("control_type")
        if control_type is not None and (
            isinstance(control_type, bool)
            or not isinstance(control_type, int)
            or int(control_type) <= 0
        ):
            return None, (
                "focused_automation_element_at_pointer control_type must be a positive integer"
            )

        has_class_name = "class_name_equals" in raw
        class_name = str(raw.get("class_name_equals") or "").strip()
        if has_class_name and not class_name:
            return None, (
                "focused_automation_element_at_pointer class_name_equals must be non-empty"
            )
        if len(class_name) > 256:
            return None, (
                "focused_automation_element_at_pointer class_name_equals exceeds 256 characters"
            )

        scope: dict[str, Any] = {
            "kind": self._AUTOMATION_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
        }
        if control_type is not None:
            scope["control_type"] = int(control_type)
        if has_class_name:
            scope["class_name_equals"] = class_name
        return scope, None

    def _probe_target_element_from_contract(
        self, event, contract: dict[str, Any]
    ) -> tuple[AutomationElementObservation | None, str | None]:
        pointer = self.body.act("pointer_state", event_id=event.event_id)
        if not pointer.success:
            return None, pointer.error or "primary pointer state is unavailable"
        width = int(pointer.data.get("screen_width") or 0)
        height = int(pointer.data.get("screen_height") or 0)
        if width <= 0 or height <= 0:
            return None, "primary screen dimensions are unavailable"
        x = int(round(float(contract["center_x_fraction"]) * max(0, width - 1)))
        y = int(round(float(contract["center_y_fraction"]) * max(0, height - 1)))
        return self._probe_automation_element_at_point(x, y)

    def _probe_automation_element_at_point(
        self, x: int, y: int
    ) -> tuple[AutomationElementObservation | None, str | None]:
        sense = getattr(self, "automation_element", None)
        if sense is None or not callable(getattr(sense, "probe_at_point", None)):
            return None, "resident-owned automation-element Sense is unavailable"
        try:
            return sense.probe_at_point(int(x), int(y)), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def _probe_focused_automation_element(
        self,
    ) -> tuple[AutomationElementObservation | None, str | None]:
        sense = getattr(self, "automation_element", None)
        if sense is None or not callable(getattr(sense, "probe_focused", None)):
            return None, "resident-owned automation-element Sense is unavailable"
        try:
            return sense.probe_focused(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _same_runtime_id(
        first: AutomationElementObservation, second: AutomationElementObservation
    ) -> bool:
        return bool(first.runtime_id and tuple(first.runtime_id) == tuple(second.runtime_id))

    @staticmethod
    def _automation_element_eligible(
        observed: AutomationElementObservation, scope: dict[str, Any]
    ) -> bool:
        expected_control_type = scope.get("control_type")
        if expected_control_type is not None and int(observed.control_type) != int(
            expected_control_type
        ):
            return False
        expected_class_name = scope.get("class_name_equals")
        if expected_class_name is not None and str(observed.class_name or "") != str(
            expected_class_name
        ):
            return False
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and observed.runtime_id
            and int(observed.control_type) > 0
            and observed.is_enabled
            and observed.is_keyboard_focusable
            and not observed.is_offscreen
        )

    @staticmethod
    def _automation_response(observed: AutomationElementObservation) -> str:
        return (
            f"automation process={observed.process_name!s} framework={observed.framework_id!r} "
            f"control_type={observed.control_type} class={observed.class_name!r} "
            f"automation_id={observed.automation_id!r} enabled={observed.is_enabled} "
            f"focusable={observed.is_keyboard_focusable} focused={observed.has_keyboard_focus} "
            f"offscreen={observed.is_offscreen}"
        )

    def _automation_verification(
        self,
        target: AutomationElementObservation,
        focused: AutomationElementObservation,
        scope: dict[str, Any],
        *,
        verified: bool,
        before_input: bool,
    ) -> dict[str, Any]:
        return {
            "verified": bool(verified),
            "kind": self._AUTOMATION_SCOPE_KIND,
            "before_input": bool(before_input),
            "expected_process_name": scope["process_name"],
            "expected_title": scope["title_equals"],
            "expected_control_type": scope.get("control_type"),
            "expected_class_name": scope.get("class_name_equals"),
            "target_runtime_id": list(target.runtime_id),
            "target_observation": asdict(target),
            "focused_observation": asdict(focused),
        }

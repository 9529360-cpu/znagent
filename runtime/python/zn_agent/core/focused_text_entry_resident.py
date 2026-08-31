from __future__ import annotations

"""Typed, non-replayable text entry into one exact focused safe Edit control."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .focused_text_sense import FocusedTextObservation, NativeFocusedTextSense
from .keyboard_text_body import KeyboardTextBody
from .models import utc_now
from .pointer_click_automation_focus_resident import (
    AutomationFocusPointerClickResidentRuntime,
)


class FocusedTextEntryResidentRuntime(AutomationFocusPointerClickResidentRuntime):
    """Add one narrow text-entry competence without widening generic input authority.

    The first slice accepts plain Unicode text only when the exact native Win32
    Edit is already focused, visible, enabled, non-password, non-read-only and
    either empty or already equal to the requested text. It persists a started
    marker before SendInput and never blindly replays an interrupted input.
    """

    _TEXT_SCOPE_KIND = "focused_native_edit_text"
    _AUTOMATION_TEXT_SCOPE_KIND = "focused_automation_edit_text"
    _TEXT_OUTCOME_KIND = "focused_text_equals_action_text"
    _TEXT_PRECONDITION_KEY = "native_keyboard_text_precondition"
    _TEXT_EXECUTION_KEY = "native_keyboard_text_execution"
    _TEXT_VERIFICATION_KEY = "native_keyboard_text_verification"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = KeyboardTextBody(resident=self)
        self.focused_text = NativeFocusedTextSense()

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("native_action_intent")
        if isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            if intent.kind == "keyboard_text":
                return self._keyboard_text_action_step(
                    event,
                    state,
                    intent,
                    thought=thought,
                )
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _native_verification_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_contract = state.data.get("native_verification")
        raw_intent = state.data.get("native_action_intent")
        if (
            isinstance(raw_contract, dict)
            and str(raw_contract.get("kind") or "").strip().lower()
            == self._TEXT_OUTCOME_KIND
            and isinstance(raw_intent, dict)
        ):
            intent = NativeActionIntent.from_dict(raw_intent)
            if intent.kind == "keyboard_text":
                return self._verify_keyboard_text(
                    event,
                    state,
                    intent,
                    raw_contract,
                    thought=thought,
                )
        return super()._native_verification_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _keyboard_text_action_step(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ):
        contract, error = self._keyboard_text_contract(event, intent)
        if error:
            return self._fail_keyboard_text_precondition(
                event, state, intent, error, thought=thought
            )
        assert contract is not None
        scope = contract["completion_scope"]

        execution = state.data.get(self._TEXT_EXECUTION_KEY)
        if (
            isinstance(execution, dict)
            and str(execution.get("intent_id") or "") == intent.intent_id
            and str(execution.get("status") or "") == "started"
        ):
            return self._fail_keyboard_text_precondition(
                event,
                state,
                intent,
                "keyboard text input may already have started before interruption; refusing blind replay",
                thought=thought,
            )

        prepared = state.data.get(self._TEXT_PRECONDITION_KEY)
        same_preparation = bool(
            isinstance(prepared, dict)
            and str(prepared.get("intent_id") or "") == intent.intent_id
            and prepared.get("completion_scope") == scope
            and prepared.get("action_precondition") == contract["action_precondition"]
            and str(prepared.get("expected_text_sha256") or "")
            == contract["expected_text_sha256"]
            and int(prepared.get("expected_text_chars") or -1)
            == int(contract["expected_text_chars"])
            and isinstance(prepared.get("target_runtime_id"), list)
            and bool(prepared.get("target_runtime_id"))
        )

        if not same_preparation:
            target, target_error = self._probe_text_target(scope)
            if target is None:
                return self._fail_keyboard_text_precondition(
                    event,
                    state,
                    intent,
                    "fresh focused text target preflight failed: " + str(target_error),
                    thought=thought,
                )
            text_observation = target["text"]
            if self._text_matches_expected(text_observation, contract):
                state.data[self._TEXT_VERIFICATION_KEY] = {
                    "verified": True,
                    "before_input": True,
                    "kind": self._TEXT_OUTCOME_KIND,
                    "expected_text_sha256": contract["expected_text_sha256"],
                    "expected_text_chars": contract["expected_text_chars"],
                    "target_runtime_id": list(target["automation"].runtime_id),
                    "text_observation": asdict(text_observation),
                }
                return self._complete_ui_scope(
                    event,
                    state,
                    scope,
                    response="focused Edit already matched the requested text digest",
                    reason=(
                        "ZN completed this ui_state_transition from fresh focused-control, "
                        "UI Automation and text-digest evidence because the exact target already "
                        "matched the requested text; no keyboard input was sent"
                    ),
                )
            if int(text_observation.text_length) != 0:
                return self._fail_keyboard_text_precondition(
                    event,
                    state,
                    intent,
                    "the focused Edit is non-empty and differs from the requested text; "
                    "this first text-entry slice refuses selection, deletion or replacement",
                    thought=thought,
                )

            state.data[self._TEXT_PRECONDITION_KEY] = {
                "intent_id": intent.intent_id,
                "completion_scope": dict(scope),
                "action_precondition": dict(contract["action_precondition"]),
                "expected_text_sha256": contract["expected_text_sha256"],
                "expected_text_chars": contract["expected_text_chars"],
                "target_runtime_id": list(target["automation"].runtime_id),
                "native_observation": asdict(target["native"]),
                "automation_observation": asdict(target["automation"]),
                "text_observation": asdict(text_observation),
                "prepared_at": utc_now(),
            }
            state.next_action = (
                "reverify the exact empty focused Edit and send one non-replayable Unicode text input"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        assert isinstance(prepared, dict)
        state.data[self._TEXT_EXECUTION_KEY] = {
            "intent_id": intent.intent_id,
            "status": "started",
            "input_sent": None,
            "target_runtime_id": list(prepared["target_runtime_id"]),
            "expected_text_sha256": contract["expected_text_sha256"],
            "expected_text_chars": contract["expected_text_chars"],
            "started_at": utc_now(),
            "action_id": None,
        }
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

        target, target_error = self._probe_text_target(
            scope,
            expected_runtime_id=tuple(int(value) for value in prepared["target_runtime_id"]),
        )
        final_error = None
        if target is None:
            final_error = "final focused text target recheck failed: " + str(target_error)
        elif int(target["text"].text_length) != 0:
            final_error = (
                "focused Edit changed after preparation and is no longer empty; refusing keyboard input"
            )
        if final_error:
            aborted = dict(state.data[self._TEXT_EXECUTION_KEY])
            aborted.update(
                {
                    "status": "aborted",
                    "input_sent": False,
                    "aborted_at": utc_now(),
                    "error": final_error,
                }
            )
            state.data[self._TEXT_EXECUTION_KEY] = aborted
            return self._fail_keyboard_text_precondition(
                event, state, intent, final_error, thought=thought
            )

        result = self.body.act(
            "keyboard_text",
            event_id=event.event_id,
            text=contract["text"],
        )
        state.data["native_action_result"] = asdict(result)
        state.data[self._TEXT_EXECUTION_KEY] = {
            "intent_id": intent.intent_id,
            "status": "completed" if result.success else "failed",
            "input_sent": True,
            "target_runtime_id": list(prepared["target_runtime_id"]),
            "expected_text_sha256": contract["expected_text_sha256"],
            "expected_text_chars": contract["expected_text_chars"],
            "started_at": state.data[self._TEXT_EXECUTION_KEY]["started_at"],
            "completed_at": utc_now(),
            "action_id": result.action_id,
            "success": bool(result.success),
        }
        if not result.success:
            failure = result.error or "keyboard text input failed or was only partially delivered"
            state.data["local_failure"] = failure
            self._record_failed_action(
                event,
                state,
                intent,
                source="body",
                failure=failure,
            )
            state.stage = "native_investigation"
            state.next_action = "inspect the focused text digest without replaying keyboard input"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        state.data["native_verification"] = {
            "kind": self._TEXT_OUTCOME_KIND,
            "intent_id": intent.intent_id,
            "action_signature": self._intent_signature(intent),
            "completion_scope": dict(scope),
            "completion_event_kind": self._UI_EVENT_KIND,
            "action_precondition": dict(contract["action_precondition"]),
            "expected_text_sha256": contract["expected_text_sha256"],
            "expected_text_chars": contract["expected_text_chars"],
            "target_runtime_id": list(prepared["target_runtime_id"]),
        }
        state.stage = "native_verification"
        state.next_action = (
            "re-observe the exact focused Edit and verify its text digest after keyboard input"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _verify_keyboard_text(
        self,
        event,
        state,
        intent: NativeActionIntent,
        admitted: dict[str, Any],
        *,
        thought=None,
    ):
        contract, error = self._keyboard_text_contract(event, intent)
        if error or contract is None:
            failure = str(error or "keyboard text contract is no longer valid")
            return self._fail_postcondition_verification(
                event, state, intent, failure=failure, thought=thought
            )
        scope = contract["completion_scope"]
        expected_runtime = admitted.get("target_runtime_id")
        if (
            admitted.get("completion_scope") != scope
            or admitted.get("action_precondition") != contract["action_precondition"]
            or str(admitted.get("completion_event_kind") or "").strip().lower()
            != self._UI_EVENT_KIND
            or str(admitted.get("intent_id") or "") != intent.intent_id
            or str(admitted.get("expected_text_sha256") or "")
            != contract["expected_text_sha256"]
            or int(admitted.get("expected_text_chars") or -1)
            != int(contract["expected_text_chars"])
            or not isinstance(expected_runtime, list)
            or not expected_runtime
        ):
            return self._fail_postcondition_verification(
                event,
                state,
                intent,
                failure="typed keyboard text authority drifted after input",
                thought=thought,
            )

        target, target_error = self._probe_text_target(
            scope,
            expected_runtime_id=tuple(int(value) for value in expected_runtime),
        )
        verified = bool(
            target is not None and self._text_matches_expected(target["text"], contract)
        )
        verification_result = (
            {
                "verified": verified,
                "kind": self._TEXT_OUTCOME_KIND,
                "expected_text_sha256": contract["expected_text_sha256"],
                "expected_text_chars": contract["expected_text_chars"],
                "target_runtime_id": list(expected_runtime),
                "native_observation": asdict(target["native"]),
                "automation_observation": asdict(target["automation"]),
                "text_observation": asdict(target["text"]),
            }
            if target is not None
            else {
                "verified": False,
                "kind": self._TEXT_OUTCOME_KIND,
                "expected_text_sha256": contract["expected_text_sha256"],
                "expected_text_chars": contract["expected_text_chars"],
                "target_runtime_id": list(expected_runtime),
                "error": str(target_error or "focused text target unavailable"),
            }
        )
        state.data[self._TEXT_VERIFICATION_KEY] = dict(verification_result)
        state.data["native_verification_result"] = dict(verification_result)
        self._record_verified_experience(
            event,
            state,
            intent,
            verification_result=verification_result,
        )
        self._sync_execution_context(event, state)

        if verified:
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=(
                    "fresh focused Edit digest matched the exact requested text after one bounded Unicode input"
                ),
                reason=(
                    "ZN completed this ui_state_transition only after fresh foreground, "
                    "focused-control/UI Automation identity and text-digest "
                    "evidence independently proved that the exact focused Edit contains the "
                    "requested action text; model text and SendInput return status were not "
                    "accepted as completion proof"
                ),
            )

        failure = (
            "keyboard text postcondition verification failed: the exact focused Edit "
            "did not match the requested text digest after input"
            if target is not None
            else "keyboard text postcondition verification failed: fresh target evidence was unavailable ("
            + str(target_error)
            + ")"
        )
        return self._fail_postcondition_verification(
            event, state, intent, failure=failure, thought=thought
        )

    def _keyboard_text_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if str(event.kind or "").strip().lower() != self._UI_EVENT_KIND:
            return None, "keyboard_text is permitted only for ui_state_transition events"

        expected = event.payload.get("expected_outcome")
        if (
            not isinstance(expected, dict)
            or str(expected.get("kind") or "").strip().lower()
            != self._TEXT_OUTCOME_KIND
        ):
            return None, (
                "keyboard_text requires expected_outcome.kind=focused_text_equals_action_text"
            )
        unknown_expected = sorted(str(key) for key in expected if key != "kind")
        if unknown_expected:
            return None, (
                "focused_text_equals_action_text contains unsupported authority fields: "
                + ", ".join(unknown_expected)
            )

        args = intent.args if isinstance(intent.args, dict) else {}
        if "text" in args:
            raw_text = args["text"]
        elif "content" in args:
            raw_text = args["content"]
        else:
            return None, "keyboard_text requires an explicit text argument"
        try:
            text, units = KeyboardTextBody.validate_text(raw_text)
        except ValueError as exc:
            return None, str(exc)

        scope, error = self._text_completion_scope(event)
        if error:
            return None, error
        assert scope is not None
        action_precondition, error = self._ui_action_precondition(event)
        if error:
            return None, error
        if not isinstance(action_precondition, dict):
            return None, (
                "focused Edit text entry requires an explicit exact "
                "action_precondition.kind=foreground_window_matches"
            )
        if (
            action_precondition.get("process_name") != scope["process_name"]
            or action_precondition.get("title_equals") != scope["title_equals"]
        ):
            return None, (
                "keyboard_text action_precondition must match the same exact foreground "
                "process/title as completion_scope"
            )

        required_senses = [("foreground-window", "probe")]
        if scope["kind"] == self._AUTOMATION_TEXT_SCOPE_KIND:
            required_senses.append(("automation-text-state", "probe"))
        else:
            required_senses.extend(
                (("focused-control", "probe"), ("focused-text", "probe"))
            )
        for name, method in required_senses:
            sense = getattr(
                self,
                {
                    "foreground-window": "foreground_window",
                    "focused-control": "focused_control",
                    "focused-text": "focused_text",
                    "automation-text-state": "automation_text_state",
                }[name],
                None,
            )
            if sense is None or not callable(getattr(sense, method, None)):
                return None, f"keyboard_text requires the resident-owned {name} Sense"
        automation = getattr(self, "automation_element", None)
        if automation is None or not callable(getattr(automation, "probe_focused", None)):
            return None, "keyboard_text requires the resident-owned read-only automation-element Sense"

        return {
            "kind": self._TEXT_OUTCOME_KIND,
            "text": text,
            "utf16_units": len(units),
            "expected_text_chars": len(text),
            "expected_text_sha256": NativeFocusedTextSense.digest_text(text),
            "completion_scope": scope,
            "completion_event_kind": self._UI_EVENT_KIND,
            "action_precondition": action_precondition,
        }, None

    def _text_completion_scope(
        self, event
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = event.payload.get("completion_scope")
        if not isinstance(raw, dict):
            return None, "ui_state_transition requires an explicit focused text completion_scope"
        scope_kind = str(raw.get("kind") or "").strip().lower()
        if scope_kind == self._AUTOMATION_TEXT_SCOPE_KIND:
            return self._automation_text_completion_scope(raw)
        if scope_kind != self._TEXT_SCOPE_KIND:
            return None, (
                "ui_state_transition requires completion_scope.kind="
                "focused_native_edit_text or focused_automation_edit_text"
            )
        allowed = {
            "kind",
            "process_name",
            "title_equals",
            "control_class_name",
            "control_id",
            "control_type",
            "class_name_equals",
        }
        unknown = sorted(str(key) for key in raw if key not in allowed)
        if unknown:
            return None, (
                "focused_native_edit_text completion_scope contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        control_class_name = str(raw.get("control_class_name") or "").strip()
        raw_control_id = raw.get("control_id")
        raw_control_type = raw.get("control_type")
        if isinstance(raw_control_id, bool) or isinstance(raw_control_type, bool):
            return None, "focused_native_edit_text control ids/types must be positive integers"
        try:
            control_id = int(raw_control_id)
            control_type = int(raw_control_type)
        except (TypeError, ValueError):
            control_id = 0
            control_type = 0
        class_name = str(raw.get("class_name_equals") or "").strip()
        if (
            not process_name
            or not title
            or control_class_name.lower() != "edit"
            or control_id <= 0
            or control_type <= 0
            or not class_name
        ):
            return None, (
                "focused_native_edit_text requires exact process_name/title, native Edit class, "
                "positive control_id/control_type and exact non-empty UIA class_name_equals"
            )
        if len(class_name) > 256:
            return None, "focused_native_edit_text class_name_equals exceeds 256 characters"
        return {
            "kind": self._TEXT_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
            "control_class_name": control_class_name,
            "control_id": control_id,
            "control_type": control_type,
            "class_name_equals": class_name,
        }, None

    def _automation_text_completion_scope(
        self, raw: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        allowed = {
            "kind",
            "process_name",
            "title_equals",
            "control_type",
            "class_name_equals",
            "automation_id_equals",
        }
        unknown = sorted(str(key) for key in raw if key not in allowed)
        if unknown:
            return None, (
                "focused_automation_edit_text completion_scope contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        raw_control_type = raw.get("control_type")
        if isinstance(raw_control_type, bool):
            return None, "focused_automation_edit_text control_type must be 50004"
        try:
            control_type = int(raw_control_type)
        except (TypeError, ValueError):
            control_type = 0
        class_name = str(raw.get("class_name_equals") or "").strip()
        automation_id = str(raw.get("automation_id_equals") or "").strip()
        if not process_name or not title or control_type != 50004:
            return None, (
                "focused_automation_edit_text requires exact process_name/title and "
                "UIA Edit control_type=50004"
            )
        if len(class_name) > 256 or len(automation_id) > 256:
            return None, "focused_automation_edit_text identity field exceeds 256 characters"
        return {
            "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
            "control_type": control_type,
            "class_name_equals": class_name,
            "automation_id_equals": automation_id,
        }, None

    def _probe_text_target(
        self,
        scope: dict[str, Any],
        *,
        expected_runtime_id: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if scope.get("kind") == self._AUTOMATION_TEXT_SCOPE_KIND:
            return self._probe_automation_text_target(
                scope,
                expected_runtime_id=expected_runtime_id,
            )
        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return None, "foreground observation unavailable: " + str(error)
        if not self._foreground_window_matches(foreground, scope):
            return None, "foreground window does not match the exact typed text scope"

        native, error = self._probe_focused_control()
        if native is None:
            return None, "focused native-control observation unavailable: " + str(error)
        if not self._focused_control_matches(native, scope):
            return None, "focused native control does not match the exact typed text scope"

        automation, error = self._probe_focused_automation_element()
        if automation is None:
            return None, "focused UI Automation observation unavailable: " + str(error)
        if not automation.has_keyboard_focus or not self._automation_element_eligible(
            automation, scope
        ):
            return None, "focused UI Automation element does not match the exact typed text scope"
        if expected_runtime_id is not None and tuple(automation.runtime_id) != tuple(
            expected_runtime_id
        ):
            return None, "focused UI Automation RuntimeId changed after text-entry preparation"

        text, error = self._probe_focused_text()
        if text is None:
            return None, "focused text digest observation unavailable: " + str(error)
        if not self._focused_text_matches(text, scope):
            return None, "focused text digest identity does not match the exact typed text scope"
        if int(automation.native_window_handle) <= 0 or int(
            automation.native_window_handle
        ) != int(text.native_window_handle):
            return None, (
                "focused UI Automation and native text Sense do not identify the same native HWND"
            )

        return {
            "foreground": foreground,
            "native": native,
            "automation": automation,
            "text": text,
        }, None

    def _probe_automation_text_target(
        self,
        scope: dict[str, Any],
        *,
        expected_runtime_id: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return None, "foreground observation unavailable: " + str(error)
        if not self._foreground_window_matches(foreground, scope):
            return None, "foreground window does not match the exact automation text scope"

        automation, error = self._probe_focused_automation_element()
        if automation is None:
            return None, "focused UI Automation observation unavailable: " + str(error)
        if not self._automation_text_identity_matches(automation, scope):
            return None, "focused UI Automation element does not match the exact automation text scope"

        text, error = self._probe_focused_automation_text()
        if text is None:
            return None, "focused UI Automation text digest unavailable: " + str(error)
        if not self._automation_text_identity_matches(text, scope):
            return None, "focused UI Automation text identity does not match the exact scope"
        if tuple(automation.runtime_id) != tuple(text.runtime_id):
            return None, "structural and text UI Automation observations identify different RuntimeIds"
        if int(automation.process_id) != int(text.process_id):
            return None, "structural and text UI Automation observations identify different processes"
        if expected_runtime_id is not None and tuple(text.runtime_id) != tuple(
            expected_runtime_id
        ):
            return None, "focused UI Automation RuntimeId changed after text-entry preparation"

        # Preserve the established evidence-shape keys so the shared durable
        # non-replayable lifecycle can serve both native and automation Edit
        # targets without creating a second mutation state machine. Neither
        # observation contains plaintext.
        return {
            "foreground": foreground,
            "native": text,
            "automation": automation,
            "text": text,
        }, None

    def _probe_focused_automation_text(self):
        sense = getattr(self, "automation_text_state", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned automation-text-state Sense is unavailable"
        try:
            return sense.probe(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _automation_text_identity_matches(observed, scope: dict[str, Any]) -> bool:
        class_name = str(scope.get("class_name_equals") or "")
        automation_id = str(scope.get("automation_id_equals") or "")
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and int(observed.control_type) == int(scope["control_type"])
            and (not class_name or str(observed.class_name or "").strip() == class_name)
            and (
                not automation_id
                or str(observed.automation_id or "").strip() == automation_id
            )
            and bool(observed.runtime_id)
            and observed.is_enabled
            and observed.is_keyboard_focusable
            and observed.has_keyboard_focus
            and not observed.is_offscreen
            and not observed.is_password
        )

    def _probe_focused_text(
        self,
    ) -> tuple[FocusedTextObservation | None, str | None]:
        sense = getattr(self, "focused_text", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned focused-text Sense is unavailable"
        try:
            return sense.probe(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _focused_text_matches(
        observed: FocusedTextObservation,
        scope: dict[str, Any],
    ) -> bool:
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and str(observed.foreground_title or "").strip() == scope["title_equals"]
            and str(observed.control_class_name or "").strip()
            == scope["control_class_name"]
            and int(observed.control_id) == int(scope["control_id"])
            and int(observed.native_window_handle) > 0
            and observed.enabled
            and observed.visible
            and not observed.is_password
            and not observed.is_read_only
        )

    @staticmethod
    def _text_matches_expected(
        observed: FocusedTextObservation,
        contract: dict[str, Any],
    ) -> bool:
        return bool(
            int(observed.text_length) == int(contract["expected_text_chars"])
            and str(observed.text_sha256 or "").strip().lower()
            == str(contract["expected_text_sha256"])
        )

    def _fail_keyboard_text_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        failure: str,
        *,
        thought=None,
    ):
        message = "keyboard text precondition failed: " + str(failure or "unknown failure")
        state.data["local_failure"] = message
        self._record_failed_action(
            event,
            state,
            intent,
            source="precondition",
            failure=message,
        )
        state.stage = "native_investigation"
        state.next_action = "refresh the exact focused text target before any further keyboard input"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if message not in thought.unknown:
                thought.unknown = (*thought.unknown, message)
            thought.reason = (
                f"{thought.reason}; the bounded keyboard text precondition was not proven from current reality"
            )
            self._persist_enriched_thought(thought)
        return None

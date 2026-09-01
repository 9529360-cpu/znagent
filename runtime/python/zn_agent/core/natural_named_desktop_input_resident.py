from __future__ import annotations

"""Natural desktop task closure without requiring the user to pre-focus the Edit."""

import re
import uuid
from dataclasses import replace
from typing import Any, Mapping

from .action import NativeActionIntent
from .automation_named_control_sense import NamedAutomationControlObservation
from .models import WorkingState, utc_now
from .natural_browser_desktop_submit_resident import NaturalBrowserDesktopSubmitResidentRuntime
from .natural_file_desktop_resident import _BROWSER_PROCESS_NAMES
from .pointer_click_automation_focus_resident import AutomationFocusPointerClickResidentRuntime


_NAMED_INPUT_PATTERNS = (
    re.compile(
        r"(?:输入框|文本框|字段)\s*[\"“'‘](?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]"
    ),
    re.compile(
        r"[\"“'‘](?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]\s*(?:输入框|文本框|字段)"
    ),
)


class NaturalNamedDesktopInputResidentRuntime(NaturalBrowserDesktopSubmitResidentRuntime):
    """Find and focus one exact named Edit before the existing task continues.

    This layer removes a user setup requirement from the complete File/Browser ->
    Desktop task. It does not introduce a new input primitive. Exact-name Edit
    discovery is read-only, the focus movement reuses the existing durable
    AutomationFocus pointer lifecycle, and the inherited text path still freshly
    verifies focused RuntimeId, safe Edit properties and text digest before any
    keyboard input. The inherited submit path still owns the final named Button,
    non-replay click and independent final-window verification.
    """

    _NAMED_INPUT_FOCUS_OUTCOME_KIND = "named_desktop_edit_focused_for_task"
    _NAMED_INPUT_FACT_KEY = "natural_named_desktop_input"
    _NAMED_INPUT_STATE_KEY = "natural_named_desktop_input_focus"
    _NAMED_INPUT_PROBE_LABEL = "bind one exact named safe Edit in the current desktop app"

    @classmethod
    def _natural_named_desktop_input_request(cls, event) -> dict[str, str] | None:
        base = super()._natural_file_desktop_submit_request(event)
        if not isinstance(base, dict):
            return None
        task = " ".join(str(event.task or "").strip().split())
        names: list[str] = []
        for pattern in _NAMED_INPUT_PATTERNS:
            for match in pattern.finditer(task):
                value = " ".join(str(match.group("name") or "").strip().split())
                if value and value not in names:
                    names.append(value)
        if len(names) != 1:
            return None
        return {**base, "input_name": names[0]}

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_named_desktop_input_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        submit_progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
        if isinstance(submit_progress, dict) and submit_progress.get("typed_verified") is True:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        target, foreground, focused, failure = self._observe_named_input_target(
            event,
            state,
            input_name=request["input_name"],
        )
        if failure or target is None or foreground is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "ZN could not freshly bind one safe named desktop input before the task: "
                    + str(failure or "named Edit evidence is unavailable")
                ),
            )

        if focused:
            state.data[self._NAMED_INPUT_STATE_KEY] = {
                "verified": True,
                "input_name": request["input_name"],
                "process_name": str(foreground.process_name or "").strip().lower(),
                "pre_title": str(foreground.title or "").strip(),
                "runtime_id": list(target.runtime_id),
                "verified_at": utc_now(),
                "input_sent": False,
            }
            state.data.pop("local_failure", None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        intent = self._named_input_focus_intent(
            event,
            target,
            process_name=str(foreground.process_name or "").strip().lower(),
            title=str(foreground.title or "").strip(),
            input_name=request["input_name"],
        )
        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact named desktop input focus movement remains blocked by unchanged "
                    "failure evidence; ZN will not replay it"
                ),
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = f'focus the freshly bound desktop input "{request["input_name"]}"'
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = (
                f"{thought.reason}; the user named the intended Edit and fresh current-app UIA "
                "evidence bound exactly one safe target, so ZN can focus it without asking the "
                "user to prepare the UI"
            )
            self._persist_enriched_thought(thought)
        return None

    def _observe_named_input_target(
        self,
        event,
        state: WorkingState,
        *,
        input_name: str,
    ):
        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return None, None, False, "foreground desktop window is unavailable: " + str(error)
        process_name = str(foreground.process_name or "").strip().lower()
        title = str(foreground.title or "").strip()
        if not process_name or process_name in _BROWSER_PROCESS_NAMES:
            return None, foreground, False, (
                "named desktop input requires a current non-browser foreground application"
            )
        if not title:
            return None, foreground, False, (
                "named desktop input requires an exact current foreground window title"
            )
        try:
            target = self.named_automation_control.find_unique_edit(
                process_id=int(foreground.process_id),
                process_name=process_name,
                name=input_name,
            )
        except Exception as exc:
            return None, foreground, False, (
                "exact named Edit discovery failed: "
                f"{type(exc).__name__}: {exc}"
            )

        focused_observation, focused_error = self._probe_focused_automation_element()
        focused = bool(
            focused_observation is not None
            and tuple(focused_observation.runtime_id) == tuple(target.runtime_id)
            and int(focused_observation.process_id) == int(target.process_id)
            and str(focused_observation.process_name or "").strip().lower()
            == process_name
            and int(focused_observation.control_type) == 50004
            and focused_observation.is_enabled
            and focused_observation.is_keyboard_focusable
            and focused_observation.has_keyboard_focus
            and not focused_observation.is_offscreen
            and not focused_observation.is_password
        )
        self._record_named_input_observation(
            event,
            state,
            target,
            process_name=process_name,
            title=title,
            input_name=input_name,
            focused=focused,
            focused_error=None if focused_observation is not None else focused_error,
        )
        return target, foreground, focused, None

    def _named_input_focus_intent(
        self,
        event,
        target: NamedAutomationControlObservation,
        *,
        process_name: str,
        title: str,
        input_name: str,
    ) -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"named-edit-focus-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(target.center_x_fraction),
                "y_fraction": float(target.center_y_fraction),
                "button": "left",
                "target_runtime_id": list(target.runtime_id),
                "target_name": input_name,
                "target_process_name": process_name,
            },
            expected_outcome={
                "kind": self._NAMED_INPUT_FOCUS_OUTCOME_KIND,
                "process_name": process_name,
                "pre_title": title,
                "input_name": input_name,
                "target_runtime_id": list(target.runtime_id),
                "target_center_x_fraction": float(target.center_x_fraction),
                "target_center_y_fraction": float(target.center_y_fraction),
                "target_class_name": str(target.class_name or ""),
            },
            reason=(
                "fresh exact-name UIA evidence bound one safe focusable non-password Edit in the "
                "current foreground application; reuse the existing non-replayable automation-focus "
                "pointer lifecycle before any text entry"
            ),
            source="resident_choice",
        )

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "pointer_click"
            or str(expected.get("kind") or "").strip().lower()
            != self._NAMED_INPUT_FOCUS_OUTCOME_KIND
        ):
            return super()._pointer_click_contract(event, intent)
        synthetic = self._named_input_focus_event(event, expected)
        if synthetic is None:
            return None, "named desktop input focus intent lost its exact scope authority"
        return AutomationFocusPointerClickResidentRuntime._pointer_click_contract(
            self,
            synthetic,
            intent,
        )

    def _pointer_click_action_step(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ):
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "pointer_click"
            or str(expected.get("kind") or "").strip().lower()
            != self._NAMED_INPUT_FOCUS_OUTCOME_KIND
        ):
            return super()._pointer_click_action_step(
                event,
                state,
                intent,
                thought=thought,
            )
        synthetic = self._named_input_focus_event(event, expected)
        if synthetic is None:
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                "named desktop input focus lost its exact synthetic event scope",
                thought=thought,
            )
        return AutomationFocusPointerClickResidentRuntime._pointer_click_action_step(
            self,
            synthetic,
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
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "pointer_click"
            or str(expected.get("kind") or "").strip().lower()
            != self._NAMED_INPUT_FOCUS_OUTCOME_KIND
        ):
            return super()._pointer_click_final_input_precondition(
                event,
                state,
                intent,
                contract,
                prepared,
            )

        process_name = str(expected.get("process_name") or "").strip().lower()
        pre_title = str(expected.get("pre_title") or "").strip()
        input_name = str(expected.get("input_name") or "").strip()
        expected_runtime = tuple(
            int(value) for value in (expected.get("target_runtime_id") or ())
        )
        if not process_name or not pre_title or not input_name or not expected_runtime:
            return "named desktop input focus lost its exact pre-input authority"

        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return "fresh foreground recheck before named Edit focus is unavailable: " + str(error)
        if not self._foreground_equals(foreground, process_name, pre_title):
            return "foreground desktop application changed before the final named Edit focus boundary"
        try:
            fresh_target = self.named_automation_control.find_unique_edit(
                process_id=int(foreground.process_id),
                process_name=process_name,
                name=input_name,
            )
        except Exception as exc:
            return (
                "exact named Edit could not be freshly revalidated before focus input: "
                f"{type(exc).__name__}: {exc}"
            )
        self._record_named_input_observation(
            event,
            state,
            fresh_target,
            process_name=process_name,
            title=pre_title,
            input_name=input_name,
            focused=bool(fresh_target.has_keyboard_focus),
            focused_error=None,
        )
        if tuple(fresh_target.runtime_id) != expected_runtime:
            return "exact named Edit RuntimeId changed before input; re-investigate the current target"
        expected_x = float(expected.get("target_center_x_fraction") or -1.0)
        expected_y = float(expected.get("target_center_y_fraction") or -1.0)
        if (
            abs(float(fresh_target.center_x_fraction) - expected_x) > 0.002
            or abs(float(fresh_target.center_y_fraction) - expected_y) > 0.002
        ):
            return "exact named Edit moved materially before input; re-investigate the current focus point"

        synthetic = self._named_input_focus_event(event, expected)
        if synthetic is None:
            return "named desktop input focus lost its exact synthetic action scope"
        parent_error = AutomationFocusPointerClickResidentRuntime._pointer_click_final_input_precondition(
            self,
            synthetic,
            state,
            intent,
            contract,
            prepared,
        )
        if parent_error:
            return parent_error
        target_record = state.data.get(self._AUTOMATION_TARGET_KEY)
        point_runtime = (
            tuple(int(value) for value in target_record.get("runtime_id") or ())
            if isinstance(target_record, dict)
            else ()
        )
        if point_runtime != expected_runtime:
            return (
                "the UI Automation element at the final pointer point is not the exact named Edit "
                "that granted focus authority"
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
    ):
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind == "pointer_click"
            and str(expected.get("kind") or "").strip().lower()
            == self._NAMED_INPUT_FOCUS_OUTCOME_KIND
        ):
            synthetic = self._named_input_focus_event(event, expected)
            if synthetic is None:
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified named Edit focus lost its exact structured scope",
                )
            return AutomationFocusPointerClickResidentRuntime._complete_successful_body_action(
                self,
                synthetic,
                state,
                intent,
                response=response,
                reason=reason,
            )
        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )

    def _complete_ui_scope(
        self,
        event,
        state,
        scope: dict[str, Any],
        *,
        response: str,
        reason: str,
    ):
        raw = state.data.get("native_action_intent")
        if isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
            if (
                intent.kind == "pointer_click"
                and str(expected.get("kind") or "").strip().lower()
                == self._NAMED_INPUT_FOCUS_OUTCOME_KIND
            ):
                original = self.store.get_event(event.event_id) or event
                state.data[self._NAMED_INPUT_STATE_KEY] = {
                    "verified": True,
                    "input_name": str(expected.get("input_name") or ""),
                    "process_name": str(expected.get("process_name") or "").strip().lower(),
                    "pre_title": str(expected.get("pre_title") or "").strip(),
                    "runtime_id": list(expected.get("target_runtime_id") or ()),
                    "verified_at": utc_now(),
                    "input_sent": True,
                    "verification_response": str(response or "")[:500],
                }
                state.stage = "native_deliberation"
                state.next_action = "freshly verify the named Edit remains focused before text entry"
                state.data.pop("local_failure", None)
                self._sync_execution_context(original, state)
                self.store.save_working_state(state)
                return None
        return super()._complete_ui_scope(
            event,
            state,
            scope,
            response=response,
            reason=reason,
        )

    def _named_input_focus_event(
        self,
        event,
        expected: Mapping[str, Any],
    ):
        process_name = str(expected.get("process_name") or "").strip().lower()
        title = str(expected.get("pre_title") or "").strip()
        class_name = str(expected.get("target_class_name") or "").strip()
        if not process_name or not title:
            return None
        completion_scope: dict[str, Any] = {
            "kind": self._AUTOMATION_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
            "control_type": 50004,
        }
        if class_name:
            completion_scope["class_name_equals"] = class_name
        return replace(
            event,
            kind=self._UI_EVENT_KIND,
            payload={
                "expected_outcome": {
                    "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                    "width_fraction": 0.08,
                    "height_fraction": 0.08,
                },
                "completion_scope": completion_scope,
                "action_precondition": {
                    "kind": "foreground_window_matches",
                    "process_name": process_name,
                    "title_equals": title,
                },
                "model_policy": "never",
            },
        )

    def _record_named_input_observation(
        self,
        event,
        state: WorkingState,
        target: NamedAutomationControlObservation,
        *,
        process_name: str,
        title: str,
        input_name: str,
        focused: bool,
        focused_error: str | None,
    ) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return
        facts = dict(investigation.facts)
        fact = {
            "process_name": str(process_name or "").strip().lower(),
            "title": str(title or "").strip(),
            "input_name": str(input_name or "").strip(),
            "runtime_id": list(target.runtime_id),
            "control_type": int(target.control_type),
            "class_name": str(target.class_name or ""),
            "center_x_fraction": float(target.center_x_fraction),
            "center_y_fraction": float(target.center_y_fraction),
            "focused": bool(focused),
            "password": bool(target.is_password),
            "value_is_read_only": target.value_is_read_only,
            "source": str(target.source or ""),
            "observed_at": target.captured_at,
            "focused_error": str(focused_error or "")[:300] or None,
        }
        facts[self._NAMED_INPUT_FACT_KEY] = fact
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key=self._NAMED_INPUT_FACT_KEY,
            label=self._NAMED_INPUT_PROBE_LABEL,
            notes=[
                f"fresh exact-name desktop Edit: process={fact['process_name']} name={fact['input_name']}",
                f"safe structural target: control_type=50004 focused={fact['focused']} password={fact['password']} read_only={fact['value_is_read_only']}",
            ],
        )
        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)

from __future__ import annotations

"""Resident-owned continuation for bounded multi-step world-state goals.

A verified Body movement is not automatically a completed user goal. This layer
keeps typed composite goals alive across multiple verified movements, clears
stale action evidence after each substep, and forces a fresh observation before
deciding what to do next. It deliberately owns no generic planner and stores no
replayable action sequence.
"""

import uuid
from dataclasses import asdict, replace
from typing import Any

from .action import NativeActionIntent
from .automation_named_control_sense import NativeNamedAutomationControlSense
from .browser_form_submit_resident import BrowserFormSubmitResidentRuntime
from .browser_named_goal import (
    browser_named_text_intent,
    browser_named_text_request,
    browser_named_text_state,
)
from .browser_named_target_sense import NativeBrowserNamedTargetSense
from .desktop_task_goal import desktop_task_goal
from .focused_text_sense import NativeFocusedTextSense
from .keyboard_text_body import KeyboardTextBody
from .models import ExecutionPath, utc_now
from .natural_file_goal import fresh_workspace_text, observe_workspace_text_source
from .pointer_click_resident import VerifiedPointerClickResidentRuntime
from .repo_goal import (
    repo_text_staged_action_intents,
    repo_text_staged_request,
    repo_text_staged_state,
)


class ResidentGoalRuntime(BrowserFormSubmitResidentRuntime):
    """Continue one typed goal until fresh reality proves the whole goal complete."""

    _RESIDENT_GOAL_PROGRESS_KEY = "resident_goal_progress"
    _BROWSER_GOAL_OBSERVATION_KEY = "resident_browser_goal_observation"
    _BROWSER_GOAL_BINDING_KEY = "resident_browser_goal_binding"
    _BROWSER_GOAL_FOCUS_VERIFICATION_KEY = "resident_browser_goal_focus_verification"
    _MAX_RESIDENT_GOAL_PROGRESS = 16
    _DESKTOP_TASK_OBSERVATION_KEY = "resident_desktop_task_observation"
    _DESKTOP_TASK_PROGRESS_KEY = "resident_desktop_task_progress"
    _DESKTOP_EDIT_FOCUS_KIND = "desktop_task_edit_focused"
    _DESKTOP_TEXT_KIND = "desktop_task_text_equals"
    _DESKTOP_SUBMIT_KIND = "desktop_task_button_submitted"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.browser_named_target = NativeBrowserNamedTargetSense()
        self.named_automation_control = NativeNamedAutomationControlSense()

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        """Do not let a satisfied subcondition terminate a composite goal."""

        if desktop_task_goal(event) is not None:
            return self._desktop_task_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        if browser_named_text_request(event) is not None:
            return self._browser_named_goal_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        if repo_text_staged_request(event) is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        local_failure = str(state.data.get("local_failure") or "").strip() or None
        investigation = self.investigator.investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        goal_state = repo_text_staged_state(event, investigation.state.facts)

        if investigation.resolved and not bool(goal_state and goal_state.get("satisfied")):
            following = self.investigator._choose_next_probe(
                event,
                readiness,
                facts=investigation.state.facts,
                performed=set(investigation.state.probe_keys),
                learning_evidence=learning_evidence,
            )
            investigation.state.status = "open"
            investigation.state.resolution = None
            investigation.state.unresolved = (
                str((goal_state or {}).get("blocked") or "").strip()
                or "the complete resident goal still has an unsatisfied subcondition"
            )
            investigation.state.next_probe = following
            investigation.state.updated_at = utc_now()
            self.investigator._save(investigation.state)
            investigation.resolved = False
            investigation.response = ""
            investigation.can_continue = bool(following)

        state.data["native_investigation"] = self._investigation_data(investigation.state)
        self._merge_investigation_into_thought(thought, investigation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        goal_state = repo_text_staged_state(event, investigation.state.facts)
        if goal_state is not None and goal_state.get("satisfied"):
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=(
                    f"{goal_state['path']}: requested repository text and staged state "
                    "are both satisfied"
                ),
                reason=(
                    "ZN completed the multi-step resident goal only after fresh file-content "
                    "and structured Git observations simultaneously proved the final state"
                ),
            )

        if investigation.can_continue:
            state.stage = "native_investigation"
            state.next_action = f"run native probe {investigation.state.next_probe}"
            self.store.save_working_state(state)
            return None

        state.stage = "native_deliberation"
        state.next_action = "form the next bounded movement from current goal evidence"
        self.store.save_working_state(state)
        return None

    def _desktop_task_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        """Re-sense one typed desktop goal and expose only its next phase."""

        goal = desktop_task_goal(event)
        assert goal is not None
        source, failure = observe_workspace_text_source(
            event,
            self.body,
            workspace_path=goal.workspace_path,
            name_hint=goal.source_name_hint,
            modified_yesterday=goal.source_modified_yesterday,
        )
        foreground = None
        target = None
        focused = None
        text_state = None
        button = None
        phase = "blocked"

        if failure is None:
            foreground, error = self._probe_foreground_window()
            if foreground is None:
                failure = "foreground desktop window is unavailable: " + str(error)
            elif not str(foreground.title or "").strip():
                failure = "foreground desktop window has no exact title for action authority"
            elif str(foreground.process_name or "").strip().lower() in {
                "chrome.exe",
                "msedge.exe",
                "firefox.exe",
                "brave.exe",
                "opera.exe",
            }:
                failure = "this goal requires the current non-browser desktop application"

        progress = state.data.get(self._DESKTOP_TASK_PROGRESS_KEY)
        progress = dict(progress) if isinstance(progress, dict) else {}
        if failure is None and progress.get("submit_dispatched") is True:
            assert foreground is not None
            pre_title = str(progress.get("pre_title") or "")
            title = str(foreground.title or "").strip()
            final_matches = (
                title == goal.expected_title
                if goal.expected_title
                else bool(title and title != pre_title)
            )
            if final_matches:
                return self._complete_goal_from_fresh_investigation(
                    event,
                    state,
                    readiness=readiness,
                    response=(
                        f"foreground process={foreground.process_name} title={foreground.title}"
                    ),
                    reason=(
                        "fresh foreground evidence independently proved the requested result "
                        "after the one non-replayable submit action"
                    ),
                )
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the submit action may already have been delivered but fresh foreground "
                    "evidence did not prove the requested result; refusing automatic replay"
                ),
            )

        if failure is None:
            assert foreground is not None
            process_name = str(foreground.process_name or "").strip().lower()
            try:
                target = self.named_automation_control.find_unique_edit(
                    process_id=int(foreground.process_id),
                    process_name=process_name,
                    name=goal.input_name,
                )
            except Exception as exc:
                failure = (
                    "fresh investigation could not bind one safe named desktop input: "
                    f"{type(exc).__name__}: {exc}"
                )

        if failure is None:
            assert target is not None and foreground is not None
            focused, focus_error = self._probe_focused_automation_element()
            same_focused_target = bool(
                focused is not None
                and tuple(focused.runtime_id) == tuple(target.runtime_id)
                and int(focused.process_id) == int(target.process_id)
                and int(focused.control_type) == 50004
                and focused.has_keyboard_focus
                and focused.is_enabled
                and focused.is_keyboard_focusable
                and not focused.is_offscreen
                and not focused.is_password
            )
            if not same_focused_target:
                phase = "focus"
            else:
                try:
                    text_state = self.automation_text_state.probe()
                except Exception as exc:
                    failure = (
                        "fresh privacy-safe text evidence is unavailable for the exact input: "
                        f"{type(exc).__name__}: {exc}"
                    )
                if failure is None:
                    expected_chars = int(source["text_chars"])
                    expected_sha = str(source["text_sha256"])
                    if (
                        int(text_state.text_length) == expected_chars
                        and str(text_state.text_sha256 or "") == expected_sha
                    ):
                        phase = "submit"
                    elif int(text_state.text_length) == 0:
                        phase = "fill"
                    else:
                        failure = (
                            "the exact desktop input already contains different text; "
                            "ZN will not delete or replace it implicitly"
                        )

        if failure is None and phase == "submit":
            assert foreground is not None
            try:
                button = self.named_automation_control.find_unique_button(
                    process_id=int(foreground.process_id),
                    process_name=str(foreground.process_name or "").strip().lower(),
                    name=goal.button_name,
                )
            except Exception as exc:
                failure = (
                    "fresh investigation could not bind one exact named desktop Button: "
                    f"{type(exc).__name__}: {exc}"
                )

        observation = {
            "phase": "blocked" if failure else phase,
            "failure": failure,
            "source": source,
            "foreground": asdict(foreground) if foreground is not None else None,
            "target": asdict(target) if target is not None else None,
            "focused": asdict(focused) if focused is not None else None,
            "text": asdict(text_state) if text_state is not None else None,
            "button": asdict(button) if button is not None else None,
            "observed_at": utc_now(),
        }
        state.data[self._DESKTOP_TASK_OBSERVATION_KEY] = observation
        state.data.pop("local_failure", None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if failure:
            return self._fail_composite_goal_investigation(event, state, reason=failure)
        if thought is not None:
            known = (
                "fresh workspace, foreground-window and exact-name UI Automation evidence "
                f"placed the desktop goal in phase={phase}"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            self._persist_enriched_thought(thought)
        state.stage = "native_deliberation"
        state.next_action = f"form the next desktop-goal movement for phase={phase}"
        self.store.save_working_state(state)
        return None

    def _browser_named_goal_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        request = browser_named_text_request(event)
        assert request is not None
        try:
            target = self.browser_named_target.probe_exact_edit(request["target_name"])
        except Exception as exc:
            reason = (
                "current foreground user-browser investigation could not prove one unique safe "
                f"exact-name Edit target: {type(exc).__name__}: {exc}"
            )
            return self._fail_composite_goal_investigation(event, state, reason=reason)

        binding = state.data.get(self._BROWSER_GOAL_BINDING_KEY)
        current_binding = {
            "process_name": target.process_name,
            "foreground_title": target.foreground_title,
        }
        if binding is None:
            state.data[self._BROWSER_GOAL_BINDING_KEY] = dict(current_binding)
        elif not isinstance(binding, dict) or any(
            str(binding.get(key) or "") != str(value)
            for key, value in current_binding.items()
        ):
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "foreground browser identity changed during the bounded named-text goal; "
                    "refusing to transfer input authority to a different window"
                ),
            )

        text_observation = None
        if target.has_keyboard_focus:
            try:
                text_observation = self.automation_text_state.probe()
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the exact named browser target is focused but fresh privacy-safe text "
                        f"evidence is unavailable: {type(exc).__name__}: {exc}"
                    ),
                )

        goal_state = browser_named_text_state(event, target, text_observation)
        assert goal_state is not None
        state.data[self._BROWSER_GOAL_OBSERVATION_KEY] = {
            "goal_state": dict(goal_state),
            "target": asdict(target),
            "text": asdict(text_observation) if text_observation is not None else None,
            "observed_at": utc_now(),
        }
        state.data.pop("local_failure", None)

        if thought is not None:
            known = (
                "fresh foreground-browser UI Automation evidence identified exactly one "
                "user-named safe Edit target"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; current browser reality places the composite goal in "
                f"phase={goal_state['phase']}"
            )
            self._persist_enriched_thought(thought)

        if goal_state["satisfied"]:
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=(
                    f"foreground browser target {request['target_name']!r} contains the "
                    "requested text"
                ),
                reason=(
                    "ZN completed the user-browser goal only after fresh exact-name target "
                    "identity and privacy-safe focused text digest evidence simultaneously "
                    "proved the requested final state"
                ),
            )

        blocked = str(goal_state.get("blocked") or "").strip()
        if blocked:
            return self._fail_composite_goal_investigation(event, state, reason=blocked)

        state.stage = "native_deliberation"
        state.next_action = (
            "form one bounded browser focus movement from current evidence"
            if goal_state["phase"] == "needs_focus"
            else "form one bounded browser text movement from current evidence"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_goal_from_fresh_investigation(
        self,
        event,
        state,
        *,
        readiness,
        response: str,
        reason: str,
    ):
        domains = self.kernel.self_model.infer_domains(
            event.task,
            self._required_capabilities(event),
        )
        completion = {
            "execution_path": ExecutionPath.INVESTIGATION.value,
            "success": True,
            "response": str(response),
            "model_invocations": 0,
            "reason": str(reason),
        }
        state.stage = "investigation_completion"
        state.next_action = "publish terminal EventOutcome"
        state.data["native_domains"] = list(domains)
        state.data["investigation_completion"] = completion
        state.data[self._INVESTIGATION_COMPLETION_ACCOUNTING_KEY] = {
            "version": self._ACCOUNTING_VERSION,
            "kind": "native_investigation_success",
            "domains": list(domains),
            "quality": 0.95,
        }
        self.store.save_working_state(state)
        self._apply_investigation_completion_accounting(event, state)
        return self._investigation_completion_result(event, completion)

    def _fail_composite_goal_investigation(self, event, state, *, reason: str):
        state.data["local_failure"] = str(reason)
        state.stage = "native_investigation"
        state.next_action = "stop before input and surface the current browser-goal evidence gap"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        self.life.begin_impasse(
            event,
            reason=str(reason),
            required_capabilities=self._required_capabilities(event),
            local_failure=str(reason),
        )
        return self._checkpoint_terminal_failure(event, state, reason=str(reason))

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        desktop_goal = desktop_task_goal(event)
        if desktop_goal is not None:
            raw = state.data.get(self._DESKTOP_TASK_OBSERVATION_KEY)
            if not isinstance(raw, dict):
                state.stage = "native_investigation"
                state.next_action = "freshly observe the typed desktop goal"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            failure = str(raw.get("failure") or "").strip()
            phase = str(raw.get("phase") or "").strip().lower()
            source = raw.get("source")
            foreground = raw.get("foreground")
            target = raw.get("target")
            focused = raw.get("focused")
            button = raw.get("button")
            if failure:
                return self._fail_composite_goal_investigation(
                    event, state, reason=failure
                )
            intent = None
            if (
                phase == "focus"
                and isinstance(foreground, dict)
                and isinstance(target, dict)
            ):
                intent = NativeActionIntent(
                    intent_id=f"desktop-goal-focus-{uuid.uuid4().hex[:12]}",
                    event_id=event.event_id,
                    kind="pointer_click",
                    args={
                        "x_fraction": float(target["center_x_fraction"]),
                        "y_fraction": float(target["center_y_fraction"]),
                        "button": "left",
                        "target_runtime_id": list(target["runtime_id"]),
                    },
                    expected_outcome={
                        "kind": self._DESKTOP_EDIT_FOCUS_KIND,
                        "process_name": str(foreground["process_name"]).strip().lower(),
                        "pre_title": str(foreground["title"]),
                        "input_name": desktop_goal.input_name,
                        "target_runtime_id": list(target["runtime_id"]),
                        "target_center_x_fraction": float(target["center_x_fraction"]),
                        "target_center_y_fraction": float(target["center_y_fraction"]),
                        "target_class_name": str(target.get("class_name") or ""),
                    },
                    reason=(
                        "fresh exact-name evidence bound one safe input in the current app; "
                        "perform only the focus movement before re-sensing"
                    ),
                    source="resident_choice",
                )
            elif (
                phase == "fill"
                and isinstance(source, dict)
                and isinstance(foreground, dict)
                and isinstance(target, dict)
                and isinstance(focused, dict)
            ):
                scope = {
                    "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
                    "process_name": str(foreground["process_name"]).strip().lower(),
                    "title_equals": str(foreground["title"]),
                    "control_type": 50004,
                    "class_name_equals": str(focused.get("class_name") or ""),
                    "automation_id_equals": str(focused.get("automation_id") or ""),
                }
                intent = NativeActionIntent(
                    intent_id=f"desktop-goal-text-{uuid.uuid4().hex[:12]}",
                    event_id=event.event_id,
                    kind="keyboard_text",
                    args={},
                    expected_outcome={
                        "kind": self._DESKTOP_TEXT_KIND,
                        "source": dict(source),
                        "completion_scope": scope,
                        "action_precondition": {
                            "kind": "foreground_window_matches",
                            "process_name": scope["process_name"],
                            "title_equals": scope["title_equals"],
                        },
                        "target_runtime_id": list(target["runtime_id"]),
                    },
                    reason=(
                        "fresh file identity and fresh focused safe Edit evidence authorize "
                        "one bounded text movement before re-sensing"
                    ),
                    source="resident_choice",
                )
            elif (
                phase == "submit"
                and isinstance(foreground, dict)
                and isinstance(button, dict)
            ):
                intent = NativeActionIntent(
                    intent_id=f"desktop-goal-submit-{uuid.uuid4().hex[:12]}",
                    event_id=event.event_id,
                    kind="pointer_click",
                    args={
                        "x_fraction": float(button["center_x_fraction"]),
                        "y_fraction": float(button["center_y_fraction"]),
                        "button": "left",
                        "target_runtime_id": list(button["runtime_id"]),
                    },
                    expected_outcome={
                        "kind": self._DESKTOP_SUBMIT_KIND,
                        "process_name": str(foreground["process_name"]).strip().lower(),
                        "pre_title": str(foreground["title"]),
                        "button_name": desktop_goal.button_name,
                        "button_runtime_id": list(button["runtime_id"]),
                        "button_center_x_fraction": float(button["center_x_fraction"]),
                        "button_center_y_fraction": float(button["center_y_fraction"]),
                        "expected_title": desktop_goal.expected_title,
                    },
                    reason=(
                        "verified requested text and fresh exact-name Button evidence authorize "
                        "one non-replayable submit movement"
                    ),
                    source="resident_choice",
                )
            if intent is None:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason="fresh typed desktop-goal evidence did not form one safe next movement",
                )
            if self._action_blocked_by_current_evidence(event, state, intent):
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason=(
                        "the same desktop movement remains blocked by unchanged evidence; "
                        "ZN will not replay it"
                    ),
                )
            self._begin_native_action_cycle(event, state, intent)
            self.store.save_working_state(state)
            return None

        browser_request = browser_named_text_request(event)
        if browser_request is not None:
            raw_observation = state.data.get(self._BROWSER_GOAL_OBSERVATION_KEY)
            goal_state = (
                raw_observation.get("goal_state")
                if isinstance(raw_observation, dict)
                else None
            )
            if not isinstance(goal_state, dict):
                state.stage = "native_investigation"
                state.next_action = "re-observe the exact named browser target"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            intent = browser_named_text_intent(event, goal_state)
            if intent is None:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        str(goal_state.get("blocked") or "").strip()
                        or "fresh browser goal evidence did not form a safe next movement"
                    ),
                )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform user-browser goal substep through body: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; fresh exact target evidence formed only the current "
                        "browser movement and did not precommit the later substep"
                    )
                    self._persist_enriched_thought(thought)
                return None
            return None

        request = repo_text_staged_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        goal_state = repo_text_staged_state(event, facts)
        intents = repo_text_staged_action_intents(event, facts)

        if goal_state is not None and goal_state.get("satisfied"):
            state.stage = "native_investigation"
            state.next_action = "reconfirm the complete resident goal from current reality"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if intents:
            intent = intents[0]
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform goal substep through body: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    known = (
                        "the current resident goal still has an independently observable "
                        "unsatisfied subcondition"
                    )
                    if known not in thought.known:
                        thought.known = (*thought.known, known)
                    thought.reason = (
                        f"{thought.reason}; current evidence formed one bounded next movement "
                        "without precommitting the later goal steps"
                    )
                    self._persist_enriched_thought(thought)
                return None

        blocked = str((goal_state or {}).get("blocked") or "").strip()
        reason = blocked or (
            "current Investigation exhausted its probes without proving a safe next "
            "movement for the typed resident goal"
        )
        self.life.begin_impasse(
            event,
            reason=reason,
            required_capabilities=self._required_capabilities(event),
            local_failure=None,
        )
        return self._checkpoint_terminal_failure(event, state, reason=reason)

    def _pointer_click_contract(self, event, intent):
        desktop_goal = desktop_task_goal(event)
        raw_desktop = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        desktop_kind = str(raw_desktop.get("kind") or "").strip().lower()
        if desktop_goal is not None and intent.kind == "pointer_click":
            if desktop_kind == self._DESKTOP_EDIT_FOCUS_KIND:
                scope: dict[str, Any] = {
                    "kind": self._AUTOMATION_SCOPE_KIND,
                    "process_name": str(raw_desktop.get("process_name") or "").strip().lower(),
                    "title_equals": str(raw_desktop.get("pre_title") or "").strip(),
                    "control_type": 50004,
                }
                class_name = str(raw_desktop.get("target_class_name") or "").strip()
                if class_name:
                    scope["class_name_equals"] = class_name
                return {
                    "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                    "center_x_fraction": float(intent.args["x_fraction"]),
                    "center_y_fraction": float(intent.args["y_fraction"]),
                    "width_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                    "height_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                    "completion_scope": scope,
                    "completion_event_kind": str(event.kind or "").strip().lower(),
                    "action_precondition": {
                        "kind": self._UI_SCOPE_KIND,
                        "process_name": scope["process_name"],
                        "title_equals": scope["title_equals"],
                    },
                }, None
            if desktop_kind == self._DESKTOP_SUBMIT_KIND:
                synthetic = replace(
                    event,
                    payload={
                        **dict(event.payload or {}),
                        "expected_outcome": {
                            "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                            "width_fraction": 0.08,
                            "height_fraction": 0.08,
                        },
                    },
                )
                return VerifiedPointerClickResidentRuntime._pointer_click_contract(
                    self, synthetic, intent
                )

        request = browser_named_text_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "pointer_click"
            and str(raw_goal.get("kind") or "").strip().lower()
            == "browser_named_target_focused"
        ):
            scope: dict[str, Any] = {
                "kind": self._AUTOMATION_SCOPE_KIND,
                "process_name": str(raw_goal.get("process_name") or "").strip().lower(),
                "title_equals": str(raw_goal.get("title_equals") or "").strip(),
                "control_type": int(raw_goal.get("control_type") or 0),
            }
            class_name = str(raw_goal.get("class_name_equals") or "").strip()
            if class_name:
                scope["class_name_equals"] = class_name
            return {
                "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                "center_x_fraction": float(intent.args["x_fraction"]),
                "center_y_fraction": float(intent.args["y_fraction"]),
                "width_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                "height_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                "completion_scope": scope,
                "completion_event_kind": str(event.kind or "").strip().lower(),
                "action_precondition": {
                    "kind": self._UI_SCOPE_KIND,
                    "process_name": scope["process_name"],
                    "title_equals": scope["title_equals"],
                },
            }, None
        return super()._pointer_click_contract(event, intent)

    def _keyboard_text_contract(self, event, intent):
        goal = desktop_task_goal(event)
        raw_desktop = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            goal is not None
            and intent.kind == "keyboard_text"
            and str(raw_desktop.get("kind") or "").strip().lower()
            == self._DESKTOP_TEXT_KIND
        ):
            source = raw_desktop.get("source")
            if not isinstance(source, dict):
                return None, "desktop goal lost its exact workspace source evidence"
            text, error = fresh_workspace_text(event, self.body, source)
            if error or text is None:
                return None, error or "workspace source text is unavailable"
            completion_scope = raw_desktop.get("completion_scope")
            action_precondition = raw_desktop.get("action_precondition")
            if not isinstance(completion_scope, dict) or not isinstance(action_precondition, dict):
                return None, "desktop goal lost its exact focused-target authority"
            synthetic = replace(
                event,
                kind=self._UI_EVENT_KIND,
                payload={
                    **dict(event.payload or {}),
                    "expected_outcome": {"kind": self._TEXT_OUTCOME_KIND},
                    "completion_scope": dict(completion_scope),
                    "action_precondition": dict(action_precondition),
                    "model_policy": "never",
                },
            )
            transient = NativeActionIntent(
                intent_id=intent.intent_id,
                event_id=intent.event_id,
                kind=intent.kind,
                args={"text": text},
                expected_outcome=intent.expected_outcome,
                reason=intent.reason,
                source=intent.source,
                created_at=intent.created_at,
            )
            return super()._keyboard_text_contract(synthetic, transient)

        request = browser_named_text_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "keyboard_text"
            and str(raw_goal.get("kind") or "").strip().lower()
            == "browser_named_text_equals"
        ):
            try:
                text, units = KeyboardTextBody.validate_text(intent.args.get("text"))
            except ValueError as exc:
                return None, str(exc)
            if text != request["text"]:
                return None, "browser goal text drifted from the current user-owned goal"
            expected_sha = NativeFocusedTextSense.digest_text(text)
            if (
                expected_sha != str(raw_goal.get("expected_text_sha256") or "")
                or len(text) != int(raw_goal.get("expected_text_chars") or -1)
            ):
                return None, "browser goal text digest authority drifted before input"
            scope = {
                "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
                "process_name": str(raw_goal.get("process_name") or "").strip().lower(),
                "title_equals": str(raw_goal.get("title_equals") or "").strip(),
                "control_type": int(raw_goal.get("control_type") or 0),
                "class_name_equals": str(raw_goal.get("class_name_equals") or "").strip(),
                "automation_id_equals": str(raw_goal.get("automation_id_equals") or "").strip(),
            }
            return {
                "kind": self._TEXT_OUTCOME_KIND,
                "text": text,
                "utf16_units": len(units),
                "expected_text_chars": len(text),
                "expected_text_sha256": expected_sha,
                "completion_scope": scope,
                "completion_event_kind": self._UI_EVENT_KIND,
                "action_precondition": {
                    "kind": self._UI_SCOPE_KIND,
                    "process_name": scope["process_name"],
                    "title_equals": scope["title_equals"],
                },
            }, None
        return super()._keyboard_text_contract(event, intent)

    def _pointer_click_final_input_precondition(
        self,
        event,
        state,
        intent,
        contract,
        prepared,
    ):
        goal = desktop_task_goal(event)
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        kind = str(expected.get("kind") or "").strip().lower()
        if goal is None or intent.kind != "pointer_click" or kind not in {
            self._DESKTOP_EDIT_FOCUS_KIND,
            self._DESKTOP_SUBMIT_KIND,
        }:
            return super()._pointer_click_final_input_precondition(
                event, state, intent, contract, prepared
            )
        foreground, error = self._probe_foreground_window()
        process_name = str(expected.get("process_name") or "").strip().lower()
        pre_title = str(expected.get("pre_title") or "").strip()
        if foreground is None:
            return "fresh foreground recheck before desktop input is unavailable: " + str(error)
        if (
            str(foreground.process_name or "").strip().lower() != process_name
            or str(foreground.title or "").strip() != pre_title
        ):
            return "foreground desktop application changed before the final input boundary"
        try:
            if kind == self._DESKTOP_EDIT_FOCUS_KIND:
                fresh = self.named_automation_control.find_unique_edit(
                    process_id=int(foreground.process_id),
                    process_name=process_name,
                    name=goal.input_name,
                )
                expected_runtime = tuple(int(v) for v in expected.get("target_runtime_id") or ())
                expected_x = float(expected.get("target_center_x_fraction") or -1.0)
                expected_y = float(expected.get("target_center_y_fraction") or -1.0)
            else:
                fresh = self.named_automation_control.find_unique_button(
                    process_id=int(foreground.process_id),
                    process_name=process_name,
                    name=goal.button_name,
                )
                expected_runtime = tuple(int(v) for v in expected.get("button_runtime_id") or ())
                expected_x = float(expected.get("button_center_x_fraction") or -1.0)
                expected_y = float(expected.get("button_center_y_fraction") or -1.0)
        except Exception as exc:
            return f"exact named desktop control could not be freshly revalidated: {type(exc).__name__}: {exc}"
        if tuple(fresh.runtime_id) != expected_runtime:
            return "exact named desktop control RuntimeId changed before input"
        if (
            abs(float(fresh.center_x_fraction) - expected_x) > 0.002
            or abs(float(fresh.center_y_fraction) - expected_y) > 0.002
        ):
            return "exact named desktop control moved materially before input"
        return super()._pointer_click_final_input_precondition(
            event, state, intent, contract, prepared
        )

    def _verification_contract(self, event, intent, *, result=None):
        request = repo_text_staged_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "command"
            and intent.source == "resident_choice"
            and str(raw_goal.get("kind") or "").strip().lower() == "git_path_staged"
        ):
            staged_event = replace(
                event,
                payload={
                    **dict(event.payload or {}),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": request["path"],
                    },
                },
            )
            return super()._verification_contract(
                staged_event,
                intent,
                result=result,
            )
        return super()._verification_contract(event, intent, result=result)

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        """Treat a verified movement as progress until the composite goal is re-sensed."""

        desktop_goal = desktop_task_goal(event)
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        desktop_kind = str(expected.get("kind") or "").strip().lower()
        if desktop_goal is not None and desktop_kind in {
            self._DESKTOP_EDIT_FOCUS_KIND,
            self._DESKTOP_TEXT_KIND,
            self._DESKTOP_SUBMIT_KIND,
        }:
            verification = state.data.get("native_verification_result")
            if not isinstance(verification, dict) or verification.get("verified") is not True:
                return super()._complete_successful_body_action(
                    event, state, intent, response=response, reason=reason
                )
            if desktop_kind == self._DESKTOP_EDIT_FOCUS_KIND:
                foreground, error = self._probe_foreground_window()
                try:
                    fresh = (
                        self.named_automation_control.find_unique_edit(
                            process_id=int(foreground.process_id),
                            process_name=str(foreground.process_name or "").strip().lower(),
                            name=desktop_goal.input_name,
                        )
                        if foreground is not None
                        else None
                    )
                except Exception as exc:
                    fresh = None
                    error = f"{type(exc).__name__}: {exc}"
                if not (
                    fresh is not None
                    and fresh.has_keyboard_focus
                    and tuple(fresh.runtime_id)
                    == tuple(int(v) for v in expected.get("target_runtime_id") or ())
                ):
                    return self._fail_composite_goal_investigation(
                        event,
                        state,
                        reason=(
                            "the focus click was already delivered, but fresh exact-target "
                            f"evidence did not prove focus; refusing replay: {error or 'focus mismatch'}"
                        ),
                    )
            if desktop_kind == self._DESKTOP_SUBMIT_KIND:
                state.data[self._DESKTOP_TASK_PROGRESS_KEY] = {
                    "submit_dispatched": True,
                    "pre_title": str(expected.get("pre_title") or ""),
                    "button_runtime_id": list(expected.get("button_runtime_id") or ()),
                    "dispatched_at": utc_now(),
                }
            self._reset_investigation_after_goal_substep(event, state, intent)
            state.data.pop(self._DESKTOP_TASK_OBSERVATION_KEY, None)
            state.stage = "native_investigation"
            state.next_action = "re-sense the complete desktop goal after the verified substep"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        is_repo_goal = repo_text_staged_request(event) is not None
        browser_request = browser_named_text_request(event)
        is_browser_goal = browser_request is not None
        if not is_repo_goal and not is_browser_goal:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        verification = state.data.get("native_verification_result")
        if not isinstance(verification, dict) or verification.get("verified") is not True:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        progress_verification_kind = str(verification.get("kind") or "")
        if is_browser_goal and intent.kind == "pointer_click":
            raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
            expected_runtime = raw_goal.get("target_runtime_id")
            if not isinstance(expected_runtime, list) or not expected_runtime:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the already-dispatched browser focus click lost its exact pre-click "
                        "RuntimeId evidence; refusing any replay"
                    ),
                )
            try:
                assert browser_request is not None
                focused = self.browser_named_target.probe_exact_edit(
                    browser_request["target_name"]
                )
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the browser focus click was already dispatched, but fresh exact-name "
                        "focus verification is unavailable; refusing any replay: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            focus_verified = bool(
                focused.has_keyboard_focus
                and tuple(focused.runtime_id)
                == tuple(int(value) for value in expected_runtime)
                and focused.process_name
                == str(raw_goal.get("process_name") or "").strip().lower()
                and focused.foreground_title
                == str(raw_goal.get("title_equals") or "").strip()
            )
            state.data[self._BROWSER_GOAL_FOCUS_VERIFICATION_KEY] = {
                "verified": focus_verified,
                "kind": "browser_named_target_focused",
                "expected_runtime_id": [int(value) for value in expected_runtime],
                "observed_runtime_id": list(focused.runtime_id),
                "observation": asdict(focused),
                "verified_at": utc_now(),
            }
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            if not focus_verified:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the browser focus click was already dispatched and its local visual "
                        "effect was observed, but fresh exact-name UI Automation evidence did "
                        "not prove that the same target gained focus; refusing automatic replay"
                    ),
                )
            progress_verification_kind = "browser_named_target_focused"

        latest = state.data.get("latest_verified_experience")
        experience_id = (
            str(latest.get("experience_id") or "").strip()
            if isinstance(latest, dict)
            else ""
        )
        raw_progress = state.data.get(self._RESIDENT_GOAL_PROGRESS_KEY)
        progress = list(raw_progress) if isinstance(raw_progress, list) else []
        progress.append(
            {
                "action_kind": str(intent.kind or ""),
                "verification_kind": progress_verification_kind,
                "experience_id": experience_id or None,
                "verified_at": utc_now(),
            }
        )
        state.data[self._RESIDENT_GOAL_PROGRESS_KEY] = progress[
            -self._MAX_RESIDENT_GOAL_PROGRESS :
        ]

        self._reset_investigation_after_goal_substep(event, state, intent)
        state.stage = "native_investigation"
        state.next_action = "re-sense the composite goal after the verified substep"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _reset_investigation_after_goal_substep(self, event, state, intent) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is not None:
            investigation.updated_at = utc_now()
            investigation.probes = ()
            investigation.probe_keys = ()
            investigation.facts = {}
            investigation.unresolved = None
            investigation.next_probe = None
            investigation.status = "open"
            investigation.resolution = None
            investigation.evidence = (
                *investigation.evidence,
                f"verified resident-goal substep completed: {intent.kind}; re-sensing current reality",
            )[-64:]
            self.investigator._save(investigation)

        for key in (
            "native_investigation",
            "native_deliberation",
            "native_action_intent",
            "native_action_result",
            "native_verification",
            "native_verification_result",
            "native_completion",
            "local_failure",
            self._BROWSER_GOAL_OBSERVATION_KEY,
            self._BROWSER_GOAL_FOCUS_VERIFICATION_KEY,
            self._REPO_TEXT_BASELINE_KEY,
            self._TARGETED_TEST_EXECUTION_KEY,
            self._PROCEDURAL_INFLUENCE_KEY,
            self._POINTER_CLICK_PRECONDITION_KEY,
            self._POINTER_CLICK_EXECUTION_KEY,
            self._SEMANTIC_PRECONDITION_KEY,
            self._AUTOMATION_TARGET_KEY,
            self._AUTOMATION_VERIFICATION_KEY,
            self._TEXT_PRECONDITION_KEY,
            self._TEXT_EXECUTION_KEY,
            self._TEXT_VERIFICATION_KEY,
        ):
            state.data.pop(key, None)

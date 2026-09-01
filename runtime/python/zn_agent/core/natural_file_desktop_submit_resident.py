from __future__ import annotations

"""Multi-step natural Work: workspace value -> desktop Edit -> exact named Button."""

import re
from dataclasses import asdict, replace
from typing import Any, Mapping

from .action import NativeActionIntent
from .automation_named_control_sense import (
    NamedAutomationControlObservation,
    NativeNamedAutomationControlSense,
)
from .models import WorkingState, utc_now
from .natural_file_desktop_resident import NaturalFileDesktopResidentRuntime
from .pointer_click_resident import VerifiedPointerClickResidentRuntime


_BUTTON_RE = re.compile(
    r"(?:点击|点|按下)\s*(?:按钮)?\s*[\"“'‘](?P<name>[^\"”'’‘，,。；;\r\n]{1,160})[\"”'’]"
)
_RESULT_TITLE_RE = re.compile(
    r"(?:窗口(?:标题)?|软件(?:窗口)?|界面)\s*(?:会)?\s*(?:变成|变为|显示为|显示成)\s*"
    r"[\"“'‘](?P<title>[^\"”'’‘\r\n]{1,240})[\"”'’]"
)


class NaturalFileDesktopSubmitResidentRuntime(NaturalFileDesktopResidentRuntime):
    """Close one real non-browser desktop task without introducing a desktop manager.

    The first substep is the existing verified File -> focused Edit transfer. A
    verified text mutation is progress, not task completion, when the user also
    names one exact desktop Button and one exact final foreground-window title.

    ZN then freshly searches only the current foreground application's UIA tree
    for exactly one enabled visible Button with that exact accessible name. The
    discovered RuntimeId and center are re-observed again at the final pointer
    input boundary. The click reuses the existing durable non-replayable pointer
    lifecycle and its target-local visual change evidence. Task completion still
    requires a separate fresh foreground-window observation matching the exact
    requested final process/title.
    """

    _DESKTOP_SUBMIT_STATE_KEY = "natural_file_desktop_submit"
    _DESKTOP_CLICK_OUTCOME_KIND = "desktop_named_button_to_foreground_title"
    _BUTTON_PROBE_LABEL = "bind one exact named Button in the current desktop app"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.named_automation_control = NativeNamedAutomationControlSense()

    @classmethod
    def _natural_file_desktop_submit_request(cls, event) -> dict[str, str] | None:
        base = cls._natural_file_to_focused_desktop_request(event)
        if base is None:
            return None
        task = " ".join(str(event.task or "").strip().split())
        buttons = [match.group("name").strip() for match in _BUTTON_RE.finditer(task)]
        titles = [match.group("title").strip() for match in _RESULT_TITLE_RE.finditer(task)]
        unique_buttons = list(dict.fromkeys(value for value in buttons if value))
        unique_titles = list(dict.fromkeys(value for value in titles if value))
        if len(unique_buttons) != 1 or len(unique_titles) != 1:
            return None
        return {
            **base,
            "button_name": unique_buttons[0],
            "expected_title": unique_titles[0],
        }

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_file_desktop_submit_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
        if not isinstance(progress, dict) or progress.get("typed_verified") is not True:
            # Let NaturalFileDesktopResidentRuntime perform the already-verified
            # exact file selection, fresh source reread, focused Edit binding and
            # non-replayable keyboard input. _complete_successful_body_action
            # below converts that verified mutation into composite progress.
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        process_name = str(progress.get("process_name") or "").strip().lower()
        pre_title = str(progress.get("pre_title") or "").strip()
        expected_title = str(progress.get("expected_title") or request["expected_title"]).strip()
        button_name = str(progress.get("button_name") or request["button_name"]).strip()
        if not process_name or not pre_title or not expected_title or not button_name:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="desktop submit progress lost its exact application/button/result identity",
            )

        observed, error = self._probe_foreground_window()
        if observed is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="fresh desktop foreground state is unavailable before the submit step: "
                + str(error or "unknown foreground error"),
            )
        if self._foreground_equals(observed, process_name, expected_title):
            return self._complete_desktop_submit_from_fresh_foreground(
                event,
                state,
                process_name=process_name,
                expected_title=expected_title,
                observed=observed,
                reason=(
                    "the exact final desktop state was already freshly observed before another "
                    "click was necessary; ZN completed the user's result rather than replaying input"
                ),
            )

        execution = state.data.get(self._POINTER_CLICK_EXECUTION_KEY)
        click_intent_id = f"desktop-submit-click-{event.event_id}"
        if (
            isinstance(execution, dict)
            and str(execution.get("intent_id") or "") == click_intent_id
            and str(execution.get("status") or "").strip().lower() in {"started", "completed"}
        ):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the desktop submit click may already have been delivered but the exact final "
                    "window state is not proven; ZN will not replay the non-idempotent click"
                ),
            )

        if not self._foreground_equals(observed, process_name, pre_title):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the foreground desktop application changed after text entry; ZN stopped before "
                    "clicking because the intended submit context is no longer current"
                ),
            )

        try:
            button = self.named_automation_control.find_unique_button(
                process_id=int(observed.process_id),
                process_name=process_name,
                name=button_name,
            )
        except Exception as exc:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "ZN could not freshly bind exactly one safe named Button in the current desktop "
                    f"application: {type(exc).__name__}: {exc}"
                ),
            )

        progress = dict(progress)
        progress.update(
            {
                "button_runtime_id": list(button.runtime_id),
                "button_center_x_fraction": float(button.center_x_fraction),
                "button_center_y_fraction": float(button.center_y_fraction),
                "button_observed_at": button.captured_at,
                "button_source": button.source,
            }
        )
        state.data[self._DESKTOP_SUBMIT_STATE_KEY] = progress

        intent = NativeActionIntent(
            intent_id=click_intent_id,
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(button.center_x_fraction),
                "y_fraction": float(button.center_y_fraction),
                "button": "left",
            },
            expected_outcome={
                "kind": self._DESKTOP_CLICK_OUTCOME_KIND,
                "process_name": process_name,
                "pre_title": pre_title,
                "button_name": button_name,
                "button_runtime_id": list(button.runtime_id),
                "button_center_x_fraction": float(button.center_x_fraction),
                "button_center_y_fraction": float(button.center_y_fraction),
                "expected_title": expected_title,
            },
            reason=(
                "fresh UIA evidence bound exactly one enabled visible Button in the same foreground "
                "application after verified text entry; reuse the durable non-replayable click lifecycle"
            ),
            source="resident_choice",
        )
        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact desktop submit click remains blocked by unchanged failure evidence; "
                    "ZN will not replay it"
                ),
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = f'click the freshly revalidated desktop Button "{button_name}" once'
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = (
                f"{thought.reason}; verified text entry is only progress, and fresh exact-name UIA "
                "evidence now supports one bounded non-replayable submit click"
            )
            self._persist_enriched_thought(thought)
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
        request = self._natural_file_desktop_submit_request(event)
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        expected_kind = str(expected.get("kind") or "").strip().lower()

        if (
            request is not None
            and intent.kind == "keyboard_text"
            and expected_kind == self._FILE_TO_DESKTOP_OUTCOME_KIND
        ):
            investigation = self.investigator.current(event.event_id)
            facts = dict(investigation.facts) if investigation is not None else {}
            source = facts.get("natural_file_desktop_source")
            destination = facts.get("natural_file_desktop_destination")
            if not isinstance(source, Mapping) or not isinstance(destination, Mapping):
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified desktop text entry lost its exact source/destination investigation evidence",
                )
            completion_scope = destination.get("completion_scope")
            action_precondition = destination.get("action_precondition")
            if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified desktop text entry lost its exact application authority",
                )
            process_name = str(completion_scope.get("process_name") or "").strip().lower()
            pre_title = str(action_precondition.get("title_equals") or "").strip()
            if not process_name or not pre_title:
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified desktop text entry lost its exact foreground process/title",
                )
            state.data[self._DESKTOP_SUBMIT_STATE_KEY] = {
                "typed_verified": True,
                "typed_at": utc_now(),
                "process_name": process_name,
                "pre_title": pre_title,
                "button_name": request["button_name"],
                "expected_title": request["expected_title"],
                "source_text_sha256": str(source.get("text_sha256") or ""),
                "source_text_chars": int(source.get("text_chars") or 0),
            }
            state.stage = "native_investigation"
            state.next_action = "freshly locate the named Button in the current desktop application"
            state.data.pop("local_failure", None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if (
            request is not None
            and intent.kind == "pointer_click"
            and expected_kind == self._DESKTOP_CLICK_OUTCOME_KIND
        ):
            process_name = str(expected.get("process_name") or "").strip().lower()
            expected_title = str(expected.get("expected_title") or "").strip()
            observed, error = self._probe_foreground_window()
            if observed is not None and self._foreground_equals(
                observed,
                process_name,
                expected_title,
            ):
                progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
                if isinstance(progress, dict):
                    progress = dict(progress)
                    progress["click_verified_at"] = utc_now()
                    progress["final_foreground"] = asdict(observed)
                    state.data[self._DESKTOP_SUBMIT_STATE_KEY] = progress
                return self._complete_desktop_submit_from_fresh_foreground(
                    event,
                    state,
                    process_name=process_name,
                    expected_title=expected_title,
                    observed=observed,
                    reason=(
                        "ZN completed the multi-step desktop Work only after verified file-to-Edit "
                        "text entry, one non-replayable named-Button click, target-local visual "
                        "change evidence, and a separate fresh exact foreground process/title observation"
                    ),
                )
            self._record_failed_action(
                event,
                state,
                intent,
                source="verification",
                failure=(
                    "fresh foreground state did not prove the exact requested desktop result after "
                    "the non-replayable click: " + str(error or self._foreground_summary(observed))
                ),
            )
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the desktop submit click was sent but the exact requested final window state "
                    "was not independently proven; ZN will not replay the click"
                ),
            )

        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
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
            != self._DESKTOP_CLICK_OUTCOME_KIND
        ):
            return super()._pointer_click_contract(event, intent)
        synthetic_event = replace(
            event,
            payload={
                "expected_outcome": {
                    "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                    "width_fraction": 0.08,
                    "height_fraction": 0.08,
                }
            },
        )
        return VerifiedPointerClickResidentRuntime._pointer_click_contract(
            self,
            synthetic_event,
            intent,
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
            != self._DESKTOP_CLICK_OUTCOME_KIND
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
        button_name = str(expected.get("button_name") or "").strip()
        expected_runtime = tuple(int(value) for value in (expected.get("button_runtime_id") or ()))
        if not process_name or not pre_title or not button_name or not expected_runtime:
            return "desktop named-Button click lost its exact pre-input authority"
        observed, error = self._probe_foreground_window()
        if observed is None:
            return "fresh foreground recheck before desktop click is unavailable: " + str(error)
        if not self._foreground_equals(observed, process_name, pre_title):
            return "foreground desktop application changed before the final named-Button click boundary"
        try:
            fresh_button = self.named_automation_control.find_unique_button(
                process_id=int(observed.process_id),
                process_name=process_name,
                name=button_name,
            )
        except Exception as exc:
            return f"exact named Button could not be freshly revalidated before input: {type(exc).__name__}: {exc}"
        if tuple(fresh_button.runtime_id) != expected_runtime:
            return "exact named Button RuntimeId changed before input; refusing a stale click target"
        expected_x = float(expected.get("button_center_x_fraction") or -1.0)
        expected_y = float(expected.get("button_center_y_fraction") or -1.0)
        if (
            abs(float(fresh_button.center_x_fraction) - expected_x) > 0.002
            or abs(float(fresh_button.center_y_fraction) - expected_y) > 0.002
        ):
            return "exact named Button moved materially before input; refusing the stale click point"
        return None

    def _complete_desktop_submit_from_fresh_foreground(
        self,
        event,
        state,
        *,
        process_name: str,
        expected_title: str,
        observed,
        reason: str,
    ):
        scope = {
            "kind": "foreground_window_matches",
            "process_name": process_name,
            "title_equals": expected_title,
        }
        state.data["natural_file_desktop_submit_final"] = {
            "verified": True,
            "scope": dict(scope),
            "observation": asdict(observed),
            "verified_at": utc_now(),
        }
        return self._complete_ui_scope(
            event,
            state,
            scope,
            response=self._foreground_summary(observed),
            reason=reason,
        )

    @staticmethod
    def _foreground_equals(observed, process_name: str, title: str) -> bool:
        return bool(
            observed is not None
            and str(observed.process_name or "").strip().lower()
            == str(process_name or "").strip().lower()
            and str(observed.title or "").strip() == str(title or "").strip()
        )

    @staticmethod
    def _foreground_summary(observed) -> str:
        if observed is None:
            return "foreground window unavailable"
        return (
            f"foreground process={str(observed.process_name or '').strip()} "
            f"title={str(observed.title or '').strip()}"
        )

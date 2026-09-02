from __future__ import annotations

"""Bounded ordinary-language workspace work and shared desktop task closure."""

import hashlib
import re
import uuid
from dataclasses import asdict, replace
from typing import Any, Mapping

from .action import NativeActionIntent
from .automation_named_control_sense import (
    NamedAutomationControlObservation,
    NativeNamedAutomationControlSense,
)
from .desktop_task_goal import desktop_task_request
from .investigation import InvestigationResult
from .keyboard_text_body import KeyboardTextBody
from .models import WorkingState, utc_now
from .natural_file_goal import (
    compare_candidates,
    edit_intent,
    failure_reason,
    natural_workspace_text_edit_request,
    observe_candidates,
    observe_text_source,
    read_target,
    read_text_source,
)
from .pointer_click_automation_focus_resident import AutomationFocusPointerClickResidentRuntime
from .pointer_click_resident import VerifiedPointerClickResidentRuntime
from .user_browser_extension_relay import UserBrowserExtensionRelayError
from .user_browser_managed_research_resident import UserBrowserManagedResearchResidentRuntime


_BROWSER_FILE_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?\s*\.?\s*txt(?=[，,。；;\s]|$)",
    re.I,
)
_BROWSER_FILE_SOURCE = re.compile(
    r"把\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,128}?)[\"”'’]?\s*改成\s*"
    r"(?:查到的|确认的|研究得到的|刚查到的|刚确认的)?\s*(?:release\s+code|代码)",
    re.I,
)
_BROWSER_PROCESS_NAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}


class NaturalFileWorkResidentRuntime(UserBrowserManagedResearchResidentRuntime):
    """Ground ordinary Work against fresh file/browser/desktop reality.

    Desktop value tasks intentionally live here instead of in a chain of task-
    specific ResidentRuntime subclasses. A parser/model may normalize only typed
    desired state. File identity, browser facts, foreground identity, UIA
    RuntimeId, action authority and completion remain products of fresh
    Investigation and the existing guarded Body lifecycles.
    """

    _NATURAL_FILE_PROBE_LABELS = (
        "enumerate bounded workspace file candidates",
        "compare plausible workspace file contents",
        "freshly read the exact selected workspace file",
    )
    _BROWSER_FILE_RESEARCH_STATE_KEY = "resident_browser_result_file_edit"

    # Keep historical state/fact keys stable while the production route is
    # converged. They are evidence labels, not separate workflows.
    _DESKTOP_SUBMIT_STATE_KEY = "natural_file_desktop_submit"
    _BROWSER_DESKTOP_RESEARCH_STATE_KEY = "natural_browser_desktop_research"
    _BROWSER_DESKTOP_RESEARCH_FACT_KEY = "natural_browser_desktop_research"
    _BROWSER_DESKTOP_DESTINATION_FACT_KEY = "natural_browser_desktop_destination"
    _FILE_DESKTOP_SOURCE_FACT_KEY = "natural_file_desktop_source"
    _FILE_DESKTOP_DESTINATION_FACT_KEY = "natural_file_desktop_destination"
    _NAMED_INPUT_FACT_KEY = "natural_named_desktop_input"
    _NAMED_INPUT_STATE_KEY = "natural_named_desktop_input_focus"
    _BUTTON_FACT_KEY = "natural_file_desktop_submit_button"

    _DESKTOP_TEXT_OUTCOME_KIND = "desktop_value_task_text"
    _FILE_TO_DESKTOP_OUTCOME_KIND = _DESKTOP_TEXT_OUTCOME_KIND
    _BROWSER_DESKTOP_OUTCOME_KIND = _DESKTOP_TEXT_OUTCOME_KIND
    _DESKTOP_FOCUS_OUTCOME_KIND = "desktop_value_task_input_focused"
    _DESKTOP_CLICK_OUTCOME_KIND = "desktop_value_task_submit"

    _SOURCE_PROBE_LABEL = "bind one bounded workspace text source"
    _DESTINATION_PROBE_LABEL = "bind one exact safe current desktop Edit"
    _NAMED_INPUT_PROBE_LABEL = "bind one exact named safe Edit in the current desktop app"
    _BUTTON_PROBE_LABEL = "bind one exact named Button in the current desktop app"
    _BROWSER_RESEARCH_PROBE_LABEL = "research two authorized-page references in isolated managed Chromium"
    _BROWSER_DESKTOP_PROBE_LABEL = "freshly bind the current desktop Edit after browser research"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.named_automation_control = NativeNamedAutomationControlSense()

    @classmethod
    def _natural_browser_result_file_request(cls, event) -> dict[str, str] | None:
        payload = event.payload or {}
        task = " ".join(str(event.task or "").strip().split())
        lowered = task.lower()
        if (
            str(event.kind or "").lower() != "desktop_user_event"
            or not str(payload.get("workspace_path") or "").strip()
            or payload.get("body_action")
            or payload.get("native_action")
            or "昨天" not in task
            or "保存" not in task
            or not any(cue in task for cue in ("读回来", "读回确认", "重新读", "确认"))
            or not ("reference" in lowered or "参考" in task)
            or not ("release code" in lowered or "代码" in task)
        ):
            return None
        hint = _BROWSER_FILE_HINT.search(task)
        source = _BROWSER_FILE_SOURCE.search(task)
        if hint is None or source is None:
            return None
        name_hint = hint.group("v").strip()
        old_text = source.group("v").strip()
        if not name_hint or not old_text:
            return None
        return {
            "workspace_path": str(payload["workspace_path"]),
            "name_hint": name_hint,
            "old_text": old_text,
        }

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        goal = desktop_task_request(event)
        source = goal.get("source_requirement") if isinstance(goal, Mapping) else None
        if (
            payload.get("required_capabilities") is None
            and isinstance(source, Mapping)
            and str(source.get("kind") or "") == "managed_browser_research"
        ):
            return ("browser",)
        if (
            payload.get("required_capabilities") is None
            and cls._natural_browser_result_file_request(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        desktop_goal = desktop_task_request(event)
        if isinstance(desktop_goal, Mapping):
            return self._desktop_task_deliberation(
                event,
                state,
                desktop_goal,
                thought=thought,
            )

        effective_event = event
        browser_file_request = self._natural_browser_result_file_request(event)
        if browser_file_request is not None:
            prepared = self._prepare_browser_result_file_event(
                event,
                state,
                browser_file_request,
                thought=thought,
            )
            if prepared is None:
                return None
            if isinstance(prepared, str):
                return self._checkpoint_terminal_failure(event, state, reason=prepared)
            effective_event = prepared

        request = natural_workspace_text_edit_request(effective_event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        facts = dict(investigation.facts)
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)

        discovery, notes = observe_candidates(effective_event, self.body)
        facts["natural_file_candidates"] = discovery
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key="natural_file_candidates",
            label=self._NATURAL_FILE_PROBE_LABELS[0],
            notes=notes,
        )

        comparison: dict[str, Any] = {
            "complete": False,
            "selected": None,
            "failure_reason": str(discovery.get("failure_reason") or ""),
        }
        if discovery.get("ready") is True:
            comparison, notes = compare_candidates(effective_event, self.body, discovery)
            self._record_probe(
                evidence,
                probes,
                probe_keys,
                key="natural_file_candidate_comparison",
                label=self._NATURAL_FILE_PROBE_LABELS[1],
                notes=notes,
            )
        facts["natural_file_candidate_comparison"] = comparison

        target_read: dict[str, Any] = {
            "complete": False,
            "failure_reason": str(comparison.get("failure_reason") or ""),
        }
        selected = comparison.get("selected")
        if isinstance(selected, dict):
            target_read, preview, notes = read_target(effective_event, self.body, comparison)
            self._record_probe(
                evidence,
                probes,
                probe_keys,
                key="natural_file_target_read",
                label=self._NATURAL_FILE_PROBE_LABELS[2],
                notes=notes,
            )
            if isinstance(preview, dict):
                facts["file_previews"] = [preview]
                identity = target_read.get("identity")
                if isinstance(identity, dict):
                    facts["natural_file_identity"] = identity
        facts["natural_file_target_read"] = target_read

        failure = failure_reason(effective_event, facts)
        intent = edit_intent(effective_event, facts)

        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = failure
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)
        self._merge_investigation_into_thought(
            thought,
            InvestigationResult(state=investigation),
        )

        if intent is None:
            reason = failure or (
                "bounded workspace evidence did not establish one exact safe edit target"
            )
            if thought is not None:
                if reason not in thought.unknown:
                    thought.unknown = (*thought.unknown, reason)
                thought.reason = (
                    f"{thought.reason}; filesystem evidence is insufficient for a safe edit"
                )
                self._persist_enriched_thought(thought)
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        if self._action_blocked_by_current_evidence(event, state, intent):
            reason = (
                "the exact file edit remains blocked by unchanged failure evidence; "
                "ZN will not replay it"
            )
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = "perform body action: write_text"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            if browser_file_request is not None:
                thought.reason = (
                    f"{thought.reason}; two managed-browser sources established the replacement value, "
                    "then fresh bounded file evidence supported one exact overwrite"
                )
            else:
                thought.reason = (
                    f"{thought.reason}; fresh bounded file evidence supports one exact overwrite"
                )
            self._persist_enriched_thought(thought)
        return None

    # ------------------------------------------------------------------
    # Shared typed Desktop value task path.

    def _desktop_task_deliberation(
        self,
        event,
        state: WorkingState,
        goal: Mapping[str, Any],
        *,
        thought=None,
    ):
        submit_name = str(goal.get("submit_control_semantic_name") or "").strip()
        progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
        if submit_name and isinstance(progress, dict) and progress.get("typed_verified") is True:
            return self._desktop_submit_step(event, state, goal, progress, thought=thought)

        source, value, error, deferred = self._desktop_task_source(event, state, goal, thought=thought)
        if deferred:
            return None
        if error or source is None or value is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=str(error or "typed desktop task source evidence is unavailable"),
            )

        destination, notes = self._observe_desktop_destination(event, state, goal, source)
        self._record_desktop_destination(event, state, source, destination, notes)
        failure = str(destination.get("failure_reason") or "").strip()
        if failure:
            return self._checkpoint_terminal_failure(event, state, reason=failure)

        if destination.get("needs_focus") is True:
            intent = self._desktop_focus_intent(event, goal, destination)
            if intent is None:
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="fresh named desktop input evidence did not form one exact focus movement",
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
            return None

        if submit_name and destination.get("already_matches") is True:
            return self._mark_desktop_text_progress(
                event,
                state,
                goal=goal,
                source=source,
                destination=destination,
                input_sent=False,
            )

        intent = self._desktop_text_intent(event, source, destination)
        if intent is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="fresh source and desktop evidence did not form one exact text movement",
            )
        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact desktop text action remains blocked by unchanged failure evidence; "
                    "ZN will not replay it"
                ),
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        return None

    def _desktop_task_source(
        self,
        event,
        state: WorkingState,
        goal: Mapping[str, Any],
        *,
        thought=None,
    ) -> tuple[dict[str, Any] | None, str | None, str | None, bool]:
        requirement = goal.get("source_requirement")
        if not isinstance(requirement, Mapping):
            return None, None, "typed desktop task lost its source requirement", False
        kind = str(requirement.get("kind") or "").strip()
        if kind == "workspace_file":
            bound, notes = observe_text_source(event, self.body, requirement)
            if bound.get("complete") is not True:
                reason = str(bound.get("failure_reason") or "workspace source investigation failed")
                self._record_desktop_source(event, state, kind, bound, notes)
                return None, None, reason, False
            read, text, read_notes = read_text_source(event, self.body, bound)
            notes = [*notes, *read_notes]
            if read.get("complete") is not True or text is None:
                combined = {**dict(bound), **dict(read)}
                self._record_desktop_source(event, state, kind, combined, notes)
                return None, None, str(read.get("failure_reason") or "workspace source read failed"), False
            try:
                validated, units = KeyboardTextBody.validate_text(text)
            except ValueError as exc:
                reason = f"workspace source cannot be safely entered as bounded text: {exc}"
                self._record_desktop_source(event, state, kind, {**bound, **read, "complete": False, "failure_reason": reason}, [*notes, reason])
                return None, None, reason, False
            source = {
                **dict(bound),
                **dict(read),
                "kind": "workspace_file",
                "text_sha256": hashlib.sha256(validated.encode("utf-8")).hexdigest(),
                "text_chars": len(validated),
                "utf16_units": len(units),
                "complete": True,
                "failure_reason": None,
            }
            self._record_desktop_source(event, state, kind, source, notes)
            return source, validated, None, False

        if kind == "managed_browser_research":
            raw = state.data.get(self._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
            code, error = self._validated_desktop_research_value(raw)
            if code is not None and error is None and isinstance(raw, dict):
                source = {
                    "kind": kind,
                    "text_sha256": str(raw.get("release_code_sha256") or ""),
                    "text_chars": int(raw.get("release_code_chars") or 0),
                    "utf16_units": int(raw.get("release_code_utf16_units") or 0),
                    "source_count": len(raw.get("sources") or ()),
                    "complete": True,
                    "failure_reason": None,
                }
                return source, code, None, False

            research_error = self._perform_desktop_browser_research(event, state, thought=thought)
            if research_error:
                return None, None, research_error, False
            return None, None, None, True

        return None, None, "unsupported typed desktop task source kind", False

    def _perform_desktop_browser_research(
        self,
        event,
        state: WorkingState,
        *,
        thought=None,
    ) -> str | None:
        if self.user_browser_extension.authorized_tab() is None:
            return (
                "browser-to-desktop research requires one current USER browser tab explicitly "
                "authorized through the ZN browser bridge"
            )
        try:
            initial = self._discover_authorized_reference_context()
            references = self._rank_reference_candidates(initial.get("references"))
            if len(references) < 2:
                raise UserBrowserExtensionRelayError(
                    "the authorized page did not expose at least two bounded reference candidates"
                )
            research = self._research_managed_references(references)
            code, units = KeyboardTextBody.validate_text(str(research.get("release_code") or ""))
            sources = self._bounded_desktop_research_sources(research.get("sources"))
            distinct_sources = {
                str(item.get("source_url") or "").strip()
                for item in sources
                if str(item.get("source_url") or "").strip()
            }
            if len(distinct_sources) < 2:
                raise RuntimeError(
                    "managed reference investigation did not preserve two distinct agreeing sources"
                )
            fresh_tab = self.probe_user_browser_extension_tab()
            initial_tab_id = int(initial.get("tab_id") or 0)
            fresh_tab_id = int(fresh_tab.get("tab_id") or 0)
            initial_url = str(initial.get("url") or "").strip()
            fresh_url = str(fresh_tab.get("url") or "").strip()
            if (
                initial_tab_id <= 0
                or fresh_tab_id != initial_tab_id
                or not initial_url
                or fresh_url != initial_url
            ):
                raise UserBrowserExtensionRelayError(
                    "the explicitly authorized USER tab/page changed during managed reference research"
                )
        except Exception as exc:
            return (
                "ZN could not establish fresh two-source browser research for the desktop task: "
                f"{type(exc).__name__}: {exc}"
            )

        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        research_state = {
            "release_code": code,
            "release_code_sha256": digest,
            "release_code_chars": len(code),
            "release_code_utf16_units": len(units),
            "sources": sources,
            "authorized_tab_id": fresh_tab_id,
            "authorized_tab_url": fresh_url,
            "initial_observed_at": str(initial.get("observed_at") or ""),
            "fresh_observed_at": str(fresh_tab.get("observed_at") or fresh_tab.get("captured_at") or ""),
            "completed_at": utc_now(),
        }
        state.data[self._BROWSER_DESKTOP_RESEARCH_STATE_KEY] = research_state
        self._record_browser_research_evidence(event, state, research_state)
        state.data.pop("local_failure", None)
        state.stage = "native_deliberation"
        state.next_action = "freshly sense the current desktop target for the researched value"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            known = (
                "two distinct managed-browser sources agreed on one value and the same authorized "
                "USER tab/page was freshly re-observed afterward"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            self._persist_enriched_thought(thought)
        return None

    def _observe_desktop_destination(
        self,
        event,
        state: WorkingState,
        goal: Mapping[str, Any],
        source: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return self._desktop_destination_failure(
                "foreground desktop window is unavailable: " + str(error)
            )
        process_name = str(foreground.process_name or "").strip().lower()
        title = str(foreground.title or "").strip()
        if not process_name or process_name in _BROWSER_PROCESS_NAMES:
            return self._desktop_destination_failure(
                "this desktop value task requires a focused non-browser application"
            )
        if not title:
            return self._desktop_destination_failure(
                "the focused desktop window has no exact title for action authority"
            )

        binding = str(goal.get("target_input_binding") or "").strip()
        target_name = str(goal.get("target_input_semantic_name") or "").strip()
        named_target: NamedAutomationControlObservation | None = None
        automation = None
        if binding == "exact_name":
            if not target_name:
                return self._desktop_destination_failure(
                    "typed desktop task lost the semantic name of its target input"
                )
            try:
                named_target = self.named_automation_control.find_unique_edit(
                    process_id=int(foreground.process_id),
                    process_name=process_name,
                    name=target_name,
                )
            except Exception as exc:
                return self._desktop_destination_failure(
                    "ZN could not freshly bind one safe named desktop input: "
                    f"{type(exc).__name__}: {exc}"
                )
            focused, focused_error = self._probe_focused_automation_element()
            is_focused = bool(
                focused is not None
                and tuple(focused.runtime_id) == tuple(named_target.runtime_id)
                and int(focused.process_id) == int(named_target.process_id)
                and str(focused.process_name or "").strip().lower() == process_name
                and int(focused.control_type) == 50004
                and focused.is_enabled
                and focused.is_keyboard_focusable
                and focused.has_keyboard_focus
                and not focused.is_offscreen
                and not focused.is_password
            )
            self._record_named_input_observation(
                event,
                state,
                named_target,
                process_name=process_name,
                title=title,
                input_name=target_name,
                focused=is_focused,
                focused_error=None if focused is not None else focused_error,
            )
            if not is_focused:
                return {
                    "complete": True,
                    "needs_focus": True,
                    "process_id": int(foreground.process_id),
                    "process_name": process_name,
                    "pre_title": title,
                    "input_name": target_name,
                    "target_runtime_id": list(named_target.runtime_id),
                    "target_class_name": str(named_target.class_name or ""),
                    "target_center_x_fraction": float(named_target.center_x_fraction),
                    "target_center_y_fraction": float(named_target.center_y_fraction),
                    "failure_reason": None,
                }, [
                    f"fresh exact-name desktop Edit: process={process_name} name={target_name}",
                    "target is safe but not currently focused; focus must be verified before text entry",
                ]
            automation = focused
        elif binding == "focused_safe_edit":
            automation, error = self._probe_focused_automation_element()
            if automation is None:
                return self._desktop_destination_failure(
                    "focused UI Automation element is unavailable: " + str(error)
                )
        else:
            return self._desktop_destination_failure(
                "typed desktop task has an unsupported target input binding"
            )

        assert automation is not None
        if (
            int(automation.process_id) != int(foreground.process_id)
            or str(automation.process_name or "").strip().lower() != process_name
            or int(automation.control_type) != 50004
            or not automation.is_enabled
            or not automation.is_keyboard_focusable
            or not automation.has_keyboard_focus
            or automation.is_offscreen
            or automation.is_password
            or automation.value_is_read_only is True
        ):
            return self._desktop_destination_failure(
                "the current desktop target is not one safe writable UIA Edit"
            )

        scope = {
            "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
            "control_type": 50004,
            "class_name_equals": str(automation.class_name or "").strip(),
            "automation_id_equals": str(automation.automation_id or "").strip(),
        }
        target, target_error = self._probe_text_target(scope)
        if target is None:
            return self._desktop_destination_failure(
                "fresh focused desktop text state is unavailable: " + str(target_error)
            )
        if tuple(target["automation"].runtime_id) != tuple(automation.runtime_id):
            return self._desktop_destination_failure(
                "focused desktop RuntimeId changed during fresh destination sensing; re-sense before input"
            )

        text_state = target["text"]
        expected_digest = str(source.get("text_sha256") or "")
        expected_chars = int(source.get("text_chars") or -1)
        already_matches = bool(
            int(text_state.text_length) == expected_chars
            and str(text_state.text_sha256 or "") == expected_digest
        )
        if int(text_state.text_length) != 0 and not already_matches:
            return self._desktop_destination_failure(
                "the desktop Edit already contains different text; ZN will not delete or replace it implicitly"
            )
        action_precondition = {
            "kind": "foreground_window_matches",
            "process_name": process_name,
            "title_equals": title,
        }
        return {
            "complete": True,
            "needs_focus": False,
            "completion_scope": scope,
            "action_precondition": action_precondition,
            "target_runtime_id": list(target["automation"].runtime_id),
            "initial_text_length": int(text_state.text_length),
            "already_matches": already_matches,
            "failure_reason": None,
        }, [
            f"fresh focused desktop target: process={process_name} control_type=50004",
            f"privacy-safe initial text state: length={int(text_state.text_length)} already_matches={already_matches}",
        ]

    def _desktop_focus_intent(
        self,
        event,
        goal: Mapping[str, Any],
        destination: Mapping[str, Any],
    ) -> NativeActionIntent | None:
        runtime_id = destination.get("target_runtime_id")
        if not isinstance(runtime_id, list) or not runtime_id:
            return None
        input_name = str(goal.get("target_input_semantic_name") or "").strip()
        process_name = str(destination.get("process_name") or "").strip().lower()
        pre_title = str(destination.get("pre_title") or "").strip()
        if not input_name or not process_name or not pre_title:
            return None
        return NativeActionIntent(
            intent_id=f"desktop-input-focus-{event.event_id}-{self._opaque_runtime_suffix(runtime_id)}",
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(destination.get("target_center_x_fraction") or 0.0),
                "y_fraction": float(destination.get("target_center_y_fraction") or 0.0),
                "button": "left",
                "target_runtime_id": list(runtime_id),
                "target_name": input_name,
                "target_process_name": process_name,
            },
            expected_outcome={
                "kind": self._DESKTOP_FOCUS_OUTCOME_KIND,
                "process_name": process_name,
                "pre_title": pre_title,
                "input_name": input_name,
                "target_runtime_id": list(runtime_id),
                "target_center_x_fraction": float(destination.get("target_center_x_fraction") or 0.0),
                "target_center_y_fraction": float(destination.get("target_center_y_fraction") or 0.0),
                "target_class_name": str(destination.get("target_class_name") or ""),
            },
            reason=(
                "fresh exact-name UIA evidence bound one safe focusable non-password Edit in the "
                "current foreground application; reuse the existing non-replayable automation-focus "
                "pointer lifecycle before any text entry"
            ),
            source="resident_choice",
        )

    def _desktop_text_intent(
        self,
        event,
        source: Mapping[str, Any],
        destination: Mapping[str, Any],
    ) -> NativeActionIntent | None:
        completion_scope = destination.get("completion_scope")
        action_precondition = destination.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return None
        expected: dict[str, Any] = {
            "kind": self._DESKTOP_TEXT_OUTCOME_KIND,
            "source_kind": str(source.get("kind") or ""),
            "source_text_sha256": str(source.get("text_sha256") or ""),
            "source_text_chars": int(source.get("text_chars") or 0),
            "source_utf16_units": int(source.get("utf16_units") or 0),
            "completion_scope": dict(completion_scope),
            "action_precondition": dict(action_precondition),
        }
        if expected["source_kind"] == "workspace_file":
            identity = source.get("identity")
            if not isinstance(identity, Mapping):
                return None
            expected.update(
                {
                    "workspace_path": str(source.get("workspace_path") or ""),
                    "source_path": str(source.get("path") or ""),
                    "source_identity": dict(identity),
                }
            )
        return NativeActionIntent(
            intent_id=f"desktop-text-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="keyboard_text",
            args={},
            expected_outcome=expected,
            reason=(
                "fresh source evidence determines the value only, while a separate fresh desktop "
                "Sense determines the exact safe Edit and foreground authority for text input"
            ),
            source="resident_choice",
        )

    def _keyboard_text_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "keyboard_text"
            or str(expected.get("kind") or "").strip().lower() != self._DESKTOP_TEXT_OUTCOME_KIND
        ):
            return super()._keyboard_text_contract(event, intent)

        text, error = self._fresh_desktop_task_value(event, expected)
        if error or text is None:
            return None, error or "typed desktop task value is unavailable"
        completion_scope = expected.get("completion_scope")
        action_precondition = expected.get("action_precondition")
        if not isinstance(completion_scope, dict) or not isinstance(action_precondition, dict):
            return None, "desktop text intent lost its exact focused-target authority"
        synthetic_event = replace(
            event,
            kind=self._UI_EVENT_KIND,
            payload={
                "expected_outcome": {"kind": self._TEXT_OUTCOME_KIND},
                "completion_scope": dict(completion_scope),
                "action_precondition": dict(action_precondition),
                "model_policy": "never",
            },
        )
        transient_intent = NativeActionIntent(
            intent_id=intent.intent_id,
            event_id=intent.event_id,
            kind=intent.kind,
            args={"text": text},
            expected_outcome=intent.expected_outcome,
            reason=intent.reason,
            source=intent.source,
            created_at=intent.created_at,
        )
        return super()._keyboard_text_contract(synthetic_event, transient_intent)

    def _fresh_desktop_task_value(
        self,
        event,
        expected: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        source_kind = str(expected.get("source_kind") or "").strip()
        if source_kind == "workspace_file":
            source = {
                "workspace_path": str(expected.get("workspace_path") or ""),
                "path": str(expected.get("source_path") or ""),
                "identity": expected.get("source_identity"),
            }
            read, text, _ = read_text_source(event, self.body, source)
            if read.get("complete") is not True or text is None:
                return None, str(read.get("failure_reason") or "fresh workspace source read failed")
            try:
                validated, units = KeyboardTextBody.validate_text(text)
            except ValueError as exc:
                return None, f"workspace source is no longer safe bounded keyboard text: {exc}"
            digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()
            if (
                digest != str(expected.get("source_text_sha256") or "")
                or len(validated) != int(expected.get("source_text_chars") or -1)
                or len(units) != int(expected.get("source_utf16_units") or -1)
            ):
                return None, "workspace source content no longer matches the investigated digest"
            return validated, None

        if source_kind == "managed_browser_research":
            raw = self.store.get_working_state().data.get(self._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
            code, error = self._validated_desktop_research_value(raw)
            if error or code is None or not isinstance(raw, dict):
                return None, error or "managed browser research value is unavailable"
            if (
                str(expected.get("source_text_sha256") or "") != str(raw.get("release_code_sha256") or "")
                or int(expected.get("source_text_chars") or -1) != int(raw.get("release_code_chars") or -2)
                or int(expected.get("source_utf16_units") or -1) != int(raw.get("release_code_utf16_units") or -2)
            ):
                return None, "browser research value no longer matches the admitted desktop text intent"
            return code, None

        return None, "desktop text intent has an unsupported source kind"

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
        kind = str(expected.get("kind") or "").strip().lower()
        original = self.store.get_event(event.event_id) or event
        goal = desktop_task_request(original)

        if intent.kind == "pointer_click" and kind == self._DESKTOP_FOCUS_OUTCOME_KIND:
            synthetic = self._desktop_focus_event(original, expected)
            if synthetic is None:
                return self._checkpoint_terminal_failure(
                    original,
                    state,
                    reason="verified desktop input focus lost its exact structured scope",
                )
            return AutomationFocusPointerClickResidentRuntime._complete_successful_body_action(
                self,
                synthetic,
                state,
                intent,
                response=response,
                reason=reason,
            )

        if (
            isinstance(goal, Mapping)
            and str(goal.get("submit_control_semantic_name") or "").strip()
            and intent.kind == "keyboard_text"
            and kind == self._DESKTOP_TEXT_OUTCOME_KIND
        ):
            source = self._source_from_text_expected(expected)
            destination = self._destination_from_text_expected(expected)
            if source is None or destination is None:
                return self._checkpoint_terminal_failure(
                    original,
                    state,
                    reason="verified desktop text entry lost its exact source/destination authority",
                )
            return self._mark_desktop_text_progress(
                original,
                state,
                goal=goal,
                source=source,
                destination=destination,
                input_sent=True,
            )

        if intent.kind == "pointer_click" and kind == self._DESKTOP_CLICK_OUTCOME_KIND:
            return self._complete_desktop_submit_click(original, state, intent, expected)

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
            kind = str(expected.get("kind") or "").strip().lower()
            original = self.store.get_event(event.event_id) or event
            goal = desktop_task_request(original)

            if intent.kind == "pointer_click" and kind == self._DESKTOP_FOCUS_OUTCOME_KIND:
                state.data[self._NAMED_INPUT_STATE_KEY] = {
                    "verified": True,
                    "input_name": str(expected.get("input_name") or ""),
                    "process_name": str(expected.get("process_name") or "").strip().lower(),
                    "pre_title": str(expected.get("pre_title") or "").strip(),
                    "runtime_id": list(expected.get("target_runtime_id") or ()),
                    "verified_at": utc_now(),
                    "verification_response": str(response or "")[:500],
                }
                state.stage = "native_deliberation"
                state.next_action = "freshly verify the named Edit remains focused before text entry"
                state.data.pop("local_failure", None)
                self._sync_execution_context(original, state)
                self.store.save_working_state(state)
                return None

            if (
                isinstance(goal, Mapping)
                and str(goal.get("submit_control_semantic_name") or "").strip()
                and intent.kind == "keyboard_text"
                and kind == self._DESKTOP_TEXT_OUTCOME_KIND
            ):
                source = self._source_from_text_expected(expected)
                destination = self._destination_from_text_expected(expected)
                if source is None or destination is None:
                    return self._checkpoint_terminal_failure(
                        original,
                        state,
                        reason="already-matching desktop text lost exact source/destination authority",
                    )
                return self._mark_desktop_text_progress(
                    original,
                    state,
                    goal=goal,
                    source=source,
                    destination=destination,
                    input_sent=False,
                )

        return super()._complete_ui_scope(
            event,
            state,
            scope,
            response=response,
            reason=reason,
        )

    def _mark_desktop_text_progress(
        self,
        event,
        state: WorkingState,
        *,
        goal: Mapping[str, Any],
        source: Mapping[str, Any],
        destination: Mapping[str, Any],
        input_sent: bool,
    ):
        completion_scope = destination.get("completion_scope")
        action_precondition = destination.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="desktop text progress lost exact foreground process/title authority",
            )
        process_name = str(completion_scope.get("process_name") or "").strip().lower()
        pre_title = str(action_precondition.get("title_equals") or "").strip()
        button_name = str(goal.get("submit_control_semantic_name") or "").strip()
        final_state = goal.get("expected_final_state")
        if not process_name or not pre_title or not button_name or not isinstance(final_state, Mapping):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="desktop submit progress lost its typed application/button/result identity",
            )
        state.data[self._DESKTOP_SUBMIT_STATE_KEY] = {
            "typed_verified": True,
            "typed_at": utc_now(),
            "input_sent": bool(input_sent),
            "process_name": process_name,
            "pre_title": pre_title,
            "button_name": button_name,
            "expected_final_state": dict(final_state),
            "expected_title": str(final_state.get("title") or ""),
            "source_kind": str(source.get("kind") or ""),
            "source_text_sha256": str(source.get("text_sha256") or ""),
            "source_text_chars": int(source.get("text_chars") or 0),
        }
        state.stage = "native_investigation"
        state.next_action = "freshly locate the named Button in the current desktop application"
        state.data.pop("local_failure", None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _desktop_submit_step(
        self,
        event,
        state: WorkingState,
        goal: Mapping[str, Any],
        progress: Mapping[str, Any],
        *,
        thought=None,
    ):
        process_name = str(progress.get("process_name") or "").strip().lower()
        pre_title = str(progress.get("pre_title") or "").strip()
        button_name = str(progress.get("button_name") or goal.get("submit_control_semantic_name") or "").strip()
        final_state = progress.get("expected_final_state")
        if not isinstance(final_state, Mapping):
            final_state = goal.get("expected_final_state")
        if not process_name or not pre_title or not button_name or not isinstance(final_state, Mapping):
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
                reason="fresh desktop foreground state is unavailable before the submit step: " + str(error),
            )
        if self._desktop_final_state_satisfied(observed, process_name, pre_title, final_state):
            return self._complete_desktop_submit_from_foreground(
                event,
                state,
                process_name=process_name,
                observed=observed,
                final_state=final_state,
                reason=(
                    "the typed final desktop state was already freshly observed before another click "
                    "was necessary; ZN completed from reality instead of replaying input"
                ),
            )

        execution = state.data.get(self._POINTER_CLICK_EXECUTION_KEY)
        click_prefix = self._desktop_click_intent_prefix(event.event_id)
        if (
            isinstance(execution, dict)
            and str(execution.get("intent_id") or "").startswith(click_prefix)
            and str(execution.get("status") or "").strip().lower() in {"started", "completed"}
        ):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the desktop submit click may already have been delivered but the typed final "
                    "state is not proven; ZN will not replay the non-idempotent click"
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
        self._record_button_observation(
            event,
            state,
            button,
            process_name=process_name,
            pre_title=pre_title,
            final_state=final_state,
        )
        intent = NativeActionIntent(
            intent_id=self._desktop_click_intent_id(event.event_id, button),
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(button.center_x_fraction),
                "y_fraction": float(button.center_y_fraction),
                "button": "left",
                "target_runtime_id": list(button.runtime_id),
                "target_name": button_name,
                "target_process_name": process_name,
            },
            expected_outcome={
                "kind": self._DESKTOP_CLICK_OUTCOME_KIND,
                "process_name": process_name,
                "pre_title": pre_title,
                "button_name": button_name,
                "button_runtime_id": list(button.runtime_id),
                "button_center_x_fraction": float(button.center_x_fraction),
                "button_center_y_fraction": float(button.center_y_fraction),
                "expected_final_state": dict(final_state),
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
                reason="the exact desktop submit click remains blocked by unchanged failure evidence; ZN will not replay it",
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        return None

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        kind = str(expected.get("kind") or "").strip().lower()
        if intent.kind == "pointer_click" and kind == self._DESKTOP_FOCUS_OUTCOME_KIND:
            synthetic = self._desktop_focus_event(event, expected)
            if synthetic is None:
                return None, "desktop input focus intent lost its exact scope authority"
            return AutomationFocusPointerClickResidentRuntime._pointer_click_contract(
                self,
                synthetic,
                intent,
            )
        if intent.kind == "pointer_click" and kind == self._DESKTOP_CLICK_OUTCOME_KIND:
            synthetic = replace(
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
                synthetic,
                intent,
            )
        return super()._pointer_click_contract(event, intent)

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
            intent.kind == "pointer_click"
            and str(expected.get("kind") or "").strip().lower() == self._DESKTOP_FOCUS_OUTCOME_KIND
        ):
            synthetic = self._desktop_focus_event(event, expected)
            if synthetic is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "desktop input focus lost its exact synthetic event scope",
                    thought=thought,
                )
            return AutomationFocusPointerClickResidentRuntime._pointer_click_action_step(
                self,
                synthetic,
                state,
                intent,
                thought=thought,
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
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        kind = str(expected.get("kind") or "").strip().lower()
        if intent.kind == "pointer_click" and kind == self._DESKTOP_FOCUS_OUTCOME_KIND:
            process_name = str(expected.get("process_name") or "").strip().lower()
            pre_title = str(expected.get("pre_title") or "").strip()
            input_name = str(expected.get("input_name") or "").strip()
            expected_runtime = tuple(int(value) for value in (expected.get("target_runtime_id") or ()))
            if not process_name or not pre_title or not input_name or not expected_runtime:
                return "desktop input focus lost its exact pre-input authority"
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
                return f"exact named Edit could not be freshly revalidated before focus input: {type(exc).__name__}: {exc}"
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
            if (
                abs(float(fresh_target.center_x_fraction) - float(expected.get("target_center_x_fraction") or -1.0)) > 0.002
                or abs(float(fresh_target.center_y_fraction) - float(expected.get("target_center_y_fraction") or -1.0)) > 0.002
            ):
                return "exact named Edit moved materially before input; re-investigate the current focus point"
            synthetic = self._desktop_focus_event(event, expected)
            if synthetic is None:
                return "desktop input focus lost its exact synthetic action scope"
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
                return "the UI Automation element at the final pointer point is not the exact named Edit that granted focus authority"
            return None

        if intent.kind == "pointer_click" and kind == self._DESKTOP_CLICK_OUTCOME_KIND:
            process_name = str(expected.get("process_name") or "").strip().lower()
            pre_title = str(expected.get("pre_title") or "").strip()
            button_name = str(expected.get("button_name") or "").strip()
            expected_runtime = tuple(int(value) for value in (expected.get("button_runtime_id") or ()))
            final_state = expected.get("expected_final_state")
            if not process_name or not pre_title or not button_name or not expected_runtime or not isinstance(final_state, Mapping):
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
            self._record_button_observation(
                event,
                state,
                fresh_button,
                process_name=process_name,
                pre_title=pre_title,
                final_state=final_state,
            )
            if tuple(fresh_button.runtime_id) != expected_runtime:
                return "exact named Button RuntimeId changed before input; re-investigate the current target"
            if (
                abs(float(fresh_button.center_x_fraction) - float(expected.get("button_center_x_fraction") or -1.0)) > 0.002
                or abs(float(fresh_button.center_y_fraction) - float(expected.get("button_center_y_fraction") or -1.0)) > 0.002
            ):
                return "exact named Button moved materially before input; re-investigate the current click point"
            return None

        return super()._pointer_click_final_input_precondition(
            event,
            state,
            intent,
            contract,
            prepared,
        )

    def _desktop_focus_event(self, event, expected: Mapping[str, Any]):
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

    def _complete_desktop_submit_click(
        self,
        event,
        state,
        intent: NativeActionIntent,
        expected: Mapping[str, Any],
    ):
        process_name = str(expected.get("process_name") or "").strip().lower()
        pre_title = str(expected.get("pre_title") or "").strip()
        final_state = expected.get("expected_final_state")
        observed, error = self._probe_foreground_window()
        if (
            isinstance(final_state, Mapping)
            and observed is not None
            and self._desktop_final_state_satisfied(observed, process_name, pre_title, final_state)
        ):
            progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
            if isinstance(progress, dict):
                progress = dict(progress)
                progress["click_verified_at"] = utc_now()
                progress["final_foreground"] = asdict(observed)
                state.data[self._DESKTOP_SUBMIT_STATE_KEY] = progress
            return self._complete_desktop_submit_from_foreground(
                event,
                state,
                process_name=process_name,
                observed=observed,
                final_state=final_state,
                reason=(
                    "ZN completed the desktop task only after verified text state, one non-replayable "
                    "named-Button click, target-local visual change evidence, and a separate fresh "
                    "foreground observation satisfying the typed final state"
                ),
            )
        self._record_failed_action(
            event,
            state,
            intent,
            source="verification",
            failure=(
                "fresh foreground state did not prove the typed desktop result after the "
                "non-replayable click: " + str(error or self._foreground_summary(observed))
            ),
        )
        return self._checkpoint_terminal_failure(
            event,
            state,
            reason=(
                "the desktop submit click was sent but the requested final state was not independently "
                "proven; ZN will not replay the click"
            ),
        )

    def _complete_desktop_submit_from_foreground(
        self,
        event,
        state,
        *,
        process_name: str,
        observed,
        final_state: Mapping[str, Any],
        reason: str,
    ):
        observed_title = str(observed.title or "").strip()
        scope = {
            "kind": "foreground_window_matches",
            "process_name": process_name,
            "title_equals": observed_title,
        }
        state.data["natural_file_desktop_submit_final"] = {
            "verified": True,
            "typed_final_state": dict(final_state),
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
    def _desktop_final_state_satisfied(
        observed,
        process_name: str,
        pre_title: str,
        final_state: Mapping[str, Any],
    ) -> bool:
        if observed is None:
            return False
        if str(observed.process_name or "").strip().lower() != str(process_name or "").strip().lower():
            return False
        current_title = str(observed.title or "").strip()
        kind = str(final_state.get("kind") or "").strip()
        if kind == "foreground_title_equals":
            return bool(current_title and current_title == str(final_state.get("title") or "").strip())
        if kind == "foreground_title_changed":
            return bool(current_title and current_title != str(pre_title or "").strip())
        return False

    def _record_desktop_source(
        self,
        event,
        state: WorkingState,
        source_kind: str,
        source: Mapping[str, Any],
        notes: list[str],
    ) -> None:
        if source_kind != "workspace_file":
            return
        self._record_investigation_fact(
            event,
            state,
            key=self._FILE_DESKTOP_SOURCE_FACT_KEY,
            fact=dict(source),
            label=self._SOURCE_PROBE_LABEL,
            notes=notes,
            unresolved=str(source.get("failure_reason") or "").strip() or None,
        )

    def _record_desktop_destination(
        self,
        event,
        state: WorkingState,
        source: Mapping[str, Any],
        destination: Mapping[str, Any],
        notes: list[str],
    ) -> None:
        source_kind = str(source.get("kind") or "")
        key = (
            self._BROWSER_DESKTOP_DESTINATION_FACT_KEY
            if source_kind == "managed_browser_research"
            else self._FILE_DESKTOP_DESTINATION_FACT_KEY
        )
        label = (
            self._BROWSER_DESKTOP_PROBE_LABEL
            if source_kind == "managed_browser_research"
            else self._DESTINATION_PROBE_LABEL
        )
        self._record_investigation_fact(
            event,
            state,
            key=key,
            fact=dict(destination),
            label=label,
            notes=notes,
            unresolved=str(destination.get("failure_reason") or "").strip() or None,
        )

    def _record_browser_research_evidence(
        self,
        event,
        state: WorkingState,
        research: Mapping[str, Any],
    ) -> None:
        sources = research.get("sources") if isinstance(research.get("sources"), list) else []
        fact = {
            "complete": True,
            "release_code_sha256": str(research.get("release_code_sha256") or ""),
            "release_code_chars": int(research.get("release_code_chars") or 0),
            "source_count": len(sources),
            "sources": [
                {
                    "source_url": str(item.get("source_url") or ""),
                    "evidence_url": str(item.get("evidence_url") or ""),
                    "observed_at": str(item.get("observed_at") or ""),
                }
                for item in sources
                if isinstance(item, Mapping)
            ],
            "authorized_tab_id": int(research.get("authorized_tab_id") or 0),
            "authorized_tab_url": str(research.get("authorized_tab_url") or ""),
        }
        self._record_investigation_fact(
            event,
            state,
            key=self._BROWSER_DESKTOP_RESEARCH_FACT_KEY,
            fact=fact,
            label=self._BROWSER_RESEARCH_PROBE_LABEL,
            notes=[
                f"managed reference agreement: sources={len(sources)} value_chars={int(research.get('release_code_chars') or 0)}",
                "the exact authorized USER tab/page was freshly re-observed after isolated research",
            ],
            unresolved=None,
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
        self._record_investigation_fact(
            event,
            state,
            key=self._NAMED_INPUT_FACT_KEY,
            fact=fact,
            label=self._NAMED_INPUT_PROBE_LABEL,
            notes=[
                f"fresh exact-name desktop Edit: process={fact['process_name']} name={fact['input_name']}",
                f"safe structural target: control_type=50004 focused={fact['focused']} password={fact['password']} read_only={fact['value_is_read_only']}",
            ],
            unresolved=None,
        )

    def _record_button_observation(
        self,
        event,
        state: WorkingState,
        button: NamedAutomationControlObservation,
        *,
        process_name: str,
        pre_title: str,
        final_state: Mapping[str, Any],
    ) -> None:
        fact = {
            "process_name": str(process_name or "").strip().lower(),
            "pre_title": str(pre_title or "").strip(),
            "button_name": str(button.name or "").strip(),
            "runtime_id": list(button.runtime_id),
            "center_x_fraction": float(button.center_x_fraction),
            "center_y_fraction": float(button.center_y_fraction),
            "expected_final_state": dict(final_state),
            "source": str(button.source or ""),
            "observed_at": button.captured_at,
        }
        self._record_investigation_fact(
            event,
            state,
            key=self._BUTTON_FACT_KEY,
            fact=fact,
            label=self._BUTTON_PROBE_LABEL,
            notes=[
                f"fresh exact-name desktop Button: process={fact['process_name']} name={fact['button_name']}",
                "opaque target identity and bounded center were refreshed before click authority",
            ],
            unresolved=None,
        )

    def _record_investigation_fact(
        self,
        event,
        state: WorkingState,
        *,
        key: str,
        fact: Mapping[str, Any],
        label: str,
        notes: list[str],
        unresolved: str | None,
    ) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return
        facts = dict(investigation.facts)
        facts[key] = dict(fact)
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key=key,
            label=label,
            notes=notes,
        )
        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = unresolved
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)

    def _validated_desktop_research_value(self, raw: Any) -> tuple[str | None, str | None]:
        if not self._desktop_research_state_complete(raw):
            return None, "managed-reference browser research evidence is incomplete"
        assert isinstance(raw, dict)
        try:
            code, units = KeyboardTextBody.validate_text(str(raw.get("release_code") or ""))
        except ValueError as exc:
            return None, f"researched value is not safe bounded keyboard text: {exc}"
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if (
            digest != str(raw.get("release_code_sha256") or "")
            or len(code) != int(raw.get("release_code_chars") or -1)
            or len(units) != int(raw.get("release_code_utf16_units") or -1)
        ):
            return None, "durable managed-reference research value failed its digest/length check"
        return code, None

    @staticmethod
    def _desktop_research_state_complete(raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        sources = raw.get("sources")
        return bool(
            str(raw.get("release_code") or "")
            and str(raw.get("release_code_sha256") or "")
            and int(raw.get("release_code_chars") or 0) > 0
            and int(raw.get("release_code_utf16_units") or 0) > 0
            and isinstance(sources, list)
            and len(sources) >= 2
            and int(raw.get("authorized_tab_id") or 0) > 0
            and str(raw.get("authorized_tab_url") or "")
        )

    @staticmethod
    def _bounded_desktop_research_sources(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        bounded: list[dict[str, str]] = []
        for item in raw[:8]:
            if not isinstance(item, Mapping):
                continue
            source_url = str(item.get("source_url") or "").strip()
            evidence_url = str(item.get("evidence_url") or "").strip()
            observed_at = str(item.get("observed_at") or "").strip()
            if not source_url or not evidence_url:
                continue
            bounded.append(
                {
                    "source_url": source_url[:2048],
                    "evidence_url": evidence_url[:2048],
                    "observed_at": observed_at[:120],
                }
            )
        return bounded

    @staticmethod
    def _source_from_text_expected(expected: Mapping[str, Any]) -> dict[str, Any] | None:
        source_kind = str(expected.get("source_kind") or "").strip()
        digest = str(expected.get("source_text_sha256") or "").strip()
        chars = int(expected.get("source_text_chars") or 0)
        if not source_kind or not digest or chars <= 0:
            return None
        return {
            "kind": source_kind,
            "text_sha256": digest,
            "text_chars": chars,
            "utf16_units": int(expected.get("source_utf16_units") or 0),
        }

    @staticmethod
    def _destination_from_text_expected(expected: Mapping[str, Any]) -> dict[str, Any] | None:
        completion_scope = expected.get("completion_scope")
        action_precondition = expected.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return None
        return {
            "complete": True,
            "completion_scope": dict(completion_scope),
            "action_precondition": dict(action_precondition),
            "already_matches": True,
            "failure_reason": None,
        }

    @staticmethod
    def _desktop_destination_failure(reason: str) -> tuple[dict[str, Any], list[str]]:
        return {"complete": False, "failure_reason": reason}, [reason]

    @staticmethod
    def _foreground_equals(observed, process_name: str, title: str) -> bool:
        return bool(
            observed is not None
            and str(observed.process_name or "").strip().lower() == str(process_name or "").strip().lower()
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

    @staticmethod
    def _opaque_runtime_suffix(runtime_id: Any) -> str:
        raw = ",".join(str(value) for value in (runtime_id or ()))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _desktop_click_intent_prefix(event_id: str) -> str:
        return f"desktop-submit-click-{str(event_id or '').strip()}-"

    @classmethod
    def _desktop_click_intent_id(
        cls,
        event_id: str,
        button: NamedAutomationControlObservation,
    ) -> str:
        opaque_target = "|".join(
            (
                str(button.process_id),
                str(button.process_name or "").strip().lower(),
                str(button.name or "").strip(),
                ",".join(str(value) for value in button.runtime_id),
                f"{float(button.center_x_fraction):.6f}",
                f"{float(button.center_y_fraction):.6f}",
            )
        )
        suffix = hashlib.sha256(opaque_target.encode("utf-8")).hexdigest()[:12]
        return cls._desktop_click_intent_prefix(event_id) + suffix

    # ------------------------------------------------------------------
    # Existing browser->file edit path remains intact.

    def _prepare_browser_result_file_event(
        self,
        event,
        state: WorkingState,
        request: dict[str, str],
        *,
        thought=None,
    ):
        raw = state.data.get(self._BROWSER_FILE_RESEARCH_STATE_KEY)
        if isinstance(raw, dict) and str(raw.get("release_code") or "").strip():
            evidence = raw
        else:
            if self.user_browser_extension.authorized_tab() is None:
                return (
                    "browser+file work requires one current browser tab explicitly authorized "
                    "through the ZN browser bridge"
                )
            try:
                initial = self._discover_authorized_reference_context()
                references = self._rank_reference_candidates(initial.get("references"))
                if len(references) < 2:
                    raise RuntimeError(
                        "the authorized page did not expose at least two bounded reference candidates"
                    )
                research = self._research_managed_references(references)
                fresh_tab = self.probe_user_browser_extension_tab()
            except Exception as exc:
                return (
                    "ZN could not establish the browser evidence needed for the file edit: "
                    f"{type(exc).__name__}: {exc}"
                )
            release_code = str(research.get("release_code") or "").strip()
            sources = research.get("sources")
            if not release_code or not isinstance(sources, list) or len(sources) < 2:
                return "managed browser research did not establish two-source agreement on one release code"
            evidence = {
                "release_code": release_code,
                "sources": sources,
                "initial_authorized_page": {
                    "url": str(initial.get("url") or ""),
                    "title": str(initial.get("title") or ""),
                    "observed_at": str(initial.get("observed_at") or ""),
                },
                "fresh_authorized_page": {
                    "url": str(fresh_tab.get("url") or ""),
                    "title": str(fresh_tab.get("title") or ""),
                    "observed_at": str(fresh_tab.get("observed_at") or ""),
                },
            }
            state.data[self._BROWSER_FILE_RESEARCH_STATE_KEY] = evidence
            state.data.pop("local_failure", None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            if thought is not None:
                known = (
                    "two independently observed managed-browser sources agreed on one release code "
                    "before ZN touched the workspace file"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                thought.reason = (
                    f"{thought.reason}; browser investigation produced evidence only, not mutation authority"
                )
                self._persist_enriched_thought(thought)

        release_code = str(evidence.get("release_code") or "").strip()
        if not release_code:
            return "durable browser research evidence no longer contains a usable release code"
        synthetic_task = (
            f"找到这里昨天改过、名字像{request['name_hint']}的那个 txt，"
            f"把{request['old_text']}改成{release_code}，保存后再读回来确认"
        )
        return replace(event, task=synthetic_task)

    def _prepare_overwrite_prestate(
        self,
        event,
        state,
        intent,
        *,
        thought=None,
    ) -> bool:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        investigation_identity = expected.get("precondition_file_identity")
        if isinstance(investigation_identity, dict):
            raw = state.data.get(self._OVERWRITE_PRESTATE_KEY)
            same_intent = bool(
                isinstance(raw, dict)
                and str(raw.get("intent_id") or "") == intent.intent_id
                and str(raw.get("action_signature") or "") == self._intent_signature(intent)
            )
            if not same_intent:
                state.data[self._OVERWRITE_PRESTATE_KEY] = {
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                    "identity": dict(investigation_identity),
                }
                state.data.pop(self._OVERWRITE_PRESTATE_RECHECK_KEY, None)
        return super()._prepare_overwrite_prestate(
            event,
            state,
            intent,
            thought=thought,
        )

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        result = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if result is not None:
            return result

        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_intent, dict):
            return None
        expected = raw_intent.get("expected_outcome")
        if not isinstance(expected, dict) or not isinstance(
            expected.get("precondition_file_identity"),
            dict,
        ):
            return None
        if state.stage != "native_investigation":
            return None
        failure = str(state.data.get("local_failure") or "").strip()
        if "identity no longer matches" not in failure:
            return None
        return self._checkpoint_terminal_failure(event, state, reason=failure)

    @staticmethod
    def _record_probe(
        evidence: list[str],
        probes: list[str],
        probe_keys: list[str],
        *,
        key: str,
        label: str,
        notes: list[str],
    ) -> None:
        if label not in probes:
            probes.append(label)
        probe_keys.append(key)
        for note in notes:
            text = str(note or "").strip()
            if text and text not in evidence:
                evidence.append(text)

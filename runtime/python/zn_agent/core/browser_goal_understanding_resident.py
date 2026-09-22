from __future__ import annotations

"""Let cognition propose typed Resident goals while Resident keeps authority and truth.

This existing understanding layer remains intentionally thin. A bounded model
call may propose semantic desired-state data for an ordinary browser or
workspace-to-desktop request. The proposal is not an action and is never
current-world evidence: ``ResidentGoalRuntime`` still senses the real file,
foreground application, UI Automation target, side-effect state and completion
from fresh evidence.
"""

import hashlib
import json
from typing import Any

from .browser_named_goal import browser_named_text_request
from .composite_work_routing import composite_work_preempts_browser_understanding
from .desktop_task_goal import (
    DESKTOP_TASK_GOAL_KIND,
    DesktopTaskGoal,
    desktop_task_goal,
    desktop_task_goal_payload,
)
from .goal_resident import ResidentGoalRuntime
from .natural_file_goal import natural_workspace_text_edit_request


_BROWSER_TASK_CUES = (
    "browser",
    "chrome",
    "edge",
    "site",
    "网页",
    "网站",
    "浏览器",
    "当前页面",
    "这个页面",
)
_UNDERSTANDING_KEY = "_resident_goal_understanding"
_BROWSER_SEMANTIC_GOAL_KEY = "_resident_user_browser_semantic_goal"
_BROWSER_SEMANTIC_LOOKUP_KIND = "user_browser_semantic_lookup"
_DESKTOP_SEMANTIC_GOAL_KEY = "_resident_desktop_semantic_goal"
_DESKTOP_SEMANTIC_REGROUND_KEY = "resident_desktop_semantic_reground"
_MAX_DESKTOP_SEMANTIC_REGROUNDS = 3
_MAX_DESKTOP_LANGUAGE_CHARS = 1600
_YESTERDAY_CUES = ("昨天", "昨日", "yesterday")
_BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
}


def _looks_like_foreground_browser_task(event) -> bool:
    if str(event.kind or "").strip().lower() != "desktop_user_event":
        return False
    payload = event.payload or {}
    if payload.get("body_action") or payload.get("native_action"):
        return False
    task = str(event.task or "").strip()
    lowered = task.lower()
    return bool(task) and any(cue in lowered or cue in task for cue in _BROWSER_TASK_CUES)


def _looks_like_workspace_desktop_goal_candidate(event) -> bool:
    """Broad structural entrance; no task phrase decides whether ZN can understand it."""

    if str(event.kind or "").strip().lower() != "desktop_user_event":
        return False
    payload = event.payload or {}
    if (
        not str(payload.get("workspace_path") or "").strip()
        or payload.get("body_action")
        or payload.get("native_action")
        or payload.get("desktop_task_goal")
    ):
        return False
    if natural_workspace_text_edit_request(event) is not None:
        return False
    task = " ".join(str(event.task or "").strip().split())
    return bool(task) and len(task) <= _MAX_DESKTOP_LANGUAGE_CHARS


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _validated_browser_goal_proposal(task: str, model_text: str) -> dict[str, str] | None:
    """Accept only a typed proposal whose target and mutation text come from the user."""

    value = _extract_json_object(model_text)
    if value is None:
        return None
    if set(value).difference({"kind", "target_name", "text"}):
        return None
    if str(value.get("kind") or "").strip().lower() != "user_browser_named_text":
        return None

    target_name = str(value.get("target_name") or "").strip()
    text = value.get("text")
    if not isinstance(text, str):
        return None
    if not target_name or len(target_name) > 256 or len(text) > 4096:
        return None

    source = str(task or "")
    if target_name not in source or text not in source:
        return None
    return {
        "kind": "user_browser_named_text",
        "target_name": target_name,
        "text": text,
    }


def _validated_browser_semantic_goal_proposal(
    task: str,
    model_text: str,
) -> dict[str, str] | None:
    """Accept desired browser semantics without accepting any world identity."""

    value = _extract_json_object(model_text)
    if value is None:
        return None
    allowed = {
        "kind",
        "subject_value",
        "subject_semantics",
        "operation",
        "desired_result",
    }
    if set(value).difference(allowed):
        return None
    if str(value.get("kind") or "").strip().lower() != _BROWSER_SEMANTIC_LOOKUP_KIND:
        return None

    subject_value = str(value.get("subject_value") or "").strip()
    subject_semantics = " ".join(str(value.get("subject_semantics") or "").strip().split())
    operation = " ".join(str(value.get("operation") or "").strip().split())
    desired_result = " ".join(str(value.get("desired_result") or "").strip().split())
    if (
        not subject_value
        or not subject_semantics
        or not operation
        or not desired_result
        or len(subject_value) > 512
        or len(subject_semantics) > 160
        or len(operation) > 240
        or len(desired_result) > 240
    ):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in subject_value):
        return None
    if subject_value not in str(task or ""):
        return None
    return {
        "kind": _BROWSER_SEMANTIC_LOOKUP_KIND,
        "subject_value": subject_value,
        "subject_semantics": subject_semantics,
        "operation": operation,
        "desired_result": desired_result,
    }


def browser_semantic_lookup_goal(event) -> dict[str, str] | None:
    payload = event.payload or {}
    raw = payload.get(_BROWSER_SEMANTIC_GOAL_KEY)
    if not isinstance(raw, dict):
        return None
    if str(raw.get("kind") or "").strip().lower() != _BROWSER_SEMANTIC_LOOKUP_KIND:
        return None
    normalized = {
        "kind": _BROWSER_SEMANTIC_LOOKUP_KIND,
        "subject_value": str(raw.get("subject_value") or "").strip(),
        "subject_semantics": " ".join(str(raw.get("subject_semantics") or "").strip().split()),
        "operation": " ".join(str(raw.get("operation") or "").strip().split()),
        "desired_result": " ".join(str(raw.get("desired_result") or "").strip().split()),
    }
    if not all(normalized[key] for key in ("subject_value", "subject_semantics", "operation", "desired_result")):
        return None
    return normalized


def _validated_desktop_goal_proposal(task: str, model_text: str) -> dict[str, Any] | None:
    """Accept semantic goal data only; reject any model attempt to mint authority."""

    value = _extract_json_object(model_text)
    if value is None:
        return None
    allowed = {
        "kind",
        "source_name_hint",
        "input_name",
        "button_name",
        "expected_title",
        "source_modified_yesterday",
    }
    if set(value).difference(allowed):
        return None
    if str(value.get("kind") or "").strip().lower() != DESKTOP_TASK_GOAL_KIND:
        return None

    source_name_hint = " ".join(str(value.get("source_name_hint") or "").strip().split())
    input_name = " ".join(str(value.get("input_name") or "").strip().split())
    button_name = " ".join(str(value.get("button_name") or "").strip().split())
    raw_title = value.get("expected_title")
    if raw_title is not None and not isinstance(raw_title, str):
        return None
    expected_title = " ".join(str(raw_title or "").strip().split()) or None
    modified_yesterday = value.get("source_modified_yesterday", False)
    if not isinstance(modified_yesterday, bool):
        return None
    if (
        not source_name_hint
        or not input_name
        or not button_name
        or len(source_name_hint) > 64
        or len(input_name) > 160
        or len(button_name) > 160
        or (expected_title is not None and len(expected_title) > 160)
    ):
        return None

    task_text = " ".join(str(task or "").strip().split())
    if source_name_hint.casefold() not in task_text.casefold():
        return None
    if expected_title and expected_title.casefold() not in task_text.casefold():
        return None
    if modified_yesterday and not any(
        cue in task_text.casefold() if cue.isascii() else cue in task_text
        for cue in _YESTERDAY_CUES
    ):
        return None

    return desktop_task_goal_payload(
        DesktopTaskGoal(
            workspace_path="",
            source_name_hint=source_name_hint,
            input_name=input_name,
            button_name=button_name,
            expected_title=expected_title,
            source_modified_yesterday=modified_yesterday,
        )
    )


def _validated_desktop_grounding_selection(
    model_text: str,
    *,
    edit_names: tuple[str, ...],
    button_names: tuple[str, ...],
) -> tuple[str, str] | None:
    """Accept only two uniquely observed accessible names, never model-minted identity."""

    value = _extract_json_object(model_text)
    if value is None or set(value).difference({"status", "input_name", "button_name"}):
        return None
    if str(value.get("status") or "").strip().lower() != "selected":
        return None
    input_name = " ".join(str(value.get("input_name") or "").strip().split())
    button_name = " ".join(str(value.get("button_name") or "").strip().split())
    if not input_name or not button_name:
        return None
    if edit_names.count(input_name) != 1 or button_names.count(button_name) != 1:
        return None
    return input_name, button_name


def _desktop_semantic_goal(event) -> dict[str, Any] | None:
    raw = (event.payload or {}).get(_DESKTOP_SEMANTIC_GOAL_KEY)
    if not isinstance(raw, dict):
        return None
    return _validated_desktop_goal_proposal(
        str(event.task or ""),
        json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )


class BrowserGoalUnderstandingResidentRuntime(ResidentGoalRuntime):
    """Use a model only to propose desired state; keep execution resident-owned."""

    def _orient_step(self, event, state, *, readiness, thought=None):
        if (
            browser_named_text_request(event) is not None
            or browser_semantic_lookup_goal(event) is not None
            or desktop_task_goal(event) is not None
        ):
            return super()._orient_step(event, state, readiness=readiness, thought=thought)

        # A durable browser+workspace Work request is a more specific route than
        # the generic foreground-browser language proposal. Keep routing
        # descriptive here: ResidentGoalRuntime still owns truth, authority and
        # all later execution/verification.
        if composite_work_preempts_browser_understanding(event):
            return super()._orient_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        if _looks_like_foreground_browser_task(event):
            proposed = self._orient_browser_goal_from_cognition(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
            if proposed is not False:
                return proposed

        if _looks_like_workspace_desktop_goal_candidate(event):
            proposed = self._orient_desktop_goal_from_cognition(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
            if proposed is not False:
                return proposed

        return super()._orient_step(event, state, readiness=readiness, thought=thought)

    def _orient_browser_goal_from_cognition(self, event, state, *, readiness, thought=None):
        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the foreground-browser task needs language understanding and model use "
                    "is disabled; no browser input was sent"
                ),
            )

        cognition_goal_id = f"goal-browser-understanding-{event.event_id}"
        question = (
            "Interpret only the user's desired outcome in the current browser. Return exactly "
            "one JSON object and no prose. If the user explicitly names a browser text field "
            "and asks to put literal text into it, return "
            '{"kind":"user_browser_named_text","target_name":"EXACT USER PHRASE",'
            '"text":"EXACT USER TEXT"}. If instead the user gives a business subject or '
            "identifier and asks ZN to find information or a record without naming the page "
            "controls, return "
            '{"kind":"user_browser_semantic_lookup","subject_value":"EXACT USER VALUE",'
            '"subject_semantics":"WHAT THE VALUE IDENTIFIES",'
            '"operation":"USER DESIRED LOOKUP OPERATION",'
            '"desired_result":"WHAT FACT THE USER WANTS VERIFIED"}. '
            "subject_value must be copied exactly from the user task. The semantic strings are "
            "intent descriptions only, never claims that a control or result currently exists. "
            "Otherwise return {\"kind\":\"not_applicable\"}. Never return URLs, tab ids, "
            "coordinates, selectors, DOM/backend ids, browser identity, action sequences, "
            "passwords, cookies, credentials, authority, side-effect state, or completion. "
            f"User task: {event.task}"
        )
        result = self.kernel.run_goal(
            question,
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "browser_goal_proposal_only",
            },
            max_attempts_override=1,
            goal_id=cognition_goal_id,
        )
        invocations = self._model_invocations(result)
        raw = (
            _extract_json_object(result.worker_result.response)
            if result.worker_result.success and result.assessment.success
            else None
        )
        raw_kind = str((raw or {}).get("kind") or "").strip().lower()
        if raw_kind == "not_applicable":
            return False

        proposal: dict[str, Any] | None = None
        goal_kind = raw_kind
        if raw_kind == "user_browser_named_text":
            proposal = _validated_browser_goal_proposal(
                event.task,
                result.worker_result.response,
            )
        elif raw_kind == _BROWSER_SEMANTIC_LOOKUP_KIND:
            proposal = _validated_browser_semantic_goal_proposal(
                event.task,
                result.worker_result.response,
            )
        if proposal is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "bounded cognition did not produce a permitted user-grounded browser semantic "
                    "goal; no browser input was sent"
                ),
            )

        event.payload = dict(event.payload or {})
        if goal_kind == "user_browser_named_text":
            event.payload["resident_goal"] = dict(proposal)
            next_action = "observe current browser reality for the proposed typed goal"
            known = (
                "bounded cognition proposed only a typed desired browser world-state; "
                "fresh Sense still owns target facts and action eligibility"
            )
        else:
            event.payload[_BROWSER_SEMANTIC_GOAL_KEY] = dict(proposal)
            next_action = (
                "freshly sense bounded safe candidates in the exact authorized browser tab and "
                "ground the semantic lookup before any movement"
            )
            known = (
                "bounded cognition proposed only business semantics and a literal user value; "
                "it supplied no control identity, browser authority, action sequence or result fact"
            )
        self._persist_understanding(
            event,
            state,
            cognition_goal_id=cognition_goal_id,
            invocations=invocations,
            route_id=str(result.goal.route_id or ""),
            goal_kind=goal_kind,
            next_action=next_action,
            thought=thought,
            known=known,
        )
        return None

    def _desktop_task_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        """Keep semantic desktop intent when exact accessible names drift at runtime."""

        goal = desktop_task_goal(event)
        semantic_goal = _desktop_semantic_goal(event)
        progress = state.data.get(self._DESKTOP_TASK_PROGRESS_KEY)
        if (
            goal is None
            or semantic_goal is None
            or (isinstance(progress, dict) and progress.get("submit_dispatched") is True)
        ):
            return super()._desktop_task_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        foreground, _foreground_error = self._probe_foreground_window()
        if foreground is None:
            return super()._desktop_task_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        process_name = str(foreground.process_name or "").strip().lower()
        if not process_name or process_name in _BROWSER_PROCESSES:
            return super()._desktop_task_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        exact_failure = None
        try:
            self.named_automation_control.find_unique_edit(
                process_id=int(foreground.process_id),
                process_name=process_name,
                name=goal.input_name,
            )
            self.named_automation_control.find_unique_button(
                process_id=int(foreground.process_id),
                process_name=process_name,
                name=goal.button_name,
            )
        except Exception as exc:
            exact_failure = f"{type(exc).__name__}: {exc}"

        if exact_failure is None:
            return super()._desktop_task_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        return self._reground_desktop_semantic_goal(
            event,
            state,
            readiness=readiness,
            thought=thought,
            semantic_goal=semantic_goal,
            exact_failure=exact_failure,
        )

    def _reground_desktop_semantic_goal(
        self,
        event,
        state,
        *,
        readiness,
        thought,
        semantic_goal: dict[str, Any],
        exact_failure: str,
    ):
        current_goal = desktop_task_goal(event)
        if current_goal is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason="desktop semantic re-ground lost the current typed goal",
            )
        raw_reground = state.data.get(_DESKTOP_SEMANTIC_REGROUND_KEY)
        reground = dict(raw_reground) if isinstance(raw_reground, dict) else {}
        count = max(0, int(reground.get("count") or 0))
        if count >= _MAX_DESKTOP_SEMANTIC_REGROUNDS:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "desktop semantic re-ground exceeded its bounded retry limit after current "
                    "accessible names kept drifting; no further desktop input was attempted"
                ),
            )

        foreground, foreground_error = self._probe_foreground_window()
        if foreground is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "fresh desktop semantic re-ground could not observe the foreground window: "
                    + str(foreground_error or "unavailable")
                ),
            )
        process_name = str(foreground.process_name or "").strip().lower()
        if not process_name or process_name in _BROWSER_PROCESSES:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason="desktop semantic re-ground requires the current non-browser application",
            )

        try:
            edits = self.named_automation_control.list_safe_edits(
                process_id=int(foreground.process_id),
                process_name=process_name,
            )
            buttons = self.named_automation_control.list_buttons(
                process_id=int(foreground.process_id),
                process_name=process_name,
            )
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "fresh desktop candidate Sense for semantic re-ground failed closed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        edit_names = tuple(item.name for item in edits)
        button_names = tuple(item.name for item in buttons)
        if not edit_names or not button_names:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "fresh desktop semantic re-ground did not expose both safe Edit and Button "
                    "candidates; no desktop input was attempted"
                ),
            )

        grounding_question = (
            "The exact accessible names selected earlier are no longer current. Keep the same "
            "semantic user goal and choose only among the freshly observed accessible names "
            "below. Return exactly "
            '{"status":"selected","input_name":"ONE OBSERVED EDIT NAME",'
            '"button_name":"ONE OBSERVED BUTTON NAME"} only when there is one clearly best '
            "choice for each. If either choice is ambiguous, return "
            '{"status":"ambiguous"}. Never return an index, RuntimeId, process/window identity, '
            "coordinates, selectors, authority, actions, or completion. "
            f"User task: {event.task}\n"
            f"Semantic destination: {semantic_goal['input_name']}\n"
            f"Semantic operation: {semantic_goal['button_name']}\n"
            f"Fresh Edit names: {json.dumps(edit_names, ensure_ascii=False)}\n"
            f"Fresh Button names: {json.dumps(button_names, ensure_ascii=False)}"
        )
        question_digest = hashlib.sha256(grounding_question.encode("utf-8")).hexdigest()
        grounding_goal_id = (
            f"goal-desktop-reground-{event.event_id}-{question_digest[:16]}"
        )
        grounding = self.kernel.run_goal(
            grounding_question,
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "desktop_fresh_candidate_reground_only",
                "fresh_candidate_digest": question_digest,
            },
            max_attempts_override=1,
            goal_id=grounding_goal_id,
        )
        invocations = self._model_invocations(grounding)
        selection = None
        if grounding.worker_result.success and grounding.assessment.success:
            selection = _validated_desktop_grounding_selection(
                grounding.worker_result.response,
                edit_names=edit_names,
                button_names=button_names,
            )
        if selection is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "fresh desktop semantic re-ground was ambiguous or did not select one "
                    "uniquely observed safe Edit and Button; no desktop input was attempted"
                ),
            )

        input_name, button_name = selection
        grounded = dict(semantic_goal)
        grounded["input_name"] = input_name
        grounded["button_name"] = button_name
        event.payload = dict(event.payload or {})
        event.payload["desktop_task_goal"] = grounded

        understanding = event.payload.get(_UNDERSTANDING_KEY)
        if isinstance(understanding, dict):
            understanding = dict(understanding)
            try:
                prior_invocations = max(0, int(understanding.get("model_invocations") or 0))
            except (TypeError, ValueError):
                prior_invocations = 0
            understanding["model_invocations"] = prior_invocations + invocations
            event.payload[_UNDERSTANDING_KEY] = understanding
            state.data[_UNDERSTANDING_KEY] = dict(understanding)

        history = reground.get("history")
        history = list(history) if isinstance(history, list) else []
        history.append(
            {
                "from_input_name": current_goal.input_name,
                "to_input_name": input_name,
                "from_button_name": current_goal.button_name,
                "to_button_name": button_name,
                "fresh_candidate_digest": question_digest,
                "grounding_goal_id": grounding_goal_id,
                "exact_revalidation_failure": str(exact_failure),
            }
        )
        state.data[_DESKTOP_SEMANTIC_REGROUND_KEY] = {
            "count": count + 1,
            "history": history[-_MAX_DESKTOP_SEMANTIC_REGROUNDS:],
        }
        state.data.pop(self._DESKTOP_TASK_OBSERVATION_KEY, None)
        state.data.pop("local_failure", None)
        self.store._save_event(event)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

        if thought is not None:
            known = (
                "fresh UIA candidate Sense showed that the previously grounded accessible "
                "names were stale while the semantic desktop goal remained unchanged"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; bounded semantic re-ground selected only current safe names "
                "and Resident will bind exact UIA identity again before any movement"
            )
            self._persist_enriched_thought(thought)

        return ResidentGoalRuntime._desktop_task_investigation(
            self,
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _orient_desktop_goal_from_cognition(self, event, state, *, readiness, thought=None):
        """Understand desired state, then ground it only in freshly sensed safe candidates."""

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            return False

        cognition_goal_id = f"goal-desktop-understanding-{event.event_id}"
        question = (
            "Interpret only the user's desired workspace-to-current-desktop outcome. "
            "Return exactly one JSON object and no prose. If the user wants a value from "
            "one attached workspace text file used in the current non-browser desktop "
            "application to find or submit a result, return "
            '{"kind":"workspace_to_foreground_desktop",'
            '"source_name_hint":"SHORT PHRASE COPIED FROM THE USER TASK",'
            '"input_name":"SEMANTIC DESCRIPTION OF THE DESTINATION FIELD",'
            '"button_name":"SEMANTIC DESCRIPTION OF THE FIND/SUBMIT OPERATION",'
            '"expected_title":null,"source_modified_yesterday":false}. '
            "Set source_modified_yesterday=true only when the user explicitly says yesterday. "
            "Set expected_title only when the user explicitly supplies that exact visible title; "
            "otherwise use null. input_name and button_name are semantic descriptions, not "
            "claims about controls that exist. Otherwise return {\"kind\":\"not_applicable\"}. "
            "Never return file paths, process/window identity, UIA RuntimeIds, automation ids, "
            "coordinates, selectors, text-field contents, credentials, authority, action "
            "sequences, side-effect state, or completion claims. "
            f"User task: {event.task}"
        )
        result = self.kernel.run_goal(
            question,
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "desktop_goal_proposal_only",
            },
            max_attempts_override=1,
            goal_id=cognition_goal_id,
        )
        invocations = self._model_invocations(result)
        raw = (
            _extract_json_object(result.worker_result.response)
            if result.worker_result.success and result.assessment.success
            else None
        )
        raw_kind = str((raw or {}).get("kind") or "").strip().lower()
        if raw_kind != DESKTOP_TASK_GOAL_KIND:
            return False

        proposal = _validated_desktop_goal_proposal(
            event.task,
            result.worker_result.response,
        )
        if proposal is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "bounded cognition proposed a desktop goal outside the permitted semantic "
                    "schema; no file, keyboard or pointer side effect was attempted"
                ),
            )

        foreground, foreground_error = self._probe_foreground_window()
        if foreground is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "fresh desktop grounding could not observe the current foreground window: "
                    + str(foreground_error or "unavailable")
                ),
            )
        process_name = str(foreground.process_name or "").strip().lower()
        if not process_name or process_name in _BROWSER_PROCESSES:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="fresh desktop grounding requires the current non-browser application",
            )

        try:
            edits = self.named_automation_control.list_safe_edits(
                process_id=int(foreground.process_id),
                process_name=process_name,
            )
            buttons = self.named_automation_control.list_buttons(
                process_id=int(foreground.process_id),
                process_name=process_name,
            )
        except Exception as exc:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "fresh desktop candidate Sense failed closed before any input: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        edit_names = tuple(item.name for item in edits)
        button_names = tuple(item.name for item in buttons)
        if not edit_names or not button_names:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "fresh desktop candidate Sense did not expose both a safe Edit candidate "
                    "and a Button candidate; no desktop input was attempted"
                ),
            )

        grounding_goal_id = f"goal-desktop-grounding-{event.event_id}"
        grounding_question = (
            "Choose only among the freshly observed accessible names below. Match the semantic "
            "destination field and operation to the user's goal. Return exactly "
            '{"status":"selected","input_name":"ONE OBSERVED EDIT NAME",'
            '"button_name":"ONE OBSERVED BUTTON NAME"} only when there is one clearly best '
            "choice for each. If either choice is ambiguous, return "
            '{"status":"ambiguous"}. Never return an index, RuntimeId, process/window identity, '
            "coordinates, selectors, authority, actions, or completion. "
            f"User task: {event.task}\n"
            f"Semantic destination: {proposal['input_name']}\n"
            f"Semantic operation: {proposal['button_name']}\n"
            f"Fresh Edit names: {json.dumps(edit_names, ensure_ascii=False)}\n"
            f"Fresh Button names: {json.dumps(button_names, ensure_ascii=False)}"
        )
        grounding = self.kernel.run_goal(
            grounding_question,
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "desktop_fresh_candidate_grounding_only",
            },
            max_attempts_override=1,
            goal_id=grounding_goal_id,
        )
        invocations += self._model_invocations(grounding)
        selection = None
        if grounding.worker_result.success and grounding.assessment.success:
            selection = _validated_desktop_grounding_selection(
                grounding.worker_result.response,
                edit_names=edit_names,
                button_names=button_names,
            )
        if selection is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "fresh desktop semantic grounding was ambiguous or did not select one "
                    "uniquely observed safe Edit and Button; no desktop input was attempted"
                ),
            )

        input_name, button_name = selection
        grounded = dict(proposal)
        grounded["input_name"] = input_name
        grounded["button_name"] = button_name
        event.payload = dict(event.payload or {})
        event.payload[_DESKTOP_SEMANTIC_GOAL_KEY] = dict(proposal)
        event.payload["desktop_task_goal"] = grounded
        self._persist_understanding(
            event,
            state,
            cognition_goal_id=cognition_goal_id,
            invocations=invocations,
            route_id=str(result.goal.route_id or ""),
            goal_kind=DESKTOP_TASK_GOAL_KIND,
            next_action=(
                "freshly bind the selected accessible names to exact current UIA targets and "
                "continue one bounded movement"
            ),
            thought=thought,
            known=(
                "bounded cognition proposed semantic goal data and then selected only names "
                "from Resident fresh safe candidate Sense; Resident still owns exact UIA "
                "identity, action authority, side-effect state and completion"
            ),
        )
        return None

    def _persist_understanding(
        self,
        event,
        state,
        *,
        cognition_goal_id: str,
        invocations: int,
        route_id: str,
        goal_kind: str,
        next_action: str,
        thought,
        known: str,
    ) -> None:
        event.payload[_UNDERSTANDING_KEY] = {
            "source": "bounded_cognition_proposal",
            "goal_id": cognition_goal_id,
            "goal_kind": goal_kind,
            "model_invocations": invocations,
            "route_id": route_id,
        }
        self.store._save_event(event)
        state.data[_UNDERSTANDING_KEY] = dict(event.payload[_UNDERSTANDING_KEY])
        state.stage = "native_investigation"
        state.next_action = next_action
        self.store.save_working_state(state)
        if thought is not None:
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; external cognition supplied a proposal, not authority "
                "or completion evidence"
            )
            self._persist_enriched_thought(thought)

    @staticmethod
    def _model_invocations(result) -> int:
        return sum(
            1
            for experience in result.experiences
            if experience.metrics.get("model_invoked", True) is not False
        )

    def _complete_result(self, event, result):
        """Keep final EventOutcome truthful about proposal-only model usage."""

        metadata = (event.payload or {}).get(_UNDERSTANDING_KEY)
        if isinstance(metadata, dict):
            try:
                prior = max(0, int(metadata.get("model_invocations") or 0))
            except (TypeError, ValueError):
                prior = 0
            if prior:
                result.model_invocations = max(0, int(result.model_invocations)) + prior
        return super()._complete_result(event, result)
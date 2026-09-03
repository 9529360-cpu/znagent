from __future__ import annotations

"""Let cognition propose typed Resident goals while Resident keeps authority and truth.

This existing understanding layer remains intentionally thin. A bounded model
call may propose semantic desired-state data for an ordinary browser or
workspace-to-desktop request. The proposal is not an action and is never
current-world evidence: ``ResidentGoalRuntime`` still senses the real file,
foreground application, UI Automation target, side-effect state and completion
from fresh evidence.
"""

import json
from typing import Any

from .browser_named_goal import browser_named_text_request
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
    "网页",
    "浏览器",
    "当前页面",
    "这个页面",
)
_UNDERSTANDING_KEY = "_resident_goal_understanding"
_MAX_DESKTOP_LANGUAGE_CHARS = 1600
_YESTERDAY_CUES = ("昨天", "昨日", "yesterday")


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

    # The model may generalize semantic control descriptions, but it may not
    # invent the workspace-selection premise or a completion title. Those values
    # directly narrow real-world evidence, so keep them user-grounded.
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


class BrowserGoalUnderstandingResidentRuntime(ResidentGoalRuntime):
    """Use a model only to propose desired state; keep execution resident-owned."""

    def _orient_step(self, event, state, *, readiness, thought=None):
        # Internal typed callers and the explicit deterministic desktop fast path
        # keep their existing zero-model route.
        if browser_named_text_request(event) is not None or desktop_task_goal(event) is not None:
            return super()._orient_step(event, state, readiness=readiness, thought=thought)

        if _looks_like_foreground_browser_task(event):
            return self._orient_browser_goal_from_cognition(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

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
            "Extract only the user's requested foreground-browser text-field goal. "
            "Return exactly one JSON object and no prose. If the task asks to put or type "
            "literal text into a named browser field, return "
            '{"kind":"user_browser_named_text","target_name":"EXACT USER PHRASE",'
            '"text":"EXACT USER TEXT"}. Otherwise return {"kind":"not_applicable"}. '
            "Never invent or normalize target_name or text. Never return coordinates, "
            "selectors, browser identity, actions, passwords, authority, or completion. "
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
        proposal = None
        if result.worker_result.success and result.assessment.success:
            proposal = _validated_browser_goal_proposal(
                event.task,
                result.worker_result.response,
            )
        if proposal is None:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "bounded cognition did not produce a strictly user-grounded browser goal "
                    "proposal; no browser input was sent"
                ),
            )

        event.payload = dict(event.payload or {})
        event.payload["resident_goal"] = dict(proposal)
        self._persist_understanding(
            event,
            state,
            cognition_goal_id=cognition_goal_id,
            invocations=invocations,
            route_id=str(result.goal.route_id or ""),
            goal_kind="user_browser_named_text",
            next_action="observe current browser reality for the proposed typed goal",
            thought=thought,
            known=(
                "bounded cognition proposed only a typed desired browser world-state; "
                "fresh Sense still owns target facts and action eligibility"
            ),
        )
        return None

    def _orient_desktop_goal_from_cognition(self, event, state, *, readiness, thought=None):
        """Return False only when this broad workspace task should keep normal routing."""

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            # A workspace may belong to another deterministic resident path. The
            # generic desktop proposal is a fallback, so lack of a model must not
            # steal or terminate those existing zero-model tasks.
            return False

        cognition_goal_id = f"goal-desktop-understanding-{event.event_id}"
        question = (
            "Interpret only the user's desired workspace-to-current-desktop outcome. "
            "Return exactly one JSON object and no prose. If the user wants a value from "
            "one attached workspace text file used in the current non-browser desktop "
            "application to find or submit a result, return "
            '{"kind":"workspace_to_foreground_desktop",'
            '"source_name_hint":"SHORT PHRASE COPIED FROM THE USER TASK",'
            '"input_name":"SEMANTIC ACCESSIBLE NAME FOR THE INPUT",'
            '"button_name":"SEMANTIC ACCESSIBLE NAME FOR THE SUBMIT/SEARCH BUTTON",'
            '"expected_title":null,"source_modified_yesterday":false}. '
            "Set source_modified_yesterday=true only when the user explicitly says yesterday. "
            "Set expected_title only when the user explicitly supplies that exact visible title; "
            "otherwise use null. input_name and button_name are semantic target descriptions "
            "only; Resident will freshly bind and validate the real controls. Otherwise return "
            '{"kind":"not_applicable"}. Never return file paths, process/window identity, '
            "UIA RuntimeIds, automation ids, coordinates, selectors, text-field contents, "
            "credentials, authority, action sequences, side-effect state, or completion claims. "
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
            # not_applicable or unrelated output leaves the ordinary Resident
            # routing untouched instead of turning the broad workspace entrance
            # into a hidden task classifier.
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

        event.payload = dict(event.payload or {})
        event.payload["desktop_task_goal"] = dict(proposal)
        self._persist_understanding(
            event,
            state,
            cognition_goal_id=cognition_goal_id,
            invocations=invocations,
            route_id=str(result.goal.route_id or ""),
            goal_kind=DESKTOP_TASK_GOAL_KIND,
            next_action="freshly ground the proposed desktop goal in workspace and UI evidence",
            thought=thought,
            known=(
                "bounded cognition proposed only semantic workspace-to-desktop goal data; "
                "fresh Resident Sense still owns file identity, app/control identity, "
                "side-effect authority and completion"
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
        # Persist resident-owned semantic enrichment before any Body action. A
        # restart can reuse the proposal but must still re-sense current reality.
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

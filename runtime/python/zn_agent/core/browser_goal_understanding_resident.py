from __future__ import annotations

"""Let cognition propose typed browser goals while Resident keeps authority and truth.

A bounded model call may propose semantic desired-state data for an ordinary
foreground-browser request. The proposal is not an action and is never
current-world evidence: ``ResidentGoalRuntime`` and the USER Browser layers
still own fresh target sensing, authorization, side-effect state and completion.
"""

import json
from typing import Any

from .browser_named_goal import browser_named_text_request
from .goal_resident import ResidentGoalRuntime


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

def _looks_like_foreground_browser_task(event) -> bool:
    if str(event.kind or "").strip().lower() != "desktop_user_event":
        return False
    payload = event.payload or {}
    if payload.get("body_action") or payload.get("native_action"):
        return False
    task = str(event.task or "").strip()
    lowered = task.lower()
    return bool(task) and any(cue in lowered or cue in task for cue in _BROWSER_TASK_CUES)


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


class BrowserGoalUnderstandingResidentRuntime(ResidentGoalRuntime):
    """Use a model only to propose desired state; keep execution resident-owned."""

    def _orient_step(self, event, state, *, readiness, thought=None):
        if (
            browser_named_text_request(event) is not None
            or browser_semantic_lookup_goal(event) is not None
        ):
            return super()._orient_step(event, state, readiness=readiness, thought=thought)

        if _looks_like_foreground_browser_task(event):
            proposed = self._orient_browser_goal_from_cognition(
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
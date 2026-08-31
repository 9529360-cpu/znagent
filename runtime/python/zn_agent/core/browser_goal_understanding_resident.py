from __future__ import annotations

"""Let cognition propose a browser goal while Resident keeps authority and truth.

This layer is intentionally thin. For ordinary foreground-browser text tasks, one
bounded cognitive-resource call may propose a typed resident goal. The proposal
is not an action and is never completion evidence: ResidentGoalRuntime must still
obtain fresh browser facts, reject unsafe/password/read-only targets, form each
Body movement, verify its postcondition, re-sense, and independently prove the
final world state.
"""

import json
from typing import Any

from .browser_named_goal import browser_named_text_request
from .goal_resident import ResidentGoalRuntime


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


class BrowserGoalUnderstandingResidentRuntime(ResidentGoalRuntime):
    """Use a model only to propose desired state; keep execution resident-owned."""

    def _orient_step(self, event, state, *, readiness, thought=None):
        # Internal typed callers keep the existing zero-model path.
        if browser_named_text_request(event) is not None:
            return super()._orient_step(event, state, readiness=readiness, thought=thought)
        if not _looks_like_foreground_browser_task(event):
            return super()._orient_step(event, state, readiness=readiness, thought=thought)

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
        invocations = sum(
            1
            for experience in result.experiences
            if experience.metrics.get("model_invoked", True) is not False
        )
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
        event.payload[_UNDERSTANDING_KEY] = {
            "source": "bounded_cognition_proposal",
            "goal_id": cognition_goal_id,
            "model_invocations": invocations,
            "route_id": str(result.goal.route_id or ""),
        }
        # Persist the resident-owned enrichment before any browser action so a
        # restart never has to repeat an already-observed provider call.
        self.store._save_event(event)

        state.data[_UNDERSTANDING_KEY] = dict(event.payload[_UNDERSTANDING_KEY])
        state.stage = "native_investigation"
        state.next_action = "observe current browser reality for the proposed typed goal"
        self.store.save_working_state(state)
        if thought is not None:
            known = (
                "bounded cognition proposed only a typed desired browser world-state; "
                "fresh Sense still owns target facts and action eligibility"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; external cognition supplied a proposal, not authority "
                "or completion evidence"
            )
            self._persist_enriched_thought(thought)
        return None

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

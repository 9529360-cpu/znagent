from __future__ import annotations

"""Borrow the mature agent pattern: cognition proposes, Resident decides and acts.

This layer exists only for ordinary foreground-browser text tasks that the local
zero-model fast path cannot already understand. One bounded cognitive-resource
call may propose a typed resident goal. The proposal is not action authority and
is never completion evidence: the existing ResidentGoalRuntime must still obtain
fresh browser facts, reject unsafe/password/read-only targets, form each Body
movement, verify its postcondition and independently prove the final world state.
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
    """Accept one small JSON object, tolerating a fenced model response only."""

    raw = str(text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
            if raw.lower().startswith("json\n"):
                raw = raw[5:].strip()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _validated_browser_goal_proposal(task: str, model_text: str) -> dict[str, str] | None:
    """Validate cognition output as a proposal, never as input authority.

    The text that would be typed must occur verbatim in the user's own task.
    The target phrase must also be grounded in the task. This deliberately gives
    the model less authority than a normal agent tool call: it may identify the
    user's spans and relation, but it may not invent mutation content or a target
    name that the user never supplied.
    """

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
    """Let bounded cognition form a typed browser goal without owning its truth."""

    def _orient_step(self, event, state, *, readiness, thought=None):
        # Typed goals and the deliberately narrow zero-model language fast path
        # keep their existing behavior and never spend a model call.
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
                    "the foreground-browser task was not unambiguously understood by the "
                    "resident's local fast path and model use is disabled; no input was sent"
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
        if result.worker_result.success:
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

        # The resident adopts only the desired typed world-state. Existing browser
        # Sense must still discover and validate the real target before any action.
        event.payload = dict(event.payload or {})
        event.payload["resident_goal"] = dict(proposal)
        event.payload[_UNDERSTANDING_KEY] = {
            "source": "bounded_cognition_proposal",
            "goal_id": cognition_goal_id,
            "model_invocations": invocations,
            "route_id": str(result.goal.route_id or ""),
        }
        # KernelStore intentionally keeps event persistence compact. This is a
        # resident-owned enrichment of the already-claimed event, not user input.
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

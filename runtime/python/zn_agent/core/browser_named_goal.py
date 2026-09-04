from __future__ import annotations

"""Typed world-state semantics for one foreground user-browser text goal."""

from typing import Any, Mapping

from .action import NativeActionIntent
from .automation_text_state_sense import NativeFocusedAutomationTextSense
from .browser_named_target_sense import BrowserNamedTargetObservation
from .focused_text_sense import NativeFocusedTextSense
from .models import AgentEvent

_KIND = "user_browser_named_text"


def browser_named_text_request(event: AgentEvent) -> dict[str, Any] | None:
    payload = event.payload or {}
    raw_goal = payload.get("resident_goal")
    if isinstance(raw_goal, str):
        kind = raw_goal.strip().lower()
        values: Mapping[str, Any] = payload
    elif isinstance(raw_goal, Mapping):
        kind = str(raw_goal.get("kind") or "").strip().lower()
        values = {**payload, **dict(raw_goal)}
    else:
        return None
    if kind != _KIND:
        return None
    target_name = str(values.get("target_name") or values.get("accessible_name") or "").strip()
    if not target_name or len(target_name) > 256:
        return None
    if "text" not in values:
        return None
    text = str(values.get("text") or "")
    return {
        "kind": _KIND,
        "target_name": target_name,
        "text": text,
        "expected_text_sha256": NativeFocusedTextSense.digest_text(text),
        "expected_text_chars": len(text),
    }


def browser_named_text_state(
    event: AgentEvent,
    target: BrowserNamedTargetObservation,
    text_observation: Any | None,
) -> dict[str, Any] | None:
    request = browser_named_text_request(event)
    if request is None:
        return None

    same_runtime = bool(
        text_observation is not None
        and tuple(getattr(text_observation, "runtime_id", ())) == tuple(target.runtime_id)
        and str(getattr(text_observation, "process_name", "")).strip().lower()
        == target.process_name.lower()
    )
    text_verified = bool(
        same_runtime
        and int(getattr(text_observation, "text_length", -1))
        == int(request["expected_text_chars"])
        and str(getattr(text_observation, "text_sha256", "")).strip().lower()
        == str(request["expected_text_sha256"]).lower()
    )
    empty = bool(same_runtime and int(getattr(text_observation, "text_length", -1)) == 0)

    if not target.has_keyboard_focus:
        phase = "needs_focus"
        blocked = None
    elif text_verified:
        phase = "satisfied"
        blocked = None
    elif not same_runtime:
        phase = "blocked"
        blocked = "fresh focused text evidence does not identify the exact named browser target"
    elif empty:
        phase = "needs_text"
        blocked = None
    else:
        phase = "blocked"
        blocked = (
            "the exact named browser Edit is non-empty and differs from the requested text; "
            "bounded replacement authority has not been granted"
        )

    return {
        **request,
        "phase": phase,
        "blocked": blocked,
        "satisfied": phase == "satisfied",
        "target_runtime_id": list(target.runtime_id),
        "process_name": target.process_name,
        "foreground_title": target.foreground_title,
        "control_type": target.control_type,
        "class_name": target.class_name,
        "automation_id": target.automation_id,
        "center_x_fraction": target.center_x_fraction,
        "center_y_fraction": target.center_y_fraction,
        "target_focused": target.has_keyboard_focus,
        "text_observed": same_runtime,
        "text_verified": text_verified,
    }


def browser_named_text_intent(
    event: AgentEvent,
    state: Mapping[str, Any],
) -> NativeActionIntent | None:
    phase = str(state.get("phase") or "")
    if phase == "needs_focus":
        return NativeActionIntent(
            intent_id=f"browser-goal-{event.event_id}-focus",
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(state["center_x_fraction"]),
                "y_fraction": float(state["center_y_fraction"]),
                "button": "left",
            },
            expected_outcome={
                "kind": "browser_named_target_focused",
                "process_name": str(state["process_name"]),
                "title_equals": str(state["foreground_title"]),
                "control_type": int(state["control_type"]),
                "class_name_equals": str(state["class_name"]),
                "target_runtime_id": list(state["target_runtime_id"]),
            },
            reason=(
                "fresh exact-name UI Automation evidence found one unique safe Edit in the "
                "current foreground user browser, but it does not yet have keyboard focus"
            ),
            source="native_deliberation",
        )
    if phase == "needs_text":
        return NativeActionIntent(
            intent_id=f"browser-goal-{event.event_id}-text",
            event_id=event.event_id,
            kind="keyboard_text",
            args={"text": str(state["text"])},
            expected_outcome={
                "kind": "browser_named_text_equals",
                "process_name": str(state["process_name"]),
                "title_equals": str(state["foreground_title"]),
                "control_type": int(state["control_type"]),
                "class_name_equals": str(state["class_name"]),
                "automation_id_equals": str(state.get("automation_id") or ""),
                "target_runtime_id": list(state["target_runtime_id"]),
                "expected_text_sha256": str(state["expected_text_sha256"]),
                "expected_text_chars": int(state["expected_text_chars"]),
            },
            reason=(
                "fresh target and focused text evidence identify the same unique empty safe "
                "foreground-browser Edit, so one bounded Unicode input can advance the goal"
            ),
            source="native_deliberation",
        )
    return None


def focused_text_matches_request(event: AgentEvent, observation: Any) -> bool:
    request = browser_named_text_request(event)
    if request is None:
        return False
    return bool(
        int(getattr(observation, "text_length", -1)) == int(request["expected_text_chars"])
        and str(getattr(observation, "text_sha256", "")).strip().lower()
        == str(request["expected_text_sha256"]).lower()
    )

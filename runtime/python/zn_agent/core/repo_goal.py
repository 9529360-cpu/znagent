from __future__ import annotations

"""Typed resident goal semantics for one bounded multi-step repository outcome.

This module describes a desired world state, not an action sequence. Current
Investigation facts decide whether the resident needs a text movement, a Git
staging movement, no movement, or more evidence. Stored procedural memory and
model output never supply the target path, content, repository root, or command.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .action import NativeActionIntent
from .git_semantics import current_git_path_staged_goal, git_stage_command
from .models import AgentEvent
from .path_context import canonical_host_path, resolve_context_path

_REPO_TEXT_STAGED = "repo_text_staged"


def repo_text_staged_request(event: AgentEvent) -> dict[str, Any] | None:
    """Return the current typed composite goal without granting action authority."""

    payload = event.payload or {}
    raw_goal = payload.get("resident_goal")
    if isinstance(raw_goal, str):
        kind = raw_goal.strip().lower()
    elif isinstance(raw_goal, Mapping):
        kind = str(raw_goal.get("kind") or "").strip().lower()
    else:
        return None
    if kind != _REPO_TEXT_STAGED:
        return None
    if bool(payload.get("append", False)):
        return None

    raw_path = payload.get("path") or payload.get("file") or payload.get("target")
    if raw_path is None or not str(raw_path).strip():
        return None
    if "content" not in payload and "text" not in payload:
        return None

    try:
        path = resolve_context_path(str(raw_path), payload)
    except (OSError, RuntimeError, ValueError):
        return None
    if path.is_absolute():
        try:
            path = canonical_host_path(path)
        except (OSError, RuntimeError, ValueError):
            return None

    return {
        "kind": _REPO_TEXT_STAGED,
        "path": str(path),
        "expected_text": str(payload.get("content", payload.get("text", ""))),
        "create_parents": bool(payload.get("create_parents", True)),
    }


def repo_text_staged_state(
    event: AgentEvent,
    facts: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Evaluate the composite goal only from current typed goal + observed facts."""

    request = repo_text_staged_request(event)
    if request is None:
        return None
    current = facts if isinstance(facts, Mapping) else {}
    path_fact = _matching_path_fact(current, request["path"])
    preview = _matching_file_preview(current, request["path"])

    path_compatible = not (
        isinstance(path_fact, Mapping)
        and bool(path_fact.get("exists"))
        and str(path_fact.get("type") or "").strip().lower() != "file"
    )
    text_observed = bool(
        isinstance(preview, Mapping)
        and not bool(preview.get("truncated"))
    )
    text_satisfied = bool(
        text_observed
        and str(preview.get("preview") or "") == request["expected_text"]
    )

    staging_event = replace(
        event,
        payload={
            **dict(event.payload or {}),
            "expected_outcome": {
                "kind": "git_path_staged",
                "path": request["path"],
            },
        },
    )
    git_goal = current_git_path_staged_goal(staging_event, facts=current)
    git_observed = isinstance(current.get("git"), Mapping)
    git_satisfied = bool(git_goal and git_goal.get("satisfied"))
    git_stageable = bool(git_goal and git_goal.get("stageable"))

    if not path_compatible:
        actionable = False
        blocked = "target path is not a regular file"
    elif not text_satisfied:
        actionable = True
        blocked = None
    elif git_stageable:
        actionable = True
        blocked = None
    elif git_satisfied:
        actionable = False
        blocked = None
    else:
        actionable = False
        blocked = "current repository evidence does not yet prove a safe staging movement"

    return {
        **request,
        "path_observed": isinstance(path_fact, Mapping),
        "path_exists": bool(path_fact and path_fact.get("exists")),
        "path_compatible": path_compatible,
        "text_observed": text_observed,
        "text_satisfied": text_satisfied,
        "git_observed": git_observed,
        "git_goal": dict(git_goal) if isinstance(git_goal, Mapping) else None,
        "git_stageable": git_stageable,
        "git_satisfied": git_satisfied,
        "actionable": actionable,
        "satisfied": bool(text_satisfied and git_satisfied),
        "blocked": blocked,
    }


def repo_text_staged_action_intents(
    event: AgentEvent,
    facts: Mapping[str, Any] | None,
) -> tuple[NativeActionIntent, ...]:
    """Form the next bounded movement from current reality, never from a stored plan."""

    state = repo_text_staged_state(event, facts)
    if state is None or not state["path_compatible"] or state["satisfied"]:
        return ()

    if not state["text_satisfied"]:
        return (
            NativeActionIntent(
                intent_id=f"goal-{event.event_id}-text",
                event_id=event.event_id,
                kind="write_text",
                args={
                    "path": state["path"],
                    "content": state["expected_text"],
                    "append": False,
                    "create_parents": state["create_parents"],
                },
                expected_outcome={
                    "kind": "text_equals",
                    "path": state["path"],
                    "expected_text": state["expected_text"],
                },
                reason=(
                    "current Investigation evidence shows the repository target has not "
                    "reached the typed exact-text goal"
                ),
                source="native_deliberation",
            ),
        )

    git_goal = state.get("git_goal")
    if not isinstance(git_goal, Mapping) or not state["git_stageable"]:
        return ()

    choices: list[NativeActionIntent] = []
    for variant in ("git_add", "git_update_index"):
        command = git_stage_command(variant, str(git_goal.get("relative_path") or ""))
        if not command:
            return ()
        choices.append(
            NativeActionIntent(
                intent_id=f"goal-{event.event_id}-stage-{variant}",
                event_id=event.event_id,
                kind="command",
                args={
                    "command": command,
                    "workdir": str(git_goal.get("root") or ""),
                },
                expected_outcome={
                    "kind": "git_path_staged",
                    "root": str(git_goal.get("root") or ""),
                    "path": str(git_goal.get("path") or ""),
                    "relative_path": str(git_goal.get("relative_path") or ""),
                    "action_variant": variant,
                },
                reason=(
                    "current Investigation proves the exact text goal and a non-conflicted "
                    "single-path Git staging goal; this bounded mechanism can satisfy it"
                ),
                source="resident_choice",
            )
        )
    return tuple(choices)


def _matching_path_fact(
    facts: Mapping[str, Any],
    target: str,
) -> Mapping[str, Any] | None:
    expected = _path_key(target)
    raw = facts.get("paths")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, Mapping) and _path_key(item.get("path")) == expected:
            return item
    return None


def _matching_file_preview(
    facts: Mapping[str, Any],
    target: str,
) -> Mapping[str, Any] | None:
    expected = _path_key(target)
    raw = facts.get("file_previews")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, Mapping) and _path_key(item.get("path")) == expected:
            return item
    return None


def _path_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        path = Path(text).expanduser()
        return str(canonical_host_path(path) if path.is_absolute() else path)
    except (OSError, RuntimeError, ValueError):
        return text

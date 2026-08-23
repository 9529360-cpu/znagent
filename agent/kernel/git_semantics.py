from __future__ import annotations

"""Current-world semantics for one bounded Git staging goal.

This module does not execute Git and does not infer a mutation from free text.
It only normalizes a typed current-event goal against independently observed
Investigation facts.  The first contract is intentionally narrow: one existing
regular file inside the observed repository root may be staged when the current
Git state proves that the file has unstaged or untracked content and is not in
conflict.
"""

import os
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .models import AgentEvent

_GIT_STAGE_KIND = "git_path_staged"
_GIT_STAGE_VARIANTS = frozenset({"git_add", "git_update_index"})


def git_stage_variants() -> frozenset[str]:
    return _GIT_STAGE_VARIANTS


def git_stage_command(variant: str, relative_path: str) -> str | None:
    """Render the exact bounded command owned by one current staging variant."""

    normalized_variant = str(variant or "").strip().lower()
    rel = normalized_git_path(relative_path)
    if normalized_variant not in _GIT_STAGE_VARIANTS or not rel:
        return None
    quoted = shlex.quote(rel)
    if normalized_variant == "git_add":
        return f"git add -- {quoted}"
    return f"git update-index --add -- {quoted}"


def normalized_git_path(value: Any) -> str:
    """Normalize a repository-relative path for structured Git-state comparison."""

    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def git_path_stage_state(
    git_fact: Mapping[str, Any] | None,
    relative_path: str,
) -> dict[str, bool] | None:
    """Classify the observed index/worktree state for one repository path."""

    if not isinstance(git_fact, Mapping) or git_fact.get("available") is False:
        return None
    rel = normalized_git_path(relative_path)
    if not rel:
        return None

    def paths(key: str) -> set[str]:
        raw = git_fact.get(key)
        if not isinstance(raw, list):
            return set()
        return {
            normalized_git_path(item)
            for item in raw
            if normalized_git_path(item)
        }

    staged = rel in paths("staged_paths")
    unstaged = rel in paths("unstaged_paths")
    untracked = rel in paths("untracked_paths")
    conflicted = rel in paths("conflicted_paths")
    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicted": conflicted,
        "stageable": (unstaged or untracked) and not conflicted,
        "satisfied": staged and not unstaged and not untracked and not conflicted,
    }


def current_git_path_staged_goal(
    event: AgentEvent,
    *,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a normalized staging goal only when current evidence makes it safe.

    Authority comes from an explicit typed current-event postcondition plus
    current Investigation facts.  The function deliberately performs a few
    additional host-path checks only to *reduce* authority: symlinked/ambiguous
    paths are rejected rather than followed into a mutation.
    """

    payload = event.payload or {}
    raw_goal = payload.get("expected_outcome")
    if not isinstance(raw_goal, Mapping):
        return None
    if str(raw_goal.get("kind") or "").strip().lower() != _GIT_STAGE_KIND:
        return None

    raw_path = raw_goal.get("path")
    if raw_path is None or not str(raw_path).strip():
        return None

    current = facts if isinstance(facts, Mapping) else {}
    git_fact = current.get("git")
    if not isinstance(git_fact, Mapping) or git_fact.get("available") is False:
        return None
    root_text = str(git_fact.get("root") or "").strip()
    if not root_text:
        return None

    identity = _resolved_git_path_identity(root_text, raw_path)
    if identity is None:
        return None
    root, resolved, rel = identity

    path_fact = _matching_path_fact(current, resolved)
    if path_fact is None:
        return None
    if not bool(path_fact.get("exists")):
        return None
    if str(path_fact.get("type") or "").strip().lower() != "file":
        return None

    state = git_path_stage_state(git_fact, rel)
    if state is None or state["conflicted"]:
        return None

    return {
        "kind": _GIT_STAGE_KIND,
        "root": str(root),
        "path": str(resolved),
        "relative_path": rel,
        **state,
    }


def current_git_goal_from_intent(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalize and revalidate a transient goal carried by current working state."""

    if not isinstance(raw, Mapping):
        return None
    if str(raw.get("kind") or "").strip().lower() != _GIT_STAGE_KIND:
        return None
    root = str(raw.get("root") or "").strip()
    path = str(raw.get("path") or "").strip()
    rel = normalized_git_path(raw.get("relative_path"))
    variant = str(raw.get("action_variant") or "").strip().lower()
    if not root or not path or not rel or variant not in _GIT_STAGE_VARIANTS:
        return None

    identity = _resolved_git_path_identity(root, path)
    if identity is None:
        return None
    resolved_root, resolved_path, resolved_rel = identity
    if resolved_rel != rel:
        return None
    return {
        "kind": _GIT_STAGE_KIND,
        "root": str(resolved_root),
        "path": str(resolved_path),
        "relative_path": resolved_rel,
        "action_variant": variant,
    }


def _resolved_git_path_identity(
    root_value: Any,
    path_value: Any,
) -> tuple[Path, Path, str] | None:
    """Prove root, host path and repository-relative path name one regular location."""

    root_text = str(root_value or "").strip()
    path_text = str(path_value or "").strip()
    if not root_text or not path_text:
        return None
    try:
        root = Path(root_text).expanduser().resolve(strict=True)
        requested = Path(path_text).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        lexical = Path(os.path.abspath(str(candidate)))
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None

    # Reject symlink/path-alias ambiguity. A later slice can support aliases only
    # after repository-path identity is made explicit rather than inferred.
    if resolved != lexical:
        return None
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    rel = normalized_git_path(relative.as_posix())
    if not rel:
        return None
    return root, resolved, rel


def _matching_path_fact(
    facts: Mapping[str, Any],
    target: Path,
) -> Mapping[str, Any] | None:
    raw = facts.get("paths")
    if not isinstance(raw, list):
        return None
    target_text = str(target)
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            observed = Path(str(item.get("path") or "")).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if str(observed) == target_text:
            return item
    return None

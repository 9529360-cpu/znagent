from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


_CONTEXT_ROOT_KEYS = ("workspace_path", "project_path", "repo_path", "workdir")


def resolve_context_path(
    value: str | Path,
    context: Mapping[str, Any] | None = None,
) -> Path:
    """Resolve a work-relative host path against ZN's durable local context.

    Absolute paths remain absolute. Relative paths are anchored to the first
    concrete workspace/project/workdir root already present in the resident
    event. This keeps filesystem investigation and movement aligned with the
    same durable work association that anchors Git and terminal execution.
    """

    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path

    values = context or {}
    for key in _CONTEXT_ROOT_KEYS:
        raw_root = values.get(key)
        if raw_root is None or not str(raw_root).strip():
            continue
        return Path(str(raw_root)).expanduser() / path
    return path


def resolved_within(root: str | Path, candidate: str | Path) -> Path | None:
    """Return the real candidate only when it stays inside the real root."""

    try:
        resolved_root = Path(root).expanduser().resolve(strict=True)
        resolved_candidate = Path(candidate).expanduser().resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved_candidate

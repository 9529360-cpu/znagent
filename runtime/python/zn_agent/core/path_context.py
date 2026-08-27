from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


_CONTEXT_ROOT_KEYS = ("workspace_path", "project_path", "repo_path", "workdir")
_IS_WINDOWS = os.name == "nt"


def _windows_long_path_name(value: str) -> str:
    """Expand DOS 8.3 components without resolving symlinks or reparse points."""

    if not _IS_WINDOWS:
        return value
    import ctypes
    from ctypes import wintypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
    function.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    function.restype = wintypes.DWORD
    required = int(function(value, None, 0))
    if required <= 0:
        return value
    buffer = ctypes.create_unicode_buffer(required)
    written = int(function(value, buffer, required))
    if written <= 0:
        return value
    if written >= required:
        buffer = ctypes.create_unicode_buffer(written + 1)
        written = int(function(value, buffer, written + 1))
        if written <= 0:
            return value
    return buffer.value or value


def canonical_host_path(value: str | Path) -> Path:
    """Return an absolute lexical path with Windows DOS components expanded.

    This does not follow symlinks or reparse points. Missing suffix components
    are reattached after expanding the longest existing prefix.
    """

    absolute = Path(os.path.abspath(str(Path(str(value)).expanduser())))
    if not _IS_WINDOWS:
        return absolute
    probe = absolute
    missing: list[str] = []
    while not probe.exists() and probe.parent != probe:
        missing.append(probe.name)
        probe = probe.parent
    expanded = Path(_windows_long_path_name(str(probe)))
    for part in reversed(missing):
        expanded /= part
    return expanded


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
        return canonical_host_path(path)

    values = context or {}
    for key in _CONTEXT_ROOT_KEYS:
        raw_root = values.get(key)
        if raw_root is None or not str(raw_root).strip():
            continue
        candidate = Path(str(raw_root)).expanduser() / path
        return canonical_host_path(candidate) if candidate.is_absolute() else candidate
    return path


def resolved_within(root: str | Path, candidate: str | Path) -> Path | None:
    """Return the real candidate only when it stays inside the real root."""

    try:
        resolved_root = canonical_host_path(root).resolve(strict=True)
        resolved_candidate = canonical_host_path(candidate).resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved_candidate

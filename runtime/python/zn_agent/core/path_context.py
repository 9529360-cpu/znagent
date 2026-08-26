from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


_CONTEXT_ROOT_KEYS = ("workspace_path", "project_path", "repo_path", "workdir")


def _windows_long_path_name(value: str) -> str:
    """Expand DOS 8.3 components without resolving symlinks/reparse points."""

    if os.name != "nt":
        return value

    import ctypes
    from ctypes import wintypes

    get_long_path_name = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
    get_long_path_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_long_path_name.restype = wintypes.DWORD

    required = int(get_long_path_name(value, None, 0))
    if required <= 0:
        return value
    buffer = ctypes.create_unicode_buffer(required)
    written = int(get_long_path_name(value, buffer, required))
    if written <= 0:
        return value
    if written >= required:
        buffer = ctypes.create_unicode_buffer(written + 1)
        written = int(get_long_path_name(value, buffer, written + 1))
        if written <= 0:
            return value
    return buffer.value or value


def lexical_host_path(value: str | Path) -> Path:
    """Return one absolute lexical host path with Windows 8.3 aliases expanded.

    This deliberately does *not* call ``Path.resolve``. On Windows,
    ``GetLongPathNameW`` expands DOS short-name aliases while preserving the
    lexical symlink/reparse-point route. Callers can therefore compare the
    result with ``resolve(strict=True)`` and keep the existing fail-closed
    symlink check without mistaking an 8.3 spelling for a symlink alias.

    For a not-yet-created target, only the longest existing prefix is expanded
    and the missing suffix is reattached unchanged.
    """

    expanded = Path(str(value)).expanduser()
    absolute = Path(os.path.abspath(str(expanded)))
    if os.name != "nt":
        return absolute

    probe = absolute
    missing: list[str] = []
    while not probe.exists() and probe.parent != probe:
        missing.append(probe.name)
        probe = probe.parent

    long_prefix = Path(_windows_long_path_name(str(probe)))
    for part in reversed(missing):
        long_prefix /= part
    return long_prefix


def resolve_context_path(
    value: str | Path,
    context: Mapping[str, Any] | None = None,
) -> Path:
    """Resolve a work-relative host path against ZN's durable local context.

    Absolute paths remain absolute. Relative paths are anchored to the first
    concrete workspace/project/workdir root already present in the resident
    event. This keeps filesystem investigation and movement aligned with the
    same durable work association that anchors Git and terminal execution.

    Existing absolute/anchored Windows paths are normalized only at the lexical
    native-identity layer so DOS 8.3 spellings do not create false identity
    mismatches. Symlinks are intentionally not resolved here.
    """

    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return lexical_host_path(path)

    values = context or {}
    for key in _CONTEXT_ROOT_KEYS:
        raw_root = values.get(key)
        if raw_root is None or not str(raw_root).strip():
            continue
        candidate = Path(str(raw_root)).expanduser() / path
        return lexical_host_path(candidate) if candidate.is_absolute() else candidate
    return path


def resolved_within(root: str | Path, candidate: str | Path) -> Path | None:
    """Return the real candidate only when it stays inside the real root."""

    try:
        resolved_root = lexical_host_path(root).resolve(strict=True)
        resolved_candidate = lexical_host_path(candidate).resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved_candidate

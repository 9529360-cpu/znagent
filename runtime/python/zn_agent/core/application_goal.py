from __future__ import annotations

"""Typed deterministic fast path for opening one installed application."""

import re
from dataclasses import dataclass
from typing import Any, Mapping

APPLICATION_OPEN_GOAL_KIND = "open_installed_application"
_OPEN_PATTERNS = (
    re.compile(r"^(?:请|帮我|麻烦)?\s*(?:打开|启动|运行)\s*(?P<name>.+?)\s*[。.!！]?$", re.I),
    re.compile(r"^(?:please\s+)?(?:open|launch|start)\s+(?P<name>.+?)\s*[.!]?\s*$", re.I),
)
_FILE_LIKE_SUFFIX = re.compile(r"\.[a-z0-9]{1,12}$", re.I)
_WINDOWS_DRIVE = re.compile(r"^[a-z]:[\\/]", re.I)


@dataclass(frozen=True, slots=True)
class ApplicationOpenGoal:
    application_name: str


def application_open_goal_payload(goal: ApplicationOpenGoal) -> dict[str, Any]:
    return {"kind": APPLICATION_OPEN_GOAL_KIND, "application_name": goal.application_name}


def application_open_goal(event) -> ApplicationOpenGoal | None:
    payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event" or payload.get("body_action") or payload.get("native_action"):
        return None
    structured = payload.get("application_open_goal")
    if isinstance(structured, Mapping):
        return _structured_goal(structured)
    return explicit_application_open_goal_hint(event)


def explicit_application_open_goal_hint(event) -> ApplicationOpenGoal | None:
    payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event" or payload.get("body_action") or payload.get("native_action"):
        return None
    task = " ".join(str(getattr(event, "task", "") or "").strip().split())
    if not task or len(task) > 220:
        return None
    for pattern in _OPEN_PATTERNS:
        match = pattern.match(task)
        if match:
            name = _clean(match.group("name"))
            return ApplicationOpenGoal(name) if _safe_name(name) else None
    return None


def _structured_goal(raw: Mapping[str, Any]) -> ApplicationOpenGoal | None:
    kind = _clean(raw.get("kind"))
    if kind and kind != APPLICATION_OPEN_GOAL_KIND:
        return None
    name = _clean(raw.get("application_name"))
    return ApplicationOpenGoal(name) if _safe_name(name) else None


def _safe_name(value: str) -> bool:
    if not value or len(value) > 160 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    lowered = value.casefold()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return False
    if _WINDOWS_DRIVE.match(value) or value.startswith(("\\\\", "/", "~")):
        return False
    if "\\" in value or "/" in value or _FILE_LIKE_SUFFIX.search(value):
        return False
    return True


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())

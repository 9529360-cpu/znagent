from __future__ import annotations

"""Structured permission model (W-1).

A permission engine, not model judgement. Per action type the user
configures one of three modes:

- ``always_ask`` -- always show an approval card;
- ``always_allow`` -- auto-approve (bounded by the allowlist when one is
  configured);
- ``agent_decides`` -- the agent decides per case (fall through to the
  existing approval gate / rules).

Command allowlist / denylist are regex patterns, searched (not
full-matched). Precedence is fixed:

1. denylist -- absolute. A denylisted command is denied even if it also
   matches the allowlist, even if the mode is ``always_allow``, and even
   if a session grant covers it.
2. session auto-approve grant -- per-session, in-memory only, never
   persisted. A grant dies with the session.
3. mode + allowlist -- ``always_allow`` auto-approves; when an allowlist
   is configured the command must also match it, otherwise it falls back
   to asking.

Auto-approve is per session by construction: grants live in a
``SessionAutoApprove`` instance that is never written to disk, so a new
process / session starts with no grants.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


ACTION_TYPES = (
    "terminal_command",
    "file_write",
    "file_delete",
    "send",
    "publish",
    "purchase",
    "production_change",
)

_MODES = ("always_ask", "always_allow", "agent_decides")


class PermissionMode(str, Enum):
    ALWAYS_ASK = "always_ask"
    ALWAYS_ALLOW = "always_allow"
    AGENT_DECIDES = "agent_decides"


class PermissionVerdict(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    AGENT_DECIDES = "agent_decides"


def validate_action_type(action_type: str) -> str:
    normalized = str(action_type or "").strip().lower()
    if normalized not in ACTION_TYPES:
        raise ValueError(f"unsupported permission action type: {normalized or '<empty>'}")
    return normalized


def _compile_patterns(patterns: tuple[str, ...] | list[str] | None, *, label: str) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for raw in patterns or ():
        text = str(raw or "")
        if not text.strip():
            raise ValueError(f"{label} pattern must not be empty")
        try:
            compiled.append(re.compile(text))
        except re.error as exc:
            raise ValueError(f"invalid {label} regex {text!r}: {exc}") from exc
    return tuple(compiled)


def _matches(patterns: tuple[re.Pattern[str], ...], command: str) -> bool:
    return any(pattern.search(command) for pattern in patterns)


class SessionAutoApprove:
    """In-memory, per-session auto-approve grants. Never persisted."""

    def __init__(self) -> None:
        self._grants: dict[str, list[tuple[str, re.Pattern[str]]]] = {}

    def grant(self, session_id: str, action_type: str, pattern: str) -> None:
        normalized_session = str(session_id or "").strip()
        if not normalized_session:
            raise ValueError("session id must not be empty")
        compiled = _compile_patterns([pattern], label="session grant")[0]
        self._grants.setdefault(normalized_session, []).append(
            (validate_action_type(action_type), compiled)
        )

    def revoke_session(self, session_id: str) -> None:
        self._grants.pop(str(session_id or "").strip(), None)

    def is_granted(self, session_id: str | None, action_type: str, command: str) -> bool:
        if not session_id or not command:
            return False
        for granted_type, pattern in self._grants.get(str(session_id), ()):  # noqa: PLR2004
            if granted_type == action_type and pattern.search(command):
                return True
        return False

    def grant_count(self, session_id: str) -> int:
        return len(self._grants.get(str(session_id or "").strip(), ()))


@dataclass
class PermissionPolicy:
    """Three-state permission per action type + command lists + sessions."""

    modes: dict[str, PermissionMode] = field(default_factory=dict)
    allowlist: tuple[str, ...] = ()
    denylist: tuple[str, ...] = ()
    sessions: SessionAutoApprove = field(default_factory=SessionAutoApprove)

    def __post_init__(self) -> None:
        normalized_modes: dict[str, PermissionMode] = {}
        for raw_type, raw_mode in (self.modes or {}).items():
            action_type = validate_action_type(raw_type)
            if isinstance(raw_mode, PermissionMode):
                mode = raw_mode
            else:
                text = str(raw_mode or "").strip().lower()
                if text not in _MODES:
                    raise ValueError(f"unsupported permission mode: {text or '<empty>'}")
                mode = PermissionMode(text)
            normalized_modes[action_type] = mode
        self.modes = normalized_modes
        self._allowlist = _compile_patterns(self.allowlist, label="allowlist")
        self._denylist = _compile_patterns(self.denylist, label="denylist")

    def mode_for(self, action_type: str) -> PermissionMode:
        return self.modes.get(validate_action_type(action_type), PermissionMode.AGENT_DECIDES)

    def denies(self, action_type: str, command: str) -> bool:
        """Denylist only: True when the command is absolutely blocked."""
        validate_action_type(action_type)
        return bool(command) and _matches(self._denylist, command)

    def evaluate(
        self,
        action_type: str,
        command: str = "",
        *,
        session_id: str | None = None,
    ) -> PermissionVerdict:
        normalized_type = validate_action_type(action_type)
        normalized_command = str(command or "")
        # 1. Denylist is absolute: beats allowlist, auto-execution and
        #    session grants.
        if self.denies(normalized_type, normalized_command):
            return PermissionVerdict.DENY
        # 2. Session grant (per-session auto-approve).
        if self.sessions.is_granted(session_id, normalized_type, normalized_command):
            return PermissionVerdict.ALLOW
        # 3. Mode + allowlist.
        mode = self.mode_for(normalized_type)
        if mode is PermissionMode.ALWAYS_ALLOW:
            if self._allowlist and normalized_command and not _matches(
                self._allowlist, normalized_command
            ):
                # Allowlist bounds auto-approve: an always_allow mode does
                # not auto-execute a command the allowlist never blessed.
                return PermissionVerdict.ASK
            return PermissionVerdict.ALLOW
        if mode is PermissionMode.ALWAYS_ASK:
            return PermissionVerdict.ASK
        return PermissionVerdict.AGENT_DECIDES

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": {key: mode.value for key, mode in self.modes.items()},
            "allowlist": list(self.allowlist),
            "denylist": list(self.denylist),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PermissionPolicy":
        data = dict(raw or {})
        return cls(
            modes=dict(data.get("modes") or {}),
            allowlist=tuple(str(item) for item in (data.get("allowlist") or ())),
            denylist=tuple(str(item) for item in (data.get("denylist") or ())),
        )

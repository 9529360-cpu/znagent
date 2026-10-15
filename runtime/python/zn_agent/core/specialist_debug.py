from __future__ import annotations

"""Conversational debugging for one specialist (FastClaw-style).

Team dispatch already re-reads specialist files per dispatch (see
``specialist_workspace.specialist_prompt_for``), but a dispatch is
one-shot per work item: there is no way to hold a multi-turn
conversation with ONE specialist, watch how it behaves, edit its
files, and see the change on the next turn -- all without restarting
anything.

``SpecialistDebugSession`` is that loop:

- One session = one specialist, one conversation. The debugger (the
  user, or ZN acting on their behalf) talks to the specialist turn by
  turn, outside the team plan flow -- no work item, no dispatch.
- Every turn re-reads the specialist's workspace files, so editing
  ``SOUL.md`` / ``MEMORY.md`` / ``agent.json`` between turns takes
  effect on the next turn. The session itself caches no prompt.
- Each turn reports whether the prompt changed since the previous
  turn, so the debugger can prove the edit landed instead of
  guessing.

File edits go through the normal path (edit the files on disk, or
ask ZN to edit them); the session only guarantees it never serves a
stale persona. Cognition failures propagate -- a debug session that
swallowed them would hide exactly the behaviour being debugged.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .specialist_workspace import specialist_prompt_for, workspace_dir


@dataclass(frozen=True, slots=True)
class DebugTurn:
    """One completed debug turn."""

    reply: str
    prompt_sha: str
    prompt_changed: bool
    turn_index: int


@dataclass(slots=True)
class SpecialistDebugSession:
    """Multi-turn conversation with one specialist, files as source of truth.

    ``cognition`` is duck-typed: it needs ``invoke(question=...,
    context=...)`` returning an object with a ``.text`` attribute (the
    ``CognitiveResource`` protocol). The session keeps the conversation
    history; the specialist's prompt is re-read from disk on every
    turn and never cached.
    """

    team: Any
    specialist_name: str
    cognition: Any
    _history: list[dict[str, str]] = field(default_factory=list, repr=False)
    _last_prompt_sha: str | None = field(default=None, repr=False)
    _turn_count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if not self.specialist_name or not str(self.specialist_name).strip():
            raise ValueError("specialist name must not be empty")
        if self._resolve_specialist() is None:
            raise ValueError(
                f"unknown specialist: {self.specialist_name!r} "
                f"(not a member of team {getattr(self.team, 'team_id', '?')})"
            )
        if not callable(getattr(self.cognition, "invoke", None)):
            raise ValueError("cognition must provide invoke(question=..., context=...)")

    def _resolve_specialist(self) -> Any:
        member = getattr(self.team, "member", None)
        if not callable(member):
            return None
        return member(self.specialist_name)

    def _fresh_prompt(self) -> str:
        specialist = self._resolve_specialist()
        if specialist is None:
            raise ValueError(f"specialist left the team: {self.specialist_name!r}")
        return specialist_prompt_for(self.team, specialist)

    def current_prompt(self) -> str:
        """The prompt the next turn would use, re-read from disk now."""
        return self._fresh_prompt()

    def workspace_path(self) -> Path | None:
        """Directory holding this specialist's files, if the team has one."""
        root = getattr(self.team, "workspace_root", None)
        if not root:
            return None
        return workspace_dir(root, self.specialist_name)

    @property
    def history(self) -> list[dict[str, str]]:
        """Conversation so far (copies; the session owns the original)."""
        return [dict(entry) for entry in self._history]

    def turn(self, user_message: str) -> DebugTurn:
        """Send one message, get one reply under the freshly-read prompt."""
        if not user_message or not str(user_message).strip():
            raise ValueError("debug message must not be empty")
        prompt = self._fresh_prompt()
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        prompt_changed = (
            self._last_prompt_sha is not None
            and prompt_sha != self._last_prompt_sha
        )

        history_lines = []
        for entry in self._history:
            role = "User" if entry["role"] == "user" else "Assistant"
            history_lines.append(f"{role}: {entry['content']}")
        context_parts = [prompt]
        if history_lines:
            context_parts.append("# CONVERSATION\n\n" + "\n".join(history_lines))
        context = "\n\n".join(part for part in context_parts if part.strip())

        increment = self.cognition.invoke(
            question=str(user_message), context=context
        )
        reply = str(getattr(increment, "text", "") or "")

        self._history.append({"role": "user", "content": str(user_message)})
        self._history.append({"role": "assistant", "content": reply})
        self._last_prompt_sha = prompt_sha
        self._turn_count += 1
        return DebugTurn(
            reply=reply,
            prompt_sha=prompt_sha,
            prompt_changed=prompt_changed,
            turn_index=self._turn_count,
        )


__all__ = ["DebugTurn", "SpecialistDebugSession"]

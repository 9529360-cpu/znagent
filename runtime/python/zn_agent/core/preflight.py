from __future__ import annotations

"""Verify-before-acting preflight for tool calls (Muse pattern M9).

Mechanism ported from Muse's "verify before acting" discipline: before
calling an external capability, verify on the spot that the connection is
ready and that the skill being relied on actually exists and is usable.
The implementation below is written for ZN; no Muse code is copied.

What this module does (and does not do):

- Connection preflight: a caller registers a lightweight readiness probe
  per connection (connectivity / authorization state). A probe MUST be a
  cheap local check -- it must never send the real request, start a
  session, or retry. When the probe says "not ready", the caller returns
  ``not ready + reason + recovery path`` and sends nothing.
- Skill-as-source-of-truth: before relying on a skill, verify it exists in
  the SkillStore and passes validation. A missing skill reports "no such
  skill + available alternatives"; a present-but-invalid bundle reports
  "invalid bundle + how to fix it". Capabilities are never invented.
- This module is NOT the failure/rate-limit policy. Rate-limit hard-stop
  (429 -> stop, no retry, no reroute) belongs to the failure-policy lane
  (CP-4); preflight deliberately has no retry, backoff, or reroute logic
  of its own. Preflight answers one question: "is it safe to send this
  call right now?"

Callers wire preflight into an existing call choke point -- e.g.
``StdioMcpClient.call_tool`` (MCP connector) and
``agentic_tool_loop.execute_tool_call`` (model-driven tool loop) -- and
pass ``preflight=None`` (the default) to keep the old behaviour. Preflight
only changes behaviour when a caller explicitly opts in.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .skills import SkillStore

_MAX_ALTERNATIVES = 10


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """One readiness verdict. ``ready`` is the only thing callers branch on."""

    ready: bool
    kind: str  # "connection" | "skill" | "preflight"
    target: str
    reason: str = ""
    recovery: str = ""

    def __bool__(self) -> bool:
        return self.ready

    @property
    def message(self) -> str:
        if self.ready:
            return f"ready: {self.target}"
        detail = self.reason or "not ready"
        if self.recovery:
            return f"not ready: {self.target}: {detail}; recovery: {self.recovery}"
        return f"not ready: {self.target}: {detail}"


class PreflightNotReadyError(RuntimeError):
    """Raised by ``PreflightChecker.require``; carries the verdict."""

    def __init__(self, result: PreflightResult) -> None:
        super().__init__(result.message)
        self.result = result


class ConnectionChecker(Protocol):
    """A cheap, side-effect-free readiness probe for one connection.

    Must NOT send the real request, open a session, or retry. It answers
    from already-known local state (client running flag, config/credential
    presence, cached health) only.
    """

    def __call__(self) -> PreflightResult: ...


def ready_if(
    is_ready: Callable[[], bool],
    *,
    target: str,
    reason: str,
    recovery: str,
) -> ConnectionChecker:
    """Build a checker from a boolean readiness supplier.

    Example: ``ready_if(lambda: client.running, target="mcp", ...)``.
    """

    def _check() -> PreflightResult:
        if bool(is_ready()):
            return PreflightResult(ready=True, kind="connection", target=target)
        return PreflightResult(
            ready=False,
            kind="connection",
            target=target,
            reason=reason,
            recovery=recovery,
        )

    return _check


class PreflightChecker:
    """Registry of connection probes + skill verification, testable in isolation."""

    def __init__(self, *, skill_store: SkillStore | None = None) -> None:
        self._connections: dict[str, ConnectionChecker] = {}
        self._skill_store = skill_store

    def register_connection(self, name: str, checker: ConnectionChecker) -> None:
        """Register (or replace) the readiness probe for ``name``."""
        key = str(name or "").strip()
        if not key:
            raise ValueError("connection name must not be empty")
        self._connections[key] = checker

    def registered_connections(self) -> tuple[str, ...]:
        return tuple(sorted(self._connections))

    def check_connection(
        self,
        name: str,
        *,
        default: ConnectionChecker | None = None,
    ) -> PreflightResult:
        """Verify one connection. Never sends the real request.

        An unregistered connection is NOT ready -- callers must not guess
        that an unknown connection works. ``default`` is used only when no
        checker is registered (lets a choke point supply a running-state
        probe without mutating the shared registry).
        """
        key = str(name or "").strip()
        if not key:
            return PreflightResult(
                ready=False,
                kind="connection",
                target="<empty>",
                reason="connection name must not be empty",
                recovery="pass a registered connection name to check",
            )
        checker = self._connections.get(key, default)
        if checker is None:
            return PreflightResult(
                ready=False,
                kind="connection",
                target=key,
                reason=f"no readiness checker registered for connection '{key}'",
                recovery=(
                    f"register a checker for '{key}' with "
                    "register_connection(), or verify the connection "
                    "manually before calling"
                ),
            )
        try:
            result = checker()
        except Exception as exc:  # A broken probe must not crash the call path.
            return PreflightResult(
                ready=False,
                kind="connection",
                target=key,
                reason=f"readiness checker raised {type(exc).__name__}: {exc}",
                recovery=f"fix the readiness checker for '{key}' and retry the check",
            )
        if not isinstance(result, PreflightResult):
            return PreflightResult(
                ready=False,
                kind="connection",
                target=key,
                reason="readiness checker did not return a PreflightResult",
                recovery=f"fix the readiness checker for '{key}' to return a PreflightResult",
            )
        return result

    def check_skill(self, name: str, *, store: SkillStore | None = None) -> PreflightResult:
        """Verify a skill exists and passes SkillStore validation.

        Skill-as-source-of-truth: a skill that fails validation is
        reported as invalid, never silently treated as usable; a missing
        skill reports the available alternatives instead of inventing one.
        """
        key = str(name or "").strip()
        if not key:
            return PreflightResult(
                ready=False,
                kind="skill",
                target="<empty>",
                reason="skill name must not be empty",
                recovery="pass a skill name to check",
            )
        skill_store = store if store is not None else self._skill_store
        if skill_store is None:
            skill_store = SkillStore()
        found = [skill for skill in skill_store.discover() if skill.name == key]
        if found:
            return PreflightResult(ready=True, kind="skill", target=key)
        skill_file = Path(skill_store.root) / key / "skill.md"
        if skill_file.is_file():
            return PreflightResult(
                ready=False,
                kind="skill",
                target=key,
                reason=(
                    f"skill bundle '{key}' exists at {skill_file} but failed "
                    "SkillStore validation (invalid name, missing/oversized "
                    "description, or empty body)"
                ),
                recovery=(
                    f"fix {skill_file} (valid name, non-empty description, "
                    "non-empty body) or remove the bundle"
                ),
            )
        available = sorted({skill.name for skill in skill_store.discover()})
        if available:
            shown = ", ".join(available[:_MAX_ALTERNATIVES])
            suffix = " (showing first 10)" if len(available) > _MAX_ALTERNATIVES else ""
            recovery = f"available skills: {shown}{suffix}; use one of those or add the skill first"
        else:
            recovery = "no skills are installed; add the skill bundle first"
        return PreflightResult(
            ready=False,
            kind="skill",
            target=key,
            reason=f"no such skill: '{key}'",
            recovery=recovery,
        )

    def verify(
        self,
        *,
        connection: str | None = None,
        skill: str | None = None,
        store: SkillStore | None = None,
        default_connection_checker: ConnectionChecker | None = None,
    ) -> PreflightResult:
        """Combined check: connection first, then skill. First failure wins."""
        target_parts: list[str] = []
        if connection is not None:
            result = self.check_connection(connection, default=default_connection_checker)
            if not result.ready:
                return result
            target_parts.append(f"connection:{connection}")
        if skill is not None:
            result = self.check_skill(skill, store=store)
            if not result.ready:
                return result
            target_parts.append(f"skill:{skill}")
        target = " + ".join(target_parts) if target_parts else "preflight"
        return PreflightResult(ready=True, kind="preflight", target=target)

    def require(
        self,
        *,
        connection: str | None = None,
        skill: str | None = None,
        store: SkillStore | None = None,
        default_connection_checker: ConnectionChecker | None = None,
    ) -> None:
        """Like ``verify`` but raises ``PreflightNotReadyError`` when not ready."""
        result = self.verify(
            connection=connection,
            skill=skill,
            store=store,
            default_connection_checker=default_connection_checker,
        )
        if not result.ready:
            raise PreflightNotReadyError(result)

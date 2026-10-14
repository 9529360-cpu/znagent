"""Project teams slice 3: long-lived specialist memory + project retrospective.

A specialist is a durable identity (slice 1), not a throwaway worker. Its
memory must therefore be durable *and* scoped: what the architect learns in
project A must not leak into project B, and disbanding a team must delete
exactly that team's memories -- no more, no less.

This module is a thin, additive adapter over ``StructuredMemory`` (the
existing facts table stays the sole owner; no schema change):

- :class:`TeamMemory` prefixes every key with the specialist's namespace
  (``team:{team_id}:{name}:``), which ``DisbandPlan.memory_key_prefix``
  (``team:{team_id}:``) already covers. Disband semantics are unchanged.
- :func:`distill_retrospective` turns the project journal (append-only,
  slice 1) into structured lessons -- the "team experience" a future
  project can borrow. Deterministic extraction, no LLM: decisions,
  blockers and handoffs are already labeled by journal kind.
- :func:`save_retrospective` stores those lessons under the team's shared
  namespace so the next team (or the resident) can recall them.

No second control plane, no new identity: this is namespaced use of the
existing memory API, executed by the resident under Work authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .memory import FactMatch, StructuredMemory
from .project_team import (
    JOURNAL_KINDS,
    Specialist,
    journal_message,
    team_memory_prefix,
)


def specialist_namespace(team_id: str, specialist_name: str) -> str:
    """Namespace owning one specialist's long-lived memory."""
    return f"{team_memory_prefix(team_id)}{specialist_name}"


def shared_namespace(team_id: str) -> str:
    """Namespace for team-level memory (retrospectives, shared lessons)."""
    return f"{team_memory_prefix(team_id)}shared"


class TeamMemory:
    """A ``StructuredMemory`` scoped to one namespace.

    Keys are stored as ``{namespace}:{key}``. The ``:`` separator is
    reserved -- user keys containing it are rejected so ``keys()`` and
    ``clear()`` can split reliably and ``DisbandPlan`` prefix deletion
    stays exact.
    """

    __slots__ = ("_memory", "_namespace", "_prefix")

    def __init__(self, memory: StructuredMemory, namespace: str):
        if not namespace or not namespace.strip():
            raise ValueError("namespace must not be empty")
        self._memory = memory
        self._namespace = namespace.strip()
        self._prefix = f"{self._namespace}:"

    @property
    def namespace(self) -> str:
        return self._namespace

    def _scoped(self, key: str) -> str:
        clean = str(key or "").strip()
        if not clean:
            raise ValueError("memory key must not be empty")
        if ":" in clean:
            raise ValueError("memory key must not contain ':'")
        return f"{self._prefix}{clean}"

    def _unscoped(self, scoped_key: str) -> str:
        assert scoped_key.startswith(self._prefix)
        return scoped_key[len(self._prefix):]

    def remember(self, key: str, value: Any, *, aliases: tuple[str, ...] = ()) -> None:
        self._memory.remember(
            self._scoped(key),
            value,
            aliases=tuple(self._scoped(a) for a in aliases),
        )

    def recall(self, query: str) -> FactMatch | None:
        # Scope the query: the facts table holds prefixed keys, and the
        # underlying recall is an exact normalized key/alias match.
        scoped_query = self._scoped(query)
        match = self._memory.recall(scoped_query)
        if match is None:
            return None
        key = match.key
        if not key.startswith(self._prefix):
            # A global (unscoped) fact matched the query text exactly;
            # it is not ours -- never leak another namespace's memory.
            return None
        matched_by = match.matched_by
        if isinstance(matched_by, str) and matched_by.startswith(self._prefix):
            matched_by = self._unscoped(matched_by)
        return FactMatch(self._unscoped(key), match.value, matched_by)

    def forget(self, key: str) -> None:
        self._memory.forget(self._scoped(key))

    def relevant_context(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        items = self._memory.relevant_context(query, **kwargs)
        out: list[dict[str, Any]] = []
        for item in items:
            key = str(item.get("key", ""))
            if not key.startswith(self._prefix):
                continue
            item = dict(item)
            item["key"] = self._unscoped(key)
            out.append(item)
        return out

    def keys(self) -> list[str]:
        """Unprefixed keys owned by this namespace, sorted."""
        return sorted(
            self._unscoped(f["key"])
            for f in self._memory.store.list_facts()
            if str(f["key"]).startswith(self._prefix)
        )

    def clear(self) -> int:
        """Delete every fact in this namespace. Returns the count removed."""
        doomed = [
            str(f["key"])
            for f in self._memory.store.list_facts()
            if str(f["key"]).startswith(self._prefix)
        ]
        for key in doomed:
            self._memory.store.delete_fact(key)
        return len(doomed)


def specialist_memory(
    memory: StructuredMemory, specialist: Specialist
) -> TeamMemory:
    """Long-lived memory for one specialist (slice 1's ``memory_namespace``)."""
    return TeamMemory(memory, specialist.memory_namespace)


def team_shared_memory(memory: StructuredMemory, team_id: str) -> TeamMemory:
    """Team-level memory: retrospectives and shared lessons."""
    return TeamMemory(memory, shared_namespace(team_id))


def delete_team_memory(memory: StructuredMemory, team_id: str) -> int:
    """Delete EVERY fact owned by one team, across all its namespaces.

    Specialists (``team:{id}:{name}:``) and shared state
    (``team:{id}:shared:``) all fall under ``DisbandPlan.memory_key_prefix``
    (``team:{id}:``), so one prefix sweep covers roster, spec, plan map,
    assignee overrides and the retrospective. Aliases live on the fact row
    itself, so deleting the row deletes its aliases too. Returns the count
    removed. Callers verify with a re-read after (see ``team_disband``).
    """
    if not team_id or not str(team_id).strip():
        raise ValueError("team_id must not be empty")
    prefix = team_memory_prefix(str(team_id).strip())
    doomed = [
        str(f["key"])
        for f in memory.store.list_facts()
        if str(f["key"]).startswith(prefix)
    ]
    for key in doomed:
        memory.store.delete_fact(key)
    return len(doomed)


@dataclass(slots=True)
class Retrospective:
    """What the project journal distills into -- reusable team experience."""

    team_id: str
    entry_count: int
    decisions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    handoffs: tuple[str, ...] = ()
    lessons: tuple[str, ...] = field(default=())

    def summary(self) -> str:
        lines = [
            f"项目 {self.team_id} 复盘（{self.entry_count} 条日志）：",
            f"- 决定 {len(self.decisions)} 项",
            f"- 阻塞 {len(self.blockers)} 项",
            f"- 交接 {len(self.handoffs)} 项",
            f"- 经验 {len(self.lessons)} 条",
        ]
        return "\n".join(lines)


def distill_retrospective(
    team_id: str, entries: list[dict[str, Any]]
) -> Retrospective:
    """Distill journal entries into a retrospective.

    ``entries`` are :func:`journal_message` payloads (``role``/``text``/
    ``detail`` with ``kind``/``author``). Extraction is deterministic and
    kind-driven -- no LLM, no guessing:

    - ``decision`` entries become recorded decisions and lessons;
    - ``blocker`` entries become recorded blockers and lessons;
    - ``handoff`` entries become recorded handoffs and lessons;
    - other kinds (``note``, ``progress``) count toward coverage but are
      not promoted to lessons on their own.
    """
    decisions: list[str] = []
    blockers: list[str] = []
    handoffs: list[str] = []
    lessons: list[str] = []
    count = 0
    for entry in entries or []:
        detail = entry.get("detail") or {}
        if detail.get("team_id") != team_id:
            continue
        kind = detail.get("kind")
        if kind not in JOURNAL_KINDS:
            continue
        count += 1
        text = str(entry.get("text") or "").strip()
        author = str(detail.get("author") or "").strip()
        if not text:
            continue
        by = f"（{author}）" if author else ""
        if kind == "decision":
            decisions.append(text)
            lessons.append(f"决定：{text}{by}")
        elif kind == "blocker":
            blockers.append(text)
            lessons.append(f"曾阻塞：{text}{by}——下次同类项目提前排查")
        elif kind == "handoff":
            handoffs.append(text)
            lessons.append(f"交接经验：{text}{by}")
    return Retrospective(
        team_id=team_id,
        entry_count=count,
        decisions=tuple(decisions),
        blockers=tuple(blockers),
        handoffs=tuple(handoffs),
        lessons=tuple(lessons),
    )


def save_retrospective(
    shared: TeamMemory, retrospective: Retrospective
) -> None:
    """Persist a retrospective under the team's shared namespace."""
    shared.remember(
        "retrospective",
        {
            "team_id": retrospective.team_id,
            "entry_count": retrospective.entry_count,
            "decisions": list(retrospective.decisions),
            "blockers": list(retrospective.blockers),
            "handoffs": list(retrospective.handoffs),
            "lessons": list(retrospective.lessons),
        },
    )


__all__ = [
    "JOURNAL_KINDS",
    "Retrospective",
    "TeamMemory",
    "delete_team_memory",
    "distill_retrospective",
    "journal_message",
    "save_retrospective",
    "shared_namespace",
    "specialist_memory",
    "specialist_namespace",
    "team_shared_memory",
]

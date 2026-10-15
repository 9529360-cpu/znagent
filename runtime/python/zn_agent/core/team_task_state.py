from __future__ import annotations

"""Team task state machine (DSH-2): revision CAS + tombstone deletes +
advisory writeScopes for team tasks.

Design copied from the deepseek-harness task-state shape (MIT), not its
API shape: no runtime swap, no Cordis, no hosted/telemetry pieces. This
module is the *state machine only* -- it never executes work, never
touches the Work ledger, and never enforces file access.

What it adds on top of the existing pieces:

- ``WorkItem`` (steerable_work) has a thread-level ``plan_version`` and
  its ``_save_item`` overwrites unconditionally (last writer wins). There
  is no per-task revision and no compare-and-swap.
- AF-3 ``ProgressLedger`` (team_coordinator) tracks todo/in_progress/
  done/failed in memory with transition history, but has no revision,
  no delete at all, no full-snapshot shape, and no write scopes.
- Team disband hard-deletes team records. There is no per-task soft
  delete that keeps history queryable.

Rules (all enforced here, all in-memory; the caller owns durability --
persist ``export_snapshots()`` / ``export_advisories()`` wherever it
already persists team state, and rebuild with ``import_snapshots``):

- Full snapshots: a ``TaskSnapshot`` carries every task field
  (``to_dict`` / ``from_dict`` round-trip all of it, including history
  and tombstone fields). A snapshot is the unit of storage.
- Revision CAS: every successful write bumps ``revision`` by exactly 1.
  ``update_task`` requires ``expected_revision``; a mismatch raises
  ``RevisionConflictError`` and changes nothing -- the stored snapshot
  keeps its data, the caller re-reads and retries. No-op writes (no
  effective field change) return the current snapshot without consuming
  a revision.
- Tombstones: ``delete_task`` never erases a row. It sets
  ``deleted=True`` + ``deleted_at`` + ``deleted_reason``, keeps the last
  status and full history, and bumps the revision. Deleted tasks are
  excluded from ``list_tasks`` by default, stay queryable via
  ``get_task(..., include_deleted=True)`` / ``get_tombstone`` /
  ``list_tombstones``, and refuse further updates. There is deliberately
  NO hard-delete API -- a tombstone is retained, not erased.
- Advisory writeScopes: ``write_scopes`` is a tuple of relative path
  prefixes a task *suggests* its writes stay under. ``check_write_scope``
  only *advises*: an out-of-scope path returns an advisory with a warning
  and is recorded in the advisory log -- it never raises, never blocks,
  and never replaces the hard file isolation (workspace_file_discipline),
  which stays the only enforcement. Empty scopes mean unrestricted.
- Status vocabulary is shared with AF-3 ``ProgressLedger``:
  todo / in_progress / done / failed, with the same transition rules
  (``done`` is terminal; ``failed`` retries through todo/in_progress).

Relation to AF-2 / LG-1: this module does not touch
``CheckpointStorage``, the checkpoint parent chain, or the two-phase
write invariants. Checkpoints snapshot pulse boundaries; this store
snapshots per-task state. The two coexist without sharing a write path.
Relation to DSH-1: the session log is the fact source for model-visible
context; this store is the fact source for team task state. Neither
re-creates the other.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import utc_now

#: Shared with AF-3 ProgressLedger (team_coordinator.TASK_STATUSES).
TASK_STATUSES = ("todo", "in_progress", "done", "failed")

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "todo": frozenset({"in_progress", "done", "failed"}),
    "in_progress": frozenset({"todo", "done", "failed"}),
    "failed": frozenset({"todo", "in_progress"}),
    "done": frozenset(),
}


class RevisionConflictError(ValueError):
    """A CAS write named a stale revision. Stored data is untouched."""

    def __init__(self, task_id: str, *, expected: int, actual: int):
        super().__init__(
            f"revision conflict on task {task_id!r}: "
            f"expected revision {expected}, actual {actual} "
            "(re-read the snapshot and retry)"
        )
        self.task_id = task_id
        self.expected = expected
        self.actual = actual


class TaskDeletedError(ValueError):
    """The task is a tombstone: readable, but no longer writable."""

    def __init__(self, task_id: str):
        super().__init__(
            f"task {task_id!r} is deleted (tombstone retained, "
            "updates refused)"
        )
        self.task_id = task_id


class TaskNotFoundError(KeyError):
    """No task (live or tombstone) exists under this id."""

    def __init__(self, task_id: str):
        super().__init__(f"unknown task_id: {task_id!r}")
        self.task_id = task_id


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """One full snapshot of a team task, at one revision.

    Immutable: every store write returns a *new* snapshot with
    ``revision + 1``; the old snapshot stays a valid historical read.
    ``history`` entries are ``{seq, from, to, reason, revision}`` with
    ``revision`` the snapshot revision *after* that transition.
    """

    task_id: str
    team_id: str
    title: str = ""
    objective: str = ""
    status: str = "todo"
    assignee: str = ""
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    revision: int = 1
    deleted: bool = False
    deleted_at: str = ""
    deleted_reason: str = ""
    history: tuple[dict[str, Any], ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Full snapshot: every field, including history + tombstone."""
        return {
            "task_id": self.task_id,
            "team_id": self.team_id,
            "title": self.title,
            "objective": self.objective,
            "status": self.status,
            "assignee": self.assignee,
            "depends_on": list(self.depends_on),
            "acceptance_criteria": list(self.acceptance_criteria),
            "write_scopes": list(self.write_scopes),
            "revision": int(self.revision),
            "deleted": bool(self.deleted),
            "deleted_at": self.deleted_at,
            "deleted_reason": self.deleted_reason,
            "history": [dict(entry) for entry in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskSnapshot:
        """Rebuild a snapshot. Every field is restored, none defaulted
        away: a snapshot that round-trips must come back identical."""
        if not isinstance(raw, dict):
            raise ValueError("task snapshot must be a dict")
        task_id = str(raw.get("task_id") or "").strip()
        team_id = str(raw.get("team_id") or "").strip()
        if not task_id or not team_id:
            raise ValueError("task snapshot needs task_id and team_id")
        status = str(raw.get("status") or "todo")
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        history = raw.get("history") or ()
        if not isinstance(history, (list, tuple)):
            raise ValueError("task snapshot history must be a list")
        return cls(
            task_id=task_id,
            team_id=team_id,
            title=str(raw.get("title") or ""),
            objective=str(raw.get("objective") or ""),
            status=status,
            assignee=str(raw.get("assignee") or ""),
            depends_on=tuple(str(d) for d in (raw.get("depends_on") or ())),
            acceptance_criteria=tuple(
                str(c) for c in (raw.get("acceptance_criteria") or ())
            ),
            write_scopes=tuple(str(s) for s in (raw.get("write_scopes") or ())),
            revision=max(1, int(raw.get("revision") or 1)),
            deleted=bool(raw.get("deleted") or False),
            deleted_at=str(raw.get("deleted_at") or ""),
            deleted_reason=str(raw.get("deleted_reason") or ""),
            history=tuple(dict(entry) for entry in history),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class WriteScopeAdvisory:
    """The advisory outcome of one write-scope check. Never a block.

    ``in_scope=True`` means the path is inside the task's suggested
    scopes (or the task suggests no scopes). ``in_scope=False`` carries a
    human-readable ``warning`` -- the caller logs it and continues; the
    hard file isolation layer, not this advisory, decides enforcement.
    """

    task_id: str
    path: str
    in_scope: bool
    scopes: tuple[str, ...] = ()
    warning: str = ""


def _normalize_scopes(scopes: Any) -> tuple[str, ...]:
    """Validate write scopes: relative path prefixes, no empties."""
    if scopes is None:
        return ()
    if isinstance(scopes, (str, bytes)):
        raise ValueError("write_scopes must be a sequence of path prefixes")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in scopes:
        if not isinstance(raw, str):
            raise ValueError("write_scopes entries must be strings")
        scope = raw.strip()
        if not scope or scope != raw.strip():
            raise ValueError("write_scopes entries must be non-empty")
        if (
            scope.startswith("/")
            or scope in (".", "..")
            or ".." in scope.split("/")
        ):
            raise ValueError(
                f"write_scopes entry {scope!r} must be a relative path "
                "prefix (no absolute paths, no parent traversal)"
            )
        scope = scope.rstrip("/")
        if not scope:
            raise ValueError("write_scopes entries must be non-empty")
        if scope in seen:
            raise ValueError(f"duplicate write_scopes entry: {scope!r}")
        seen.add(scope)
        normalized.append(scope)
    return tuple(normalized)


def _path_in_scope(path: str, scopes: tuple[str, ...]) -> bool:
    """Prefix match on a path-segment boundary: ``agents/dev`` matches
    ``agents/dev/SOUL.md`` but NOT ``agents/dev2/x``."""
    if not scopes:
        return True
    candidate = str(path or "").strip().rstrip("/")
    if not candidate:
        return False
    for scope in scopes:
        if candidate == scope or candidate.startswith(scope + "/"):
            return True
    return False


class TeamTaskStateStore:
    """In-memory team task state: snapshots + CAS + tombstones + scopes.

    The caller owns durability (same pattern as AF-3 ProgressLedger):
    export with :meth:`export_snapshots` / :meth:`export_advisories`
    and rebuild with :meth:`import_snapshots`. This class only enforces
    the state-machine rules and records history + advisories.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSnapshot] = {}
        self._advisories: list[dict[str, Any]] = []
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # -- create / read ---------------------------------------------------

    def create_task(
        self,
        task_id: str,
        team_id: str,
        *,
        title: str = "",
        objective: str = "",
        status: str = "todo",
        assignee: str = "",
        depends_on: tuple[str, ...] | list[str] = (),
        acceptance_criteria: tuple[str, ...] | list[str] = (),
        write_scopes: tuple[str, ...] | list[str] = (),
    ) -> TaskSnapshot:
        """Create a task at revision 1. Duplicate ids raise ValueError."""
        task_id = str(task_id or "").strip()
        team_id = str(team_id or "").strip()
        if not task_id:
            raise ValueError("task_id must not be empty")
        if not team_id:
            raise ValueError("team_id must not be empty")
        if task_id in self._tasks:
            raise ValueError(f"duplicate task_id: {task_id!r}")
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        deps = tuple(str(d) for d in depends_on)
        if task_id in deps:
            raise ValueError("a task may not depend on itself")
        for dep in deps:
            if dep not in self._tasks:
                raise ValueError(f"unknown dependency: {dep!r}")
        now = utc_now()
        snapshot = TaskSnapshot(
            task_id=task_id,
            team_id=team_id,
            title=str(title or "").strip(),
            objective=str(objective or ""),
            status=status,
            assignee=str(assignee or ""),
            depends_on=deps,
            acceptance_criteria=tuple(str(c) for c in acceptance_criteria),
            write_scopes=_normalize_scopes(write_scopes),
            revision=1,
            history=(
                {
                    "seq": self._next_seq(),
                    "from": "",
                    "to": status,
                    "reason": "created",
                    "revision": 1,
                },
            ),
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = snapshot
        return snapshot

    def get_task(
        self, task_id: str, *, include_deleted: bool = False
    ) -> TaskSnapshot:
        """Current snapshot. Missing ids raise TaskNotFoundError; a
        tombstone raises TaskDeletedError unless ``include_deleted``."""
        snapshot = self._tasks.get(str(task_id))
        if snapshot is None:
            raise TaskNotFoundError(str(task_id))
        if snapshot.deleted and not include_deleted:
            raise TaskDeletedError(str(task_id))
        return snapshot

    def get_tombstone(self, task_id: str) -> TaskSnapshot | None:
        """The tombstone for a deleted task, or None (live / missing)."""
        snapshot = self._tasks.get(str(task_id))
        if snapshot is None or not snapshot.deleted:
            return None
        return snapshot

    def list_tasks(self, *, include_deleted: bool = False) -> list[TaskSnapshot]:
        """Snapshots in creation order. Tombstones excluded by default."""
        return [
            snapshot
            for snapshot in self._tasks.values()
            if include_deleted or not snapshot.deleted
        ]

    def list_tombstones(self) -> list[TaskSnapshot]:
        """Only the deleted tasks, in creation order."""
        return [s for s in self._tasks.values() if s.deleted]

    # -- CAS update ------------------------------------------------------

    def update_task(
        self,
        task_id: str,
        *,
        expected_revision: int,
        title: str | None = None,
        objective: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        depends_on: tuple[str, ...] | list[str] | None = None,
        acceptance_criteria: tuple[str, ...] | list[str] | None = None,
        write_scopes: tuple[str, ...] | list[str] | None = None,
        reason: str = "",
    ) -> TaskSnapshot:
        """CAS write: revision must match, else RevisionConflictError
        and nothing changes. Illegal status transitions raise ValueError
        and change nothing. A write with no effective field change is a
        no-op returning the current snapshot (no revision consumed)."""
        current = self._tasks.get(str(task_id))
        if current is None:
            raise TaskNotFoundError(str(task_id))
        if current.deleted:
            raise TaskDeletedError(str(task_id))
        if int(expected_revision) != int(current.revision):
            raise RevisionConflictError(
                str(task_id),
                expected=int(expected_revision),
                actual=int(current.revision),
            )
        new_status = current.status if status is None else str(status)
        if new_status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {new_status!r}")
        if (
            new_status != current.status
            and new_status not in _ALLOWED_TRANSITIONS[current.status]
        ):
            raise ValueError(
                f"illegal transition: {current.status} -> {new_status} "
                f"(task {task_id!r}); done is terminal, "
                "failed retries go through todo/in_progress"
            )
        new_values = {
            "title": current.title if title is None else str(title or "").strip(),
            "objective": current.objective if objective is None else str(objective or ""),
            "assignee": current.assignee if assignee is None else str(assignee or ""),
            "depends_on": current.depends_on
            if depends_on is None
            else tuple(str(d) for d in depends_on),
            "acceptance_criteria": current.acceptance_criteria
            if acceptance_criteria is None
            else tuple(str(c) for c in acceptance_criteria),
            "write_scopes": current.write_scopes
            if write_scopes is None
            else _normalize_scopes(write_scopes),
        }
        if (
            new_status == current.status
            and new_values["title"] == current.title
            and new_values["objective"] == current.objective
            and new_values["assignee"] == current.assignee
            and new_values["depends_on"] == current.depends_on
            and new_values["acceptance_criteria"] == current.acceptance_criteria
            and new_values["write_scopes"] == current.write_scopes
        ):
            return current
        if str(task_id) in new_values["depends_on"]:
            raise ValueError("a task may not depend on itself")
        for dep in new_values["depends_on"]:
            if dep not in self._tasks:
                raise ValueError(f"unknown dependency: {dep!r}")
        new_revision = int(current.revision) + 1
        updated = TaskSnapshot(
            task_id=current.task_id,
            team_id=current.team_id,
            title=new_values["title"],
            objective=new_values["objective"],
            status=new_status,
            assignee=new_values["assignee"],
            depends_on=new_values["depends_on"],
            acceptance_criteria=new_values["acceptance_criteria"],
            write_scopes=new_values["write_scopes"],
            revision=new_revision,
            deleted=False,
            deleted_at="",
            deleted_reason="",
            history=current.history
            + (
                {
                    "seq": self._next_seq(),
                    "from": current.status,
                    "to": new_status,
                    "reason": str(reason or ""),
                    "revision": new_revision,
                },
            ),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self._tasks[str(task_id)] = updated
        return updated

    # -- tombstone delete --------------------------------------------------

    def delete_task(self, task_id: str, *, reason: str = "") -> TaskSnapshot:
        """Soft delete: write a tombstone, keep the row and its history.

        The last status is preserved; ``deleted`` is the marker. The
        revision bumps by 1. Deleting a tombstone again raises
        TaskDeletedError (one tombstone per task). There is no
        hard-delete API: a tombstone is retained, never erased.
        """
        current = self._tasks.get(str(task_id))
        if current is None:
            raise TaskNotFoundError(str(task_id))
        if current.deleted:
            raise TaskDeletedError(str(task_id))
        new_revision = int(current.revision) + 1
        tombstone = TaskSnapshot(
            task_id=current.task_id,
            team_id=current.team_id,
            title=current.title,
            objective=current.objective,
            status=current.status,
            assignee=current.assignee,
            depends_on=current.depends_on,
            acceptance_criteria=current.acceptance_criteria,
            write_scopes=current.write_scopes,
            revision=new_revision,
            deleted=True,
            deleted_at=utc_now(),
            deleted_reason=str(reason or ""),
            history=current.history
            + (
                {
                    "seq": self._next_seq(),
                    "from": current.status,
                    "to": "deleted",
                    "reason": str(reason or ""),
                    "revision": new_revision,
                },
            ),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        self._tasks[str(task_id)] = tombstone
        return tombstone

    # -- advisory writeScopes ---------------------------------------------

    def check_write_scope(
        self, task_id: str, path: str, *, record: bool = True
    ) -> WriteScopeAdvisory:
        """Advisory-only scope check. Out-of-scope NEVER raises and NEVER
        blocks: it returns a warning advisory and (when ``record``) logs
        it. Unknown task ids raise TaskNotFoundError (a programming
        error, not a write). A check on a tombstone returns an
        out-of-scope advisory (the task is gone) without raising."""
        current = self._tasks.get(str(task_id))
        if current is None:
            raise TaskNotFoundError(str(task_id))
        candidate = str(path or "").strip()
        if current.deleted:
            advisory = WriteScopeAdvisory(
                task_id=str(task_id),
                path=candidate,
                in_scope=False,
                scopes=tuple(current.write_scopes),
                warning=(
                    f"task {task_id!r} is deleted (tombstone retained); "
                    "no writes expected for it"
                ),
            )
        elif _path_in_scope(candidate, tuple(current.write_scopes)):
            return WriteScopeAdvisory(
                task_id=str(task_id),
                path=candidate,
                in_scope=True,
                scopes=tuple(current.write_scopes),
            )
        else:
            advisory = WriteScopeAdvisory(
                task_id=str(task_id),
                path=candidate,
                in_scope=False,
                scopes=tuple(current.write_scopes),
                warning=(
                    f"advisory: path {candidate!r} is outside the task's "
                    f"suggested writeScopes {list(current.write_scopes)}; "
                    "not blocked -- hard file isolation still applies"
                ),
            )
        if record:
            self._advisories.append(
                {
                    "seq": self._next_seq(),
                    "task_id": advisory.task_id,
                    "path": advisory.path,
                    "scopes": list(advisory.scopes),
                    "warning": advisory.warning,
                }
            )
        return advisory

    def list_advisories(self) -> tuple[dict[str, Any], ...]:
        """Out-of-scope advisories recorded so far, in order."""
        return tuple(dict(entry) for entry in self._advisories)

    # -- team sync / decision mirror --------------------------------------

    def sync_from_team(self, team: Any) -> list[TaskSnapshot]:
        """Create one snapshot per plan item of a ProjectTeam (or any
        duck-typed object with ``team_id`` + ``plan`` items carrying
        ``item_id``/``title``/``objective``/``assignee``/
        ``dependency_ids``/``acceptance_criteria``). Existing tasks are
        returned as-is (idempotent); nothing is overwritten."""
        team_id = str(getattr(team, "team_id", "") or "").strip()
        if not team_id:
            raise ValueError("team needs a team_id")
        created: list[TaskSnapshot] = []
        for item in getattr(team, "plan", ()) or ():
            item_id = str(getattr(item, "item_id", "") or "").strip()
            if not item_id:
                continue
            existing = self._tasks.get(item_id)
            if existing is not None:
                created.append(existing)
                continue
            created.append(
                self.create_task(
                    item_id,
                    team_id,
                    title=str(getattr(item, "title", "") or ""),
                    objective=str(getattr(item, "objective", "") or ""),
                    status="todo",
                    assignee=str(getattr(item, "assignee", "") or ""),
                    depends_on=tuple(
                        str(d) for d in (getattr(item, "dependency_ids", ()) or ())
                    ),
                    acceptance_criteria=tuple(
                        str(c)
                        for c in (getattr(item, "acceptance_criteria", ()) or ())
                    ),
                )
            )
        return created

    def mirror_decision(
        self, decision: Any, *, reason: str = ""
    ) -> TaskSnapshot | None:
        """Mirror one coordinator decision into task state (observer only,
        same contract as AF-3's progress mirror): dispatch ->
        in_progress, complete -> done, via read-then-CAS. Unknown tasks,
        tombstones, same-status targets, and non-state actions (wait /
        verify / escalate / team_complete) are skipped. Never raises."""
        try:
            action = str(getattr(decision, "action", "") or "")
            work_item_id = getattr(decision, "work_item_id", None)
            if action not in ("dispatch", "complete") or not work_item_id:
                return None
            target = "in_progress" if action == "dispatch" else "done"
            current = self._tasks.get(str(work_item_id))
            if current is None or current.deleted or current.status == target:
                return None
            return self.update_task(
                str(work_item_id),
                expected_revision=int(current.revision),
                status=target,
                reason=reason or f"coordinator:{action}",
            )
        except (ValueError, KeyError):
            return None

    # -- snapshot export / import (caller-owned durability) ----------------

    def export_snapshots(self) -> dict[str, dict[str, Any]]:
        """Full snapshot export, tombstones included, in creation order."""
        return {
            task_id: snapshot.to_dict()
            for task_id, snapshot in self._tasks.items()
        }

    def export_advisories(self) -> tuple[dict[str, Any], ...]:
        """Advisory log export (out-of-scope checks only)."""
        return self.list_advisories()

    @classmethod
    def import_snapshots(
        cls,
        data: Mapping[str, Any],
        *,
        advisories: Any = (),
    ) -> TeamTaskStateStore:
        """Rebuild a store from ``export_snapshots`` output. Tombstones,
        revisions, and history survive the round-trip exactly."""
        store = cls()
        if not isinstance(data, Mapping):
            raise ValueError("snapshot export must be a mapping")
        for task_id, raw in data.items():
            snapshot = TaskSnapshot.from_dict(dict(raw))
            if snapshot.task_id != str(task_id):
                raise ValueError(
                    f"snapshot key {task_id!r} != task_id "
                    f"{snapshot.task_id!r}"
                )
            store._tasks[snapshot.task_id] = snapshot
        seqs = [
            int(entry.get("seq") or 0)
            for snapshot in store._tasks.values()
            for entry in snapshot.history
        ]
        adv_entries = [
            dict(entry) for entry in (advisories or ()) if isinstance(entry, Mapping)
        ]
        seqs.extend(int(entry.get("seq") or 0) for entry in adv_entries)
        store._seq = max(seqs) if seqs else 0
        store._advisories = adv_entries
        return store


__all__ = [
    "TASK_STATUSES",
    "RevisionConflictError",
    "TaskDeletedError",
    "TaskNotFoundError",
    "TaskSnapshot",
    "TeamTaskStateStore",
    "WriteScopeAdvisory",
]

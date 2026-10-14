from __future__ import annotations

"""Persistent user goals: durable goals + append-only progress entries.

Pattern source: Muse "Goals" (M13 in the copy-mature-patterns mapping
doc). Only the mechanism is copied; this implementation is original ZN
code. The three M13 rules this module enforces:

- A goal is durable state: title + description + status, persisted in
  SQLite next to the rest of the resident store.
- Completing a goal is not deleting it. There is deliberately no delete
  API anywhere in this module: ``complete_goal`` flips the status to
  ``completed`` and stamps ``archived_at``, and the goal (with all of its
  progress entries) stays queryable forever. ``archive_goal`` shelves a
  goal without completing it.
- Background updates only travel the scheduled-task path. The only
  background entry point is ``record_background_progress``, which
  requires a routine/scheduled-task context (a real routine id + a real
  routine run id). A direct background write without that context is
  rejected with ``PermissionError``. Progress entries are append-only:
  there is no edit or delete API for them either.

Storage follows the existing ``routine.py`` pattern: a dedicated
SQLite connection to the same ``KernelStore`` file, with its own
tables. It does NOT reuse the ``goals`` table in ``store.py`` — that
table owns internal execution goals (task routing / retries), a
different concept from a user's durable goals. The distinct table
names (``resident_user_goals``) and id prefix (``ugoal-``) keep the two
from ever being confused.
"""

import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .models import utc_now

GOAL_STATUSES = ("active", "completed", "archived")
BACKGROUND_SOURCES = ("routine", "scheduled")
MAX_TITLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 10000
MAX_PROGRESS_CHARS = 10000
MAX_EVIDENCE_REF_CHARS = 2000
_INSTALL_MARKER = "_zn_user_goal_behavior_installed"


@dataclass(slots=True)
class UserGoal:
    goal_id: str
    title: str
    description: str = ""
    status: str = "active"  # active | completed | archived
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    archived_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class UserGoalProgressEntry:
    entry_id: str
    goal_id: str
    content: str
    created_at: str = ""
    evidence_ref: str | None = None
    source: str = "user"  # user | routine | scheduled
    routine_id: str | None = None
    routine_run_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class UserGoalManager:
    """Durable user goals + append-only progress, on the resident store."""

    def __init__(self, resident):
        self.resident = resident
        self.store = resident.store
        self._lock = threading.RLock()
        self._init_schema()

    # -- creation ---------------------------------------------------------

    def create_goal(
        self, title: str, description: str = "", *, status: str = "active"
    ) -> dict:
        """Create a goal. Returns its snapshot (no progress entries yet)."""
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("goal title must not be empty")
        if len(clean_title) > MAX_TITLE_CHARS:
            raise ValueError(f"goal title must be at most {MAX_TITLE_CHARS} characters")
        clean_description = str(description or "").strip()
        if len(clean_description) > MAX_DESCRIPTION_CHARS:
            raise ValueError(
                f"goal description must be at most {MAX_DESCRIPTION_CHARS} characters"
            )
        clean_status = str(status or "").strip().lower()
        if clean_status not in GOAL_STATUSES:
            raise ValueError(
                f"unknown goal status: {status!r} (expected one of {GOAL_STATUSES})"
            )
        now = utc_now()
        goal_id = f"ugoal-{uuid.uuid4().hex[:12]}"
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_user_goals(
                    goal_id,title,description,status,
                    created_at,updated_at,completed_at,archived_at
                ) VALUES(?,?,?,?,?,?,NULL,NULL)
                """,
                (
                    goal_id,
                    clean_title,
                    clean_description,
                    clean_status,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.snapshot(goal_id)

    # -- reads ------------------------------------------------------------

    def get(self, goal_id: str) -> UserGoal | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM resident_user_goals WHERE goal_id=?",
                (str(goal_id),),
            ).fetchone()
        return self._goal_from_row(row) if row else None

    def snapshot(self, goal_id: str) -> dict:
        """One goal with ALL of its progress entries, oldest first."""
        goal = self._require(goal_id)
        data = goal.to_dict()
        data["progress"] = [entry.to_dict() for entry in self._entries(goal)]
        return data

    def list_goals(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        """Goals (newest first) with a progress count, not full entries.

        ``status`` filters to one of active / completed / archived; omit
        it to list every goal, including completed and archived ones —
        completing a goal never removes it from query results.
        """
        query = "SELECT * FROM resident_user_goals"
        params: list[Any] = []
        if status is not None:
            clean_status = str(status).strip().lower()
            if clean_status not in GOAL_STATUSES:
                raise ValueError(f"unknown goal status: {status!r}")
            query += " WHERE status=?"
            params.append(clean_status)
        query += " ORDER BY created_at DESC, goal_id DESC LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            goal = self._goal_from_row(row)
            entries = self._entries(goal)
            data = goal.to_dict()
            data["progress_count"] = len(entries)
            data["latest_progress_at"] = (
                entries[-1].created_at if entries else None
            )
            result.append(data)
        return result

    def list_progress(self, goal_id: str, *, limit: int = 100) -> list[dict]:
        """All progress entries for one goal, oldest first."""
        goal = self._require(goal_id)
        entries = self._entries(goal, limit=limit)
        return [entry.to_dict() for entry in entries]

    # -- progress: append-only ---------------------------------------------

    def add_progress(
        self,
        goal_id: str,
        content: str,
        *,
        evidence_ref: str | None = None,
        source: str = "user",
        routine_context: Mapping[str, Any] | None = None,
    ) -> dict:
        """Append one progress entry (time + content + evidence reference).

        Foreground (``source="user"``) entries need no context. Background
        entries (``source="routine"`` / ``"scheduled"``) require a
        ``routine_context`` proving they came through a real scheduled
        task run; anything else is rejected. There is no API to edit or
        delete an entry once appended.
        """
        goal = self._require(goal_id)
        if goal.status != "active":
            raise ValueError(
                f"cannot add progress to a {goal.status} goal: {goal.goal_id}"
            )
        clean_content = str(content or "").strip()
        if not clean_content:
            raise ValueError("progress content must not be empty")
        if len(clean_content) > MAX_PROGRESS_CHARS:
            raise ValueError(
                f"progress content must be at most {MAX_PROGRESS_CHARS} characters"
            )
        clean_evidence = None
        if evidence_ref is not None:
            clean_evidence = str(evidence_ref).strip() or None
            if clean_evidence is not None and len(clean_evidence) > MAX_EVIDENCE_REF_CHARS:
                raise ValueError(
                    "evidence reference must be at most "
                    f"{MAX_EVIDENCE_REF_CHARS} characters"
                )
        clean_source = str(source or "").strip().lower()
        routine_id: str | None = None
        routine_run_id: str | None = None
        if clean_source == "user":
            if routine_context is not None:
                raise ValueError(
                    "a foreground (user) progress entry must not carry a "
                    "routine context; use record_background_progress for "
                    "background updates so provenance stays honest"
                )
        elif clean_source in BACKGROUND_SOURCES:
            _, routine_id, routine_run_id = self._validate_routine_context(
                routine_context
            )
        else:
            raise ValueError(
                f"unknown progress source: {source!r} "
                f"(expected 'user' or one of {BACKGROUND_SOURCES})"
            )
        now = utc_now()
        entry_id = f"uprog-{uuid.uuid4().hex[:12]}"
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_user_goal_progress(
                    entry_id,goal_id,created_at,content,evidence_ref,
                    source,routine_id,routine_run_id
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    entry_id,
                    goal.goal_id,
                    now,
                    clean_content,
                    clean_evidence,
                    clean_source,
                    routine_id,
                    routine_run_id,
                ),
            )
            conn.execute(
                "UPDATE resident_user_goals SET updated_at=? WHERE goal_id=?",
                (now, goal.goal_id),
            )
            conn.commit()
        return UserGoalProgressEntry(
            entry_id=entry_id,
            goal_id=goal.goal_id,
            content=clean_content,
            created_at=now,
            evidence_ref=clean_evidence,
            source=clean_source,
            routine_id=routine_id,
            routine_run_id=routine_run_id,
        ).to_dict()

    def record_background_progress(
        self,
        goal_id: str,
        content: str,
        *,
        routine_context: Mapping[str, Any] | None,
        evidence_ref: str | None = None,
    ) -> dict:
        """The ONLY background entry point for goal progress.

        ``routine_context`` must describe a real scheduled-task run, e.g.
        ``{"source": "routine", "routine_id": ..., "routine_run_id": ...}``
        as produced by the routines layer. A direct background write
        without such a context — or with a context that does not match a
        real routine run — is rejected with ``PermissionError`` and
        writes nothing.
        """
        _source, _routine_id, _run_id = self._validate_routine_context(
            routine_context
        )
        return self.add_progress(
            goal_id,
            content,
            evidence_ref=evidence_ref,
            source=_source,
            routine_context=routine_context,
        )

    # -- completion / archiving: never delete -------------------------------

    def complete_goal(self, goal_id: str) -> dict:
        """Complete a goal: status -> completed, stamped as archived.

        The goal and all its progress entries stay queryable. Completing
        an already-completed goal is idempotent; completing an archived
        (shelved) goal is rejected — archive is a terminal shelf state.
        """
        goal = self._require(goal_id)
        if goal.status == "completed":
            return self.snapshot(goal_id)
        if goal.status == "archived":
            raise ValueError(
                f"cannot complete an archived goal: {goal.goal_id}"
            )
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_user_goals
                SET status='completed',completed_at=?,archived_at=?,
                    updated_at=?
                WHERE goal_id=? AND status='active'
                """,
                (now, now, now, goal.goal_id),
            )
            conn.commit()
        return self.snapshot(goal_id)

    def archive_goal(self, goal_id: str) -> dict:
        """Shelve a goal without completing it: status -> archived.

        Like completion, archiving never deletes anything. Archiving an
        already-archived goal is idempotent.
        """
        goal = self._require(goal_id)
        if goal.status == "archived":
            return self.snapshot(goal_id)
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_user_goals
                SET status='archived',archived_at=?,updated_at=?
                WHERE goal_id=?
                """,
                (now, now, goal.goal_id),
            )
            conn.commit()
        return self.snapshot(goal_id)

    # -- background-context enforcement ------------------------------------

    def _validate_routine_context(
        self, context: Mapping[str, Any] | None
    ) -> tuple[str, str, str]:
        """Prove a background write came through a real scheduled-task run.

        Raises ``PermissionError`` for a missing, malformed, or
        unverifiable context. When the resident has a routines manager,
        the routine id must exist and the run id must be one of that
        routine's recorded runs, so a caller cannot forge a context out
        of thin air. Without a routines manager (bare store), the
        shape check is the enforcement.
        """
        if not isinstance(context, Mapping):
            raise PermissionError(
                "background goal updates require a routine/scheduled-task "
                "context; got none. Background writes must go through the "
                "routines layer, not a direct call."
            )
        source = str(context.get("source") or "").strip().lower()
        if source not in BACKGROUND_SOURCES:
            raise PermissionError(
                "background goal updates require a routine/scheduled-task "
                f"context with source in {BACKGROUND_SOURCES}; got {source!r}"
            )
        routine_id = str(context.get("routine_id") or "").strip()
        routine_run_id = str(context.get("routine_run_id") or "").strip()
        if not routine_id or not routine_run_id:
            raise PermissionError(
                "background goal updates require a routine context with a "
                "non-empty routine_id and routine_run_id"
            )
        routines = getattr(self.resident, "routines", None)
        if routines is None:
            return source, routine_id, routine_run_id
        try:
            routine = routines.get(routine_id)
        except Exception as exc:
            raise PermissionError(
                "background goal update context could not be verified "
                f"against the routines layer: {type(exc).__name__}"
            ) from exc
        if routine is None:
            raise PermissionError(
                "background goal updates require a real routine: "
                f"unknown routine_id {routine_id!r}"
            )
        try:
            runs = routines.runs(routine_id)
        except Exception as exc:
            raise PermissionError(
                "background goal update context could not be verified "
                f"against the routines layer: {type(exc).__name__}"
            ) from exc
        if not any(
            str(run.get("run_id") or "") == routine_run_id
            for run in runs
            if isinstance(run, dict)
        ):
            raise PermissionError(
                "background goal updates require a real routine run: "
                f"unknown routine_run_id {routine_run_id!r} for routine "
                f"{routine_id!r}"
            )
        return source, routine_id, routine_run_id

    # -- internals -----------------------------------------------------------

    def _require(self, goal_id: str) -> UserGoal:
        goal = self.get(goal_id)
        if goal is None:
            raise KeyError(f"unknown user goal: {goal_id}")
        return goal

    def _entries(self, goal: UserGoal, *, limit: int = 1000) -> list[UserGoalProgressEntry]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM resident_user_goal_progress WHERE goal_id=? "
                "ORDER BY created_at ASC, entry_id ASC LIMIT ?",
                (goal.goal_id, max(1, min(10000, int(limit)))),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_user_goals(
                    goal_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_user_goals_status
                    ON resident_user_goals(status, updated_at);
                CREATE TABLE IF NOT EXISTS resident_user_goal_progress(
                    entry_id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence_ref TEXT,
                    source TEXT NOT NULL DEFAULT 'user',
                    routine_id TEXT,
                    routine_run_id TEXT,
                    FOREIGN KEY(goal_id) REFERENCES resident_user_goals(goal_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_goal_progress_goal
                    ON resident_user_goal_progress(goal_id, created_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _goal_from_row(row: sqlite3.Row) -> UserGoal:
        return UserGoal(
            goal_id=str(row["goal_id"]),
            title=str(row["title"]),
            description=str(row["description"] or ""),
            status=str(row["status"]),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            archived_at=str(row["archived_at"]) if row["archived_at"] else None,
        )

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> UserGoalProgressEntry:
        return UserGoalProgressEntry(
            entry_id=str(row["entry_id"]),
            goal_id=str(row["goal_id"]),
            content=str(row["content"]),
            created_at=str(row["created_at"] or ""),
            evidence_ref=str(row["evidence_ref"]) if row["evidence_ref"] else None,
            source=str(row["source"] or "user"),
            routine_id=str(row["routine_id"]) if row["routine_id"] else None,
            routine_run_id=str(row["routine_run_id"]) if row["routine_run_id"] else None,
        )


def install_user_goal_behavior(resident) -> None:
    """Attach durable user goals to the existing product Resident.

    Requires only the resident store. The routines manager is consulted
    (when present) to verify background-update contexts; it is not
    required for foreground use.
    """

    if getattr(resident, _INSTALL_MARKER, False):
        return
    if not hasattr(resident, "store"):
        raise ValueError("user goal behavior requires the existing resident store")

    manager = UserGoalManager(resident)
    original_status = resident.status

    def status():
        data = original_status()
        items = manager.list_goals(limit=500)
        data["user_goals"] = {
            "goal_count": len(items),
            "active_count": sum(1 for item in items if item.get("status") == "active"),
            "completed_count": sum(
                1 for item in items if item.get("status") == "completed"
            ),
            "archived_count": sum(
                1 for item in items if item.get("status") == "archived"
            ),
            "goals": items,
        }
        return data

    resident.user_goals = manager
    resident.status = status
    setattr(resident, _INSTALL_MARKER, True)


__all__ = [
    "BACKGROUND_SOURCES",
    "GOAL_STATUSES",
    "UserGoal",
    "UserGoalManager",
    "UserGoalProgressEntry",
    "install_user_goal_behavior",
]

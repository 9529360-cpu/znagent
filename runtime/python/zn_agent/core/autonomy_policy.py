from __future__ import annotations

"""User autonomy policy store (Q12).

Per-domain autonomy levels that bound how far ZN may act on its own:
which domains the user lets ZN merely observe, suggest about, prepare
for, execute reversibly in, or only touch with explicit approval.

Five levels, fail closed, default ``require_approval``:

* ``observe_only``       ZN may watch, never surface work on its own.
* ``suggest``            ZN may surface suggestions, never schedule/execute.
* ``prepare``            ZN may schedule and prepare, never execute.
* ``execute_reversible`` ZN may execute reversible actions on its own.
* ``require_approval``   ZN may schedule (materialize) but must ask before
                         any side effect. This is the default for every
                         domain: an unknown domain, a read failure, or an
                         unknown stored value all land here, so a broken
                         policy store never downgrades execution authority.

Only one materialize decision is wired in v1: the recurring-will
trigger organ's handoff (``recurring_will_behavior._handoff_pending``).
A trigger whose domain level sits below ``suggest`` (i.e.
``observe_only``) never materializes into Will's ``next_task``; the due
occurrence is routed to the P1-1 suggestion bar instead, reusing its
stable-key dedup and 7-day dismissal semantics (module
``suggestions``).

Domain naming reuses trigger kinds and connector names:

* ``recurring.interval`` / ``recurring.cron`` / ``recurring.file_changed``
* ``connector.weather`` / ``connector.web_search`` / ... (one per
  R-series connector name in ``connector_autoattach.CONNECTOR_REGISTRY``)

This module never touches ``store.py``: it keeps its own tables in the
same sqlite file through direct connections, following the additive
migration style of Q7 (``CREATE TABLE IF NOT EXISTS``; new tables need
no ``ALTER``).
"""

import logging
import re
import sqlite3
import threading
from contextlib import closing
from typing import Any

from .models import utc_now
from .suggestions import suggestion_key

_LOG = logging.getLogger(__name__)

OBSERVE_ONLY = "observe_only"
SUGGEST = "suggest"
PREPARE = "prepare"
EXECUTE_REVERSIBLE = "execute_reversible"
REQUIRE_APPROVAL = "require_approval"

AUTONOMY_LEVELS = (
    OBSERVE_ONLY,
    SUGGEST,
    PREPARE,
    EXECUTE_REVERSIBLE,
    REQUIRE_APPROVAL,
)
DEFAULT_LEVEL = REQUIRE_APPROVAL

# Materialize ladder for the recurring-will gate: the decision only
# distinguishes "this occurrence may become a Will next_task" from
# "route it to the suggestion bar". Only observe_only sits below
# suggest; require_approval still materializes (scheduling is not
# execution — the approval gate holds at execution time).
_MATERIALIZE_RANK = {
    OBSERVE_ONLY: 0,
    SUGGEST: 1,
    PREPARE: 2,
    EXECUTE_REVERSIBLE: 3,
    REQUIRE_APPROVAL: 3,
}

_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")

_GATED_OCCURRENCE_TTL_DAYS = 7


def normalize_level(level: Any) -> str:
    """Normalize a level value, failing closed to ``require_approval``."""
    text = str(level or "").strip().lower()
    if text in AUTONOMY_LEVELS:
        return text
    return REQUIRE_APPROVAL


def may_materialize_next_task(level: Any) -> bool:
    """Whether a domain at ``level`` may materialize into Will's next_task.

    Only ``observe_only`` is below ``suggest``; everything else
    materializes normally. Unknown values fail closed to
    ``require_approval``, which materializes (scheduling is not
    execution).
    """
    normalized = normalize_level(level)
    return _MATERIALIZE_RANK[normalized] >= _MATERIALIZE_RANK[SUGGEST]


def validate_domain(domain: Any) -> str:
    """Normalize and validate a policy domain name."""
    text = str(domain or "").strip().lower()
    if not text:
        raise ValueError("autonomy domain must not be empty")
    if "*" in text:
        raise ValueError(
            "autonomy domain must not contain wildcards; "
            "set one explicit domain at a time"
        )
    if not _DOMAIN_RE.match(text):
        raise ValueError(
            "autonomy domain must match [a-z0-9][a-z0-9_.:-]{0,127}"
        )
    return text


def autonomy_domain_for_trigger_kind(schedule_kind: Any) -> str:
    """Domain name for a recurring trigger kind (interval/cron/file_changed)."""
    kind = str(schedule_kind or "interval").strip().lower() or "interval"
    return validate_domain(f"recurring.{kind}")


def connector_domain(connector_name: Any) -> str:
    """Domain name for a connector (e.g. ``connector.weather``)."""
    return validate_domain(f"connector.{connector_name}")


class AutonomyPolicyStore:
    """Durable per-domain autonomy policy plus gated-occurrence outbox.

    The policy table is the user autonomy envelope. The gated-occurrence
    table is the outbox the recurring-will gate writes into when a due
    occurrence is held back: the P1-1 suggestion engine reads it as one
    more candidate source, so the occurrence gets the same stable-key
    dedup and dismissal suppression as every other suggestion.
    """

    def __init__(self, resident):
        self.resident = resident
        self.store = resident.store
        self._lock = threading.RLock()
        self._init_schema()

    # -- policy (read/write) -------------------------------------------

    def get_level(self, domain: Any) -> str:
        """Read-only query: autonomy level for a domain, fail closed.

        Unknown domains and any read failure return
        ``require_approval``: a broken policy store never widens what ZN
        may do on its own.
        """
        try:
            name = validate_domain(domain)
        except ValueError:
            return REQUIRE_APPROVAL
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT level FROM resident_autonomy_policy WHERE domain=?",
                    (name,),
                ).fetchone()
        except Exception:
            _LOG.warning(
                "autonomy policy unreadable; failing closed for domain %r",
                name,
                exc_info=True,
            )
            return REQUIRE_APPROVAL
        if row is None:
            return REQUIRE_APPROVAL
        return normalize_level(row["level"])

    def set_level(self, domain: Any, level: Any) -> dict[str, str]:
        """Set the autonomy level for a domain (user-owned write).

        The write is explicit and per-domain: wildcards are rejected and
        the level must be one of the five known levels. The previous
        level is captured first and both the change and an audit row are
        committed atomically, so every change stays traceable
        (who/what/when/old/new) without a separate approval card: the
        user typing the command on their own terminal is the approval.
        """
        name = validate_domain(domain)
        normalized = str(level or "").strip().lower()
        if normalized not in AUTONOMY_LEVELS:
            raise ValueError(
                f"unknown autonomy level: {level!r} "
                f"(expected one of {', '.join(AUTONOMY_LEVELS)})"
            )
        updated = utc_now()
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT level FROM resident_autonomy_policy WHERE domain=?",
                (name,),
            ).fetchone()
            old_level = (
                normalize_level(row["level"])
                if row is not None
                else REQUIRE_APPROVAL
            )
            conn.execute(
                """
                INSERT INTO resident_autonomy_policy(domain,level,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(domain) DO UPDATE SET
                    level=excluded.level,
                    updated_at=excluded.updated_at
                """,
                (name, normalized, updated),
            )
            conn.execute(
                """
                INSERT INTO resident_autonomy_policy_audit(
                    domain,old_level,new_level,changed_at
                ) VALUES(?,?,?,?)
                """,
                (name, old_level, normalized, updated),
            )
            conn.commit()
        return {
            "domain": name,
            "level": normalized,
            "old_level": old_level,
            "updated_at": updated,
        }

    def list_levels(self) -> list[dict[str, str]]:
        """Read-only query: every explicitly stored domain level."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT domain,level,updated_at "
                "FROM resident_autonomy_policy ORDER BY domain ASC"
            ).fetchall()
        return [
            {
                "domain": str(row["domain"]),
                "level": normalize_level(row["level"]),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def list_policy_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read-only query: autonomy level changes, newest first.

        The audit trail for the autonomy envelope: every ``set_level``
        call lands here atomically with its write, so a change is
        always traceable after the fact.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT domain,old_level,new_level,changed_at
                FROM resident_autonomy_policy_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [
            {
                "domain": str(row["domain"]),
                "old_level": normalize_level(row["old_level"]),
                "new_level": normalize_level(row["new_level"]),
                "changed_at": str(row["changed_at"] or ""),
            }
            for row in rows
        ]

    # -- gated occurrences (outbox to the suggestion bar) ---------------

    def record_gated_occurrence(
        self,
        *,
        intention_id: str,
        task: str,
        domain: str,
        level: str,
        scheduled_at: str,
    ) -> str:
        """Durably record one gated due occurrence for the suggestion bar.

        The suggestion key is stable per occurrence (intention + task +
        scheduled instant), so a retry never pushes a duplicate and a
        dismissal suppresses exactly this occurrence. Returns the key.
        """
        clean_task = str(task or "").strip()
        if not clean_task:
            raise ValueError("gated occurrence task must not be empty")
        stamp = str(scheduled_at or "").strip()
        if not stamp:
            raise ValueError("gated occurrence scheduled_at must not be empty")
        key = suggestion_key(
            "autonomy_gated",
            str(intention_id or "").strip(),
            f"{clean_task}\x00{stamp}",
        )
        created = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO resident_autonomy_gated_occurrences(
                    suggestion_key,task,intention_id,domain,level,
                    scheduled_at,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    key,
                    clean_task,
                    str(intention_id or "").strip(),
                    validate_domain(domain),
                    normalize_level(level),
                    stamp,
                    created,
                ),
            )
            conn.commit()
        return key

    def list_gated_occurrences(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read-only query: gated occurrences awaiting the suggestion bar."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT suggestion_key,task,intention_id,domain,level,
                       scheduled_at,created_at
                FROM resident_autonomy_gated_occurrences
                ORDER BY scheduled_at ASC,intention_id ASC
                LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [
            {
                "suggestion_key": str(row["suggestion_key"]),
                "task": str(row["task"]),
                "intention_id": str(row["intention_id"]),
                "domain": str(row["domain"]),
                "level": str(row["level"]),
                "scheduled_at": str(row["scheduled_at"]),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def prune_gated_occurrences(self, *, before_iso: str) -> int:
        """Delete gated occurrences created at or before ``before_iso``."""
        with self._lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM resident_autonomy_gated_occurrences "
                "WHERE created_at <= ?",
                (str(before_iso),),
            )
            conn.commit()
            return max(0, int(cursor.rowcount or 0))

    # -- schema ----------------------------------------------------------

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_autonomy_policy(
                    domain TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resident_autonomy_gated_occurrences(
                    suggestion_key TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    intention_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    level TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_autonomy_gated_scheduled
                    ON resident_autonomy_gated_occurrences(scheduled_at);
                CREATE TABLE IF NOT EXISTS resident_autonomy_policy_audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    old_level TEXT NOT NULL,
                    new_level TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_autonomy_policy_audit_domain
                    ON resident_autonomy_policy_audit(domain, id);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

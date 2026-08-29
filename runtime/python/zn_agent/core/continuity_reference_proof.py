from __future__ import annotations

"""Privacy-preserving complete reference proofs for resident continuity.

A resident is allowed to keep living while continuity is checked. Therefore a
candidate may add durable state or advance mutable status fields after restart.
The proofs below hash baseline entities and immutable content independently so a
comparator can require baseline hashes to survive as a subset of candidate
hashes. This deliberately favors correctness over constant evidence size: there
is no 100/256 logical ceiling, and private Work/memory/intention text is never
exported in plaintext.
"""

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

_PROOF_ALGORITHM = "sha256"
_PROOF_DOMAIN = b"zn-continuity-reference-proof-v2\x00"


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=5.0)


def _update_value(digest, value: Any) -> None:
    if value is None:
        digest.update(b"N")
        return
    encoded = str(value).encode("utf-8", errors="replace")
    digest.update(b"V")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _leaf_hash(domain: str, section: str, row: Sequence[Any]) -> str:
    digest = hashlib.sha256()
    digest.update(_PROOF_DOMAIN)
    _update_value(digest, domain)
    _update_value(digest, section)
    digest.update(len(row).to_bytes(4, "big"))
    for value in row:
        _update_value(digest, value)
    return digest.hexdigest()


def _reference_proof(
    domain: str,
    sections: Sequence[tuple[str, Sequence[Sequence[Any]]]],
) -> dict[str, Any]:
    hashes: list[str] = []
    section_counts: dict[str, int] = {}
    for name, rows in sections:
        section_counts[name] = len(rows)
        hashes.extend(_leaf_hash(domain, name, row) for row in rows)
    hashes.sort()
    aggregate = hashlib.sha256()
    aggregate.update(_PROOF_DOMAIN)
    _update_value(aggregate, domain)
    for value in hashes:
        _update_value(aggregate, value)
    return {
        "algorithm": _PROOF_ALGORITHM,
        "count": len(hashes),
        "section_counts": section_counts,
        "digest": aggregate.hexdigest(),
        "reference_hashes": hashes,
    }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _rows(conn: sqlite3.Connection, table: str, columns: str, order_by: str) -> list[sqlite3.Row]:
    if not _table_exists(conn, table):
        return []
    return conn.execute(f"SELECT {columns} FROM {table} ORDER BY {order_by} ASC").fetchall()


def _protected_side_effect_attempt_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return attempts whose disappearance would violate replay/recovery safety.

    The persistence owner intentionally capacity-prunes non-started attempt
    history only after both a terminal event row and its EventOutcome are
    durable. Those rows are historical diagnostics, not permanent continuity
    identity. Everything else remains protected, including every ``started``
    attempt and observed/recovery-verified attempts whose owner is not terminal.
    """

    if not _table_exists(conn, "resident_side_effect_attempts"):
        return []
    if not (_table_exists(conn, "events") and _table_exists(conn, "event_outcomes")):
        return conn.execute(
            "SELECT attempt_id,event_id,signature_hash,kind,started_at "
            "FROM resident_side_effect_attempts ORDER BY attempt_id ASC"
        ).fetchall()
    return conn.execute(
        "SELECT attempt.attempt_id,attempt.event_id,attempt.signature_hash,"
        "attempt.kind,attempt.started_at "
        "FROM resident_side_effect_attempts AS attempt "
        "WHERE attempt.status='started' OR NOT EXISTS ("
        "SELECT 1 FROM events AS event "
        "JOIN event_outcomes AS outcome ON outcome.event_id=event.event_id "
        "WHERE event.event_id=attempt.event_id "
        "AND event.status IN ('completed','failed')) "
        "ORDER BY attempt.attempt_id ASC"
    ).fetchall()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity_anchor_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    if not _table_exists(conn, "identity"):
        return []
    row = conn.execute("SELECT data FROM identity WHERE id=1").fetchone()
    if row is None:
        return []
    raw = json.loads(row[0])
    return [(
        raw.get("name"),
        raw.get("purpose"),
        _canonical_json(raw.get("principles") or []),
        raw.get("created_at"),
    )]


def _living_self_anchor_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    if not _table_exists(conn, "living_self"):
        return []
    row = conn.execute("SELECT data FROM living_self WHERE id=1").fetchone()
    if row is None:
        return []
    raw = json.loads(row[0])
    return [(raw.get("name"), raw.get("born_at"))]


def _resident_intention_anchor_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    if not _table_exists(conn, "resident_intentions"):
        return []
    rows = conn.execute(
        "SELECT intention_id,data FROM resident_intentions ORDER BY intention_id ASC"
    ).fetchall()
    anchors: list[tuple[Any, ...]] = []
    for row in rows:
        raw = json.loads(row[1])
        anchors.append((
            row[0],
            raw.get("description"),
            raw.get("source"),
            raw.get("created_at"),
        ))
    return anchors


def _world_focus_anchor_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    if not _table_exists(conn, "world_focuses"):
        return []
    rows = conn.execute("SELECT focus_id,data FROM world_focuses ORDER BY focus_id ASC").fetchall()
    anchors: list[tuple[Any, ...]] = []
    for row in rows:
        raw = json.loads(row[1])
        anchors.append((
            row[0],
            raw.get("topic"),
            int(raw.get("priority") or 0),
            int(raw.get("interval_seconds") or 0),
            1 if bool(raw.get("enabled", True)) else 0,
            raw.get("source"),
            raw.get("created_at"),
        ))
    return anchors


def resident_state_proof(path: str | Path) -> dict[str, Any]:
    """Hash durable resident entities using fields that must survive progress.

    Mutable execution state (status, checkpoints, counters, freshness, repair
    timestamps, current thought/body and similar fields) is intentionally not a
    leaf identity. Losing a durable entity changes the candidate set; normal
    completion or recovery can advance without invalidating the baseline.

    Completion-observation journal rows are resident recovery obligations. Their
    status, attempts and errors may advance, but the stable ``(event_id, stage)``
    identity must survive so an already-terminal event cannot silently lose the
    Life observation owed to it.
    """

    with closing(_open_read_only(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        sections = (
            ("identity_anchor", _identity_anchor_rows(conn)),
            ("living_self_anchor", _living_self_anchor_rows(conn)),
            ("world_focus_anchors", _world_focus_anchor_rows(conn)),
            ("resident_intention_anchors", _resident_intention_anchor_rows(conn)),
            ("resident_event_accounting", _rows(conn, "resident_event_accounting", "event_id,kind,created_at", "event_id,kind")),
            ("goals", _rows(conn, "goals", "goal_id", "goal_id")),
            ("experiences", _rows(conn, "experiences", "experience_id,goal_id", "experience_id")),
            ("capabilities", _rows(conn, "capabilities", "name", "name")),
            ("proposals", _rows(conn, "proposals", "proposal_id,goal_id", "proposal_id")),
            ("events", _rows(conn, "events", "event_id,created_at", "event_id")),
            ("event_outcomes", _rows(conn, "event_outcomes", "event_id,created_at", "event_id")),
            ("facts", _rows(conn, "facts", "fact_key,created_at", "fact_key")),
            ("side_effect_attempts", _protected_side_effect_attempt_rows(conn)),
            ("completion_observations", _rows(conn, "resident_completion_observations", "event_id,stage", "event_id,stage")),
            ("life_impasses", _rows(conn, "life_impasses", "impasse_id,event_id", "impasse_id")),
            ("life_learning_candidates", _rows(conn, "life_learning_candidates", "candidate_id,source_impasse_id,created_at", "candidate_id")),
        )
        proof = _reference_proof("resident-durable-state", sections)
        conn.rollback()
    return proof


def long_lived_neural_reference_proof(path: str | Path) -> dict[str, Any]:
    """Hash identities that normal nervous-system consolidation must retain."""

    with closing(_open_read_only(path)) as conn:
        if _table_exists(conn, "neural_traces"):
            rows = conn.execute(
                "SELECT trace_id FROM neural_traces "
                "WHERE channel='schema' OR repetitions>1 ORDER BY trace_id ASC"
            ).fetchall()
        else:
            rows = []
    return _reference_proof("long-lived-neural-references", (("neural_traces", rows),))


def work_state_proof(path: str | Path) -> dict[str, Any]:
    """Hash every durable Work entity and immutable payload that must survive.

    Thread presentation metadata and run ledger status may legitimately advance;
    message/artifact payloads are immutable evidence and therefore participate in
    their leaves.
    """

    with closing(_open_read_only(path)) as conn:
        conn.execute("BEGIN")
        threads = conn.execute(
            "SELECT thread_id,created_at FROM work_threads ORDER BY thread_id ASC"
        ).fetchall()
        messages = conn.execute(
            "SELECT message_id,thread_id,role,text,detail_json,created_at "
            "FROM work_messages ORDER BY message_id ASC"
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_id,thread_id,event_id,kind,name,path,content,metadata_json,created_at "
            "FROM work_artifacts ORDER BY artifact_id ASC"
        ).fetchall()
        runs = conn.execute(
            "SELECT event_id,thread_id,message_id,task,created_at "
            "FROM work_runs ORDER BY event_id ASC"
        ).fetchall()
        proof = _reference_proof(
            "work-state",
            (
                ("work_threads", threads),
                ("work_messages", messages),
                ("work_artifacts", artifacts),
                ("work_runs", runs),
            ),
        )
        conn.rollback()
    return {
        **proof,
        "thread_count": len(threads),
    }


def verified_experience_reference_proof(path: str | Path) -> dict[str, Any]:
    """Hash every retained causal-learning experience identifier."""

    with closing(_open_read_only(path)) as conn:
        rows = conn.execute(
            "SELECT experience_id FROM verified_experiences ORDER BY experience_id ASC"
        ).fetchall()
    return _reference_proof("verified-experiences", (("verified_experiences", rows),))

from __future__ import annotations

"""Constant-size proofs for resident-owned continuity state.

The proofs commit to durable state without exporting Work text, artifact
content, resident memory payloads, intention descriptions, or individual
learning identifiers. Exact proofs are used only for state that must remain
stable across a controlled restart; mutable neural plasticity is represented by
stable long-lived trace identities instead of mutable weights or timestamps.
"""

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

_PROOF_ALGORITHM = "sha256"
_PROOF_DOMAIN = b"zn-continuity-state-proof-v1\x00"


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


def _proof(domain: str, sections: Sequence[tuple[str, Sequence[Sequence[Any]]]]) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(_PROOF_DOMAIN)
    _update_value(digest, domain)
    total_rows = 0
    section_counts: dict[str, int] = {}
    for name, rows in sections:
        _update_value(digest, name)
        digest.update(len(rows).to_bytes(8, "big"))
        section_counts[name] = len(rows)
        total_rows += len(rows)
        for row in rows:
            digest.update(len(row).to_bytes(4, "big"))
            for value in row:
                _update_value(digest, value)
    return {
        "algorithm": _PROOF_ALGORITHM,
        "row_count": total_rows,
        "section_counts": section_counts,
        "digest": digest.hexdigest(),
    }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _rows(conn: sqlite3.Connection, table: str, columns: str, order_by: str) -> list[sqlite3.Row]:
    if not _table_exists(conn, table):
        return []
    return conn.execute(
        f"SELECT {columns} FROM {table} ORDER BY {order_by} ASC"
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
    """Return first-person fields that must survive while excluding wake volatility."""

    if not _table_exists(conn, "living_self"):
        return []
    row = conn.execute("SELECT data FROM living_self WHERE id=1").fetchone()
    if row is None:
        return []
    raw = json.loads(row[0])
    current_impasse = raw.get("current_impasse")
    impasse_id = (
        current_impasse.get("impasse_id")
        if isinstance(current_impasse, dict)
        else None
    )
    return [(
        raw.get("name"),
        raw.get("born_at"),
        _canonical_json(raw.get("open_questions") or []),
        impasse_id,
        _canonical_json(raw.get("learning_candidates") or []),
        raw.get("last_event_id"),
        raw.get("last_action_summary"),
    )]


def resident_state_proof(path: str | Path) -> dict[str, Any]:
    """Commit to stable resident-owned durable state across a controlled restart.

    Lifecycle-volatile state is intentionally excluded: resident leases, runtime
    metrics, pulse/situation/thought history, wake-derived LivingState fields and
    mutable nervous-system weights. Durable Will and event-accounting journals
    are included because losing either can erase intention or duplicate semantic
    accounting after recovery.
    """

    with closing(_open_read_only(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        sections = (
            ("identity_anchor", _identity_anchor_rows(conn)),
            ("living_self_anchor", _living_self_anchor_rows(conn)),
            ("resident_intentions", _rows(conn, "resident_intentions", "intention_id,status,priority,updated_at,data", "intention_id")),
            ("resident_event_accounting", _rows(conn, "resident_event_accounting", "event_id,kind,created_at", "event_id,kind")),
            ("goals", _rows(conn, "goals", "goal_id,data", "goal_id")),
            ("experiences", _rows(conn, "experiences", "experience_id,goal_id,data", "experience_id")),
            ("capabilities", _rows(conn, "capabilities", "name,data", "name")),
            ("proposals", _rows(conn, "proposals", "proposal_id,goal_id,data", "proposal_id")),
            ("events", _rows(conn, "events", "event_id,status,priority,created_at,data", "event_id")),
            ("event_outcomes", _rows(conn, "event_outcomes", "event_id,created_at,data", "event_id")),
            ("working_state", _rows(conn, "working_state", "id,data", "id")),
            ("facts", _rows(conn, "facts", "fact_key,value_json,aliases_json,created_at,updated_at", "fact_key")),
            ("side_effect_attempts", _rows(conn, "resident_side_effect_attempts", "attempt_id,event_id,signature_hash,kind,status,started_at,completed_at,result_action_id,result_success", "attempt_id")),
            ("life_impasses", _rows(conn, "life_impasses", "impasse_id,event_id,status,updated_at,data", "impasse_id")),
            ("life_learning_candidates", _rows(conn, "life_learning_candidates", "candidate_id,source_impasse_id,created_at,status,data", "candidate_id")),
        )
        proof = _proof("resident-stable-state", sections)
        conn.rollback()
    return {
        **proof,
        "count": proof["row_count"],
    }


def long_lived_neural_reference_proof(path: str | Path) -> dict[str, Any]:
    """Commit to neural trace identities normal consolidation must retain.

    Schema traces are never pruned by the current consolidation policy and
    repeated traces (repetitions > 1) are likewise outside its pruning rule.
    Their mutable strengths, salience, activation timestamps and metadata are
    deliberately not hashed, because heartbeat/consolidation may legitimately
    evolve those values during a restart.
    """

    with closing(_open_read_only(path)) as conn:
        if _table_exists(conn, "neural_traces"):
            rows = conn.execute(
                "SELECT trace_id FROM neural_traces "
                "WHERE channel='schema' OR repetitions>1 ORDER BY trace_id ASC"
            ).fetchall()
        else:
            rows = []
    proof = _proof("long-lived-neural-references", (("neural_traces", rows),))
    return {
        **proof,
        "count": len(rows),
    }


def work_state_proof(path: str | Path) -> dict[str, Any]:
    """Commit to all durable Work rows while exporting only counts and a digest."""

    with closing(_open_read_only(path)) as conn:
        conn.execute("BEGIN")
        threads = conn.execute(
            "SELECT thread_id,title,metadata_json,created_at,updated_at "
            "FROM work_threads ORDER BY thread_id ASC"
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
            "SELECT event_id,thread_id,message_id,task,ledger_state,created_at,updated_at,finalized_at "
            "FROM work_runs ORDER BY event_id ASC"
        ).fetchall()
        proof = _proof(
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
        "count": len(threads),
    }


def verified_experience_reference_proof(path: str | Path) -> dict[str, Any]:
    """Commit to every retained causal-learning experience identifier."""

    with closing(_open_read_only(path)) as conn:
        rows = conn.execute(
            "SELECT experience_id FROM verified_experiences ORDER BY experience_id ASC"
        ).fetchall()
    proof = _proof("verified-experiences", (("verified_experiences", rows),))
    return {
        **proof,
        "count": len(rows),
    }

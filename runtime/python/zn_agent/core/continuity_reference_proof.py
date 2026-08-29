from __future__ import annotations

"""Constant-size proofs for resident-owned continuity state.

The proofs commit to complete durable state without exporting Work text,
artifact content, run details, or individual learning identifiers. They are
exact rather than probabilistic: continuity must never accept a false positive
because a sampled or Bloom-filter representation collided.
"""

import hashlib
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

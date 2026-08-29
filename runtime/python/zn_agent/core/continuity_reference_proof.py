from __future__ import annotations

"""Constant-size proofs for resident-owned continuity reference sets.

The proof commits to the complete retained reference set without exporting
individual Work or learning identifiers. It is intentionally exact rather than
probabilistic: a continuity verifier must never accept a false positive merely
because a sampled or Bloom-filter representation collided.
"""

import hashlib
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

_PROOF_ALGORITHM = "sha256"
_PROOF_DOMAIN = b"zn-continuity-reference-proof-v1\x00"


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=5.0)


def _proof(domain: str, rows: Iterable[Sequence[Any]]) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(_PROOF_DOMAIN)
    digest.update(domain.encode("utf-8", errors="strict"))
    digest.update(b"\x00")
    count = 0
    for row in rows:
        count += 1
        digest.update(len(row).to_bytes(4, "big"))
        for value in row:
            encoded = str(value).encode("utf-8", errors="replace")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return {
        "algorithm": _PROOF_ALGORITHM,
        "count": count,
        "digest": digest.hexdigest(),
    }


def work_reference_proof(path: str | Path) -> dict[str, Any]:
    """Commit to every durable Work thread reference and its birth timestamp."""

    with closing(_open_read_only(path)) as conn:
        rows = conn.execute(
            "SELECT thread_id, created_at FROM work_threads "
            "ORDER BY thread_id ASC, created_at ASC"
        ).fetchall()
    return _proof("work-threads", rows)


def verified_experience_reference_proof(path: str | Path) -> dict[str, Any]:
    """Commit to every retained causal-learning experience identifier."""

    with closing(_open_read_only(path)) as conn:
        rows = conn.execute(
            "SELECT experience_id FROM verified_experiences ORDER BY experience_id ASC"
        ).fetchall()
    return _proof("verified-experiences", rows)

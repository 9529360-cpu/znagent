from __future__ import annotations

"""Privacy-preserving continuity proof for atomic overwrite recovery authority.

Prepared-only protocols have not crossed the durable side-effect boundary and
may be reconstructed from the resident intent. Once a stage is durable, the
protocol is recovery authority: it may only advance monotonically or disappear
when exact durable evidence proves that authority was discharged.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

_PROOF_VERSION = 1
_ALGORITHM = "sha256"
_DOMAIN = b"zn-atomic-overwrite-continuity-v1\x00"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_VALID_STRATEGIES = frozenset({"replace_file_with_backup", "move_new_no_replace"})
_DISCHARGE_WITNESS_LIMIT = 4096


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=5.0)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _update_value(digest, value: Any) -> None:
    if value is None:
        digest.update(b"N")
        return
    encoded = str(value).encode("utf-8", errors="replace")
    digest.update(b"V")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _hash_reference(kind: str, *values: Any) -> str:
    digest = hashlib.sha256()
    digest.update(_DOMAIN)
    _update_value(digest, kind)
    for value in values:
        _update_value(digest, value)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _attempt_hash(event_id: Any, attempt_id: Any) -> str:
    return _hash_reference("attempt", event_id, attempt_id)


def _event_hash(event_id: Any) -> str:
    return _hash_reference("event", event_id)


def _safe_snapshot_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": value.get("version"),
        "algorithm": value.get("algorithm"),
        "protocol_count": value.get("protocol_count"),
        "protocols": value.get("protocols"),
        "verified_attempt_hashes": value.get("verified_attempt_hashes"),
        "native_completion_attempt_hashes": value.get("native_completion_attempt_hashes"),
        "terminal_event_hashes": value.get("terminal_event_hashes"),
    }


def _snapshot_digest(value: Mapping[str, Any]) -> str:
    return _hash_reference("snapshot", _canonical_json(_safe_snapshot_payload(value)))


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError(f"atomic overwrite continuity found empty {label}")
    return text


def _strict_flag(value: Any, label: str) -> bool:
    if type(value) is not int or value not in {0, 1}:
        raise RuntimeError(f"atomic overwrite continuity found invalid {label}")
    return value == 1


def _protocol_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "resident_atomic_overwrite_protocols"):
        return []
    rows = conn.execute(
        "SELECT event_id,signature_hash,version,intent_id,attempt_id,"
        "staging_path,backup_path,stage_ready,stage_identity_json,"
        "namespace_commit_started,write_strategy "
        "FROM resident_atomic_overwrite_protocols "
        "ORDER BY event_id ASC,signature_hash ASC"
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        event_id = _nonempty(row[0], "protocol event id")
        signature_hash = _nonempty(row[1], "protocol signature")
        try:
            version = int(row[2])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("atomic overwrite continuity found invalid protocol version") from exc
        if version <= 0:
            raise RuntimeError("atomic overwrite continuity found invalid protocol version")
        intent_id = _nonempty(row[3], "protocol intent id")
        staging_path = _nonempty(row[5], "protocol staging path")
        backup_path = _nonempty(row[6], "protocol backup path")
        stage_ready = _strict_flag(row[7], "stage_ready flag")
        commit_started = _strict_flag(row[9], "namespace_commit_started flag")
        attempt_raw = str(row[4] or "").strip()
        stage_identity_raw = str(row[8] or "").strip()
        strategy = str(row[10] or "").strip() or None

        if not stage_ready:
            if commit_started or attempt_raw or stage_identity_raw or strategy is not None:
                raise RuntimeError(
                    "atomic overwrite continuity found mutated prepared-only protocol"
                )
            continue

        attempt_id = _nonempty(attempt_raw, "protocol attempt id")
        if not stage_identity_raw:
            raise RuntimeError("atomic overwrite continuity found missing stage identity")
        try:
            stage_identity = json.loads(stage_identity_raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "atomic overwrite continuity found malformed stage identity"
            ) from exc
        if not isinstance(stage_identity, dict):
            raise RuntimeError("atomic overwrite continuity stage identity must be an object")

        stage_rank = 2 if commit_started else 1
        if stage_rank == 1 and strategy is not None:
            raise RuntimeError(
                "atomic overwrite continuity found strategy before namespace commit"
            )
        if stage_rank == 2 and strategy not in _VALID_STRATEGIES:
            raise RuntimeError(
                "atomic overwrite continuity found unsupported commit strategy"
            )

        result.append(
            {
                "reference_hash": _hash_reference(
                    "protocol",
                    version,
                    event_id,
                    signature_hash,
                    intent_id,
                    attempt_id,
                    staging_path,
                    backup_path,
                ),
                "attempt_hash": _attempt_hash(event_id, attempt_id),
                "event_hash": _event_hash(event_id),
                "stage_rank": stage_rank,
                "stage_identity_hash": _hash_reference(
                    "stage-identity", _canonical_json(stage_identity)
                ),
                "write_strategy": strategy,
            }
        )
    result.sort(key=lambda item: item["reference_hash"])
    return result


def _verified_attempt_hashes(conn: sqlite3.Connection) -> list[str]:
    if not _table_exists(conn, "resident_side_effect_attempts"):
        return []
    rows = conn.execute(
        "SELECT event_id,attempt_id FROM resident_side_effect_attempts "
        "WHERE status IN ('verified_effect','verified_absent') "
        "ORDER BY COALESCE(completed_at,started_at) DESC,started_at DESC,attempt_id DESC "
        "LIMIT ?",
        (_DISCHARGE_WITNESS_LIMIT,),
    ).fetchall()
    return sorted({_attempt_hash(row[0], row[1]) for row in rows})


def _terminal_event_hashes(conn: sqlite3.Connection) -> list[str]:
    if not (_table_exists(conn, "events") and _table_exists(conn, "event_outcomes")):
        return []
    rows = conn.execute(
        "SELECT event.event_id FROM events AS event "
        "JOIN event_outcomes AS outcome ON outcome.event_id=event.event_id "
        "WHERE event.status IN ('completed','failed') "
        "ORDER BY outcome.created_at DESC,event.event_id DESC LIMIT ?",
        (_DISCHARGE_WITNESS_LIMIT,),
    ).fetchall()
    return sorted({_event_hash(row[0]) for row in rows})


def _native_completion_attempt_hashes(conn: sqlite3.Connection) -> list[str]:
    if not _table_exists(conn, "working_state"):
        return []
    row = conn.execute("SELECT data FROM working_state WHERE id=1").fetchone()
    if row is None:
        return []
    try:
        state = json.loads(str(row[0] or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(state, dict) or str(state.get("stage") or "") != "native_completion":
        return []
    event_id = str(state.get("current_event_id") or "").strip()
    data = state.get("data")
    action_result = data.get("native_action_result") if isinstance(data, dict) else None
    result_data = action_result.get("data") if isinstance(action_result, dict) else None
    attempt_id = (
        str(result_data.get("side_effect_attempt_id") or "").strip()
        if isinstance(result_data, dict)
        else ""
    )
    if (
        not event_id
        or not attempt_id
        or not isinstance(action_result, dict)
        or action_result.get("success") is not True
        or not isinstance(data.get("native_completion"), dict)
    ):
        return []
    return [_attempt_hash(event_id, attempt_id)]


def atomic_overwrite_recovery_snapshot(path: str | Path) -> dict[str, Any]:
    """Return sanitized atomic overwrite recovery authority and bounded discharge truth."""

    with closing(_open_read_only(path)) as conn:
        conn.execute("BEGIN")
        protocols = _protocol_rows(conn)
        result: dict[str, Any] = {
            "version": _PROOF_VERSION,
            "algorithm": _ALGORITHM,
            "protocol_count": len(protocols),
            "protocols": protocols,
            "verified_attempt_hashes": _verified_attempt_hashes(conn),
            "native_completion_attempt_hashes": _native_completion_attempt_hashes(conn),
            "terminal_event_hashes": _terminal_event_hashes(conn),
        }
        result["digest"] = _snapshot_digest(result)
        conn.rollback()
    return result


def _hash_list(
    value: Any,
    *,
    max_length: int | None = None,
) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    if max_length is not None and len(value) > max_length:
        return None
    hashes = tuple(str(item) for item in value)
    if len(set(hashes)) != len(hashes):
        return None
    if any(_SHA256_RE.fullmatch(item) is None for item in hashes):
        return None
    return hashes


def _parse_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if set(value) != {
        "version",
        "algorithm",
        "protocol_count",
        "protocols",
        "verified_attempt_hashes",
        "native_completion_attempt_hashes",
        "terminal_event_hashes",
        "digest",
    }:
        return None
    if value.get("version") != _PROOF_VERSION or value.get("algorithm") != _ALGORITHM:
        return None
    count = value.get("protocol_count")
    protocols_raw = value.get("protocols")
    digest = str(value.get("digest") or "")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        or not isinstance(protocols_raw, list)
        or len(protocols_raw) != count
        or _SHA256_RE.fullmatch(digest) is None
    ):
        return None

    protocols: dict[str, dict[str, Any]] = {}
    for raw in protocols_raw:
        if not isinstance(raw, Mapping) or set(raw) != {
            "reference_hash",
            "attempt_hash",
            "event_hash",
            "stage_rank",
            "stage_identity_hash",
            "write_strategy",
        }:
            return None
        reference_hash = str(raw.get("reference_hash") or "")
        attempt_hash = str(raw.get("attempt_hash") or "")
        event_hash = str(raw.get("event_hash") or "")
        stage_identity_hash = str(raw.get("stage_identity_hash") or "")
        if any(
            _SHA256_RE.fullmatch(item) is None
            for item in (reference_hash, attempt_hash, event_hash, stage_identity_hash)
        ):
            return None
        rank = raw.get("stage_rank")
        strategy = raw.get("write_strategy")
        if isinstance(rank, bool) or rank not in {1, 2}:
            return None
        if rank == 1 and strategy is not None:
            return None
        if rank == 2 and strategy not in _VALID_STRATEGIES:
            return None
        if reference_hash in protocols:
            return None
        protocols[reference_hash] = {
            "reference_hash": reference_hash,
            "attempt_hash": attempt_hash,
            "event_hash": event_hash,
            "stage_rank": rank,
            "stage_identity_hash": stage_identity_hash,
            "write_strategy": strategy,
        }

    verified = _hash_list(
        value.get("verified_attempt_hashes"),
        max_length=_DISCHARGE_WITNESS_LIMIT,
    )
    native_completion = _hash_list(
        value.get("native_completion_attempt_hashes"),
        max_length=1,
    )
    terminal = _hash_list(
        value.get("terminal_event_hashes"),
        max_length=_DISCHARGE_WITNESS_LIMIT,
    )
    if verified is None or native_completion is None or terminal is None:
        return None
    if _snapshot_digest(value) != digest:
        return None
    return {
        "protocols": protocols,
        "verified_attempt_hashes": frozenset(verified),
        "native_completion_attempt_hashes": frozenset(native_completion),
        "terminal_event_hashes": frozenset(terminal),
    }


def compare_atomic_overwrite_recovery(before: Any, after: Any) -> list[dict[str, Any]]:
    """Block recovery-authority loss, regression, or immutable protocol rewrite."""

    if before is None:
        return []
    old = _parse_snapshot(before)
    new = _parse_snapshot(after)
    if old is None or new is None:
        return [
            {
                "kind": "atomic_overwrite_recovery_continuity_unproven",
                "reason": "atomic overwrite recovery proof is invalid or missing",
            }
        ]

    blockers: list[dict[str, Any]] = []
    candidate_protocols = new["protocols"]
    for reference_hash, prior in old["protocols"].items():
        current = candidate_protocols.get(reference_hash)
        if current is None:
            if not (
                prior["attempt_hash"] in new["verified_attempt_hashes"]
                or prior["attempt_hash"] in new["native_completion_attempt_hashes"]
                or prior["event_hash"] in new["terminal_event_hashes"]
            ):
                blockers.append(
                    {
                        "kind": "atomic_overwrite_recovery_protocol_lost",
                        "missing_protocol_count": 1,
                        "before_stage_rank": prior["stage_rank"],
                    }
                )
            continue

        if (
            current["attempt_hash"] != prior["attempt_hash"]
            or current["event_hash"] != prior["event_hash"]
        ):
            blockers.append(
                {
                    "kind": "atomic_overwrite_recovery_continuity_unproven",
                    "reason": "protocol owner reference changed",
                }
            )
            continue
        if current["stage_identity_hash"] != prior["stage_identity_hash"]:
            blockers.append(
                {
                    "kind": "atomic_overwrite_recovery_stage_identity_changed",
                    "before_stage_rank": prior["stage_rank"],
                    "after_stage_rank": current["stage_rank"],
                }
            )
            continue
        if current["stage_rank"] < prior["stage_rank"]:
            blockers.append(
                {
                    "kind": "atomic_overwrite_recovery_stage_regressed",
                    "before_stage_rank": prior["stage_rank"],
                    "after_stage_rank": current["stage_rank"],
                }
            )
            continue
        if (
            prior["stage_rank"] == 2
            and current["write_strategy"] != prior["write_strategy"]
        ):
            blockers.append(
                {
                    "kind": "atomic_overwrite_recovery_strategy_changed",
                    "before_stage_rank": prior["stage_rank"],
                    "after_stage_rank": current["stage_rank"],
                }
            )
    return blockers

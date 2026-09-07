from __future__ import annotations

"""Work-owned progress evidence for delegated WorkerRuns.

This module does not own scheduling or lifecycle. It updates only the existing
``worker_runs.metrics_json`` row owned by the Work ledger. A heartbeat is a
change in durable progress evidence, never a timer tick: repeating the same
stage/evidence fingerprint does not refresh ``last_progress_at``.
"""

import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from .models import utc_now

_PROGRESS_KEY = "supervision_progress"
_DOMAIN = b"zn-worker-progress-v1\x00"


def record_worker_progress(
    ledger,
    worker_run_id: str,
    *,
    stage: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one privacy-safe progress revision iff real evidence changed."""

    normalized_id = str(worker_run_id or "").strip()
    normalized_stage = str(stage or "").strip().lower()
    if not normalized_id or not normalized_stage:
        raise ValueError("worker progress requires worker_run_id and stage")
    run = ledger.worker_run(normalized_id)
    if run is None:
        raise ValueError("unknown WorkerRun")
    if run.state not in {"queued", "running"}:
        return progress_snapshot(run)

    fingerprint = _fingerprint(normalized_stage, evidence or {})
    metrics = dict(run.metrics or {})
    current = _progress_from_metrics(metrics, started_at=run.started_at)
    if (
        current.get("stage") == normalized_stage
        and current.get("fingerprint") == fingerprint
    ):
        return current

    now = utc_now()
    next_progress = {
        "revision": max(0, int(current.get("revision") or 0)) + 1,
        "stage": normalized_stage[:120],
        "fingerprint": fingerprint,
        "last_progress_at": now,
    }
    metrics[_PROGRESS_KEY] = next_progress
    with ledger._lock, closing(ledger._connect()) as conn:
        updated = conn.execute(
            "UPDATE worker_runs SET metrics_json=? "
            "WHERE worker_run_id=? AND state IN ('queued','running')",
            (
                json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                normalized_id,
            ),
        )
        conn.commit()
    if updated.rowcount != 1:
        refreshed = ledger.worker_run(normalized_id)
        return progress_snapshot(refreshed) if refreshed is not None else next_progress
    return next_progress


def progress_snapshot(run) -> dict[str, Any]:
    if run is None:
        return {
            "revision": 0,
            "stage": None,
            "fingerprint": None,
            "last_progress_at": None,
        }
    return _progress_from_metrics(dict(run.metrics or {}), started_at=run.started_at)


def worker_stalled(run, *, timeout_seconds: float) -> bool:
    """Return true only when a live WorkerRun has no new durable progress."""

    if run is None or run.state not in {"queued", "running"}:
        return False
    timeout = max(0.0, float(timeout_seconds))
    progress = progress_snapshot(run)
    observed = _parse_timestamp(progress.get("last_progress_at"))
    if observed is None:
        observed = _parse_timestamp(run.started_at)
    if observed is None:
        return False
    age = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())
    return age >= timeout


def _progress_from_metrics(metrics: dict[str, Any], *, started_at: str | None) -> dict[str, Any]:
    raw = metrics.get(_PROGRESS_KEY)
    if isinstance(raw, dict):
        return {
            "revision": max(0, int(raw.get("revision") or 0)),
            "stage": str(raw.get("stage") or "").strip() or None,
            "fingerprint": str(raw.get("fingerprint") or "").strip() or None,
            "last_progress_at": str(raw.get("last_progress_at") or "").strip() or started_at,
        }
    return {
        "revision": 0,
        "stage": None,
        "fingerprint": None,
        "last_progress_at": started_at,
    }


def _fingerprint(stage: str, evidence: dict[str, Any]) -> str:
    """Hash bounded structural evidence; never persist the evidence payload."""

    bounded = _bounded_structure(evidence, depth=0)
    encoded = json.dumps(
        bounded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="replace")
    digest = hashlib.sha256()
    digest.update(_DOMAIN)
    digest.update(stage.encode("utf-8", errors="replace"))
    digest.update(b"\x00")
    digest.update(encoded)
    return digest.hexdigest()


def _bounded_structure(value: Any, *, depth: int) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(key)[:120]: _bounded_structure(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:24]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_structure(item, depth=depth + 1) for item in value[:24]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    # Identifiers and states are enough to prove a transition. Hash arbitrary
    # text at this boundary so WorkerContextPack/project content never lands in
    # progress metrics.
    if len(text) <= 160 and all(char.isalnum() or char in "-_.:/" for char in text):
        return text
    return {"sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()}


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

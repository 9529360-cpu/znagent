from __future__ import annotations

"""Sanitized resident-owned continuity evidence for installation transitions.

The snapshot exports references, counts and non-secret configuration metadata.
Complete durable state is protected by constant-size digests rather than being
exported into evidence. The result is designed to be persisted by release and
install verification without leaking Work text, artifact content, lived
thoughts, body state, causal episode payloads, resident memory contents, or
provider credentials.
"""

import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from .continuity_reference_proof import (
    long_lived_neural_reference_proof,
    resident_state_proof,
    verified_experience_reference_proof,
    work_state_proof,
)


class ContinuitySnapshotService:
    SCHEMA_VERSION = 2
    WORK_REFERENCE_LIMIT = 100
    VERIFIED_EXPERIENCE_REFERENCE_LIMIT = 256

    def __init__(self, resident, *, work, provider_settings):
        self.resident = resident
        self.work = work
        self.provider_settings = provider_settings

    def snapshot(self) -> dict[str, Any]:
        identity = self.resident.identity
        living = self.resident.life.snapshot()
        threads = sorted(
            self.work.list_threads(limit=self.WORK_REFERENCE_LIMIT),
            key=lambda item: item.thread_id,
        )
        work_proof = work_state_proof(self.work.path)
        resident_proof = resident_state_proof(self.resident.store.path)
        neural_proof = long_lived_neural_reference_proof(self.resident.store.path)
        provider = self._provider_snapshot(self.provider_settings.snapshot())
        verified_learning = self._verified_learning_snapshot()
        return {
            "schema_version": self.SCHEMA_VERSION,
            "identity": {
                "name": str(identity.name),
                "version": str(identity.version),
                "created_at": str(identity.created_at),
                "updated_at": str(identity.updated_at),
            },
            "living_self": {
                "name": str(living.name),
                "version": str(living.version),
                "born_at": str(living.born_at),
                "wake_count": int(living.wake_count),
                "pulse_count": int(living.pulse_count),
                "last_event_id": living.last_event_id,
                "learning_candidate_ids": sorted(
                    str(value) for value in living.learning_candidates
                ),
            },
            "resident_state": {
                "full_state_proof": resident_proof,
            },
            "long_lived_memory": {
                "full_reference_proof": neural_proof,
            },
            "work": {
                "reference_count": len(threads),
                "total_count": int(work_proof["count"]),
                "reference_limit": self.WORK_REFERENCE_LIMIT,
                "references_may_be_truncated": int(work_proof["count"]) > len(threads),
                "full_state_proof": work_proof,
                "threads": [
                    {
                        "id": str(thread.thread_id),
                        "created_at": str(thread.created_at),
                    }
                    for thread in threads
                ],
            },
            "verified_learning": verified_learning,
            "provider": provider,
        }

    def _verified_learning_snapshot(self) -> dict[str, Any]:
        store = getattr(self.resident, "verified_experiences", None)
        recent = getattr(store, "recent", None)
        count = getattr(store, "count", None)
        if not callable(recent) or not callable(count):
            return {
                "reference_count": 0,
                "total_count": 0,
                "reference_limit": self.VERIFIED_EXPERIENCE_REFERENCE_LIMIT,
                "references_may_be_truncated": False,
                "experience_ids": [],
            }

        records = list(recent(self.VERIFIED_EXPERIENCE_REFERENCE_LIMIT))
        total = max(0, int(count()))
        ids = sorted(
            {
                str(getattr(record, "experience_id", "")).strip()
                for record in records
                if str(getattr(record, "experience_id", "")).strip()
            }
        )
        proof = verified_experience_reference_proof(store.path)
        if int(proof["count"]) != total:
            raise RuntimeError(
                "verified learning continuity count changed while snapshotting"
            )
        return {
            "reference_count": len(ids),
            "total_count": total,
            "reference_limit": self.VERIFIED_EXPERIENCE_REFERENCE_LIMIT,
            "references_may_be_truncated": total > len(ids),
            "full_reference_proof": proof,
            "experience_ids": ids,
        }

    @staticmethod
    def _safe_base_url_origin(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = urlsplit(raw)
            scheme = parsed.scheme.lower()
            host = parsed.hostname
            if scheme not in {"http", "https"} or not host:
                return ""
            display_host = f"[{host}]" if ":" in host else host
            port = parsed.port
            return f"{scheme}://{display_host}{f':{port}' if port is not None else ''}"
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _provider_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
        credential = raw.get("credential")
        credential = credential if isinstance(credential, dict) else {}
        routes = raw.get("active_routes")
        routes = routes if isinstance(routes, list) else []
        safe_routes: list[dict[str, str]] = []
        for item in routes:
            if not isinstance(item, dict):
                continue
            safe_routes.append(
                {
                    "id": str(item.get("id") or ""),
                    "provider": str(item.get("provider") or ""),
                    "model": str(item.get("model") or ""),
                }
            )
        safe_routes.sort(key=lambda item: (item["id"], item["provider"], item["model"]))
        environment_name = credential.get("environment_name")
        return {
            "mode": str(raw.get("mode") or ""),
            "provider": str(raw.get("provider") or ""),
            "model": str(raw.get("model") or ""),
            "base_url": ContinuitySnapshotService._safe_base_url_origin(raw.get("base_url")),
            "credential": {
                "configured": bool(credential.get("configured")),
                "source": str(credential.get("source") or "none"),
                "environment_name": (
                    str(environment_name) if environment_name is not None else None
                ),
            },
            "active_routes": safe_routes,
            "cognition_available": bool(raw.get("cognition_available")),
        }


def compare_continuity_snapshots(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a fail-closed, read-only continuity verdict for an N -> candidate N+1 pair."""

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    before_schema = _schema_version(before.get("schema_version"))
    after_schema = _schema_version(after.get("schema_version"))
    if before_schema != after_schema or before_schema != ContinuitySnapshotService.SCHEMA_VERSION:
        blockers.append(
            {
                "kind": "schema_mismatch",
                "before": before_schema,
                "after": after_schema,
            }
        )

    before_identity = _mapping(before.get("identity"))
    after_identity = _mapping(after.get("identity"))
    _require_equal(blockers, "identity_name_changed", before_identity, after_identity, "name")
    _require_equal(blockers, "identity_birth_changed", before_identity, after_identity, "created_at")

    before_living = _mapping(before.get("living_self"))
    after_living = _mapping(after.get("living_self"))
    _require_equal(blockers, "living_self_name_changed", before_living, after_living, "name")
    _require_equal(blockers, "living_self_birth_changed", before_living, after_living, "born_at")
    _require_non_decreasing_counter(blockers, "wake_count_regressed", before_living, after_living, "wake_count")
    _require_non_decreasing_counter(blockers, "pulse_count_regressed", before_living, after_living, "pulse_count")
    _require_id_survival(
        blockers,
        category="learning_candidate",
        before=before_living.get("learning_candidate_ids"),
        after=after_living.get("learning_candidate_ids"),
    )

    _require_optional_state_proof(
        blockers,
        category="resident_state",
        before=_mapping(before.get("resident_state")),
        after=_mapping(after.get("resident_state")),
        proof_key="full_state_proof",
        proof_label="state proof",
    )
    _require_optional_state_proof(
        blockers,
        category="long_lived_memory",
        before=_mapping(before.get("long_lived_memory")),
        after=_mapping(after.get("long_lived_memory")),
        proof_key="full_reference_proof",
        proof_label="reference proof",
    )
    _require_reference_survival(
        blockers,
        category="work",
        before=_mapping(before.get("work")),
        after=_mapping(after.get("work")),
        reference_key="threads",
        proof_key="full_state_proof",
        proof_label="state proof",
        identity=lambda item: str(_mapping(item).get("id") or ""),
    )
    _require_reference_survival(
        blockers,
        category="verified_learning",
        before=_mapping(before.get("verified_learning")),
        after=_mapping(after.get("verified_learning")),
        reference_key="experience_ids",
        proof_key="full_reference_proof",
        proof_label="reference proof",
        identity=lambda item: str(item or ""),
    )

    before_provider = _mapping(before.get("provider"))
    after_provider = _mapping(after.get("provider"))
    provider_keys = ("mode", "provider", "model", "base_url")
    changed_provider = {
        key: {"before": before_provider.get(key), "after": after_provider.get(key)}
        for key in provider_keys
        if before_provider.get(key) != after_provider.get(key)
    }
    if changed_provider:
        warnings.append({"kind": "provider_reference_changed", "changes": changed_provider})

    return {
        "compatible": not blockers,
        "schema_version": ContinuitySnapshotService.SCHEMA_VERSION,
        "blockers": blockers,
        "warnings": warnings,
    }


def _schema_version(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require_equal(
    blockers: list[dict[str, Any]],
    kind: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    key: str,
) -> None:
    old = before.get(key)
    new = after.get(key)
    if not old or old != new:
        blockers.append({"kind": kind, "before": old, "after": new})


def _require_non_decreasing_counter(
    blockers: list[dict[str, Any]],
    kind: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    key: str,
) -> None:
    try:
        old = int(before.get(key))
        new = int(after.get(key))
    except (TypeError, ValueError):
        blockers.append({"kind": kind, "before": before.get(key), "after": after.get(key)})
        return
    if old < 0 or new < old:
        blockers.append({"kind": kind, "before": old, "after": new})


def _require_id_survival(
    blockers: list[dict[str, Any]],
    *,
    category: str,
    before: Any,
    after: Any,
) -> None:
    if not isinstance(before, list) or not isinstance(after, list):
        blockers.append({"kind": f"{category}_continuity_unproven", "reason": "reference set is invalid"})
        return
    old_refs = {str(item).strip() for item in before if str(item).strip()}
    new_refs = {str(item).strip() for item in after if str(item).strip()}
    missing = sorted(old_refs - new_refs)
    if missing:
        blockers.append(
            {
                "kind": f"{category}_references_lost",
                "missing_reference_count": len(missing),
                "missing_reference_ids": missing[:32],
            }
        )


def _reference_proof(value: Any) -> tuple[int, str] | None:
    proof = _mapping(value)
    if proof.get("algorithm") != "sha256":
        return None
    count = proof.get("count")
    digest = str(proof.get("digest") or "")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return None
    return count, digest


def _require_optional_state_proof(
    blockers: list[dict[str, Any]],
    *,
    category: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    proof_key: str,
    proof_label: str,
) -> None:
    before_raw = before.get(proof_key)
    if before_raw is None:
        return
    before_proof = _reference_proof(before_raw)
    after_proof = _reference_proof(after.get(proof_key))
    if before_proof is None or after_proof is None:
        blockers.append(
            {
                "kind": f"{category}_continuity_unproven",
                "reason": f"full {proof_label} is invalid or missing",
            }
        )
        return
    if before_proof != after_proof:
        blockers.append(
            {
                "kind": f"{category}_{proof_key}_changed",
                "before_count": before_proof[0],
                "after_count": after_proof[0],
            }
        )


def _require_reference_survival(
    blockers: list[dict[str, Any]],
    *,
    category: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    reference_key: str,
    proof_key: str,
    proof_label: str,
    identity,
) -> None:
    before_proof_raw = before.get(proof_key)
    before_proof = _reference_proof(before_proof_raw)

    if before_proof_raw is not None:
        after_proof = _reference_proof(after.get(proof_key))
        if before_proof is None or after_proof is None:
            blockers.append(
                {
                    "kind": f"{category}_continuity_unproven",
                    "reason": f"full {proof_label} is invalid or missing",
                }
            )
            return
        if before_proof != after_proof:
            blockers.append(
                {
                    "kind": f"{category}_{proof_key}_changed",
                    "before_count": before_proof[0],
                    "after_count": after_proof[0],
                }
            )
        return

    if bool(before.get("references_may_be_truncated")):
        blockers.append(
            {
                "kind": f"{category}_baseline_incomplete",
                "reason": "pre-transition reference set is truncated",
            }
        )

    before_items = before.get(reference_key)
    after_items = after.get(reference_key)
    if not isinstance(before_items, list) or not isinstance(after_items, list):
        blockers.append(
            {
                "kind": f"{category}_continuity_unproven",
                "reason": "reference set is invalid",
            }
        )
        return

    old_refs = {identity(item) for item in before_items if identity(item)}
    new_refs = {identity(item) for item in after_items if identity(item)}
    missing = sorted(old_refs - new_refs)
    if not missing:
        return
    if bool(after.get("references_may_be_truncated")):
        blockers.append(
            {
                "kind": f"{category}_continuity_unproven",
                "missing_reference_count": len(missing),
                "reason": "post-transition reference set is truncated",
            }
        )
        return
    blockers.append(
        {
            "kind": f"{category}_references_lost",
            "missing_reference_count": len(missing),
            "missing_reference_ids": missing[:32],
        }
    )

from __future__ import annotations

"""Sanitized resident-owned continuity evidence for installation transitions.

Bounded human-readable references remain diagnostic. Complete continuity uses
privacy-preserving per-entity SHA-256 references so a restarted resident may
legitimately add state or advance mutable statuses while protected baseline
state either survives or follows an explicit bounded-retention contract.
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

        work_path = getattr(self.work, "path", None)
        resident_store = getattr(self.resident, "store", None)
        resident_path = getattr(resident_store, "path", None)
        work_proof = work_state_proof(work_path) if work_path is not None else None
        resident_proof = (
            resident_state_proof(resident_path) if resident_path is not None else None
        )
        neural_proof = (
            long_lived_neural_reference_proof(resident_path)
            if resident_path is not None
            else None
        )
        provider = self._provider_snapshot(self.provider_settings.snapshot())
        verified_learning = self._verified_learning_snapshot()

        if work_proof is not None:
            thread_count = int(work_proof["thread_count"])
            work_may_be_truncated = thread_count > len(threads)
        else:
            thread_count = len(threads)
            # Without the durable store path there is no way to distinguish
            # exactly-at-limit from truncated. Keep the historical fail-closed
            # diagnostic behavior for lightweight callers and test doubles.
            work_may_be_truncated = len(threads) >= self.WORK_REFERENCE_LIMIT

        work_snapshot: dict[str, Any] = {
            "reference_count": len(threads),
            "total_count": thread_count,
            "reference_limit": self.WORK_REFERENCE_LIMIT,
            "references_may_be_truncated": work_may_be_truncated,
            "threads": [
                {"id": str(thread.thread_id), "created_at": str(thread.created_at)}
                for thread in threads
            ],
        }
        if work_proof is not None:
            work_snapshot["full_state_proof"] = work_proof

        resident_state: dict[str, Any] = {}
        if resident_proof is not None:
            resident_state["full_state_proof"] = resident_proof
        long_lived_memory: dict[str, Any] = {}
        if neural_proof is not None:
            long_lived_memory["full_reference_proof"] = neural_proof

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
            "resident_state": resident_state,
            "long_lived_memory": long_lived_memory,
            "work": work_snapshot,
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
        result: dict[str, Any] = {
            "reference_count": len(ids),
            "total_count": total,
            "reference_limit": self.VERIFIED_EXPERIENCE_REFERENCE_LIMIT,
            "references_may_be_truncated": total > len(ids),
            "experience_ids": ids,
        }

        retention_capacity = _positive_int(getattr(store, "max_records", None))
        if retention_capacity is not None:
            result["retention_capacity"] = retention_capacity

        store_path = getattr(store, "path", None)
        if store_path is not None:
            proof = verified_experience_reference_proof(store_path)
            if int(proof["count"]) != total:
                raise RuntimeError(
                    "verified learning continuity count changed while snapshotting"
                )
            result["full_reference_proof"] = proof
        return result

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
            "base_url": ContinuitySnapshotService._safe_base_url_origin(
                raw.get("base_url")
            ),
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
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    before_schema = _schema_version(before.get("schema_version"))
    after_schema = _schema_version(after.get("schema_version"))
    if (
        before_schema != after_schema
        or before_schema != ContinuitySnapshotService.SCHEMA_VERSION
    ):
        blockers.append(
            {
                "kind": "schema_mismatch",
                "before": before_schema,
                "after": after_schema,
            }
        )

    before_identity = _mapping(before.get("identity"))
    after_identity = _mapping(after.get("identity"))
    _require_equal(
        blockers,
        "identity_name_changed",
        before_identity,
        after_identity,
        "name",
    )
    _require_equal(
        blockers,
        "identity_birth_changed",
        before_identity,
        after_identity,
        "created_at",
    )

    before_living = _mapping(before.get("living_self"))
    after_living = _mapping(after.get("living_self"))
    _require_equal(
        blockers,
        "living_self_name_changed",
        before_living,
        after_living,
        "name",
    )
    _require_equal(
        blockers,
        "living_self_birth_changed",
        before_living,
        after_living,
        "born_at",
    )
    _require_non_decreasing_counter(
        blockers,
        "wake_count_regressed",
        before_living,
        after_living,
        "wake_count",
    )
    _require_non_decreasing_counter(
        blockers,
        "pulse_count_regressed",
        before_living,
        after_living,
        "pulse_count",
    )

    before_resident_state = _mapping(before.get("resident_state"))
    after_resident_state = _mapping(after.get("resident_state"))
    if before_resident_state.get("full_state_proof") is None:
        # Backward compatibility for schema-2 baselines created before complete
        # resident references existed. New snapshots use durable table anchors,
        # allowing a candidate to legitimately resolve a pending candidate.
        _require_id_survival(
            blockers,
            category="learning_candidate",
            before=before_living.get("learning_candidate_ids"),
            after=after_living.get("learning_candidate_ids"),
        )
    _require_proof_survival(
        blockers,
        category="resident_state",
        before=before_resident_state.get("full_state_proof"),
        after=after_resident_state.get("full_state_proof"),
        proof_label="state proof",
        optional_if_before_missing=True,
    )
    _require_proof_survival(
        blockers,
        category="long_lived_memory",
        before=_mapping(before.get("long_lived_memory")).get(
            "full_reference_proof"
        ),
        after=_mapping(after.get("long_lived_memory")).get("full_reference_proof"),
        proof_label="reference proof",
        optional_if_before_missing=True,
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
    _require_verified_learning_survival(
        blockers,
        before=_mapping(before.get("verified_learning")),
        after=_mapping(after.get("verified_learning")),
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
        warnings.append(
            {"kind": "provider_reference_changed", "changes": changed_provider}
        )

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


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
        blockers.append(
            {"kind": kind, "before": before.get(key), "after": after.get(key)}
        )
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
        blockers.append(
            {
                "kind": f"{category}_continuity_unproven",
                "reason": "reference set is invalid",
            }
        )
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


def _parsed_proof(value: Any) -> dict[str, Any] | None:
    proof = _mapping(value)
    if proof.get("algorithm") != "sha256":
        return None
    count = proof.get("count")
    digest = str(proof.get("digest") or "")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return None
    hashes_raw = proof.get("reference_hashes")
    if hashes_raw is None:
        return {"count": count, "digest": digest, "hashes": None}
    if not isinstance(hashes_raw, list) or len(hashes_raw) != count:
        return None
    hashes = [str(item) for item in hashes_raw]
    if len(set(hashes)) != len(hashes):
        return None
    if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in hashes):
        return None
    return {"count": count, "digest": digest, "hashes": frozenset(hashes)}


def _require_proof_survival(
    blockers: list[dict[str, Any]],
    *,
    category: str,
    before: Any,
    after: Any,
    proof_label: str,
    optional_if_before_missing: bool = False,
) -> None:
    if before is None and optional_if_before_missing:
        return
    old = _parsed_proof(before)
    new = _parsed_proof(after)
    if old is None or new is None:
        blockers.append(
            {
                "kind": f"{category}_continuity_unproven",
                "reason": f"full {proof_label} is invalid or missing",
            }
        )
        return
    old_hashes = old["hashes"]
    new_hashes = new["hashes"]
    if old_hashes is not None:
        if new_hashes is None:
            blockers.append(
                {
                    "kind": f"{category}_continuity_unproven",
                    "reason": f"full {proof_label} lacks reference hashes",
                }
            )
            return
        missing_count = len(old_hashes - new_hashes)
        if missing_count:
            blockers.append(
                {
                    "kind": f"{category}_references_lost",
                    "missing_reference_count": missing_count,
                    "before_count": old["count"],
                    "after_count": new["count"],
                }
            )
        return
    # Digest-only proofs were used by unreleased development snapshots. Treat
    # them strictly rather than pretending they can prove subset survival.
    if old["count"] != new["count"] or old["digest"] != new["digest"]:
        blockers.append(
            {
                "kind": f"{category}_proof_changed",
                "before_count": old["count"],
                "after_count": new["count"],
            }
        )


def _require_verified_learning_survival(
    blockers: list[dict[str, Any]],
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    before_proof_raw = before.get("full_reference_proof")
    if before_proof_raw is None:
        _require_reference_survival(
            blockers,
            category="verified_learning",
            before=before,
            after=after,
            reference_key="experience_ids",
            proof_key="full_reference_proof",
            proof_label="reference proof",
            identity=lambda item: str(item or ""),
        )
        return

    old = _parsed_proof(before_proof_raw)
    new = _parsed_proof(after.get("full_reference_proof"))
    if old is None or new is None:
        blockers.append(
            {
                "kind": "verified_learning_continuity_unproven",
                "reason": "full reference proof is invalid or missing",
            }
        )
        return

    before_capacity = _positive_int(before.get("retention_capacity"))
    after_capacity = _positive_int(after.get("retention_capacity"))
    if before_capacity is not None:
        if after_capacity is None:
            blockers.append(
                {
                    "kind": "verified_learning_continuity_unproven",
                    "reason": "retention capacity is missing after transition",
                }
            )
            return
        if after_capacity < before_capacity:
            blockers.append(
                {
                    "kind": "verified_learning_retention_capacity_regressed",
                    "before": before_capacity,
                    "after": after_capacity,
                }
            )
            return

    old_hashes = old["hashes"]
    new_hashes = new["hashes"]
    if old_hashes is None or new_hashes is None:
        _require_proof_survival(
            blockers,
            category="verified_learning",
            before=before_proof_raw,
            after=after.get("full_reference_proof"),
            proof_label="reference proof",
        )
        return

    missing = old_hashes - new_hashes
    if not missing:
        return

    # Proofs created before retention capacity was exported cannot distinguish
    # legitimate bounded pruning from arbitrary loss, so they remain strict.
    if before_capacity is None or after_capacity is None:
        blockers.append(
            {
                "kind": "verified_learning_references_lost",
                "missing_reference_count": len(missing),
                "before_count": old["count"],
                "after_count": new["count"],
            }
        )
        return

    if old["count"] > before_capacity or new["count"] > after_capacity:
        blockers.append(
            {
                "kind": "verified_learning_continuity_unproven",
                "reason": "reference proof exceeds retention capacity",
            }
        )
        return

    # Increasing capacity never requires dropping an old retained episode.
    if after_capacity != before_capacity:
        blockers.append(
            {
                "kind": "verified_learning_references_lost",
                "missing_reference_count": len(missing),
                "before_count": old["count"],
                "after_count": new["count"],
            }
        )
        return

    added_count = len(new_hashes - old_hashes)
    # The store prunes only after an insertion would exceed max_records and then
    # returns to exactly that capacity. If the candidate is not full, or the new
    # references were insufficient to overflow the baseline, loss is unexplained.
    if (
        new["count"] != after_capacity
        or old["count"] + added_count <= after_capacity
    ):
        blockers.append(
            {
                "kind": "verified_learning_references_lost",
                "missing_reference_count": len(missing),
                "before_count": old["count"],
                "after_count": new["count"],
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
    before_proof = before.get(proof_key)
    if before_proof is not None:
        _require_proof_survival(
            blockers,
            category=category,
            before=before_proof,
            after=after.get(proof_key),
            proof_label=proof_label,
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

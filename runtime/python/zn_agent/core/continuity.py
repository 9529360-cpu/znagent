from __future__ import annotations

"""Sanitized resident-owned continuity evidence for installation transitions.

The snapshot deliberately contains references and non-secret configuration
metadata only. It is designed to be persisted by release/install evidence and
compared with a later runtime without exporting Work content, lived thoughts,
body state, causal episode payloads, or provider credentials.
"""

from typing import Any, Mapping


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
            "work": {
                "reference_count": len(threads),
                "reference_limit": self.WORK_REFERENCE_LIMIT,
                # list_threads is deliberately bounded. Equality means callers
                # must treat the reference set as potentially incomplete rather
                # than claiming a false exact total.
                "references_may_be_truncated": len(threads) >= self.WORK_REFERENCE_LIMIT,
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
        return {
            "reference_count": len(ids),
            "total_count": total,
            "reference_limit": self.VERIFIED_EXPERIENCE_REFERENCE_LIMIT,
            "references_may_be_truncated": total > len(ids),
            "experience_ids": ids,
        }

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
            "base_url": str(raw.get("base_url") or ""),
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
    """Return a fail-closed, read-only continuity verdict for an N -> candidate N+1 pair.

    This function never applies an update. It only decides whether the supplied
    post-transition evidence proves that core subject references survived. A
    truncated post snapshot is insufficient evidence for a missing reference and
    therefore blocks a positive continuity verdict rather than guessing.
    """

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    before_schema = int(before.get("schema_version") or 0)
    after_schema = int(after.get("schema_version") or 0)
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

    _require_reference_survival(
        blockers,
        category="work",
        before=_mapping(before.get("work")),
        after=_mapping(after.get("work")),
        reference_key="threads",
        identity=lambda item: str(_mapping(item).get("id") or ""),
    )
    _require_reference_survival(
        blockers,
        category="verified_learning",
        before=_mapping(before.get("verified_learning")),
        after=_mapping(after.get("verified_learning")),
        reference_key="experience_ids",
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


def _require_reference_survival(
    blockers: list[dict[str, Any]],
    *,
    category: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    reference_key: str,
    identity,
) -> None:
    before_items = before.get(reference_key)
    after_items = after.get(reference_key)
    old_refs = {
        identity(item)
        for item in before_items
        if identity(item)
    } if isinstance(before_items, list) else set()
    new_refs = {
        identity(item)
        for item in after_items
        if identity(item)
    } if isinstance(after_items, list) else set()
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

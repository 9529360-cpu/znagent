from __future__ import annotations

"""Sanitized resident-owned continuity evidence for installation transitions.

The snapshot deliberately contains references and non-secret configuration
metadata only. It is designed to be persisted by release/install evidence and
compared with a later runtime without exporting Work content, lived thoughts,
body state, or provider credentials.
"""

from typing import Any


class ContinuitySnapshotService:
    SCHEMA_VERSION = 1
    WORK_REFERENCE_LIMIT = 100

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
        thread_count = self.work.count_threads()
        provider = self._provider_snapshot(self.provider_settings.snapshot())
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
                "thread_count": thread_count,
                "reference_limit": self.WORK_REFERENCE_LIMIT,
                "references_truncated": thread_count > len(threads),
                "threads": [
                    {
                        "id": str(thread.thread_id),
                        "created_at": str(thread.created_at),
                    }
                    for thread in threads
                ],
            },
            "provider": provider,
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

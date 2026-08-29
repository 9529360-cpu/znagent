from __future__ import annotations

"""Sanitized resident-owned continuity evidence for installation transitions.

The snapshot deliberately contains references and non-secret configuration
metadata only. It is designed to be persisted by release/install evidence and
compared with a later runtime without exporting Work content, lived thoughts,
body state, or provider credentials.
"""

from typing import Any
from urllib.parse import urlsplit


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
            "provider": provider,
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
            # Provider URLs can legally contain userinfo, query tokens or
            # sensitive tenant paths. Continuity evidence only needs endpoint
            # identity at origin granularity, never those secret-bearing parts.
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

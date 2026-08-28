from __future__ import annotations

"""Read-only Work restore-point inspection against fresh file reality.

This layer projects bounded metadata for an existing retained restore point. It
never reads the retained content BLOB, never writes bytes back to the target,
and never converts inspection evidence into restore authority.
"""

import json
from contextlib import closing
from typing import Any

from .file_identity import (
    DEFAULT_MAX_HASH_BYTES,
    compare_file_identities,
    observe_file_identity,
)
from .work_restore_point_resident import WorkRestorePointResidentRuntime


_TABLE = "work_restore_points"
_MAX_INSPECTION_POINTS = 64


class WorkRestorePointInspectionResidentRuntime(WorkRestorePointResidentRuntime):
    """Expose privacy-bounded restore-point metadata for exact Work ownership."""

    @staticmethod
    def _inspection_state(
        expected: dict[str, Any],
        current: dict[str, Any],
    ) -> tuple[str, str]:
        if current.get("observable") is not True:
            return "unsupported", "current_target_unobservable"
        if current.get("stable") is not True:
            return "unsupported", "current_target_unstable"
        if current.get("exists") is False:
            return "missing", "current_target_missing"
        if str(current.get("type") or "") != "file":
            return "unsupported", "current_target_type_unsupported"
        if current.get("digest_complete") is not True:
            return "unsupported", "current_target_exact_identity_unavailable"

        comparison = compare_file_identities(expected, current)
        if comparison.get("exact") is True:
            return "unchanged", str(comparison.get("reason") or "same_exact_file_identity")
        if comparison.get("comparable") is True:
            return "changed", str(comparison.get("reason") or "file_identity_changed")
        return "unsupported", str(comparison.get("reason") or "identity_not_comparable")

    def inspect_work_restore_points(
        self,
        thread_id: str,
        *,
        limit: int = 48,
    ) -> list[dict[str, Any]]:
        """Inspect retained points for one exact Work thread without mutation.

        The query intentionally excludes the retained content BLOB. Stored
        pre-mutation identity is read only inside the resident so the public
        projection can compare it with fresh current-world evidence without
        exporting hashes, action signatures, intent identity or raw bytes.
        """

        normalized_thread = str(thread_id or "").strip()
        if not normalized_thread:
            return []
        bounded = max(1, min(_MAX_INSPECTION_POINTS, int(limit)))

        with closing(self._restore_connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT restore_point_id,version,event_id,thread_id,message_id,
                       target_path,pre_identity_json,size_bytes,status,
                       created_at,updated_at
                FROM {_TABLE}
                WHERE thread_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized_thread, bounded),
            ).fetchall()

            projected: list[dict[str, Any]] = []
            for row in rows:
                run = conn.execute(
                    "SELECT event_id,thread_id,message_id FROM work_runs WHERE event_id=?",
                    (str(row["event_id"]),),
                ).fetchone()
                if run is None or (
                    str(run["event_id"]) != str(row["event_id"])
                    or str(run["thread_id"]) != normalized_thread
                    or str(run["thread_id"]) != str(row["thread_id"])
                    or str(run["message_id"]) != str(row["message_id"])
                ):
                    raise RuntimeError(
                        "durable Work restore point conflicts with its Work ownership"
                    )

                try:
                    expected = json.loads(row["pre_identity_json"] or "{}")
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "durable Work restore identity is malformed"
                    ) from exc
                if not self._capturable_identity(expected):
                    raise RuntimeError(
                        "durable Work restore identity is not an exact retained file identity"
                    )
                if (
                    str(expected.get("path") or "") != str(row["target_path"])
                    or int(expected.get("size_bytes") or 0) != int(row["size_bytes"])
                ):
                    raise RuntimeError(
                        "durable Work restore metadata conflicts with retained identity"
                    )

                current = observe_file_identity(
                    str(row["target_path"]),
                    max_hash_bytes=DEFAULT_MAX_HASH_BYTES,
                )
                current_status, current_reason = self._inspection_state(expected, current)
                current_size = current.get("size_bytes")
                if isinstance(current_size, bool) or not isinstance(current_size, int):
                    current_size = None

                projected.append(
                    {
                        "restore_point_id": str(row["restore_point_id"]),
                        "version": int(row["version"]),
                        "event_id": str(row["event_id"]),
                        "thread_id": normalized_thread,
                        "target_path": str(row["target_path"]),
                        "size_bytes": int(row["size_bytes"]),
                        "status": str(row["status"]),
                        "created_at": str(row["created_at"]),
                        "updated_at": str(row["updated_at"]),
                        "current_status": current_status,
                        "current_reason": current_reason,
                        "current_observed_at": str(current.get("observed_at") or ""),
                        "current_exists": (
                            current.get("exists")
                            if isinstance(current.get("exists"), bool)
                            else None
                        ),
                        "current_type": str(current.get("type") or "unknown"),
                        "current_size_bytes": current_size,
                        "automatic_restore_authority": False,
                        "restore_application_available": False,
                    }
                )
        return projected

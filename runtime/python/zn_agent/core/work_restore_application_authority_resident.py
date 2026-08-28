from __future__ import annotations

"""Authorization hardening for explicit Work restore application control."""

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any

from .file_identity import DEFAULT_MAX_HASH_BYTES, observe_file_identity
from .work_restore_application_resident import (
    _APPLICATION_TABLE,
    WorkRestoreApplicationResidentRuntime,
)


class WorkRestoreApplicationAuthorityResidentRuntime(
    WorkRestoreApplicationResidentRuntime
):
    """Fail closed when restore ownership or parent identity is not exact enough."""

    @staticmethod
    def _same_parent_identity(
        expected: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        expected_inode = expected.get("inode")
        current_inode = current.get("inode")
        if (
            type(expected_inode) is not int
            or type(current_inode) is not int
            or expected_inode <= 0
            or current_inode <= 0
        ):
            return False
        return bool(
            expected_inode == current_inode
            and WorkRestoreApplicationResidentRuntime._same_parent_identity(
                expected, current
            )
        )

    @classmethod
    def _safe_parent(cls, identity: dict[str, Any]) -> bool:
        inode = identity.get("inode")
        return bool(
            type(inode) is int
            and inode > 0
            and WorkRestoreApplicationResidentRuntime._safe_parent(identity)
        )

    @staticmethod
    def _application_public(row) -> dict[str, Any]:
        projected = WorkRestoreApplicationResidentRuntime._application_public(row)
        # The legacy application-id-only inspection RPC is capability-token scoped,
        # not Work-thread scoped. Keep its response deliberately minimal so knowing
        # an application id cannot reveal another Work thread's path/event metadata.
        for key in ("restore_point_id", "thread_id", "event_id", "target_path"):
            projected.pop(key, None)
        return projected

    def prepare_missing_work_restore(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> dict[str, Any]:
        """Reuse one still-valid approval request instead of minting duplicates.

        This is restart continuity, not mutation authority. The target must still
        be freshly missing, Work ownership must still verify, and the exact parent
        directory identity must match the durable approval context. An interrupted
        application therefore remains discoverable by repeating the explicit
        Prepare action after a desktop/resident restart, while approval remains a
        separate user act.
        """

        if os.name != "nt":
            return super().prepare_missing_work_restore(thread_id, restore_point_id)

        point, _, _ = self._owned_restore_point(thread_id, restore_point_id)
        normalized_thread = str(thread_id or "").strip()
        normalized_point = str(restore_point_id or "").strip()
        target = Path(str(point["target_path"]))
        current = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        parent = self._observe_parent(target)
        if not self._stable_missing(current) or not self._safe_parent(parent):
            return super().prepare_missing_work_restore(thread_id, restore_point_id)

        size_bytes = int(point["size_bytes"])
        content_sha256 = str(point["content_sha256"])
        with closing(self._restore_connect()) as conn:
            active = conn.execute(
                f"""
                SELECT * FROM {_APPLICATION_TABLE}
                WHERE thread_id=? AND restore_point_id=?
                  AND status IN ('approval_required','recovery_required')
                ORDER BY updated_at DESC, created_at DESC
                """,
                (normalized_thread, normalized_point),
            ).fetchall()

        reusable = None
        for application in active:
            try:
                expected_parent = json.loads(application["parent_identity_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                expected_parent = {}
            if reusable is None and self._same_parent_identity(expected_parent, parent):
                reusable = application
                continue

            stage_removed = self._discard_exact_stage(
                Path(str(application["staging_path"])),
                size_bytes=size_bytes,
                content_sha256=content_sha256,
            )
            base_error = (
                "restore approval was superseded by a newer explicit preparation"
                if reusable is not None
                else "restore parent directory identity changed before renewed preparation"
            )
            self._set_application(
                str(application["application_id"]),
                status="blocked",
                current_identity=current,
                error=(
                    base_error
                    if stage_removed
                    else f"{base_error}; unexpected staging evidence remains"
                ),
            )

        if reusable is not None:
            return self.inspect_work_restore_application(str(reusable["application_id"]))
        return super().prepare_missing_work_restore(thread_id, restore_point_id)

    def inspect_work_restore_application_for_thread(
        self,
        thread_id: str,
        application_id: str,
    ) -> dict[str, Any]:
        normalized_thread = str(thread_id or "").strip()
        normalized_application = str(application_id or "").strip()
        if not normalized_thread or not normalized_application:
            raise ValueError(
                "Work restore application inspection requires thread_id and application_id"
            )
        row = self._application_row(normalized_application)
        if row is None or str(row["thread_id"]) != normalized_thread:
            raise ValueError("unknown Work restore application for thread")
        return WorkRestoreApplicationResidentRuntime._application_public(row)

from __future__ import annotations

"""Authorization hardening for explicit Work restore application control."""

from typing import Any

from .work_restore_application_resident import WorkRestoreApplicationResidentRuntime


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

    @staticmethod
    def _application_public(row) -> dict[str, Any]:
        projected = WorkRestoreApplicationResidentRuntime._application_public(row)
        # The legacy application-id-only inspection RPC is capability-token scoped,
        # not Work-thread scoped. Keep its response deliberately minimal so knowing
        # an application id cannot reveal another Work thread's path/event metadata.
        for key in ("restore_point_id", "thread_id", "event_id", "target_path"):
            projected.pop(key, None)
        return projected

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

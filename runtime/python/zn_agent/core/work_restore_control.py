from __future__ import annotations

"""Explicit control-plane authority for applying retained Work restore points."""

from typing import Any

from .work_control import ResidentWorkControl


class RestoreAwareWorkControl(ResidentWorkControl):
    """Keep restore mutation behind explicit control calls, never model intent."""

    def prepare_missing_restore(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_point = str(restore_point_id or "").strip()
        if not normalized_point:
            raise ValueError("missing-file restore preparation requires restore_point_id")
        prepare = getattr(self.resident, "prepare_missing_work_restore", None)
        if not callable(prepare):
            raise RuntimeError("resident does not support Work restore application")
        return prepare(normalized_thread, normalized_point)

    def approve_missing_restore(
        self,
        thread_id: str,
        application_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("missing-file restore approval requires application_id")
        approve = getattr(self.resident, "approve_missing_work_restore", None)
        if not callable(approve):
            raise RuntimeError("resident does not support Work restore application")
        return approve(normalized_thread, normalized_application)

    def restore_application(self, application_id: str) -> dict[str, Any]:
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("restore application inspection requires application_id")
        inspect = getattr(self.resident, "inspect_work_restore_application", None)
        if not callable(inspect):
            raise RuntimeError("resident does not support Work restore application")
        return inspect(normalized_application)

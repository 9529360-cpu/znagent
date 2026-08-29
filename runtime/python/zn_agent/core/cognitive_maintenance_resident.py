from __future__ import annotations

"""Resident composition that adds bounded cognitive self-maintenance.

This layer does not broaden ordinary body or Work authority. It composes the
existing health-aware resident with maintenance-specific cognitive authoring,
semantic review, bounded rejected-attempt cleanup, and local-only publication
preparation for accepted repairs.
"""

import sqlite3
from pathlib import Path
from typing import Any

from .health_aware_resident import HealthAwareResidentRuntime
from .maintenance_attempt_lifecycle import MaintenanceRepairAttemptLifecycle
from .maintenance_cognition_journal import DurableMaintenanceCognitiveRepairOrchestrator
from .maintenance_publication import MaintenancePublicationPreparation


class CognitiveMaintenanceResidentRuntime(HealthAwareResidentRuntime):
    """Health-aware resident with bounded self-maintenance orchestration."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.maintenance_cognition: DurableMaintenanceCognitiveRepairOrchestrator | None = None
        self.maintenance_attempt_lifecycle: MaintenanceRepairAttemptLifecycle | None = None
        self.maintenance_publication_preparation: MaintenancePublicationPreparation | None = None
        self._install_maintenance_cognition()
        self._install_maintenance_attempt_lifecycle()
        self._install_maintenance_publication_preparation()

    def status(self) -> dict[str, Any]:
        data = super().status()
        orchestrator = self.maintenance_cognition
        if orchestrator is None:
            try:
                orchestrator = self._maintenance_cognitive_orchestrator()
            except (sqlite3.Error, RuntimeError):
                data["maintenance_cognitive_repairs"] = {
                    "available": False,
                    "candidate_count": 0,
                    "review_count": 0,
                    "candidates": [],
                    "reviews": [],
                }
            else:
                self._project_cognitive_status(data, orchestrator)
        else:
            self._project_cognitive_status(data, orchestrator)

        lifecycle = self.maintenance_attempt_lifecycle
        if lifecycle is None:
            try:
                lifecycle = self._maintenance_attempt_lifecycle_owner()
            except (sqlite3.Error, RuntimeError):
                data["maintenance_attempt_cleanup"] = {
                    "available": False,
                    "cleanup_count": 0,
                    "returned_count": 0,
                    "truncated": False,
                    "cleanups": [],
                }
            else:
                self._project_attempt_lifecycle_status(data, lifecycle)
        else:
            self._project_attempt_lifecycle_status(data, lifecycle)

        preparation = self.maintenance_publication_preparation
        if preparation is None:
            try:
                preparation = self._maintenance_publication_preparation_owner()
            except (sqlite3.Error, RuntimeError):
                data["maintenance_publication_preparation"] = {
                    "available": False,
                    "prepared_count": 0,
                    "returned_count": 0,
                    "truncated": False,
                    "prepared": [],
                }
                return data
        try:
            snapshot = preparation.snapshot()
        except sqlite3.Error:
            self.maintenance_publication_preparation = None
            data["maintenance_publication_preparation"] = {
                "available": False,
                "prepared_count": 0,
                "returned_count": 0,
                "truncated": False,
                "prepared": [],
            }
        else:
            data["maintenance_publication_preparation"] = {"available": True, **snapshot}
        return data

    def run_cognitive_maintenance_repair(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        attempt_root: str | Path,
        branch_ref: str,
    ) -> dict[str, Any]:
        """Derive, execute, review, then retire or prepare the isolated attempt.

        Model calls receive only bounded maintenance evidence/source context. They
        do not receive body tools, terminal/Git access, arbitrary file access,
        commit/push/merge, release, updater, replacement, or rollback authority.
        Every external maintenance cognition call is durably reserved before
        dispatch so a crash or ambiguous provider outcome cannot trigger an
        automatic replay. Rejected candidates are eligible for bounded cleanup.
        Accepted candidates are revalidated and may become a local-only commit; no
        remote publication or repository credential authority is granted here.
        """

        result = self._maintenance_cognitive_orchestrator().derive_execute_and_review(
            task_id,
            source_root=source_root,
            attempt_root=attempt_root,
            branch_ref=branch_ref,
        )
        review = result.get("semantic_review") or {}
        decision = str(review.get("decision") or "")
        if decision == "reject":
            try:
                cleanup = self._maintenance_attempt_lifecycle_owner().cleanup_rejected(
                    task_id,
                    source_root=source_root,
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                result["attempt_cleanup"] = {
                    "completed": False,
                    "error_type": type(exc).__name__,
                }
            else:
                result["attempt_cleanup"] = {"completed": True, **cleanup}
        elif decision == "accept":
            result["attempt_cleanup"] = {
                "completed": False,
                "retained": True,
                "reason": "accepted_for_publication",
            }
            try:
                prepared = self._maintenance_publication_preparation_owner().prepare(
                    task_id,
                    source_root=source_root,
                )
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                result["publication_preparation"] = {
                    "completed": False,
                    "error_type": type(exc).__name__,
                }
            else:
                result["publication_preparation"] = {"completed": True, **prepared}
        return result

    def cleanup_rejected_maintenance_repair(
        self,
        task_id: str,
        *,
        source_root: str | Path,
    ) -> dict[str, Any]:
        """Retry bounded cleanup for a durable rejected repair attempt."""

        return self._maintenance_attempt_lifecycle_owner().cleanup_rejected(
            task_id,
            source_root=source_root,
        )

    def prepare_accepted_maintenance_publication(
        self,
        task_id: str,
        *,
        source_root: str | Path,
    ) -> dict[str, Any]:
        """Create/recover the local-only commit for one accepted repair.

        This method performs no push, pull-request creation, merge, release,
        updater/replacement, rollback, or repository credential access.
        """

        return self._maintenance_publication_preparation_owner().prepare(
            task_id,
            source_root=source_root,
        )

    def _project_cognitive_status(
        self,
        data: dict[str, Any],
        orchestrator: DurableMaintenanceCognitiveRepairOrchestrator,
    ) -> None:
        try:
            snapshot = orchestrator.snapshot()
        except sqlite3.Error:
            self.maintenance_cognition = None
            data["maintenance_cognitive_repairs"] = {
                "available": False,
                "candidate_count": 0,
                "review_count": 0,
                "candidates": [],
                "reviews": [],
            }
        else:
            data["maintenance_cognitive_repairs"] = {"available": True, **snapshot}

    def _project_attempt_lifecycle_status(
        self,
        data: dict[str, Any],
        lifecycle: MaintenanceRepairAttemptLifecycle,
    ) -> None:
        try:
            snapshot = lifecycle.snapshot()
        except sqlite3.Error:
            self.maintenance_attempt_lifecycle = None
            data["maintenance_attempt_cleanup"] = {
                "available": False,
                "cleanup_count": 0,
                "returned_count": 0,
                "truncated": False,
                "cleanups": [],
            }
        else:
            data["maintenance_attempt_cleanup"] = {"available": True, **snapshot}

    def _install_maintenance_cognition(self) -> None:
        if self.maintenance is None or self.maintenance_repair is None:
            return
        try:
            self.maintenance_cognition = DurableMaintenanceCognitiveRepairOrchestrator(
                self.store,
                self.maintenance,
                self.maintenance_repair,
                self.kernel,
            )
        except sqlite3.Error:
            self.maintenance_cognition = None

    def _install_maintenance_attempt_lifecycle(self) -> None:
        if self.maintenance is None:
            return
        try:
            self.maintenance_attempt_lifecycle = MaintenanceRepairAttemptLifecycle(
                self.store,
                self.maintenance,
            )
        except sqlite3.Error:
            self.maintenance_attempt_lifecycle = None

    def _install_maintenance_publication_preparation(self) -> None:
        if self.maintenance is None:
            return
        try:
            self.maintenance_publication_preparation = MaintenancePublicationPreparation(
                self.store,
                self.maintenance,
            )
        except sqlite3.Error:
            self.maintenance_publication_preparation = None

    def _maintenance_cognitive_orchestrator(self) -> DurableMaintenanceCognitiveRepairOrchestrator:
        orchestrator = self.maintenance_cognition
        if orchestrator is not None:
            return orchestrator
        ledger = self._maintenance_ledger()
        operator = self._maintenance_repair_operator()
        try:
            orchestrator = DurableMaintenanceCognitiveRepairOrchestrator(
                self.store,
                ledger,
                operator,
                self.kernel,
            )
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance cognitive orchestrator is unavailable") from exc
        self.maintenance_cognition = orchestrator
        return orchestrator

    def _maintenance_attempt_lifecycle_owner(self) -> MaintenanceRepairAttemptLifecycle:
        owner = self.maintenance_attempt_lifecycle
        if owner is not None:
            return owner
        ledger = self._maintenance_ledger()
        try:
            owner = MaintenanceRepairAttemptLifecycle(self.store, ledger)
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance attempt lifecycle is unavailable") from exc
        self.maintenance_attempt_lifecycle = owner
        return owner

    def _maintenance_publication_preparation_owner(self) -> MaintenancePublicationPreparation:
        owner = self.maintenance_publication_preparation
        if owner is not None:
            return owner
        ledger = self._maintenance_ledger()
        try:
            owner = MaintenancePublicationPreparation(self.store, ledger)
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance publication preparation is unavailable") from exc
        self.maintenance_publication_preparation = owner
        return owner

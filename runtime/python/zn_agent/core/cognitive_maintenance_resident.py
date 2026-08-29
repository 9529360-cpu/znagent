from __future__ import annotations

"""Resident composition that adds bounded cognitive self-maintenance.

This layer does not broaden ordinary body or Work authority. It composes the
existing health-aware resident with the maintenance-specific cognitive authoring
and semantic review boundary.
"""

import sqlite3
from pathlib import Path
from typing import Any

from .health_aware_resident import HealthAwareResidentRuntime
from .maintenance_cognitive import MaintenanceCognitiveRepairOrchestrator


class CognitiveMaintenanceResidentRuntime(HealthAwareResidentRuntime):
    """Health-aware resident with bounded candidate derivation and review."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.maintenance_cognition: MaintenanceCognitiveRepairOrchestrator | None = None
        self._install_maintenance_cognition()

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
                return data
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
        return data

    def run_cognitive_maintenance_repair(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        attempt_root: str | Path,
        branch_ref: str,
    ) -> dict[str, Any]:
        """Derive, execute, and semantically review one isolated repair attempt.

        Model calls receive only bounded maintenance evidence/source context. They
        do not receive body tools, terminal/Git access, arbitrary file access,
        commit/push/merge, release, updater, replacement, or rollback authority.
        The existing isolated repair operator remains the sole source-write owner.
        """

        return self._maintenance_cognitive_orchestrator().derive_execute_and_review(
            task_id,
            source_root=source_root,
            attempt_root=attempt_root,
            branch_ref=branch_ref,
        )

    def _install_maintenance_cognition(self) -> None:
        if self.maintenance is None or self.maintenance_repair is None:
            return
        try:
            self.maintenance_cognition = MaintenanceCognitiveRepairOrchestrator(
                self.store,
                self.maintenance,
                self.maintenance_repair,
                self.kernel,
            )
        except sqlite3.Error:
            self.maintenance_cognition = None

    def _maintenance_cognitive_orchestrator(self) -> MaintenanceCognitiveRepairOrchestrator:
        orchestrator = self.maintenance_cognition
        if orchestrator is not None:
            return orchestrator
        ledger = self._maintenance_ledger()
        operator = self._maintenance_repair_operator()
        try:
            orchestrator = MaintenanceCognitiveRepairOrchestrator(
                self.store,
                ledger,
                operator,
                self.kernel,
            )
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance cognitive orchestrator is unavailable") from exc
        self.maintenance_cognition = orchestrator
        return orchestrator

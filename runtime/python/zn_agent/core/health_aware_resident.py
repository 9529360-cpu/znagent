from __future__ import annotations

"""Resident ownership for self-maintenance health evidence.

This layer does not repair source, grant maintenance authority, or mutate a
running installation. It makes durable health/task evidence part of the formal
resident subject, gives maintenance candidates an authority-free investigation
lifecycle, and connects selected active resident Sense boundaries to the same
journal without allowing secondary observation failures to break those Senses or
resident health truth.
"""

import sqlite3
from typing import Any

from .browser_work_resident import BrowserWorkResidentRuntime
from .foreground_window_sense import ForegroundWindowObservation
from .health_observation import ResidentHealthJournal
from .maintenance_investigation import MaintenanceInvestigationLedger


class HealthAwareResidentRuntime(BrowserWorkResidentRuntime):
    """Final resident composition with durable self-health inspection."""

    _FOREGROUND_WINDOW_HEALTH_ORGAN = "sense:foreground_window"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.health = ResidentHealthJournal(self.store)
        # Health/task truth is initialized first. The investigation projection is
        # strictly secondary: an unavailable projection must not prevent the same
        # resident from booting with its identity, health and work state intact.
        try:
            self.maintenance: MaintenanceInvestigationLedger | None = (
                MaintenanceInvestigationLedger(self.store)
            )
        except sqlite3.Error:
            self.maintenance = None

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["resident_health"] = self.health.snapshot()
        data["maintenance_tasks"] = self.health.maintenance_tasks()
        data["maintenance_investigations"] = self._maintenance_status()
        return data

    def _maintenance_status(self) -> dict[str, Any]:
        ledger = self.maintenance
        if ledger is not None:
            try:
                snapshot = ledger.snapshot()
            except sqlite3.Error:
                pass
            else:
                return {"available": True, **snapshot}
        return {
            "available": False,
            "investigation_count": 0,
            "active_count": 0,
            "returned_count": 0,
            "truncated": False,
            "investigations": [],
        }

    def _probe_foreground_window(
        self,
    ) -> tuple[ForegroundWindowObservation | None, str | None]:
        """Observe the active foreground-window Sense at its real call boundary.

        Pointer/UI completion already centralizes foreground-window probing here.
        Record one health observation per actual probe attempt rather than polling
        persisted errors later, so repeated failures represent repeated real Sense
        failures and a successful probe closes the same organ's failure streak.
        Health persistence is secondary and must never become a new Sense failure.
        """
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned foreground window Sense is unavailable"
        try:
            observed = sense.probe()
        except Exception as exc:
            try:
                self.health.record_failure(self._FOREGROUND_WINDOW_HEALTH_ORGAN, exc)
            except Exception:
                pass
            return None, f"{type(exc).__name__}: {exc}"

        try:
            self.health.record_success(self._FOREGROUND_WINDOW_HEALTH_ORGAN)
        except Exception:
            pass
        return observed, None

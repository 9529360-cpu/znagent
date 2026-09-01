from __future__ import annotations

"""Final resident composition for privacy-safe upstream defect reporting.

The resident health journal remains canonical. Report projection is secondary and
best-effort: a broken outbox must never roll back or mask a real health failure.
Health projection only prepares a local durable report envelope. An optional
operator-controlled transport may be invoked explicitly; it does not grant
repository, push, PR, merge, release, updater, signing, or credential authority.
"""

import sqlite3
from typing import Any, Callable

from .natural_browser_desktop_submit_resident import NaturalBrowserDesktopSubmitResidentRuntime
from .upstream_bug_report import ResidentUpstreamBugReportOutbox
from .upstream_bug_report_transport import UpstreamBugReportTransport


class ReportingMaintenanceResidentRuntime(NaturalBrowserDesktopSubmitResidentRuntime):
    """Resident with bounded automatic health -> upstream-report projection."""

    def __init__(
        self,
        *,
        kernel,
        capabilities=None,
        budget=None,
        report_transport: UpstreamBugReportTransport | None = None,
    ):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # Browser form/text composition installs the final browser-aware Body after
        # the inherited HealthAwareResidentRuntime observed an earlier Body. Re-bind
        # health to the actual final active Body before report projection so native
        # Body failures remain durable health truth.
        self._install_body_dispatch_health_observer()
        self.upstream_bug_reports: ResidentUpstreamBugReportOutbox | None = None
        self.upstream_bug_report_transport = report_transport
        self._install_upstream_bug_report_outbox()
        self._install_health_report_projection()
        self._repair_pending_report_projection_best_effort()

    def status(self) -> dict[str, Any]:
        data = super().status()
        owner = self.upstream_bug_reports
        if owner is None:
            try:
                owner = self._upstream_bug_report_owner()
            except (sqlite3.Error, RuntimeError):
                data["upstream_bug_reports"] = self._unavailable_report_status(
                    transport_available=self.upstream_bug_report_transport is not None
                )
                return data
        try:
            snapshot = owner.snapshot()
        except sqlite3.Error:
            self.upstream_bug_reports = None
            data["upstream_bug_reports"] = self._unavailable_report_status(
                transport_available=self.upstream_bug_report_transport is not None
            )
        else:
            transport_available = self.upstream_bug_report_transport is not None
            data["upstream_bug_reports"] = {
                "available": True,
                "authority": (
                    "bounded_operator_transport"
                    if transport_available
                    else "local_outbox_only"
                ),
                "transport_available": transport_available,
                **snapshot,
            }
        return data

    def prepare_upstream_bug_report(self, task_id: str) -> dict[str, Any]:
        """Prepare/recover the bounded report for one durable maintenance task."""

        task = self._maintenance_task_by_id(task_id)
        return self._upstream_bug_report_owner().prepare(task)

    def dispatch_upstream_bug_report(self, report_key: str) -> dict[str, Any]:
        """Explicitly dispatch one pending report through configured operator transport."""

        transport = self.upstream_bug_report_transport
        if transport is None:
            raise RuntimeError("upstream bug report transport is not configured")
        return transport.dispatch(self._upstream_bug_report_owner(), report_key)

    def reconcile_upstream_bug_report(self, report_key: str) -> dict[str, Any]:
        """Reconcile one uncertain dispatch without blindly replaying it."""

        transport = self.upstream_bug_report_transport
        if transport is None:
            raise RuntimeError("upstream bug report transport is not configured")
        return transport.reconcile(self._upstream_bug_report_owner(), report_key)

    def _install_upstream_bug_report_outbox(self) -> None:
        try:
            self.upstream_bug_reports = ResidentUpstreamBugReportOutbox(self.store)
        except sqlite3.Error:
            self.upstream_bug_reports = None

    def _install_health_report_projection(self) -> None:
        health = self.health
        current = getattr(health, "record_failure", None)
        if not callable(current):
            return
        if bool(getattr(health, "_zn_upstream_report_projection_installed", False)):
            return

        record_failure: Callable[..., dict[str, Any]] = current

        def observed_record_failure(organ: str, error: BaseException) -> dict[str, Any]:
            snapshot = record_failure(organ, error)
            if bool(snapshot.get("maintenance_candidate")):
                self._project_health_candidate_best_effort(str(snapshot.get("organ") or organ))
            return snapshot

        setattr(health, "record_failure", observed_record_failure)
        setattr(health, "_zn_upstream_report_projection_installed", True)

    def _project_health_candidate_best_effort(self, organ: str) -> None:
        try:
            task = self.health.maintenance_task(organ)
            if task is None or str(task.get("status") or "") != "open":
                return
            self._upstream_bug_report_owner().prepare(task)
        except (sqlite3.Error, RuntimeError, ValueError, KeyError):
            return

    def _repair_pending_report_projection_best_effort(self) -> None:
        """Rebuild missing report rows from durable open maintenance-task truth."""

        try:
            tasks = self.health.maintenance_tasks(limit=512).get("tasks") or []
        except sqlite3.Error:
            return
        for task in tasks:
            if str(task.get("status") or "") != "open":
                continue
            try:
                self._upstream_bug_report_owner().prepare(task)
            except (sqlite3.Error, RuntimeError, ValueError, KeyError):
                continue

    def _maintenance_task_by_id(self, task_id: str) -> dict[str, Any]:
        expected = str(task_id or "").strip()
        if not expected:
            raise ValueError("maintenance task id must not be empty")
        tasks = self.health.maintenance_tasks(limit=512).get("tasks") or []
        for task in tasks:
            if str(task.get("task_id") or "") == expected:
                return task
        raise KeyError("maintenance task does not exist")

    def _upstream_bug_report_owner(self) -> ResidentUpstreamBugReportOutbox:
        owner = self.upstream_bug_reports
        if owner is not None:
            return owner
        try:
            owner = ResidentUpstreamBugReportOutbox(self.store)
        except sqlite3.Error as exc:
            raise RuntimeError("upstream bug report outbox is unavailable") from exc
        self.upstream_bug_reports = owner
        return owner

    @staticmethod
    def _unavailable_report_status(*, transport_available: bool) -> dict[str, Any]:
        return {
            "available": False,
            "authority": (
                "bounded_operator_transport"
                if transport_available
                else "local_outbox_only"
            ),
            "transport_available": transport_available,
            "report_count": 0,
            "pending_count": 0,
            "outcome_uncertain_count": 0,
            "returned_count": 0,
            "truncated": False,
            "reports": [],
        }

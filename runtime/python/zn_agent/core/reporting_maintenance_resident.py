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

from .natural_file_work_resident import NaturalFileWorkResidentRuntime
from .upstream_bug_report import ResidentUpstreamBugReportOutbox
from .upstream_bug_report_transport import UpstreamBugReportTransport


class ReportingMaintenanceResidentRuntime(NaturalFileWorkResidentRuntime):
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

    def _install_upstream_bug_report_outbox(self) -> None:
        try:
            self.upstream_bug_reports = ResidentUpstreamBugReportOutbox(self)
        except Exception as exc:
            self._record_report_projection_failure(
                operation="outbox_init",
                error=exc,
            )

    def _install_health_report_projection(self) -> None:
        journal = getattr(self, "health", None)
        subscribe = getattr(journal, "subscribe", None)
        if journal is None or not callable(subscribe):
            return
        try:
            subscribe(self._project_health_to_upstream_report)
        except Exception as exc:
            self._record_report_projection_failure(
                operation="subscribe",
                error=exc,
            )
            return
        self._repair_health_report_projection()

    def _repair_health_report_projection(self) -> None:
        journal = getattr(self, "health", None)
        if journal is None:
            return
        try:
            tasks = journal.maintenance_tasks(limit=256)
        except Exception as exc:
            self._record_report_projection_failure(
                operation="reconcile_read",
                error=exc,
            )
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue
            try:
                self._project_health_to_upstream_report(task)
            except Exception as exc:
                self._record_report_projection_failure(
                    operation="reconcile_project",
                    error=exc,
                )

    def _project_health_to_upstream_report(self, task: dict[str, Any]) -> None:
        outbox = self.upstream_bug_reports
        if outbox is None:
            return
        try:
            outbox.prepare(task)
        except Exception as exc:
            self._record_report_projection_failure(
                operation="prepare",
                error=exc,
            )

    def _record_report_projection_failure(
        self,
        *,
        operation: str,
        error: BaseException,
    ) -> None:
        journal = getattr(self, "health", None)
        record = getattr(journal, "record_failure", None)
        if not callable(record):
            return
        try:
            record(
                organ="upstream_bug_report",
                failure_kind="projection",
                error=error,
                source=f"reporting_maintenance:{operation}",
            )
        except Exception:
            # Health truth is primary. A report projection failure is explicitly
            # not permitted to replace or roll back the original resident event.
            pass

    def configure_upstream_bug_report_transport(
        self,
        transport: UpstreamBugReportTransport | None,
    ) -> None:
        self.upstream_bug_report_transport = transport

    def dispatch_upstream_bug_report(
        self,
        report_key: str,
    ) -> dict[str, Any]:
        outbox = self.upstream_bug_reports
        transport = self.upstream_bug_report_transport
        if outbox is None:
            raise RuntimeError("upstream bug report outbox is unavailable")
        if transport is None:
            raise RuntimeError("upstream bug report transport is not configured")
        return transport.dispatch(outbox, report_key)

    def reconcile_upstream_bug_report(
        self,
        report_key: str,
    ) -> dict[str, Any]:
        outbox = self.upstream_bug_reports
        transport = self.upstream_bug_report_transport
        if outbox is None:
            raise RuntimeError("upstream bug report outbox is unavailable")
        if transport is None:
            raise RuntimeError("upstream bug report transport is not configured")
        return transport.reconcile(outbox, report_key)

    def list_upstream_bug_reports(self, limit: int = 64) -> list[dict[str, Any]]:
        outbox = self.upstream_bug_reports
        if outbox is None:
            return []
        try:
            return outbox.list_reports(limit=limit)
        except (OSError, RuntimeError, sqlite3.DatabaseError):
            return []

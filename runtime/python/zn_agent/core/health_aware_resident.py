from __future__ import annotations

"""Resident ownership for self-maintenance health evidence.

This layer keeps durable health/task evidence part of the formal resident subject,
connects bounded source investigation and isolated source-repair attempts, and
observes selected active resident Sense/resource boundaries without allowing
secondary maintenance evidence failures to break resident health truth.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .browser_work_resident import BrowserWorkResidentRuntime
from .foreground_window_sense import ForegroundWindowObservation
from .health_observation import ResidentHealthJournal
from .maintenance_investigation import MaintenanceInvestigationLedger
from .maintenance_repair import MaintenanceIsolatedRepairOperator
from .maintenance_source import MaintenanceSourceInvestigator
from .models import ModelRoute


class HealthAwareResidentRuntime(BrowserWorkResidentRuntime):
    """Final resident composition with durable self-health inspection."""

    _FOREGROUND_WINDOW_HEALTH_ORGAN = "sense:foreground_window"
    _KNOWN_BODY_ACTION_KINDS = frozenset(
        {
            "sense",
            "inspect_path",
            "path",
            "read_text",
            "read_file",
            "write_text",
            "write_file",
            "list_directory",
            "list_dir",
            "process_state",
            "process",
            "pointer_state",
            "pointer_move",
            "pointer_click",
            "git_state",
            "git",
            "git_diff",
            "command",
            "terminal",
            "shell",
            "terminal_poll",
            "command_poll",
            "terminal_stop",
            "command_stop",
            "terminal_input",
            "terminal_write",
            "command_input",
            "terminal_resize",
            "command_resize",
            "browser_navigate",
            "browser_navigate_focus",
            "browser_observe",
            "browser_close",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.health = ResidentHealthJournal(self.store)
        self._install_cognitive_resource_health_observer()
        self._install_body_dispatch_health_observer()
        # Health/task truth is initialized first. Investigation/source/repair
        # projections are secondary and must never prevent the same resident from
        # booting with its identity, health and work state intact.
        try:
            self.maintenance: MaintenanceInvestigationLedger | None = (
                MaintenanceInvestigationLedger(self.store)
            )
        except sqlite3.Error:
            self.maintenance = None
        self.maintenance_source: MaintenanceSourceInvestigator | None = None
        self.maintenance_repair: MaintenanceIsolatedRepairOperator | None = None
        if self.maintenance is not None:
            try:
                self.maintenance_source = MaintenanceSourceInvestigator(
                    self.store,
                    self.maintenance,
                )
            except sqlite3.Error:
                self.maintenance_source = None
            try:
                self.maintenance_repair = MaintenanceIsolatedRepairOperator(
                    self.store,
                    self.maintenance,
                )
            except sqlite3.Error:
                self.maintenance_repair = None

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["resident_health"] = self.health.snapshot()
        data["maintenance_tasks"] = self.health.maintenance_tasks()
        data["maintenance_investigations"] = self._maintenance_status()
        data["maintenance_source_evidence"] = self._maintenance_source_status()
        data["maintenance_repair_attempts"] = self._maintenance_repair_status()
        return data

    def investigate_maintenance_source(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        regression_oracle: str,
    ) -> dict[str, Any]:
        """Run the resident's bounded read-only source-investigation path."""

        investigator = self._maintenance_source_investigator()
        return investigator.investigate(
            task_id,
            source_root=source_root,
            regression_oracle=regression_oracle,
        )

    def run_maintenance_repair_attempt(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        attempt_root: str | Path,
        branch_ref: str,
        replacements: Mapping[str, str],
    ) -> dict[str, Any]:
        """Form one isolated repair candidate under the SM3 authority boundary.

        This entry point does not use ordinary Work attachment, NativeBody writes,
        generic terminal/shell execution, commit/push/merge, release, or updater
        authority. The dedicated operator re-verifies the observed baseline before
        creating a fresh ``work/*`` worktree and applies only bounded declared ZN
        core Python/test replacements there.
        """

        operator = self._maintenance_repair_operator()
        return operator.execute(
            task_id,
            source_root=source_root,
            attempt_root=attempt_root,
            branch_ref=branch_ref,
            replacements=replacements,
        )

    def _maintenance_status(self) -> dict[str, Any]:
        ledger = self.maintenance
        if ledger is not None:
            try:
                snapshot = ledger.snapshot()
            except sqlite3.Error:
                ledger = None
            else:
                return {"available": True, **snapshot}

        try:
            ledger = MaintenanceInvestigationLedger(self.store)
            snapshot = ledger.snapshot()
        except sqlite3.Error:
            self.maintenance = None
            self.maintenance_source = None
            self.maintenance_repair = None
            return {
                "available": False,
                "investigation_count": 0,
                "active_count": 0,
                "returned_count": 0,
                "truncated": False,
                "investigations": [],
            }
        self.maintenance = ledger
        try:
            self.maintenance_source = MaintenanceSourceInvestigator(self.store, ledger)
        except sqlite3.Error:
            self.maintenance_source = None
        try:
            self.maintenance_repair = MaintenanceIsolatedRepairOperator(self.store, ledger)
        except sqlite3.Error:
            self.maintenance_repair = None
        return {"available": True, **snapshot}

    def _maintenance_source_status(self) -> dict[str, Any]:
        investigator = self.maintenance_source
        if investigator is not None:
            try:
                snapshot = investigator.snapshot()
            except sqlite3.Error:
                investigator = None
            else:
                return {"available": True, **snapshot}
        try:
            investigator = self._maintenance_source_investigator()
            snapshot = investigator.snapshot()
        except (sqlite3.Error, RuntimeError):
            self.maintenance_source = None
            return {
                "available": False,
                "evidence_count": 0,
                "returned_count": 0,
                "truncated": False,
                "evidence": [],
            }
        return {"available": True, **snapshot}

    def _maintenance_repair_status(self) -> dict[str, Any]:
        operator = self.maintenance_repair
        if operator is not None:
            try:
                snapshot = operator.snapshot()
            except sqlite3.Error:
                operator = None
            else:
                return {"available": True, **snapshot}
        try:
            operator = self._maintenance_repair_operator()
            snapshot = operator.snapshot()
        except (sqlite3.Error, RuntimeError):
            self.maintenance_repair = None
            return {
                "available": False,
                "attempt_evidence_count": 0,
                "returned_count": 0,
                "truncated": False,
                "attempts": [],
            }
        return {"available": True, **snapshot}

    def _maintenance_source_investigator(self) -> MaintenanceSourceInvestigator:
        investigator = self.maintenance_source
        if investigator is not None:
            return investigator
        ledger = self._maintenance_ledger()
        try:
            investigator = MaintenanceSourceInvestigator(self.store, ledger)
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance source investigator is unavailable") from exc
        self.maintenance_source = investigator
        return investigator

    def _maintenance_repair_operator(self) -> MaintenanceIsolatedRepairOperator:
        operator = self.maintenance_repair
        if operator is not None:
            return operator
        ledger = self._maintenance_ledger()
        try:
            operator = MaintenanceIsolatedRepairOperator(self.store, ledger)
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance isolated repair operator is unavailable") from exc
        self.maintenance_repair = operator
        return operator

    def _maintenance_ledger(self) -> MaintenanceInvestigationLedger:
        ledger = self.maintenance
        if ledger is not None:
            return ledger
        try:
            ledger = MaintenanceInvestigationLedger(self.store)
        except sqlite3.Error as exc:
            raise RuntimeError("maintenance investigation ledger is unavailable") from exc
        self.maintenance = ledger
        return ledger

    def _install_cognitive_resource_health_observer(self) -> None:
        """Bind provider observation after resident health exists."""

        observer = self._observe_cognitive_resource_health
        setattr(self.kernel, "resource_health_observer", observer)
        factory = getattr(self.kernel, "worker_factory", None)
        setter = getattr(factory, "set_health_observer", None)
        if callable(setter):
            try:
                setter(observer)
            except Exception:
                pass

    def _observe_cognitive_resource_health(
        self,
        route: ModelRoute,
        error: BaseException | None,
    ) -> None:
        organ = self._cognitive_resource_health_organ(route)
        if error is None:
            self.health.record_success(organ)
        else:
            self.health.record_failure(organ, error)

    @staticmethod
    def _cognitive_resource_health_organ(route: ModelRoute) -> str:
        """Use a stable privacy-safe route identity without persisting model text."""

        raw_provider = str(route.provider or "unknown").strip().lower() or "unknown"
        provider = "".join(
            char if char.isalnum() else "-" for char in raw_provider
        ).strip("-")[:32] or "unknown"
        digest = hashlib.sha256()
        digest.update(b"zn-cognitive-health-route-v1\x00")
        digest.update(raw_provider.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
        digest.update(str(route.route_id or "").encode("utf-8", errors="replace"))
        return f"cognition:{provider}:{digest.hexdigest()[:16]}"

    def _install_body_dispatch_health_observer(self) -> None:
        """Observe real Body dispatch exceptions before NativeBody flattens them."""

        body = getattr(self, "body", None)
        dispatch = getattr(body, "_dispatch", None)
        if body is None or not callable(dispatch):
            return
        if bool(getattr(body, "_zn_health_dispatch_observer_installed", False)):
            return

        def observed_dispatch(action, started):
            organ = self._body_health_organ(getattr(action, "kind", ""))
            try:
                result = dispatch(action, started)
            except Exception as exc:
                try:
                    self.health.record_failure(organ, exc)
                except Exception:
                    pass
                raise

            if bool(getattr(result, "success", False)):
                try:
                    self.health.record_success(organ)
                except Exception:
                    pass
            return result

        setattr(body, "_dispatch", observed_dispatch)
        setattr(body, "_zn_health_dispatch_observer_installed", True)

    @classmethod
    def _body_health_organ(cls, kind: str) -> str:
        """Keep known Body kinds readable and arbitrary caller strings private."""

        normalized = str(kind or "").strip().lower()
        if normalized in cls._KNOWN_BODY_ACTION_KINDS:
            return f"body:{normalized}"
        digest = hashlib.sha256()
        digest.update(b"zn-body-health-kind-v1\x00")
        digest.update(normalized.encode("utf-8", errors="replace"))
        return f"body:action-{digest.hexdigest()[:16]}"

    def _probe_foreground_window(
        self,
    ) -> tuple[ForegroundWindowObservation | None, str | None]:
        """Observe the active foreground-window Sense at its real call boundary."""
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

from __future__ import annotations

"""Resident ownership for self-maintenance health evidence.

This layer does not repair source, grant maintenance authority, or mutate a
running installation. It makes durable health/task evidence part of the formal
resident subject, gives maintenance candidates an authority-free investigation
lifecycle, and connects selected active resident Sense/resource boundaries to
the same journal without allowing secondary observation failures to break those
organs or resident health truth.
"""

import hashlib
import sqlite3
from typing import Any

from .browser_work_resident import BrowserWorkResidentRuntime
from .foreground_window_sense import ForegroundWindowObservation
from .health_observation import ResidentHealthJournal
from .maintenance_investigation import MaintenanceInvestigationLedger
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
            "browser_observe",
            "browser_close",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.health = ResidentHealthJournal(self.store)
        self._install_cognitive_resource_health_observer()
        self._install_body_dispatch_health_observer()
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
                ledger = None
            else:
                return {"available": True, **snapshot}

        # The investigation surface is reconstructible from maintenance-task
        # truth. Retry construction once so loss of a secondary table can heal
        # in-place without requiring a resident restart. Persistent SQLite
        # failure remains a bounded unavailable status, not a resident failure.
        try:
            ledger = MaintenanceInvestigationLedger(self.store)
            snapshot = ledger.snapshot()
        except sqlite3.Error:
            self.maintenance = None
            return {
                "available": False,
                "investigation_count": 0,
                "active_count": 0,
                "returned_count": 0,
                "truncated": False,
                "investigations": [],
            }
        self.maintenance = ledger
        return {"available": True, **snapshot}

    def _install_cognitive_resource_health_observer(self) -> None:
        """Bind provider observation after resident health exists.

        The kernel is assembled before the resident, so provider factories cannot
        own or construct the health journal. Bind the resident callback only after
        the same resident/store exists, and leave the callback on the kernel so
        the normal provider hot-reconfiguration path can bind replacement
        factories without replacing ZN identity or health state.
        """

        observer = self._observe_cognitive_resource_health
        setattr(self.kernel, "resource_health_observer", observer)
        factory = getattr(self.kernel, "worker_factory", None)
        setter = getattr(factory, "set_health_observer", None)
        if callable(setter):
            try:
                setter(observer)
            except Exception:
                # Provider health is observational; factory behavior remains the
                # primary path if observer binding itself is unavailable.
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
        """Observe real Body dispatch exceptions before NativeBody flattens them.

        The final Body is assembled by the resident inheritance chain before this
        health journal exists. Wrap only its dispatch seam in place so the mature
        browser/recovery/atomic-overwrite Body remains the active object. This is
        observational: it does not change action admission, dispatch, result
        flattening, verification, replay protection, or durable action evidence.
        """

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

            # Only a successful concrete dispatch proves recovery. Some Body
            # implementations intentionally return success=False as bounded task
            # evidence without raising an exception; do not misclassify that as
            # either an organ exception or a recovery event.
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

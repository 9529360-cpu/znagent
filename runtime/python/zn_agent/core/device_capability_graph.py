from __future__ import annotations

"""Public V1 DeviceCapabilityGraph with conservative application name resolution.

The lower-level Windows fact collectors live in ``machine_capability``.  This
composition tightens human-facing resolution so a long unknown name can never be
accepted merely because it starts with a shorter installed alias.  Exact aliases
are resolved before bounded prefix/substring matching; fuzzy candidates can never
make an otherwise unique exact application ambiguous.

The public graph also owns read-only Windows companion, display and foreground
senses. This keeps session/power/network/multi-monitor/current-window facts in the
existing Resident device graph instead of creating a parallel OS agent or context
store.
"""

from dataclasses import dataclass
from typing import Any

from .machine_capability import (
    ApplicationResolution,
    DeviceCapabilityGraph as _MachineFactGraph,
    DeviceCapabilitySnapshot,
    InstalledApplication,
    _aliases,
    _normalize_name,
)
from .models import utc_now
from .windows_companion_context import (
    NativeWindowsCompanionContextSense,
    WindowsCompanionContextSnapshot,
)
from .windows_display_context import (
    NativeWindowsDisplayContextSense,
    WindowsDisplayObservation,
)
from .windows_foreground_companion import (
    NativeWindowsForegroundCompanionSense,
    WindowsForegroundCompanionObservation,
)


@dataclass(frozen=True, slots=True)
class ResidentDeviceContextSnapshot:
    machine: DeviceCapabilitySnapshot
    companion: WindowsCompanionContextSnapshot
    display: WindowsDisplayObservation
    foreground: WindowsForegroundCompanionObservation
    observed_at: str


class DeviceCapabilityGraph(_MachineFactGraph):
    """Deterministic machine facts plus fail-closed application resolution."""

    def __init__(
        self,
        *args: Any,
        companion_context_sense: NativeWindowsCompanionContextSense | None = None,
        display_context_sense: NativeWindowsDisplayContextSense | None = None,
        foreground_companion_sense: NativeWindowsForegroundCompanionSense | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._companion_context_sense = (
            companion_context_sense or NativeWindowsCompanionContextSense()
        )
        self._display_context_sense = (
            display_context_sense or NativeWindowsDisplayContextSense()
        )
        self._foreground_companion_sense = (
            foreground_companion_sense or NativeWindowsForegroundCompanionSense()
        )

    def companion_context(self) -> WindowsCompanionContextSnapshot:
        """Fresh read-only Windows session/power/network context."""

        return self._companion_context_sense.probe()

    def display_context(self) -> WindowsDisplayObservation:
        """Fresh read-only Windows multi-monitor topology without device identifiers."""

        return self._display_context_sense.probe()

    def foreground_companion_context(self) -> WindowsForegroundCompanionObservation:
        """Fresh current-window identity with raw title/class content redacted."""

        return self._foreground_companion_sense.probe()

    def resident_context_snapshot(
        self,
        *,
        force_inventory_refresh: bool = False,
    ) -> ResidentDeviceContextSnapshot:
        """Compose current machine and companion facts without caching them."""

        return ResidentDeviceContextSnapshot(
            machine=self.snapshot(force_inventory_refresh=force_inventory_refresh),
            companion=self.companion_context(),
            display=self.display_context(),
            foreground=self.foreground_companion_context(),
            observed_at=utc_now(),
        )

    @staticmethod
    def _ordered_candidates(
        matches: dict[str, InstalledApplication],
    ) -> tuple[InstalledApplication, ...]:
        return tuple(
            sorted(
                matches.values(),
                key=lambda app: (app.canonical_name.casefold(), app.app_id),
            )
        )

    def resolve_application(
        self,
        query: str,
        *,
        force_refresh: bool = False,
    ) -> ApplicationResolution:
        raw = " ".join(str(query or "").strip().split())
        wanted = _normalize_name(raw)
        if not wanted:
            return ApplicationResolution(raw, "not_installed")

        applications = self.installed_applications(force_refresh=force_refresh)

        # Exact aliases are authoritative for human-facing resolution.  This
        # keeps "Notepad" from becoming ambiguous merely because "Notepad++"
        # is installed, while two distinct identities both exactly named
        # "Notepad" still fail closed as genuinely ambiguous.
        exact: dict[str, InstalledApplication] = {}
        for application in applications:
            if wanted in _aliases(application):
                exact[application.app_id] = application
        exact_candidates = self._ordered_candidates(exact)
        if len(exact_candidates) == 1:
            return ApplicationResolution(raw, "resolved", exact_candidates[0])
        if len(exact_candidates) > 1:
            return ApplicationResolution(raw, "ambiguous", candidates=exact_candidates)

        if len(wanted) < 2:
            return ApplicationResolution(raw, "not_installed")

        partial: dict[str, InstalledApplication] = {}
        for application in applications:
            if any(
                alias.startswith(wanted)
                or (len(wanted) >= 4 and wanted in alias)
                for alias in _aliases(application)
            ):
                partial[application.app_id] = application
        partial_candidates = self._ordered_candidates(partial)
        if len(partial_candidates) == 1:
            return ApplicationResolution(raw, "resolved", partial_candidates[0])
        if len(partial_candidates) > 1:
            return ApplicationResolution(raw, "ambiguous", candidates=partial_candidates)
        return ApplicationResolution(raw, "not_installed")

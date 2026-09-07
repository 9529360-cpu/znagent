from __future__ import annotations

"""Public V1 DeviceCapabilityGraph with conservative application name resolution.

The lower-level Windows fact collectors live in ``machine_capability``.  This
composition tightens human-facing resolution so a long unknown name can never be
accepted merely because it starts with a shorter installed alias.  Exact aliases
are resolved before bounded prefix/substring matching; fuzzy candidates can never
make an otherwise unique exact application ambiguous.
"""

from .machine_capability import (
    ApplicationResolution,
    DeviceCapabilityGraph as _MachineFactGraph,
    InstalledApplication,
    _aliases,
    _normalize_name,
)


class DeviceCapabilityGraph(_MachineFactGraph):
    """Deterministic machine facts plus fail-closed application resolution."""

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

from __future__ import annotations

"""Public V1 DeviceCapabilityGraph with conservative application name resolution.

The lower-level Windows fact collectors live in ``machine_capability``.  This
composition tightens human-facing resolution so a long unknown name can never be
accepted merely because it starts with a shorter installed alias.  Prefix and
substring matching only flow from the user query into a candidate alias, never
from a candidate alias into arbitrary trailing user text.
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

        matches: dict[str, InstalledApplication] = {}
        for application in self.installed_applications(force_refresh=force_refresh):
            aliases = _aliases(application)
            if wanted in aliases:
                matches[application.app_id] = application
                continue
            if len(wanted) < 2:
                continue
            if any(
                alias.startswith(wanted)
                or (len(wanted) >= 4 and wanted in alias)
                for alias in aliases
            ):
                matches[application.app_id] = application

        candidates = tuple(
            sorted(
                matches.values(),
                key=lambda app: (app.canonical_name.casefold(), app.app_id),
            )
        )
        if len(candidates) == 1:
            return ApplicationResolution(raw, "resolved", candidates[0])
        if len(candidates) > 1:
            return ApplicationResolution(raw, "ambiguous", candidates=candidates)
        return ApplicationResolution(raw, "not_installed")

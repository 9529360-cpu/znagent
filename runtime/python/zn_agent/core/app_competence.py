from __future__ import annotations

"""Version-aware application competence metadata for ZN.

This registry is data-only. It selects app/version-specific bindings to existing
Action Fabric action IDs; it does not execute actions, grant authority, persist a
second capability universe, or bypass Body verification.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _key(value: object) -> str:
    return _clean(value).casefold()


@dataclass(frozen=True, slots=True)
class AppCompetenceBinding:
    capability: str
    action_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        capability = _key(self.capability)
        action_id = _clean(self.action_id)
        if not capability:
            raise ValueError("competence capability must not be empty")
        if not action_id:
            raise ValueError("competence action_id must not be empty")
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


@dataclass(frozen=True, slots=True)
class AppCompetencePack:
    pack_id: str
    app_id: str
    app_version: str
    bindings: tuple[AppCompetenceBinding, ...]
    aliases: tuple[str, ...] = ()
    schema_version: int = 1
    source: str = "builtin"

    def __post_init__(self) -> None:
        pack_id = _clean(self.pack_id)
        app_id = _key(self.app_id)
        app_version = _clean(self.app_version)
        if not pack_id:
            raise ValueError("competence pack_id must not be empty")
        if not app_id:
            raise ValueError("competence app_id must not be empty")
        if not app_version:
            raise ValueError("competence app_version must not be empty")
        if self.schema_version != 1:
            raise ValueError(f"unsupported competence schema_version: {self.schema_version}")
        bindings = tuple(self.bindings or ())
        if not bindings:
            raise ValueError("competence pack must contain at least one binding")
        capabilities = [binding.capability for binding in bindings]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("competence pack contains duplicate capabilities")
        aliases = tuple(dict.fromkeys(_key(alias) for alias in self.aliases if _key(alias)))
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "app_version", app_version)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "source", _clean(self.source) or "builtin")

    def binding(self, capability: str) -> AppCompetenceBinding | None:
        wanted = _key(capability)
        return next((item for item in self.bindings if item.capability == wanted), None)


class AppCompetenceRegistry:
    """Select exact app/version competence without becoming an executor."""

    def __init__(self) -> None:
        self._packs: dict[tuple[str, str], AppCompetencePack] = {}
        self._aliases: dict[str, str] = {}

    def register(self, pack: AppCompetencePack) -> None:
        key = (pack.app_id, pack.app_version)
        if key in self._packs:
            raise ValueError(f"competence already registered for {pack.app_id}@{pack.app_version}")
        for alias in (pack.app_id, *pack.aliases):
            owner = self._aliases.get(alias)
            if owner is not None and owner != pack.app_id:
                raise ValueError(f"competence alias already owned by another app: {alias}")
        self._packs[key] = pack
        for alias in (pack.app_id, *pack.aliases):
            self._aliases[alias] = pack.app_id

    def resolve(self, app: str, version: str) -> AppCompetencePack | None:
        app_key = _key(app)
        version_key = _clean(version)
        canonical = self._aliases.get(app_key, app_key)
        return self._packs.get((canonical, version_key))

    def binding(self, app: str, version: str, capability: str) -> AppCompetenceBinding | None:
        pack = self.resolve(app, version)
        return pack.binding(capability) if pack is not None else None

    def validate_action_fabric(self, action_fabric: object) -> None:
        descriptor = getattr(action_fabric, "descriptor", None)
        if not callable(descriptor):
            raise TypeError("action_fabric must expose descriptor(action_id)")
        missing = sorted({
            binding.action_id
            for pack in self._packs.values()
            for binding in pack.bindings
            if descriptor(binding.action_id) is None
        })
        if missing:
            raise ValueError(
                "competence references unknown Action Fabric actions: " + ", ".join(missing)
            )

    def packs(self, *, app: str | None = None) -> tuple[AppCompetencePack, ...]:
        canonical = None
        if app is not None:
            app_key = _key(app)
            canonical = self._aliases.get(app_key, app_key)
        rows = [pack for pack in self._packs.values() if canonical is None or pack.app_id == canonical]
        return tuple(sorted(rows, key=lambda item: (item.app_id, item.app_version, item.pack_id)))

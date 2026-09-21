from __future__ import annotations

"""Version-aware application competence metadata for ZN.

Competence packs are data, not another agent runtime. They can describe a staged
sequence of existing Action Fabric actions plus explicit read-only completion
conditions. Execution, authority, replay policy, Work state and verification
remain owned by ZN's existing Action Fabric / Body / Work chain.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping


_FORBIDDEN_RUNTIME_ARGUMENTS = frozenset(
    {
        "application_id",
        "event_id",
        "hwnd",
        "window_handle",
        "pid",
        "process_id",
        "runtime_id",
        "x",
        "y",
        "screen_x",
        "screen_y",
        "coordinates",
        "cursor_position",
    }
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _key(value: object) -> str:
    return _clean(value).casefold()


def _forbidden_runtime_paths(value: object, *, path: str = "") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for raw_name, nested in value.items():
            name = str(raw_name).strip()
            key = name.casefold()
            child_path = f"{path}.{name}" if path else name
            if key in _FORBIDDEN_RUNTIME_ARGUMENTS:
                found.append(child_path)
            found.extend(_forbidden_runtime_paths(nested, path=child_path))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_forbidden_runtime_paths(nested, path=child_path))
    return tuple(found)


def _safe_arguments(value: Mapping[str, Any] | None, *, owner: str) -> dict[str, Any]:
    arguments = dict(value or {})
    forbidden = sorted(set(_forbidden_runtime_paths(arguments)))
    if forbidden:
        raise ValueError(
            f"{owner} cannot persist runtime/native action authority: " + ", ".join(forbidden)
        )
    return arguments


@dataclass(frozen=True, slots=True)
class AppCompetenceCompletion:
    """Read-only proof expected after one competence stage."""

    action_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    expected: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        action_id = _clean(self.action_id)
        if not action_id:
            raise ValueError("competence completion action_id must not be empty")
        arguments = _safe_arguments(self.arguments, owner="competence completion")
        expected = _safe_arguments(self.expected, owner="competence completion expected evidence")
        if not expected:
            raise ValueError("competence completion must declare expected read-only evidence")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "expected", expected)


@dataclass(frozen=True, slots=True)
class AppCompetenceStage:
    """One bounded semantic action in an app/version competence recipe."""

    action_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    completion: AppCompetenceCompletion | None = None
    timeout_ms: int = 3000
    execution_mode: str = "semantic_action"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        action_id = _clean(self.action_id)
        if not action_id:
            raise ValueError("competence stage action_id must not be empty")
        arguments = _safe_arguments(self.arguments, owner="competence stage")
        timeout_ms = int(self.timeout_ms)
        if not 100 <= timeout_ms <= 120_000:
            raise ValueError("competence stage timeout_ms must be within 100..120000")
        execution_mode = _key(self.execution_mode).replace(" ", "_")
        if execution_mode != "semantic_action":
            raise ValueError(
                "competence stage execution_mode must be semantic_action in schema v1"
            )
        if self.completion is not None and not isinstance(
            self.completion, AppCompetenceCompletion
        ):
            raise TypeError("competence stage completion must be AppCompetenceCompletion")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "timeout_ms", timeout_ms)
        object.__setattr__(self, "execution_mode", execution_mode)
        object.__setattr__(self, "metadata", _safe_arguments(self.metadata, owner="competence stage metadata"))


@dataclass(frozen=True, slots=True)
class AppCompetenceBinding:
    capability: str
    action_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    stages: tuple[AppCompetenceStage, ...] = ()

    def __post_init__(self) -> None:
        capability = _key(self.capability)
        action_id = _clean(self.action_id)
        if not capability:
            raise ValueError("competence capability must not be empty")
        if not action_id:
            raise ValueError("competence action_id must not be empty")
        stages = tuple(self.stages or ())
        if any(not isinstance(stage, AppCompetenceStage) for stage in stages):
            raise TypeError("competence stages must contain AppCompetenceStage values")
        if stages and stages[0].action_id != action_id:
            raise ValueError(
                "competence binding action_id must equal the first staged action_id"
            )
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "metadata", _safe_arguments(self.metadata, owner="competence binding metadata"))
        object.__setattr__(self, "stages", stages)

    def stage_plan(self) -> tuple[AppCompetenceStage, ...]:
        if self.stages:
            return self.stages
        return (
            AppCompetenceStage(
                action_id=self.action_id,
                metadata=dict(self.metadata or {}),
            ),
        )


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

    def stage_plan(
        self,
        app: str,
        version: str,
        capability: str,
    ) -> tuple[AppCompetenceStage, ...]:
        binding = self.binding(app, version, capability)
        return binding.stage_plan() if binding is not None else ()

    def validate_action_fabric(self, action_fabric: object) -> None:
        descriptor = getattr(action_fabric, "descriptor", None)
        if not callable(descriptor):
            raise TypeError("action_fabric must expose descriptor(action_id)")

        missing: set[str] = set()
        non_read_only_completions: set[str] = set()
        for pack in self._packs.values():
            for binding in pack.bindings:
                for stage in binding.stage_plan():
                    stage_descriptor = descriptor(stage.action_id)
                    if stage_descriptor is None:
                        missing.add(stage.action_id)
                    completion = stage.completion
                    if completion is None:
                        continue
                    completion_descriptor = descriptor(completion.action_id)
                    if completion_descriptor is None:
                        missing.add(completion.action_id)
                    elif str(getattr(completion_descriptor, "effect_class", "")) != "read_only":
                        non_read_only_completions.add(completion.action_id)
        if missing:
            raise ValueError(
                "competence references unknown Action Fabric actions: " + ", ".join(sorted(missing))
            )
        if non_read_only_completions:
            raise ValueError(
                "competence completion actions must be read_only: "
                + ", ".join(sorted(non_read_only_completions))
            )

    def packs(self, *, app: str | None = None) -> tuple[AppCompetencePack, ...]:
        canonical = None
        if app is not None:
            app_key = _key(app)
            canonical = self._aliases.get(app_key, app_key)
        rows = [pack for pack in self._packs.values() if canonical is None or pack.app_id == canonical]
        return tuple(sorted(rows, key=lambda item: (item.app_id, item.app_version, item.pack_id)))

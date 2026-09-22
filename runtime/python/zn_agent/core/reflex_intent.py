from __future__ import annotations

"""Deterministic resident intent and slot fast paths."""

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Literal, Mapping

from .application_goal import application_open_goal
from .current_app_text_cleanup_goal import current_app_text_cleanup_goal
from .desktop_task_goal import desktop_task_goal
from .natural_file_goal import natural_workspace_text_edit_request
from .windows_audio_intent import (
    windows_audio_volume_read_goal,
    windows_audio_volume_set_goal,
)


ReflexResolutionStatus = Literal["matched", "no_match", "ambiguous"]
ReflexRecognizer = Callable[[Any], Any | None]


@dataclass(frozen=True, slots=True)
class ReflexIntentDescriptor:
    intent_id: str
    description: str
    required_slots: tuple[str, ...] = ()
    action_id: str | None = None
    priority: int = 0
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        intent_id = str(self.intent_id or "").strip()
        description = " ".join(str(self.description or "").split())
        if not intent_id:
            raise ValueError("intent_id must not be empty")
        if not description:
            raise ValueError("intent description must not be empty")
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "required_slots",
            _normalized_tuple(self.required_slots),
        )
        object.__setattr__(
            self,
            "action_id",
            str(self.action_id or "").strip() or None,
        )
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "tags", _normalized_tuple(self.tags))


@dataclass(frozen=True, slots=True)
class ReflexIntentMatch:
    intent_id: str
    slots: Mapping[str, Any]
    action_id: str | None
    priority: int
    source: str = "resident_deterministic"

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", dict(self.slots or {}))


@dataclass(frozen=True, slots=True)
class ReflexIntentResolution:
    status: ReflexResolutionStatus
    match: ReflexIntentMatch | None = None
    candidates: tuple[ReflexIntentMatch, ...] = ()
    reason: str = ""


class ReflexIntentRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ReflexIntentDescriptor] = {}
        self._recognizers: dict[str, ReflexRecognizer] = {}

    def register(
        self,
        descriptor: ReflexIntentDescriptor,
        recognizer: ReflexRecognizer,
    ) -> None:
        if descriptor.intent_id in self._descriptors:
            raise ValueError(
                f"intent_id already registered: {descriptor.intent_id}"
            )
        if not callable(recognizer):
            raise ValueError("reflex recognizer must be callable")
        self._descriptors[descriptor.intent_id] = descriptor
        self._recognizers[descriptor.intent_id] = recognizer

    def descriptor(
        self,
        intent_id: str,
    ) -> ReflexIntentDescriptor | None:
        return self._descriptors.get(str(intent_id or "").strip())

    def descriptors(
        self,
        *,
        tags: tuple[str, ...] = (),
    ) -> tuple[ReflexIntentDescriptor, ...]:
        wanted = set(_normalized_tuple(tags))
        rows = [
            descriptor
            for descriptor in self._descriptors.values()
            if not wanted or wanted.issubset(set(descriptor.tags))
        ]
        return tuple(
            sorted(
                rows,
                key=lambda item: (-item.priority, item.intent_id),
            )
        )

    def matches(self, event: Any) -> tuple[ReflexIntentMatch, ...]:
        rows: list[ReflexIntentMatch] = []
        for descriptor in self.descriptors():
            recognizer = self._recognizers[descriptor.intent_id]
            try:
                raw = recognizer(event)
            except Exception:
                continue
            if raw is None:
                continue
            slots = _semantic_slots(raw)
            if slots is None:
                continue
            if any(
                slot not in slots or slots[slot] is None
                for slot in descriptor.required_slots
            ):
                continue
            rows.append(
                ReflexIntentMatch(
                    intent_id=descriptor.intent_id,
                    slots=slots,
                    action_id=descriptor.action_id,
                    priority=descriptor.priority,
                )
            )
        return tuple(
            sorted(
                rows,
                key=lambda item: (-item.priority, item.intent_id),
            )
        )

    def resolve(self, event: Any) -> ReflexIntentResolution:
        matches = self.matches(event)
        if not matches:
            return ReflexIntentResolution(
                "no_match",
                reason="no deterministic resident intent matched",
            )
        highest = matches[0].priority
        top = tuple(
            match for match in matches if match.priority == highest
        )
        if len(top) != 1:
            return ReflexIntentResolution(
                "ambiguous",
                candidates=top,
                reason=(
                    "multiple deterministic resident intents matched at the "
                    "same priority"
                ),
            )
        return ReflexIntentResolution(
            "matched",
            match=top[0],
            candidates=matches,
            reason="one highest-priority deterministic resident intent matched",
        )


def build_resident_reflex_intents() -> ReflexIntentRegistry:
    registry = ReflexIntentRegistry()
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.audio.volume.set",
            description="Set the Windows master volume to one explicit absolute percentage.",
            required_slots=("level_percent",),
            action_id="windows.audio.volume.set",
            priority=110,
            tags=("windows", "audio", "action_candidate", "direct_action"),
        ),
        windows_audio_volume_set_goal,
    )
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.audio.volume.read",
            description="Read the current Windows master volume.",
            action_id="windows.audio.volume.read",
            priority=110,
            tags=("windows", "audio", "action_candidate", "direct_action"),
        ),
        windows_audio_volume_read_goal,
    )
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.application.open",
            description="Open one installed application by semantic name.",
            required_slots=("application_name",),
            action_id="windows.application.launch",
            priority=100,
            tags=(
                "windows",
                "application",
                "action_candidate",
                "requires_grounding",
            ),
        ),
        application_open_goal,
    )
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.current_app.text_cleanup",
            description=(
                "Clean bounded text in the current application using the "
                "existing deterministic transform contract."
            ),
            required_slots=(
                "kind",
                "field_name",
                "save_button_name",
                "transform",
            ),
            priority=90,
            tags=("windows", "current_app", "composite_goal"),
        ),
        current_app_text_cleanup_goal,
    )
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.workspace.text_edit",
            description=(
                "Edit one bounded workspace text file selected from explicit "
                "user semantics and fresh file evidence."
            ),
            required_slots=(
                "workspace_path",
                "name_hint",
                "old_text",
                "new_text",
            ),
            priority=90,
            tags=("windows", "file", "composite_goal"),
        ),
        natural_workspace_text_edit_request,
    )
    registry.register(
        ReflexIntentDescriptor(
            intent_id="windows.desktop.workspace_to_app",
            description=(
                "Move bounded workspace content into one foreground desktop "
                "application goal using semantic control names."
            ),
            required_slots=(
                "workspace_path",
                "source_name_hint",
                "input_name",
                "button_name",
            ),
            priority=80,
            tags=("windows", "desktop", "composite_goal"),
        ),
        desktop_task_goal,
    )
    return registry


def _semantic_slots(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, Mapping):
        return dict(raw)
    if is_dataclass(raw):
        value = asdict(raw)
        return dict(value) if isinstance(value, dict) else None
    return None


def _normalized_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (str(item or "").strip() for item in values)
            if value
        )
    )

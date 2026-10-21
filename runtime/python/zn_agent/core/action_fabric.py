from __future__ import annotations

import os
import re

"""ZN-owned semantic action discovery substrate.

This module describes actions and their current availability.  It deliberately
does not execute them, grant authority, plan work, or persist a second capability
universe.  Body/authority/verification remain the owners of real effects.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from .models import utc_now
from .windows_audio import (
    WindowsAudioError,
    WindowsAudioUnavailable,
    read_default_render_volume_percent,
)
from .windows_brightness import (
    WindowsBrightnessError,
    WindowsBrightnessUnavailable,
    read_active_brightness,
)
from .windows_wifi import (
    WindowsWifiError,
    WindowsWifiUnavailable,
    read_windows_wifi_state,
)
from .windows_screen_capture import screen_capture_support


ActionAvailabilityState = Literal[
    "available",
    "unavailable",
    "restricted",
    "unknown",
]
ActionEffectClass = Literal[
    "read_only",
    "reversible_side_effect",
    "potential_side_effect",
    "irreversible_side_effect",
]

@dataclass(frozen=True, slots=True)
class ActionDescriptor:
    """Stable semantic contract for one action mechanism."""

    action_id: str
    provider: str
    description: str
    body_action_kind: str | None = None
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    effect_class: ActionEffectClass = "read_only"
    required_authority: tuple[str, ...] = ()
    sensitivity: str = "normal"
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    reversibility: str = "not_applicable"
    replay_semantics: str = "read_only"
    cost_hint: str = "local"
    latency_hint: str = "interactive"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        action_id = str(self.action_id or "").strip()
        provider = str(self.provider or "").strip()
        description = " ".join(str(self.description or "").split())

        if not action_id:
            raise ValueError("action_id must not be empty")
        if not provider:
            raise ValueError("action provider must not be empty")
        if not description:
            raise ValueError("action description must not be empty")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "description", description)
        body_action_kind = str(self.body_action_kind or "").strip().lower() or None
        object.__setattr__(self, "body_action_kind", body_action_kind)
        object.__setattr__(self, "input_schema", dict(self.input_schema or {}))
        object.__setattr__(self, "output_schema", dict(self.output_schema or {}))
        for name in (
            "required_authority",
            "preconditions",
            "postconditions",
            "verification",
            "tags",
        ):
            raw = getattr(self, name)
            normalized = tuple(
                dict.fromkeys(
                    value
                    for value in (str(item or "").strip() for item in raw)
                    if value
                )
            )
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class ActionAvailability:

    """Fresh evidence about whether one descriptor can be used now."""

    action_id: str
    state: ActionAvailabilityState
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)

    @property
    def available(self) -> bool:
        return self.state == "available"

    def __post_init__(self) -> None:
        action_id = str(self.action_id or "").strip()
        if not action_id:
            raise ValueError("availability action_id must not be empty")
        if self.state not in {
            "available",
            "unavailable",
            "restricted",
            "unknown",
        }:
            raise ValueError(f"invalid action availability state: {self.state}")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "reason", " ".join(str(self.reason or "").split()))
        object.__setattr__(self, "evidence", dict(self.evidence or {}))


AvailabilityProbe = Callable[[ActionDescriptor], ActionAvailability]


# Deterministic relevance retrieval (M-2): no vectors, no model. A task token
# counts as matching a descriptor token on exact equality or substring in
# either direction, so "volume" matches "volumes" and "调低音量" matches "音量".
_RELEVANCE_STOPWORDS = frozenset(
    {
        "a", "an", "the", "to", "of", "for", "on", "in", "at", "by", "with",
        "and", "or", "please", "help", "me", "my", "it", "is", "are", "was",
        "were", "be", "do", "does", "did", "can", "could", "would", "should",
        "want", "need", "let", "get", "make", "take", "put", "go",
        "的", "了", "在", "是", "要", "请", "把", "给", "帮", "我", "你",
        "他", "她", "它", "这", "那", "吗", "呢", "吧", "啊", "一下",
    }
)
_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)


def _relevance_tokens(text: str) -> tuple[str, ...]:
    tokens = tuple(
        dict.fromkeys(
            token
            for token in _TOKEN_SPLIT.split(str(text or "").lower())
            if token and token not in _RELEVANCE_STOPWORDS
        )
    )
    return tokens


def _token_matches(task_token: str, candidate: str) -> bool:
    return bool(task_token) and bool(candidate) and (
        task_token == candidate
        or task_token in candidate
        or candidate in task_token
    )


def _availability_rank(state: ActionAvailabilityState) -> int:
    # Usable evidence first; unknown availability never ranks ahead of
    # available/restricted/unavailable evidence.
    return {"available": 0, "restricted": 1, "unavailable": 2, "unknown": 3}[state]


@dataclass(frozen=True, slots=True)
class RelevantAction:
    """One registry action scored against a task, for prompt subsetting."""

    descriptor: ActionDescriptor
    availability: ActionAvailability
    score: int
    matched_terms: tuple[str, ...] = ()
    matched_tags: tuple[str, ...] = ()

    @property
    def action_id(self) -> str:
        return self.descriptor.action_id

    def prompt_line(self) -> str:
        return (
            f"{self.descriptor.action_id}: {self.descriptor.description}"
            f" [{self.availability.state}]"
        )


class ActionFabricRegistry:
    """Deterministic registry of semantic actions and availability probes."""

    def __init__(
        self,
        *,
        success_evidence: Callable[[str], int] | None = None,
        failed_evidence: Callable[[str], int] | None = None,
    ) -> None:
        self._descriptors: dict[str, ActionDescriptor] = {}
        self._probes: dict[str, AvailabilityProbe] = {}
        self._success_evidence = success_evidence
        self._failed_evidence = failed_evidence

    def set_success_evidence_provider(
        self, provider: Callable[[str], int] | None
    ) -> None:
        """Attach prior-verified counts for retrieval ranking (Q13).

        The provider maps an action_id to its durable verified-execution
        count. Retrieval queries it once per candidate per
        ``relevant_actions`` call; a failing provider or a negative value
        is treated as "no evidence". The provider is advisory ranking
        input only: it can never admit or exclude an action, and it can
        never reorder across availability states or relevance scores --
        it only breaks ties inside one (availability, score) segment.
        """
        self._success_evidence = provider

    def set_failed_evidence_provider(
        self, provider: Callable[[str], int] | None
    ) -> None:
        """Attach prior-failed counts for retrieval ranking (Q17).

        The provider maps an action_id to its durable failed-execution
        count. It joins the Q13 success-evidence tie-break as a *failure
        rate* (``failed / (verified + failed)``), not a raw count, so an
        old burst of environmental failures cannot bury an action
        forever: later verified runs pull the rate back down. Inside one
        (availability, score) segment, actions still sort verified-high
        first; the failure rate only demotes inside a verified tie. A
        missing provider, a failing lookup, or no history means rate
        0.0 -- never a penalty, never hidden. Like the verified
        provider, this is advisory ranking input only: it can never
        admit or exclude an action, and it can never reorder across
        availability states or relevance scores.
        """
        self._failed_evidence = provider

    def register(
        self,
        descriptor: ActionDescriptor,
        *,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        action_id = descriptor.action_id
        if action_id in self._descriptors:
            raise ValueError(f"action_id already registered: {action_id}")
        self._descriptors[action_id] = descriptor
        if availability_probe is not None:
            self._probes[action_id] = availability_probe

    def unregister(self, action_id: str) -> None:
        normalized = str(action_id or "").strip()
        self._descriptors.pop(normalized, None)
        self._probes.pop(normalized, None)

    def descriptor(self, action_id: str) -> ActionDescriptor | None:
        return self._descriptors.get(str(action_id or "").strip())

    def descriptors(
        self,
        *,
        provider: str | None = None,

        tags: tuple[str, ...] = (),
    ) -> tuple[ActionDescriptor, ...]:
        wanted_provider = str(provider or "").strip()
        wanted_tags = {
            value
            for value in (str(item or "").strip() for item in tags)
            if value
        }
        rows = []
        for descriptor in self._descriptors.values():
            if wanted_provider and descriptor.provider != wanted_provider:
                continue
            if wanted_tags and not wanted_tags.issubset(set(descriptor.tags)):
                continue
            rows.append(descriptor)
        return tuple(sorted(rows, key=lambda item: item.action_id))

    def availability(self, action_id: str) -> ActionAvailability:
        descriptor = self.descriptor(action_id)
        if descriptor is None:
            raise KeyError(str(action_id or "").strip())
        probe = self._probes.get(descriptor.action_id)
        if probe is None:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason="registered action has no current availability probe",
            )
        try:
            result = probe(descriptor)
        except Exception as exc:
            return ActionAvailability(
                descriptor.action_id,

                "unknown",
                reason=f"availability probe failed: {type(exc).__name__}",
            )
        if result.action_id != descriptor.action_id:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason="availability probe returned evidence for a different action",
            )
        return result

    def availability_snapshot(
        self,
        *,
        provider: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[ActionAvailability, ...]:
        return tuple(
            self.availability(descriptor.action_id)
            for descriptor in self.descriptors(provider=provider, tags=tags)
        )

    def relevant_actions(
        self,
        *,
        task: str,
        context_tags: tuple[str, ...] = (),
        authority_domains: tuple[str, ...] = (),
        max_actions: int = 12,
        max_chars: int = 4000,
    ) -> tuple[RelevantAction, ...]:
        """Return the task-relevant action subset, best first, within caps.

        Relevance is deterministic: task-term matches against a descriptor's
        tags / action_id segments / description words, plus exact matches
        against caller-provided ``context_tags``. A descriptor is included
        only when its textual relevance reaches 4 (one caller-provided
        context-tag match, or a tag match plus an action-id match, or two
        independent term matches), so a single shared verb such as "set"
        never admits an unrelated action. ``authority_domains`` only adjusts
        the score (held authority > partial > none held; authority-free
        actions get a small bonus) and never admits or excludes an action.
        Availability orders the result: available first, then restricted,
        unavailable, and unknown last. Within one availability state and one
        relevance score, prior success evidence (Blueprint §7.5, Q13) orders
        the tied segment: actions with more verified executions rank first.
        Actions with no history are never penalized and never hidden -- they
        sort exactly like any other action with a zero verified count.
        ``max_chars`` budgets
        ``len(action_id) + 1 + len(description)`` per action; the first
        relevant action is always kept even if it alone exceeds the budget.
        Registration and execution paths are untouched.
        """
        if max_actions < 1:
            raise ValueError("max_actions must be at least 1")
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        task_terms = _relevance_tokens(task)
        wanted_tags = tuple(
            dict.fromkeys(
                tag.lower()
                for tag in (str(item or "").strip() for item in context_tags)
                if tag
            )
        )
        held_authority = {
            value
            for value in (str(item or "").strip().lower() for item in authority_domains)
            if value
        }
        scored: list[RelevantAction] = []
        for descriptor in self._descriptors.values():
            descriptor_tags = tuple(tag.lower() for tag in descriptor.tags)
            matched_tags = tuple(
                tag for tag in descriptor_tags if tag in wanted_tags
            )
            matched_terms: list[str] = []
            # Caller-provided context tags are an explicit signal and weigh
            # more than a task term merely matching a descriptor tag.
            text_score = 4 * len(matched_tags)
            id_segments = tuple(
                segment
                for segment in _TOKEN_SPLIT.split(descriptor.action_id.lower())
                if segment
            )
            description_words = _relevance_tokens(descriptor.description)
            for term in task_terms:
                matched = False
                if any(_token_matches(term, tag) for tag in descriptor_tags):
                    text_score += 3
                    matched = True
                if any(_token_matches(term, segment) for segment in id_segments):
                    text_score += 2
                    matched = True
                if any(_token_matches(term, word) for word in description_words):
                    text_score += 1
                    matched = True
                if matched:
                    matched_terms.append(term)
            if text_score < 4:
                continue
            required = {
                str(item or "").strip().lower()
                for item in descriptor.required_authority
            }
            if not required:
                authority_bonus = 1
            elif required <= held_authority:
                authority_bonus = 2
            elif required & held_authority:
                authority_bonus = 1
            else:
                authority_bonus = 0
            availability = self.availability(descriptor.action_id)
            scored.append(
                RelevantAction(
                    descriptor=descriptor,
                    availability=availability,
                    score=text_score + authority_bonus,
                    matched_terms=tuple(matched_terms),
                    matched_tags=matched_tags,
                )
            )
        # Q13 (Blueprint §7.5): prior success evidence only breaks ties inside
        # one (availability, relevance score) segment. Token relevance stays
        # the primary order and availability priority is untouched; a missing
        # provider or failing lookup means "no evidence", never a penalty.
        # Q17: prior *failed* evidence joins the same tie-break as a failure
        # rate (failed / (verified + failed)), not a raw count. Verified-high
        # still ranks first inside the segment; the rate only demotes inside
        # a verified tie. Because it is a rate, an action can recover from an
        # old burst of environmental failures as later verified runs pull
        # the rate down. No history means rate 0.0: never a penalty, never
        # hidden (Q13 acceptance semantics preserved).
        provider = self._success_evidence
        failed_provider = self._failed_evidence
        _verified_counts: dict[str, int] = {}
        _failure_rates: dict[str, float] = {}
        if provider is not None or failed_provider is not None:
            for item in scored:
                try:
                    verified = (
                        max(0, int(provider(item.action_id) or 0))
                        if provider is not None
                        else 0
                    )
                except Exception:
                    verified = 0
                try:
                    failed = (
                        max(0, int(failed_provider(item.action_id) or 0))
                        if failed_provider is not None
                        else 0
                    )
                except Exception:
                    failed = 0
                _verified_counts[item.action_id] = verified
                total = verified + failed
                _failure_rates[item.action_id] = (
                    failed / total if total > 0 else 0.0
                )
        scored.sort(
            key=lambda item: (
                _availability_rank(item.availability.state),
                -item.score,
                -_verified_counts.get(item.action_id, 0),
                _failure_rates.get(item.action_id, 0.0),
                item.action_id,
            )
        )
        selected: list[RelevantAction] = []
        spent_chars = 0
        for item in scored:
            if len(selected) >= max_actions:
                break
            cost = len(item.action_id) + 1 + len(item.descriptor.description)
            if selected and spent_chars + cost > max_chars:
                break
            selected.append(item)
            spent_chars += cost
        return tuple(selected)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._descriptors))



def build_machine_action_fabric(device_capabilities: Any) -> ActionFabricRegistry:
    """Describe current Windows machine actions without creating execution authority."""

    registry = ActionFabricRegistry()

    def resolution_availability(
        descriptor: ActionDescriptor,
    ) -> ActionAvailability:
        try:
            applications = tuple(device_capabilities.installed_applications())
        except Exception as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason=f"application inventory query failed: {type(exc).__name__}",
                evidence={"source": "device_capability_graph"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="current application inventory can resolve human-facing names locally",
            evidence={
                "source": "device_capability_graph",
                "installed_application_count": len(applications),
            },
        )

    def launch_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        applications = tuple(device_capabilities.installed_applications())
        launchable = tuple(
            application
            for application in applications
            if bool(getattr(application, "launchable", False))
        )
        return ActionAvailability(
            descriptor.action_id,
            "available" if launchable else "unavailable",
            reason=(
                "current inventory contains launchable application identities"
                if launchable
                else "current inventory contains no launchable application identity"
            ),
            evidence={
                "source": "device_capability_graph",
                "installed_application_count": len(applications),
                "launchable_application_count": len(launchable),
            },
        )

    def activation_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        processes = tuple(device_capabilities.running_processes())
        windows = tuple(device_capabilities.windows(processes=processes))
        eligible = tuple(
            window
            for window in windows
            if bool(getattr(window, "visible", False))
            and bool(getattr(window, "resolved_app_id", None))
        )
        return ActionAvailability(
            descriptor.action_id,
            "available" if eligible else "unavailable",
            reason=(
                "current machine evidence contains a visible identity-bound application window"
                if eligible
                else "no visible identity-bound application window is currently observed"
            ),
            evidence={
                "source": "device_capability_graph",
                "running_process_count": len(processes),
                "eligible_window_count": len(eligible),
            },
        )

    def companion_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        snapshot = device_capabilities.companion_context()
        supported = bool(snapshot.session.platform_supported)

        return ActionAvailability(
            descriptor.action_id,
            "available" if supported else "unavailable",
            reason=(
                "Windows companion context sense is supported on the current platform"
                if supported
                else "Windows companion context sense is unavailable on the current platform"
            ),
            evidence={
                "source": "windows_companion_context",
                "platform_supported": supported,
            },
        )

    def screen_capture_availability(
        descriptor: ActionDescriptor,
    ) -> ActionAvailability:
        supported, reason, evidence = screen_capture_support()
        return ActionAvailability(
            descriptor.action_id,
            "available" if supported else "unavailable",
            reason=reason,
            evidence=evidence,
        )

    def audio_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        try:
            level = read_default_render_volume_percent()
        except WindowsAudioUnavailable as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason=str(exc),
                evidence={"source": "windows_core_audio"},
            )
        except WindowsAudioError as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason=str(exc),
                evidence={"source": "windows_core_audio"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="default Windows render endpoint exposes master-volume control",
            evidence={
                "source": "windows_core_audio",
                "current_level_percent": level,
            },
        )

    def brightness_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        try:
            observed = read_active_brightness()
        except WindowsBrightnessUnavailable as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason=str(exc),
                evidence={"source": "windows_wmi_brightness"},
            )
        except WindowsBrightnessError as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason=str(exc),
                evidence={"source": "windows_wmi_brightness"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="one active Windows WMI monitor exposes brightness control",
            evidence={
                "source": "windows_wmi_brightness",
                "instance_name": observed.instance_name,
                "current_level_percent": observed.level_percent,
            },
        )

    def wifi_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        try:
            observed = read_windows_wifi_state()
        except WindowsWifiUnavailable as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason=str(exc),
                evidence={"source": "windows_native_wifi"},
            )
        except WindowsWifiError as exc:
            return ActionAvailability(
                descriptor.action_id,
                "unknown",
                reason=str(exc),
                evidence={"source": "windows_native_wifi"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="Windows Native Wi-Fi interface state is queryable",
            evidence={
                "source": "windows_native_wifi",
                "interface_count": observed.interface_count,
                "connected_interface_count": observed.connected_interface_count,
                "connected": observed.connected,
            },
        )

    def uia_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        if os.name != "nt":
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="Windows UI Automation control actions are available only on Windows",
                evidence={"source": "windows_uia"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="Windows UI Automation control-pattern runtime is available",
            evidence={"source": "windows_uia", "semantic_selector": True},
        )

    def office_availability(descriptor: ActionDescriptor) -> ActionAvailability:
        if os.name != "nt":
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="Microsoft Office native-object actions are available only on Windows",
                evidence={"source": "office_nativeom"},
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="Office Native Object Model binding is available when an admitted Office window is foreground",
            evidence={"source": "office_nativeom", "exact_hwnd_binding": True},
        )

    registry.register(
        ActionDescriptor(
            action_id="windows.application.resolve",
            provider="zn.windows",
            description=(
                "Resolve one human-facing Windows application name against fresh "
                "local inventory without granting launch authority."
            ),
            body_action_kind="resolve_application",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "status": {"type": "string"},
                    "application": {"type": ["object", "null"]},
                    "candidates": {"type": "array"},
                    "candidate_count": {"type": "integer"},
                },
            },
            effect_class="read_only",
            sensitivity="local_application_inventory",
            postconditions=(
                "fresh local application inventory returns resolved, ambiguous or not-installed evidence",
            ),
            verification=(
                "the local identity-resolution read itself is current machine evidence",
            ),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "application", "resolve", "sense", "native", "body"),
        ),
        availability_probe=resolution_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.application.launch",
            provider="zn.windows",
            description=(
                "Launch one installed Windows application using a resolved ZN "
                "application identity."
            ),
            body_action_kind="launch_application",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {"application_id": {"type": "string"}},
                "additionalProperties": False,
            },

            effect_class="potential_side_effect",
            required_authority=("body_action",),
            sensitivity="local_application_control",
            preconditions=(
                "application_id resolves to one currently installed launchable application",
            ),
            postconditions=(
                "the resolved application is freshly observed running or visible",
            ),
            verification=("fresh process/window observation",),
            reversibility="application_specific",
            replay_semantics="verify_before_replay",
            tags=("windows", "application", "native", "body"),
        ),
        availability_probe=launch_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.application.activate",
            provider="zn.windows",
            description=(
                "Bring one identity-bound visible Windows application window to the foreground."
            ),
            body_action_kind="activate_application_window",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {"application_id": {"type": "string"}},

                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_control",
            preconditions=(
                "application_id resolves to a currently running application",
                "exact visible window identity is freshly derived by ZN",
            ),
            postconditions=("the admitted application window is foreground",),
            verification=("fresh foreground-window observation",),
            reversibility="user_can_restore_previous_foreground",
            replay_semantics="verify_before_replay",
            tags=("windows", "application", "foreground", "native", "body"),
        ),
        availability_probe=activation_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.context.read",
            provider="zn.windows",
            description=(
                "Read bounded Windows session, power, network and display companion context."
            ),
            body_action_kind="windows_companion_context",
            input_schema={"type": "object", "additionalProperties": False},

            effect_class="read_only",
            postconditions=("fresh bounded Windows companion context is returned",),
            verification=("the read itself is current machine evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "context", "sense", "native", "body"),
        ),
        availability_probe=companion_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.desktop.scene.capture",
            provider="zn.windows.desktop.scene",
            description=(
                "Capture one bounded foreground Windows desktop scene that combines "
                "ZN-owned screenshot evidence, semantic UI Automation targets and "
                "optional visual-grounding fallback evidence."
            ),
            body_action_kind="windows_desktop_scene_capture",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {
                    "application_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "scene_id": {"type": "string"},
                    "scene_artifact_path": {"type": "string"},
                    "grounding_mode": {"type": "string"},
                    "target_count": {"type": "integer"},
                    "uia_target_count": {"type": "integer"},
                    "visual_target_count": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                    "scene": {"type": "object"},
                },
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="screen_content",
            preconditions=(
                "application_id resolves to exactly one current foreground application window",
                "the foreground window intersects the captured primary screen",
            ),
            postconditions=(
                "one coherent scene sidecar references one verified ZN-owned screenshot artifact",
                "scene targets remain bounded and carry UIA/visual provenance",
            ),
            verification=(
                "fresh scene sidecar digest plus screenshot path/dimensions/SHA-256 readback",
            ),
            reversibility=(
                "remove the exact ZN-owned desktop-scene sidecar and referenced screenshot artifact"
            ),
            replay_semantics="verify_before_replay",
            tags=(
                "windows",
                "desktop",
                "scene",
                "grounding",
                "uia",
                "visual_fallback",
                "artifact",
                "body",
            ),
        ),
        availability_probe=screen_capture_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.screen.capture",
            provider="zn.windows",
            description=(
                "Capture the current primary Windows screen into a ZN-owned PNG artifact."
            ),
            body_action_kind="windows_screen_capture",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "size_bytes": {"type": "integer"},
                    "sha256": {"type": "string"},
                },
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="screen_content",
            preconditions=("an interactive Windows desktop is available to ZN",),
            postconditions=(
                "one PNG exists under the ZN-owned screenshot artifact root",
            ),
            verification=(
                "fresh artifact path containment, PNG decode, dimensions and SHA-256 readback",
            ),
            reversibility="remove the exact ZN-owned screenshot artifact",
            replay_semantics="verify_before_replay",
            tags=("windows", "screen", "capture", "artifact", "native", "body"),
        ),
        availability_probe=screen_capture_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.audio.volume.read",
            provider="zn.windows",
            description="Read the master volume of the default Windows render endpoint.",
            body_action_kind="windows_audio_volume_read",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {"level_percent": {"type": "number"}},
            },
            effect_class="read_only",
            postconditions=("fresh default render endpoint master volume is returned",),
            verification=("the Core Audio read itself is current machine evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "audio", "volume", "native", "body"),
        ),
        availability_probe=audio_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.audio.volume.set",
            provider="zn.windows",
            description="Set the master volume of the default Windows render endpoint.",
            body_action_kind="windows_audio_volume_set",
            input_schema={
                "type": "object",
                "required": ["level_percent"],
                "properties": {
                    "level_percent": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    }
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "requested_level_percent": {"type": "number"},
                    "observed_level_percent": {"type": "number"},
                    "verified": {"type": "boolean"},
                },
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="local_audio_control",
            preconditions=(
                "a default Windows render endpoint exposes IAudioEndpointVolume",
            ),
            postconditions=(
                "fresh endpoint readback matches the requested volume within tolerance",
            ),
            verification=("fresh Core Audio master-volume readback",),
            reversibility="set the previously observed volume through the same action",
            replay_semantics="verify_before_replay",
            tags=("windows", "audio", "volume", "native", "body"),
        ),
        availability_probe=audio_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.display.brightness.read",
            provider="zn.windows",
            description="Read the brightness of the unique active Windows WMI monitor.",
            body_action_kind="windows_display_brightness_read",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "level_percent": {"type": "number"},
                    "instance_name": {"type": "string"},
                },
            },
            effect_class="read_only",
            postconditions=("fresh active-monitor brightness is returned",),
            verification=("the WMI read itself is current machine evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "display", "brightness", "native", "body"),
        ),
        availability_probe=brightness_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.display.brightness.set",
            provider="zn.windows",
            description="Set the brightness of the unique active Windows WMI monitor.",
            body_action_kind="windows_display_brightness_set",
            input_schema={
                "type": "object",
                "required": ["level_percent"],
                "properties": {
                    "level_percent": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    }
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "instance_name": {"type": "string"},
                    "requested_level_percent": {"type": "number"},
                    "observed_level_percent": {"type": "number"},
                    "verified": {"type": "boolean"},
                },
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="local_display_control",
            preconditions=(
                "exactly one active WmiMonitorBrightness target is currently observed",
            ),
            postconditions=(
                "fresh active-monitor readback matches the requested brightness within tolerance",
            ),
            verification=("fresh WMI active-monitor brightness readback",),
            reversibility="set the previously observed brightness through the same action",
            replay_semantics="verify_before_replay",
            tags=("windows", "display", "brightness", "native", "body"),
        ),
        availability_probe=brightness_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.ui.controls.list",
            provider="zn.windows.uia",
            description=(
                "List a bounded set of one semantic Windows UI Automation control type "
                "inside the exact current foreground application."
            ),
            body_action_kind="automation_controls_list",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type"],
                "properties": {
                    "application_id": {"type": "string"},
                    "control_type": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="read_only",
            sensitivity="interactive_desktop_state",
            preconditions=(
                "application_id is the exact current foreground application",
                "control_type is one supported bounded UI Automation semantic type",
            ),
            postconditions=(
                "at most 24 current controls of the requested type are returned without text values",
            ),
            verification=("the bounded UI Automation candidate read itself is current evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "uia", "gui", "sense", "candidate_inventory", "body"),
        ),
        availability_probe=uia_availability,
    )

    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.read",
            provider="zn.windows.uia",
            description=(
                "Read one exact foreground Windows UI Automation control-pattern state "
                "through a semantic selector."
            ),
            body_action_kind="automation_control_read",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type", "pattern"],
                "properties": {
                    "application_id": {"type": "string"},
                    "control_type": {"type": "string"},
                    "control_name": {"type": "string"},
                    "automation_id": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="read_only",
            sensitivity="interactive_desktop_state",
            preconditions=(
                "application_id is the exact current foreground application",
                "name/automation_id selector resolves to exactly one enabled onscreen control",
                "the requested UI Automation control pattern is exposed",
            ),
            postconditions=("fresh exact-control pattern state is returned",),
            verification=("the UI Automation pattern read itself is current desktop evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "uia", "gui", "sense", "semantic_control", "body"),
        ),
        availability_probe=uia_availability,
    )

    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.set_value",
            provider="zn.windows.uia",
            description=(
                "Set one exact foreground Windows UI Automation ValuePattern control "
                "through a semantic selector."
            ),
            body_action_kind="automation_control_set_value",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type", "value"],
                "properties": {
                "application_id": {"type": "string"},
                "control_type": {"type": "string"},
                "control_name": {"type": "string"},
                "automation_id": {"type": "string"},                    "value": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_control",
            preconditions=(
                "application_id is the exact current foreground application",
                "name/automation_id selector resolves to exactly one enabled onscreen non-password control",
                "the control exposes writable ValuePattern",
            ),
            postconditions=("fresh exact-control ValuePattern digest matches the requested value",),
            verification=("fresh UI Automation ValuePattern readback",),
            reversibility="set the previously observed value through the same semantic control action",
            replay_semantics="verify_before_replay",
            tags=("windows", "uia", "gui", "value", "semantic_control", "body"),
        ),
        availability_probe=uia_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.type_text",
            provider="zn.windows.uia",
            description=(
                "Type bounded Unicode text into one exact empty foreground Windows "
                "UI Automation Edit or Document control after verified focus."
            ),
            body_action_kind="automation_control_type_text",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type", "text"],
                "properties": {
                    "application_id": {"type": "string"},
                    "control_type": {"type": "string"},
                    "control_name": {"type": "string"},
                    "automation_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_text_input",
            preconditions=(
                "application_id is the exact current foreground application",
                "semantic selector resolves to exactly one enabled onscreen non-password Edit or Document control",
                "target is keyboard-focusable and current text digest proves the control is empty or already satisfied",
            ),
            postconditions=(
                "fresh exact-control ValuePattern/TextPattern digest matches the requested text",
            ),
            verification=(
                "fresh UI Automation text length plus SHA-256 digest readback",
            ),
            reversibility=(
                "application-specific; V1 refuses replacement of non-empty text"
            ),
            replay_semantics="verify_before_replay",
            tags=(
                "windows",
                "uia",
                "gui",
                "text",
                "keyboard",
                "semantic_control",
                "body",
            ),
        ),
        availability_probe=uia_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.toggle",
            provider="zn.windows.uia",
            description="Set one exact foreground Windows UI Automation TogglePattern control on or off.",
            body_action_kind="automation_control_toggle",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type", "state"],
                "properties": {
                "application_id": {"type": "string"},
                "control_type": {"type": "string"},
                "control_name": {"type": "string"},
                "automation_id": {"type": "string"},                    "state": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_control",
            preconditions=(
                "application_id is the exact current foreground application",
                "semantic selector resolves to exactly one enabled onscreen TogglePattern control",
                "indeterminate toggle state is rejected",
            ),
            postconditions=("fresh exact-control TogglePattern state equals on/off target",),
            verification=("fresh UI Automation TogglePattern readback",),
            reversibility="toggle to the previously observed on/off state",
            replay_semantics="verify_before_replay",
            tags=("windows", "uia", "gui", "toggle", "semantic_control", "body"),
        ),
        availability_probe=uia_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.expand_collapse",
            provider="zn.windows.uia",
            description=(
                "Expand or collapse one exact foreground Windows UI Automation "
                "ExpandCollapsePattern control."
            ),
            body_action_kind="automation_control_expand_collapse",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type", "state"],
                "properties": {
                "application_id": {"type": "string"},
                "control_type": {"type": "string"},
                "control_name": {"type": "string"},
                "automation_id": {"type": "string"},                    "state": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_control",
            preconditions=(
                "application_id is the exact current foreground application",
                "semantic selector resolves to exactly one enabled onscreen ExpandCollapsePattern control",
            ),
            postconditions=("fresh exact-control state equals expanded/collapsed target",),
            verification=("fresh UI Automation ExpandCollapsePattern readback",),
            reversibility="restore the previously observed expand/collapse state",
            replay_semantics="verify_before_replay",
            tags=("windows", "uia", "gui", "expand_collapse", "semantic_control", "body"),
        ),
        availability_probe=uia_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.ui.control.select",
            provider="zn.windows.uia",
            description=(
                "Select one exact foreground Windows UI Automation SelectionItemPattern control."
            ),
            body_action_kind="automation_control_select",
            input_schema={
                "type": "object",
                "required": ["application_id", "control_type"],
                "properties": {
                "application_id": {"type": "string"},
                "control_type": {"type": "string"},
                "control_name": {"type": "string"},
                "automation_id": {"type": "string"},                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="interactive_desktop_control",
            preconditions=(
                "application_id is the exact current foreground application",
                "semantic selector resolves to exactly one enabled onscreen SelectionItemPattern control",
            ),
            postconditions=("fresh exact-control SelectionItemPattern reports selected=true",),
            verification=("fresh UI Automation SelectionItemPattern readback",),
            reversibility="selection is application/container specific",
            replay_semantics="verify_before_replay",
            tags=("windows", "uia", "gui", "selection", "semantic_control", "body"),
        ),
        availability_probe=uia_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.office.session.read",
            provider="zn.windows.office",
            description="Read bounded identity for the exact foreground Microsoft Office session.",
            body_action_kind="office_session_read",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {"application_id": {"type": "string"}},
                "additionalProperties": False,
            },
            effect_class="read_only",
            sensitivity="local_document_state",
            preconditions=("application_id is the exact current foreground Word/Excel/PowerPoint app",),
            postconditions=("current Office version and active document identity are returned",),
            verification=("the exact-HWND Native Object Model read itself is current evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "office", "com", "nativeom", "sense", "body"),
        ),
        availability_probe=office_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.office.excel.cell.read",
            provider="zn.windows.office",
            description="Read privacy-safe state for one exact cell in the foreground Excel workbook.",
            body_action_kind="office_excel_cell_read",
            input_schema={
                "type": "object",
                "required": ["application_id", "worksheet_name", "cell_address"],
                "properties": {
                    "application_id": {"type": "string"},
                    "worksheet_name": {"type": "string"},
                    "cell_address": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="read_only",
            sensitivity="local_document_content_digest",
            preconditions=(
                "application_id is the exact current foreground Microsoft Excel app",
                "worksheet_name resolves exactly and cell_address is one A1-style cell",
            ),
            postconditions=("fresh cell type/length/digest state is returned without raw content",),
            verification=("the exact-HWND Excel NativeOM read itself is current evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "office", "excel", "com", "cell", "sense", "body"),
        ),
        availability_probe=office_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.office.excel.cell.set",
            provider="zn.windows.office",
            description="Set one exact cell in the foreground Excel workbook through Native Object Model.",
            body_action_kind="office_excel_cell_set",
            input_schema={
                "type": "object",
                "required": ["application_id", "worksheet_name", "cell_address", "value"],
                "properties": {
                    "application_id": {"type": "string"},
                    "worksheet_name": {"type": "string"},
                    "cell_address": {"type": "string"},
                    "value": {},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="local_document_control",
            preconditions=(
                "application_id is the exact current foreground Microsoft Excel app",
                "worksheet_name resolves exactly and cell_address is one A1-style cell",
            ),
            postconditions=("fresh exact-cell digest matches the requested scalar value",),
            verification=("fresh Excel NativeOM cell readback",),
            reversibility="set the previously observed scalar value through the same action",
            replay_semantics="verify_before_replay",
            tags=("windows", "office", "excel", "com", "cell", "mutation", "body"),
        ),
        availability_probe=office_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.office.word.selection.read",
            provider="zn.windows.office",
            description="Read privacy-safe text state for the current foreground Word selection.",
            body_action_kind="office_word_selection_read",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {"application_id": {"type": "string"}},
                "additionalProperties": False,
            },
            effect_class="read_only",
            sensitivity="local_document_content_digest",
            preconditions=("application_id is the exact current foreground Microsoft Word app",),
            postconditions=("fresh selection length/digest state is returned without raw text",),
            verification=("the exact-HWND Word NativeOM selection read itself is current evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("windows", "office", "word", "com", "selection", "sense", "body"),
        ),
        availability_probe=office_availability,
    )
    registry.register(
        ActionDescriptor(
            action_id="windows.office.word.selection.set_text",
            provider="zn.windows.office",
            description="Replace the current foreground Word selection through Native Object Model.",
            body_action_kind="office_word_selection_set_text",
            input_schema={
                "type": "object",
                "required": ["application_id", "text"],
                "properties": {
                    "application_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="local_document_control",
            preconditions=("application_id is the exact current foreground Microsoft Word app",),
            postconditions=("fresh selection digest matches the requested replacement text",),
            verification=("fresh Word NativeOM selection readback",),
            reversibility="Office Undo or a later explicit replacement",
            replay_semantics="verify_before_replay",
            tags=("windows", "office", "word", "com", "selection", "mutation", "body"),
        ),
        availability_probe=office_availability,
    )

    registry.register(
        ActionDescriptor(
            action_id="windows.network.wifi.read",
            provider="zn.windows",
            description=(
                "Read enabled Windows Wi-Fi interface state without network identity."
            ),
            body_action_kind="windows_network_wifi_read",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "connected": {"type": "boolean"},
                    "interface_count": {"type": "integer"},
                    "connected_interface_count": {"type": "integer"},
                    "interfaces": {"type": "array"},
                },
            },
            effect_class="read_only",
            postconditions=("fresh Native Wi-Fi interface state is returned",),
            verification=("the WlanEnumInterfaces read itself is current machine evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            sensitivity="local_network_state",
            tags=("windows", "network", "wifi", "native", "body"),
        ),
        availability_probe=wifi_availability,
    )
    return registry

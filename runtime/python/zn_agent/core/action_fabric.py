from __future__ import annotations

import os

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

class ActionFabricRegistry:
    """Deterministic registry of semantic actions and availability probes."""

    def __init__(self) -> None:
        self._descriptors: dict[str, ActionDescriptor] = {}
        self._probes: dict[str, AvailabilityProbe] = {}

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

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._descriptors))



def build_machine_action_fabric(device_capabilities: Any) -> ActionFabricRegistry:
    """Describe current Windows machine actions without creating execution authority."""

    registry = ActionFabricRegistry()

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

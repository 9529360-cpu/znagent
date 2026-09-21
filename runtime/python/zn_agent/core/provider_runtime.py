from __future__ import annotations

"""Runtime supervision metadata for ZN capability providers.

A provider is a body/domain implementation such as Windows, Browser, Office or
local inference. This registry tracks current health/queryability and optional
lifecycle hooks; it never grants action authority and does not replace Work,
Body, Action Fabric, or verification.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from .action_fabric import ActionFabricRegistry
from .models import utc_now


ProviderLifecycleMode = Literal["resident", "lazy", "external"]
ProviderHealthState = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class CapabilityProviderDescriptor:
    provider_id: str
    description: str
    action_ids: tuple[str, ...] = ()
    lifecycle_mode: ProviderLifecycleMode = "resident"
    idle_timeout_seconds: int | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "").strip()
        description = " ".join(str(self.description or "").split())
        if not provider_id:
            raise ValueError("provider_id must not be empty")
        if not description:
            raise ValueError("provider description must not be empty")
        if self.lifecycle_mode not in {"resident", "lazy", "external"}:
            raise ValueError(
                f"invalid provider lifecycle mode: {self.lifecycle_mode}"
            )
        idle_timeout = self.idle_timeout_seconds
        if idle_timeout is not None and int(idle_timeout) < 0:
            raise ValueError("idle_timeout_seconds must be non-negative")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "action_ids",
            _normalized_tuple(self.action_ids),
        )
        object.__setattr__(self, "tags", _normalized_tuple(self.tags))
        object.__setattr__(
            self,
            "idle_timeout_seconds",
            int(idle_timeout) if idle_timeout is not None else None,
        )


@dataclass(frozen=True, slots=True)
class CapabilityProviderStatus:
    provider_id: str
    state: ProviderHealthState
    queryable: bool
    running: bool | None = None
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider status provider_id must not be empty")
        if self.state not in {
            "healthy",
            "degraded",
            "unavailable",
            "unknown",
        }:
            raise ValueError(f"invalid provider health state: {self.state}")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(
            self,
            "reason",
            " ".join(str(self.reason or "").split()),
        )
        object.__setattr__(self, "evidence", dict(self.evidence or {}))


ProviderHealthProbe = Callable[
    [CapabilityProviderDescriptor],
    CapabilityProviderStatus,
]
ProviderLifecycleHook = Callable[[CapabilityProviderDescriptor], None]


class CapabilityProviderRuntime:
    """Deterministic provider registry with fresh health and explicit lifecycle."""

    def __init__(self) -> None:
        self._descriptors: dict[str, CapabilityProviderDescriptor] = {}
        self._health_probes: dict[str, ProviderHealthProbe] = {}
        self._start_hooks: dict[str, ProviderLifecycleHook] = {}
        self._stop_hooks: dict[str, ProviderLifecycleHook] = {}

    def register(
        self,
        descriptor: CapabilityProviderDescriptor,
        *,
        health_probe: ProviderHealthProbe | None = None,
        start_hook: ProviderLifecycleHook | None = None,
        stop_hook: ProviderLifecycleHook | None = None,
    ) -> None:
        provider_id = descriptor.provider_id
        if provider_id in self._descriptors:
            raise ValueError(f"provider_id already registered: {provider_id}")
        self._descriptors[provider_id] = descriptor
        if health_probe is not None:
            self._health_probes[provider_id] = health_probe
        if start_hook is not None:
            self._start_hooks[provider_id] = start_hook
        if stop_hook is not None:
            self._stop_hooks[provider_id] = stop_hook

    def descriptor(
        self,
        provider_id: str,
    ) -> CapabilityProviderDescriptor | None:
        return self._descriptors.get(str(provider_id or "").strip())

    def descriptors(self) -> tuple[CapabilityProviderDescriptor, ...]:
        return tuple(
            sorted(
                self._descriptors.values(),
                key=lambda descriptor: descriptor.provider_id,
            )
        )

    def status(self, provider_id: str) -> CapabilityProviderStatus:
        descriptor = self.descriptor(provider_id)
        if descriptor is None:
            raise KeyError(str(provider_id or "").strip())
        probe = self._health_probes.get(descriptor.provider_id)
        if probe is None:
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "unknown",
                queryable=False,
                reason="registered provider has no current health probe",
            )
        try:
            result = probe(descriptor)
        except Exception as exc:
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "unknown",
                queryable=False,
                reason=f"provider health probe failed: {type(exc).__name__}",
            )
        if result.provider_id != descriptor.provider_id:
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "unknown",
                queryable=False,
                reason="provider health probe returned status for another provider",
            )
        return result

    def activate(self, provider_id: str) -> CapabilityProviderStatus:
        descriptor = self._require_descriptor(provider_id)
        current = self.status(descriptor.provider_id)
        if current.queryable:
            return current
        hook = self._start_hooks.get(descriptor.provider_id)
        if hook is None:
            return current
        hook(descriptor)
        return self.status(descriptor.provider_id)

    def deactivate(self, provider_id: str) -> CapabilityProviderStatus:
        descriptor = self._require_descriptor(provider_id)
        hook = self._stop_hooks.get(descriptor.provider_id)
        if hook is not None:
            hook(descriptor)
        return self.status(descriptor.provider_id)
    def status_snapshot(self) -> tuple[CapabilityProviderStatus, ...]:
        return tuple(
            self.status(descriptor.provider_id)
            for descriptor in self.descriptors()
        )

    def _require_descriptor(
        self,
        provider_id: str,
    ) -> CapabilityProviderDescriptor:
        descriptor = self.descriptor(provider_id)
        if descriptor is None:
            raise KeyError(str(provider_id or "").strip())
        return descriptor


def build_machine_provider_runtime(
    action_fabric: ActionFabricRegistry,
) -> CapabilityProviderRuntime:
    """Register the current native Windows provider over Action Fabric evidence."""

    runtime = CapabilityProviderRuntime()
    action_ids = tuple(
        descriptor.action_id
        for descriptor in action_fabric.descriptors(provider="zn.windows")
    )
    def windows_health(
        descriptor: CapabilityProviderDescriptor,
    ) -> CapabilityProviderStatus:
        availability = tuple(
            action_fabric.availability(action_id)
            for action_id in descriptor.action_ids
        )
        available_count = sum(1 for row in availability if row.available)
        unknown_count = sum(
            1 for row in availability if row.state == "unknown"
        )
        if available_count:
            state: ProviderHealthState = (
                "degraded" if unknown_count else "healthy"
            )
            queryable = True
            reason = "native Windows provider has currently available actions"
        elif unknown_count:
            state = "unknown"
            queryable = False
            reason = "native Windows provider availability is not fully known"
        else:
            state = "unavailable"
            queryable = False
            reason = "native Windows provider has no currently available action"
        return CapabilityProviderStatus(
            descriptor.provider_id,
            state,
            queryable=queryable,
            running=True,
            reason=reason,
            evidence={
                "registered_action_count": len(availability),
                "available_action_count": available_count,
                "unknown_action_count": unknown_count,
                "source": "action_fabric",
            },
        )

    runtime.register(
        CapabilityProviderDescriptor(
            provider_id="zn.windows",
            description="Resident deterministic Windows body and context provider.",
            action_ids=action_ids,
            lifecycle_mode="resident",
            tags=("windows", "native", "body"),
        ),
        health_probe=windows_health,
    )
    return runtime


def _normalized_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (str(item or "").strip() for item in values)
            if value
        )
    )

from __future__ import annotations

"""Replaceable managed-browser provider selection owned by ZN.

Providers supply browser execution. They never own Work, browser authority, or
completion truth. Product code asks this module for the best currently
available managed browser instead of instantiating a concrete engine directly.
"""

import os
from dataclasses import dataclass
from typing import Callable

from .browser import BrowserAdapter, BrowserPlane


BrowserFactory = Callable[[], BrowserAdapter]


@dataclass(frozen=True, slots=True)
class BrowserProviderDescriptor:
    name: str
    plane: BrowserPlane
    priority: int
    factory: BrowserFactory
    available: Callable[[], bool]


class BrowserProviderRegistry:
    """Small deterministic provider registry modeled after mature browser agents."""

    def __init__(self) -> None:
        self._providers: dict[str, BrowserProviderDescriptor] = {}

    def register(self, descriptor: BrowserProviderDescriptor) -> None:
        name = str(descriptor.name or "").strip().lower()
        if not name:
            raise ValueError("browser provider name must not be empty")
        if name in self._providers:
            raise ValueError(f"browser provider already registered: {name}")
        self._providers[name] = descriptor

    def resolve(
        self,
        *,
        plane: BrowserPlane,
        preferred: str = "",
    ) -> BrowserProviderDescriptor:
        wanted = str(preferred or "").strip().lower()
        if wanted:
            descriptor = self._providers.get(wanted)
            if descriptor is None:
                raise RuntimeError(f"unknown browser provider: {wanted}")
            if descriptor.plane is not plane:
                raise RuntimeError(
                    f"browser provider {wanted} does not serve {plane.value} plane"
                )
            if not descriptor.available():
                raise RuntimeError(f"browser provider is unavailable: {wanted}")
            return descriptor

        candidates = [
            descriptor
            for descriptor in self._providers.values()
            if descriptor.plane is plane and descriptor.available()
        ]
        if not candidates:
            raise RuntimeError(f"no available browser provider for {plane.value} plane")
        candidates.sort(key=lambda item: (-item.priority, item.name))
        return candidates[0]


def default_managed_browser_registry() -> BrowserProviderRegistry:
    registry = BrowserProviderRegistry()

    from .chrome_devtools_mcp_browser import (
        ChromeDevToolsMcpManagedBrowser,
        chrome_devtools_mcp_available,
    )
    from .research_managed_browser import ResearchSemanticPlaywrightManagedBrowser

    registry.register(
        BrowserProviderDescriptor(
            name="chrome-devtools-mcp",
            plane=BrowserPlane.MANAGED,
            priority=100,
            factory=ChromeDevToolsMcpManagedBrowser,
            available=chrome_devtools_mcp_available,
        )
    )
    registry.register(
        BrowserProviderDescriptor(
            name="playwright",
            plane=BrowserPlane.MANAGED,
            priority=200,
            factory=ResearchSemanticPlaywrightManagedBrowser,
            available=lambda: True,
        )
    )
    return registry


def build_readable_managed_browser_adapter(
    *,
    preferred: str | None = None,
    registry: BrowserProviderRegistry | None = None,
) -> BrowserAdapter:
    """Build an ephemeral research browser.

    Read-only managed research prefers the mature Chrome DevTools MCP provider
    when its pinned runtime and a supported Chrome installation are present.
    Interactive BrowserScene/file-transfer ownership stays on the complete
    Playwright provider until the mature provider exposes those ZN contracts.
    """

    selected = (
        str(preferred).strip()
        if preferred is not None
        else str(os.getenv("ZN_RESEARCH_BROWSER_PROVIDER") or "").strip()
    )
    providers = registry or default_managed_browser_registry()
    if selected:
        descriptor = providers.resolve(
            plane=BrowserPlane.MANAGED,
            preferred=selected,
        )
        return descriptor.factory()

    try:
        descriptor = providers.resolve(
            plane=BrowserPlane.MANAGED,
            preferred="chrome-devtools-mcp",
        )
    except RuntimeError:
        descriptor = providers.resolve(
            plane=BrowserPlane.MANAGED,
            preferred="playwright",
        )
    return descriptor.factory()


def build_managed_browser_adapter(
    *,
    preferred: str | None = None,
    registry: BrowserProviderRegistry | None = None,
) -> BrowserAdapter:
    """Build the complete interactive managed-browser owner.

    The default provider remains Playwright because ZN's active BrowserScene,
    causal popup and file-transfer contracts extend beyond the base
    BrowserAdapter protocol. Read-only research uses
    build_readable_managed_browser_adapter() and can prefer Chrome DevTools MCP.
    """

    selected = (
        str(preferred).strip()
        if preferred is not None
        else str(os.getenv("ZN_BROWSER_PROVIDER") or "").strip()
    )
    providers = registry or default_managed_browser_registry()
    descriptor = providers.resolve(
        plane=BrowserPlane.MANAGED,
        preferred=selected,
    )
    return descriptor.factory()

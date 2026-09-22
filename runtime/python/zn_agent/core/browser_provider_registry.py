from __future__ import annotations

"""Replaceable managed-browser provider selection owned by ZN.

Providers supply browser execution. They never own Work, browser authority, or
completion truth. Product code asks this module for the best currently
available managed browser instead of instantiating a concrete engine directly.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserAdapter,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserTargetQueryKind,
)


BrowserFactory = Callable[[], BrowserAdapter]


@dataclass(frozen=True, slots=True)
class BrowserProviderDescriptor:
    name: str
    plane: BrowserPlane
    priority: int
    factory: BrowserFactory
    available: Callable[[], bool]
    supported_actions: frozenset[BrowserActionKind] = field(
        default_factory=lambda: frozenset(BrowserActionKind)
    )
    supported_target_queries: frozenset[BrowserTargetQueryKind] = field(
        default_factory=lambda: frozenset(BrowserTargetQueryKind)
    )

    def supports(
        self,
        required_actions: Iterable[BrowserActionKind],
        required_target_queries: Iterable[BrowserTargetQueryKind] = (),
    ) -> bool:
        return (
            set(required_actions).issubset(self.supported_actions)
            and set(required_target_queries).issubset(self.supported_target_queries)
        )


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
        required_actions: Iterable[BrowserActionKind] = (),
        required_target_queries: Iterable[BrowserTargetQueryKind] = (),
    ) -> BrowserProviderDescriptor:
        wanted = str(preferred or "").strip().lower()
        required = frozenset(required_actions)
        required_queries = frozenset(required_target_queries)
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
            if not descriptor.supports(required, required_queries):
                missing = required.difference(descriptor.supported_actions)
                missing_queries = required_queries.difference(
                    descriptor.supported_target_queries
                )
                details: list[str] = []
                if missing:
                    details.append(
                        "actions: " + ", ".join(sorted(item.value for item in missing))
                    )
                if missing_queries:
                    details.append(
                        "target queries: "
                        + ", ".join(sorted(item.value for item in missing_queries))
                    )
                raise RuntimeError(
                    f"browser provider {wanted} does not support required "
                    + "; ".join(details)
                )
            return descriptor

        candidates = [
            descriptor
            for descriptor in self._providers.values()
            if descriptor.plane is plane
            and descriptor.available()
            and descriptor.supports(required, required_queries)
        ]
        if not candidates:
            suffix = ""
            needs = [
                *(item.value for item in sorted(required, key=lambda item: item.value)),
                *(
                    f"target:{item.value}"
                    for item in sorted(required_queries, key=lambda item: item.value)
                ),
            ]
            if needs:
                suffix = " supporting " + ", ".join(needs)
            raise RuntimeError(
                f"no available browser provider for {plane.value} plane{suffix}"
            )
        candidates.sort(key=lambda item: (-item.priority, item.name))
        return candidates[0]

    def available(
        self,
        *,
        plane: BrowserPlane,
    ) -> tuple[BrowserProviderDescriptor, ...]:
        rows = [
            descriptor
            for descriptor in self._providers.values()
            if descriptor.plane is plane and descriptor.available()
        ]
        rows.sort(key=lambda item: (-item.priority, item.name))
        return tuple(rows)


class ManagedBrowserProviderRouter:
    """Choose one provider per session from explicit capability requirements."""

    name = "managed-browser-provider-router"
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        registry: BrowserProviderRegistry,
        preferred: str = "",
    ) -> None:
        self._registry = registry
        self._preferred = str(preferred or "").strip().lower()
        self._sessions: dict[str, BrowserAdapter] = {}

    @staticmethod
    def _required_actions(
        permission: BrowserPermissionContext,
    ) -> frozenset[BrowserActionKind]:
        return frozenset(
            kind for kind in BrowserActionKind if permission.allows_action(kind)
        )

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ):
        return self.open_session_for_requirements(
            permission=permission,
            headless=headless,
        )

    def open_session_for_requirements(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
        required_target_queries: Iterable[BrowserTargetQueryKind] = (),
    ):
        policy = permission or BrowserPermissionContext()
        descriptor = self._registry.resolve(
            plane=BrowserPlane.MANAGED,
            preferred=self._preferred,
            required_actions=self._required_actions(policy),
            required_target_queries=required_target_queries,
        )
        adapter = descriptor.factory()
        try:
            identity = adapter.open_session(
                permission=policy,
                headless=headless,
            )
        except BaseException:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
            raise
        self._sessions[identity.session_id] = adapter
        return identity

    def close_session(self, session_id: str) -> None:
        adapter = self._sessions.pop(str(session_id), None)
        if adapter is None:
            return
        try:
            adapter.close_session(session_id)
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    def close(self) -> None:
        for session_id in tuple(self._sessions):
            self.close_session(session_id)

    def observe(self, session_id: str, *, page_id: str = ""):
        return self._adapter(session_id).observe(session_id, page_id=page_id)

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        return self._adapter(session_id).observe_target(
            session_id,
            query,
            page_id=page_id,
        )

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ):
        return self._adapter(action.session_id).act(action, authority)

    def read_page(self, session_id: str, *, page_id: str = "") -> dict[str, Any]:
        adapter = self._adapter(session_id)
        reader = getattr(adapter, "read_page", None)
        if not callable(reader):
            raise RuntimeError(
                f"browser provider {getattr(adapter, 'name', '<unknown>')} "
                "does not support readable page evidence"
            )
        return reader(session_id, page_id=page_id)

    def _adapter(self, session_id: str) -> BrowserAdapter:
        adapter = self._sessions.get(str(session_id))
        if adapter is None:
            raise RuntimeError(f"unknown managed browser session: {session_id}")
        return adapter

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
            priority=200,
            factory=ChromeDevToolsMcpManagedBrowser,
            available=chrome_devtools_mcp_available,
            supported_actions=frozenset(
                kind
                for kind in BrowserActionKind
                if kind
                not in {
                    BrowserActionKind.UPLOAD_FILE,
                    BrowserActionKind.DOWNLOAD_FILE,
                }
            ),
            supported_target_queries=frozenset(
                kind
                for kind in BrowserTargetQueryKind
                if kind is not BrowserTargetQueryKind.DOM_ID
            ),
        )
    )
    registry.register(
        BrowserProviderDescriptor(
            name="playwright",
            plane=BrowserPlane.MANAGED,
            priority=100,
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
    """Build the capability-routed interactive managed-browser owner.

    When both providers are available, ordinary semantic browser sessions prefer
    Chrome DevTools MCP. Sessions whose granted permissions admit actions the
    mature provider does not yet implement (currently upload/download) route to
    Playwright before a browser session is opened.
    """

    selected = (
        str(preferred).strip()
        if preferred is not None
        else str(os.getenv("ZN_BROWSER_PROVIDER") or "").strip()
    )
    providers = registry or default_managed_browser_registry()
    if selected:
        providers.resolve(
            plane=BrowserPlane.MANAGED,
            preferred=selected,
        )
        return ManagedBrowserProviderRouter(
            registry=providers,
            preferred=selected,
        )

    available = list(providers.available(plane=BrowserPlane.MANAGED))
    if len(available) == 1:
        return available[0].factory()
    if not available:
        providers.resolve(plane=BrowserPlane.MANAGED)
        raise AssertionError("unreachable")
    return ManagedBrowserProviderRouter(registry=providers)

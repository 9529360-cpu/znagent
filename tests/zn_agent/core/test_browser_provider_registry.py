from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTargetQueryKind,
)
from zn_agent.core.browser_provider_registry import (
    BrowserProviderDescriptor,
    BrowserProviderRegistry,
    ManagedBrowserProviderRouter,
    build_managed_browser_adapter,
    build_readable_managed_browser_adapter,
)


class _Adapter:
    plane = BrowserPlane.MANAGED

    def __init__(self, name):
        self.name = name

    def open_session(self, *, permission=None, headless=True):
        return BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider=self.name,
        )

    def close_session(self, session_id):
        return None

    def observe(self, session_id, *, page_id=""):
        raise NotImplementedError

    def observe_target(self, session_id, query, *, page_id=""):
        raise NotImplementedError

    def act(self, action, authority):
        raise NotImplementedError


class BrowserProviderRegistryTests(unittest.TestCase):
    def test_highest_priority_available_provider_wins(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="legacy",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("legacy"),
                available=lambda: True,
            )
        )
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
            )
        )

        descriptor = registry.resolve(plane=BrowserPlane.MANAGED)
        self.assertEqual(descriptor.name, "mature")

    def test_unavailable_mature_provider_falls_back_without_new_authority(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="legacy",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("legacy"),
                available=lambda: True,
            )
        )
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: False,
            )
        )

        adapter = build_managed_browser_adapter(registry=registry)
        self.assertIsInstance(adapter, ManagedBrowserProviderRouter)
        self.assertIs(adapter.plane, BrowserPlane.MANAGED)
        session = adapter.open_session(permission=BrowserPermissionContext())
        try:
            self.assertEqual(session.provider, "legacy")
        finally:
            adapter.close_session(session.session_id)

    def test_readable_browser_prefers_mature_provider_then_falls_back(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="chrome-devtools-mcp",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
            )
        )
        registry.register(
            BrowserProviderDescriptor(
                name="playwright",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("playwright"),
                available=lambda: True,
            )
        )

        readable = build_readable_managed_browser_adapter(registry=registry)
        self.assertEqual(readable.name, "mature")

        unavailable = BrowserProviderRegistry()
        unavailable.register(
            BrowserProviderDescriptor(
                name="chrome-devtools-mcp",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("mature"),
                available=lambda: False,
            )
        )
        unavailable.register(
            BrowserProviderDescriptor(
                name="playwright",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("playwright"),
                available=lambda: True,
            )
        )
        fallback = build_readable_managed_browser_adapter(registry=unavailable)
        self.assertEqual(fallback.name, "playwright")

    def test_capability_router_prefers_mature_but_keeps_file_transfer_on_complete_provider(self):
        registry = BrowserProviderRegistry()
        mature_actions = frozenset(
            kind
            for kind in BrowserActionKind
            if kind
            not in {
                BrowserActionKind.UPLOAD_FILE,
                BrowserActionKind.DOWNLOAD_FILE,
            }
        )
        registry.register(
            BrowserProviderDescriptor(
                name="playwright",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("playwright"),
                available=lambda: True,
            )
        )
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
                supported_actions=mature_actions,
            )
        )

        adapter = build_managed_browser_adapter(registry=registry)
        self.assertIsInstance(adapter, ManagedBrowserProviderRouter)

        semantic = adapter.open_session(
            permission=BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
                allow_text_entry=True,
            )
        )
        self.assertEqual(semantic.provider, "mature")
        adapter.close_session(semantic.session_id)

        download = adapter.open_session(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allow_downloads=True,
            )
        )
        self.assertEqual(download.provider, "playwright")
        adapter.close_session(download.session_id)

    def test_target_query_capability_routes_legacy_dom_id_to_playwright(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="playwright",
                plane=BrowserPlane.MANAGED,
                priority=100,
                factory=lambda: _Adapter("playwright"),
                available=lambda: True,
            )
        )
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
                supported_target_queries=frozenset(
                    kind
                    for kind in BrowserTargetQueryKind
                    if kind is not BrowserTargetQueryKind.DOM_ID
                ),
            )
        )

        adapter = build_managed_browser_adapter(registry=registry)
        self.assertIsInstance(adapter, ManagedBrowserProviderRouter)

        semantic = adapter.open_session_for_requirements(
            permission=BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
            ),
            required_target_queries=(
                BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
            ),
        )
        self.assertEqual(semantic.provider, "mature")
        adapter.close_session(semantic.session_id)

        combobox = adapter.open_session_for_requirements(
            permission=BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
            ),
            required_target_queries=(
                BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME,
            ),
        )
        self.assertEqual(combobox.provider, "mature")
        adapter.close_session(combobox.session_id)

        legacy_dom = adapter.open_session_for_requirements(
            permission=BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
            ),
            required_target_queries=(BrowserTargetQueryKind.DOM_ID,),
        )
        self.assertEqual(legacy_dom.provider, "playwright")
        adapter.close_session(legacy_dom.session_id)

    def test_explicit_provider_capability_mismatch_fails_closed(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
                supported_actions=frozenset(
                    kind
                    for kind in BrowserActionKind
                    if kind is not BrowserActionKind.DOWNLOAD_FILE
                ),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "does not support required actions"):
            registry.resolve(
                plane=BrowserPlane.MANAGED,
                preferred="mature",
                required_actions=(BrowserActionKind.DOWNLOAD_FILE,),
            )

    def test_explicit_provider_router_rejects_unsupported_permission_before_session(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: True,
                supported_actions=frozenset(
                    kind
                    for kind in BrowserActionKind
                    if kind is not BrowserActionKind.DOWNLOAD_FILE
                ),
            )
        )
        adapter = build_managed_browser_adapter(
            preferred="mature",
            registry=registry,
        )
        self.assertIsInstance(adapter, ManagedBrowserProviderRouter)
        with self.assertRaisesRegex(RuntimeError, "does not support required actions"):
            adapter.open_session(
                permission=BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_downloads=True,
                )
            )

    def test_explicit_unavailable_provider_fails_closed(self):
        registry = BrowserProviderRegistry()
        registry.register(
            BrowserProviderDescriptor(
                name="mature",
                plane=BrowserPlane.MANAGED,
                priority=200,
                factory=lambda: _Adapter("mature"),
                available=lambda: False,
            )
        )

        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            build_managed_browser_adapter(
                preferred="mature",
                registry=registry,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime

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
    ProviderFailure,
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


class _FailingAdapter(_Adapter):
    """Adapter whose session open always blows up like a dead browser."""

    def open_session(self, *, permission=None, headless=True):
        raise RuntimeError("chrome socket died")


def _managed_descriptor(name, *, priority=100, available=True, factory=None):
    return BrowserProviderDescriptor(
        name=name,
        plane=BrowserPlane.MANAGED,
        priority=priority,
        factory=factory or (lambda: _Adapter(name)),
        available=lambda: available,
    )


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


class BrowserProviderHealthTests(unittest.TestCase):
    """P2-11: registry records last failure reason + timestamp per provider."""

    def test_record_failure_stores_reason_and_utc_timestamp(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature"))

        registry.record_failure("mature", "chrome socket died")

        failure = registry.last_failure("mature")
        self.assertIsNotNone(failure)
        self.assertIsInstance(failure, ProviderFailure)
        self.assertEqual(failure.reason, "chrome socket died")
        # parseable UTC ISO-8601 timestamp
        self.assertIsNotNone(datetime.fromisoformat(failure.at))
        self.assertIn("+00:00", failure.at)

    def test_record_failure_keeps_latest_reason(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature"))

        registry.record_failure("mature", "first hiccup")
        registry.record_failure("mature", "chrome binary missing")

        self.assertEqual(registry.last_failure("mature").reason, "chrome binary missing")

    def test_last_failure_is_none_without_record_and_for_unknown_names(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature"))

        self.assertIsNone(registry.last_failure("mature"))
        self.assertIsNone(registry.last_failure("no-such-provider"))

    def test_record_failure_is_fail_closed(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature"))

        with self.assertRaises(ValueError):
            registry.record_failure("no-such-provider", "boom")
        with self.assertRaises(ValueError):
            registry.record_failure("mature", "   ")
        with self.assertRaises(ValueError):
            registry.record_failure("", "boom")

    def test_resolve_preferred_unavailable_error_carries_last_failure(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature", priority=200, available=False))
        registry.record_failure("mature", "chrome binary missing")

        with self.assertRaisesRegex(
            RuntimeError, r"browser provider is unavailable: mature.*chrome binary missing"
        ):
            registry.resolve(plane=BrowserPlane.MANAGED, preferred="mature")

    def test_resolve_unavailable_error_unchanged_without_recorded_failure(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature", priority=200, available=False))

        with self.assertRaises(RuntimeError) as ctx:
            registry.resolve(plane=BrowserPlane.MANAGED, preferred="mature")
        self.assertEqual(
            str(ctx.exception), "browser provider is unavailable: mature"
        )

    def test_resolve_no_candidate_error_carries_last_failures(self):
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("mature", priority=200, available=False))
        registry.register(_managed_descriptor("legacy", priority=100, available=False))
        registry.record_failure("mature", "chrome binary missing")

        with self.assertRaises(RuntimeError) as ctx:
            registry.resolve(plane=BrowserPlane.MANAGED)
        message = str(ctx.exception)
        self.assertIn("no available browser provider for managed plane", message)
        self.assertIn("mature", message)
        self.assertIn("chrome binary missing", message)
        # legacy has no recorded failure, so it must not appear in the notes
        self.assertNotIn("legacy: last failure", message)

    def test_recorded_failure_does_not_change_selection(self):
        # No automatic failover: a recorded failure is observation only.
        registry = BrowserProviderRegistry()
        registry.register(_managed_descriptor("legacy", priority=100, available=True))
        registry.register(_managed_descriptor("mature", priority=200, available=True))
        registry.record_failure("mature", "transient hiccup earlier")

        descriptor = registry.resolve(plane=BrowserPlane.MANAGED)
        self.assertEqual(descriptor.name, "mature")

    def test_router_records_failure_when_open_session_fails_and_reraises(self):
        registry = BrowserProviderRegistry()
        registry.register(
            _managed_descriptor(
                "mature",
                priority=200,
                available=True,
                factory=lambda: _FailingAdapter("mature"),
            )
        )
        router = ManagedBrowserProviderRouter(registry=registry, preferred="mature")

        with self.assertRaisesRegex(RuntimeError, "chrome socket died"):
            router.open_session(permission=BrowserPermissionContext())

        failure = registry.last_failure("mature")
        self.assertIsNotNone(failure)
        self.assertIn("chrome socket died", failure.reason)
        self.assertIn("RuntimeError", failure.reason)
        self.assertIsNotNone(datetime.fromisoformat(failure.at))

    def test_router_records_failure_when_factory_fails(self):
        def broken_factory():
            raise OSError("playwright driver missing")

        registry = BrowserProviderRegistry()
        registry.register(
            _managed_descriptor(
                "playwright",
                priority=100,
                available=True,
                factory=broken_factory,
            )
        )
        router = ManagedBrowserProviderRouter(registry=registry, preferred="playwright")

        with self.assertRaisesRegex(OSError, "playwright driver missing"):
            router.open_session(permission=BrowserPermissionContext())

        failure = registry.last_failure("playwright")
        self.assertIsNotNone(failure)
        self.assertIn("playwright driver missing", failure.reason)
        self.assertIn("OSError", failure.reason)

    def test_router_still_fails_closed_without_failover_after_failure(self):
        registry = BrowserProviderRegistry()
        registry.register(
            _managed_descriptor(
                "mature",
                priority=200,
                available=True,
                factory=lambda: _FailingAdapter("mature"),
            )
        )
        registry.register(_managed_descriptor("legacy", priority=100, available=True))
        router = ManagedBrowserProviderRouter(registry=registry, preferred="mature")

        # The failing provider must not be silently skipped to the next one:
        # selection behavior is unchanged, the error propagates.
        with self.assertRaises(RuntimeError):
            router.open_session(permission=BrowserPermissionContext())
        self.assertEqual(router._sessions, {})


if __name__ == "__main__":
    unittest.main()

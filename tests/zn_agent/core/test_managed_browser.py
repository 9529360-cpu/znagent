from __future__ import annotations

import time
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import ManagedBrowserError, PlaywrightManagedBrowser


class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class _FakeRoute:
    def __init__(self, url: str):
        self.request = _FakeRequest(url)
        self.continued = False
        self.aborted = False
        self.error_code = None

    def continue_(self):
        self.continued = True

    def abort(self, *, error_code=None):
        self.aborted = True
        self.error_code = error_code


class _FakeWebSocketRoute:
    def __init__(self, url: str):
        self.url = url
        self.connected = False
        self.closed = False
        self.close_code = None

    def connect_to_server(self):
        self.connected = True

    def close(self, *, code=None, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class _FakeValueHandle:
    def __init__(self, value):
        self.value = value
        self.disposed = False

    def json_value(self):
        return self.value

    def dispose(self):
        self.disposed = True


class _FakeElementHandle:
    def __init__(self, page, node):
        self.page = page
        self.node = node
        self.disposed = False
        page.created_element_handles.append(self)

    def as_element(self):
        return self if self.node is not None else None

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed fake element handle")
        if "element === other" in expression:
            return bool(
                self.node is not None
                and isinstance(arg, _FakeElementHandle)
                and arg.node is self.node
            )
        if "document.activeElement === element" in expression:
            return bool(
                self.node is not None
                and self.node.get("connected", True)
                and self.page.active_node is self.node
            )
        if "document.querySelectorAll" in expression and "element.isConnected" in expression:
            expected_id = str(arg or "")
            current = self.page.target_snapshots.get(expected_id)
            count = 0 if current is None else int(current.get("count", 1))
            node = self.node or {}
            connected = bool(node.get("connected", True))
            return {
                "count": count,
                "current": bool(
                    connected
                    and count == 1
                    and current is self.node
                    and node.get("dom_id") == expected_id
                ),
                "connected": connected,
                "visible": bool(connected and node.get("visible", True)),
                "dom_id": str(node.get("dom_id") or ""),
                "tag": str(node.get("tag") or ""),
                "role": str(node.get("role") or ""),
                "name": str(node.get("name") or ""),
                "input_type": str(node.get("input_type") or ""),
                "is_password": bool(node.get("is_password", False)),
            }
        raise AssertionError("unexpected element evaluate expression")

    def focus(self):
        if self.disposed:
            raise RuntimeError("disposed fake element handle")
        if self.node is None or not self.node.get("connected", True):
            raise RuntimeError("fake target is detached")
        if self.node.get("focus_error"):
            raise RuntimeError("fake provider focus error")

        self.page.active_node = self.node
        if self.node.get("replace_on_focus"):
            dom_id = str(self.node.get("dom_id") or "")
            replacement = dict(self.node)
            replacement.pop("replace_on_focus", None)
            self.node["connected"] = False
            replacement["connected"] = True
            self.page.target_snapshots[dom_id] = replacement
            self.page.active_node = None
        elif self.node.get("focus_blocked"):
            self.page.active_node = None

    def dispose(self):
        self.disposed = True


class _FakeNullHandle:
    def __init__(self):
        self.disposed = False

    def as_element(self):
        return None

    def dispose(self):
        self.disposed = True


class _FakeBundleHandle:
    def __init__(self, page, count, node):
        self.page = page
        self.count = count
        self.node = node
        self.disposed = False

    def get_property(self, name):
        if name == "count":
            return _FakeValueHandle(self.count)
        if name == "node":
            if self.node is None:
                return _FakeNullHandle()
            return _FakeElementHandle(self.page, self.node)
        raise AssertionError(f"unexpected fake bundle property: {name}")

    def dispose(self):
        self.disposed = True


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = ""
        self._ready = "complete"
        self.viewport_size = {"width": 1280, "height": 720}
        self.closed = False
        self.goto_calls = []
        self.target_snapshots = {}
        self.active_node = None
        self.created_element_handles = []

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState" and arg is None:
            return self._ready
        raise AssertionError("unexpected page evaluate expression")

    def evaluate_handle(self, expression, arg=None):
        if "document.querySelectorAll" not in expression:
            raise AssertionError("unexpected evaluate_handle expression")
        dom_id = str(arg or "")
        current = self.target_snapshots.get(dom_id)
        count = 0 if current is None else int(current.get("count", 1))
        node = current if count == 1 else None
        return _FakeBundleHandle(self, count, node)

    def goto(self, url, *, wait_until):
        self.goto_calls.append((url, wait_until))
        self.url = url
        self._title = "Fixture"
        self._ready = "interactive"
        self.active_node = None

    def is_closed(self):
        return self.closed


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.route_handler = None
        self.websocket_handler = None
        self.navigation_timeout = None
        self.action_timeout = None
        self.closed = False

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def set_default_timeout(self, value):
        self.action_timeout = value

    def route(self, pattern, handler):
        self.route_pattern = pattern
        self.route_handler = handler

    def route_web_socket(self, pattern, handler):
        self.websocket_pattern = pattern
        self.websocket_handler = handler

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeBrowser:
    version = "fake-1"

    def __init__(self):
        self.context = _FakeContext()
        self.new_context_kwargs = None
        self.closed = False

    def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self.context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_headless = None

    def launch(self, *, headless):
        self.launch_headless = headless
        return self.browser


class _FakePlaywright:
    def __init__(self):
        self.browser = _FakeBrowser()
        self.chromium = _FakeChromium(self.browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _target_snapshot(
    *,
    dom_id="search-input",
    tag="input",
    role="textbox",
    name="Search",
    input_type="text",
    connected=True,
    visible=True,
    is_password=False,
    count=1,
    replace_on_focus=False,
    focus_blocked=False,
    focus_error=False,
):
    return {
        "count": count,
        "connected": connected,
        "visible": visible,
        "dom_id": dom_id,
        "tag": tag,
        "role": role,
        "name": name,
        "input_type": input_type,
        "is_password": is_password,
        "replace_on_focus": replace_on_focus,
        "focus_blocked": focus_blocked,
        "focus_error": focus_error,
    }


class ManagedBrowserTests(unittest.TestCase):
    def _build(self, *, permission=None, checker=None):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=checker or (lambda url, **kwargs: True),
            navigation_timeout_ms=5000,
            action_timeout_ms=3000,
        )
        identity = adapter.open_session(permission=permission, headless=True)
        return adapter, playwright, identity

    def _observe_target(self, adapter, playwright, identity, *, dom_id="search-input"):
        page = playwright.browser.context.page
        page.url = "https://example.com/form"
        page._title = "Form"
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value=dom_id,
        )
        return query, adapter.observe_target(identity.session_id, query)

    def test_open_session_is_ephemeral_and_blocks_service_workers_and_downloads(self):
        adapter, playwright, identity = self._build()
        try:
            self.assertEqual(identity.profile_scope, "ephemeral")
            self.assertTrue(playwright.chromium.launch_headless)
            self.assertEqual(
                playwright.browser.new_context_kwargs,
                {"accept_downloads": False, "service_workers": "block"},
            )
            observation = adapter.observe(identity.session_id)
            self.assertEqual(observation.url, "about:blank")
            self.assertEqual(observation.metadata["service_workers"], "blocked")
            self.assertNotIn("content", observation.metadata)
            self.assertNotIn("html", observation.metadata)
        finally:
            adapter.close()
        self.assertTrue(playwright.browser.context.closed)
        self.assertTrue(playwright.browser.closed)
        self.assertTrue(playwright.stopped)

    def test_download_or_upload_permission_is_rejected_until_file_authority_exists(self):
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(_FakePlaywright()),
            url_checker=lambda url, **kwargs: True,
        )
        with self.assertRaises(ManagedBrowserError):
            adapter.open_session(permission=BrowserPermissionContext(allow_downloads=True))
        with self.assertRaises(ManagedBrowserError):
            adapter.open_session(permission=BrowserPermissionContext(allow_uploads=True))

    def test_dom_id_target_observation_is_bounded_fresh_and_authority_ready(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        page.url = "https://example.com/form"
        page._title = "Form"
        page.target_snapshots["search-input"] = _target_snapshot()
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="search-input",
        )
        try:
            first = adapter.observe_target(identity.session_id, query)
            self.assertIsNotNone(first.target)
            self.assertEqual(first.target.kind, BrowserTargetKind.ELEMENT)
            self.assertEqual(first.target.frame_id, "main")
            self.assertEqual(first.target.role, "textbox")
            self.assertEqual(first.target.name, "Search")
            self.assertEqual(first.target.selector_hint, "dom_id:search-input")
            self.assertEqual(first.target.observed_at, first.captured_at)
            self.assertFalse(hasattr(first.target, "value"))
            self.assertFalse(hasattr(first.target, "text"))

            time.sleep(0.001)
            refreshed = adapter.observe_target(
                identity.session_id,
                query,
                page_id=first.page_id,
            )
            self.assertEqual(refreshed.target.target_id, first.target.target_id)
            self.assertNotEqual(refreshed.target.observed_at, first.target.observed_at)

            stale_action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=first.page_id,
                kind=BrowserActionKind.CLICK,
                target=first.target,
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                BrowserActionAuthority.from_observation(
                    stale_action,
                    refreshed,
                    permission,
                )

            current_action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=refreshed.page_id,
                kind=BrowserActionKind.CLICK,
                target=refreshed.target,
            )
            authority = BrowserActionAuthority.from_observation(
                current_action,
                refreshed,
                permission,
            )
            effect = adapter.act(current_action, authority)
            self.assertFalse(effect.success)
            self.assertIn("not implemented", effect.error or "")
        finally:
            adapter.close()

    def test_observation_replacement_disposes_old_provider_target_handle(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        page.target_snapshots["search-input"] = _target_snapshot()
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="search-input",
        )
        try:
            adapter.observe_target(identity.session_id, query)
            first_handle = page.created_element_handles[-1]
            self.assertFalse(first_handle.disposed)
            adapter.observe(identity.session_id)
            self.assertTrue(first_handle.disposed)
        finally:
            adapter.close()

    def test_focus_requires_current_exact_node_and_returns_fresh_postcondition_evidence(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        page.target_snapshots["search-input"] = _target_snapshot()
        try:
            _query, observed = self._observe_target(adapter, playwright, identity)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS,
                target=observed.target,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_focused")
            self.assertEqual(effect.target_id, observed.target.target_id)
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertTrue(effect.data["focused"])
            self.assertIs(page.active_node, page.target_snapshots["search-input"])
            self.assertNotEqual(effect.observed_at, observed.captured_at)
        finally:
            adapter.close()

    def test_focus_rejects_same_shape_replacement_before_dispatch(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        original = _target_snapshot()
        page.target_snapshots["search-input"] = original
        try:
            _query, observed = self._observe_target(adapter, playwright, identity)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS,
                target=observed.target,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )

            original["connected"] = False
            replacement = _target_snapshot()
            page.target_snapshots["search-input"] = replacement

            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("changed before dispatch", effect.error or "")
            self.assertIsNone(page.active_node)
        finally:
            adapter.close()

    def test_focus_fails_if_exact_target_is_replaced_during_dispatch(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        original = _target_snapshot(replace_on_focus=True)
        page.target_snapshots["search-input"] = original
        try:
            _query, observed = self._observe_target(adapter, playwright, identity)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS,
                target=observed.target,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("replaced target node", effect.error or "")
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertIsNot(page.target_snapshots["search-input"], original)
            self.assertIsNone(page.active_node)
        finally:
            adapter.close()

    def test_focus_requires_independent_fresh_active_element_postcondition(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        page.target_snapshots["search-input"] = _target_snapshot(focus_blocked=True)
        try:
            _query, observed = self._observe_target(adapter, playwright, identity)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS,
                target=observed.target,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertFalse(effect.data["focused"])
        finally:
            adapter.close()

    def test_target_handles_are_disposed_when_session_closes(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        page.target_snapshots["search-input"] = _target_snapshot()
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="search-input",
        )
        adapter.observe_target(identity.session_id, query)
        target_handle = page.created_element_handles[-1]
        self.assertFalse(target_handle.disposed)
        adapter.close_session(identity.session_id)
        self.assertTrue(target_handle.disposed)

    def test_dom_id_target_observation_fails_closed_for_missing_ambiguous_hidden_or_frame(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        page.target_snapshots["duplicate"] = _target_snapshot(
            dom_id="duplicate",
            count=2,
        )
        page.target_snapshots["hidden"] = _target_snapshot(
            dom_id="hidden",
            visible=False,
        )
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "not found"):
                adapter.observe_target(
                    identity.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="missing",
                    ),
                )
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                adapter.observe_target(
                    identity.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="duplicate",
                    ),
                )
            with self.assertRaisesRegex(ManagedBrowserError, "not visible"):
                adapter.observe_target(
                    identity.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="hidden",
                    ),
                )
            with self.assertRaisesRegex(ManagedBrowserError, "only the main frame"):
                adapter.observe_target(
                    identity.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="missing",
                        frame_id="child-frame",
                    ),
                )
        finally:
            adapter.close()

    def test_password_target_requires_sensitive_permission_and_does_not_export_name(self):
        denied, denied_playwright, denied_identity = self._build()
        denied_playwright.browser.context.page.target_snapshots["password"] = _target_snapshot(
            dom_id="password",
            name="Password",
            input_type="password",
            is_password=True,
        )
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="password",
        )
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "sensitive-field"):
                denied.observe_target(denied_identity.session_id, query)
        finally:
            denied.close()

        allowed, allowed_playwright, allowed_identity = self._build(
            permission=BrowserPermissionContext(allow_sensitive_fields=True)
        )
        allowed_playwright.browser.context.page.target_snapshots["password"] = _target_snapshot(
            dom_id="password",
            name="Password",
            input_type="password",
            is_password=True,
        )
        try:
            observed = allowed.observe_target(allowed_identity.session_id, query)
            self.assertEqual(observed.target.name, "")
            self.assertEqual(observed.target.role, "textbox")
        finally:
            allowed.close()

    def test_target_identity_changes_when_page_or_semantic_shape_changes(self):
        adapter, playwright, identity = self._build()
        page = playwright.browser.context.page
        page.url = "https://example.com/one"
        page.target_snapshots["shared"] = _target_snapshot(
            dom_id="shared",
            tag="input",
            role="textbox",
        )
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.DOM_ID,
            value="shared",
        )
        try:
            first = adapter.observe_target(identity.session_id, query)
            page.url = "https://example.com/two"
            page.target_snapshots["shared"] = _target_snapshot(
                dom_id="shared",
                tag="button",
                role="button",
                input_type="",
            )
            second = adapter.observe_target(
                identity.session_id,
                query,
                page_id=first.page_id,
            )
            self.assertNotEqual(first.target.target_id, second.target.target_id)
            self.assertEqual(second.target.role, "button")
        finally:
            adapter.close()

    def test_navigation_requires_fresh_authority_and_returns_observed_effect(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allowed_origins=("https://example.com",),
        )
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://example.com/next"},
                expected={"url_equals": "https://example.com/next"},
            )
            authority = BrowserActionAuthority.from_observation(action, observation, permission)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.url_before, "about:blank")
            self.assertEqual(effect.url_after, "https://example.com/next")
            self.assertEqual(effect.postcondition, "safe_current_page_observed")
            self.assertEqual(
                playwright.browser.context.page.goto_calls,
                [("https://example.com/next", "domcontentloaded")],
            )
        finally:
            adapter.close()

    def test_stale_authority_fails_before_navigation(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allowed_origins=("https://example.com",),
        )
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://example.com/"},
            )
            authority = BrowserActionAuthority(
                action_id=action.action_id,
                session_id=identity.session_id,
                issued_at="now",
                observation_captured_at="stale-observation",
                permission=permission,
                page_id=observation.page_id,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", effect.error or "")
            self.assertEqual(playwright.browser.context.page.goto_calls, [])
        finally:
            adapter.close()

    def test_network_route_and_websocket_route_share_zn_url_boundary(self):
        def checker(url, **kwargs):
            return "blocked.example" not in url

        permission = BrowserPermissionContext()
        adapter, playwright, identity = self._build(permission=permission, checker=checker)
        try:
            context = playwright.browser.context
            allowed = _FakeRoute("https://allowed.example/a")
            blocked = _FakeRoute("https://blocked.example/a")
            context.route_handler(allowed)
            context.route_handler(blocked)
            self.assertTrue(allowed.continued)
            self.assertTrue(blocked.aborted)
            self.assertEqual(blocked.error_code, "blockedbyclient")

            ws_allowed = _FakeWebSocketRoute("wss://allowed.example/socket")
            ws_blocked = _FakeWebSocketRoute("wss://blocked.example/socket")
            context.websocket_handler(ws_allowed)
            context.websocket_handler(ws_blocked)
            self.assertTrue(ws_allowed.connected)
            self.assertTrue(ws_blocked.closed)
            self.assertEqual(ws_blocked.close_code, 1008)
        finally:
            adapter.close()

    def test_origin_policy_blocks_navigation_before_browser_dispatch(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allowed_origins=("https://allowed.example",),
        )
        adapter, playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "https://other.example/"},
            )
            authority = BrowserActionAuthority.from_observation(action, observation, permission)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(playwright.browser.context.page.goto_calls, [])
        finally:
            adapter.close()

    def test_forged_target_authority_is_rechecked_at_execution_boundary(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, _playwright, identity = self._build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            stale_target = BrowserTarget(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserTargetKind.ELEMENT,
                target_id="reused-element-id",
                observed_at="stale-target-evidence",
            )
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=stale_target,
            )
            forged = BrowserActionAuthority(
                action_id=action.action_id,
                session_id=identity.session_id,
                issued_at="now",
                observation_captured_at=observation.captured_at,
                permission=permission,
                target_id=stale_target.target_id,
                page_id=observation.page_id,
            )
            effect = adapter.act(action, forged)
            self.assertFalse(effect.success)
            self.assertIn("current target observation", effect.error or "")
        finally:
            adapter.close()

    def test_unimplemented_click_returns_failure_evidence_without_dispatch(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        adapter, playwright, identity = self._build(permission=permission)
        page = playwright.browser.context.page
        page.target_snapshots["search-input"] = _target_snapshot()
        try:
            _query, observation = self._observe_target(adapter, playwright, identity)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=observation.target,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observation,
                permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("not implemented", effect.error or "")
            self.assertIsNone(page.active_node)
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

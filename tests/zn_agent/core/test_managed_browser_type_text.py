from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import asdict

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


_TYPED_TEXT = "ZN typed Unicode ✓"
_TYPED_DIGEST = hashlib.sha256(_TYPED_TEXT.encode("utf-8")).hexdigest()
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


class _ValueHandle:
    def __init__(self, value):
        self.value = value

    def json_value(self):
        return self.value

    def dispose(self):
        return None


class _ElementHandle:
    def __init__(self, page, node):
        self.page = page
        self.node = node
        self.disposed = False

    def as_element(self):
        return self

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return isinstance(arg, _ElementHandle) and self.node is arg.node
        if "element.value" in expression and "element.readOnly" in expression:
            connected = bool(self.node.get("connected", True))
            is_password = bool(self.node.get("is_password", False))
            return {
                "connected": connected,
                "supported": bool(self.node.get("supported", True)),
                "disabled": bool(self.node.get("disabled", False)),
                "read_only": bool(self.node.get("read_only", False)),
                "is_password": is_password,
                "value": None if is_password else str(self.node.get("value") or ""),
            }
        if "document.querySelectorAll" in expression and "element.isConnected" in expression:
            current = self.page.node
            connected = bool(self.node.get("connected", True))
            return {
                "count": 1,
                "current": bool(connected and current is self.node),
                "connected": connected,
                "visible": connected,
                "dom_id": "text-target",
                "tag": "input",
                "role": "textbox",
                "name": "Text target",
                "input_type": "password" if self.node.get("is_password") else "text",
                "is_password": bool(self.node.get("is_password", False)),
            }
        raise AssertionError("unexpected evaluate expression")

    def fill(self, text):
        if self.disposed or not self.node.get("connected", True):
            raise RuntimeError("detached element")
        self.page.fill_dispatches += 1
        if self.node.get("fill_error"):
            raise RuntimeError("provider fill error")
        if not self.node.get("fill_blocked"):
            self.node["value"] = text
        if self.node.get("replace_on_fill"):
            replacement = dict(self.node)
            replacement.pop("replace_on_fill", None)
            self.node["connected"] = False
            replacement["connected"] = True
            self.page.node = replacement

    def dispose(self):
        self.disposed = True


class _BundleHandle:
    def __init__(self, page):
        self.page = page

    def get_property(self, name):
        if name == "count":
            return _ValueHandle(1)
        if name == "node":
            return _ElementHandle(self.page, self.page.node)
        raise AssertionError(name)

    def dispose(self):
        return None


class _Page:
    def __init__(self, node):
        self.node = node
        self.url = "https://example.com/text"
        self.viewport_size = {"width": 800, "height": 600}
        self.fill_dispatches = 0

    def title(self):
        return "Text"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def evaluate_handle(self, expression, arg=None):
        if "document.querySelectorAll" not in expression or arg != "text-target":
            raise AssertionError("unexpected target query")
        return _BundleHandle(self)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.page = page

    def set_default_navigation_timeout(self, value):
        return None

    def set_default_timeout(self, value):
        return None

    def route(self, pattern, handler):
        return None

    def route_web_socket(self, pattern, handler):
        return None

    def new_page(self):
        return self.page

    def close(self):
        return None


class _Browser:
    version = "fake"

    def __init__(self, page):
        self.context = _Context(page)

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class _Chromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        return self.browser


class _Playwright:
    def __init__(self, page):
        self.chromium = _Chromium(_Browser(page))

    def stop(self):
        return None


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _build(node, *, permission=None):
    page = _Page(node)
    playwright = _Playwright(page)
    policy = permission or BrowserPermissionContext(
        allow_page_interaction=True,
        allow_text_entry=True,
    )
    browser = PlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=policy, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.DOM_ID,
        value="text-target",
    )
    observed = browser.observe_target(session.session_id, query)
    return browser, session, policy, page, observed


def _type_action(session, observed, *, text=_TYPED_TEXT):
    return BrowserAction.create(
        session_id=session.session_id,
        page_id=observed.page_id,
        kind=BrowserActionKind.TYPE_TEXT,
        target=observed.target,
        args={"text": text} if text is not None else {},
    )


class ManagedBrowserTypeTextTests(unittest.TestCase):
    def test_type_text_requires_text_entry_permission_at_authority_boundary(self):
        permission = BrowserPermissionContext(allow_page_interaction=True)
        browser, session, _permission, page, observed = _build(
            {"connected": True, "value": ""},
            permission=permission,
        )
        try:
            action = _type_action(session, observed)
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, permission)
            self.assertEqual(page.fill_dispatches, 0)
        finally:
            browser.close()

    def test_type_text_requires_explicit_nonempty_plain_text_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "value": ""}
        )
        try:
            action = _type_action(session, observed, text=None)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("explicit string text", effect.error or "")
            self.assertEqual(page.fill_dispatches, 0)
        finally:
            browser.close()

    def test_type_text_refuses_nonempty_target_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "value": "existing"}
        )
        try:
            action = _type_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("non-empty", effect.error or "")
            self.assertEqual(page.fill_dispatches, 0)
        finally:
            browser.close()

    def test_type_text_returns_success_only_from_fresh_same_node_digest(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "value": ""}
        )
        try:
            action = _type_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_text_equals_requested")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(effect.data["text_length_before"], 0)
            self.assertEqual(effect.data["text_sha256_before"], _EMPTY_DIGEST)
            self.assertEqual(effect.data["text_length_after"], len(_TYPED_TEXT))
            self.assertEqual(effect.data["text_sha256_after"], _TYPED_DIGEST)
            self.assertEqual(effect.data["expected_text_length"], len(_TYPED_TEXT))
            self.assertEqual(effect.data["expected_text_sha256"], _TYPED_DIGEST)
            self.assertTrue(effect.data["input_sent"])
            self.assertEqual(page.fill_dispatches, 1)
            self.assertNotEqual(effect.observed_at, observed.captured_at)
            serialized = json.dumps(asdict(effect), sort_keys=True)
            self.assertNotIn(_TYPED_TEXT, serialized)
        finally:
            browser.close()

    def test_type_text_fails_if_provider_dispatch_does_not_change_text_state(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "value": "", "fill_blocked": True}
        )
        try:
            action = _type_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(effect.data["text_length_after"], 0)
            self.assertEqual(page.fill_dispatches, 1)
        finally:
            browser.close()

    def test_type_text_fails_if_same_shape_target_is_replaced_during_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "value": "", "replace_on_fill": True}
        )
        try:
            action = _type_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("replaced target node", effect.error or "")
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertEqual(effect.data["text_sha256_after"], _TYPED_DIGEST)
            self.assertEqual(page.fill_dispatches, 1)
        finally:
            browser.close()

    def test_type_text_refuses_password_even_with_sensitive_field_permission(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_sensitive_fields=True,
        )
        browser, session, _permission, page, observed = _build(
            {"connected": True, "value": "secret", "is_password": True},
            permission=permission,
        )
        try:
            action = _type_action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("password", effect.error or "")
            self.assertEqual(page.fill_dispatches, 0)
            serialized = json.dumps(asdict(effect), sort_keys=True)
            self.assertNotIn("secret", serialized)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import hashlib
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.semantic_managed_browser import (
    ManagedBrowserError,
    SemanticPlaywrightManagedBrowser,
)


class _Element:
    def __init__(self, page, token):
        self.page = page
        self.token = token
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "native_combobox" in expression:
            return {
                "connected": True,
                "visible": True,
                "tag": self.page.tag,
                "native_combobox": self.page.tag == "select",
                "disabled": self.page.disabled,
                "multiple": self.page.multiple,
            }
        if "selectedOptions" in expression and "selected_values" in expression:
            return {
                "connected": True,
                "supported": self.page.tag == "select",
                "disabled": self.page.disabled,
                "multiple": self.page.multiple,
                "selected_values": [self.page.selected_value],
                "selected_labels": [self.page.selected_label],
            }
        if "element === other" in expression:
            return isinstance(arg, _Element) and self.token is arg.token
        raise AssertionError("unexpected element expression")

    def select_option(self, *, value=None, label=None):
        if (value is None) == (label is None):
            raise RuntimeError("expected exactly one select mode")
        if value is not None:
            self.page.selected_value = value
            self.page.selected_label = self.page.value_labels[value]
        else:
            self.page.selected_label = label
            self.page.selected_value = self.page.label_values[label]
        if self.page.replace_on_select:
            self.page.token = object()

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return self.page.count

    def element_handle(self):
        return _Element(self.page, self.page.token)


class _Page:
    def __init__(
        self,
        *,
        count=1,
        tag="select",
        disabled=False,
        multiple=False,
        replace_on_select=False,
    ):
        self.url = "https://example.com/form"
        self.viewport_size = {"width": 800, "height": 600}
        self.count = count
        self.tag = tag
        self.disabled = disabled
        self.multiple = multiple
        self.replace_on_select = replace_on_select
        self.role_calls = []
        self.token = object()
        self.selected_value = "alpha"
        self.selected_label = "Alpha"
        self.label_values = {"Alpha": "alpha", "Private Beta": "beta-private"}
        self.value_labels = {value: label for label, value in self.label_values.items()}

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self)

    def title(self):
        return "Form"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.pages = [page]
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


def _build(**page_kwargs):
    page = _Page(**page_kwargs)
    playwright = _Playwright(page)
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    permission = BrowserPermissionContext(allow_page_interaction=True)
    session = browser.open_session(permission=permission, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME,
        value="Plan",
    )
    return browser, session, permission, page, query


class SemanticManagedBrowserComboboxTests(unittest.TestCase):
    def test_exact_named_native_combobox_binds_by_accessible_name(self):
        browser, session, _permission, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "combobox")
            self.assertEqual(observed.target.name, "Plan")
            self.assertEqual(
                observed.target.selector_hint,
                "accessible_combobox_name:exact",
            )
            self.assertEqual(page.role_calls, [("combobox", "Plan", True)])
        finally:
            browser.close()

    def test_semantic_combobox_requires_unique_native_enabled_single_select(self):
        cases = (
            ({"count": 2}, "ambiguous"),
            ({"tag": "div"}, "native select"),
            ({"disabled": True}, "disabled"),
            ({"multiple": True}, "multi-select"),
        )
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                browser, session, _permission, _page, query = _build(**kwargs)
                try:
                    with self.assertRaisesRegex(ManagedBrowserError, expected):
                        browser.observe_target(session.session_id, query)
                finally:
                    browser.close()

    def test_visible_label_selection_requires_fresh_same_node_postcondition(self):
        browser, session, permission, page, query = _build()
        try:
            observed = browser.observe_target(session.session_id, query)
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={"label": "Private Beta"},
            )
            effect = browser.act(
                action,
                BrowserActionAuthority.from_observation(
                    action, observed, permission
                ),
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_selected_label")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(
                effect.data["selected_label_sha256_after"],
                hashlib.sha256("Private Beta".encode("utf-8")).hexdigest(),
            )
            self.assertEqual(page.selected_value, "beta-private")
        finally:
            browser.close()

    def test_same_shape_combobox_replacement_after_dispatch_fails_closed(self):
        browser, session, permission, _page, query = _build(replace_on_select=True)
        try:
            observed = browser.observe_target(session.session_id, query)
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={"label": "Private Beta"},
            )
            effect = browser.act(
                action,
                BrowserActionAuthority.from_observation(
                    action, observed, permission
                ),
            )
            self.assertFalse(effect.success)
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertIn("replaced target node", effect.error or "")
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

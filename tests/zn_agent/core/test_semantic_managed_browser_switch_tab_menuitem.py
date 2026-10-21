from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
    BrowserSessionOwner,
)

_OWNER = BrowserSessionOwner(work_id="test", root_id="test", purpose="test")
from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.semantic_managed_browser import (
    ManagedBrowserError,
    SemanticPlaywrightManagedBrowser,
)


_ROLE_QUERY_KIND = {
    "switch": BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME,
    "tab": BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME,
    "menuitem": BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME,
}
_ROLE_NAME = {
    "switch": "Dark mode",
    "tab": "Settings",
    "menuitem": "Copy",
}


class _Element:
    def __init__(self, page, generation):
        self.page = page
        self.generation = generation
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "aria-selected" in expression:
            assert self.page.role == "tab", self.page.role
            if self.page.tab_aria_missing:
                return None
            return self.page.tab_selected
        if "aria-checked" in expression:
            assert self.page.role == "switch", self.page.role
            return {
                "connected": True,
                "supported": self.page.native,
                "disabled": self.page.disabled,
                "checked": self.page.switch_checked,
            }
        if "native_switch" in expression:
            assert self.page.role == "switch", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "button",
                "input_type": "",
                "role_attr": "switch" if self.page.native else "generic",
                "native_switch": self.page.native,
                "disabled": self.page.disabled,
            }
        if "native_tab" in expression:
            assert self.page.role == "tab", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "div",
                "input_type": "",
                "role_attr": "tab" if self.page.native else "generic",
                "native_tab": self.page.native,
                "disabled": self.page.disabled,
            }
        if "native_menuitem" in expression:
            assert self.page.role == "menuitem", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "li",
                "input_type": "",
                "role_attr": "menuitem" if self.page.native else "generic",
                "native_menuitem": self.page.native,
                "disabled": self.page.disabled,
            }
        if "element === other" in expression:
            return isinstance(arg, _Element) and self.generation == arg.generation
        raise AssertionError(f"unexpected element expression: {expression[:80]}")

    def click(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        self.page.click_dispatches += 1
        if self.page.role == "tab" and not self.page.tab_stuck:
            self.page.tab_selected = True

    def check(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        assert self.page.role == "switch", self.page.role
        self.page.check_dispatches += 1
        self.page.switch_checked = True

    def uncheck(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        assert self.page.role == "switch", self.page.role
        self.page.uncheck_dispatches += 1
        self.page.switch_checked = False

    def dispose(self):
        self.disposed = True


class _Locator:
    def __init__(self, page, count=1):
        self.page = page
        self._count = count

    def count(self):
        return self._count

    def element_handle(self):
        return _Element(self.page, 1)


class _Page:
    def __init__(self, *, role: str, count: int = 1):
        self.url = "https://example.com/start"
        self.role = role
        self.count = count
        self.role_calls = []
        self.native = True
        self.disabled = False
        self.switch_checked = False
        self.tab_selected = False
        self.tab_stuck = False
        self.tab_aria_missing = False
        self.click_dispatches = 0
        self.check_dispatches = 0
        self.uncheck_dispatches = 0
        self.viewport_size = {"width": 800, "height": 600}

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self, self.count)

    def title(self):
        return "Start"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.page = page
        self.pages = [page]

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


def _build(*, role, count=1):
    page = _Page(role=role, count=count)
    playwright = _Playwright(page)
    permission = BrowserPermissionContext(
        allow_page_interaction=True,
        allowed_origins=("https://example.com",),
    )
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(owner=_OWNER, permission=permission, headless=True)
    query = BrowserTargetQuery(
        kind=_ROLE_QUERY_KIND[role],
        value=_ROLE_NAME[role],
    )
    return browser, session, permission, page, query


def _act(browser, session, permission, observed, *, kind, args=None, expected=None):
    action = BrowserAction.create(
        session_id=session.session_id,
        page_id=observed.page_id,
        kind=kind,
        target=observed.target,
        args=dict(args or {}),
        expected=dict(expected or {}),
    )
    authority = BrowserActionAuthority.from_observation(action, observed, permission)
    return browser.act(action, authority)


class SemanticManagedBrowserSwitchTests(unittest.TestCase):
    def test_exact_named_switch_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="switch")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "switch")
            self.assertEqual(observed.target.name, "Dark mode")
            self.assertEqual(
                observed.target.selector_hint, "accessible_switch_name:exact"
            )
            self.assertEqual(page.role_calls, [("switch", "Dark mode", True)])
        finally:
            browser.close()

    def test_ambiguous_switch_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="switch", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_missing_switch_target_reports_not_found(self):
        browser, session, _permission, _page, query = _build(role="switch", count=0)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "was not found"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_non_switch_role_is_refused(self):
        browser, session, _permission, page, query = _build(role="switch")
        page.native = False
        try:
            with self.assertRaisesRegex(
                ManagedBrowserError, "currently supports only role=switch"
            ):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_disabled_switch_is_refused(self):
        browser, session, _permission, page, query = _build(role="switch")
        page.disabled = True
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "disabled"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_switch_check_turns_on_with_real_checked_state_postcondition(self):
        browser, session, permission, page, query = _build(role="switch")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CHECK)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_checked")
            self.assertFalse(effect.data["checked_before"])
            self.assertTrue(effect.data["checked_after"])
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.check_dispatches, 1)
            self.assertTrue(page.switch_checked)
        finally:
            browser.close()

    def test_switch_check_refuses_already_on_target(self):
        browser, session, permission, page, query = _build(role="switch")
        page.switch_checked = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CHECK)
            self.assertFalse(effect.success)
            self.assertIn("already checked", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_switch_uncheck_turns_off_with_real_checked_state_postcondition(self):
        browser, session, permission, page, query = _build(role="switch")
        page.switch_checked = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser, session, permission, observed, kind=BrowserActionKind.UNCHECK
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_unchecked")
            self.assertTrue(effect.data["checked_before"])
            self.assertFalse(effect.data["checked_after"])
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.uncheck_dispatches, 1)
            self.assertFalse(page.switch_checked)
        finally:
            browser.close()

    def test_switch_uncheck_refuses_already_off_target(self):
        browser, session, permission, page, query = _build(role="switch")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser, session, permission, observed, kind=BrowserActionKind.UNCHECK
            )
            self.assertFalse(effect.success)
            self.assertIn("already unchecked", effect.error or "")
            self.assertEqual(page.uncheck_dispatches, 0)
        finally:
            browser.close()


class SemanticManagedBrowserTabTests(unittest.TestCase):
    def test_exact_named_tab_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="tab")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "tab")
            self.assertEqual(observed.target.name, "Settings")
            self.assertEqual(observed.target.selector_hint, "accessible_tab_name:exact")
            self.assertEqual(page.role_calls, [("tab", "Settings", True)])
        finally:
            browser.close()

    def test_ambiguous_tab_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="tab", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_non_tab_role_is_refused(self):
        browser, session, _permission, page, query = _build(role="tab")
        page.native = False
        try:
            with self.assertRaisesRegex(
                ManagedBrowserError, "currently supports only role=tab"
            ):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_disabled_tab_is_refused(self):
        browser, session, _permission, page, query = _build(role="tab")
        page.disabled = True
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "disabled"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_tab_select_click_verifies_aria_selected_on_same_exact_node(self):
        browser, session, permission, page, query = _build(role="tab")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"aria_selected": True},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_tab_selected")
            self.assertFalse(effect.data["selected_before"])
            self.assertTrue(effect.data["selected_after"])
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.click_dispatches, 1)
            self.assertTrue(page.tab_selected)
        finally:
            browser.close()

    def test_tab_select_refuses_already_selected_target(self):
        browser, session, permission, page, query = _build(role="tab")
        page.tab_selected = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"aria_selected": True},
            )
            self.assertFalse(effect.success)
            self.assertIn("already selected", effect.error or "")
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()

    def test_tab_select_fails_when_aria_selected_does_not_flip(self):
        browser, session, permission, page, query = _build(role="tab")
        page.tab_stuck = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"aria_selected": True},
            )
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertFalse(effect.data["selected_after"])
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()

    def test_tab_select_refuses_tab_without_boolean_aria_selected(self):
        browser, session, permission, page, query = _build(role="tab")
        page.tab_aria_missing = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"aria_selected": True},
            )
            self.assertFalse(effect.success)
            self.assertIn("boolean aria-selected", effect.error or "")
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()

    def test_tab_select_rejects_non_true_expected(self):
        browser, session, permission, _page, query = _build(role="tab")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"aria_selected": False},
            )
            self.assertFalse(effect.success)
            self.assertIn("requires expected aria_selected true", effect.error or "")
        finally:
            browser.close()

    def test_tab_click_without_aria_selected_expected_is_not_offered(self):
        browser, session, permission, _page, query = _build(role="tab")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CLICK)
            self.assertFalse(effect.success)
            self.assertIn("generic browser click is not implemented", effect.error or "")
        finally:
            browser.close()


class SemanticManagedBrowserMenuitemTests(unittest.TestCase):
    def test_exact_named_menuitem_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="menuitem")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "menuitem")
            self.assertEqual(observed.target.name, "Copy")
            self.assertEqual(
                observed.target.selector_hint, "accessible_menuitem_name:exact"
            )
            self.assertEqual(page.role_calls, [("menuitem", "Copy", True)])
        finally:
            browser.close()

    def test_ambiguous_menuitem_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="menuitem", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_missing_menuitem_target_reports_not_found(self):
        browser, session, _permission, _page, query = _build(role="menuitem", count=0)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "was not found"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_non_menuitem_role_is_refused(self):
        browser, session, _permission, page, query = _build(role="menuitem")
        page.native = False
        try:
            with self.assertRaisesRegex(
                ManagedBrowserError, "currently supports only role=menuitem"
            ):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_disabled_menuitem_is_refused(self):
        browser, session, _permission, page, query = _build(role="menuitem")
        page.disabled = True
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "disabled"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_menuitem_click_is_explicitly_not_offered(self):
        browser, session, permission, page, query = _build(role="menuitem")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CLICK)
            self.assertFalse(effect.success)
            self.assertIn("generic browser click is not implemented", effect.error or "")
            self.assertEqual(page.click_dispatches, 0)
        finally:
            browser.close()


class SemanticActionKindMappingBatch2Tests(unittest.TestCase):
    def _map(self, kind_value: str, query_kind: BrowserTargetQueryKind):
        query = BrowserTargetQuery(kind=query_kind, value="Target")
        return BrowserResidentRpcServer._semantic_action_kind_from_params(kind_value, query)

    def test_batch2_roles_map_to_their_action_kinds(self):
        self.assertIs(
            self._map("check", BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME),
            BrowserActionKind.CHECK,
        )
        self.assertIs(
            self._map("uncheck", BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME),
            BrowserActionKind.UNCHECK,
        )
        self.assertIs(
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME),
            BrowserActionKind.CLICK,
        )

    def test_existing_mappings_still_hold(self):
        self.assertIs(
            self._map("check", BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME),
            BrowserActionKind.CHECK,
        )
        self.assertIs(
            self._map("uncheck", BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME),
            BrowserActionKind.UNCHECK,
        )
        self.assertIs(
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME),
            BrowserActionKind.CLICK,
        )

    def test_mismatched_kinds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("check", BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME)
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME)
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME)
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("uncheck", BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)

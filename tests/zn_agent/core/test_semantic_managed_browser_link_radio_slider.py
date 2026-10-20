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
)
from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.semantic_managed_browser import (
    ManagedBrowserError,
    SemanticPlaywrightManagedBrowser,
)


_ROLE_QUERY_KIND = {
    "link": BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME,
    "radio": BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME,
    "slider": BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME,
}
_ROLE_NAME = {
    "link": "Next",
    "radio": "Choice A",
    "slider": "Volume",
}


class _Element:
    def __init__(self, page, generation):
        self.page = page
        self.generation = generation
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "slider_set_ok" in expression:
            self.page.set_dispatches += 1
            requested = float(arg)
            clamped = min(max(requested, self.page.slider_min), self.page.slider_max)
            if not self.page.slider_ack:
                return {"slider_set_ok": False, "slider_set_reason": "mock-refused"}
            if not self.page.slider_stuck:
                self.page.slider_value = clamped
            return {"slider_set_ok": True, "slider_assigned": str(self.page.slider_value)}
        if "element.checked" in expression:
            assert self.page.role == "radio", self.page.role
            return {
                "connected": True,
                "supported": self.page.native,
                "disabled": self.page.disabled,
                "checked": self.page.radio_checked,
            }
        if "native_link" in expression:
            assert self.page.role == "link", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "a",
                "href": "/next" if self.page.native else "",
                "native_link": self.page.native,
            }
        if "native_radio" in expression:
            assert self.page.role == "radio", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": "radio",
                "supported": self.page.native,
                "native_radio": self.page.native,
                "disabled": self.page.disabled,
            }
        if "native_slider" in expression:
            assert self.page.role == "slider", self.page.role
            return {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": "range",
                "supported": self.page.native,
                "native_slider": self.page.native,
                "disabled": self.page.disabled,
                "slider_min": self.page.slider_min,
                "slider_max": self.page.slider_max,
                "slider_step": 1.0,
                "slider_value": self.page.slider_value,
            }
        if "element === other" in expression:
            return isinstance(arg, _Element) and self.generation == arg.generation
        raise AssertionError(f"unexpected element expression: {expression[:80]}")

    def click(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        self.page.click_dispatches += 1
        if not self.page.block_navigation:
            self.page.url = self.page.destination

    def check(self):
        if self.disposed:
            raise RuntimeError("disposed element")
        self.page.check_dispatches += 1
        self.page.radio_checked = True

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
    def __init__(self, *, role: str, destination: str, count: int = 1):
        self.url = "https://example.com/start"
        self.destination = destination
        self.role = role
        self.count = count
        self.role_calls = []
        self.block_navigation = False
        self.native = True
        self.disabled = False
        self.radio_checked = False
        self.slider_min = 0.0
        self.slider_max = 100.0
        self.slider_value = 20.0
        self.slider_stuck = False
        self.slider_ack = True
        self.click_dispatches = 0
        self.check_dispatches = 0
        self.set_dispatches = 0
        self.viewport_size = {"width": 800, "height": 600}

    def get_by_role(self, role, *, name, exact):
        self.role_calls.append((role, name, exact))
        return _Locator(self, self.count)

    def title(self):
        return "Done" if self.url == self.destination else "Start"

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


def _build(*, role, destination="https://example.com/done", count=1):
    page = _Page(role=role, destination=destination, count=count)
    playwright = _Playwright(page)
    permission = BrowserPermissionContext(
        allow_page_interaction=True,
        allowed_origins=("https://example.com",),
    )
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=permission, headless=True)
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


class SemanticManagedBrowserLinkTests(unittest.TestCase):
    def test_exact_named_native_link_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="link")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "link")
            self.assertEqual(observed.target.name, "Next")
            self.assertEqual(observed.target.selector_hint, "accessible_link_name:exact")
            self.assertEqual(page.role_calls, [("link", "Next", True)])
        finally:
            browser.close()

    def test_ambiguous_link_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="link", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_missing_link_target_reports_not_found(self):
        browser, session, _permission, _page, query = _build(role="link", count=0)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "was not found"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_link_navigation_click_verifies_expected_url(self):
        browser, session, permission, page, query = _build(role="link")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"url_equals": "https://example.com/done"},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.url_after, "https://example.com/done")
            self.assertEqual(
                effect.postcondition,
                "url_equals_after_fresh_semantic_link_click",
            )
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()

    def test_link_click_fails_when_expected_url_not_reached(self):
        browser, session, permission, page, query = _build(role="link")
        page.block_navigation = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.CLICK,
                expected={"url_equals": "https://example.com/done"},
            )
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
            self.assertEqual(page.click_dispatches, 1)
        finally:
            browser.close()

    def test_link_click_without_expected_url_is_not_offered(self):
        browser, session, permission, _page, query = _build(role="link")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CLICK)
            self.assertFalse(effect.success)
            self.assertIn("generic browser click is not implemented", effect.error or "")
        finally:
            browser.close()


class SemanticManagedBrowserRadioTests(unittest.TestCase):
    def test_exact_named_native_radio_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="radio")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "radio")
            self.assertEqual(observed.target.name, "Choice A")
            self.assertEqual(observed.target.selector_hint, "accessible_radio_name:exact")
            self.assertEqual(page.role_calls, [("radio", "Choice A", True)])
        finally:
            browser.close()

    def test_ambiguous_radio_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="radio", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_non_native_radio_is_refused(self):
        browser, session, _permission, page, query = _build(role="radio")
        page.native = False
        try:
            with self.assertRaisesRegex(
                ManagedBrowserError, "currently supports only native"
            ):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_disabled_radio_is_refused(self):
        browser, session, _permission, page, query = _build(role="radio")
        page.disabled = True
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "disabled"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_radio_check_selects_with_real_checked_state_postcondition(self):
        browser, session, permission, page, query = _build(role="radio")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CHECK)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_checked")
            self.assertFalse(effect.data["checked_before"])
            self.assertTrue(effect.data["checked_after"])
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.check_dispatches, 1)
            self.assertTrue(page.radio_checked)
        finally:
            browser.close()

    def test_radio_check_refuses_already_selected_target(self):
        browser, session, permission, page, query = _build(role="radio")
        page.radio_checked = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(browser, session, permission, observed, kind=BrowserActionKind.CHECK)
            self.assertFalse(effect.success)
            self.assertIn("already checked", effect.error or "")
            self.assertEqual(page.check_dispatches, 0)
        finally:
            browser.close()

    def test_radio_uncheck_is_refused(self):
        browser, session, permission, _page, query = _build(role="radio")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser, session, permission, observed, kind=BrowserActionKind.UNCHECK
            )
            self.assertFalse(effect.success)
            self.assertIn("native checkbox target", effect.error or "")
        finally:
            browser.close()


class SemanticManagedBrowserSliderTests(unittest.TestCase):
    def test_exact_named_native_slider_binds_as_accessibility_target(self):
        browser, session, _permission, page, query = _build(role="slider")
        try:
            observed = browser.observe_target(session.session_id, query)
            self.assertIsNotNone(observed.target)
            assert observed.target is not None
            self.assertIs(observed.target.kind, BrowserTargetKind.ACCESSIBILITY_NODE)
            self.assertEqual(observed.target.role, "slider")
            self.assertEqual(observed.target.name, "Volume")
            self.assertEqual(observed.target.selector_hint, "accessible_slider_name:exact")
            self.assertEqual(page.role_calls, [("slider", "Volume", True)])
        finally:
            browser.close()

    def test_ambiguous_slider_match_fails_closed(self):
        browser, session, _permission, _page, query = _build(role="slider", count=2)
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_disabled_slider_is_refused(self):
        browser, session, _permission, page, query = _build(role="slider")
        page.disabled = True
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "disabled"):
                browser.observe_target(session.session_id, query)
        finally:
            browser.close()

    def test_slider_set_value_reads_back_on_same_exact_node(self):
        browser, session, permission, page, query = _build(role="slider")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": 75},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_slider_value_set")
            self.assertEqual(effect.data["value_before"], 20.0)
            self.assertEqual(effect.data["value_requested"], 75.0)
            self.assertEqual(effect.data["value_after"], 75.0)
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.set_dispatches, 1)
            self.assertEqual(page.slider_value, 75.0)
        finally:
            browser.close()

    def test_slider_set_value_clamps_into_observed_bounds(self):
        browser, session, permission, page, query = _build(role="slider")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": 150},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["value_requested"], 100.0)
            self.assertEqual(effect.data["value_after"], 100.0)
        finally:
            browser.close()

    def test_slider_set_value_refuses_already_at_requested_value(self):
        browser, session, permission, page, query = _build(role="slider")
        page.slider_value = 75.0
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": 75},
            )
            self.assertFalse(effect.success)
            self.assertIn("already at the requested value", effect.error or "")
            self.assertEqual(page.set_dispatches, 0)
        finally:
            browser.close()

    def test_slider_set_value_fails_when_read_back_mismatches(self):
        browser, session, permission, page, query = _build(role="slider")
        page.slider_stuck = True
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": 75},
            )
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertEqual(effect.data["value_after"], 20.0)
        finally:
            browser.close()

    def test_slider_set_value_fails_when_page_does_not_acknowledge(self):
        browser, session, permission, page, query = _build(role="slider")
        page.slider_ack = False
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": 75},
            )
            self.assertFalse(effect.success)
            self.assertIn("not acknowledged", effect.error or "")
        finally:
            browser.close()

    def test_slider_set_value_rejects_non_numeric_arg(self):
        browser, session, permission, _page, query = _build(role="slider")
        try:
            observed = browser.observe_target(session.session_id, query)
            effect = _act(
                browser,
                session,
                permission,
                observed,
                kind=BrowserActionKind.SET_SLIDER_VALUE,
                args={"value": "loud"},
            )
            self.assertFalse(effect.success)
            self.assertIn("numeric", effect.error or "")
        finally:
            browser.close()


class SemanticActionKindMappingTests(unittest.TestCase):
    def _map(self, kind_value: str, query_kind: BrowserTargetQueryKind):
        query = BrowserTargetQuery(kind=query_kind, value="Target")
        return BrowserResidentRpcServer._semantic_action_kind_from_params(kind_value, query)

    def test_new_roles_map_to_their_action_kinds(self):
        self.assertIs(
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME),
            BrowserActionKind.CLICK,
        )
        self.assertIs(
            self._map("check", BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME),
            BrowserActionKind.CHECK,
        )
        self.assertIs(
            self._map("set_slider_value", BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME),
            BrowserActionKind.SET_SLIDER_VALUE,
        )

    def test_existing_mappings_still_hold(self):
        self.assertIs(
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME),
            BrowserActionKind.CLICK,
        )
        self.assertIs(
            self._map("check", BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME),
            BrowserActionKind.CHECK,
        )

    def test_mismatched_kinds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("uncheck", BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME)
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("click", BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME)
        with self.assertRaisesRegex(ValueError, "requires one of query kinds"):
            self._map("set_slider_value", BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME)
        with self.assertRaisesRegex(ValueError, "unsupported browser semantic action kind"):
            self._map("fly", BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME)

    def test_set_slider_value_requires_page_interaction_permission(self):
        allowed = BrowserPermissionContext(allow_page_interaction=True)
        denied = BrowserPermissionContext()
        self.assertTrue(allowed.allows_action(BrowserActionKind.SET_SLIDER_VALUE))
        self.assertFalse(denied.allows_action(BrowserActionKind.SET_SLIDER_VALUE))


if __name__ == "__main__":
    unittest.main(verbosity=2)

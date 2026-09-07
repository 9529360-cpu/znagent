from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserAction, BrowserActionAuthority, BrowserActionKind
from tests.zn_agent.core.test_browser_scene_actions import (
    ORIGIN,
    _Frame,
    _ItemLocator,
    _Node,
    _Page as _BasePage,
    _authorized,
    _build,
    _permission,
    _target,
)


class _PopupExpectation:
    def __init__(self, page, timeout):
        self.page, self.timeout, self.value = page, timeout, None

    def __enter__(self):
        self.page.expectation_active = True
        self.page.expect_popup_timeouts.append(self.timeout)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.page.expectation_active = False
        if exc_type is not None:
            return False
        if self.page.expect_popup_error is not None:
            raise self.page.expect_popup_error
        if self.page.captured_popup is None:
            raise RuntimeError("popup did not appear")
        self.value = self.page.captured_popup
        self.page.captured_popup = None
        return False


class _PopupPage(_BasePage):
    def __init__(self, *, url, main_frame, visible=True, opener=None):
        super().__init__(url=url, main_frame=main_frame, visible=visible)
        self._opener = opener
        self.captured_popup = None
        self.expectation_active = False
        self.expect_popup_error = None
        self.expect_popup_timeouts = []
        self.bring_to_front_calls = 0

    def expect_popup(self, *, timeout):
        return _PopupExpectation(self, timeout)

    def opener(self):
        return self._opener

    def bring_to_front(self):
        self.bring_to_front_calls += 1
        for page in self.context.pages:
            page.visible = page is self

    def close(self):
        super().close()
        if self.context is not None:
            self.context.pages = [page for page in self.context.pages if page is not self]


def _fixture(*, permission=None, user=False):
    main = _Frame(url=ORIGIN + "/start")
    opener = _PopupPage(url=main.url, main_frame=main, visible=True)
    node = _Node(tag="a")
    main.roles["link"] = [_ItemLocator(role="link", name="Open popup", node=node)]
    browser, identity, context, provider = _build(
        opener,
        permission=permission,
        user=user,
    )
    return browser, identity, context, provider, opener, node


def _action(browser, identity, *, args=None, expected=None):
    _scene, target = _target(browser, identity, name="Open popup")
    return _authorized(
        browser,
        identity,
        target,
        BrowserActionKind.CLICK,
        args=args,
        expected=expected,
    )


def _popup(url, opener=None):
    return _PopupPage(url=url, main_frame=_Frame(url=url), visible=False, opener=opener)


def _emit(opener, context, popup, *, extra=None):
    if not opener.expectation_active:
        raise AssertionError("popup created outside expect_popup")
    popup.context = context
    context.pages.append(popup)
    opener.captured_popup = popup
    if extra is not None:
        extra.context = context
        context.pages.append(extra)


class BrowserCausalPopupTests(unittest.TestCase):
    def test_success_stable_identity_ownership_default_and_switch_round_trip(self):
        browser, identity, context, _provider, opener, node = _fixture()
        popup_url = ORIGIN + "/popup"
        popup = _popup(popup_url, opener)
        node.on_mutation = lambda: _emit(opener, context, popup)
        try:
            _observed, click, authority = _action(
                browser,
                identity,
                expected={"popup_url_equals": popup_url},
            )
            opener_id = click.page_id
            effect = browser.act(click, authority)
            self.assertTrue(effect.success, effect.error)
            popup_id = effect.data["popup_page_id"]
            self.assertNotEqual(popup_id, opener_id)
            self.assertEqual(effect.postcondition, "causal_popup_opener_and_url_verified")
            self.assertEqual(effect.data["opener_page_id"], opener_id)
            self.assertEqual(effect.data["new_page_ids"], [popup_id])
            self.assertEqual(effect.data["expected_popup_url"], popup_url)
            self.assertEqual(effect.data["popup_url"], popup_url)
            self.assertEqual(effect.data["ownership"], "zn_created")
            self.assertTrue(effect.data["opener_matches"])
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertEqual(effect.data["default_page_id_before"], opener_id)
            self.assertEqual(effect.data["default_page_id_after"], opener_id)
            self.assertEqual(browser._sessions[identity.session_id].default_page_id, opener_id)

            for page_id, expected_url in ((popup_id, popup_url), (opener_id, ORIGIN + "/start")):
                observed = browser.observe(identity.session_id, page_id=page_id)
                switch = BrowserAction.create(
                    session_id=identity.session_id,
                    page_id=page_id,
                    kind=BrowserActionKind.SWITCH_TAB,
                )
                switch_authority = BrowserActionAuthority.from_observation(
                    switch,
                    observed,
                    browser._sessions[identity.session_id].permission,
                )
                switched = browser.act(switch, switch_authority)
                self.assertTrue(switched.success, switched.error)
                fresh = browser.observe(identity.session_id)
                self.assertEqual((fresh.page_id, fresh.url), (page_id, expected_url))

            tab = next(
                item
                for item in browser.observe_browser_workspace(identity.session_id).tabs
                if item.page_id == popup_id
            )
            self.assertEqual(tab.ownership, "zn_created")
        finally:
            browser.close()

    def test_missing_popup_fails_closed(self):
        browser, identity, _context, _provider, _opener, node = _fixture()
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("popup did not appear", effect.error or "")
            self.assertEqual(node.click_calls, 1)
        finally:
            browser.close()

    def test_wrong_opener_rolls_back_only_causal_popup(self):
        browser, identity, context, _provider, opener, node = _fixture()
        existing = _popup(ORIGIN + "/existing")
        existing.context = context
        context.pages.append(existing)
        popup = _popup(ORIGIN + "/popup", existing)
        node.on_mutation = lambda: _emit(opener, context, popup)
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("opener", (effect.error or "").lower())
            self.assertTrue(effect.data["rollback_complete"])
            self.assertEqual(popup.close_calls, 1)
            self.assertEqual(existing.close_calls, 0)
            self.assertIn(existing, context.pages)
        finally:
            browser.close()

    def test_wrong_and_out_of_scope_urls_fail_with_exact_rollback(self):
        for actual_url, error_fragment, expected_evidence_url in (
            (ORIGIN + "/wrong", "postcondition", ORIGIN + "/wrong"),
            ("https://other.test/outside", "permitted network boundary", ""),
        ):
            with self.subTest(actual_url=actual_url):
                browser, identity, context, _provider, opener, node = _fixture()
                popup = _popup(actual_url, opener)
                node.on_mutation = lambda p=popup: _emit(opener, context, p)
                try:
                    _o, action, authority = _action(
                        browser,
                        identity,
                        expected={"popup_url_equals": ORIGIN + "/popup"},
                    )
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(error_fragment, effect.error or "")
                    self.assertEqual(effect.data["popup_url"], expected_evidence_url)
                    self.assertEqual(popup.close_calls, 1)
                    self.assertTrue(effect.data["rollback_complete"])
                finally:
                    browser.close()

    def test_causal_popup_plus_other_fresh_page_is_ambiguous_without_claiming_or_closing_other(self):
        browser, identity, context, _provider, opener, node = _fixture()
        popup = _popup(ORIGIN + "/popup", opener)
        extra = _popup(ORIGIN + "/concurrent")
        node.on_mutation = lambda: _emit(opener, context, popup, extra=extra)
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("ambiguous", (effect.error or "").lower())
            self.assertEqual(popup.close_calls, 1)
            self.assertEqual(extra.close_calls, 0)
            self.assertIn(extra, context.pages)
            state = browser._scene_state(browser._sessions[identity.session_id])
            self.assertNotIn(effect.data["popup_page_id"], state.page_ownership)
            self.assertEqual(len(effect.data["new_page_ids"]), 1)
            self.assertNotIn(effect.data["new_page_ids"][0], state.page_ownership)
        finally:
            browser.close()

    def test_preexisting_page_is_not_misattributed(self):
        browser, identity, context, _provider, opener, node = _fixture()
        existing = _popup(ORIGIN + "/existing")
        existing.context = context
        context.pages.append(existing)
        popup = _popup(ORIGIN + "/popup", opener)
        node.on_mutation = lambda: _emit(opener, context, popup)
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["new_page_ids"], [effect.data["popup_page_id"]])
            self.assertEqual(existing.close_calls, 0)
        finally:
            browser.close()

    def test_schema_and_authority_fail_before_provider_observation(self):
        cases = (
            (_permission(), {"force": True}, {"popup_url_equals": ORIGIN + "/popup"}),
            (_permission(), {}, {"popup_url_equals": ORIGIN + "/popup", "url_equals": ORIGIN + "/done"}),
            (_permission(), {}, {"popup_url_equals": ORIGIN + "/popup", "extra": True}),
            (_permission(), {}, {"popup_url_equals": ""}),
            (_permission(), {}, {"popup_url_equals": "about:blank"}),
            (_permission(navigation=False), {}, {"popup_url_equals": ORIGIN + "/popup"}),
            (_permission(), {}, {"popup_url_equals": "https://other.test/popup"}),
        )
        for permission, args, expected in cases:
            with self.subTest(args=args, expected=expected):
                browser, identity, _context, _provider, opener, node = _fixture(permission=permission)
                try:
                    _o, action, authority = _action(browser, identity, args=args, expected=expected)
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertEqual(node.click_calls, 0)
                    self.assertEqual(opener.expect_popup_timeouts, [])
                finally:
                    browser.close()

    def test_stale_replaced_target_fails_before_expectation_or_click(self):
        browser, identity, _context, _provider, opener, node = _fixture()
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            opener.main_frame.roles["link"][0].node = _Node(tag="a")
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(node.click_calls, 0)
            self.assertEqual(opener.expect_popup_timeouts, [])
        finally:
            browser.close()

    def test_user_plane_fails_closed_before_popup_observation_or_click(self):
        browser, identity, context, provider, opener, node = _fixture(user=True)
        try:
            _o, action, authority = _action(
                browser, identity, expected={"popup_url_equals": ORIGIN + "/popup"}
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("existing user browser", effect.error or "")
            self.assertEqual(node.click_calls, 0)
            self.assertEqual(opener.expect_popup_timeouts, [])
            self.assertEqual(len(context.pages), 1)
            self.assertEqual(provider.close_calls, 0)
        finally:
            browser.close_session(identity.session_id)

    def test_provider_without_expect_popup_fails_closed(self):
        main = _Frame(url=ORIGIN + "/start")
        page = _BasePage(url=main.url, main_frame=main)
        node = _Node(tag="a")
        main.roles["link"] = [_ItemLocator(role="link", name="Open popup", node=node)]
        browser, identity, _context, _provider = _build(page)
        try:
            _scene, target = _target(browser, identity, name="Open popup")
            _o, action, authority = _authorized(
                browser,
                identity,
                target,
                BrowserActionKind.CLICK,
                expected={"popup_url_equals": ORIGIN + "/popup"},
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("action-scoped popup observation", effect.error or "")
            self.assertEqual(node.click_calls, 0)
        finally:
            browser.close()

    def test_existing_url_equals_click_is_unchanged(self):
        browser, identity, _context, _provider, opener, node = _fixture()
        done = ORIGIN + "/done"
        node.on_mutation = lambda: setattr(opener, "url", done)
        try:
            _o, action, authority = _action(
                browser, identity, expected={"url_equals": done}
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "url_equals_after_exact_scene_target_click")
            self.assertEqual(effect.url_after, done)
            self.assertEqual(opener.expect_popup_timeouts, [])
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

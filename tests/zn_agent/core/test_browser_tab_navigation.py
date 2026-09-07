from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.browser_scene import BrowserScene, _PageSceneState
from zn_agent.core.managed_browser import _ManagedTargetBinding
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser


class _Response:
    pass


class _Handle:
    def __init__(self):
        self.disposed = False

    def dispose(self):
        self.disposed = True


class _Page:
    def __init__(self, context, *, url="about:blank", visible=False):
        self.context = context
        self.url = url
        self._title = url
        self.visible = visible
        self.closed = False
        self.viewport_size = {"width": 1280, "height": 720}
        self.history = [url]
        self.history_index = 0
        self.goto_error = None
        self.goto_override = None
        self.activation_mode = "exclusive"
        self.bring_to_front_calls = 0
        self.close_calls = 0
        self.go_back_calls = 0
        self.go_forward_calls = 0
        self.reload_calls = 0

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.readyState !== undefined":
            return True
        if expression == "document.visibilityState":
            return "visible" if self.visible else "hidden"
        if expression == "document.visibilityState === 'visible'":
            return self.visible
        raise AssertionError(expression)

    def is_closed(self):
        return self.closed

    def goto(self, url, *, wait_until):
        del wait_until
        if self.goto_error is not None:
            raise self.goto_error
        final_url = self.goto_override or url
        self.history = self.history[: self.history_index + 1]
        self.history.append(final_url)
        self.history_index += 1
        self.url = final_url
        self._title = final_url.rsplit("/", 1)[-1] or "root"
        return _Response()

    def set_history(self, *urls):
        self.history = list(urls)
        self.history_index = len(self.history) - 1
        self.url = self.history[self.history_index]
        self._title = self.url.rsplit("/", 1)[-1]

    def go_back(self, *, wait_until):
        del wait_until
        self.go_back_calls += 1
        if self.history_index <= 0:
            return None
        self.history_index -= 1
        self.url = self.history[self.history_index]
        return _Response()

    def go_forward(self, *, wait_until):
        del wait_until
        self.go_forward_calls += 1
        if self.history_index >= len(self.history) - 1:
            return None
        self.history_index += 1
        self.url = self.history[self.history_index]
        return _Response()

    def reload(self, *, wait_until):
        del wait_until
        self.reload_calls += 1
        return _Response()

    def bring_to_front(self):
        self.bring_to_front_calls += 1
        if self.activation_mode == "exclusive":
            for page in self.context.pages:
                page.visible = page is self
        elif self.activation_mode == "ambiguous":
            for page in self.context.pages:
                page.visible = True

    def close(self):
        self.close_calls += 1
        self.closed = True
        self.context.pages = [page for page in self.context.pages if page is not self]


class _Context:
    def __init__(self, *, user=False):
        self.pages = []
        self.user = user
        self.new_page_calls = 0
        self.next_page_goto_error = None
        self.next_page_goto_override = None
        self.closed = False

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def set_default_timeout(self, value):
        self.action_timeout = value

    def route(self, pattern, handler):
        self.route_handler = handler

    def route_web_socket(self, pattern, handler):
        self.websocket_handler = handler

    def new_page(self):
        self.new_page_calls += 1
        page = _Page(self, visible=not self.user)
        page.goto_error = self.next_page_goto_error
        page.goto_override = self.next_page_goto_override
        self.next_page_goto_error = None
        self.next_page_goto_override = None
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class _Browser:
    version = "fake-1"

    def __init__(self, context):
        self.context = context
        self.contexts = [context]
        self.closed = False

    def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self.context

    def close(self):
        self.closed = True


class _Chromium:
    def __init__(self, browser):
        self.browser = browser
        self.endpoints = []

    def launch(self, *, headless):
        self.headless = headless
        return self.browser

    def connect_over_cdp(self, endpoint):
        self.endpoints.append(endpoint)
        return self.browser


class _Playwright:
    def __init__(self, browser):
        self.browser = browser
        self.chromium = _Chromium(browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class _InspectableBrowser(SemanticPlaywrightManagedBrowser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene_invalidations = []

    def _scene_invalidate_page(self, session_id: str, page_id: str) -> None:
        self.scene_invalidations.append((session_id, page_id))
        super()._scene_invalidate_page(session_id, page_id)


class BrowserTabNavigationTests(unittest.TestCase):
    ORIGIN = "https://example.test"

    def _managed(self, *, permission=None):
        context = _Context()
        provider = _Browser(context)
        playwright = _Playwright(provider)
        adapter = _InspectableBrowser(
            playwright_factory=lambda: _Starter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        identity = adapter.open_session(
            permission=permission
            or BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
                allowed_origins=(self.ORIGIN,),
            ),
            headless=True,
        )
        return adapter, context, identity

    def _user(self, *, two_pages=False):
        context = _Context(user=True)
        first = _Page(context, url=self.ORIGIN + "/one", visible=True)
        context.pages.append(first)
        second = None
        if two_pages:
            second = _Page(context, url=self.ORIGIN + "/two", visible=False)
            context.pages.append(second)
        provider = _Browser(context)
        playwright = _Playwright(provider)
        adapter = AuthorizedCDPUserBrowser(
            endpoint="http://127.0.0.1:9222",
            playwright_factory=lambda: _Starter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        identity = adapter.open_session(
            permission=BrowserPermissionContext(
                allow_navigation=True,
                allow_page_interaction=True,
                allowed_origins=(self.ORIGIN,),
            )
        )
        return adapter, context, identity, first, second

    @staticmethod
    def _authority(adapter, identity, action, *, page_id=""):
        observation = adapter.observe(identity.session_id, page_id=page_id)
        session = adapter._sessions[identity.session_id]
        return observation, BrowserActionAuthority.from_observation(
            action,
            observation,
            session.permission,
        )

    def _open(self, adapter, identity, url):
        current = adapter.observe(identity.session_id)
        action = BrowserAction.create(
            session_id=identity.session_id,
            kind=BrowserActionKind.OPEN_TAB,
            args={"url": url},
            expected={"url_equals": url},
        )
        permission = adapter._sessions[identity.session_id].permission
        authority = BrowserActionAuthority.from_observation(action, current, permission)
        return adapter.act(action, authority)

    def test_contract_permission_mapping_and_open_navigation_requirement(self):
        page_only = BrowserPermissionContext(allow_page_interaction=True)
        self.assertTrue(page_only.allows_action(BrowserActionKind.OPEN_TAB))
        self.assertTrue(page_only.allows_action(BrowserActionKind.SWITCH_TAB))
        self.assertTrue(page_only.allows_action(BrowserActionKind.CLOSE_TAB))
        self.assertFalse(page_only.allows_action(BrowserActionKind.BACK))
        nav = BrowserPermissionContext(allow_navigation=True)
        for kind in (BrowserActionKind.BACK, BrowserActionKind.FORWARD, BrowserActionKind.RELOAD):
            self.assertTrue(nav.allows_action(kind))

        adapter, context, identity = self._managed(permission=page_only)
        try:
            observed = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.ORIGIN + "/two"},
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            authority = BrowserActionAuthority.from_observation(action, observed, page_only)
            before = context.new_page_calls
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("navigation permission", effect.error or "")
            self.assertEqual(context.new_page_calls, before)
        finally:
            adapter.close()

    def test_stale_authority_rejected_before_switch_dispatch(self):
        adapter, context, identity = self._managed()
        try:
            second = _Page(context, url=self.ORIGIN + "/two")
            context.pages.append(second)
            registered = adapter.observe(identity.session_id)
            second_id = registered.metadata["page_ids"][1]
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            session = adapter._sessions[identity.session_id]
            session.last_observation[second_id] = BrowserObservation(
                session=identity,
                page_id=second_id,
                captured_at=observed.captured_at + "-new",
                url=second.url,
                title="two",
                load_state="complete",
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", effect.error or "")
            self.assertEqual(second.bring_to_front_calls, 0)
        finally:
            adapter.close()

    def test_open_requires_explicit_http_url_expected_and_allowed_origin(self):
        adapter, context, identity = self._managed()
        try:
            base = adapter.observe(identity.session_id)
            permission = adapter._sessions[identity.session_id].permission
            cases = (
                ({}, {"url_equals": self.ORIGIN + "/two"}),
                ({"url": self.ORIGIN + "/two"}, {}),
                ({"url": "about:blank"}, {"url_equals": "about:blank"}),
                ({"url": "https://other.test/two"}, {"url_equals": "https://other.test/two"}),
            )
            for args, expected in cases:
                action = BrowserAction.create(
                    session_id=identity.session_id,
                    kind=BrowserActionKind.OPEN_TAB,
                    args=args,
                    expected=expected,
                )
                authority = BrowserActionAuthority.from_observation(action, base, permission)
                before = context.new_page_calls
                effect = adapter.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(context.new_page_calls, before)
        finally:
            adapter.close()

    def test_open_success_has_stable_fresh_identity_and_ownership(self):
        adapter, _context, identity = self._managed()
        try:
            adapter.observe(identity.session_id)
            effect = self._open(adapter, identity, self.ORIGIN + "/two")
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["ownership"], "zn_created")
            self.assertEqual(effect.page_id, effect.data["fresh_page_id"])
            session = adapter._sessions[identity.session_id]
            self.assertEqual(session.default_page_id, effect.page_id)
            fresh = adapter.observe(identity.session_id)
            self.assertEqual(fresh.page_id, effect.page_id)
            self.assertEqual(fresh.url, self.ORIGIN + "/two")
            tab = next(
                tab
                for tab in adapter.observe_browser_workspace(identity.session_id).tabs
                if tab.page_id == effect.page_id
            )
            self.assertEqual(tab.ownership, "zn_created")
        finally:
            adapter.close()

    def test_open_wrong_postcondition_rolls_back_exact_page_and_keeps_unrelated(self):
        adapter, context, identity = self._managed()
        try:
            original = adapter.observe(identity.session_id)
            unrelated = _Page(context, url=self.ORIGIN + "/unrelated")
            context.pages.append(unrelated)
            adapter.observe(identity.session_id)
            context.next_page_goto_override = self.ORIGIN + "/wrong"
            action = BrowserAction.create(
                session_id=identity.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.ORIGIN + "/two"},
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            current = adapter.observe(identity.session_id)
            permission = adapter._sessions[identity.session_id].permission
            authority = BrowserActionAuthority.from_observation(action, current, permission)
            before_pages = list(context.pages)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertTrue(effect.data["rollback_complete"])
            self.assertEqual(context.pages, before_pages)
            self.assertFalse(unrelated.closed)
            self.assertEqual(adapter.observe(identity.session_id).page_id, original.page_id)
        finally:
            adapter.close()

    def test_open_navigation_exception_rolls_back_and_restores_default(self):
        adapter, context, identity = self._managed()
        try:
            original = adapter.observe(identity.session_id)
            context.next_page_goto_error = RuntimeError("navigation failed")
            action = BrowserAction.create(
                session_id=identity.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.ORIGIN + "/two"},
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                original,
                adapter._sessions[identity.session_id].permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertTrue(effect.data["rollback_complete"])
            self.assertEqual(len(context.pages), 1)
            self.assertEqual(adapter.observe(identity.session_id).page_id, original.page_id)
        finally:
            adapter.close()

    def test_user_open_fails_closed_without_new_page(self):
        adapter, context, identity, _first, _second = self._user()
        try:
            current = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                kind=BrowserActionKind.OPEN_TAB,
                args={"url": self.ORIGIN + "/two"},
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                current,
                adapter._sessions[identity.session_id].permission,
            )
            before = context.new_page_calls
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("existing user browser", effect.error or "")
            self.assertEqual(context.new_page_calls, before)
        finally:
            adapter.close_session(identity.session_id)

    def test_managed_switch_uses_exact_default_fresh_observation_not_visibility(self):
        adapter, context, identity = self._managed()
        try:
            first = adapter.observe(identity.session_id)
            second = _Page(context, url=self.ORIGIN + "/two", visible=False)
            second.activation_mode = "none"
            context.pages.append(second)
            refreshed = adapter.observe(identity.session_id)
            second_id = refreshed.metadata["page_ids"][1]
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertFalse(second.visible)
            self.assertEqual(effect.data["default_page_id"], second_id)
            self.assertEqual(effect.data["fresh_page_id"], second_id)
            self.assertFalse(effect.data["os_foreground_verified"])
            self.assertEqual(adapter.observe(identity.session_id).page_id, second_id)
            self.assertNotEqual(first.page_id, second_id)
            self.assertIn((identity.session_id, second_id), adapter.scene_invalidations)
        finally:
            adapter.close()

    def test_switch_closed_page_rejected(self):
        adapter, context, identity = self._managed()
        try:
            second = _Page(context, url=self.ORIGIN + "/two")
            context.pages.append(second)
            refreshed = adapter.observe(identity.session_id)
            second_id = refreshed.metadata["page_ids"][1]
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            second.close()
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("unknown managed browser page", effect.error or "")
        finally:
            adapter.close()

    def test_switch_out_of_scope_page_rejected_before_activation(self):
        adapter, context, identity = self._managed()
        try:
            unsafe = _Page(context, url="https://other.test/page")
            context.pages.append(unsafe)
            session = adapter._sessions[identity.session_id]
            adapter._reconcile_pages(session)
            unsafe_id = next(page_id for page_id, page in session.pages.items() if page is unsafe)
            fake = BrowserObservation(
                session=identity,
                page_id=unsafe_id,
                captured_at="unsafe-observation",
                url=unsafe.url,
                title="unsafe",
                load_state="complete",
            )
            session.last_observation[unsafe_id] = fake
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=unsafe_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            authority = BrowserActionAuthority.from_observation(action, fake, session.permission)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("network boundary", effect.error or "")
            self.assertEqual(unsafe.bring_to_front_calls, 0)
        finally:
            adapter.close()

    def test_user_switch_requires_unique_visible_target(self):
        adapter, _context, identity, first, second = self._user(two_pages=True)
        assert second is not None
        try:
            workspace = adapter.observe_browser_workspace(identity.session_id)
            second_id = next(tab.page_id for tab in workspace.tabs if tab.url.endswith("/two"))
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertFalse(first.visible)
            self.assertTrue(second.visible)
            self.assertEqual(second.bring_to_front_calls, 1)
            self.assertEqual(adapter.observe(identity.session_id).page_id, second_id)
        finally:
            adapter.close_session(identity.session_id)

    def test_user_switch_ambiguous_visibility_fails_closed(self):
        adapter, _context, identity, _first, second = self._user(two_pages=True)
        assert second is not None
        try:
            original = adapter.observe(identity.session_id)
            workspace = adapter.observe_browser_workspace(identity.session_id)
            second_id = next(tab.page_id for tab in workspace.tabs if tab.url.endswith("/two"))
            second.activation_mode = "ambiguous"
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.SWITCH_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("uniquely observed", effect.error or "")
            self.assertEqual(adapter._sessions[identity.session_id].default_page_id, original.page_id)
        finally:
            adapter.close_session(identity.session_id)

    def test_close_current_owned_tab_promotes_default_and_cleans_evidence(self):
        adapter, _context, identity = self._managed()
        try:
            first = adapter.observe(identity.session_id)
            opened = self._open(adapter, identity, self.ORIGIN + "/two")
            self.assertTrue(opened.success, opened.error)
            page_id = opened.page_id
            session = adapter._sessions[identity.session_id]
            handle = _Handle()
            target = BrowserTarget(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserTargetKind.ELEMENT,
                target_id="dummy-target",
                observed_at="dummy-observed",
                url=self.ORIGIN + "/two",
                frame_id="main",
            )
            session.target_bindings[page_id] = _ManagedTargetBinding(
                target=target,
                query=BrowserTargetQuery(kind=BrowserTargetQueryKind.DOM_ID, value="dummy"),
                handle=handle,
            )
            adapter._scene_state(session).page_scenes[page_id] = _PageSceneState(
                scene=BrowserScene(
                    scene_id="dummy-scene",
                    session_id=identity.session_id,
                    page_id=page_id,
                    captured_at="dummy-scene-time",
                    url=self.ORIGIN + "/two",
                    title="two",
                    frames=(),
                    targets=(),
                )
            )
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.CLOSE_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=page_id)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["fresh_default_page_id"], first.page_id)
            self.assertEqual(adapter.observe(identity.session_id).page_id, first.page_id)
            self.assertTrue(handle.disposed)
            self.assertNotIn(page_id, session.target_bindings)
            self.assertNotIn(page_id, adapter._scene_state(session).page_scenes)
        finally:
            adapter.close()

    def test_close_last_live_and_user_existing_are_rejected(self):
        adapter, _context, identity = self._managed()
        try:
            current = adapter.observe(identity.session_id)
            page = adapter._sessions[identity.session_id].pages[current.page_id]
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=current.page_id,
                kind=BrowserActionKind.CLOSE_TAB,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                current,
                adapter._sessions[identity.session_id].permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("last live", effect.error or "")
            self.assertEqual(page.close_calls, 0)
        finally:
            adapter.close()

        user, _context, user_identity, first, _second = self._user()
        try:
            current = user.observe(user_identity.session_id)
            action = BrowserAction.create(
                session_id=user_identity.session_id,
                page_id=current.page_id,
                kind=BrowserActionKind.CLOSE_TAB,
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                current,
                user._sessions[user_identity.session_id].permission,
            )
            effect = user.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(first.close_calls, 0)
        finally:
            user.close_session(user_identity.session_id)

    def test_close_stale_page_does_not_close_unrelated(self):
        adapter, context, identity = self._managed()
        try:
            opened = self._open(adapter, identity, self.ORIGIN + "/two")
            second_id = opened.page_id
            second = adapter._sessions[identity.session_id].pages[second_id]
            unrelated = _Page(context, url=self.ORIGIN + "/three")
            context.pages.append(unrelated)
            adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=second_id,
                kind=BrowserActionKind.CLOSE_TAB,
            )
            _observed, authority = self._authority(adapter, identity, action, page_id=second_id)
            second.close()
            adapter.observe(identity.session_id)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(unrelated.close_calls, 0)
        finally:
            adapter.close()

    def test_back_success_none_failure_and_expected_current_noop_refusal(self):
        adapter, _context, identity = self._managed()
        try:
            session = adapter._sessions[identity.session_id]
            page_id = adapter.observe(identity.session_id).page_id
            page = session.pages[page_id]
            page.set_history(self.ORIGIN + "/one", self.ORIGIN + "/two")
            current = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.BACK,
                expected={"url_equals": self.ORIGIN + "/one"},
            )
            authority = BrowserActionAuthority.from_observation(action, current, session.permission)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(effect.data["provider_transition_reported"])
            self.assertEqual(effect.url_after, self.ORIGIN + "/one")
            self.assertIn((identity.session_id, page_id), adapter.scene_invalidations)

            page.set_history(self.ORIGIN + "/two")
            current = adapter.observe(identity.session_id)
            none_action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.BACK,
                expected={"url_equals": self.ORIGIN + "/one"},
            )
            none_authority = BrowserActionAuthority.from_observation(
                none_action, current, session.permission
            )
            failed = adapter.act(none_action, none_authority)
            self.assertFalse(failed.success)
            self.assertFalse(failed.data["provider_transition_reported"])

            page.set_history(self.ORIGIN + "/one", self.ORIGIN + "/two")
            current = adapter.observe(identity.session_id)
            noop = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.BACK,
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            noop_authority = BrowserActionAuthority.from_observation(noop, current, session.permission)
            before = page.go_back_calls
            refused = adapter.act(noop, noop_authority)
            self.assertFalse(refused.success)
            self.assertIn("refusing no-op", refused.error or "")
            self.assertEqual(page.go_back_calls, before)
        finally:
            adapter.close()

    def test_forward_success_and_no_history_failure(self):
        adapter, _context, identity = self._managed()
        try:
            session = adapter._sessions[identity.session_id]
            page_id = adapter.observe(identity.session_id).page_id
            page = session.pages[page_id]
            page.set_history(self.ORIGIN + "/one", self.ORIGIN + "/two")
            page.history_index = 0
            page.url = self.ORIGIN + "/one"
            current = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.FORWARD,
                expected={"url_equals": self.ORIGIN + "/two"},
            )
            authority = BrowserActionAuthority.from_observation(action, current, session.permission)
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            current = adapter.observe(identity.session_id)
            no_more = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.FORWARD,
                expected={"url_equals": self.ORIGIN + "/three"},
            )
            authority = BrowserActionAuthority.from_observation(no_more, current, session.permission)
            failed = adapter.act(no_more, authority)
            self.assertFalse(failed.success)
            self.assertFalse(failed.data["provider_transition_reported"])
        finally:
            adapter.close()

    def test_history_wrong_url_postcondition_fails_after_transition(self):
        adapter, _context, identity = self._managed()
        try:
            session = adapter._sessions[identity.session_id]
            page_id = adapter.observe(identity.session_id).page_id
            page = session.pages[page_id]
            page.set_history(self.ORIGIN + "/one", self.ORIGIN + "/two")
            current = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.BACK,
                expected={"url_equals": self.ORIGIN + "/different"},
            )
            authority = BrowserActionAuthority.from_observation(action, current, session.permission)
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(effect.url_after, self.ORIGIN + "/one")
            self.assertTrue(effect.data["provider_transition_reported"])
        finally:
            adapter.close()

    def test_reload_requires_expected_and_does_not_claim_business_state(self):
        adapter, _context, identity = self._managed()
        try:
            session = adapter._sessions[identity.session_id]
            page_id = adapter.observe(identity.session_id).page_id
            page = session.pages[page_id]
            page.set_history(self.ORIGIN + "/one")
            current = adapter.observe(identity.session_id)
            missing = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.RELOAD,
            )
            authority = BrowserActionAuthority.from_observation(missing, current, session.permission)
            failed = adapter.act(missing, authority)
            self.assertFalse(failed.success)
            self.assertEqual(page.reload_calls, 0)

            current = adapter.observe(identity.session_id)
            reload_action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=page_id,
                kind=BrowserActionKind.RELOAD,
                expected={"url_equals": self.ORIGIN + "/one"},
            )
            authority = BrowserActionAuthority.from_observation(
                reload_action, current, session.permission
            )
            effect = adapter.act(reload_action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(page.reload_calls, 1)
            self.assertFalse(effect.data["business_state_verified"])
            self.assertEqual(effect.url_after, self.ORIGIN + "/one")
            self.assertIn((identity.session_id, page_id), adapter.scene_invalidations)
        finally:
            adapter.close()

    def test_tab_history_actions_reject_provider_specific_keys(self):
        adapter, _context, identity = self._managed()
        try:
            current = adapter.observe(identity.session_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=current.page_id,
                kind=BrowserActionKind.RELOAD,
                args={"wait_until": "networkidle"},
                expected={"url_equals": self.ORIGIN + "/one"},
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                current,
                adapter._sessions[identity.session_id].permission,
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("declared schema", effect.error or "")
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

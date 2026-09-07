from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import ManagedBrowserError
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser


ORIGIN = "https://example.test"


class _Element:
    def __init__(self, *, tag="button", input_type="", value="", checked=None, sensitive=False):
        self.tag = tag
        self.input_type = input_type
        self.value = value
        self.checked = checked
        self.sensitive = sensitive or input_type == "password"
        self.disabled = False
        self.read_only = False
        self.connected = True
        self.focused = False
        self.disposed = False
        self.no_effect = False
        self.on_mutation = None
        self.click_calls = 0
        self.fill_calls = 0
        self.check_calls = 0
        self.uncheck_calls = 0

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return self is arg
        if "ownerDocument.activeElement === element" in expression:
            return self.connected and self.focused
        if "const supported = tag === 'input'" in expression and "checked:" in expression:
            supported = self.tag == "input" and self.input_type in {"checkbox", "radio"}
            return {
                "connected": self.connected,
                "supported": supported,
                "type": self.input_type,
                "disabled": self.disabled,
                "checked": self.checked if supported else None,
            }
        if "const sensitive" in expression and "value:" in expression:
            supported = self.tag == "textarea" or (
                self.tag == "input" and self.input_type in {"", "text", "search"}
            )
            return {
                "connected": self.connected,
                "supported": supported,
                "sensitive": self.sensitive,
                "disabled": self.disabled,
                "read_only": self.read_only,
                "value": self.value if supported else "",
            }
        if expression.strip().startswith("element => String(element.tagName"):
            return self.tag
        return {
            "connected": self.connected,
            "tag": self.tag,
            "input_type": self.input_type,
            "sensitive": self.sensitive,
            "disabled": self.disabled,
            "read_only": self.read_only,
            "checked": self.checked,
            "selected": None,
            "value_length": len(self.value),
            "href": "",
        }

    def _mutated(self):
        if self.on_mutation is not None:
            self.on_mutation()

    def focus(self):
        if not self.no_effect:
            self.focused = True
        self._mutated()

    def fill(self, value):
        self.fill_calls += 1
        if not self.no_effect:
            self.value = str(value)
        self._mutated()

    def check(self):
        self.check_calls += 1
        if not self.no_effect:
            self.checked = True
        self._mutated()

    def uncheck(self):
        self.uncheck_calls += 1
        if not self.no_effect:
            self.checked = False
        self._mutated()

    def click(self):
        self.click_calls += 1
        self._mutated()

    def dispose(self):
        self.disposed = True


class _ItemLocator:
    def __init__(self, *, role, name, element, editable=False):
        self.role = role
        self.name = name
        self.element = element
        self.editable = editable

    def is_visible(self):
        return self.element.connected

    def is_enabled(self):
        return not self.element.disabled

    def is_editable(self):
        return self.editable and not self.element.read_only

    def element_handle(self):
        return self.element

    def aria_snapshot(self, **kwargs):
        escaped = self.name.replace("\\", "\\\\").replace('"', '\\"')
        return f'- {self.role} "{escaped}"'


class _RoleLocator:
    def __init__(self, items=None):
        self.items = list(items or [])

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _Frame:
    def __init__(self, *, url, parent_frame=None, roles=None, name=""):
        self.url = url
        self.parent_frame = parent_frame
        self.roles = dict(roles or {})
        self.name = name

    def get_by_role(self, role):
        return _RoleLocator(self.roles.get(role, ()))


class _Page:
    def __init__(self, *, url, main_frame, frames=None, title="Page", visible=True):
        self.url = url
        self.main_frame = main_frame
        self.frames = list(frames or [main_frame])
        self._title = title
        self.viewport_size = {"width": 1200, "height": 800}
        self.visible = visible
        self.closed = False
        self.context = None
        self.wait_accept_any = False
        self.wait_calls = []
        self.close_calls = 0

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.readyState !== undefined":
            return True
        if expression == "document.visibilityState":
            return "visible" if self.visible else "hidden"
        if expression == "document.visibilityState === 'visible'":
            return self.visible
        raise AssertionError(expression)

    def wait_for_url(self, url, *, wait_until, timeout):
        self.wait_calls.append((url, wait_until, timeout))
        if not self.wait_accept_any and self.url != url:
            raise RuntimeError(f"URL did not reach {url}")

    def is_closed(self):
        return self.closed

    def close(self):
        self.close_calls += 1
        self.closed = True


class _Context:
    def __init__(self, pages, *, user=False):
        self.pages = list(pages)
        self.user = user
        self.close_calls = 0
        for page in self.pages:
            page.context = self

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def set_default_timeout(self, value):
        self.action_timeout = value

    def route(self, pattern, handler):
        self.route_handler = handler

    def route_web_socket(self, pattern, handler):
        self.websocket_handler = handler

    def new_page(self):
        if self.user:
            raise AssertionError("USER plane must not create a page")
        if self.pages:
            return self.pages[0]
        raise AssertionError("fixture requires a page")

    def close(self):
        self.close_calls += 1


class _Browser:
    version = "fake"

    def __init__(self, context):
        self.context = context
        self.contexts = [context]
        self.close_calls = 0

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        self.close_calls += 1


class _Chromium:
    def __init__(self, browser):
        self.browser = browser
        self.endpoints = []

    def launch(self, *, headless):
        return self.browser

    def connect_over_cdp(self, endpoint):
        self.endpoints.append(endpoint)
        return self.browser


class _Playwright:
    def __init__(self, browser):
        self.chromium = _Chromium(browser)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _permission(*, navigation=True, text=True, sensitive=False):
    return BrowserPermissionContext(
        allow_navigation=navigation,
        allow_page_interaction=True,
        allow_text_entry=text,
        allow_sensitive_fields=sensitive,
        allowed_origins=(ORIGIN,),
    )


def _managed(page, *, permission=None):
    context = _Context([page])
    provider = _Browser(context)
    playwright = _Playwright(provider)
    adapter = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    identity = adapter.open_session(permission=permission or _permission(), headless=True)
    return adapter, identity, context, provider


def _user(page, *, permission=None):
    context = _Context([page], user=True)
    provider = _Browser(context)
    playwright = _Playwright(provider)
    adapter = AuthorizedCDPUserBrowser(
        endpoint="http://127.0.0.1:9222",
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    identity = adapter.open_session(permission=permission or _permission())
    return adapter, identity, context, provider


def _scene_target(browser, session_id, *, role=None, name=None):
    scene = browser.observe_scene(session_id)
    return scene, next(
        target
        for target in scene.targets
        if (role is None or target.role == role)
        and (name is None or target.accessible_name == name)
    )


def _authorized(browser, identity, target, kind, *, args=None, expected=None):
    observed = browser.observe_scene_target(identity.session_id, target.target_id, page_id=target.page_id)
    action = BrowserAction.create(
        session_id=identity.session_id,
        page_id=observed.page_id,
        kind=kind,
        target=observed.target,
        args=args,
        expected=expected,
    )
    authority = BrowserActionAuthority.from_observation(
        action,
        observed,
        browser._sessions[identity.session_id].permission,
    )
    return observed, action, authority


class BrowserSceneActionTests(unittest.TestCase):
    def test_observe_scene_target_keeps_scene_alive_and_authority_action_succeeds(self):
        element = _Element(tag="button")
        item = _ItemLocator(role="button", name="Focus me", element=element)
        frame = _Frame(url=ORIGIN + "/form", roles={"button": [item]})
        browser, identity, _context, _provider = _managed(_Page(url=frame.url, main_frame=frame))
        try:
            scene, target = _scene_target(browser, identity.session_id)
            state = browser._scene_state(browser._sessions[identity.session_id])
            self.assertIn(scene.page_id, state.page_scenes)
            observed, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            self.assertIn(scene.page_id, state.page_scenes)
            self.assertEqual(observed.target.target_id, target.target_id)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(element.focused)
            self.assertNotIn(scene.page_id, state.page_scenes)
        finally:
            browser.close()

    def test_same_name_replacement_and_detached_frame_fail_without_re_grounding(self):
        main = _Frame(url=ORIGIN + "/form")
        original = _Element(tag="button")
        item = _ItemLocator(role="button", name="Same", element=original)
        child = _Frame(url=ORIGIN + "/frame", parent_frame=main, roles={"button": [item]})
        page = _Page(url=main.url, main_frame=main, frames=[main, child])
        browser, identity, _context, _provider = _managed(page)
        try:
            _scene, target = _scene_target(browser, identity.session_id, name="Same")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            replacement = _Element(tag="button")
            item.element = replacement
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertFalse(replacement.focused)

            browser.observe_scene(identity.session_id)
            target = next(t for t in browser.observe_scene(identity.session_id).targets if t.accessible_name == "Same")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            page.frames.remove(child)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("detached", (effect.error or "").lower())
        finally:
            browser.close()

    def test_cross_origin_frame_remains_unobservable(self):
        main = _Frame(url=ORIGIN + "/form")
        child = _Frame(
            url="https://other.test/frame",
            parent_frame=main,
            roles={"button": [_ItemLocator(role="button", name="Nope", element=_Element())]},
        )
        page = _Page(url=main.url, main_frame=main, frames=[main, child])
        browser, identity, _context, _provider = _managed(page)
        try:
            scene = browser.observe_scene(identity.session_id)
            self.assertFalse(any(t.accessible_name == "Nope" for t in scene.targets))
            blocked = next(frame for frame in scene.frames if not frame.is_main)
            self.assertFalse(blocked.observable)
        finally:
            browser.close()

    def test_same_origin_child_frame_focus_success_and_scene_invalidated(self):
        main = _Frame(url=ORIGIN + "/form")
        element = _Element(tag="button")
        child = _Frame(
            url=ORIGIN + "/frame",
            parent_frame=main,
            roles={"button": [_ItemLocator(role="button", name="Frame focus", element=element)]},
        )
        page = _Page(url=main.url, main_frame=main, frames=[main, child])
        browser, identity, _context, _provider = _managed(page)
        try:
            scene, target = _scene_target(browser, identity.session_id, name="Frame focus")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["frame_id"], target.frame_id)
            with self.assertRaisesRegex(ManagedBrowserError, "fresh BrowserScene|stale"):
                browser.validate_scene_target(identity.session_id, target.target_id, page_id=scene.page_id)
        finally:
            browser.close()

    def test_focus_requires_exact_empty_schema_and_real_postcondition(self):
        element = _Element(tag="button")
        element.no_effect = True
        frame = _Frame(url=ORIGIN + "/form", roles={"button": [_ItemLocator(role="button", name="Focus", element=element)]})
        browser, identity, _context, _provider = _managed(_Page(url=frame.url, main_frame=frame))
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            bad = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS,
                target=observed.target,
                args={"force": True},
            )
            authority = BrowserActionAuthority.from_observation(bad, observed, browser._sessions[identity.session_id].permission)
            self.assertFalse(browser.act(bad, authority).success)

            browser.observe_scene(identity.session_id)
            target = browser.observe_scene(identity.session_id).targets[0]
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
        finally:
            browser.close()

    def test_type_text_hash_length_success_plaintext_absent_and_old_scene_stale(self):
        text = "private query 42"
        element = _Element(tag="input", input_type="search")
        main = _Frame(
            url=ORIGIN + "/form",
            roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", element=element, editable=True)]},
        )
        browser, identity, _context, _provider = _managed(_Page(url=main.url, main_frame=main))
        try:
            scene, target = _scene_target(browser, identity.session_id, role="searchbox")
            _obs, action, authority = _authorized(
                browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": text}
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(element.value, text)
            self.assertEqual(effect.data["text_length_after"], len(text))
            self.assertEqual(effect.data["expected_text_sha256"], effect.data["text_sha256_after"])
            self.assertNotIn(text, repr(effect.data))
            self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
        finally:
            browser.close()

    def test_type_text_refuses_nonempty_sensitive_and_missing_permission(self):
        cases = [
            (_Element(tag="input", input_type="search", value="existing"), _permission(), "non-empty"),
            (_Element(tag="input", input_type="password", sensitive=True), _permission(sensitive=True), "sensitive"),
        ]
        for element, permission, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                main = _Frame(
                    url=ORIGIN + "/form",
                    roles={"textbox": [_ItemLocator(role="textbox", name="Field", element=element, editable=True)]},
                )
                browser, identity, _context, _provider = _managed(_Page(url=main.url, main_frame=main), permission=permission)
                try:
                    _scene, target = _scene_target(browser, identity.session_id)
                    _obs, action, authority = _authorized(
                        browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "new"}
                    )
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(expected_error, (effect.error or "").lower())
                finally:
                    browser.close()

        element = _Element(tag="input", input_type="search")
        main = _Frame(url=ORIGIN + "/form", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", element=element, editable=True)]})
        browser, identity, _context, _provider = _managed(_Page(url=main.url, main_frame=main), permission=_permission(text=False))
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.TYPE_TEXT,
                target=observed.target,
                args={"text": "denied"},
            )
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, browser._sessions[identity.session_id].permission)
            self.assertEqual(element.fill_calls, 0)
        finally:
            browser.close()

    def test_type_text_url_change_and_node_replacement_fail_closed(self):
        for mode in ("url", "replacement"):
            with self.subTest(mode=mode):
                element = _Element(tag="input", input_type="search")
                item = _ItemLocator(role="searchbox", name="Search", element=element, editable=True)
                main = _Frame(url=ORIGIN + "/form", roles={"searchbox": [item]})
                page = _Page(url=main.url, main_frame=main)
                browser, identity, _context, _provider = _managed(page)
                try:
                    _scene, target = _scene_target(browser, identity.session_id)
                    _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "abc"})
                    if mode == "url":
                        element.on_mutation = lambda: setattr(page, "url", ORIGIN + "/changed")
                    else:
                        element.on_mutation = lambda: setattr(item, "element", _Element(tag="input", input_type="search"))
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertNotIn(target.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
                finally:
                    browser.close()

    def test_checkbox_check_uncheck_radio_and_postcondition_rules(self):
        checkbox = _Element(tag="input", input_type="checkbox", checked=False)
        radio = _Element(tag="input", input_type="radio", checked=False)
        main = _Frame(
            url=ORIGIN + "/form",
            roles={
                "checkbox": [_ItemLocator(role="checkbox", name="Agree", element=checkbox)],
                "radio": [_ItemLocator(role="radio", name="Choice", element=radio)],
            },
        )
        browser, identity, _context, _provider = _managed(_Page(url=main.url, main_frame=main))
        try:
            _scene, target = _scene_target(browser, identity.session_id, role="checkbox")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.CHECK)
            self.assertTrue(browser.act(action, authority).success)
            browser.observe_scene(identity.session_id)
            target = next(t for t in browser.observe_scene(identity.session_id).targets if t.role == "checkbox")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.UNCHECK)
            self.assertTrue(browser.act(action, authority).success)

            browser.observe_scene(identity.session_id)
            target = next(t for t in browser.observe_scene(identity.session_id).targets if t.role == "checkbox")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.UNCHECK)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("already observed", effect.error or "")

            browser.observe_scene(identity.session_id)
            target = next(t for t in browser.observe_scene(identity.session_id).targets if t.role == "radio")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.CHECK)
            self.assertTrue(browser.act(action, authority).success)
            browser.observe_scene(identity.session_id)
            target = next(t for t in browser.observe_scene(identity.session_id).targets if t.role == "radio")
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.UNCHECK)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("radio", effect.error or "")
        finally:
            browser.close()

    def test_checked_state_not_observed_is_failure(self):
        element = _Element(tag="input", input_type="checkbox", checked=False)
        element.no_effect = True
        main = _Frame(url=ORIGIN + "/form", roles={"checkbox": [_ItemLocator(role="checkbox", name="Agree", element=element)]})
        browser, identity, _context, _provider = _managed(_Page(url=main.url, main_frame=main))
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.CHECK)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
        finally:
            browser.close()

    def test_navigation_link_and_button_success_require_expected_authority_and_invalidate(self):
        for role, tag in (("link", "a"), ("button", "button")):
            with self.subTest(role=role):
                main = _Frame(url=ORIGIN + "/start")
                page = _Page(url=main.url, main_frame=main)
                element = _Element(tag=tag)
                element.on_mutation = lambda p=page: setattr(p, "url", ORIGIN + "/done")
                main.roles[role] = [_ItemLocator(role=role, name="Go", element=element)]
                browser, identity, _context, _provider = _managed(page)
                try:
                    scene, target = _scene_target(browser, identity.session_id, role=role)
                    _obs, action, authority = _authorized(
                        browser,
                        identity,
                        target,
                        BrowserActionKind.CLICK,
                        expected={"url_equals": ORIGIN + "/done"},
                    )
                    effect = browser.act(action, authority)
                    self.assertTrue(effect.success, effect.error)
                    self.assertEqual(effect.url_after, ORIGIN + "/done")
                    self.assertEqual(len(page.wait_calls), 1)
                    self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
                    replay = browser.act(action, authority)
                    self.assertFalse(replay.success)
                finally:
                    browser.close()

    def test_navigation_click_rejections_do_not_dispatch(self):
        scenarios = (
            (False, {"url_equals": ORIGIN + "/done"}, "navigation permission"),
            (True, {}, "declared schema"),
            (True, {"url_equals": ORIGIN + "/start"}, "already observed"),
            (True, {"url_equals": "https://other.test/done"}, "permitted"),
        )
        for navigation, expected, message in scenarios:
            with self.subTest(expected=expected, navigation=navigation):
                main = _Frame(url=ORIGIN + "/start")
                page = _Page(url=main.url, main_frame=main)
                element = _Element(tag="a")
                main.roles["link"] = [_ItemLocator(role="link", name="Go", element=element)]
                browser, identity, _context, _provider = _managed(page, permission=_permission(navigation=navigation))
                try:
                    _scene, target = _scene_target(browser, identity.session_id)
                    _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.CLICK, expected=expected)
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(message, (effect.error or "").lower())
                    self.assertEqual(element.click_calls, 0)
                finally:
                    browser.close()

    def test_navigation_wrong_observed_url_is_failure(self):
        main = _Frame(url=ORIGIN + "/start")
        page = _Page(url=main.url, main_frame=main)
        page.wait_accept_any = True
        element = _Element(tag="a")
        element.on_mutation = lambda: setattr(page, "url", ORIGIN + "/wrong")
        main.roles["link"] = [_ItemLocator(role="link", name="Go", element=element)]
        browser, identity, _context, _provider = _managed(page)
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.CLICK, expected={"url_equals": ORIGIN + "/done"})
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
        finally:
            browser.close()

    def test_unexpected_fresh_page_fails_and_is_not_closed_or_claimed(self):
        main = _Frame(url=ORIGIN + "/form")
        page = _Page(url=main.url, main_frame=main)
        element = _Element(tag="button")
        main.roles["button"] = [_ItemLocator(role="button", name="Popup", element=element)]
        browser, identity, context, _provider = _managed(page)
        popup = _Page(url=ORIGIN + "/popup", main_frame=_Frame(url=ORIGIN + "/popup"), visible=False)
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            _obs, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            def add_popup():
                popup.context = context
                context.pages.append(popup)
            element.on_mutation = add_popup
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("unexpected fresh page observed", effect.error or "")
            self.assertIn(popup, context.pages)
            self.assertEqual(popup.close_calls, 0)
        finally:
            browser.close()

    def test_user_plane_allowed_existing_tab_preserves_metadata_and_permission_denial(self):
        element = _Element(tag="input", input_type="search")
        main = _Frame(url=ORIGIN + "/account", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", element=element, editable=True)]})
        page = _Page(url=main.url, main_frame=main, visible=True)
        browser, identity, context, provider = _user(page)
        try:
            scene, target = _scene_target(browser, identity.session_id)
            observed, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "existing tab"})
            self.assertEqual(observed.metadata["attachment"], "authorized_existing_session")
            self.assertEqual(observed.metadata["service_workers"], "user_owned_unmodified")
            self.assertEqual(observed.metadata["profile_scope"], "user_existing")
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(element.value, "existing tab")
            self.assertEqual(len(context.pages), 1)
            self.assertEqual(provider.close_calls, 0)
            self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
        finally:
            browser.close_session(identity.session_id)

        denied_element = _Element(tag="input", input_type="search")
        denied_main = _Frame(url=ORIGIN + "/account", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", element=denied_element, editable=True)]})
        denied_page = _Page(url=denied_main.url, main_frame=denied_main, visible=True)
        browser, identity, _context, _provider = _user(denied_page, permission=_permission(text=False))
        try:
            _scene, target = _scene_target(browser, identity.session_id)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.TYPE_TEXT,
                target=observed.target,
                args={"text": "denied"},
            )
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, browser._sessions[identity.session_id].permission)
            self.assertEqual(denied_element.fill_calls, 0)
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

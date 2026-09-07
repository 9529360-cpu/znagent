from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserPermissionContext
from zn_agent.core.managed_browser import ManagedBrowserError
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser

ORIGIN = "https://example.test"


class _Node:
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
        self.no_effect = False
        self.on_mutation = None
        self.click_calls = 0
        self.fill_calls = 0


class _Handle:
    """Disposable handle around a persistent fake DOM node."""

    def __init__(self, node):
        self.node = node
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed handle")
        node = self.node
        other = arg.node if isinstance(arg, _Handle) else None
        if "element === other" in expression:
            return node is other
        if "ownerDocument.activeElement === element" in expression:
            return node.connected and node.focused
        if "const supported = tag === 'input'" in expression and "checked:" in expression:
            supported = node.tag == "input" and node.input_type in {"checkbox", "radio"}
            return {"connected": node.connected, "supported": supported, "type": node.input_type,
                    "disabled": node.disabled, "checked": node.checked if supported else None}
        if "const sensitive" in expression and "value:" in expression:
            supported = node.tag == "textarea" or (node.tag == "input" and node.input_type in {"", "text", "search"})
            return {"connected": node.connected, "supported": supported, "sensitive": node.sensitive,
                    "disabled": node.disabled, "read_only": node.read_only,
                    "value": node.value if supported else ""}
        if expression.strip().startswith("element => String(element.tagName"):
            return node.tag
        return {"connected": node.connected, "tag": node.tag, "input_type": node.input_type,
                "sensitive": node.sensitive, "disabled": node.disabled, "read_only": node.read_only,
                "checked": node.checked, "selected": None, "value_length": len(node.value), "href": ""}

    def _mutated(self):
        if self.node.on_mutation is not None:
            self.node.on_mutation()

    def focus(self):
        if not self.node.no_effect:
            self.node.focused = True
        self._mutated()

    def fill(self, value):
        self.node.fill_calls += 1
        if not self.node.no_effect:
            self.node.value = str(value)
        self._mutated()

    def check(self):
        if not self.node.no_effect:
            self.node.checked = True
        self._mutated()

    def uncheck(self):
        if not self.node.no_effect:
            self.node.checked = False
        self._mutated()

    def click(self):
        self.node.click_calls += 1
        self._mutated()

    def dispose(self):
        self.disposed = True


class _ItemLocator:
    def __init__(self, *, role, name, node, editable=False):
        self.role, self.name, self.node, self.editable = role, name, node, editable

    def is_visible(self):
        return self.node.connected

    def is_enabled(self):
        return not self.node.disabled

    def is_editable(self):
        return self.editable and not self.node.read_only

    def element_handle(self):
        return _Handle(self.node)

    def aria_snapshot(self, **kwargs):
        return f'- {self.role} "{self.name}"'


class _RoleLocator:
    def __init__(self, items=None):
        self.items = list(items or [])

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _Frame:
    def __init__(self, *, url, parent_frame=None, roles=None, name=""):
        self.url, self.parent_frame, self.roles, self.name = url, parent_frame, dict(roles or {}), name

    def get_by_role(self, role):
        return _RoleLocator(self.roles.get(role, ()))


class _Page:
    def __init__(self, *, url, main_frame, frames=None, visible=True):
        self.url, self.main_frame = url, main_frame
        self.frames = list(frames or [main_frame])
        self.viewport_size = {"width": 1200, "height": 800}
        self.visible, self.closed = visible, False
        self.context = None
        self.wait_accept_any = False
        self.wait_calls, self.close_calls = [], 0

    def title(self):
        return "Page"

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
        self.pages, self.user, self.close_calls = list(pages), user, 0
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
        return self.pages[0]

    def close(self):
        self.close_calls += 1


class _ProviderBrowser:
    version = "fake"

    def __init__(self, context):
        self.contexts, self.context, self.close_calls = [context], context, 0

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        self.close_calls += 1


class _Chromium:
    def __init__(self, browser):
        self.browser, self.endpoints = browser, []

    def launch(self, *, headless):
        return self.browser

    def connect_over_cdp(self, endpoint):
        self.endpoints.append(endpoint)
        return self.browser


class _Playwright:
    def __init__(self, browser):
        self.chromium, self.stop_calls = _Chromium(browser), 0

    def stop(self):
        self.stop_calls += 1


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _permission(*, navigation=True, text=True, sensitive=False):
    return BrowserPermissionContext(allow_navigation=navigation, allow_page_interaction=True,
        allow_text_entry=text, allow_sensitive_fields=sensitive, allowed_origins=(ORIGIN,))


def _build(page, *, permission=None, user=False):
    context = _Context([page], user=user)
    provider = _ProviderBrowser(context)
    playwright = _Playwright(provider)
    if user:
        adapter = AuthorizedCDPUserBrowser(endpoint="http://127.0.0.1:9222",
            playwright_factory=lambda: _Starter(playwright), url_checker=lambda url, **kwargs: True)
        identity = adapter.open_session(permission=permission or _permission())
    else:
        adapter = SemanticPlaywrightManagedBrowser(playwright_factory=lambda: _Starter(playwright),
            url_checker=lambda url, **kwargs: True)
        identity = adapter.open_session(permission=permission or _permission(), headless=True)
    return adapter, identity, context, provider


def _target(browser, identity, *, role=None, name=None):
    scene = browser.observe_scene(identity.session_id)
    return scene, next(t for t in scene.targets if (role is None or t.role == role) and (name is None or t.accessible_name == name))


def _authorized(browser, identity, target, kind, *, args=None, expected=None):
    observed = browser.observe_scene_target(identity.session_id, target.target_id, page_id=target.page_id)
    action = BrowserAction.create(session_id=identity.session_id, page_id=observed.page_id,
        kind=kind, target=observed.target, args=args, expected=expected)
    authority = BrowserActionAuthority.from_observation(action, observed,
        browser._sessions[identity.session_id].permission)
    return observed, action, authority


class BrowserSceneActionTests(unittest.TestCase):
    def test_observe_scene_target_keeps_binding_authority_ready_and_focus_invalidates(self):
        node = _Node(tag="button")
        main = _Frame(url=ORIGIN + "/form", roles={"button": [_ItemLocator(role="button", name="Focus", node=node)]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main))
        try:
            scene, target = _target(browser, identity)
            state = browser._scene_state(browser._sessions[identity.session_id])
            observed, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            self.assertIn(scene.page_id, state.page_scenes)
            self.assertEqual(observed.target.target_id, target.target_id)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(node.focused)
            self.assertNotIn(scene.page_id, state.page_scenes)
        finally:
            browser.close()

    def test_exact_replacement_detached_and_cross_origin_fail_closed(self):
        original = _Node(tag="button")
        item = _ItemLocator(role="button", name="Same", node=original)
        main = _Frame(url=ORIGIN + "/form", roles={"button": [item]})
        page = _Page(url=main.url, main_frame=main)
        browser, identity, _c, _p = _build(page)
        try:
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            replacement = _Node(tag="button")
            item.node = replacement
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertFalse(replacement.focused)
        finally:
            browser.close()

        main = _Frame(url=ORIGIN + "/form")
        child = _Frame(url=ORIGIN + "/frame", parent_frame=main,
            roles={"button": [_ItemLocator(role="button", name="Frame", node=_Node())]})
        page = _Page(url=main.url, main_frame=main, frames=[main, child])
        browser, identity, _c, _p = _build(page)
        try:
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            page.frames.remove(child)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("detached", (effect.error or "").lower())
        finally:
            browser.close()

        main = _Frame(url=ORIGIN + "/form")
        foreign = _Frame(url="https://other.test/frame", parent_frame=main,
            roles={"button": [_ItemLocator(role="button", name="Foreign", node=_Node())]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main, frames=[main, foreign]))
        try:
            scene = browser.observe_scene(identity.session_id)
            self.assertFalse(any(t.accessible_name == "Foreign" for t in scene.targets))
            self.assertFalse(next(f for f in scene.frames if not f.is_main).observable)
        finally:
            browser.close()

    def test_same_origin_iframe_focus_success(self):
        main = _Frame(url=ORIGIN + "/form")
        node = _Node(tag="button")
        child = _Frame(url=ORIGIN + "/frame", parent_frame=main,
            roles={"button": [_ItemLocator(role="button", name="Frame focus", node=node)]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main, frames=[main, child]))
        try:
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["frame_id"], target.frame_id)
        finally:
            browser.close()

    def test_focus_schema_and_postcondition_are_strict(self):
        node = _Node(tag="button")
        node.no_effect = True
        main = _Frame(url=ORIGIN + "/form", roles={"button": [_ItemLocator(role="button", name="Focus", node=node)]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main))
        try:
            _scene, target = _target(browser, identity)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            bad = BrowserAction.create(session_id=identity.session_id, page_id=observed.page_id,
                kind=BrowserActionKind.FOCUS, target=observed.target, args={"force": True})
            authority = BrowserActionAuthority.from_observation(bad, observed, browser._sessions[identity.session_id].permission)
            self.assertFalse(browser.act(bad, authority).success)
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
        finally:
            browser.close()

    def test_type_text_hash_privacy_refusals_and_stale_after_mutation(self):
        text = "private query 42"
        node = _Node(tag="input", input_type="search")
        main = _Frame(url=ORIGIN + "/form", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", node=node, editable=True)]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main))
        try:
            scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": text})
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(node.value, text)
            self.assertEqual(effect.data["text_length_after"], len(text))
            self.assertEqual(effect.data["text_sha256_after"], effect.data["expected_text_sha256"])
            self.assertNotIn(text, repr(effect.data))
            self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
        finally:
            browser.close()

        for node, permission, error in (
            (_Node(tag="input", input_type="search", value="old"), _permission(), "non-empty"),
            (_Node(tag="input", input_type="password", sensitive=True), _permission(sensitive=True), "non-sensitive"),
        ):
            main = _Frame(url=ORIGIN + "/form", roles={"textbox": [_ItemLocator(role="textbox", name="Field", node=node, editable=True)]})
            browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main), permission=permission)
            try:
                _scene, target = _target(browser, identity)
                _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "new"})
                effect = browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertIn(error, (effect.error or "").lower())
            finally:
                browser.close()

    def test_type_text_permission_url_change_and_replacement_fail_closed(self):
        node = _Node(tag="input", input_type="search")
        item = _ItemLocator(role="searchbox", name="Search", node=node, editable=True)
        main = _Frame(url=ORIGIN + "/form", roles={"searchbox": [item]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main), permission=_permission(text=False))
        try:
            _scene, target = _target(browser, identity)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            action = BrowserAction.create(session_id=identity.session_id, page_id=observed.page_id,
                kind=BrowserActionKind.TYPE_TEXT, target=observed.target, args={"text": "denied"})
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, browser._sessions[identity.session_id].permission)
            self.assertEqual(node.fill_calls, 0)
        finally:
            browser.close()

        for mode in ("url", "replacement"):
            node = _Node(tag="input", input_type="search")
            item = _ItemLocator(role="searchbox", name="Search", node=node, editable=True)
            main = _Frame(url=ORIGIN + "/form", roles={"searchbox": [item]})
            page = _Page(url=main.url, main_frame=main)
            browser, identity, _c, _p = _build(page)
            try:
                scene, target = _target(browser, identity)
                _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "abc"})
                node.on_mutation = (lambda: setattr(page, "url", ORIGIN + "/changed")) if mode == "url" else (lambda: setattr(item, "node", _Node(tag="input", input_type="search")))
                effect = browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
            finally:
                browser.close()

    def test_check_uncheck_radio_and_postcondition_rules(self):
        def run(node, role, kind):
            main = _Frame(url=ORIGIN + "/form", roles={role: [_ItemLocator(role=role, name="Control", node=node)]})
            browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main))
            try:
                _scene, target = _target(browser, identity)
                _o, action, authority = _authorized(browser, identity, target, kind)
                return browser.act(action, authority)
            finally:
                browser.close()
        self.assertTrue(run(_Node(tag="input", input_type="checkbox", checked=False), "checkbox", BrowserActionKind.CHECK).success)
        self.assertTrue(run(_Node(tag="input", input_type="checkbox", checked=True), "checkbox", BrowserActionKind.UNCHECK).success)
        self.assertFalse(run(_Node(tag="input", input_type="checkbox", checked=True), "checkbox", BrowserActionKind.CHECK).success)
        self.assertTrue(run(_Node(tag="input", input_type="radio", checked=False), "radio", BrowserActionKind.CHECK).success)
        radio_uncheck = run(_Node(tag="input", input_type="radio", checked=True), "radio", BrowserActionKind.UNCHECK)
        self.assertFalse(radio_uncheck.success)
        self.assertIn("radio", radio_uncheck.error or "")
        no_effect = _Node(tag="input", input_type="checkbox", checked=False)
        no_effect.no_effect = True
        effect = run(no_effect, "checkbox", BrowserActionKind.CHECK)
        self.assertFalse(effect.success)
        self.assertIn("postcondition", effect.error or "")

    def test_navigation_link_button_authority_url_and_stale_replay(self):
        for role, tag in (("link", "a"), ("button", "button")):
            main = _Frame(url=ORIGIN + "/start")
            page = _Page(url=main.url, main_frame=main)
            node = _Node(tag=tag)
            node.on_mutation = lambda p=page: setattr(p, "url", ORIGIN + "/done")
            main.roles[role] = [_ItemLocator(role=role, name="Go", node=node)]
            browser, identity, _c, _p = _build(page)
            try:
                scene, target = _target(browser, identity)
                _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.CLICK, expected={"url_equals": ORIGIN + "/done"})
                effect = browser.act(action, authority)
                self.assertTrue(effect.success, effect.error)
                self.assertEqual(effect.url_after, ORIGIN + "/done")
                self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
                self.assertFalse(browser.act(action, authority).success)
            finally:
                browser.close()

        for navigation, expected in ((False, {"url_equals": ORIGIN + "/done"}), (True, {}),
                                     (True, {"url_equals": ORIGIN + "/start"}),
                                     (True, {"url_equals": "https://other.test/done"})):
            main = _Frame(url=ORIGIN + "/start")
            page = _Page(url=main.url, main_frame=main)
            node = _Node(tag="a")
            main.roles["link"] = [_ItemLocator(role="link", name="Go", node=node)]
            browser, identity, _c, _p = _build(page, permission=_permission(navigation=navigation))
            try:
                _scene, target = _target(browser, identity)
                _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.CLICK, expected=expected)
                self.assertFalse(browser.act(action, authority).success)
                self.assertEqual(node.click_calls, 0)
            finally:
                browser.close()

    def test_wrong_navigation_and_unexpected_popup_fail_without_claiming_page(self):
        main = _Frame(url=ORIGIN + "/start")
        page = _Page(url=main.url, main_frame=main)
        page.wait_accept_any = True
        node = _Node(tag="a")
        node.on_mutation = lambda: setattr(page, "url", ORIGIN + "/wrong")
        main.roles["link"] = [_ItemLocator(role="link", name="Go", node=node)]
        browser, identity, _c, _p = _build(page)
        try:
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.CLICK, expected={"url_equals": ORIGIN + "/done"})
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition", effect.error or "")
        finally:
            browser.close()

        main = _Frame(url=ORIGIN + "/form")
        page = _Page(url=main.url, main_frame=main)
        node = _Node(tag="button")
        main.roles["button"] = [_ItemLocator(role="button", name="Popup", node=node)]
        browser, identity, context, _p = _build(page)
        popup = _Page(url=ORIGIN + "/popup", main_frame=_Frame(url=ORIGIN + "/popup"), visible=False)
        try:
            _scene, target = _target(browser, identity)
            _o, action, authority = _authorized(browser, identity, target, BrowserActionKind.FOCUS)
            def add_popup():
                popup.context = context
                context.pages.append(popup)
            node.on_mutation = add_popup
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("unexpected fresh page observed", effect.error or "")
            self.assertIn(popup, context.pages)
            self.assertEqual(popup.close_calls, 0)
        finally:
            browser.close()

    def test_user_plane_existing_tab_metadata_and_permission_boundary(self):
        node = _Node(tag="input", input_type="search")
        main = _Frame(url=ORIGIN + "/account", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", node=node, editable=True)]})
        browser, identity, context, provider = _build(_Page(url=main.url, main_frame=main, visible=True), user=True)
        try:
            scene, target = _target(browser, identity)
            observed, action, authority = _authorized(browser, identity, target, BrowserActionKind.TYPE_TEXT, args={"text": "existing tab"})
            self.assertEqual(observed.metadata["attachment"], "authorized_existing_session")
            self.assertEqual(observed.metadata["service_workers"], "user_owned_unmodified")
            self.assertEqual(observed.metadata["profile_scope"], "user_existing")
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(node.value, "existing tab")
            self.assertEqual(len(context.pages), 1)
            self.assertEqual(provider.close_calls, 0)
            self.assertNotIn(scene.page_id, browser._scene_state(browser._sessions[identity.session_id]).page_scenes)
        finally:
            browser.close_session(identity.session_id)

        node = _Node(tag="input", input_type="search")
        main = _Frame(url=ORIGIN + "/account", roles={"searchbox": [_ItemLocator(role="searchbox", name="Search", node=node, editable=True)]})
        browser, identity, _c, _p = _build(_Page(url=main.url, main_frame=main, visible=True), permission=_permission(text=False), user=True)
        try:
            _scene, target = _target(browser, identity)
            observed = browser.observe_scene_target(identity.session_id, target.target_id)
            action = BrowserAction.create(session_id=identity.session_id, page_id=observed.page_id,
                kind=BrowserActionKind.TYPE_TEXT, target=observed.target, args={"text": "denied"})
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, browser._sessions[identity.session_id].permission)
            self.assertEqual(node.fill_calls, 0)
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

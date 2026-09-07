from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _Element:
    def __init__(
        self,
        *,
        tag: str,
        input_type: str = "",
        checked=None,
        value: str = "",
        on_click=None,
    ):
        self.tag = tag
        self.input_type = input_type
        self.checked = checked
        self.value = value
        self.on_click = on_click
        self.focused = False
        self.disposed = False
        self.disabled = False
        self.read_only = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return self is arg
        if "ownerDocument.activeElement === element" in expression:
            return self.focused
        if "supported = tag === \"input\" && (type === \"checkbox\" || type === \"radio\")" in expression:
            return {
                "connected": True,
                "supported": self.tag == "input" and self.input_type in {"checkbox", "radio"},
                "type": self.input_type,
                "disabled": self.disabled,
                "checked": self.checked,
            }
        if "type === \"search\"" in expression and "value:" in expression:
            supported = self.tag == "textarea" or (
                self.tag == "input" and self.input_type in {"", "text", "search"}
            )
            return {
                "connected": True,
                "supported": supported,
                "sensitive": self.tag == "input" and self.input_type == "password",
                "disabled": self.disabled,
                "read_only": self.read_only,
                "value": self.value if supported else "",
            }
        if expression.strip().startswith("element => String(element.tagName"):
            return self.tag
        return {
            "connected": True,
            "tag": self.tag,
            "input_type": self.input_type,
            "sensitive": self.input_type == "password",
            "disabled": self.disabled,
            "read_only": self.read_only,
            "checked": self.checked,
            "selected": None,
            "value_length": len(self.value),
            "href": "",
        }

    def focus(self):
        self.focused = True

    def fill(self, value):
        self.value = str(value)

    def check(self):
        self.checked = True

    def uncheck(self):
        self.checked = False

    def click(self):
        if self.on_click is not None:
            self.on_click()

    def dispose(self):
        self.disposed = True


class _ItemLocator:
    def __init__(self, *, role: str, name: str, element: _Element, editable=False):
        self.role = role
        self.name = name
        self.element = element
        self.editable = editable

    def is_visible(self):
        return True

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
    def __init__(self, *, url: str, parent_frame=None, roles=None, name=""):
        self.url = url
        self.parent_frame = parent_frame
        self.roles = dict(roles or {})
        self.name = name

    def get_by_role(self, role):
        return _RoleLocator(self.roles.get(role, ()))


class _Page:
    def __init__(self, *, url: str, main_frame: _Frame, frames=None, title="Page"):
        self.url = url
        self.main_frame = main_frame
        self.frames = list(frames or [main_frame])
        self._title = title
        self.viewport_size = {"width": 1200, "height": 800}
        self.closed = False

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.visibilityState":
            return "visible"
        if expression == "document.visibilityState === 'visible'":
            return True
        raise AssertionError(expression)

    def is_closed(self):
        return self.closed


class _Context:
    def __init__(self, page):
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
        return self.pages[0]

    def close(self):
        return None


class _Browser:
    version = "fake"

    def __init__(self, context):
        self.context = context

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
    def __init__(self, context):
        self.chromium = _Chromium(_Browser(context))

    def stop(self):
        return None


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _build(page, *, navigation=True, text_entry=True):
    permission = BrowserPermissionContext(
        allow_navigation=navigation,
        allow_page_interaction=True,
        allow_text_entry=text_entry,
        allowed_origins=("https://example.com",),
    )
    context = _Context(page)
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(_Playwright(context)),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=permission, headless=True)
    return browser, session, permission


def _authorized_action(browser, session, permission, scene_target, kind, *, args=None, expected=None):
    observation = browser.observe_scene_target(
        session.session_id,
        scene_target.target_id,
    )
    action = BrowserAction.create(
        session_id=session.session_id,
        page_id=observation.page_id,
        kind=kind,
        target=observation.target,
        args=args,
        expected=expected,
    )
    authority = BrowserActionAuthority.from_observation(
        action,
        observation,
        permission,
    )
    return action, authority


class BrowserSceneActionTests(unittest.TestCase):
    def test_focuses_exact_target_inside_same_origin_child_frame(self):
        main = _Frame(url="https://example.com/app")
        element = _Element(tag="button")
        child = _Frame(
            url="https://example.com/embed",
            parent_frame=main,
            roles={
                "button": [
                    _ItemLocator(role="button", name="Continue", element=element)
                ]
            },
        )
        page = _Page(url=main.url, main_frame=main, frames=[main, child])
        browser, session, permission = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(item for item in scene.targets if item.accessible_name == "Continue")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                target,
                BrowserActionKind.FOCUS,
            )
            evidence = browser.act(action, authority)
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(evidence.postcondition, "same_scene_target_focused")
            self.assertEqual(evidence.data["frame_id"], target.frame_id)
            self.assertTrue(element.focused)
        finally:
            browser.close()

    def test_link_navigation_click_requires_navigation_authority_and_url_postcondition(self):
        main = _Frame(url="https://example.com/start")
        page = _Page(url=main.url, main_frame=main)
        link = _Element(tag="a", on_click=lambda: setattr(page, "url", "https://example.com/done"))
        main.roles["link"] = [_ItemLocator(role="link", name="Open", element=link)]
        browser, session, permission = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(item for item in scene.targets if item.role == "link")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                target,
                BrowserActionKind.CLICK,
                expected={"url_equals": "https://example.com/done"},
            )
            evidence = browser.act(action, authority)
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(evidence.url_after, "https://example.com/done")
            self.assertEqual(
                evidence.postcondition,
                "url_equals_after_exact_scene_target_click",
            )
        finally:
            browser.close()

        main = _Frame(url="https://example.com/start")
        page = _Page(url=main.url, main_frame=main)
        link = _Element(tag="a", on_click=lambda: setattr(page, "url", "https://example.com/done"))
        main.roles["link"] = [_ItemLocator(role="link", name="Open", element=link)]
        browser, session, permission = _build(page, navigation=False)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(item for item in scene.targets if item.role == "link")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                target,
                BrowserActionKind.CLICK,
                expected={"url_equals": "https://example.com/done"},
            )
            evidence = browser.act(action, authority)
            self.assertFalse(evidence.success)
            self.assertIn("navigation permission", evidence.error or "")
            self.assertEqual(page.url, "https://example.com/start")
        finally:
            browser.close()

    def test_radio_check_is_verified_and_radio_uncheck_is_refused(self):
        radio = _Element(tag="input", input_type="radio", checked=False)
        main = _Frame(
            url="https://example.com/form",
            roles={"radio": [_ItemLocator(role="radio", name="Choice A", element=radio)]},
        )
        page = _Page(url=main.url, main_frame=main)
        browser, session, permission = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(item for item in scene.targets if item.role == "radio")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                target,
                BrowserActionKind.CHECK,
            )
            evidence = browser.act(action, authority)
            self.assertTrue(evidence.success, evidence.error)
            self.assertTrue(evidence.data["checked_after"])

            fresh_scene = browser.observe_scene(session.session_id)
            fresh_target = next(item for item in fresh_scene.targets if item.role == "radio")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                fresh_target,
                BrowserActionKind.UNCHECK,
            )
            evidence = browser.act(action, authority)
            self.assertFalse(evidence.success)
            self.assertIn("refuses to uncheck a radio", evidence.error or "")
            self.assertTrue(radio.checked)
        finally:
            browser.close()

    def test_searchbox_text_entry_returns_hash_evidence_not_plaintext(self):
        search = _Element(tag="input", input_type="search", value="")
        main = _Frame(
            url="https://example.com/search",
            roles={
                "searchbox": [
                    _ItemLocator(
                        role="searchbox",
                        name="Search",
                        element=search,
                        editable=True,
                    )
                ]
            },
        )
        page = _Page(url=main.url, main_frame=main)
        browser, session, permission = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(item for item in scene.targets if item.role == "searchbox")
            action, authority = _authorized_action(
                browser,
                session,
                permission,
                target,
                BrowserActionKind.TYPE_TEXT,
                args={"text": "privacy safe query"},
            )
            evidence = browser.act(action, authority)
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(search.value, "privacy safe query")
            self.assertEqual(evidence.data["text_length_after"], 18)
            self.assertNotIn("privacy safe query", repr(evidence.data))
            self.assertEqual(
                evidence.postcondition,
                "same_scene_target_text_equals_requested",
            )
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

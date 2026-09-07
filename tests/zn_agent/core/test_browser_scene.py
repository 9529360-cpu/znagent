from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.managed_browser import ManagedBrowserError
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _Element:
    def __init__(
        self,
        *,
        tag: str,
        input_type: str = "",
        sensitive: bool = False,
        disabled: bool = False,
        read_only: bool = False,
        checked=None,
        selected=None,
        href: str = "",
    ):
        self.tag = tag
        self.state = {
            "connected": True,
            "tag": tag,
            "input_type": input_type,
            "sensitive": sensitive,
            "disabled": disabled,
            "read_only": read_only,
            "checked": checked,
            "selected": selected,
            "value_length": 0,
            "href": href,
        }
        self.disposed = False

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return self is arg
        if expression.strip().startswith("element => String(element.tagName"):
            return self.tag
        return dict(self.state)

    def dispose(self):
        self.disposed = True


class _ItemLocator:
    def __init__(self, *, role: str, name: str, element: _Element, enabled=True, editable=False):
        self.role = role
        self.name = name
        self.element = element
        self.enabled = enabled
        self.editable = editable

    def is_visible(self):
        return True

    def is_enabled(self):
        return self.enabled

    def is_editable(self):
        return self.editable

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
    def __init__(self, *, url: str, name: str = "", parent_frame=None, roles=None):
        self.url = url
        self.name = name
        self.parent_frame = parent_frame
        self.roles = dict(roles or {})

    def get_by_role(self, role):
        return _RoleLocator(self.roles.get(role, ()))


class _Page:
    def __init__(self, *, url: str, title: str, main_frame: _Frame, frames=None, visible=True):
        self.url = url
        self._title = title
        self.main_frame = main_frame
        self.frames = list(frames or [main_frame])
        self.viewport_size = {"width": 1200, "height": 800}
        self.visible = visible
        self.closed = False

    def title(self):
        return self._title

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        if expression == "document.visibilityState":
            return "visible" if self.visible else "hidden"
        raise AssertionError(expression)

    def is_closed(self):
        return self.closed


class _Context:
    def __init__(self, pages):
        self.pages = list(pages)

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


def _build(page, *, allowed_origins=("https://example.com",)):
    context = _Context([page])
    playwright = _Playwright(context)
    browser = SemanticPlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(
        permission=BrowserPermissionContext(
            allow_page_interaction=True,
            allowed_origins=allowed_origins,
        ),
        headless=True,
    )
    return browser, session, context


class BrowserSceneTests(unittest.TestCase):
    def test_scene_exposes_bounded_semantic_targets_without_page_text(self):
        search_element = _Element(tag="input", input_type="search")
        button_element = _Element(tag="button")
        main = _Frame(
            url="https://example.com/search",
            roles={
                "searchbox": [
                    _ItemLocator(
                        role="searchbox",
                        name="Search",
                        element=search_element,
                        editable=True,
                    )
                ],
                "button": [
                    _ItemLocator(role="button", name="Go", element=button_element)
                ],
            },
        )
        page = _Page(url=main.url, title="Search", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            self.assertEqual(scene.url, "https://example.com/search")
            self.assertEqual(scene.title, "Search")
            self.assertEqual(
                {target.role for target in scene.targets},
                {"searchbox", "button"},
            )
            search = next(
                target for target in scene.targets if target.role == "searchbox"
            )
            self.assertEqual(search.accessible_name, "Search")
            self.assertTrue(search.editable)
            self.assertLessEqual(len(scene.targets), 64)
            self.assertFalse(hasattr(scene, "body_text"))
        finally:
            browser.close()

    def test_sensitive_textbox_is_redacted_without_sensitive_field_authority(self):
        password = _Element(tag="input", input_type="password", sensitive=True)
        main = _Frame(
            url="https://example.com/login",
            roles={
                "textbox": [
                    _ItemLocator(
                        role="textbox",
                        name="Account password",
                        element=password,
                        editable=True,
                    )
                ]
            },
        )
        page = _Page(url=main.url, title="Login", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            self.assertEqual(scene.redacted_target_count, 1)
            self.assertEqual(len(scene.targets), 1)
            self.assertTrue(scene.targets[0].sensitive)
            self.assertEqual(scene.targets[0].accessible_name, "")
            self.assertFalse(scene.targets[0].editable)
        finally:
            browser.close()

    def test_cross_origin_frame_fails_closed_without_main_frame_fallback(self):
        main = _Frame(url="https://example.com/app")
        child_button = _Element(tag="button")
        child = _Frame(
            url="https://other.example/embed",
            parent_frame=main,
            roles={
                "button": [
                    _ItemLocator(
                        role="button",
                        name="Continue",
                        element=child_button,
                    )
                ]
            },
        )
        page = _Page(
            url=main.url,
            title="App",
            main_frame=main,
            frames=[main, child],
        )
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            blocked = next(frame for frame in scene.frames if not frame.is_main)
            self.assertFalse(blocked.observable)
            self.assertEqual(blocked.url, "")
            self.assertIn("cross-origin", blocked.blocked_reason)
            self.assertEqual(scene.targets, ())
        finally:
            browser.close()

    def test_scene_target_revalidation_rejects_spa_node_replacement(self):
        original = _Element(tag="button")
        item = _ItemLocator(role="button", name="Save", element=original)
        main = _Frame(
            url="https://example.com/editor",
            roles={"button": [item]},
        )
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = scene.targets[0]
            self.assertEqual(
                browser.validate_scene_target(
                    session.session_id,
                    target.target_id,
                ),
                target,
            )
            item.element = _Element(tag="button")
            with self.assertRaisesRegex(ManagedBrowserError, "stale"):
                browser.validate_scene_target(
                    session.session_id,
                    target.target_id,
                )
        finally:
            browser.close()

    def test_workspace_tracks_stable_page_ids_and_managed_ownership(self):
        main1 = _Frame(url="https://example.com/one")
        main2 = _Frame(url="https://example.com/two")
        page1 = _Page(
            url=main1.url,
            title="One",
            main_frame=main1,
            visible=False,
        )
        page2 = _Page(
            url=main2.url,
            title="Two",
            main_frame=main2,
            visible=True,
        )
        browser, session, context = _build(page1)
        try:
            context.pages.append(page2)
            first = browser.observe_browser_workspace(session.session_id)
            second = browser.observe_browser_workspace(session.session_id)
            self.assertTrue(first.foreground_known)
            self.assertEqual(first.foreground_page_id, "page-2")
            self.assertFalse(first.window_topology_known)
            self.assertEqual(
                [tab.page_id for tab in first.tabs],
                ["page-1", "page-2"],
            )
            self.assertEqual(
                [tab.page_id for tab in second.tabs],
                ["page-1", "page-2"],
            )
            self.assertTrue(
                all(tab.ownership == "zn_created" for tab in first.tabs)
            )
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

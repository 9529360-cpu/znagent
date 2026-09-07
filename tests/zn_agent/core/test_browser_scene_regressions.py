from __future__ import annotations

import unittest
from dataclasses import replace

from zn_agent.core.browser import BrowserPermissionContext, BrowserPlane
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


def _items(role: str, count: int, *, prefix: str | None = None):
    label = prefix or role.title()
    return [
        _ItemLocator(
            role=role,
            name=f"{label} {index}",
            element=_Element(tag="button" if role == "button" else "div"),
        )
        for index in range(count)
    ]


class BrowserSceneRegressionTests(unittest.TestCase):
    def test_requested_max_targets_cannot_exceed_global_cap(self):
        main = _Frame(
            url="https://example.com/caps",
            roles={
                "link": _items("link", 16),
                "button": _items("button", 16),
                "checkbox": _items("checkbox", 16),
                "radio": _items("radio", 16),
                "heading": _items("heading", 16),
            },
        )
        page = _Page(url=main.url, title="Caps", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id, max_targets=1000)
            self.assertEqual(len(scene.targets), 64)
            self.assertTrue(scene.truncated)
        finally:
            browser.close()

    def test_single_role_has_deterministic_cap(self):
        main = _Frame(
            url="https://example.com/buttons",
            roles={"button": _items("button", 20)},
        )
        page = _Page(url=main.url, title="Buttons", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            buttons = [target for target in scene.targets if target.role == "button"]
            self.assertEqual(len(buttons), 16)
            self.assertEqual(
                [target.accessible_name for target in buttons],
                [f"Button {index}" for index in range(16)],
            )
            self.assertTrue(scene.truncated)
        finally:
            browser.close()

    def test_requested_smaller_target_limit_is_respected_and_marks_truncated(self):
        main = _Frame(
            url="https://example.com/small",
            roles={"button": _items("button", 8)},
        )
        page = _Page(url=main.url, title="Small", main_frame=main)
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id, max_targets=3)
            self.assertEqual(len(scene.targets), 3)
            self.assertTrue(scene.truncated)
        finally:
            browser.close()

    def test_same_origin_child_frame_has_independent_provenance(self):
        main = _Frame(url="https://example.com/app")
        child_item = _ItemLocator(
            role="button",
            name="Child action",
            element=_Element(tag="button"),
        )
        child = _Frame(
            url="https://example.com/embed",
            name="child",
            parent_frame=main,
            roles={"button": [child_item]},
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
            child_scene = next(frame for frame in scene.frames if not frame.is_main)
            target = next(target for target in scene.targets if target.accessible_name == "Child action")
            self.assertTrue(child_scene.observable)
            self.assertEqual(child_scene.url, child.url)
            self.assertEqual(child_scene.name, "child")
            self.assertEqual(target.frame_id, child_scene.frame_id)
            self.assertNotEqual(child_scene.frame_id, scene.frames[0].frame_id)
        finally:
            browser.close()

    def test_page_url_change_makes_old_target_stale(self):
        item = _ItemLocator(role="button", name="Save", element=_Element(tag="button"))
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        try:
            target = browser.observe_scene(session.session_id).targets[0]
            page.url = "https://example.com/editor?version=2"
            with self.assertRaisesRegex(ManagedBrowserError, "page changed"):
                browser.validate_scene_target(session.session_id, target.target_id)
        finally:
            browser.close()

    def test_frame_detach_makes_old_target_stale(self):
        main = _Frame(url="https://example.com/app")
        item = _ItemLocator(role="button", name="Inside", element=_Element(tag="button"))
        child = _Frame(
            url="https://example.com/frame",
            parent_frame=main,
            roles={"button": [item]},
        )
        page = _Page(url=main.url, title="App", main_frame=main, frames=[main, child])
        browser, session, _context = _build(page)
        try:
            scene = browser.observe_scene(session.session_id)
            target = next(target for target in scene.targets if target.accessible_name == "Inside")
            page.frames = [main]
            with self.assertRaisesRegex(ManagedBrowserError, "frame is detached"):
                browser.validate_scene_target(session.session_id, target.target_id)
        finally:
            browser.close()

    def test_frame_navigation_or_origin_change_makes_old_target_stale(self):
        main = _Frame(url="https://example.com/app")
        item = _ItemLocator(role="button", name="Inside", element=_Element(tag="button"))
        child = _Frame(
            url="https://example.com/frame",
            parent_frame=main,
            roles={"button": [item]},
        )
        page = _Page(url=main.url, title="App", main_frame=main, frames=[main, child])
        browser, session, _context = _build(page)
        try:
            target = next(
                target
                for target in browser.observe_scene(session.session_id).targets
                if target.accessible_name == "Inside"
            )
            child.url = "https://other.example/frame"
            with self.assertRaisesRegex(ManagedBrowserError, "frame navigated"):
                browser.validate_scene_target(session.session_id, target.target_id)
        finally:
            browser.close()

    def test_accessible_name_change_makes_old_target_stale(self):
        item = _ItemLocator(role="button", name="Save", element=_Element(tag="button"))
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        try:
            target = browser.observe_scene(session.session_id).targets[0]
            item.name = "Publish"
            with self.assertRaisesRegex(ManagedBrowserError, "accessible name changed"):
                browser.validate_scene_target(session.session_id, target.target_id)
        finally:
            browser.close()

    def test_accessible_role_change_makes_old_target_stale(self):
        item = _ItemLocator(role="button", name="Save", element=_Element(tag="button"))
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        try:
            target = browser.observe_scene(session.session_id).targets[0]
            item.role = "checkbox"
            with self.assertRaisesRegex(ManagedBrowserError, "semantic role changed"):
                browser.validate_scene_target(session.session_id, target.target_id)
        finally:
            browser.close()

    def test_new_observation_invalidates_old_scene_and_disposes_retained_handle(self):
        first_element = _Element(tag="button")
        item = _ItemLocator(role="button", name="Save", element=first_element)
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        try:
            first = browser.observe_scene(session.session_id)
            old_target_id = first.targets[0].target_id
            item.element = _Element(tag="button")
            second = browser.observe_scene(session.session_id)
            self.assertNotEqual(first.scene_id, second.scene_id)
            self.assertTrue(first_element.disposed)
            with self.assertRaisesRegex(ManagedBrowserError, "stale or unknown"):
                browser.validate_scene_target(session.session_id, old_target_id)
        finally:
            browser.close()

    def test_close_session_disposes_retained_scene_handle(self):
        element = _Element(tag="button")
        item = _ItemLocator(role="button", name="Save", element=element)
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, _context = _build(page)
        browser.observe_scene(session.session_id)
        browser.close_session(session.session_id)
        self.assertTrue(element.disposed)
        browser.close()

    def test_page_eviction_disposes_retained_scene_handle(self):
        element = _Element(tag="button")
        item = _ItemLocator(role="button", name="Save", element=element)
        main = _Frame(url="https://example.com/editor", roles={"button": [item]})
        page = _Page(url=main.url, title="Editor", main_frame=main)
        browser, session, context = _build(page)
        try:
            browser.observe_scene(session.session_id)
            page.closed = True
            context.pages.clear()
            workspace = browser.observe_browser_workspace(session.session_id)
            self.assertEqual(workspace.tabs, ())
            self.assertTrue(element.disposed)
        finally:
            browser.close()

    def test_multiple_visible_tabs_make_foreground_unknown(self):
        main1 = _Frame(url="https://example.com/one")
        main2 = _Frame(url="https://example.com/two")
        page1 = _Page(url=main1.url, title="One", main_frame=main1, visible=True)
        page2 = _Page(url=main2.url, title="Two", main_frame=main2, visible=True)
        browser, session, context = _build(page1)
        try:
            context.pages.append(page2)
            workspace = browser.observe_browser_workspace(session.session_id)
            self.assertFalse(workspace.foreground_known)
            self.assertEqual(workspace.foreground_page_id, "")
            self.assertFalse(any(tab.is_foreground for tab in workspace.tabs))
            self.assertFalse(workspace.window_topology_known)
            self.assertEqual(workspace.windows, ())
        finally:
            browser.close()

    def test_unauthorized_tab_does_not_leak_url_or_title(self):
        allowed_frame = _Frame(url="https://example.com/one")
        blocked_frame = _Frame(url="https://other.example/private")
        allowed = _Page(url=allowed_frame.url, title="Allowed", main_frame=allowed_frame)
        blocked = _Page(url=blocked_frame.url, title="Secret title", main_frame=blocked_frame, visible=False)
        browser, session, context = _build(allowed)
        try:
            context.pages.append(blocked)
            workspace = browser.observe_browser_workspace(session.session_id)
            blocked_tab = next(tab for tab in workspace.tabs if not tab.in_authority_scope)
            self.assertEqual(blocked_tab.url, "")
            self.assertEqual(blocked_tab.title, "")
        finally:
            browser.close()

    def test_user_plane_ownership_is_user_existing(self):
        main = _Frame(url="https://example.com/current")
        page = _Page(url=main.url, title="Current", main_frame=main)
        browser, session, _context = _build(page)
        try:
            managed_session = browser._session(session.session_id)
            managed_session.identity = replace(
                managed_session.identity,
                plane=BrowserPlane.USER,
                profile_scope="user_existing",
            )
            workspace = browser.observe_browser_workspace(session.session_id)
            self.assertEqual([tab.ownership for tab in workspace.tabs], ["user_existing"])
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

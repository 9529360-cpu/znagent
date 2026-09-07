from __future__ import annotations

import http.server
import threading
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.managed_browser import ManagedBrowserError
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _SceneActionFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/frame"):
            payload = b"""<!doctype html><html><head><title>Frame</title></head><body>
              <button aria-label='Frame focus'>Frame focus</button>
              <input type='search' aria-label='Frame search'>
              <label><input type='checkbox'> Frame check</label>
            </body></html>"""
        elif self.path.startswith("/done-link"):
            payload = b"<!doctype html><html><head><title>Done Link</title></head><body><h1>done link</h1></body></html>"
        elif self.path.startswith("/done-button"):
            payload = b"<!doctype html><html><head><title>Done Button</title></head><body><h1>done button</h1></body></html>"
        else:
            payload = b"""<!doctype html><html><head><title>Scene Form</title></head><body>
              <main>
                <input type='search' aria-label='Main search'>
                <label><input type='checkbox'> Main check</label>
                <label><input type='radio' name='choice'> Main radio</label>
                <a aria-label='Go link' href='/done-link'>Go link</a>
                <button aria-label='Go button' onclick="location.href='/done-button'">Go button</button>
                <button aria-label='Dynamic focus' id='dynamic' onfocus="
                  const old = document.getElementById('dynamic');
                  const replacement = old.cloneNode(true);
                  replacement.removeAttribute('onfocus');
                  old.replaceWith(replacement);">Dynamic focus</button>
                <iframe title='Same origin frame' src='/frame'></iframe>
              </main>
            </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserSceneActionsWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SceneActionFixtureHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _browser(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        identity = browser.open_session(permission=permission, headless=True)
        return browser, identity, permission

    @staticmethod
    def _page_authority(browser, identity, permission, action):
        observed = browser.observe(identity.session_id, page_id=action.page_id)
        return BrowserActionAuthority.from_observation(action, observed, permission)

    @staticmethod
    def _scene_action(browser, identity, permission, target, kind, *, args=None, expected=None):
        page_id = browser._default_page_id(browser._sessions[identity.session_id])
        observed = browser.observe_scene_target(
            identity.session_id,
            target.target_id,
            page_id=page_id,
        )
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=observed.page_id,
            kind=kind,
            target=observed.target,
            args=args,
            expected=expected,
        )
        authority = BrowserActionAuthority.from_observation(action, observed, permission)
        return action, authority

    @staticmethod
    def _target(scene, name, *, role=None):
        return next(
            target
            for target in scene.targets
            if target.accessible_name == name and (role is None or target.role == role)
        )

    def _navigate_form(self, browser, identity, permission):
        initial = browser.observe(identity.session_id)
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=initial.page_id,
            kind=BrowserActionKind.NAVIGATE,
            args={"url": self.origin + "/form"},
            expected={"url_equals": self.origin + "/form"},
        )
        authority = BrowserActionAuthority.from_observation(action, initial, permission)
        effect = browser.act(action, authority)
        self.assertTrue(effect.success, effect.error)
        return initial.page_id

    def test_real_chromium_exact_scene_mutations_and_dynamic_re_grounding(self):
        browser, identity, permission = self._browser()
        try:
            page_id = self._navigate_form(browser, identity, permission)

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            frame_focus = self._target(scene, "Frame focus")
            self.assertNotEqual(frame_focus.frame_id, "main")
            action, authority = self._scene_action(
                browser, identity, permission, frame_focus, BrowserActionKind.FOCUS
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            with self.assertRaisesRegex(ManagedBrowserError, "fresh BrowserScene|stale"):
                browser.validate_scene_target(identity.session_id, frame_focus.target_id, page_id=page_id)

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            frame_search = self._target(scene, "Frame search", role="searchbox")
            text = "chromium exact scene"
            action, authority = self._scene_action(
                browser,
                identity,
                permission,
                frame_search,
                BrowserActionKind.TYPE_TEXT,
                args={"text": text},
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.data["text_length_after"], len(text))
            self.assertEqual(effect.data["text_sha256_after"], effect.data["expected_text_sha256"])
            self.assertNotIn(text, repr(effect.data))

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            frame_check = self._target(scene, "Frame check", role="checkbox")
            action, authority = self._scene_action(
                browser, identity, permission, frame_check, BrowserActionKind.CHECK
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(effect.data["checked_after"])

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            main_check = self._target(scene, "Main check", role="checkbox")
            action, authority = self._scene_action(
                browser, identity, permission, main_check, BrowserActionKind.CHECK
            )
            self.assertTrue(browser.act(action, authority).success)

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            main_check = self._target(scene, "Main check", role="checkbox")
            action, authority = self._scene_action(
                browser, identity, permission, main_check, BrowserActionKind.UNCHECK
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertFalse(effect.data["checked_after"])

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            radio = self._target(scene, "Main radio", role="radio")
            action, authority = self._scene_action(
                browser, identity, permission, radio, BrowserActionKind.CHECK
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(effect.data["checked_after"])

            scene = browser.observe_scene(identity.session_id, page_id=page_id)
            dynamic = self._target(scene, "Dynamic focus", role="button")
            action, authority = self._scene_action(
                browser, identity, permission, dynamic, BrowserActionKind.FOCUS
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            replay = browser.act(action, authority)
            self.assertFalse(replay.success)
            fresh_scene = browser.observe_scene(identity.session_id, page_id=page_id)
            replacement = self._target(fresh_scene, "Dynamic focus", role="button")
            self.assertEqual(replacement.accessible_name, dynamic.accessible_name)
            self.assertNotEqual(replacement.observed_at, dynamic.observed_at)
        finally:
            browser.close_session(identity.session_id)

    def test_real_chromium_verified_link_and_button_navigation_click(self):
        for role, name, suffix in (
            ("link", "Go link", "/done-link"),
            ("button", "Go button", "/done-button"),
        ):
            with self.subTest(role=role):
                browser, identity, permission = self._browser()
                try:
                    page_id = self._navigate_form(browser, identity, permission)
                    scene = browser.observe_scene(identity.session_id, page_id=page_id)
                    target = self._target(scene, name, role=role)
                    action, authority = self._scene_action(
                        browser,
                        identity,
                        permission,
                        target,
                        BrowserActionKind.CLICK,
                        expected={"url_equals": self.origin + suffix},
                    )
                    effect = browser.act(action, authority)
                    self.assertTrue(effect.success, effect.error)
                    self.assertEqual(effect.url_after, self.origin + suffix)
                    self.assertEqual(
                        browser.observe(identity.session_id, page_id=page_id).url,
                        self.origin + suffix,
                    )
                    self.assertFalse(browser.act(action, authority).success)
                    with self.assertRaisesRegex(ManagedBrowserError, "fresh BrowserScene|stale"):
                        browser.validate_scene_target(identity.session_id, target.target_id, page_id=page_id)
                finally:
                    browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


class _ControlsFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = b"""<!doctype html><html><head><title>ZN Stateful Controls Fixture</title></head>
        <body><main>
          <button id='toggle' aria-label='Toggle favorite' aria-pressed='false'
            onclick="window.toggleClicks=(window.toggleClicks||0)+1;this.setAttribute('aria-pressed','true')">Toggle</button>
          <button id='disclosure' aria-label='Expand details' aria-expanded='false'
            onclick="window.disclosureClicks=(window.disclosureClicks||0)+1;this.setAttribute('aria-expanded','true')">Expand</button>
          <div role='tablist' aria-label='Example tabs'>
            <button role='tab' aria-label='Overview tab' aria-selected='true' id='tab-overview'>Overview</button>
            <button role='tab' aria-label='Details tab' aria-selected='false' id='tab-details'
              onclick="window.tabClicks=(window.tabClicks||0)+1;document.getElementById('tab-overview').setAttribute('aria-selected','false');this.setAttribute('aria-selected','true')">Details</button>
          </div>
          <button id='noop' aria-label='No-op toggle' aria-pressed='false'
            onclick="window.noopClicks=(window.noopClicks||0)+1">No-op</button>
          <button id='stale' aria-label='Stale toggle' aria-pressed='false'
            onclick="window.staleClicks=(window.staleClicks||0)+1;this.setAttribute('aria-pressed','true')">Stale</button>
        </main></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserControlsWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _ControlsFixtureHandler,
        )
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
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        identity = browser.open_session(permission=permission, headless=True)
        return browser, identity, permission

    def _navigate(self, browser, identity, permission):
        initial = browser.observe(identity.session_id)
        page_url = self.origin + "/controls"
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=initial.page_id,
            kind=BrowserActionKind.NAVIGATE,
            args={"url": page_url},
            expected={"url_equals": page_url},
        )
        effect = browser.act(
            action,
            BrowserActionAuthority.from_observation(action, initial, permission),
        )
        self.assertTrue(effect.success, effect.error)
        return initial.page_id, page_url

    @staticmethod
    def _target(scene, *, role, name):
        matches = [
            target
            for target in scene.targets
            if target.role == role and target.accessible_name == name
        ]
        if len(matches) != 1:
            raise AssertionError((role, name, len(matches)))
        return matches[0]

    @staticmethod
    def _control(
        browser,
        identity,
        permission,
        *,
        page_id,
        role,
        name,
        expected,
    ):
        scene = browser.observe_scene(identity.session_id, page_id=page_id)
        target = ManagedBrowserControlsWindowsE2E._target(
            scene,
            role=role,
            name=name,
        )
        observed = browser.observe_scene_target(
            identity.session_id,
            target.target_id,
            page_id=page_id,
        )
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=page_id,
            kind=BrowserActionKind.CLICK,
            target=observed.target,
            expected=expected,
        )
        authority = BrowserActionAuthority.from_observation(
            action,
            observed,
            permission,
        )
        return scene, action, authority

    def test_real_chromium_toggle_disclosure_and_tab_verify_exact_aria_state_once(self):
        cases = (
            (
                "button",
                "Toggle favorite",
                {"pressed_equals": True},
                "aria-pressed",
                "toggleClicks",
                "toggle",
            ),
            (
                "button",
                "Expand details",
                {"expanded_equals": True},
                "aria-expanded",
                "disclosureClicks",
                "disclosure",
            ),
            (
                "tab",
                "Details tab",
                {"selected_equals": True},
                "aria-selected",
                "tabClicks",
                "tab-details",
            ),
        )
        for role, name, expected, attribute, counter, target_id in cases:
            with self.subTest(role=role, name=name):
                browser, identity, permission = self._browser()
                try:
                    page_id, page_url = self._navigate(browser, identity, permission)
                    before_workspace = browser.observe_browser_workspace(identity.session_id)
                    before_scene, action, authority = self._control(
                        browser,
                        identity,
                        permission,
                        page_id=page_id,
                        role=role,
                        name=name,
                        expected=expected,
                    )
                    effect = browser.act(action, authority)
                    self.assertTrue(effect.success, effect.error)
                    self.assertEqual(effect.data["dispatch_count"], 1)
                    self.assertIs(effect.data["state_before"], False)
                    self.assertIs(effect.data["state_after"], True)
                    self.assertTrue(effect.data["target_revalidated_before_dispatch"])
                    self.assertTrue(effect.data["page_topology_unchanged"])
                    self.assertEqual(effect.data["new_page_count"], 0)
                    self.assertEqual(effect.url_before, page_url)
                    self.assertEqual(effect.url_after, page_url)
                    provider_page = browser._sessions[identity.session_id].pages[page_id]
                    self.assertEqual(
                        provider_page.locator(f"#{target_id}").get_attribute(attribute),
                        "true",
                    )
                    self.assertEqual(
                        provider_page.evaluate(f"() => window.{counter} || 0"),
                        1,
                    )
                    fresh = browser.observe_scene(identity.session_id, page_id=page_id)
                    self.assertNotEqual(fresh.scene_id, before_scene.scene_id)
                    after_workspace = browser.observe_browser_workspace(identity.session_id)
                    self.assertEqual(
                        [tab.page_id for tab in after_workspace.tabs],
                        [tab.page_id for tab in before_workspace.tabs],
                    )
                    self.assertEqual(
                        browser.observe(identity.session_id, page_id=page_id).url,
                        page_url,
                    )
                finally:
                    browser.close_session(identity.session_id)

    def test_real_chromium_noop_fails_after_one_click_without_retry(self):
        browser, identity, permission = self._browser()
        try:
            page_id, page_url = self._navigate(browser, identity, permission)
            _scene, action, authority = self._control(
                browser,
                identity,
                permission,
                page_id=page_id,
                role="button",
                name="No-op toggle",
                expected={"pressed_equals": True},
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertIs(effect.data["state_before"], False)
            self.assertIs(effect.data["state_after"], False)
            provider_page = browser._sessions[identity.session_id].pages[page_id]
            self.assertEqual(provider_page.evaluate("() => window.noopClicks || 0"), 1)
            self.assertEqual(provider_page.url, page_url)
        finally:
            browser.close_session(identity.session_id)

    def test_real_chromium_same_name_clone_replacement_is_stale_before_dispatch(self):
        browser, identity, permission = self._browser()
        try:
            page_id, _page_url = self._navigate(browser, identity, permission)
            _scene, action, authority = self._control(
                browser,
                identity,
                permission,
                page_id=page_id,
                role="button",
                name="Stale toggle",
                expected={"pressed_equals": True},
            )
            provider_page = browser._sessions[identity.session_id].pages[page_id]
            provider_page.evaluate(
                """() => {
                  const old = document.getElementById('stale');
                  const replacement = old.cloneNode(true);
                  old.replaceWith(replacement);
                }"""
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(provider_page.evaluate("() => window.staleClicks || 0"), 0)
            self.assertEqual(
                provider_page.locator("#stale").get_attribute("aria-pressed"),
                "false",
            )
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

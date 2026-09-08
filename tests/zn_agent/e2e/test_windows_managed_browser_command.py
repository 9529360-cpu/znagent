from __future__ import annotations

import hashlib
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


class _CommandFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = b"""<!doctype html><html><head><title>ZN Command Fixture</title></head>
        <body><main>
          <div role='row' aria-label='Invoice 42' id='invoice-42'>
            <span>Invoice 42</span>
            <button aria-label='Delete invoice 42'
              onclick="document.getElementById('invoice-42').remove()">Delete</button>
          </div>
          <div role='row' aria-label='Invoice 43' id='invoice-43'>
            <span>Invoice 43</span>
            <button aria-label='Delete invoice 43 no-op'
              onclick="window.commandNoopClicks=(window.commandNoopClicks||0)+1">Delete no-op</button>
          </div>
          <div role='row' aria-label='Invoice 44' id='invoice-44'>
            <span>Invoice 44</span>
            <button aria-label='Delete invoice 44 stale' id='stale-delete'
              onclick="window.staleDeleteClicks=(window.staleDeleteClicks||0)+1;document.getElementById('invoice-44').remove()">Delete stale</button>
          </div>
        </main></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserCommandWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _CommandFixtureHandler,
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
        page_url = self.origin + "/commands"
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
    def _command(browser, identity, permission, *, page_id, trigger_name, row_name):
        scene = browser.observe_scene(identity.session_id, page_id=page_id)
        trigger = ManagedBrowserCommandWindowsE2E._target(
            scene,
            role="button",
            name=trigger_name,
        )
        rows = [
            target
            for target in scene.targets
            if target.role == "row" and target.accessible_name == row_name
        ]
        if len(rows) != 1:
            raise AssertionError((row_name, len(rows)))
        observed = browser.observe_scene_target(
            identity.session_id,
            trigger.target_id,
            page_id=page_id,
        )
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=page_id,
            kind=BrowserActionKind.CLICK,
            target=observed.target,
            expected={
                "target_absent_equals": {
                    "role": "row",
                    "accessible_name": row_name,
                }
            },
        )
        authority = BrowserActionAuthority.from_observation(
            action,
            observed,
            permission,
        )
        return scene, action, authority

    def test_real_chromium_exact_command_requires_fresh_row_absence(self):
        browser, identity, permission = self._browser()
        try:
            page_id, page_url = self._navigate(browser, identity, permission)
            before_workspace = browser.observe_browser_workspace(identity.session_id)
            before_scene, action, authority = self._command(
                browser,
                identity,
                permission,
                page_id=page_id,
                trigger_name="Delete invoice 42",
                row_name="Invoice 42",
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.url_before, page_url)
            self.assertEqual(effect.url_after, page_url)
            self.assertEqual(effect.data["matching_target_count_before"], 1)
            self.assertEqual(effect.data["matching_target_count_after"], 0)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertTrue(effect.data["page_topology_unchanged"])
            self.assertEqual(effect.data["new_page_count"], 0)
            self.assertEqual(effect.data["new_page_ids"], [])
            self.assertEqual(effect.data["name_length"], len("Invoice 42"))
            self.assertEqual(
                effect.data["name_sha256"],
                hashlib.sha256(b"Invoice 42").hexdigest(),
            )
            self.assertNotIn("Invoice 42", repr(effect.data))

            fresh = browser.observe_scene(identity.session_id, page_id=page_id)
            self.assertNotEqual(fresh.scene_id, before_scene.scene_id)
            self.assertFalse(fresh.truncated)
            self.assertFalse(
                any(
                    target.role == "row" and target.accessible_name == "Invoice 42"
                    for target in fresh.targets
                )
            )
            after_workspace = browser.observe_browser_workspace(identity.session_id)
            self.assertEqual(
                [tab.page_id for tab in after_workspace.tabs],
                [tab.page_id for tab in before_workspace.tabs],
            )
            self.assertEqual(browser.observe(identity.session_id, page_id=page_id).url, page_url)
        finally:
            browser.close_session(identity.session_id)

    def test_real_chromium_noop_command_fails_after_one_click_without_retry(self):
        browser, identity, permission = self._browser()
        try:
            page_id, page_url = self._navigate(browser, identity, permission)
            _scene, action, authority = self._command(
                browser,
                identity,
                permission,
                page_id=page_id,
                trigger_name="Delete invoice 43 no-op",
                row_name="Invoice 43",
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("remained present", effect.error or "")
            self.assertEqual(effect.data["matching_target_count_before"], 1)
            self.assertEqual(effect.data["matching_target_count_after"], 1)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertEqual(effect.url_before, page_url)
            self.assertEqual(effect.url_after, page_url)
            provider_page = browser._sessions[identity.session_id].pages[page_id]
            self.assertEqual(
                provider_page.evaluate("() => window.commandNoopClicks || 0"),
                1,
            )
            fresh = browser.observe_scene(identity.session_id, page_id=page_id)
            self.assertTrue(
                any(
                    target.role == "row" and target.accessible_name == "Invoice 43"
                    for target in fresh.targets
                )
            )
        finally:
            browser.close_session(identity.session_id)

    def test_real_chromium_same_name_trigger_replacement_is_stale_before_dispatch(self):
        browser, identity, permission = self._browser()
        try:
            page_id, _page_url = self._navigate(browser, identity, permission)
            _scene, action, authority = self._command(
                browser,
                identity,
                permission,
                page_id=page_id,
                trigger_name="Delete invoice 44 stale",
                row_name="Invoice 44",
            )
            provider_page = browser._sessions[identity.session_id].pages[page_id]
            provider_page.evaluate(
                """() => {
                  const old = document.getElementById('stale-delete');
                  const replacement = old.cloneNode(true);
                  old.replaceWith(replacement);
                }"""
            )
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(
                provider_page.evaluate("() => window.staleDeleteClicks || 0"),
                0,
            )
            fresh = browser.observe_scene(identity.session_id, page_id=page_id)
            self.assertTrue(
                any(
                    target.role == "row" and target.accessible_name == "Invoice 44"
                    for target in fresh.targets
                )
            )
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

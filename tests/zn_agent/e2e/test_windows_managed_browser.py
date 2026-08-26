from __future__ import annotations

import http.server
import json
import threading
import time
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import ManagedBrowserError, PlaywrightManagedBrowser


_RAW_TARGET_VALUE = "ZN managed browser raw target value must stay private"


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/next":
            title = "ZN Browser Next"
            body = (
                '<button id="zn-target" aria-label="ZN Next Action">Continue</button>'
                "<main>ZN managed browser next marker</main>"
            )
        else:
            title = "ZN Browser Fixture"
            body = (
                f'<input id="zn-target" type="text" aria-label="ZN Search Target" '
                f'value="{_RAW_TARGET_VALUE}">'
                '<input id="zn-churn" type="text" aria-label="ZN Churn Target">'
                '<button id="zn-toggle" type="button" aria-label="ZN Toggle" aria-pressed="false">Toggle</button>'
                '<button id="zn-toggle-churn" type="button" aria-label="ZN Toggle Churn" aria-pressed="false">Toggle churn</button>'
                '<input id="zn-password" type="password" aria-label="Secret Password" value="hidden">'
                '<div id="zn-hidden" style="display:none">hidden target</div>'
                '<span id="zn-duplicate">one</span><span id="zn-duplicate">two</span>'
                "<main>ZN managed browser marker</main>"
                "<script>"
                "const churn=document.getElementById('zn-churn');"
                "churn.addEventListener('focus',(event)=>{"
                "const current=event.currentTarget;"
                "const replacement=current.cloneNode(true);"
                "current.replaceWith(replacement);"
                "},{once:true});"
                "const toggle=document.getElementById('zn-toggle');"
                "toggle.addEventListener('click',()=>{"
                "toggle.setAttribute('aria-pressed',toggle.getAttribute('aria-pressed')==='true'?'false':'true');"
                "});"
                "const toggleChurn=document.getElementById('zn-toggle-churn');"
                "toggleChurn.addEventListener('click',(event)=>{"
                "const current=event.currentTarget;"
                "current.setAttribute('aria-pressed','true');"
                "const replacement=current.cloneNode(true);"
                "current.replaceWith(replacement);"
                "},{once:true});"
                "</script>"
            )
        payload = (
            "<!doctype html><html><head>"
            f"<title>{title}</title>"
            "</head><body>"
            f"{body}"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_local_headless_chromium_observes_targets_focuses_exact_node_clicks_verified_toggle_and_verifies_navigation(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            self.assertEqual(initial.url, "about:blank")
            self.assertEqual(session.profile_scope, "ephemeral")
            self.assertEqual(session.provider, "playwright-chromium")

            first = BrowserAction.create(
                session_id=session.session_id,
                page_id=initial.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/"},
                expected={"url_equals": self.origin + "/"},
            )
            first_authority = BrowserActionAuthority.from_observation(
                first,
                initial,
                permission,
            )
            first_effect = browser.act(first, first_authority)
            self.assertTrue(first_effect.success, first_effect.error)
            self.assertEqual(first_effect.url_after, self.origin + "/")

            observed = browser.observe(session.session_id, page_id=initial.page_id)
            self.assertEqual(observed.title, "ZN Browser Fixture")
            self.assertIn(observed.load_state, {"interactive", "complete"})
            self.assertNotIn("text", observed.metadata)
            self.assertNotIn("content", observed.metadata)
            self.assertNotIn("html", observed.metadata)

            query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value="zn-target",
            )
            target_observation = browser.observe_target(
                session.session_id,
                query,
                page_id=observed.page_id,
            )
            target = target_observation.target
            self.assertIsNotNone(target)
            self.assertEqual(target.kind, BrowserTargetKind.ELEMENT)
            self.assertEqual(target.frame_id, "main")
            self.assertEqual(target.role, "textbox")
            self.assertEqual(target.name, "ZN Search Target")
            self.assertEqual(target.selector_hint, "dom_id:zn-target")
            self.assertEqual(target.observed_at, target_observation.captured_at)
            serialized = json.dumps(target_observation.to_dict(), sort_keys=True)
            self.assertNotIn(_RAW_TARGET_VALUE, serialized)
            self.assertNotIn("<input", serialized.lower())

            time.sleep(0.001)
            refreshed_target_observation = browser.observe_target(
                session.session_id,
                query,
                page_id=observed.page_id,
            )
            self.assertEqual(
                refreshed_target_observation.target.target_id,
                target.target_id,
            )
            self.assertNotEqual(
                refreshed_target_observation.target.observed_at,
                target.observed_at,
            )

            focus_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=refreshed_target_observation.page_id,
                kind=BrowserActionKind.FOCUS,
                target=refreshed_target_observation.target,
            )
            focus_authority = BrowserActionAuthority.from_observation(
                focus_action,
                refreshed_target_observation,
                permission,
            )
            focus_effect = browser.act(focus_action, focus_authority)
            self.assertTrue(focus_effect.success, focus_effect.error)
            self.assertEqual(focus_effect.postcondition, "same_exact_target_focused")
            self.assertEqual(
                focus_effect.target_id,
                refreshed_target_observation.target.target_id,
            )
            self.assertTrue(focus_effect.data["exact_node_continuity"])
            self.assertTrue(focus_effect.data["focused"])
            self.assertNotEqual(
                focus_effect.observed_at,
                refreshed_target_observation.captured_at,
            )

            post_focus_target_observation = browser.observe_target(
                session.session_id,
                query,
                page_id=observed.page_id,
            )
            self.assertEqual(
                post_focus_target_observation.target.target_id,
                target.target_id,
            )

            click_probe = BrowserAction.create(
                session_id=session.session_id,
                page_id=post_focus_target_observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=post_focus_target_observation.target,
            )
            click_authority = BrowserActionAuthority.from_observation(
                click_probe,
                post_focus_target_observation,
                permission,
            )
            click_effect = browser.act(click_probe, click_authority)
            self.assertFalse(click_effect.success)
            self.assertIn("not implemented", click_effect.error or "")

            toggle_query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value="zn-toggle",
            )
            toggle_observation = browser.observe_target(
                session.session_id,
                toggle_query,
                page_id=observed.page_id,
            )
            self.assertEqual(toggle_observation.target.role, "button")
            self.assertEqual(toggle_observation.target.name, "ZN Toggle")
            toggle_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=toggle_observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=toggle_observation.target,
                expected={"aria_pressed": True},
            )
            toggle_authority = BrowserActionAuthority.from_observation(
                toggle_action,
                toggle_observation,
                permission,
            )
            toggle_effect = browser.act(toggle_action, toggle_authority)
            self.assertTrue(toggle_effect.success, toggle_effect.error)
            self.assertEqual(toggle_effect.postcondition, "same_exact_target_aria_pressed")
            self.assertEqual(toggle_effect.target_id, toggle_observation.target.target_id)
            self.assertTrue(toggle_effect.data["exact_node_continuity"])
            self.assertFalse(toggle_effect.data["aria_pressed_before"])
            self.assertTrue(toggle_effect.data["aria_pressed_after"])
            self.assertNotEqual(toggle_effect.observed_at, toggle_observation.captured_at)

            toggle_back_observation = browser.observe_target(
                session.session_id,
                toggle_query,
                page_id=observed.page_id,
            )
            toggle_back_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=toggle_back_observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=toggle_back_observation.target,
                expected={"aria_pressed": False},
            )
            toggle_back_authority = BrowserActionAuthority.from_observation(
                toggle_back_action,
                toggle_back_observation,
                permission,
            )
            toggle_back_effect = browser.act(toggle_back_action, toggle_back_authority)
            self.assertTrue(toggle_back_effect.success, toggle_back_effect.error)
            self.assertTrue(toggle_back_effect.data["aria_pressed_before"])
            self.assertFalse(toggle_back_effect.data["aria_pressed_after"])
            self.assertTrue(toggle_back_effect.data["exact_node_continuity"])

            toggle_churn_query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value="zn-toggle-churn",
            )
            toggle_churn_observation = browser.observe_target(
                session.session_id,
                toggle_churn_query,
                page_id=observed.page_id,
            )
            toggle_churn_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=toggle_churn_observation.page_id,
                kind=BrowserActionKind.CLICK,
                target=toggle_churn_observation.target,
                expected={"aria_pressed": True},
            )
            toggle_churn_authority = BrowserActionAuthority.from_observation(
                toggle_churn_action,
                toggle_churn_observation,
                permission,
            )
            toggle_churn_effect = browser.act(toggle_churn_action, toggle_churn_authority)
            self.assertFalse(toggle_churn_effect.success)
            self.assertIn("replaced target node", toggle_churn_effect.error or "")
            self.assertFalse(toggle_churn_effect.data["exact_node_continuity"])
            self.assertTrue(toggle_churn_effect.data["aria_pressed_after"])

            churn_query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value="zn-churn",
            )
            churn_observation = browser.observe_target(
                session.session_id,
                churn_query,
                page_id=observed.page_id,
            )
            churn_action = BrowserAction.create(
                session_id=session.session_id,
                page_id=churn_observation.page_id,
                kind=BrowserActionKind.FOCUS,
                target=churn_observation.target,
            )
            churn_authority = BrowserActionAuthority.from_observation(
                churn_action,
                churn_observation,
                permission,
            )
            churn_effect = browser.act(churn_action, churn_authority)
            self.assertFalse(churn_effect.success)
            self.assertIn("replaced target node", churn_effect.error or "")
            self.assertFalse(churn_effect.data["exact_node_continuity"])

            with self.assertRaisesRegex(ManagedBrowserError, "not found"):
                browser.observe_target(
                    session.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="zn-missing",
                    ),
                    page_id=observed.page_id,
                )
            with self.assertRaisesRegex(ManagedBrowserError, "ambiguous"):
                browser.observe_target(
                    session.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="zn-duplicate",
                    ),
                    page_id=observed.page_id,
                )
            with self.assertRaisesRegex(ManagedBrowserError, "not visible"):
                browser.observe_target(
                    session.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="zn-hidden",
                    ),
                    page_id=observed.page_id,
                )
            with self.assertRaisesRegex(ManagedBrowserError, "sensitive-field"):
                browser.observe_target(
                    session.session_id,
                    BrowserTargetQuery(
                        kind=BrowserTargetQueryKind.DOM_ID,
                        value="zn-password",
                    ),
                    page_id=observed.page_id,
                )

            before_second_navigation = browser.observe(
                session.session_id,
                page_id=observed.page_id,
            )
            second = BrowserAction.create(
                session_id=session.session_id,
                page_id=before_second_navigation.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": self.origin + "/next"},
                expected={"url_equals": self.origin + "/next"},
            )
            second_authority = BrowserActionAuthority.from_observation(
                second,
                before_second_navigation,
                permission,
            )
            second_effect = browser.act(second, second_authority)
            self.assertTrue(second_effect.success, second_effect.error)
            self.assertEqual(second_effect.url_after, self.origin + "/next")

            changed_target_observation = browser.observe_target(
                session.session_id,
                query,
                page_id=observed.page_id,
            )
            self.assertEqual(changed_target_observation.target.role, "button")
            self.assertNotEqual(
                changed_target_observation.target.target_id,
                post_focus_target_observation.target.target_id,
            )
            with self.assertRaisesRegex(ValueError, "target changed"):
                BrowserActionAuthority.from_observation(
                    click_probe,
                    changed_target_observation,
                    permission,
                )
        finally:
            browser.close_session(session.session_id)

    def test_metadata_floor_survives_private_network_permission(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=True,
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            current = browser.observe(session.session_id)
            metadata_probe = BrowserAction.create(
                session_id=session.session_id,
                page_id=current.page_id,
                kind=BrowserActionKind.NAVIGATE,
                args={"url": "http://169.254.169.254/latest/meta-data/"},
            )
            metadata_authority = BrowserActionAuthority.from_observation(
                metadata_probe,
                current,
                permission,
            )
            metadata_effect = browser.act(metadata_probe, metadata_authority)
            self.assertFalse(metadata_effect.success)
            self.assertIn("network boundary", metadata_effect.error or "")
            self.assertEqual(
                browser.observe(session.session_id, page_id=current.page_id).url,
                "about:blank",
            )
        finally:
            browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

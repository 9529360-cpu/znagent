from __future__ import annotations

import hashlib
import http.server
import json
import threading
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


_REQUESTED_VALUE = "zn-private-beta-value"
_REQUESTED_DIGEST = hashlib.sha256(_REQUESTED_VALUE.encode("utf-8")).hexdigest()


class _SelectFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            '<select id="zn-select" aria-label="ZN Select">'
            '<option value="alpha" selected>Alpha</option>'
            f'<option value="{_REQUESTED_VALUE}">Beta</option>'
            '</select>'
            '<select id="zn-select-churn" aria-label="ZN Select Churn">'
            '<option value="alpha" selected>Alpha</option>'
            f'<option value="{_REQUESTED_VALUE}">Beta</option>'
            '</select>'
            '<script>'
            "const churn=document.getElementById('zn-select-churn');"
            "churn.addEventListener('input',(event)=>{"
            "const current=event.currentTarget;"
            "const value=current.value;"
            "const replacement=current.cloneNode(true);"
            "replacement.value=value;"
            "current.replaceWith(replacement);"
            "},{once:true});"
            '</script>'
        )
        payload = (
            '<!doctype html><html><head><title>ZN Select Fixture</title></head>'
            f'<body>{body}</body></html>'
        ).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserSelectWindowsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _SelectFixtureHandler)
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _navigate(self, browser, session, permission):
        initial = browser.observe(session.session_id)
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id=initial.page_id,
            kind=BrowserActionKind.NAVIGATE,
            args={'url': self.origin + '/'},
            expected={'url_equals': self.origin + '/'},
        )
        authority = BrowserActionAuthority.from_observation(action, initial, permission)
        effect = browser.act(action, authority)
        self.assertTrue(effect.success, effect.error)
        return initial.page_id

    def test_native_select_requires_fresh_same_node_selected_value_evidence(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            page_id = self._navigate(browser, session, permission)
            query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value='zn-select',
            )
            observed = browser.observe_target(session.session_id, query, page_id=page_id)
            self.assertIsNotNone(observed.target)
            self.assertEqual(observed.target.role, 'combobox')

            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={'value': _REQUESTED_VALUE},
            )
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)

            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, 'same_exact_target_selected_value')
            self.assertEqual(effect.target_id, observed.target.target_id)
            self.assertTrue(effect.data['exact_node_continuity'])
            self.assertTrue(effect.data['selection_dispatched'])
            self.assertEqual(effect.data['expected_value_sha256'], _REQUESTED_DIGEST)
            self.assertEqual(effect.data['selected_value_sha256_after'], _REQUESTED_DIGEST)
            self.assertNotEqual(effect.observed_at, observed.captured_at)
            self.assertNotIn(_REQUESTED_VALUE, json.dumps(effect.data, sort_keys=True))

            refreshed = browser.observe_target(session.session_id, query, page_id=page_id)
            self.assertEqual(refreshed.target.target_id, observed.target.target_id)
        finally:
            browser.close()

    def test_native_select_rejects_same_shape_node_replacement_after_dispatch(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = PlaywrightManagedBrowser()
        session = browser.open_session(permission=permission, headless=True)
        try:
            page_id = self._navigate(browser, session, permission)
            query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value='zn-select-churn',
            )
            observed = browser.observe_target(session.session_id, query, page_id=page_id)
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={'value': _REQUESTED_VALUE},
            )
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)

            self.assertFalse(effect.success)
            self.assertIn('replaced target node', effect.error or '')
            self.assertFalse(effect.data['exact_node_continuity'])
            self.assertEqual(effect.data['selected_value_sha256_after'], _REQUESTED_DIGEST)
            self.assertNotIn(_REQUESTED_VALUE, json.dumps(effect.data, sort_keys=True))
        finally:
            browser.close()


if __name__ == '__main__':
    unittest.main()

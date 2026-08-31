from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from zn_agent.core.user_browser_extension_relay import (
    AuthorizedUserBrowserTab,
    UserBrowserExtensionCommandUncertainError,
)


_START_URL = "https://example.test/account"
_DONE_URL = "https://example.test/results"
_BUTTON = "Search"
_TARGET_ID = "backend:811"


class _ButtonRelay:
    def authorized_tab(self):
        return AuthorizedUserBrowserTab(
            tab_id=81,
            url=_START_URL,
            title="Account",
            attached_at="2026-08-31T00:00:00Z",
        )

    def request_command(self, kind, *, args=None, timeout_seconds=5.0):
        del timeout_seconds
        if kind == "probe_current_tab":
            return {
                "success": True,
                "result": {"tab_id": 81, "url": _START_URL, "title": "Account"},
                "completed_at": "2026-08-31T00:00:01Z",
            }
        if kind == "observe_named_button":
            assert args == {"target_name": _BUTTON}
            return {
                "success": True,
                "result": {
                    "tab_id": 81,
                    "url": _START_URL,
                    "title": "Account",
                    "target_id": _TARGET_ID,
                    "role": "button",
                    "name": _BUTTON,
                },
                "completed_at": "2026-08-31T00:00:02Z",
            }
        if kind == "click_named_button_to_url":
            assert args == {
                "target_name": _BUTTON,
                "target_id": _TARGET_ID,
                "expected_url_before": _START_URL,
                "expected_url_after": _DONE_URL,
            }
            return {
                "success": True,
                "result": {
                    "tab_id": 81,
                    "url_before": _START_URL,
                    "url_after": _DONE_URL,
                    "target_id": _TARGET_ID,
                    "click_sent": True,
                    "exact_node_continuity": True,
                    "target_revalidated_before_dispatch": True,
                    "expected_url": _DONE_URL,
                    "postcondition": "url_equals_after_fresh_semantic_button_click",
                },
                "completed_at": "2026-08-31T00:00:03Z",
            }
        raise AssertionError(f"unexpected command kind: {kind}")


class _LostClickRelay(_ButtonRelay):
    def request_command(self, kind, *, args=None, timeout_seconds=5.0):
        if kind == "click_named_button_to_url":
            raise UserBrowserExtensionCommandUncertainError(
                "browser extension command result was lost after delivery; side effect may have occurred"
            )
        return super().request_command(kind, args=args, timeout_seconds=timeout_seconds)


def _prepared_click(browser: AuthorizedExtensionUserBrowser):
    permission = BrowserPermissionContext(
        allow_navigation=False,
        allow_page_interaction=True,
        allow_text_entry=True,
        allowed_origins=(_START_URL,),
    )
    session = browser.open_session(permission=permission)
    initial = browser.observe(session.session_id)
    observed = browser.observe_target(
        session.session_id,
        BrowserTargetQuery(
            kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
            value=_BUTTON,
        ),
        page_id=initial.page_id,
    )
    action = BrowserAction.create(
        session_id=session.session_id,
        kind=BrowserActionKind.CLICK,
        page_id=observed.page_id,
        target=observed.target,
        expected={"url_equals": _DONE_URL},
    )
    authority = BrowserActionAuthority.from_observation(action, observed, permission)
    return session, action, authority


class AuthorizedExtensionUserBrowserButtonTests(unittest.TestCase):
    def test_exact_button_click_requires_fresh_target_and_final_url_proof(self) -> None:
        browser = AuthorizedExtensionUserBrowser(_ButtonRelay())
        session, action, authority = _prepared_click(browser)

        evidence = browser.act(action, authority)

        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.url_before, _START_URL)
        self.assertEqual(evidence.url_after, _DONE_URL)
        self.assertEqual(evidence.target_id, _TARGET_ID)
        self.assertTrue(evidence.data["click_sent"])
        self.assertTrue(evidence.data["exact_node_continuity"])
        self.assertTrue(evidence.data["target_revalidated_before_dispatch"])
        browser.close_session(session.session_id)

    def test_lost_click_result_blocks_replay_until_fresh_resense(self) -> None:
        browser = AuthorizedExtensionUserBrowser(_LostClickRelay())
        session, action, authority = _prepared_click(browser)

        evidence = browser.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertFalse(evidence.data["click_sent"])
        self.assertTrue(evidence.data["click_may_have_been_sent"])
        self.assertTrue(evidence.data["requires_fresh_resense"])
        self.assertEqual(evidence.data["command_delivery"], "extension_received")
        self.assertIn("side effect may have occurred", str(evidence.error))
        self.assertIn("refusing replay", str(evidence.error))
        browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

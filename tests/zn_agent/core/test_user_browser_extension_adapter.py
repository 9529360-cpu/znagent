from __future__ import annotations

import hashlib
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


_URL = "https://example.test/account"
_TARGET = "Account search"
_TEXT = "alice@example.test"
_TARGET_ID = "backend:701"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _UncertainMutationRelay:
    def authorized_tab(self):
        return AuthorizedUserBrowserTab(
            tab_id=71,
            url=_URL,
            title="Account",
            attached_at="2026-08-31T00:00:00Z",
        )

    def request_command(self, kind, *, args=None, timeout_seconds=5.0):
        del timeout_seconds
        if kind == "probe_current_tab":
            return {
                "success": True,
                "result": {"tab_id": 71, "url": _URL, "title": "Account"},
                "completed_at": "2026-08-31T00:00:01Z",
            }
        if kind == "observe_named_textbox":
            self._expect_target(args)
            return {
                "success": True,
                "result": {
                    "tab_id": 71,
                    "url": _URL,
                    "title": "Account",
                    "target_id": _TARGET_ID,
                    "role": "textbox",
                    "name": _TARGET,
                    "text_length": 0,
                    "text_sha256": _digest(""),
                },
                "completed_at": "2026-08-31T00:00:02Z",
            }
        if kind == "type_named_textbox":
            self._expect_target(args)
            assert args["target_id"] == _TARGET_ID
            assert args["expected_url"] == _URL
            assert args["text"] == _TEXT
            return {
                "success": True,
                "result": {
                    "tab_id": 71,
                    "url_before": _URL,
                    "url_after": _URL,
                    "target_id": _TARGET_ID,
                    "input_sent": True,
                    "exact_node_continuity": True,
                    "text_length_before": 0,
                    "text_sha256_before": _digest(""),
                    "text_length_after": len(_TEXT),
                    "text_sha256_after": _digest("different-final-value"),
                    "expected_text_length": len(_TEXT),
                    "expected_text_sha256": _digest(_TEXT),
                    "expected_utf16_units": len(_TEXT.encode("utf-16-le")) // 2,
                    "postcondition": "",
                },
                "completed_at": "2026-08-31T00:00:03Z",
            }
        raise AssertionError(f"unexpected command kind: {kind}")

    @staticmethod
    def _expect_target(args) -> None:
        assert isinstance(args, dict)
        assert args["target_name"] == _TARGET


class _LostResultMutationRelay(_UncertainMutationRelay):
    def request_command(self, kind, *, args=None, timeout_seconds=5.0):
        if kind == "type_named_textbox":
            self._expect_target(args)
            assert args["target_id"] == _TARGET_ID
            assert args["expected_url"] == _URL
            assert args["text"] == _TEXT
            raise UserBrowserExtensionCommandUncertainError(
                "browser extension command result was lost after delivery; side effect may have occurred"
            )
        return super().request_command(kind, args=args, timeout_seconds=timeout_seconds)


def _prepared_action(browser: AuthorizedExtensionUserBrowser):
    permission = BrowserPermissionContext(
        allow_navigation=False,
        allow_page_interaction=True,
        allow_text_entry=True,
        allowed_origins=(_URL,),
    )
    session = browser.open_session(permission=permission)
    initial = browser.observe(session.session_id)
    observed = browser.observe_target(
        session.session_id,
        BrowserTargetQuery(
            kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
            value=_TARGET,
        ),
        page_id=initial.page_id,
    )
    action = BrowserAction.create(
        session_id=session.session_id,
        kind=BrowserActionKind.TYPE_TEXT,
        page_id=observed.page_id,
        target=observed.target,
        args={"text": _TEXT},
    )
    authority = BrowserActionAuthority.from_observation(action, observed, permission)
    return session, action, authority


class AuthorizedExtensionUserBrowserTests(unittest.TestCase):
    def test_sent_input_without_final_digest_proof_returns_uncertain_failure_evidence(self) -> None:
        browser = AuthorizedExtensionUserBrowser(_UncertainMutationRelay())
        session, action, authority = _prepared_action(browser)

        evidence = browser.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertTrue(evidence.data["input_sent"])
        self.assertTrue(evidence.data["exact_node_continuity"])
        self.assertEqual(evidence.data["expected_text_sha256"], _digest(_TEXT))
        self.assertNotEqual(
            evidence.data["text_sha256_after"],
            evidence.data["expected_text_sha256"],
        )
        self.assertIn("refusing replay", str(evidence.error))
        browser.close_session(session.session_id)

    def test_lost_result_after_command_delivery_requires_fresh_resense_before_replay(self) -> None:
        browser = AuthorizedExtensionUserBrowser(_LostResultMutationRelay())
        session, action, authority = _prepared_action(browser)

        evidence = browser.act(action, authority)

        self.assertFalse(evidence.success)
        self.assertFalse(evidence.data["input_sent"])
        self.assertTrue(evidence.data["input_may_have_been_sent"])
        self.assertTrue(evidence.data["requires_fresh_resense"])
        self.assertEqual(evidence.data["command_delivery"], "extension_received")
        self.assertEqual(evidence.data["expected_text_sha256"], _digest(_TEXT))
        self.assertIn("side effect may have occurred", str(evidence.error))
        self.assertIn("refusing replay", str(evidence.error))
        browser.close_session(session.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

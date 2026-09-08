from __future__ import annotations

from dataclasses import asdict
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.user_browser_causal_popup_adapter import (
    CausalPopupAuthorizedExtensionUserBrowser,
)
from zn_agent.core.user_browser_extension_adapter import ExtensionUserBrowserError
from zn_agent.core.user_browser_extension_relay import (
    AuthorizedUserBrowserTab,
    UserBrowserExtensionCommandUncertainError,
)


_ROOT = "https://example.test/account"
_CHILD = "https://example.test/orders/detail?order=alice%40example.test"
_ANCHOR = "alice@example.test"
_TITLE = "Order alice@example.test — Status: delivered"
_AUTH = "2026-09-08T00:00:00Z"
_BUTTON = "Open order detail"
_TARGET = "backend:811"


def _valid_result() -> dict:
    return {
        "tab_id": 81,
        "url_before": _ROOT,
        "url_after": _ROOT,
        "target_id": _TARGET,
        "click_sent": True,
        "exact_node_continuity": True,
        "target_revalidated_before_dispatch": True,
        "expected_url": _CHILD,
        "task_action_id": "body-e2e07-1",
        "relationship": "causal_child",
        "child_tab_id": 91,
        "opener_tab_id": 81,
        "opener_matches_root": True,
        "fresh_child_identity": True,
        "page_window_open_matches_expected": True,
        "causal_candidate_count": 1,
        "unrelated_created_count": 0,
        "window_open_event_count": 1,
        "child_url": _CHILD,
        "child_title": _TITLE,
        "child_authority_task_scoped": True,
        "child_debugger_detached": True,
        "root_authorization_preserved": True,
        "root_generation_unchanged": True,
        "returned_to_exact_root_tab": True,
        "fresh_root_resense_after_return": True,
        "root_active_after_return": True,
        "root_window_focused_after_return": True,
        "postcondition": "causal_child_verified_and_returned_to_exact_root",
    }


class _CausalRelay:
    def __init__(self, result: dict | None = None) -> None:
        self.result = dict(result or _valid_result())
        self.after_click_tab = 81
        self.after_click_generation = _AUTH
        self.click_seen = False
        self.uncertain = False

    def authorized_tab(self):
        if self.click_seen and self.after_click_tab is None:
            return None
        return AuthorizedUserBrowserTab(
            tab_id=self.after_click_tab if self.click_seen else 81,
            url=_ROOT,
            title="Account",
            attached_at=self.after_click_generation if self.click_seen else _AUTH,
        )

    def request_command(
        self,
        kind,
        *,
        args=None,
        timeout_seconds=5.0,
        expected_tab_id=None,
        expected_attached_at=None,
    ):
        del timeout_seconds
        assert expected_tab_id == 81
        assert expected_attached_at == _AUTH
        if kind == "probe_current_tab":
            return {
                "success": True,
                "result": {"tab_id": 81, "url": _ROOT, "title": "Account"},
                "authorization_attached_at": _AUTH,
                "completed_at": "2026-09-08T00:00:01Z",
            }
        if kind == "observe_named_button":
            assert args == {"target_name": _BUTTON}
            return {
                "success": True,
                "result": {
                    "tab_id": 81,
                    "url": _ROOT,
                    "title": "Account",
                    "target_id": _TARGET,
                    "role": "button",
                    "name": _BUTTON,
                },
                "authorization_attached_at": _AUTH,
                "completed_at": "2026-09-08T00:00:02Z",
            }
        if kind == "click_named_button_to_url":
            assert args == {
                "target_name": _BUTTON,
                "target_id": _TARGET,
                "expected_url_before": _ROOT,
                "expected_url_after": _CHILD,
                "causal_popup_allowed": True,
                "task_action_id": "body-e2e07-1",
            }
            self.click_seen = True
            if self.uncertain:
                raise UserBrowserExtensionCommandUncertainError(
                    "browser extension command result was lost after delivery; side effect may have occurred"
                )
            return {
                "success": True,
                "result": dict(self.result),
                "authorization_attached_at": _AUTH,
                "completed_at": "2026-09-08T00:00:03Z",
            }
        raise AssertionError(kind)


def _prepared(relay: _CausalRelay):
    browser = CausalPopupAuthorizedExtensionUserBrowser(relay)
    permission = BrowserPermissionContext(
        allow_navigation=False,
        allow_page_interaction=True,
        allowed_origins=(_ROOT,),
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
        expected={
            "url_equals": _CHILD,
            "causal_popup_allowed": True,
            "task_action_id": "body-e2e07-1",
        },
    )
    authority = BrowserActionAuthority.from_observation(action, observed, permission)
    return browser, session, action, authority


class CausalPopupAuthorizedExtensionUserBrowserTests(unittest.TestCase):
    def _act(self, relay: _CausalRelay):
        browser, session, action, authority = _prepared(relay)
        return browser, session, action, authority, browser.act(action, authority)

    def test_single_causal_child_succeeds_with_task_scoped_authority(self) -> None:
        browser, session, _action, _authority, evidence = self._act(_CausalRelay())
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.url_before, _ROOT)
        self.assertEqual(evidence.url_after, _ROOT)
        self.assertEqual(evidence.postcondition, "causal_child_verified_and_returned_to_exact_root")
        self.assertTrue(evidence.data["opener_matches_root"])
        self.assertTrue(evidence.data["fresh_child_identity"])
        self.assertTrue(evidence.data["child_authority_task_scoped"])
        self.assertTrue(evidence.data["child_debugger_detached"])
        self.assertTrue(evidence.data["returned_to_exact_root_tab"])
        self.assertEqual(browser.causal_child_result("body-e2e07-1")["child_title"], _TITLE)
        browser.close_session(session.session_id)

    def test_unrelated_user_tab_is_counted_but_never_claimed(self) -> None:
        result = _valid_result()
        result["unrelated_created_count"] = 1
        _browser, _session, _action, _authority, evidence = self._act(_CausalRelay(result))
        self.assertTrue(evidence.success, evidence.error)
        self.assertEqual(evidence.data["causal_candidate_count"], 1)
        self.assertEqual(evidence.data["unrelated_created_count"], 1)
        self.assertEqual(evidence.data["child_tab_id"], 91)

    def test_child_opener_mismatch_fails_closed(self) -> None:
        result = _valid_result()
        result["opener_tab_id"] = 82
        self.assertFalse(self._act(_CausalRelay(result))[-1].success)

    def test_child_url_mismatch_fails_closed(self) -> None:
        result = _valid_result()
        result["child_url"] = "https://example.test/orders/other"
        self.assertFalse(self._act(_CausalRelay(result))[-1].success)

    def test_multiple_causal_children_fail_closed(self) -> None:
        result = _valid_result()
        result["causal_candidate_count"] = 2
        self.assertFalse(self._act(_CausalRelay(result))[-1].success)

    def test_child_closed_before_required_evidence_fails_closed(self) -> None:
        result = _valid_result()
        result["postcondition"] = ""
        result["verification_error"] = "causal child identity disappeared before evidence completed"
        evidence = self._act(_CausalRelay(result))[-1]
        self.assertFalse(evidence.success)
        self.assertIn("disappeared", str(evidence.error))

    def test_root_authorization_generation_change_stops_completion(self) -> None:
        relay = _CausalRelay()
        relay.after_click_generation = "2026-09-08T00:00:04Z"
        evidence = self._act(relay)[-1]
        self.assertFalse(evidence.success)
        self.assertFalse(evidence.data["root_generation_unchanged"])

    def test_root_disappearance_stops_completion(self) -> None:
        relay = _CausalRelay()
        relay.after_click_tab = None
        evidence = self._act(relay)[-1]
        self.assertFalse(evidence.success)
        self.assertFalse(evidence.data["root_authorization_preserved"])

    def test_root_replacement_provider_failure_is_not_reinterpreted_as_success(self) -> None:
        result = _valid_result()
        result["postcondition"] = ""
        result["verification_error"] = "root tab disappeared or was replaced during causal popup action"
        evidence = self._act(_CausalRelay(result))[-1]
        self.assertFalse(evidence.success)
        self.assertIn("replaced", str(evidence.error))

    def test_pre_popup_target_observation_cannot_be_reused(self) -> None:
        browser, _session, action, authority, evidence = self._act(_CausalRelay())
        self.assertTrue(evidence.success, evidence.error)
        with self.assertRaises(ExtensionUserBrowserError):
            browser.act(action, authority)

    def test_child_title_is_transient_result_not_causal_authority(self) -> None:
        result = _valid_result()
        result["child_title"] = "Status: delivered"
        browser, _session, _action, _authority, evidence = self._act(_CausalRelay(result))
        self.assertTrue(evidence.success, evidence.error)
        self.assertNotIn("Status: delivered", repr(asdict(evidence)))
        self.assertEqual(
            browser.causal_child_result("body-e2e07-1")["child_title"],
            "Status: delivered",
        )

    def test_privacy_safe_evidence_contains_no_child_title_or_query_subject(self) -> None:
        evidence = self._act(_CausalRelay())[-1]
        self.assertTrue(evidence.success, evidence.error)
        durable = repr(asdict(evidence))
        self.assertNotIn(_TITLE, durable)
        self.assertNotIn(_ANCHOR, durable)
        self.assertNotIn("order=alice", durable)
        self.assertIn("child_title_sha256", durable)
        self.assertIn("child_url_sha256", durable)

    def test_uncertain_delivery_requires_fresh_resense_and_never_replays(self) -> None:
        relay = _CausalRelay()
        relay.uncertain = True
        browser, _session, _action, _authority, evidence = self._act(relay)
        self.assertFalse(evidence.success)
        self.assertTrue(evidence.data["click_may_have_been_sent"])
        self.assertTrue(evidence.data["requires_fresh_resense"])
        self.assertIsNone(browser.causal_child_result("body-e2e07-1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

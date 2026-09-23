from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.browser_semantic_action import execute_fresh_semantic_action
from zn_agent.core.models import utc_now


class _SemanticRetryBrowser:
    name = "semantic-retry-fixture"
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        first_failure: dict | None = None,
        observed_urls: tuple[str, ...] = ("https://example.test/form",),
    ):
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider=self.name,
            browser_name="chromium",
        )
        self.permission = BrowserPermissionContext(
            allow_page_interaction=True,
            allow_text_entry=True,
        )
        self.first_failure = dict(first_failure or {})
        self.observe_calls = 0
        self.act_calls = 0
        self.last_observation = None
        self.observed_urls = observed_urls

    def observe_target(self, session_id, query, *, page_id=""):
        self.observe_calls += 1
        observed_at = utc_now()
        url = self.observed_urls[min(self.observe_calls - 1, len(self.observed_urls) - 1)]
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or "page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=f"target-{self.observe_calls}",
            observed_at=observed_at,
            url=url,
            frame_id="main",
            role="textbox",
            name=query.value,
            selector_hint="accessible_textbox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=target.page_id,
            captured_at=observed_at,
            url=target.url,
            title="Form",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        authority.validate_current(action, self.last_observation, self.permission)
        if self.act_calls == 1 and self.first_failure:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=action.page_id,
                url_before=self.last_observation.url,
                url_after=self.last_observation.url,
                target_id=action.target.target_id,
                data=dict(self.first_failure),
                error="fixture first action failed",
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=self.last_observation.url,
            url_after=self.last_observation.url,
            target_id=action.target.target_id,
            postcondition="same_exact_target_text_equals_requested",
            data={"input_sent": True},
        )
    def open_session(self, *, permission=None, headless=True):
        raise AssertionError("not used")

    def close_session(self, session_id):
        raise AssertionError("not used")

    def observe(self, session_id, *, page_id=""):
        raise AssertionError("not used")


class BrowserSemanticActionTests(unittest.TestCase):
    def _execute(self, browser, *, max_regrounds=1):
        return execute_fresh_semantic_action(
            browser,
            session_id=browser.identity.session_id,
            permission=browser.permission,
            query=BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                value="Customer",
            ),
            kind=BrowserActionKind.TYPE_TEXT,
            page_id="page-1",
            args={"text": "alice@example.test"},
            expected_url_before="https://example.test/form",
            max_regrounds=max_regrounds,
        )

    def test_pre_dispatch_stale_target_rebinds_once_then_executes(self):
        browser = _SemanticRetryBrowser(
            first_failure={
                "dispatch_state": "not_started",
                "requires_fresh_resense": True,
            }
        )
        result = self._execute(browser)

        self.assertTrue(result.effect.success)
        self.assertEqual(result.regrounds, 1)
        self.assertEqual(browser.observe_calls, 2)
        self.assertEqual(browser.act_calls, 2)
        self.assertEqual(result.observation.target.target_id, "target-2")

    def test_uncertain_or_dispatched_effect_is_never_replayed(self):
        for dispatch_state in ("uncertain", "started"):
            with self.subTest(dispatch_state=dispatch_state):
                browser = _SemanticRetryBrowser(
                    first_failure={
                        "dispatch_state": dispatch_state,
                        "requires_fresh_resense": True,
                    }
                )
                result = self._execute(browser)

                self.assertFalse(result.effect.success)
                self.assertEqual(result.regrounds, 0)
                self.assertEqual(browser.observe_calls, 1)
                self.assertEqual(browser.act_calls, 1)

    def test_rebind_requires_explicit_provider_proof(self):
        browser = _SemanticRetryBrowser(first_failure={"requires_fresh_resense": True})
        result = self._execute(browser)

        self.assertFalse(result.effect.success)
        self.assertEqual(result.regrounds, 0)
        self.assertEqual(browser.observe_calls, 1)
        self.assertEqual(browser.act_calls, 1)

    def test_reground_refuses_same_name_after_page_url_transfer(self):
        browser = _SemanticRetryBrowser(
            first_failure={
                "dispatch_state": "not_started",
                "requires_fresh_resense": True,
            },
            observed_urls=(
                "https://example.test/form",
                "https://example.test/other",
            ),
        )

        with self.assertRaisesRegex(ValueError, "URL changed before dispatch"):
            self._execute(browser)

        self.assertEqual(browser.observe_calls, 2)
        self.assertEqual(browser.act_calls, 1)

    def test_max_regrounds_zero_disables_retry(self):
        browser = _SemanticRetryBrowser(
            first_failure={
                "dispatch_state": "not_started",
                "requires_fresh_resense": True,
            }
        )
        result = self._execute(browser, max_regrounds=0)

        self.assertFalse(result.effect.success)
        self.assertEqual(result.regrounds, 0)
        self.assertEqual(browser.observe_calls, 1)
        self.assertEqual(browser.act_calls, 1)


if __name__ == "__main__":
    unittest.main()

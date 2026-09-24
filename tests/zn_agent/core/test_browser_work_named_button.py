from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQueryKind,
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _FakeNamedButtonBrowser:
    def __init__(self, *, stale_once: bool = False) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-named-button-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.permission = None
        self.last_observation = None
        self.actions = []
        self.queries = []
        self.close_calls = 0
        self.stale_once = stale_once
        self.semantic_attempts = 0

    def open_session(self, *, permission=None, headless=True):
        self.permission = permission
        self.headless = headless
        return self.identity

    def observe(self, session_id: str, *, page_id: str = ""):
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=utc_now(),
            url=self.url,
            title="Done" if self.url.endswith("/done") else "Start",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            raise AssertionError(query.kind)
        if query.value != "Continue":
            raise AssertionError(query.value)
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=f"a11y-continue-{len(self.queries)}",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="button",
            name="Continue",
            selector_hint="accessible_button_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Start",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.actions.append(action.kind)
        assert self.last_observation is not None
        authority.validate_current(action, self.last_observation, self.permission)
        before = self.url
        if action.kind is BrowserActionKind.NAVIGATE:
            self.url = str(action.args["url"])
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=True,
                page_id=action.page_id,
                url_before=before,
                url_after=self.url,
                postcondition="url_equals",
                data={"provider": "fake-named-button-browser"},
            )
        if action.kind is not BrowserActionKind.CLICK:
            raise AssertionError(action.kind)
        self.semantic_attempts += 1
        if self.stale_once and self.semantic_attempts == 1:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=action.page_id,
                url_before=before,
                url_after=self.url,
                target_id=action.target.target_id if action.target else "",
                data={
                    "provider": "fake-named-button-browser",
                    "dispatch_state": "not_started",
                    "requires_fresh_resense": True,
                },
                error="browser target changed before dispatch",
            )
        self.url = str(action.expected["url_equals"])
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=before,
            url_after=self.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="url_equals_after_fresh_semantic_button_click",
            data={
                "provider": "fake-named-button-browser",
                "target_revalidated_before_dispatch": True,
            },
        )

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class BrowserWorkNamedButtonTests(unittest.TestCase):
    def test_structured_named_button_action_is_origin_bounded_and_replay_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedButtonBrowser()
            resident.managed_browser = browser
            args = {
                "url": "https://example.com/start",
                "target_name": "Continue",
                "expected_url": "https://example.com/done",
            }
            try:
                first = resident.body.act(
                    "browser_click_named_button_to_url",
                    event_id="evt-named-button-once",
                    **args,
                )
                self.assertTrue(first.success, first.error)
                self.assertEqual(first.output, "https://example.com/done")
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.CLICK],
                )
                self.assertEqual(len(browser.queries), 1)
                self.assertIs(
                    browser.queries[0].kind,
                    BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                )
                self.assertTrue(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_text_entry)
                self.assertFalse(browser.permission.allow_downloads)
                self.assertFalse(browser.permission.allow_uploads)
                self.assertFalse(browser.permission.allow_sensitive_fields)
                self.assertEqual(
                    browser.permission.allowed_origins,
                    ("https://example.com",),
                )
                self.assertTrue(first.data["target_revalidated_before_dispatch"])
                self.assertEqual(browser.close_calls, 1)

                duplicate = resident.body.act(
                    "browser_click_named_button_to_url",
                    event_id="evt-named-button-once",
                    **args,
                )
                self.assertFalse(duplicate.success)
                self.assertTrue(duplicate.data["side_effect_uncertain"])
                self.assertTrue(duplicate.data["replay_blocked"])
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.CLICK],
                )
                self.assertEqual(browser.close_calls, 1)
            finally:
                resident.store.close()

    def test_named_button_regrounds_same_semantic_target_once_before_click(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedButtonBrowser(stale_once=True)
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_click_named_button_to_url",
                    event_id="evt-named-button-reground",
                    url="https://example.com/start",
                    target_name="Continue",
                    expected_url="https://example.com/done",
                )

                self.assertTrue(result.success, result.error)
                self.assertEqual(result.data["semantic_regrounds"], 1)
                self.assertEqual(len(browser.queries), 2)
                self.assertEqual(browser.semantic_attempts, 2)
                self.assertEqual(
                    browser.actions,
                    [
                        BrowserActionKind.NAVIGATE,
                        BrowserActionKind.CLICK,
                        BrowserActionKind.CLICK,
                    ],
                )
            finally:
                resident.store.close()

    def test_named_button_action_refuses_cross_origin_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedButtonBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_click_named_button_to_url",
                    event_id="evt-named-button-cross-origin",
                    url="https://example.com/start",
                    target_name="Continue",
                    expected_url="https://other.example/done",
                )
                self.assertFalse(result.success)
                self.assertIn("same-origin", result.error or "")
                self.assertEqual(browser.actions, [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

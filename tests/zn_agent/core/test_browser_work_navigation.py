from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPlane,
    BrowserSessionIdentity,
)
from zn_agent.core.browser_work_body import BrowserSideEffectAwareBody
from zn_agent.core.models import WorkingState, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.side_effect_body import SideEffectAwareBody


class _FakeManagedBrowser:
    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.open_calls = 0
        self.observe_calls = 0
        self.act_calls = 0
        self.close_calls = 0
        self.permission = None

    def open_session(self, *, permission=None, headless=True):
        self.open_calls += 1
        self.permission = permission
        self.assert_headless = headless
        return self.identity

    def observe(self, session_id: str, *, page_id: str = ""):
        self.observe_calls += 1
        if session_id != self.identity.session_id:
            raise ValueError("wrong fake browser session")
        return BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=utc_now(),
            url=self.url,
            title="ZN Work Browser" if self.url != "about:blank" else "",
            load_state="complete",
        )

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        current = self.observe(action.session_id, page_id=action.page_id)
        authority.validate_current(action, current, self.permission)
        before = self.url
        self.url = str(action.args["url"])
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=before,
            url_after=self.url,
            postcondition="safe_current_page_observed",
            data={
                "title": "ZN Work Browser",
                "load_state": "complete",
                "provider": "fake-browser",
            },
        )

    def close_session(self, session_id: str) -> None:
        if session_id != self.identity.session_id:
            raise ValueError("wrong fake browser session")
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class BrowserWorkNavigationTests(unittest.TestCase):
    def _resident(self, root: Path):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        fake = _FakeManagedBrowser()
        resident.managed_browser = fake
        return resident, fake

    def test_active_resident_browser_navigation_requires_independent_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, browser = self._resident(Path(tmp))
            try:
                self.assertIsInstance(resident.body, BrowserSideEffectAwareBody)
                self.assertIsInstance(resident.body, SideEffectAwareBody)
                url = "https://example.com/work"
                event = resident.enqueue(
                    "navigate managed browser to the structured URL",
                    payload={
                        "required_capabilities": ["browser"],
                        "expected_outcome": {"kind": "browser_url_equals", "url": url},
                    },
                )
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                intent = NativeActionIntent(
                    intent_id=f"intent-{event.event_id}",
                    event_id=event.event_id,
                    kind="browser_navigate",
                    args={"url": url},
                    source="structured_event",
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_action",
                    next_action="move body: browser_navigate",
                    data={"native_action_intent": intent.to_dict()},
                )
                resident.store.save_working_state(state)

                self.assertIsNone(
                    resident._native_action_step(event, state, readiness=None)
                )
                verification = resident.store.get_working_state()
                self.assertEqual(verification.stage, "native_verification")
                self.assertEqual(
                    verification.data["native_verification"]["kind"],
                    "browser_url_equals",
                )
                action_result = verification.data["native_action_result"]
                self.assertTrue(action_result["success"])
                self.assertTrue(action_result["data"]["side_effect_dispatch_observed"])
                self.assertEqual(browser.open_calls, 1)
                self.assertEqual(browser.act_calls, 1)
                observations_after_dispatch = browser.observe_calls

                result = resident._native_verification_step(
                    event,
                    verification,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.response, "ZN Work Browser")
                self.assertGreater(browser.observe_calls, observations_after_dispatch)
                self.assertEqual(browser.close_calls, 1)
                verified = resident.store.get_working_state().data[
                    "native_verification_result"
                ]
                self.assertTrue(verified["verified"])
                self.assertEqual(verified["observed_url"], url)
                self.assertTrue(browser.permission.allow_navigation)
                self.assertFalse(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_text_entry)
                self.assertFalse(browser.permission.allow_downloads)
                self.assertFalse(browser.permission.allow_uploads)
                self.assertEqual(browser.permission.allowed_origins, ("https://example.com",))
            finally:
                resident.store.close()

    def test_same_browser_navigation_is_not_blindly_replayed_after_observed_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, browser = self._resident(Path(tmp))
            try:
                args = {"url": "https://example.com/once"}
                first = resident.body.act(
                    "browser_navigate",
                    event_id="evt-browser-once",
                    **args,
                )
                self.assertTrue(first.success)
                self.assertEqual(browser.act_calls, 1)

                duplicate = resident.body.act(
                    "browser_navigate",
                    event_id="evt-browser-once",
                    **args,
                )
                self.assertFalse(duplicate.success)
                self.assertTrue(duplicate.data["side_effect_uncertain"])
                self.assertTrue(duplicate.data["replay_blocked"])
                self.assertIn("refusing blind replay", duplicate.error or "")
                self.assertEqual(browser.act_calls, 1)
                browser.close_session(first.data["browser_session_id"])
            finally:
                resident.store.close()

    def test_uncertain_browser_navigation_enters_existing_recovery_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, browser = self._resident(Path(tmp))
            try:
                url = "https://example.com/uncertain"
                event = resident.enqueue(
                    "recover interrupted browser navigation",
                    payload={"required_capabilities": ["browser"]},
                )
                claimed = resident.store.claim_event(event.event_id)
                self.assertIsNotNone(claimed)
                intent = NativeActionIntent(
                    intent_id=f"intent-{event.event_id}",
                    event_id=event.event_id,
                    kind="browser_navigate",
                    args={"url": url},
                    source="structured_event",
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_action",
                    next_action="move body: browser_navigate",
                    data={"native_action_intent": intent.to_dict()},
                )
                resident.store.save_working_state(state)
                signature = resident.body._signature_hash("browser_navigate", {"url": url})
                resident.body._start_attempt(
                    attempt_id="sidefx-browser-seeded",
                    event_id=event.event_id,
                    kind="browser_navigate",
                    signature_hash=signature,
                )

                self.assertIsNone(
                    resident._native_action_step(event, state, readiness=None)
                )
                recovery = resident.store.get_working_state()
                self.assertEqual(recovery.stage, "side_effect_recovery")
                self.assertEqual(recovery.blocked_by, "outside_world_effect_uncertain")
                self.assertTrue(recovery.data["side_effect_recovery"]["replay_blocked"])
                self.assertEqual(
                    recovery.data["side_effect_recovery"]["decision"],
                    "user_decision_required",
                )
                self.assertEqual(browser.open_calls, 0)
                self.assertEqual(browser.act_calls, 0)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

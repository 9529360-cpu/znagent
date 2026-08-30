from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPlane,
    BrowserSessionIdentity,
)
from zn_agent.core.models import AgentEvent, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


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
        self.last_observation = None

    def open_session(self, *, permission=None, headless=True):
        self.open_calls += 1
        self.permission = permission
        return self.identity

    def observe(self, session_id: str, *, page_id: str = ""):
        self.observe_calls += 1
        if session_id != self.identity.session_id:
            raise ValueError("wrong fake browser session")
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=utc_now(),
            url=self.url,
            title="User Entry Browser" if self.url != "about:blank" else "",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        if self.last_observation is None:
            raise AssertionError("browser action requires a prior observation")
        authority.validate_current(action, self.last_observation, self.permission)
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
                "title": "User Entry Browser",
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


class BrowserWorkUserEntryTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-user-entry", task=task)

    def test_natural_navigation_requires_one_explicit_url_and_navigation_cue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_navigation_url(
                        self._event("打开 https://example.com/work。")
                    ),
                    "https://example.com/work",
                )
                self.assertEqual(
                    resident._natural_navigation_url(
                        self._event("please visit https://example.com/docs")
                    ),
                    "https://example.com/docs",
                )
                self.assertIsNone(
                    resident._natural_navigation_url(
                        self._event("explain what https://example.com does")
                    )
                )
                self.assertIsNone(
                    resident._natural_navigation_url(
                        self._event(
                            "open https://example.com or https://example.org"
                        )
                    )
                )
                self.assertIsNone(
                    resident._natural_navigation_url(
                        self._event("open https://user:secret@example.com/private")
                    )
                )
                self.assertEqual(
                    resident._required_capabilities(
                        self._event("visit https://example.com/docs")
                    ),
                    ("browser",),
                )
            finally:
                resident.store.close()

    def test_normal_user_work_navigates_without_hidden_body_action_or_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeManagedBrowser()
            resident.managed_browser = browser
            try:
                result = resident.submit("打开 https://example.com/work")

                self.assertTrue(result.success)
                self.assertEqual(result.response, "User Entry Browser")
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(browser.open_calls, 1)
                self.assertEqual(browser.act_calls, 1)
                self.assertGreaterEqual(browser.observe_calls, 2)
                self.assertEqual(browser.close_calls, 1)
                self.assertTrue(browser.permission.allow_navigation)
                self.assertFalse(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_text_entry)
                self.assertEqual(
                    browser.permission.allowed_origins,
                    ("https://example.com",),
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

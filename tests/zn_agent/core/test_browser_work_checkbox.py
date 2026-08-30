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
)
from zn_agent.core.models import AgentEvent, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class _FakeManagedCheckboxBrowser:
    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-checkbox-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.checked = False
        self.open_calls = 0
        self.observe_calls = 0
        self.observe_target_calls = 0
        self.act_calls = 0
        self.close_calls = 0
        self.permission = None
        self.last_observation = None

    def open_session(self, *, permission=None, headless=True):
        self.open_calls += 1
        self.permission = permission
        self.assert_headless = headless
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
            title="Checkbox Work" if self.url != "about:blank" else "",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.observe_target_calls += 1
        if session_id != self.identity.session_id:
            raise ValueError("wrong fake browser session")
        if query.value != "consent":
            raise ValueError("wrong fake checkbox target")
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ELEMENT,
            target_id="dom-consent",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="checkbox",
            name="Consent",
            selector_hint="dom_id:consent",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Checkbox Work",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        if self.last_observation is None:
            raise AssertionError("browser action requires a prior observation")
        authority.validate_current(action, self.last_observation, self.permission)
        before_url = self.url
        if action.kind is BrowserActionKind.NAVIGATE:
            self.url = str(action.args["url"])
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=True,
                page_id=action.page_id,
                url_before=before_url,
                url_after=self.url,
                postcondition="safe_current_page_observed",
                data={
                    "title": "Checkbox Work",
                    "load_state": "complete",
                    "provider": "fake-checkbox-browser",
                },
            )
        if action.kind not in {BrowserActionKind.CHECK, BrowserActionKind.UNCHECK}:
            raise AssertionError(f"unexpected browser action: {action.kind}")
        before_checked = self.checked
        self.checked = action.kind is BrowserActionKind.CHECK
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=before_url,
            url_after=self.url,
            target_id=action.target.target_id if action.target is not None else "",
            postcondition=(
                "same_exact_target_checked"
                if self.checked
                else "same_exact_target_unchecked"
            ),
            data={
                "provider": "fake-checkbox-browser",
                "exact_node_continuity": True,
                "checked_before": before_checked,
                "checked_after": self.checked,
            },
        )

    def close_session(self, session_id: str) -> None:
        if session_id != self.identity.session_id:
            raise ValueError("wrong fake browser session")
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class BrowserWorkCheckboxTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-checkbox", task=task)

    def test_natural_checkbox_requires_one_url_target_and_unambiguous_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_checkbox_request(
                        self._event("open https://example.com/form and check #consent")
                    ),
                    ("https://example.com/form", "consent", True),
                )
                self.assertEqual(
                    resident._natural_checkbox_request(
                        self._event("打开 https://example.com/form 并取消勾选 #consent")
                    ),
                    ("https://example.com/form", "consent", False),
                )
                self.assertIsNone(
                    resident._natural_checkbox_request(
                        self._event("open https://example.com/form#consent and check it")
                    )
                )
                self.assertIsNone(
                    resident._natural_checkbox_request(
                        self._event(
                            "open https://example.com/form and check #one then uncheck #two"
                        )
                    )
                )
                self.assertIsNone(
                    resident._natural_checkbox_request(
                        self._event("open https://example.com/form and inspect #consent")
                    )
                )
                self.assertEqual(
                    resident._required_capabilities(
                        self._event("打开 https://example.com/form 并勾选 #consent")
                    ),
                    ("browser",),
                )
            finally:
                resident.store.close()

    def test_normal_work_checks_explicit_checkbox_without_model_or_hidden_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeManagedCheckboxBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-checkbox")
                (_, messages), result = ledger.submit(
                    "browser-checkbox",
                    "open https://example.com/form and check #consent",
                )

                self.assertTrue(result.success)
                self.assertEqual(result.response, "checkbox #consent is checked")
                self.assertEqual(result.model_invocations, 0)
                self.assertTrue(
                    any(
                        message.role == "zn"
                        and message.text == "checkbox #consent is checked"
                        for message in messages
                    )
                )
                self.assertTrue(browser.checked)
                self.assertEqual(browser.open_calls, 1)
                self.assertEqual(browser.act_calls, 2)
                self.assertEqual(browser.observe_target_calls, 1)
                self.assertEqual(browser.close_calls, 1)
                self.assertTrue(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_text_entry)
                self.assertFalse(browser.permission.allow_downloads)
                self.assertFalse(browser.permission.allow_uploads)
                self.assertEqual(
                    browser.permission.allowed_origins,
                    ("https://example.com",),
                )
            finally:
                resident.store.close()

    def test_checkbox_mutation_is_not_blindly_replayed_for_same_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeManagedCheckboxBrowser()
            resident.managed_browser = browser
            try:
                args = {
                    "url": "https://example.com/form",
                    "dom_id": "consent",
                    "checked": True,
                }
                first = resident.body.act(
                    "browser_set_checkbox",
                    event_id="evt-checkbox-once",
                    **args,
                )
                self.assertTrue(first.success, first.error)
                self.assertEqual(browser.act_calls, 2)

                duplicate = resident.body.act(
                    "browser_set_checkbox",
                    event_id="evt-checkbox-once",
                    **args,
                )
                self.assertFalse(duplicate.success)
                self.assertTrue(duplicate.data["side_effect_uncertain"])
                self.assertTrue(duplicate.data["replay_blocked"])
                self.assertIn("refusing blind replay", duplicate.error or "")
                self.assertEqual(browser.act_calls, 2)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
from zn_agent.core.models import AgentEvent, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger


class _FakeNamedCheckboxBrowser:
    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-named-checkbox-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.checked = False
        self.permission = None
        self.last_observation = None
        self.queries = []
        self.actions = []
        self.close_calls = 0

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
            title="Named Checkbox Work" if self.url != "about:blank" else "",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            raise AssertionError(f"unexpected query kind: {query.kind}")
        if query.value != "Email updates":
            raise AssertionError(f"unexpected target name: {query.value}")
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="a11y-email-updates",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="checkbox",
            name="Email updates",
            selector_hint="accessible_checkbox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Named Checkbox Work",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.actions.append(action.kind)
        assert self.last_observation is not None
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
                data={"provider": "fake-named-checkbox-browser"},
            )
        if action.kind not in {BrowserActionKind.CHECK, BrowserActionKind.UNCHECK}:
            raise AssertionError(action.kind)
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
            target_id=action.target.target_id if action.target else "",
            postcondition=(
                "same_exact_target_checked" if self.checked else "same_exact_target_unchecked"
            ),
            data={
                "provider": "fake-named-checkbox-browser",
                "exact_node_continuity": True,
                "checked_before": before_checked,
                "checked_after": self.checked,
            },
        )

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class BrowserWorkNamedCheckboxTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-named-checkbox", task=task)

    def test_natural_named_checkbox_requires_exact_quoted_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_named_checkbox_request(
                        self._event(
                            'open https://example.com/settings and check checkbox "Email updates"'
                        )
                    ),
                    ("https://example.com/settings", "Email updates", True),
                )
                self.assertEqual(
                    resident._natural_named_checkbox_request(
                        self._event(
                            "打开 https://example.com/settings 并取消勾选“邮件更新”复选框"
                        )
                    ),
                    ("https://example.com/settings", "邮件更新", False),
                )
                self.assertIsNone(
                    resident._natural_named_checkbox_request(
                        self._event(
                            "open https://example.com/settings and check checkbox Email updates"
                        )
                    )
                )
                self.assertIsNone(
                    resident._natural_named_checkbox_request(
                        self._event(
                            'open https://example.com/settings and check checkbox "One" then "Two"'
                        )
                    )
                )
                ambiguous = self._event(
                    'open https://example.com/settings and check checkbox "One" then "Two"'
                )
                self.assertIsNone(resident._natural_navigation_url(ambiguous))
            finally:
                resident.store.close()

    def test_normal_work_sets_named_checkbox_without_model_or_dom_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedCheckboxBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-named-checkbox")
                (_, messages), result = ledger.submit(
                    "browser-named-checkbox",
                    'open https://example.com/settings and check checkbox "Email updates"',
                )

                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.response, 'checkbox "Email updates" is checked')
                self.assertEqual(result.model_invocations, 0)
                self.assertTrue(browser.checked)
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.CHECK],
                )
                self.assertEqual(len(browser.queries), 1)
                self.assertIs(
                    browser.queries[0].kind,
                    BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
                )
                self.assertEqual(browser.queries[0].value, "Email updates")
                self.assertEqual(browser.close_calls, 1)
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
                self.assertTrue(
                    any(
                        message.role == "zn"
                        and message.text == 'checkbox "Email updates" is checked'
                        for message in messages
                    )
                )
            finally:
                resident.store.close()

    def test_named_checkbox_replay_is_blocked_for_same_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedCheckboxBrowser()
            resident.managed_browser = browser
            try:
                args = {
                    "url": "https://example.com/settings",
                    "target_name": "Email updates",
                    "checked": True,
                }
                first = resident.body.act(
                    "browser_set_named_checkbox",
                    event_id="evt-named-checkbox-once",
                    **args,
                )
                self.assertTrue(first.success, first.error)
                self.assertEqual(len(browser.actions), 2)

                duplicate = resident.body.act(
                    "browser_set_named_checkbox",
                    event_id="evt-named-checkbox-once",
                    **args,
                )
                self.assertFalse(duplicate.success)
                self.assertTrue(duplicate.data["side_effect_uncertain"])
                self.assertTrue(duplicate.data["replay_blocked"])
                self.assertEqual(len(browser.actions), 2)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

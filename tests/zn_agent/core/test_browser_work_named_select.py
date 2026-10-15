from __future__ import annotations

import hashlib
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


class _FakeNamedSelectBrowser:
    plane = BrowserPlane.MANAGED

    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-semantic-select-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.selected_label = "Alpha"
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
            title="Semantic Select Work" if self.url != "about:blank" else "",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME:
            raise AssertionError(query.kind)
        if query.value != "Plan":
            raise AssertionError(query.value)
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="a11y-plan",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="combobox",
            name="Plan",
            selector_hint="accessible_combobox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Semantic Select Work",
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
                data={"provider": "fake-semantic-select-browser"},
            )
        if action.kind is not BrowserActionKind.SELECT_OPTION:
            raise AssertionError(action.kind)
        label = str(action.args.get("label") or "")
        self.selected_label = label
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=before_url,
            url_after=self.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="same_exact_target_selected_label",
            data={
                "provider": "fake-semantic-select-browser",
                "selection_mode": "label",
                "selection_dispatched": True,
                "exact_node_continuity": True,
                "expected_label_length": len(label),
                "expected_label_sha256": digest,
                "selected_label_length_after": len(label),
                "selected_label_sha256_after": digest,
            },
        )

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1


class BrowserWorkNamedSelectTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-named-select", task=task)

    def test_natural_named_select_requires_url_exact_combobox_and_option_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_named_select_request(
                        self._event(
                            'open https://example.com/form and select option "Private Beta" '
                            'from combobox "Plan"'
                        )
                    ),
                    ("https://example.com/form", "Plan", "Private Beta"),
                )
                self.assertEqual(
                    resident._natural_named_select_request(
                        self._event(
                            "打开 https://example.com/form，在下拉框“计划”里选择“测试版”"
                        )
                    ),
                    ("https://example.com/form", "计划", "测试版"),
                )
                ambiguous = self._event(
                    'open https://example.com/form and select option "One" '
                    'from combobox "Plan" then "Two"'
                )
                self.assertIsNone(resident._natural_named_select_request(ambiguous))
                self.assertIsNone(resident._natural_navigation_url(ambiguous))
                missing_quotes = self._event(
                    "open https://example.com/form and select option Private Beta "
                    'from combobox "Plan"'
                )
                self.assertIsNone(
                    resident._natural_named_select_request(missing_quotes)
                )
                self.assertIsNone(resident._natural_navigation_url(missing_quotes))
            finally:
                resident.store.close()

    def test_normal_work_selects_named_option_without_model_or_dom_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedSelectBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-named-select")
                (_, messages), result = ledger.submit(
                    "browser-named-select",
                    'open https://example.com/form and select option "Private Beta" '
                    'from combobox "Plan"',
                )
                self.assertTrue(result.success, result.reason)
                self.assertEqual(
                    result.response,
                    'combobox "Plan" selected option "Private Beta"',
                )
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(browser.selected_label, "Private Beta")
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.SELECT_OPTION],
                )
                self.assertEqual(len(browser.queries), 1)
                self.assertIs(
                    browser.queries[0].kind,
                    BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME,
                )
                self.assertEqual(browser.queries[0].value, "Plan")
                self.assertEqual(browser.close_calls, 1)
                self.assertTrue(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_text_entry)
                self.assertEqual(
                    browser.permission.allowed_origins,
                    ("https://example.com",),
                )
                self.assertTrue(
                    any(
                        message.role == "zn"
                        and message.text
                        == 'combobox "Plan" selected option "Private Beta"'
                        for message in messages
                    )
                )
            finally:
                resident.store.close()

    def test_named_select_replay_is_blocked_for_same_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedSelectBrowser()
            resident.managed_browser = browser
            try:
                args = {
                    "url": "https://example.com/form",
                    "target_name": "Plan",
                    "option_label": "Private Beta",
                }
                first = resident.body.act(
                    "browser_select_named_option",
                    event_id="evt-named-select-once",
                    **args,
                )
                self.assertTrue(first.success, first.error)
                self.assertEqual(len(browser.actions), 2)

                duplicate = resident.body.act(
                    "browser_select_named_option",
                    event_id="evt-named-select-once",
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

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
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


_FORM_TEXT = "ZN form value ✓"
_FORM_DIGEST = hashlib.sha256(_FORM_TEXT.encode("utf-8")).hexdigest()
_START_URL = "https://example.com/form"
_DONE_URL = "https://example.com/done"


class _FakeFormSubmitBrowser:
    plane = BrowserPlane.MANAGED

    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-form-submit-browser",
            browser_name="chromium",
        )
        self.url = "about:blank"
        self.page_id = "page-1"
        self.permission = None
        self.last_observation = None
        self.actions = []
        self.queries = []
        self.close_calls = 0
        self.typed_text = ""

    def open_session(self, *, permission=None, headless=True):
        self.permission = permission
        return self.identity

    def observe(self, session_id: str, *, page_id: str = ""):
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=utc_now(),
            url=self.url,
            title="Form",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        observed_at = utc_now()
        if query.kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            if query.value != "Search":
                raise AssertionError(query.value)
            role = "textbox"
            target_id = "a11y-search"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            if query.value != "Continue":
                raise AssertionError(query.value)
            role = "button"
            target_id = "a11y-continue"
        else:
            raise AssertionError(query.kind)
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=target_id,
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role=role,
            name=query.value,
            selector_hint=f"accessible_{role}_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Form",
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
                data={"provider": "fake-form-submit-browser"},
            )
        if action.kind is BrowserActionKind.TYPE_TEXT:
            text = str(action.args["text"])
            self.typed_text = text
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=True,
                page_id=action.page_id,
                url_before=before,
                url_after=self.url,
                target_id=action.target.target_id if action.target else "",
                postcondition="same_exact_target_text_equals_requested",
                data={
                    "provider": "fake-form-submit-browser",
                    "exact_node_continuity": True,
                    "input_sent": True,
                    "expected_text_length": len(text),
                    "expected_text_sha256": digest,
                    "expected_utf16_units": len(text.encode("utf-16-le")) // 2,
                    "text_length_after": len(text),
                    "text_sha256_after": digest,
                },
            )
        if action.kind is BrowserActionKind.CLICK:
            self.url = str(action.expected.get("url_equals") or _DONE_URL)
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
                    "provider": "fake-form-submit-browser",
                    "target_revalidated_before_dispatch": True,
                },
            )
        raise AssertionError(action.kind)

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _FakeUserFormSubmitBrowser(_FakeFormSubmitBrowser):
    plane = BrowserPlane.USER

    def __init__(self) -> None:
        super().__init__()
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.USER,
            provider="fake-user-form-submit-browser",
            browser_name="chromium",
            profile_scope="user_existing",
        )
        self.url = _START_URL


class BrowserWorkFormSubmitTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-form-submit", task=task)

    def test_natural_form_parser_is_explicit_bilingual_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            try:
                self.assertEqual(
                    resident._natural_form_submit_request(
                        self._event(
                            f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
                            f'then click button "Continue" and expect {_DONE_URL}'
                        )
                    ),
                    (_START_URL, "Search", _FORM_TEXT, "Continue", _DONE_URL),
                )
                self.assertEqual(
                    resident._natural_form_submit_request(
                        self._event(
                            f'打开 {_START_URL}，在输入框“Search”中输入“{_FORM_TEXT}”，'
                            f'点击按钮“Continue”，完成后应到 {_DONE_URL}'
                        )
                    ),
                    (_START_URL, "Search", _FORM_TEXT, "Continue", _DONE_URL),
                )
                malformed = self._event(
                    f'open {_START_URL} and type {_FORM_TEXT} into textbox "Search", '
                    f'then click button "Continue" and expect {_DONE_URL}'
                )
                self.assertIsNone(resident._natural_form_submit_request(malformed))
                self.assertIsNone(resident._natural_navigation_url(malformed))
            finally:
                resident.store.close()

    def test_normal_work_fills_and_submits_in_one_session_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeFormSubmitBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-form-submit")
                (_, messages), result = ledger.submit(
                    "browser-form-submit",
                    f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
                    f'then click button "Continue" and expect {_DONE_URL}',
                )
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(result.response, _DONE_URL)
                self.assertEqual(browser.typed_text, _FORM_TEXT)
                self.assertEqual(
                    browser.actions,
                    [
                        BrowserActionKind.NAVIGATE,
                        BrowserActionKind.TYPE_TEXT,
                        BrowserActionKind.CLICK,
                    ],
                )
                self.assertEqual(
                    [query.kind for query in browser.queries],
                    [
                        BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                        BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                    ],
                )
                self.assertTrue(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_text_entry)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertFalse(browser.permission.allow_sensitive_fields)
                self.assertEqual(browser.close_calls, 1)
                self.assertTrue(any(message.role == "zn" for message in messages))
            finally:
                resident.store.close()

    def test_user_plane_form_uses_current_page_without_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeUserFormSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_click_named_button_to_url",
                    event_id="evt-user-form-submit",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    button_name="Continue",
                    expected_url=_DONE_URL,
                )
                self.assertTrue(result.success, result.error)
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.TYPE_TEXT, BrowserActionKind.CLICK],
                )
                self.assertFalse(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertTrue(browser.permission.allow_text_entry)
                self.assertEqual(result.data["browser_plane"], BrowserPlane.USER.value)
                self.assertFalse(result.data["navigation_performed"])
                self.assertEqual(result.data["url"], _START_URL)
                self.assertEqual(result.data["observed_url"], _DONE_URL)
            finally:
                resident.store.close()

    def test_cross_origin_expected_url_is_rejected_before_browser_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeFormSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_click_named_button_to_url",
                    event_id="evt-cross-origin-form-submit",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    button_name="Continue",
                    expected_url="https://other.example/done",
                )
                self.assertFalse(result.success)
                self.assertIn("same-origin expected_url", str(result.error))
                self.assertEqual(browser.actions, [])
                self.assertIsNone(browser.permission)
            finally:
                resident.store.close()

    def test_body_history_redacts_form_plaintext_and_keeps_bounded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            browser = _FakeFormSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_click_named_button_to_url",
                    event_id="evt-form-submit-once",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    button_name="Continue",
                    expected_url=_DONE_URL,
                )
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.data["expected_text_sha256"], _FORM_DIGEST)
                self.assertEqual(result.data["observed_url"], _DONE_URL)
                with closing(sqlite3.connect(store_path)) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE action_id=?",
                        (result.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertNotIn(_FORM_TEXT, str(row[0]))
                self.assertNotIn(_FORM_TEXT, str(row[1]))
                persisted_action = json.loads(str(row[0]))
                persisted_result = json.loads(str(row[1]))
                self.assertTrue(persisted_action["args"]["text_redacted"])
                self.assertNotIn("text", persisted_action["args"])
                self.assertEqual(
                    persisted_result["data"]["expected_text_sha256"], _FORM_DIGEST
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

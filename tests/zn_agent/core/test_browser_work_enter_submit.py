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
    BrowserPlane,
    BrowserTargetQueryKind,
)
from zn_agent.core.models import AgentEvent, utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger
from tests.zn_agent.core.test_browser_work_form_submit import (
    _DONE_URL,
    _FORM_TEXT,
    _START_URL,
    _FakeFormSubmitBrowser,
    _FakeUserFormSubmitBrowser,
)


_FORM_DIGEST = hashlib.sha256(_FORM_TEXT.encode("utf-8")).hexdigest()


class _FakeEnterSubmitBrowser(_FakeFormSubmitBrowser):
    def act(self, action, authority: BrowserActionAuthority):
        if action.kind is not BrowserActionKind.PRESS:
            return super().act(action, authority)
        self.actions.append(action.kind)
        assert self.last_observation is not None
        authority.validate_current(action, self.last_observation, self.permission)
        before = self.url
        expected_digest = hashlib.sha256(self.typed_text.encode("utf-8")).hexdigest()
        if action.args != {"key": "Enter"}:
            raise AssertionError(action.args)
        if int(action.expected.get("text_length") or -1) != len(self.typed_text):
            raise AssertionError(action.expected)
        if str(action.expected.get("text_sha256") or "") != expected_digest:
            raise AssertionError(action.expected)
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
            postcondition="url_equals_after_fresh_semantic_textbox_enter",
            data={
                "provider": "fake-form-submit-browser",
                "target_revalidated_before_dispatch": True,
                "text_revalidated_before_dispatch": True,
                "press_sent": True,
                "key": "Enter",
                "expected_url": self.url,
                "expected_text_length": len(self.typed_text),
                "expected_text_sha256": expected_digest,
            },
        )


class BrowserWorkEnterSubmitTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-enter-submit", task=task)

    def test_natural_enter_submit_parser_is_explicit_bilingual_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            try:
                self.assertEqual(
                    resident._natural_enter_submit_request(
                        self._event(
                            f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
                            f'then press Enter and expect {_DONE_URL}'
                        )
                    ),
                    (_START_URL, "Search", _FORM_TEXT, _DONE_URL),
                )
                self.assertEqual(
                    resident._natural_enter_submit_request(
                        self._event(
                            f'打开 {_START_URL}，在输入框“Search”中输入“{_FORM_TEXT}”，'
                            f'按下回车键，完成后应到 {_DONE_URL}'
                        )
                    ),
                    (_START_URL, "Search", _FORM_TEXT, _DONE_URL),
                )
                malformed = self._event(
                    f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
                    f'then press Escape and expect {_DONE_URL}'
                )
                self.assertIsNone(resident._natural_enter_submit_request(malformed))
                self.assertIsNone(resident._natural_form_submit_request(malformed))
                self.assertIsNone(resident._natural_navigation_url(malformed))
            finally:
                resident.store.close()

    def test_normal_work_fills_and_submits_with_enter_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeEnterSubmitBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-enter-submit")
                (_, messages), result = ledger.submit(
                    "browser-enter-submit",
                    f'open {_START_URL} and type "{_FORM_TEXT}" into textbox "Search", '
                    f'then press Enter and expect {_DONE_URL}',
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
                        BrowserActionKind.PRESS,
                    ],
                )
                self.assertEqual(
                    [query.kind for query in browser.queries],
                    [
                        BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                        BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
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

    def test_enter_submit_is_rejected_on_user_browser_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeUserFormSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_press_enter_to_url",
                    event_id="evt-user-enter-submit",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    expected_url=_DONE_URL,
                )
                self.assertFalse(result.success)
                self.assertIn("MANAGED-browser only", str(result.error))
                self.assertEqual(browser.actions, [])
                self.assertEqual(browser.typed_text, "")
            finally:
                resident.store.close()

    def test_cross_origin_enter_destination_is_rejected_before_browser_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            browser = _FakeEnterSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_press_enter_to_url",
                    event_id="evt-cross-origin-enter-submit",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    expected_url="https://other.example/done",
                )
                self.assertFalse(result.success)
                self.assertIn("same-origin expected_url", str(result.error))
                self.assertEqual(browser.actions, [])
                self.assertIsNone(browser.permission)
            finally:
                resident.store.close()

    def test_body_history_redacts_enter_submit_plaintext_and_keeps_bounded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            browser = _FakeEnterSubmitBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_fill_named_text_and_press_enter_to_url",
                    event_id="evt-enter-submit-once",
                    url=_START_URL,
                    textbox_name="Search",
                    text=_FORM_TEXT,
                    expected_url=_DONE_URL,
                )
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.data["expected_text_sha256"], _FORM_DIGEST)
                self.assertEqual(result.data["submit_key"], "Enter")
                self.assertTrue(result.data["textbox_revalidated_before_enter"])
                self.assertTrue(result.data["text_revalidated_before_enter"])
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

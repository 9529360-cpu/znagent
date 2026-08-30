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


_TYPED_TEXT = "ZN hello ✓"
_TYPED_DIGEST = hashlib.sha256(_TYPED_TEXT.encode("utf-8")).hexdigest()


class _FakeNamedTextBrowser:
    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-named-text-browser",
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
            title="Text",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            raise AssertionError(query.kind)
        if query.value != "Search":
            raise AssertionError(query.value)
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or self.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="a11y-search",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="textbox",
            name="Search",
            selector_hint="accessible_textbox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Text",
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
                data={"provider": "fake-named-text-browser"},
            )
        if action.kind is not BrowserActionKind.TYPE_TEXT:
            raise AssertionError(action.kind)
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
                "provider": "fake-named-text-browser",
                "exact_node_continuity": True,
                "input_sent": True,
                "text_length_before": 0,
                "text_sha256_before": hashlib.sha256(b"").hexdigest(),
                "text_length_after": len(text),
                "text_sha256_after": digest,
                "expected_text_length": len(text),
                "expected_text_sha256": digest,
                "expected_utf16_units": len(text.encode("utf-16-le")) // 2,
            },
        )

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class BrowserWorkNamedTextTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-natural-text", task=task)

    def test_natural_named_text_parser_is_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_named_text_request(
                        self._event(
                            'open https://example.com/form and type "ZN hello ✓" into textbox "Search"'
                        )
                    ),
                    ("https://example.com/form", "Search", _TYPED_TEXT),
                )
                self.assertEqual(
                    resident._natural_named_text_request(
                        self._event(
                            '打开 https://example.com/form，在输入框“Search”中输入“ZN hello ✓”'
                        )
                    ),
                    ("https://example.com/form", "Search", _TYPED_TEXT),
                )
                malformed = self._event(
                    'open https://example.com/form and type ZN hello into textbox "Search"'
                )
                self.assertIsNone(resident._natural_named_text_request(malformed))
                self.assertIsNone(resident._natural_navigation_url(malformed))
                self.assertIsNone(
                    resident._natural_named_text_request(
                        self._event(
                            'open https://example.com/one https://example.com/two and '
                            'type "ZN hello ✓" into textbox "Search"'
                        )
                    )
                )
            finally:
                resident.store.close()

    def test_normal_work_types_exact_named_text_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedTextBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-natural-text")
                (_, messages), result = ledger.submit(
                    "browser-natural-text",
                    'open https://example.com/form and type "ZN hello ✓" into textbox "Search"',
                )

                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(browser.typed_text, _TYPED_TEXT)
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.TYPE_TEXT],
                )
                self.assertEqual(browser.queries[0].value, "Search")
                self.assertTrue(browser.permission.allow_text_entry)
                self.assertFalse(browser.permission.allow_sensitive_fields)
                self.assertEqual(browser.close_calls, 1)
                self.assertNotIn(_TYPED_TEXT, result.response)
                self.assertTrue(any(message.role == "zn" for message in messages))
            finally:
                resident.store.close()

    def test_body_history_redacts_plaintext_and_blocks_duplicate_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            browser = _FakeNamedTextBrowser()
            resident.managed_browser = browser
            args = {
                "url": "https://example.com/form",
                "target_name": "Search",
                "text": _TYPED_TEXT,
            }
            try:
                first = resident.body.act(
                    "browser_type_named_text",
                    event_id="evt-browser-text-once",
                    **args,
                )
                self.assertTrue(first.success, first.error)
                self.assertEqual(first.data["expected_text_sha256"], _TYPED_DIGEST)
                with closing(sqlite3.connect(store_path)) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE action_id=?",
                        (first.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                persisted_action = json.loads(str(row[0]))
                persisted_result = json.loads(str(row[1]))
                self.assertNotIn(_TYPED_TEXT, str(row[0]))
                self.assertNotIn(_TYPED_TEXT, str(row[1]))
                self.assertTrue(persisted_action["args"]["text_redacted"])
                self.assertNotIn("text", persisted_action["args"])
                self.assertEqual(persisted_result["data"]["expected_text_sha256"], _TYPED_DIGEST)

                duplicate = resident.body.act(
                    "browser_type_named_text",
                    event_id="evt-browser-text-once",
                    **args,
                )
                self.assertFalse(duplicate.success)
                self.assertTrue(duplicate.data["side_effect_uncertain"])
                self.assertTrue(duplicate.data["replay_blocked"])
                self.assertEqual(
                    browser.actions,
                    [BrowserActionKind.NAVIGATE, BrowserActionKind.TYPE_TEXT],
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

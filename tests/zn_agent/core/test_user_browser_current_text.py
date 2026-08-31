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
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime


_URL = "https://example.com/form"
_TEXT = "ZN hello ✓"


class _UserBrowser:
    name = "fake-user-browser"
    plane = BrowserPlane.USER

    def __init__(self, *, url: str = _URL) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.USER,
            provider=self.name,
            browser_name="chromium",
            profile_scope="user_existing",
        )
        self.url = url
        self.page_id = "page-current"
        self.permission = None
        self.last_observation = None
        self.actions = []
        self.queries = []
        self.close_calls = 0
        self.typed_text = ""

    def open_session(self, *, permission=None, headless=False):
        self.permission = permission
        return self.identity

    def observe(self, session_id: str, *, page_id: str = ""):
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=utc_now(),
            url=self.url,
            title="Current user page",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.queries.append(query)
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            raise AssertionError(query.kind)
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
            name=query.value,
            selector_hint="accessible_textbox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or self.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Current user page",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.actions.append(action.kind)
        assert self.last_observation is not None
        authority.validate_current(action, self.last_observation, self.permission)
        if action.kind is BrowserActionKind.NAVIGATE:
            raise AssertionError("USER-plane text entry must not navigate")
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
            url_before=self.url,
            url_after=self.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="same_exact_target_text_equals_requested",
            data={
                "provider": self.name,
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


class UserBrowserCurrentTextTests(unittest.TestCase):
    def test_user_plane_types_on_current_page_without_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _UserBrowser()
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_type_named_text",
                    event_id="evt-user-browser-current-text",
                    url=_URL,
                    target_name="Search",
                    text=_TEXT,
                )
                self.assertTrue(result.success, result.error)
                self.assertEqual(browser.actions, [BrowserActionKind.TYPE_TEXT])
                self.assertEqual(browser.typed_text, _TEXT)
                self.assertFalse(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertTrue(browser.permission.allow_text_entry)
                self.assertEqual(browser.permission.allowed_origins, (_URL,))
                self.assertEqual(result.data["browser_plane"], BrowserPlane.USER.value)
                self.assertTrue(result.data["exact_node_continuity"])
                self.assertTrue(result.data["input_sent"])
                self.assertEqual(browser.close_calls, 1)
            finally:
                resident.store.close()

    def test_user_plane_url_mismatch_stops_before_target_lookup_or_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _UserBrowser(url="https://example.com/other")
            resident.managed_browser = browser
            try:
                result = resident.body.act(
                    "browser_type_named_text",
                    event_id="evt-user-browser-wrong-page",
                    url=_URL,
                    target_name="Search",
                    text=_TEXT,
                )
                self.assertFalse(result.success)
                self.assertEqual(browser.actions, [])
                self.assertEqual(browser.queries, [])
                self.assertEqual(browser.typed_text, "")
                self.assertFalse(result.data["input_sent"])
                self.assertEqual(result.data["current_url"], "https://example.com/other")
                self.assertEqual(browser.close_calls, 1)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
)
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser


_URL = "https://example.test/account"
_TARGET = "Account search"
_TEXT = "alice@example.test"


class _SemanticUserBrowser(AuthorizedCDPUserBrowser):
    def __init__(self):
        super().__init__(endpoint="http://127.0.0.1:9222")
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.USER,
            provider=self.name,
            browser_name="chromium",
            profile_scope="user_existing",
        )
        self.permission = None
        self.last_observation = None
        self.text = ""
        self.actions = []
        self.semantic_state_reads = 0
        self.close_calls = 0

    def open_session(self, *, permission=None, headless=False):
        self.permission = permission
        return self.identity

    def close_session(self, session_id: str) -> None:
        self.close_calls += 1

    def observe(self, session_id: str, *, page_id: str = ""):
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or "page-current",
            captured_at=utc_now(),
            url=_URL,
            title="Account",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def _target_observation(self, *, page_id: str = ""):
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or "page-current",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="semantic-account-search",
            observed_at=observed_at,
            url=_URL,
            frame_id="main",
            role="textbox",
            name=_TARGET,
            selector_hint="accessible_textbox_name:exact",
        )
        observation = BrowserObservation(
            session=self.identity,
            page_id=target.page_id,
            captured_at=observed_at,
            url=_URL,
            title="Account",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def observe_named_text_state(self, session_id: str, target_name: str, *, page_id: str = ""):
        self.semantic_state_reads += 1
        self.assert_target(target_name)
        observation = self._target_observation(page_id=page_id)
        return observation, {
            "text_length": len(self.text),
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
        }

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        self.assert_target(query.value)
        return self._target_observation(page_id=page_id)

    def act(self, action, authority: BrowserActionAuthority):
        self.actions.append(action.kind)
        assert self.last_observation is not None
        authority.validate_current(action, self.last_observation, self.permission)
        if action.kind is not BrowserActionKind.TYPE_TEXT:
            raise AssertionError(f"unexpected USER-plane action: {action.kind}")
        self.text = str(action.args["text"])
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=_URL,
            url_after=_URL,
            target_id=action.target.target_id if action.target else "",
            postcondition="same_exact_target_text_equals_requested",
            data={
                "provider": self.name,
                "exact_node_continuity": True,
                "input_sent": True,
                "text_length_before": 0,
                "text_sha256_before": hashlib.sha256(b"").hexdigest(),
                "text_length_after": len(self.text),
                "text_sha256_after": digest,
                "expected_text_length": len(self.text),
                "expected_text_sha256": digest,
                "expected_utf16_units": len(self.text.encode("utf-16-le")) // 2,
            },
        )

    @staticmethod
    def assert_target(value: str) -> None:
        if value != _TARGET:
            raise AssertionError(value)


class _ForbiddenUIA:
    def probe_exact_edit(self, target_name):
        raise AssertionError("authorized USER browser goal must prefer semantic grounding")


class NaturalSemanticUserBrowserGoalTests(unittest.TestCase):
    def test_typed_browser_goal_uses_semantic_user_bridge_and_resenses_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _SemanticUserBrowser()
            resident.managed_browser = browser
            resident.browser_named_target = _ForbiddenUIA()
            try:
                result = resident.submit(
                    "In my current browser, put alice@example.test in Account search.",
                    payload={
                        "resident_goal": {
                            "kind": "user_browser_named_text",
                            "target_name": _TARGET,
                            "text": _TEXT,
                        },
                        "model_policy": "never",
                    },
                )
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(browser.text, _TEXT)
                self.assertEqual(browser.actions, [BrowserActionKind.TYPE_TEXT])
                self.assertGreaterEqual(browser.semantic_state_reads, 2)
                self.assertFalse(browser.permission.allow_navigation)
                self.assertTrue(browser.permission.allow_page_interaction)
                self.assertTrue(browser.permission.allow_text_entry)
                self.assertGreaterEqual(browser.close_calls, 2)
            finally:
                resident.store.close()

    def test_nonempty_different_semantic_text_stops_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _SemanticUserBrowser()
            browser.text = "existing"
            resident.managed_browser = browser
            resident.browser_named_target = _ForbiddenUIA()
            try:
                result = resident.submit(
                    "In my current browser, put alice@example.test in Account search.",
                    payload={
                        "resident_goal": {
                            "kind": "user_browser_named_text",
                            "target_name": _TARGET,
                            "text": _TEXT,
                        },
                        "model_policy": "never",
                    },
                )
                self.assertFalse(result.success)
                self.assertEqual(browser.actions, [])
                self.assertEqual(browser.text, "existing")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

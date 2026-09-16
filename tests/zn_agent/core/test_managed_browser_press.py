from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from types import SimpleNamespace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.managed_browser_press import PlaywrightBrowserPressMixin
from zn_agent.core.models import utc_now


_START_URL = "https://example.com/form"
_DONE_URL = "https://example.com/done"
_TEXT = "search value"
_DIGEST = hashlib.sha256(_TEXT.encode("utf-8")).hexdigest()


class _Handle:
    def __init__(self, owner) -> None:
        self.owner = owner

    def press(self, key: str) -> None:
        self.owner.press_dispatches += 1
        if self.owner.press_error:
            raise RuntimeError("provider press failed")
        self.owner.page.url = self.owner.submit_url


class _PressAdapter(PlaywrightBrowserPressMixin):
    def __init__(self) -> None:
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-press-browser",
            browser_name="chromium",
        )
        self.permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allowed_origins=(_START_URL,),
        )
        self.page = SimpleNamespace(url=_START_URL)
        self.current_text = _TEXT
        self.submit_url = _DONE_URL
        self.press_dispatches = 0
        self.press_error = False
        self.refresh_calls = 0
        self.revalidate_calls = 0
        self.handle = _Handle(self)
        self.session = SimpleNamespace(
            identity=identity,
            permission=self.permission,
            last_observation={},
        )
        captured_at = utc_now()
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="a11y-search",
            observed_at=captured_at,
            url=_START_URL,
            frame_id="main",
            role="textbox",
            name="Search",
            selector_hint="accessible_textbox_name:exact",
        )
        self.observation = BrowserObservation(
            session=identity,
            page_id="page-1",
            captured_at=captured_at,
            url=_START_URL,
            title="Form",
            load_state="complete",
            target=self.target,
        )
        self.session.last_observation["page-1"] = self.observation

    def _session(self, session_id: str):
        if session_id != self.session.identity.session_id:
            raise RuntimeError("unknown session")
        return self.session

    def _validate_authority(self, session, action, authority) -> None:
        authority.validate_current(
            action,
            session.last_observation[action.page_id],
            session.permission,
        )

    def _require_url_allowed(self, url: str, permission) -> None:
        if not url.startswith("https://example.com/"):
            raise RuntimeError("URL is not allowed")

    def _default_page_id(self, session) -> str:
        return "page-1"

    def _page(self, session, page_id: str):
        return self.page

    def _revalidate_target_binding(self, session, page_id: str, target):
        self.revalidate_calls += 1
        if target != self.target:
            raise RuntimeError("target changed")
        return SimpleNamespace(handle=self.handle)

    def _read_target_text_state(self, handle):
        return {
            "text_length": len(self.current_text),
            "text_sha256": hashlib.sha256(self.current_text.encode("utf-8")).hexdigest(),
        }

    def _capture(self, session, page_id: str, *, captured_at: str):
        return BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=captured_at,
            url=self.page.url,
            title="Result",
            load_state="complete",
        )

    def _refresh_page_observation_after_failed_mutation(self, session, page_id: str) -> None:
        self.refresh_calls += 1

    def _failure(self, action, *, error: str):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            error=error,
        )


def _action(adapter: _PressAdapter, *, key: str = "Enter") -> tuple[BrowserAction, BrowserActionAuthority]:
    action = BrowserAction.create(
        session_id=adapter.session.identity.session_id,
        kind=BrowserActionKind.PRESS,
        page_id="page-1",
        target=adapter.target,
        args={"key": key},
        expected={
            "url_equals": _DONE_URL,
            "text_length": len(_TEXT),
            "text_sha256": _DIGEST,
        },
    )
    authority = BrowserActionAuthority.from_observation(
        action,
        adapter.observation,
        adapter.permission,
    )
    return action, authority


class ManagedBrowserPressTests(unittest.TestCase):
    def test_enter_press_succeeds_only_after_fresh_target_and_text_revalidation(self) -> None:
        adapter = _PressAdapter()
        action, authority = _action(adapter)

        effect = adapter.act(action, authority)

        self.assertTrue(effect.success, effect.error)
        self.assertEqual(effect.url_before, _START_URL)
        self.assertEqual(effect.url_after, _DONE_URL)
        self.assertEqual(effect.postcondition, "url_equals_after_fresh_semantic_textbox_enter")
        self.assertEqual(adapter.press_dispatches, 1)
        self.assertEqual(adapter.revalidate_calls, 1)
        self.assertTrue(effect.data["target_revalidated_before_dispatch"])
        self.assertTrue(effect.data["text_revalidated_before_dispatch"])
        self.assertTrue(effect.data["press_sent"])
        self.assertEqual(effect.data["key"], "Enter")
        self.assertEqual(effect.data["expected_text_sha256"], _DIGEST)

    def test_press_rejects_user_browser_plane_before_dispatch(self) -> None:
        adapter = _PressAdapter()
        user_identity = replace(adapter.session.identity, plane=BrowserPlane.USER)
        adapter.session.identity = user_identity
        adapter.target = replace(adapter.target, session_id=user_identity.session_id)
        adapter.observation = replace(
            adapter.observation,
            session=user_identity,
            target=adapter.target,
        )
        adapter.session.last_observation["page-1"] = adapter.observation
        action, authority = _action(adapter)

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("MANAGED Browser", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 0)
        self.assertEqual(adapter.revalidate_calls, 0)

    def test_press_rejects_every_key_except_exact_enter_before_dispatch(self) -> None:
        adapter = _PressAdapter()
        action, authority = _action(adapter, key="Control+Enter")

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("exactly the Enter key", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 0)
        self.assertEqual(adapter.revalidate_calls, 0)

    def test_press_fails_closed_if_text_drifted_before_dispatch(self) -> None:
        adapter = _PressAdapter()
        action, authority = _action(adapter)
        adapter.current_text = "user changed it"

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("content changed before dispatch", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 0)
        self.assertEqual(adapter.revalidate_calls, 1)

    def test_press_reports_wrong_destination_without_replaying(self) -> None:
        adapter = _PressAdapter()
        action, authority = _action(adapter)
        adapter.submit_url = "https://example.com/wrong"

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("postcondition did not match", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 1)
        self.assertEqual(effect.data["press_sent"], True)

    def test_press_refuses_when_expected_destination_is_already_current(self) -> None:
        adapter = _PressAdapter()
        adapter.page.url = _DONE_URL
        adapter.observation = BrowserObservation(
            session=adapter.session.identity,
            page_id="page-1",
            captured_at=adapter.target.observed_at,
            url=_DONE_URL,
            title="Done",
            load_state="complete",
            target=adapter.target,
        )
        adapter.session.last_observation["page-1"] = adapter.observation
        action, authority = _action(adapter)

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("already observed", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

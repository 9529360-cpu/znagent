from __future__ import annotations

import unittest

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


class BrowserContractTests(unittest.TestCase):
    def test_managed_session_defaults_to_ephemeral_profile(self):
        session = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="playwright",
            browser_name="chromium",
        )
        self.assertEqual(session.profile_scope, "ephemeral")
        self.assertTrue(session.session_id.startswith("browser-"))

    def test_user_session_cannot_claim_managed_profile(self):
        with self.assertRaises(ValueError):
            BrowserSessionIdentity(
                session_id="user-1",
                plane=BrowserPlane.USER,
                provider="uia",
                profile_scope="ephemeral",
            )

    def test_managed_session_cannot_claim_existing_user_profile(self):
        with self.assertRaises(ValueError):
            BrowserSessionIdentity(
                session_id="managed-1",
                plane=BrowserPlane.MANAGED,
                provider="playwright",
                profile_scope="user_existing",
            )

    def test_allowed_origins_are_normalized_and_scoped(self):
        permission = BrowserPermissionContext(
            allowed_origins=("HTTPS://Example.COM:443/path", "http://example.net:8080/a"),
        )
        self.assertEqual(
            permission.allowed_origins,
            ("https://example.com", "http://example.net:8080"),
        )
        self.assertTrue(permission.allows_origin("https://example.com/ok"))
        self.assertFalse(permission.allows_origin("https://other.example/"))

    def test_duplicate_allowed_origins_fail_closed_after_normalization(self):
        with self.assertRaises(ValueError):
            BrowserPermissionContext(
                allowed_origins=("https://example.com", "https://EXAMPLE.com:443/path"),
            )

    def test_invalid_origin_port_fails_closed(self):
        with self.assertRaises(ValueError):
            BrowserPermissionContext(allowed_origins=("https://example.com:bad",))

    def test_action_permissions_default_deny_side_effects(self):
        permission = BrowserPermissionContext()
        self.assertFalse(permission.allows_action(BrowserActionKind.NAVIGATE))
        self.assertFalse(permission.allows_action(BrowserActionKind.CLICK))
        self.assertFalse(permission.allows_action(BrowserActionKind.TYPE_TEXT))
        self.assertTrue(permission.allows_action(BrowserActionKind.WAIT))
        self.assertFalse(
            BrowserPermissionContext(allow_text_entry=True).allows_action(
                BrowserActionKind.TYPE_TEXT
            )
        )
        self.assertTrue(
            BrowserPermissionContext(
                allow_page_interaction=True,
                allow_text_entry=True,
            ).allows_action(BrowserActionKind.TYPE_TEXT)
        )

    def _target_observation(self):
        session = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="playwright",
        )
        target = BrowserTarget(
            session_id=session.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ELEMENT,
            target_id="element-1",
            observed_at="2026-08-26T00:00:00+00:00",
            url="https://example.com/",
            frame_id="frame-main",
            role="textbox",
        )
        observation = BrowserObservation(
            session=session,
            page_id="page-1",
            captured_at="2026-08-26T00:00:01+00:00",
            url="https://example.com/",
            title="Example",
            load_state="complete",
            target=target,
        )
        return session, target, observation

    def test_action_authority_binds_to_current_session_page_and_target(self):
        session, target, observation = self._target_observation()
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id="page-1",
            kind=BrowserActionKind.FOCUS,
            target=target,
        )
        authority = BrowserActionAuthority.from_observation(
            action,
            observation,
            BrowserPermissionContext(allow_page_interaction=True),
        )
        self.assertEqual(authority.action_id, action.action_id)
        self.assertEqual(authority.session_id, session.session_id)
        self.assertEqual(authority.page_id, "page-1")
        self.assertEqual(authority.target_id, "element-1")
        self.assertEqual(authority.observation_captured_at, observation.captured_at)

    def test_default_permission_refuses_navigation_authority(self):
        session, _target, observation = self._target_observation()
        page_observation = BrowserObservation(
            session=session,
            page_id=observation.page_id,
            captured_at=observation.captured_at,
            url=observation.url,
            title=observation.title,
            load_state=observation.load_state,
        )
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=BrowserActionKind.NAVIGATE,
            args={"url": "https://example.com/next"},
        )
        with self.assertRaisesRegex(ValueError, "not permitted"):
            BrowserActionAuthority.from_observation(
                action,
                page_observation,
                BrowserPermissionContext(),
            )

    def test_target_action_requires_current_target_observation(self):
        session, target, observation = self._target_observation()
        observation_without_target = BrowserObservation(
            session=session,
            page_id=observation.page_id,
            captured_at=observation.captured_at,
            url=observation.url,
            title=observation.title,
            load_state=observation.load_state,
        )
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=BrowserActionKind.CLICK,
            target=target,
        )
        with self.assertRaises(ValueError):
            BrowserActionAuthority.from_observation(
                action,
                observation_without_target,
                BrowserPermissionContext(allow_page_interaction=True),
            )

    def test_target_action_rejects_kind_or_frame_drift(self):
        session, target, observation = self._target_observation()
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=BrowserActionKind.CLICK,
            target=target,
        )
        permission = BrowserPermissionContext(allow_page_interaction=True)
        kind_drift = BrowserTarget(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=target.target_id,
            observed_at=target.observed_at,
            frame_id=target.frame_id,
        )
        with self.assertRaises(ValueError):
            BrowserActionAuthority.from_observation(
                action,
                BrowserObservation(
                    session=session,
                    page_id=observation.page_id,
                    captured_at=observation.captured_at,
                    url=observation.url,
                    title=observation.title,
                    load_state=observation.load_state,
                    target=kind_drift,
                ),
                permission,
            )
        frame_drift = BrowserTarget(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=target.kind,
            target_id=target.target_id,
            observed_at=target.observed_at,
            frame_id="frame-other",
        )
        with self.assertRaises(ValueError):
            BrowserActionAuthority.from_observation(
                action,
                BrowserObservation(
                    session=session,
                    page_id=observation.page_id,
                    captured_at=observation.captured_at,
                    url=observation.url,
                    title=observation.title,
                    load_state=observation.load_state,
                    target=frame_drift,
                ),
                permission,
            )

    def test_target_action_rejects_reused_id_with_stale_target_evidence(self):
        session, target, observation = self._target_observation()
        action = BrowserAction.create(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=BrowserActionKind.CLICK,
            target=target,
        )
        refreshed_target = BrowserTarget(
            session_id=session.session_id,
            page_id=observation.page_id,
            kind=target.kind,
            target_id=target.target_id,
            observed_at="2026-08-26T00:00:02+00:00",
            url=target.url,
            frame_id=target.frame_id,
            role=target.role,
        )
        refreshed = BrowserObservation(
            session=session,
            page_id=observation.page_id,
            captured_at="2026-08-26T00:00:03+00:00",
            url=observation.url,
            title=observation.title,
            load_state=observation.load_state,
            target=refreshed_target,
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            BrowserActionAuthority.from_observation(
                action,
                refreshed,
                BrowserPermissionContext(allow_page_interaction=True),
            )

    def test_cross_session_target_is_rejected(self):
        target = BrowserTarget(
            session_id="session-a",
            page_id="page-1",
            kind=BrowserTargetKind.ELEMENT,
            target_id="element-1",
            observed_at="now",
        )
        with self.assertRaises(ValueError):
            BrowserAction.create(
                session_id="session-b",
                page_id="page-1",
                kind=BrowserActionKind.CLICK,
                target=target,
            )

    def test_success_and_failure_evidence_are_unambiguous(self):
        success = BrowserEffectEvidence(
            action_id="action-1",
            session_id="session-1",
            observed_at="now",
            success=True,
            postcondition="url_changed",
        )
        self.assertIsNone(success.error)

        failure = BrowserEffectEvidence(
            action_id="action-2",
            session_id="session-1",
            observed_at="now",
            success=False,
            error="target became stale",
        )
        self.assertFalse(failure.success)

        with self.assertRaises(ValueError):
            BrowserEffectEvidence(
                action_id="action-3",
                session_id="session-1",
                observed_at="now",
                success=False,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

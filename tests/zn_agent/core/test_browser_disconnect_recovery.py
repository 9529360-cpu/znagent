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
    BrowserProviderDisconnectedError,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.browser_disconnect_recovery import (
    BrowserSessionRecoveryError,
    is_provider_disconnect,
    recover_browser_session_after_disconnect,
)
from zn_agent.core.browser_loop import execute_browser_loop_step
from zn_agent.core.models import utc_now


FORM_URL = "https://example.test/form"
OTHER_URL = "https://example.test/other"


def _permission(**overrides):
    values = {
        "allow_navigation": True,
        "allow_page_interaction": True,
        "allow_text_entry": True,
    }
    values.update(overrides)
    return BrowserPermissionContext(**values)


class _DisconnectFakeBrowser:
    """Mock managed provider with scriptable disconnects and a full act log."""

    name = "disconnect-fixture"
    plane = BrowserPlane.MANAGED

    def __init__(self, *, permission=None):
        self.permission = permission or _permission()
        self.url = FORM_URL
        self.identity = None
        self.open_calls = 0
        self.observe_calls = 0
        self.observe_target_calls = 0
        self.act_log: list[tuple[BrowserActionKind, str, dict]] = []
        self.closed_sessions: list[str] = []
        self.last_observation = None
        # Disconnect / failure scripting.
        self.disconnect_on_observe = False
        # Raise a disconnect on the next N observe_target calls, then behave
        # normally again (models a transient provider outage).
        self.disconnect_observe_target_times = 0
        self.fail_open_with: BaseException | None = None
        self.fail_observe_target_with: BaseException | None = None
        self.fail_navigate_effect = False

    def open_session(self, *, permission=None, headless=True, owner=None):
        self.open_calls += 1
        if self.fail_open_with is not None:
            raise self.fail_open_with
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider=self.name,
            browser_name="chromium",
        )
        return self.identity

    def close_session(self, session_id):
        self.closed_sessions.append(str(session_id))

    def _observation(self, *, page_id="", target=None):
        return BrowserObservation(
            session=self.identity,
            page_id=page_id or "page-1",
            captured_at=utc_now(),
            url=self.url,
            title="Form",
            load_state="complete",
            target=target,
        )

    def observe(self, session_id, *, page_id=""):
        self.observe_calls += 1
        if self.disconnect_on_observe:
            raise BrowserProviderDisconnectedError(
                "fixture: provider connection dropped"
            )
        observation = self._observation(page_id=page_id)
        self.last_observation = observation
        return observation

    def observe_target(self, session_id, query, *, page_id=""):
        self.observe_target_calls += 1
        if self.disconnect_observe_target_times > 0:
            self.disconnect_observe_target_times -= 1
            raise BrowserProviderDisconnectedError(
                "fixture: provider connection dropped"
            )
        if self.fail_observe_target_with is not None:
            raise self.fail_observe_target_with
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=page_id or "page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=f"target-{self.observe_target_calls}",
            observed_at=observed_at,
            url=self.url,
            frame_id="main",
            role="button",
            name=query.value,
            selector_hint="accessible_button_name:exact",
        )
        observation = self._observation(page_id=page_id, target=target)
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        authority.validate_current(action, self.last_observation, self.permission)
        self.act_log.append((action.kind, action.session_id, dict(action.args)))
        url_before = self.url
        if action.kind is BrowserActionKind.NAVIGATE:
            if self.fail_navigate_effect:
                return BrowserEffectEvidence(
                    action_id=action.action_id,
                    session_id=action.session_id,
                    observed_at=utc_now(),
                    success=False,
                    page_id=action.page_id,
                    url_before=url_before,
                    url_after=url_before,
                    error="fixture: re-navigation rejected",
                )
            self.url = str(action.args.get("url") or self.url)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=True,
                page_id=action.page_id,
                url_before=url_before,
                url_after=self.url,
                postcondition="safe_current_page_observed",
            )
        # Any side-effect kind the fixture understands.
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=url_before,
            url_after=self.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="fixture side effect applied",
        )


def _old_session(*, url=FORM_URL, session_id="session-old"):
    return {
        "session_id": session_id,
        "url": url,
        "page_id": "page-1",
        "last_observation": {
            "url": url,
            "title": "Form",
            "load_state": "complete",
            "page_id": "page-1",
        },
    }


class DisconnectDetectionTests(unittest.TestCase):
    def test_explicit_disconnect_error_is_detected(self):
        self.assertTrue(
            is_provider_disconnect(BrowserProviderDisconnectedError("gone"))
        )

    def test_transport_connection_error_is_detected(self):
        self.assertTrue(is_provider_disconnect(ConnectionError("reset by peer")))
        self.assertTrue(is_provider_disconnect(ConnectionResetError("reset")))

    def test_browser_closed_messages_are_detected(self):
        self.assertTrue(is_provider_disconnect(RuntimeError("Browser has been closed")))
        self.assertTrue(
            is_provider_disconnect(RuntimeError("unknown managed browser session"))
        )
        self.assertTrue(
            is_provider_disconnect(RuntimeError("Target crashed, navigating"))
        )

    def test_validation_and_generic_errors_are_not_disconnects(self):
        self.assertFalse(is_provider_disconnect(ValueError("browser navigation requires url")))
        self.assertFalse(is_provider_disconnect(RuntimeError("browser click requires a current target")))
        self.assertFalse(is_provider_disconnect(RuntimeError("")))
        self.assertFalse(is_provider_disconnect(TimeoutError("navigation timed out")))


class RecoveryHappyPathTests(unittest.TestCase):
    def test_recovery_reopens_renavigates_and_matches_last_verified_url(self):
        browser = _DisconnectFakeBrowser()
        permission = browser.permission
        session = _old_session()

        recovered = recover_browser_session_after_disconnect(
            browser,
            session=session,
            permission=permission,
        )

        self.assertEqual(recovered.recovered_url, FORM_URL)
        self.assertEqual(recovered.session["url"], FORM_URL)
        self.assertEqual(browser.open_calls, 1)
        # Rebuilt session is a NEW session, not the dead one.
        self.assertNotEqual(recovered.session["session_id"], "session-old")
        self.assertEqual(recovered.previous_session_id, "session-old")
        self.assertTrue(recovered.session["recovered_from_disconnect"])
        # The dead session was closed best-effort.
        self.assertIn("session-old", browser.closed_sessions)

    def test_recovery_dispatches_only_navigate_never_replays_side_effects(self):
        browser = _DisconnectFakeBrowser()
        permission = browser.permission
        session = _old_session()

        # Simulate a side-effect action dispatched on the old session before
        # the disconnect: the provider log already contains a CLICK.
        browser.open_session(permission=permission)
        browser.observe(browser.identity.session_id)

        old_target = browser.observe_target(
            browser.identity.session_id,
            BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME, value="Submit"
            ),
        ).target
        click = BrowserAction.create(
            session_id=browser.identity.session_id,
            kind=BrowserActionKind.CLICK,
            page_id="page-1",
            target=old_target,
            args={},
            expected={"aria_pressed": True},
        )
        browser.act(
            click,
            BrowserActionAuthority.from_observation(click, browser.last_observation, permission),
        )
        clicks_before = [
            entry for entry in browser.act_log if entry[0] is BrowserActionKind.CLICK
        ]
        self.assertEqual(len(clicks_before), 1)

        recovered = recover_browser_session_after_disconnect(
            browser,
            session=session,
            permission=permission,
            dispatched_side_effect_action_ids=("proposal-click-1",),
        )

        kinds_after = [entry[0] for entry in browser.act_log]
        self.assertEqual(
            kinds_after.count(BrowserActionKind.NAVIGATE),
            1,
            f"recovery must dispatch exactly one NAVIGATE, got {kinds_after}",
        )
        self.assertEqual(
            kinds_after.count(BrowserActionKind.CLICK),
            1,
            "the pre-disconnect CLICK must not be replayed",
        )
        # The dispatched side-effect journal is carried over untouched so the
        # caller never re-proposes it.
        self.assertEqual(
            recovered.dispatched_side_effect_action_ids, ("proposal-click-1",)
        )
        self.assertEqual(
            recovered.session["dispatched_side_effect_action_ids"], ("proposal-click-1",)
        )

    def test_recovery_reresolves_in_flight_target_query(self):
        browser = _DisconnectFakeBrowser()
        permission = browser.permission
        session = _old_session()

        recovered = recover_browser_session_after_disconnect(
            browser,
            session=session,
            permission=permission,
            target_query=BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME, value="Submit"
            ),
        )

        self.assertTrue(recovered.target_reresolved)
        self.assertEqual(browser.observe_target_calls, 1)
        self.assertIn("re-resolved", recovered.target_reresolve_detail)

    def test_recovery_succeeds_when_target_no_longer_resolves(self):
        browser = _DisconnectFakeBrowser()
        browser.fail_observe_target_with = RuntimeError("no such target on rebuilt page")
        permission = browser.permission
        session = _old_session()

        recovered = recover_browser_session_after_disconnect(
            browser,
            session=session,
            permission=permission,
            target_query=BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME, value="Gone"
            ),
        )

        # The session is healthy (URL pin holds); only the target evidence is
        # negative, for the caller's preconditions to judge.
        self.assertFalse(recovered.target_reresolved)
        self.assertEqual(recovered.session["url"], FORM_URL)
        self.assertIn("could not be re-resolved", recovered.target_reresolve_detail)

    def test_recovery_carries_multipage_context(self):
        browser = _DisconnectFakeBrowser()
        permission = browser.permission
        session = _old_session()
        session["multipage_context"] = {"pages": ["a"]}

        recovered = recover_browser_session_after_disconnect(
            browser,
            session=session,
            permission=permission,
        )
        self.assertEqual(recovered.session["multipage_context"], {"pages": ["a"]})


class RecoveryFailureTests(unittest.TestCase):
    def test_recovery_refuses_without_url_pin(self):
        browser = _DisconnectFakeBrowser()
        with self.assertRaises(BrowserSessionRecoveryError) as ctx:
            recover_browser_session_after_disconnect(
                browser,
                session={"session_id": "session-old"},
                permission=browser.permission,
            )
        self.assertIn("no last verified URL pin", str(ctx.exception))
        self.assertEqual(browser.open_calls, 0)

    def test_recovery_refuses_when_navigation_not_permitted(self):
        browser = _DisconnectFakeBrowser()
        permission = _permission(allow_navigation=False)
        with self.assertRaises(BrowserSessionRecoveryError) as ctx:
            recover_browser_session_after_disconnect(
                browser,
                session=_old_session(),
                permission=permission,
            )
        self.assertIn("does not allow navigation", str(ctx.exception))
        self.assertEqual(browser.open_calls, 0)

    def test_recovery_fails_explicitly_when_provider_cannot_reopen(self):
        browser = _DisconnectFakeBrowser()
        browser.fail_open_with = RuntimeError("chromium binary missing")
        with self.assertRaises(BrowserSessionRecoveryError) as ctx:
            recover_browser_session_after_disconnect(
                browser,
                session=_old_session(),
                permission=browser.permission,
            )
        self.assertIn("could not reopen", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_recovery_fails_explicitly_when_renavigation_does_not_verify(self):
        browser = _DisconnectFakeBrowser()
        browser.fail_navigate_effect = True
        with self.assertRaises(BrowserSessionRecoveryError) as ctx:
            recover_browser_session_after_disconnect(
                browser,
                session=_old_session(),
                permission=browser.permission,
            )
        self.assertIn("re-navigation", str(ctx.exception))
        # The half-opened session is cleaned up, not leaked.
        new_ids = [
            closed
            for closed in browser.closed_sessions
            if closed != "session-old"
        ]
        self.assertEqual(len(new_ids), 1)

    def test_recovery_fails_explicitly_when_observation_diverges_from_pin(self):
        browser = _DisconnectFakeBrowser()
        permission = browser.permission
        session = _old_session()
        # Provider "recovers" but lands somewhere else: must not fake success.
        original_observe = browser.observe

        def diverging_observe(session_id, *, page_id=""):
            original_observe(session_id, page_id=page_id)
            # The provider "recovers" the navigation but its fresh
            # observation disagrees with the pin: recovery must not fake it.
            browser.url = OTHER_URL
            divergent = browser._observation(page_id=page_id)
            browser.last_observation = divergent
            return divergent

        browser.observe = diverging_observe
        with self.assertRaises(BrowserSessionRecoveryError) as ctx:
            recover_browser_session_after_disconnect(
                browser,
                session=session,
                permission=permission,
            )
        self.assertIn("does not match the last verified URL", str(ctx.exception))


class LoopWireTests(unittest.TestCase):
    def test_disconnect_during_semantic_step_recovers_session_without_replay(self):
        browser = _DisconnectFakeBrowser()
        browser.open_session(permission=browser.permission)
        old_session_id = browser.identity.session_id
        permission = browser.permission
        session = {
            "session_id": old_session_id,
            "url": FORM_URL,
            "page_id": "page-1",
            "last_observation": {
                "url": FORM_URL,
                "title": "Form",
                "load_state": "complete",
                "page_id": "page-1",
            },
        }
        # The provider dies once while resolving the semantic target, then
        # comes back; recovery must rebuild without replaying the click.
        browser.disconnect_observe_target_times = 1

        result = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit"},
        )

        # The proposal failed (disconnect), but the session came back.
        self.assertFalse(result.execution.success)
        evidence = result.execution.verification.evidence
        self.assertTrue(evidence["recovered"])
        self.assertEqual(result.session["url"], FORM_URL)
        self.assertNotEqual(result.session["session_id"], old_session_id)
        self.assertEqual(result.session["previous_session_id"], old_session_id)
        self.assertTrue(result.session["target_reresolved"])
        kinds = [entry[0] for entry in browser.act_log]
        self.assertEqual(kinds.count(BrowserActionKind.CLICK), 0)
        self.assertEqual(kinds.count(BrowserActionKind.NAVIGATE), 1)

    def test_disconnect_with_unrecoverable_provider_fails_explicitly(self):
        browser = _DisconnectFakeBrowser()
        browser.open_session(permission=browser.permission)
        old_session_id = browser.identity.session_id
        permission = browser.permission
        session = {
            "session_id": old_session_id,
            "url": FORM_URL,
            "page_id": "page-1",
        }
        browser.disconnect_observe_target_times = 1
        # ...and the provider cannot reopen at all.
        browser.fail_open_with = ConnectionError("provider transport dead")

        result = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit"},
        )

        self.assertFalse(result.execution.success)
        evidence = result.execution.verification.evidence
        self.assertTrue(evidence["recovery_failed"])
        self.assertIn("could not be recovered", result.execution.error)
        # No fake success: the session is the dead one, flagged unusable.
        self.assertEqual(result.session["session_id"], old_session_id)

    def test_non_disconnect_failure_does_not_trigger_recovery(self):
        browser = _DisconnectFakeBrowser()
        browser.fail_observe_target_with = RuntimeError("generic provider error")
        permission = browser.permission
        session = _old_session(session_id="session-old")

        result = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit"},
        )

        self.assertFalse(result.execution.success)
        self.assertIn("generic provider error", result.execution.error)
        self.assertEqual(browser.open_calls, 0)
        self.assertNotIn("recovered", result.execution.verification.evidence)


if __name__ == "__main__":
    unittest.main()

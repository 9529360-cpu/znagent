from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_execution import ActionExecutionRuntime
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.browser_loop import (
    browser_loop_catalog,
    browser_loop_spec,
    execute_browser_loop_step,
    parse_browser_permission,
    validate_browser_loop_arguments,
)
from zn_agent.core.models import AgentEvent, ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.models import utc_now


FORM_URL = "https://example.test/form"
DONE_URL = "https://example.test/done"
OTHER_URL = "https://example.test/other"


def _permission(**overrides):
    values = {
        "allow_navigation": True,
        "allow_page_interaction": True,
        "allow_text_entry": True,
    }
    values.update(overrides)
    return BrowserPermissionContext(**values)


class _FakeBrowser:
    name = "browser-loop-fixture"
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        click_navigates_to=None,
        fail_first_act=None,
        permission=None,
    ):
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider=self.name,
            browser_name="chromium",
        )
        self.permission = permission or _permission()
        self.url = FORM_URL
        self.click_navigates_to = click_navigates_to
        self.fail_first_act = dict(fail_first_act or {})
        self.open_calls = 0
        self.observe_calls = 0
        self.observe_target_calls = 0
        self.act_calls = 0
        self.closed_sessions = []
        self.last_observation = None
        self.drift_target_on_next_observe = False
        self.session_open = False

    def open_session(self, *, permission=None, headless=True, owner=None):
        self.open_calls += 1
        self.session_open = True
        return self.identity

    def close_session(self, session_id):
        self.closed_sessions.append(session_id)
        self.session_open = False

    def observe(self, session_id, *, page_id=""):
        self.observe_calls += 1
        observed_at = utc_now()
        observation = BrowserObservation(
            session=self.identity,
            page_id=page_id or "page-1",
            captured_at=observed_at,
            url=self.url,
            title="Form",
            load_state="complete",
        )
        self.last_observation = observation
        return observation

    def observe_target(self, session_id, query, *, page_id=""):
        self.observe_target_calls += 1
        observed_at = utc_now()
        if self.drift_target_on_next_observe:
            self.drift_target_on_next_observe = False
            self.url = OTHER_URL
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
        observation = BrowserObservation(
            session=self.identity,
            page_id=target.page_id,
            captured_at=observed_at,
            url=self.url,
            title="Form",
            load_state="complete",
            target=target,
        )
        self.last_observation = observation
        return observation

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        authority.validate_current(action, self.last_observation, self.permission)
        if self.act_calls == 1 and self.fail_first_act:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=action.page_id,
                url_before=self.last_observation.url,
                url_after=self.last_observation.url,
                target_id=action.target.target_id if action.target else "",
                data=dict(self.fail_first_act),
                error="fixture first action failed",
            )
        url_before = self.url
        if str(action.kind) == "BrowserActionKind.NAVIGATE":
            self.url = str(action.args.get("url") or self.url)
        elif str(action.kind) == "BrowserActionKind.CLICK" and self.click_navigates_to:
            self.url = self.click_navigates_to
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=url_before,
            url_after=self.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="fixture action applied",
            data={"input_sent": True},
        )


def _navigate(browser, permission):
    result = execute_browser_loop_step(
        browser,
        session={},
        permission=permission,
        action_id="browser.navigate",
        arguments={"url": FORM_URL},
    )
    assert result.execution.success, result.execution.error
    return result.session


class BrowserLoopExecutorTests(unittest.TestCase):
    def test_navigate_observe_type_text_flow_with_post_step_verification(self):
        browser = _FakeBrowser()
        permission = browser.permission
        session = _navigate(browser, permission)

        self.assertEqual(session["url"], FORM_URL)
        self.assertEqual(session["session_id"], browser.identity.session_id)

        observed = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.observe",
            arguments={},
        )
        self.assertTrue(observed.execution.success)
        self.assertEqual(observed.session["url"], FORM_URL)

        typed = execute_browser_loop_step(
            browser,
            session=observed.session,
            permission=permission,
            action_id="browser.semantic_type_text",
            arguments={"target_name": "Customer", "text": "alice@example.test"},
        )
        self.assertTrue(typed.execution.success, typed.execution.error)
        self.assertEqual(typed.session["url"], FORM_URL)
        self.assertEqual(browser.act_calls, 2)
        # Post-step verification evidence travels with the verified execution.
        verification = typed.execution.verification
        self.assertTrue(verification.verified)
        self.assertEqual(verification.evidence["post_verification"]["url"], FORM_URL)

    def test_click_without_expected_url_after_fails_on_drift_and_never_replays(self):
        browser = _FakeBrowser(click_navigates_to=DONE_URL)
        permission = browser.permission
        session = _navigate(browser, permission)

        clicked = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit"},
        )
        self.assertFalse(clicked.execution.success)
        self.assertIn("drifted", clicked.execution.error)
        self.assertEqual(browser.act_calls, 2)  # navigate + one click, no redispatch
        # The pin follows the fresh observation instead of the stale page.
        self.assertEqual(clicked.session["url"], DONE_URL)

    def test_click_with_declared_expected_url_after_succeeds(self):
        browser = _FakeBrowser(click_navigates_to=DONE_URL)
        permission = browser.permission
        session = _navigate(browser, permission)

        clicked = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit", "expected_url_after": DONE_URL},
        )
        self.assertTrue(clicked.execution.success, clicked.execution.error)
        self.assertEqual(clicked.session["url"], DONE_URL)

    def test_drift_before_dispatch_refreshes_pin_and_does_not_redispatch(self):
        browser = _FakeBrowser()
        permission = browser.permission
        session = _navigate(browser, permission)
        browser.drift_target_on_next_observe = True

        typed = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_type_text",
            arguments={"target_name": "Customer", "text": "alice@example.test"},
        )
        self.assertFalse(typed.execution.success)
        self.assertIn("drifted before dispatch", typed.execution.error)
        self.assertEqual(browser.act_calls, 1)  # navigate only; no dispatch after drift
        self.assertEqual(typed.session["url"], OTHER_URL)

    def test_dispatched_failure_is_never_replayed(self):
        browser = _FakeBrowser(
            fail_first_act={"dispatch_state": "started", "requires_fresh_resense": True}
        )
        # First act is the navigation itself: make it fail as dispatched.
        result = execute_browser_loop_step(
            browser,
            session={},
            permission=browser.permission,
            action_id="browser.navigate",
            arguments={"url": FORM_URL},
        )
        self.assertFalse(result.execution.success)
        self.assertEqual(browser.act_calls, 1)

    def test_permission_denies_type_text_before_dispatch(self):
        browser = _FakeBrowser()
        permission = _permission(allow_text_entry=False)
        browser.permission = permission
        session = _navigate(browser, permission)

        typed = execute_browser_loop_step(
            browser,
            session=session,
            permission=permission,
            action_id="browser.semantic_type_text",
            arguments={"target_name": "Customer", "text": "alice@example.test"},
        )
        self.assertFalse(typed.execution.success)
        self.assertIn("does not allow", typed.execution.error)
        self.assertEqual(browser.act_calls, 1)  # navigate only

    def test_semantic_action_requires_an_open_session(self):
        browser = _FakeBrowser()
        result = execute_browser_loop_step(
            browser,
            session={},
            permission=browser.permission,
            action_id="browser.semantic_click",
            arguments={"target_name": "Submit"},
        )
        self.assertFalse(result.execution.success)
        self.assertIn("navigate first", result.execution.error)
        self.assertEqual(browser.act_calls, 0)
        self.assertEqual(browser.open_calls, 0)

    def test_argument_validation_rejects_unknown_and_malformed_arguments(self):
        spec = browser_loop_spec("browser.semantic_select_option")
        self.assertIsNotNone(spec)
        with self.assertRaisesRegex(ValueError, "exactly one of label/value"):
            validate_browser_loop_arguments(
                spec, {"target_name": "Choice", "label": "A", "value": "a"}
            )
        with self.assertRaisesRegex(ValueError, "unknown arguments"):
            validate_browser_loop_arguments(
                spec, {"target_name": "Choice", "label": "A", "session_id": "spoofed"}
            )
        with self.assertRaisesRegex(ValueError, "http\\(s\\) URL"):
            validate_browser_loop_arguments(
                browser_loop_spec("browser.navigate"),
                {"url": "file:///etc/passwd"},
            )

    def test_permission_parsing_is_caller_owned_and_fail_closed(self):
        self.assertIsNone(parse_browser_permission(None))
        parsed = parse_browser_permission(
            {"allow_navigation": True, "allowed_origins": ["https://example.test"]}
        )
        self.assertTrue(parsed.allow_navigation)
        self.assertFalse(parsed.allow_page_interaction)
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            parse_browser_permission({"allow_navigation": "yes"})
        with self.assertRaisesRegex(ValueError, "must be an object"):
            parse_browser_permission("allow everything")

    def test_catalog_exposes_browser_actions(self):
        ids = [row["action_id"] for row in browser_loop_catalog()]
        self.assertEqual(
            ids,
            [
                "browser.navigate",
                "browser.observe",
                "browser.semantic_click",
                "browser.semantic_type_text",
                "browser.semantic_check",
                "browser.semantic_uncheck",
                "browser.semantic_select_option",
                "browser.page.register",
                "browser.page.return",
            ],
        )


class _Body:
    def __init__(self):
        self.calls = []

    def act(self, kind, *, event_id=None, **kwargs):
        self.calls.append((kind, event_id, dict(kwargs)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"value": "fresh"},
            event_id=event_id,
        )


class _Device:
    def installed_applications(self):
        return ()

    def foreground_application(self):
        return None


def _fabric():
    fabric = ActionFabricRegistry()
    fabric.register(
        ActionDescriptor(
            action_id="test.read",
            provider="test",
            description="Read one fresh test value.",
            body_action_kind="test_read",
            input_schema={"type": "object", "additionalProperties": False},
            effect_class="read_only",
            verification=("fresh body result",),
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            reason="test action is available",
        ),
    )
    return fabric


class BrowserLoopResidentTests(unittest.TestCase):
    def _resident(self, root: Path, browser, permission):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        resident.action_fabric = _fabric()
        resident.action_executor = ActionExecutionRuntime(_fabric(), _Body())
        resident.device_capabilities = _Device()
        resident.browser_provider = browser
        resident.browser_permission_context = permission
        resident._accept_generic_action_increment = lambda event, state, increment: 1
        return resident

    @staticmethod
    def _increment(event, content):
        from zn_agent.core.cognition import CognitiveIncrement

        return CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id="impasse-test",
            source="external:test",
            question=event.task,
            content=content,
            quality=1.0,
            confidence=1.0,
        )

    @staticmethod
    def _state(event, increment):
        from zn_agent.core.models import WorkingState

        return WorkingState(
            current_event_id=event.event_id,
            stage="cognition_integration",
            data={
                "cognition_request": {
                    "context": {"generic_action_loop": {"version": 1}},
                },
                "cognitive_increment": increment.to_dict(),
                "external_cognition_result": {"model_invocations": 1},
            },
        )

    def _propose(self, resident, event, state, content):
        from types import SimpleNamespace as _NS

        state.stage = "cognition_integration"
        state.data["cognition_request"] = {
            "context": {"generic_action_loop": {"version": 1}},
        }
        state.data["cognitive_increment"] = self._increment(event, content).to_dict()
        state.data["external_cognition_result"] = {"model_invocations": 1}
        admitted = resident._cognition_integration_step(
            event, state, readiness=_NS()
        )
        self.assertIsNone(admitted)
        self.assertEqual(state.stage, resident._GENERIC_ACTION_STAGE)
        executed = resident._generic_action_step(event, state)
        self.assertIsNone(executed)
        return state

    def test_browser_loop_available_only_with_provider_and_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser = _FakeBrowser()
            resident = self._resident(Path(tmp), browser, _permission())
            event = AgentEvent(
                event_id="evt-browser-avail",
                task="fill the form",
                kind="desktop_user_event",
            )
            try:
                self.assertTrue(resident._browser_loop_available(event))
                resident.browser_permission_context = None
                self.assertFalse(resident._browser_loop_available(event))
            finally:
                resident.store.close()

    def test_model_completes_navigate_find_act_verify_in_one_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser = _FakeBrowser()
            resident = self._resident(Path(tmp), browser, _permission())
            try:
                event = AgentEvent(
                    event_id="evt-browser-loop",
                    task="inspect the current test value",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"browser.navigate",'
                        '"arguments":{"url":"' + FORM_URL + '"}}}',
                    ),
                )
                resident.store.save_working_state(state)

                self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"browser.navigate",'
                    '"arguments":{"url":"' + FORM_URL + '"}}}',
                )
                self.assertEqual(state.stage, "native_deliberation")
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(len(loop["history"]), 1)
                self.assertTrue(loop["history"][0]["verified"])
                self.assertEqual(loop["browser"]["url"], FORM_URL)

                self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"browser.semantic_type_text",'
                    '"arguments":{"target_name":"Customer","text":"alice@example.test"}}}',
                )
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(len(loop["history"]), 2)
                self.assertTrue(loop["history"][1]["verified"])
                # Exactly one navigate + one type_text; nothing re-dispatched.
                self.assertEqual(browser.act_calls, 2)
                self.assertEqual(browser.open_calls, 1)
                evidence_id = loop["history"][-1]["execution_id"]

                from types import SimpleNamespace as _NS

                state.stage = "cognition_integration"
                state.data["cognition_request"] = {
                    "context": {"generic_action_loop": {"version": 1}},
                }
                state.data["cognitive_increment"] = self._increment(
                    event,
                    '{"zn_action_completion":{"execution_ids":["'
                    + evidence_id
                    + '"],"response":"form field filled and verified"}}',
                ).to_dict()
                state.data["external_cognition_result"] = {"model_invocations": 1}
                completed = resident._cognition_integration_step(
                    event, state, readiness=_NS()
                )
                self.assertIsNotNone(completed)
                self.assertTrue(completed.success)
                self.assertIs(completed.execution_path, ExecutionPath.BODY)
                self.assertEqual(completed.response, "form field filled and verified")
                # Completion closes the loop session instead of leaking it.
                self.assertEqual(browser.closed_sessions, [browser.identity.session_id])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

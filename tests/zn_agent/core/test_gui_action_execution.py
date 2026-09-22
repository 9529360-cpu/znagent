from __future__ import annotations

import unittest

from zn_agent.core.action_execution import ActionRequest, build_machine_action_execution_runtime
from zn_agent.core.action_fabric import ActionAvailability, ActionDescriptor, ActionFabricRegistry
from zn_agent.core.automation_control_action import (
    AutomationControlObservation,
    AutomationControlSelector,
    text_sha256,
)
from zn_agent.core.body import BodyActionResult


class _GuiBody:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, dict]] = []
        self.toggle_state = "off"
        self.value = ""
        self.read_count = 0

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, event_id, dict(args)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"dispatch_sent": True, "postcondition_verified": False},
            event_id=event_id,
        )

    def observe_automation_control(
        self,
        *,
        application_id: str,
        control_type: str,
        control_name: str,
        automation_id: str,
        pattern: str,
    ):
        self.read_count += 1
        selector = AutomationControlSelector(
            control_type=control_type,
            name=control_name,
            automation_id=automation_id,
        )
        if pattern == "toggle":
            state = {"toggle_state": self.toggle_state}
        elif pattern == "value":
            state = {
                "value_chars": len(self.value),
                "value_sha256": text_sha256(self.value),
                "read_only": False,
            }
        elif pattern == "expand_collapse":
            state = {"expand_collapse_state": "expanded"}
        else:
            state = {"selected": True}
        return AutomationControlObservation(
            process_id=55,
            process_name="demo.exe",
            window_handle=66,
            runtime_id=(1, 2, 3),
            selector=selector,
            observed_name=selector.name,
            observed_automation_id=selector.automation_id,
            class_name="DemoControl",
            is_enabled=True,
            is_offscreen=False,
            is_password=False,
            supported_patterns=(pattern,),
            pattern=pattern,
            state=state,
        )


def _registry(action_id: str, body_kind: str) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    registry.register(
        ActionDescriptor(
            action_id=action_id,
            provider="zn.windows.uia",
            description="test semantic GUI action",
            body_action_kind=body_kind,
            effect_class="reversible_side_effect",
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            evidence={"source": "test"},
        ),
    )
    return registry


class GuiActionExecutionTests(unittest.TestCase):
    def test_toggle_completion_comes_from_fresh_uia_readback(self) -> None:
        body = _GuiBody()
        body.toggle_state = "on"
        runtime = build_machine_action_execution_runtime(
            _registry("windows.ui.control.toggle", "automation_control_toggle"),
            body,
            device_capabilities=None,
        )
        result = runtime.execute(
            ActionRequest(
                "windows.ui.control.toggle",
                {
                    "application_id": "app.demo",
                    "control_type": "checkbox",
                    "control_name": "Sync",
                    "state": "on",
                },
                event_id="evt-toggle",
            )
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(body.read_count, 1)
        self.assertEqual(result.observations[-1].source, "windows_uia_control_readback")
        self.assertTrue(result.verification.evidence["selector_matches"])

    def test_reverify_observes_without_redispatch(self) -> None:
        body = _GuiBody()
        runtime = build_machine_action_execution_runtime(
            _registry("windows.ui.control.toggle", "automation_control_toggle"),
            body,
            device_capabilities=None,
        )
        request = ActionRequest(
            "windows.ui.control.toggle",
            {
                "application_id": "app.demo",
                "control_type": "checkbox",
                "control_name": "Sync",
                "state": "on",
            },
            event_id="evt-reverify",
        )
        first = runtime.execute(request)
        self.assertFalse(first.success)
        self.assertEqual(first.status, "failed")
        self.assertEqual(len(body.calls), 1)

        body.toggle_state = "on"
        second = runtime.verify(first)
        self.assertTrue(second.success)
        self.assertEqual(second.status, "verified")
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(body.read_count, 2)

    def test_value_verification_uses_digest_not_raw_text(self) -> None:
        body = _GuiBody()
        body.value = "secret-ish local text"
        runtime = build_machine_action_execution_runtime(
            _registry("windows.ui.control.set_value", "automation_control_set_value"),
            body,
            device_capabilities=None,
        )
        result = runtime.execute(
            ActionRequest(
                "windows.ui.control.set_value",
                {
                    "application_id": "app.demo",
                    "control_type": "edit",
                    "automation_id": "Editor",
                    "value": body.value,
                },
                event_id="evt-value",
            )
        )
        self.assertTrue(result.success)
        evidence = result.verification.evidence
        self.assertEqual(evidence["expected_value_chars"], len(body.value))
        self.assertEqual(evidence["expected_value_sha256"], text_sha256(body.value))
        self.assertNotIn(body.value, repr(evidence))


if __name__ == "__main__":
    unittest.main()

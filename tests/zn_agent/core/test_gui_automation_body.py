from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.automation_control_action import (
    AutomationControlMutationResult,
    AutomationControlObservation,
    AutomationControlSelector,
    NativeAutomationControlAction,
    _WindowsAutomationControlWorker,
    text_sha256,
)
from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.gui_automation_body import GuiAutomationBody
from zn_agent.core.machine_capability import ApplicationInventoryCandidate, DeviceCapabilityGraph
from zn_agent.core.store import KernelStore


class _FakeControlDriver:
    def __init__(self) -> None:
        self.mutations: list[dict] = []
        self.reads: list[dict] = []
        self.toggle_state = "off"

    @staticmethod
    def _observation(*, process_id, process_name, window_handle, selector, pattern, state):
        return AutomationControlObservation(
            process_id=process_id,
            process_name=process_name,
            window_handle=window_handle,
            runtime_id=(42, 7),
            selector=selector,
            observed_name=selector.name,
            observed_automation_id=selector.automation_id,
            class_name="Button",
            is_enabled=True,
            is_offscreen=False,
            is_password=False,
            supported_patterns=(pattern,),
            pattern=pattern,
            state=state,
        )

    def mutate(self, **kwargs):
        self.mutations.append(dict(kwargs))
        pattern = kwargs["pattern"]
        before_state = {"toggle_state": self.toggle_state}
        if pattern == "toggle":
            self.toggle_state = kwargs["target"]
            after_state = {"toggle_state": self.toggle_state}
        elif pattern == "value":
            value = kwargs["target"]
            before_state = {"value_chars": 3, "value_sha256": text_sha256("old"), "read_only": False}
            after_state = {
                "value_chars": len(value),
                "value_sha256": text_sha256(value),
                "read_only": False,
            }
        else:
            after_state = {"selected": True}
        before = self._observation(**{k: kwargs[k] for k in ("process_id", "process_name", "window_handle", "selector", "pattern")}, state=before_state)
        after = self._observation(**{k: kwargs[k] for k in ("process_id", "process_name", "window_handle", "selector", "pattern")}, state=after_state)
        return AutomationControlMutationResult(
            success=True,
            mutation_dispatched=True,
            postcondition_verified=True,
            before=before,
            after=after,
        )

    def read(self, **kwargs):
        self.reads.append(dict(kwargs))
        if kwargs["pattern"] == "toggle":
            state = {"toggle_state": self.toggle_state}
        else:
            state = {"selected": True}
        return self._observation(**kwargs, state=state)



class _FakeControlSense:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_controls(self, **kwargs):
        self.calls.append(dict(kwargs))
        return (
            NamedAutomationControlObservation(
                runtime_id=(90, 1),
                process_id=kwargs["process_id"],
                process_name=kwargs["process_name"],
                name="Sync",
                control_type=50002,
                class_name="CheckBox",
                is_enabled=True,
                is_offscreen=False,
                left=10,
                top=10,
                right=100,
                bottom=40,
                center_x_fraction=0.1,
                center_y_fraction=0.1,
                captured_at="2026-09-21T00:00:00+00:00",
                is_toggle_pattern_available=True,
                source="test",
            ),
        )


class GuiAutomationBodyTests(unittest.TestCase):
    def _fixture(self, tmp: str):
        executable = Path(tmp) / "notepad.exe"
        executable.write_bytes(b"")
        runtime = {
            "processes": [
                {"pid": 55, "name": "notepad.exe", "exe": str(executable)},
            ],
            "windows": [
                {
                    "hwnd": 66,
                    "pid": 55,
                    "title": "Untitled - Notepad",
                    "class_name": "Notepad",
                    "visible": True,
                    "foreground": True,
                }
            ],
        }
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths",
                    source_id="notepad",
                    display_name="Notepad",
                    executable_path=str(executable),
                    identity_paths=(str(executable),),
                    launch_kind="executable",
                    launch_target=str(executable),
                    version="11.0",
                )
            ],
            process_provider=lambda: list(runtime["processes"]),
            window_provider=lambda: list(runtime["windows"]),
            cache_path=Path(tmp) / "apps.json",
            inventory_ttl_seconds=0,
        )
        app = graph.installed_applications(force_refresh=True)[0]
        store = KernelStore(Path(tmp) / "kernel.db")
        driver = _FakeControlDriver()
        control_sense = _FakeControlSense()
        control = NativeAutomationControlAction(read_fn=driver.read, mutate_fn=driver.mutate)
        body = GuiAutomationBody(
            store=store,
            device_capabilities=graph,
            automation_control=control,
            automation_control_sense=control_sense,
        )
        return store, body, app, runtime, driver, executable, control_sense

    def test_public_gui_action_rejects_native_targets_and_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, driver, _, _control_sense = self._fixture(tmp)
            try:
                for index, key in enumerate(("hwnd", "pid", "x", "y", "coordinates", body._DISPATCH_MARKER)):
                    with self.subTest(key=key):
                        result = body.act(
                            "automation_control_toggle",
                            event_id=f"evt-raw-{index}",
                            application_id=app.app_id,
                            control_type="checkbox",
                            control_name="Sync",
                            state="on",
                            **{key: 1},
                        )
                        self.assertFalse(result.success)
                        self.assertFalse(result.data["dispatch_sent"])
                        self.assertIn(key, result.data["rejected_arguments"])
                self.assertEqual(driver.mutations, [])
            finally:
                store.close()

    def test_semantic_toggle_uses_fresh_foreground_identity_and_pattern_driver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, driver, _, _control_sense = self._fixture(tmp)
            try:
                result = body.act(
                    "automation_control_toggle",
                    event_id="evt-toggle",
                    application_id=app.app_id,
                    control_type="checkbox",
                    control_name="Sync",
                    state="on",
                )
                self.assertTrue(result.success)
                self.assertTrue(result.data["dispatch_sent"])
                self.assertTrue(result.data["postcondition_verified"])
                self.assertEqual(len(driver.mutations), 1)
                sent = driver.mutations[0]
                self.assertEqual(sent["process_id"], 55)
                self.assertEqual(sent["window_handle"], 66)
                self.assertEqual(sent["pattern"], "toggle")
                self.assertEqual(sent["target"], "on")
                self.assertEqual(sent["selector"].name, "Sync")
            finally:
                store.close()

    def test_replay_identity_is_semantic_across_hwnd_pid_churn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, runtime, driver, executable, _control_sense = self._fixture(tmp)
            try:
                first = body.act(
                    "automation_control_toggle",
                    event_id="evt-replay",
                    application_id=app.app_id,
                    control_type="checkbox",
                    control_name="Sync",
                    state="on",
                )
                self.assertTrue(first.success)
                self.assertEqual(len(driver.mutations), 1)

                runtime["processes"] = [
                    {"pid": 77, "name": "notepad.exe", "exe": str(executable)},
                ]
                runtime["windows"] = [
                    {
                        "hwnd": 88,
                        "pid": 77,
                        "title": "Untitled - Notepad",
                        "class_name": "Notepad",
                        "visible": True,
                        "foreground": True,
                    }
                ]
                second = body.act(
                    "automation_control_toggle",
                    event_id="evt-replay",
                    application_id=app.app_id,
                    control_type="checkbox",
                    control_name="Sync",
                    state="on",
                )
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(len(driver.mutations), 1)
            finally:
                store.close()

    def test_empty_value_is_a_valid_verified_target(self) -> None:
        state = {"value_chars": 0, "value_sha256": text_sha256("")}
        self.assertTrue(_WindowsAutomationControlWorker._target_verified("value", "", state))

    def test_selector_requires_semantic_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires name or automation_id"):
            AutomationControlSelector(control_type="button")


    def test_read_action_returns_fresh_semantic_pattern_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, driver, _executable, _sense = self._fixture(tmp)
            try:
                driver.toggle_state = "on"
                result = body.act(
                    "automation_control_read",
                    application_id=app.app_id,
                    control_type="checkbox",
                    control_name="Sync",
                    pattern="toggle",
                )
                self.assertTrue(result.success)
                self.assertEqual(result.data["state"]["toggle_state"], "on")
                self.assertEqual(result.data["selector"]["name"], "Sync")
                self.assertEqual(len(driver.reads), 1)
            finally:
                store.close()

    def test_control_inventory_is_bounded_read_only_sense(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, _driver, _executable, sense = self._fixture(tmp)
            try:
                result = body.act(
                    "automation_controls_list",
                    application_id=app.app_id,
                    control_type="checkbox",
                )
                self.assertTrue(result.success)
                self.assertEqual(result.data["count"], 1)
                self.assertEqual(result.data["controls"][0]["name"], "Sync")
                self.assertEqual(result.data["controls"][0]["supported_patterns"], ["toggle"])
                self.assertEqual(len(sense.calls), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

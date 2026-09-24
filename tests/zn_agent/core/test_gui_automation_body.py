from __future__ import annotations

import json
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

from zn_agent.core.automation_control_action import (
    AutomationControlFocusResult,
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
        self.focuses: list[dict] = []
        self.toggle_state = "off"
        self.text = ""

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
            is_keyboard_focusable=True,
            has_keyboard_focus=True,
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
        elif kwargs["pattern"] == "text":
            state = {
                "text_chars": len(self.text),
                "text_sha256": text_sha256(self.text),
            }
        elif kwargs["pattern"] == "value":
            state = {
                "value_chars": len(self.text),
                "value_sha256": text_sha256(self.text),
                "read_only": False,
            }
        else:
            state = {"selected": True}
        return self._observation(**kwargs, state=state)

    def focus(self, **kwargs):
        self.focuses.append(dict(kwargs))
        before = self.read(**kwargs)
        after = self.read(**kwargs)
        return AutomationControlFocusResult(
            success=True,
            focus_dispatched=True,
            before=before,
            after=after,
        )


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


class _FakeSceneBuilder:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.calls: list[dict] = []

    def artifact_path(self, event_id):
        return self.root / f"{event_id}.scene.json"

    def capture(self, *, event_id, foreground, foreground_probe):
        fresh = foreground_probe()
        if not foreground.same_identity(fresh):
            raise RuntimeError("foreground drifted during fake scene capture")
        self.calls.append(
            {
                "event_id": event_id,
                "application_id": foreground.application_id,
                "process_id": foreground.process_id,
                "process_name": foreground.process_name,
                "window_handle": foreground.window_handle,
            }
        )
        scene_payload = {
            "scene_id": "desktop-scene-test",
            "grounding_mode": "uia_only",
            "targets": [
                {
                    "target_id": "desktop-target-test",
                    "accessible_name": "Sensitive customer label",
                }
            ],
            "screenshot": {
                "local_path": r"C:\zn\shot.png",
                "sha256": "b" * 64,
                "width": 1000,
                "height": 800,
                "size_bytes": 1234,
            },
        }
        self.artifact_path(event_id).write_text("{}", encoding="utf-8")
        scene = SimpleNamespace(
            scene_id="desktop-scene-test",
            grounding_mode="uia_only",
            targets=("target",),
            uia_target_count=1,
            visual_target_count=0,
            truncated=False,
            audit=lambda: scene_payload,
        )
        return scene, r"C:\zn\scene.json"


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
        control = NativeAutomationControlAction(
            read_fn=driver.read,
            mutate_fn=driver.mutate,
            focus_fn=driver.focus,
        )
        scene_builder = _FakeSceneBuilder(Path(tmp))
        body = GuiAutomationBody(
            store=store,
            device_capabilities=graph,
            automation_control=control,
            automation_control_sense=control_sense,
            desktop_scene_builder=scene_builder,
        )
        return store, body, app, runtime, driver, executable, control_sense

    def test_desktop_scene_rejects_native_authority_and_requires_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, _driver, _, _sense = self._fixture(tmp)
            try:
                builder = body._desktop_scene_builder
                for index, key in enumerate(
                    (
                        "hwnd",
                        "pid",
                        "x",
                        "y",
                        "coordinates",
                        body._SCENE_DISPATCH_MARKER,
                    )
                ):
                    with self.subTest(key=key):
                        result = body.act(
                            "windows_desktop_scene_capture",
                            event_id=f"evt-scene-raw-{index}",
                            application_id=app.app_id,
                            **{key: 1},
                        )
                        self.assertFalse(result.success)
                        self.assertFalse(result.data["dispatch_sent"])
                        self.assertIn(key, result.data["rejected_arguments"])
                missing = body.act(
                    "windows_desktop_scene_capture",
                    application_id=app.app_id,
                )
                self.assertFalse(missing.success)
                self.assertIn("stable event_id", missing.error or "")
                self.assertEqual(builder.calls, [])
            finally:
                store.close()

    def test_desktop_scene_uses_exact_foreground_identity_and_replay_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, _driver, _, _sense = self._fixture(tmp)
            try:
                builder = body._desktop_scene_builder
                first = body.act(
                    "windows_desktop_scene_capture",
                    event_id="evt-scene",
                    application_id=app.app_id,
                )
                self.assertTrue(first.success, first.error)
                self.assertTrue(first.data["dispatch_sent"])
                self.assertTrue(first.data["artifact_created"])
                self.assertEqual(first.data["scene_id"], "desktop-scene-test")
                self.assertEqual(first.data["target_count"], 1)
                self.assertEqual(
                    builder.calls,
                    [
                        {
                            "event_id": "evt-scene",
                            "application_id": app.app_id,
                            "process_id": 55,
                            "process_name": "notepad.exe",
                            "window_handle": 66,
                        }
                    ],
                )

                _runtime["windows"][0]["foreground"] = False
                second = body.act(
                    "windows_desktop_scene_capture",
                    event_id="evt-scene",
                    application_id=app.app_id,
                )
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(len(builder.calls), 1)
            finally:
                store.close()

    def test_orphan_scene_artifact_never_becomes_replay_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, runtime, _driver, _, _sense = self._fixture(tmp)
            try:
                builder = body._desktop_scene_builder
                builder.artifact_path("evt-orphan").write_text("{}", encoding="utf-8")
                runtime["windows"][0]["foreground"] = False

                result = body.act(
                    "windows_desktop_scene_capture",
                    event_id="evt-orphan",
                    application_id=app.app_id,
                )

                self.assertFalse(result.success)
                self.assertFalse(result.data.get("replay_blocked", False))
                self.assertFalse(result.data.get("dispatch_sent", False))
                self.assertEqual(builder.calls, [])
            finally:
                store.close()

    def test_desktop_scene_durable_body_history_redacts_full_scene_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, _driver, _, _sense = self._fixture(tmp)
            try:
                result = body.act(
                    "windows_desktop_scene_capture",
                    event_id="evt-scene-history",
                    application_id=app.app_id,
                )
                self.assertTrue(result.success)
                conn = sqlite3.connect(store.path)
                try:
                    row = conn.execute(
                        "SELECT result_json FROM native_body_actions "
                        "WHERE kind=? ORDER BY completed_at DESC LIMIT 1",
                        ("windows_desktop_scene_capture",),
                    ).fetchone()
                finally:
                    conn.close()
                self.assertIsNotNone(row)
                persisted = json.loads(row[0])
                persisted_data = dict(persisted.get("data") or {})
                self.assertTrue(persisted_data["scene_payload_redacted"])
                self.assertNotIn("scene", persisted_data)
                self.assertNotIn(
                    "Sensitive customer label",
                    str(persisted_data),
                )
                self.assertEqual(
                    persisted_data["scene_id"],
                    "desktop-scene-test",
                )
            finally:
                store.close()

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

    def test_semantic_document_text_uses_focus_keyboard_digest_and_replay_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, driver, _, _control_sense = self._fixture(tmp)
            try:
                text = "hello from ZN"

                def send_keyboard(value):
                    driver.text = value
                    return len(value), len(value)

                body._send_keyboard_text = send_keyboard
                first = body.act(
                    "automation_control_type_text",
                    event_id="evt-type-text",
                    application_id=app.app_id,
                    control_type="document",
                    automation_id="Editor",
                    text=text,
                )
                self.assertTrue(first.success, first.error)
                self.assertTrue(first.data["dispatch_sent"])
                self.assertTrue(first.data["postcondition_verified"])
                self.assertFalse(first.data["side_effect_uncertain"])
                self.assertEqual(first.data["expected_text_chars"], len(text))
                self.assertEqual(first.data["expected_text_sha256"], text_sha256(text))
                self.assertEqual(driver.text, text)
                self.assertEqual(len(driver.focuses), 1)

                reads_after_first = len(driver.reads)
                second = body.act(
                    "automation_control_type_text",
                    event_id="evt-type-text",
                    application_id=app.app_id,
                    control_type="document",
                    automation_id="Editor",
                    text=text,
                )
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(len(driver.reads), reads_after_first)
                self.assertEqual(driver.text, text)

                conn = sqlite3.connect(store.path)
                try:
                    row = conn.execute(
                        "SELECT action_json FROM native_body_actions "
                        "WHERE kind=? ORDER BY completed_at DESC LIMIT 1",
                        ("automation_control_type_text",),
                    ).fetchone()
                finally:
                    conn.close()
                self.assertIsNotNone(row)
                persisted = row[0]
                self.assertNotIn(text, persisted)
                persisted_action = json.loads(persisted)
                self.assertIs(persisted_action["args"]["text_redacted"], True)
                self.assertEqual(persisted_action["args"]["text_chars"], len(text))
                self.assertEqual(
                    persisted_action["args"]["text_sha256"],
                    text_sha256(text),
                )
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

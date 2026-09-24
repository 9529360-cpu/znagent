from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from zn_agent.core.action_authority import ActionAuthorityContext
from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
    build_machine_action_execution_runtime,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.side_effect_journal import ResidentSideEffectJournal
from zn_agent.core.store import KernelStore
from zn_agent.core.windows_brightness import WindowsBrightnessObservation
from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody
from zn_agent.core.desktop_scene import (
    DesktopSceneForegroundBinding,
    DesktopSceneRect,
    NativeDesktopSceneBuilder,
    desktop_scene_capture_event_id,
)
from zn_agent.core.windows_screen_capture import (
    capture_primary_screen_artifact,
    inspect_screen_capture_artifact,
    screen_capture_artifact_path,
)


class _FakeBody:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, dict]] = []
        self.handlers = {}

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, event_id, dict(args)))
        handler = self.handlers.get(kind)
        if handler is not None:
            return handler(kind, event_id, args)
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"dispatch_sent": True},
            event_id=event_id,
        )


class _FakeGraph:
    def __init__(self) -> None:
        self.application = SimpleNamespace(
            app_id="app.demo",
            canonical_name="Demo",
        )
        self.processes = ()
        self.windows_rows = ()

    def application_by_id(self, app_id: str, *, force_refresh: bool = False):
        return self.application if app_id == self.application.app_id else None

    def application_runtime(self, application):
        return tuple(self.processes), tuple(self.windows_rows)


def _registry(*descriptors: ActionDescriptor) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    for descriptor in descriptors:
        registry.register(
            descriptor,
            availability_probe=lambda current: ActionAvailability(
                current.action_id,
                "available",
                evidence={"source": "test"},
            ),
        )
    return registry
class ActionExecutionContractTests(unittest.TestCase):
    def test_read_only_body_result_is_verified_current_evidence(self) -> None:
        descriptor = ActionDescriptor(
            action_id="test.context.read",
            provider="zn.test",
            description="Read context",
            body_action_kind="test_context_read",
            effect_class="read_only",
        )
        body = _FakeBody()
        body.handlers["test_context_read"] = lambda kind, event_id, args: BodyActionResult(
            action_id="body-read",
            kind=kind,
            success=True,
            data={"value": 7},
            event_id=event_id,
        )
        runtime = ActionExecutionRuntime(_registry(descriptor), body)

        result = runtime.execute(ActionRequest("test.context.read"))

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.verification.status, "verified")
        self.assertEqual(result.observations[-1].source, "body_result")
        self.assertEqual(body.calls, [("test_context_read", None, {})])
    def test_side_effect_requires_stable_event_before_dispatch(self) -> None:
        descriptor = ActionDescriptor(
            action_id="test.effect.set",
            provider="zn.test",
            description="Mutate something",
            body_action_kind="test_effect_set",
            effect_class="reversible_side_effect",
        )
        body = _FakeBody()
        runtime = ActionExecutionRuntime(_registry(descriptor), body)

        result = runtime.execute(
            ActionRequest("test.effect.set", {"value": 1})
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertIn("stable event_id", result.error or "")
        self.assertEqual(body.calls, [])

    def test_worker_authority_context_is_bound_to_existing_body_gate(self) -> None:
        descriptor = ActionDescriptor(
            action_id="test.read",
            provider="zn.test",
            description="Read through worker authority",
            body_action_kind="read_text",
            effect_class="read_only",
        )
        body = _FakeBody()
        authority = ActionAuthorityContext(
            work_thread_id="thread-1",
            work_item_id="item-1",
            worker_run_id="worker-1",
            plan_version=1,
            executor_kind="research",
            expected_action="read_file",
            tool_scope=("workspace.read",),
            authority_scope=("workspace_read",),
            workspace_root="D:\\repo",
        )
        runtime = ActionExecutionRuntime(_registry(descriptor), body)

        result = runtime.execute(
            ActionRequest(
                "test.read",
                {"path": "D:\\repo\\a.txt"},
                authority_context=authority,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.authority_mode, "worker_run")
        sent_args = body.calls[0][2]
        self.assertIn("__zn_authority_context", sent_args)
        self.assertEqual(
            sent_args["__zn_authority_context"]["worker_run_id"],
            "worker-1",
        )
class MachineActionExecutionTests(unittest.TestCase):
    def _scene_runtime(self, body: _FakeBody):
        descriptor = ActionDescriptor(
            action_id="windows.desktop.scene.capture",
            provider="zn.windows.desktop.scene",
            description="Capture desktop scene",
            body_action_kind="windows_desktop_scene_capture",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {
                    "application_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
        )
        return build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=None,
        )

    def _screen_runtime(self, body: _FakeBody):
        descriptor = ActionDescriptor(
            action_id="windows.screen.capture",
            provider="zn.windows",
            description="Capture screen",
            body_action_kind="windows_screen_capture",
            effect_class="reversible_side_effect",
        )
        return build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=None,
        )

    def _volume_runtime(self, body: _FakeBody):
        descriptor = ActionDescriptor(
            action_id="windows.audio.volume.set",
            provider="zn.windows",
            description="Set volume",
            body_action_kind="windows_audio_volume_set",
            effect_class="reversible_side_effect",
        )
        return build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=None,
        )

    def _brightness_runtime(self, body: _FakeBody):
        descriptor = ActionDescriptor(
            action_id="windows.display.brightness.set",
            provider="zn.windows",
            description="Set brightness",
            body_action_kind="windows_display_brightness_set",
            effect_class="reversible_side_effect",
        )
        return build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=None,
        )
    @staticmethod
    def _build_scene_artifact(home: Path, event_id: str):
        class _EmptySense:
            def list_controls(self, **_kwargs):
                return ()

        def capture(scene_event_id):
            return capture_primary_screen_artifact(
                desktop_scene_capture_event_id(scene_event_id),
                home=home,
                capture_fn=lambda: Image.new("RGB", (200, 120), (10, 20, 30)),
            )

        binding = DesktopSceneForegroundBinding(
            application_id="app.demo",
            process_id=77,
            process_name="demo.exe",
            window_handle=88,
            class_name="Demo",
        )
        builder = NativeDesktopSceneBuilder(
            automation_sense=_EmptySense(),
            capture_fn=capture,
            window_rect_fn=lambda hwnd, pid: DesktopSceneRect(5, 5, 180, 110),
            home=home,
        )
        return builder.capture(
            event_id=event_id,
            foreground=binding,
            foreground_probe=lambda: binding,
        )

    def test_desktop_scene_requires_independent_artifact_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": tmp},
        ):
            scene, scene_path = self._build_scene_artifact(
                Path(tmp),
                "event-scene",
            )
            body = _FakeBody()
            body.handlers["windows_desktop_scene_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-scene",
                    kind=kind,
                    success=True,
                    data={
                        "dispatch_sent": True,
                        "artifact_created": True,
                        "scene_artifact_path": scene_path,
                        "scene_id": scene.scene_id,
                        "grounding_mode": scene.grounding_mode,
                        "target_count": len(scene.targets),
                        "uia_target_count": scene.uia_target_count,
                        "visual_target_count": scene.visual_target_count,
                        "truncated": scene.truncated,
                        "scene": scene.audit(),
                    },
                    event_id=event_id,
                )
            )

            result = self._scene_runtime(body).execute(
                ActionRequest(
                    "windows.desktop.scene.capture",
                    {"application_id": "app.demo"},
                    event_id="event-scene",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(
                result.observations[-1].source,
                "zn_desktop_scene_artifact_readback",
            )
            self.assertEqual(
                result.observations[-1].data["scene_id"],
                scene.scene_id,
            )
            self.assertEqual(
                result.observations[-1].data["scene"]["screenshot"]["sha256"],
                scene.screenshot.sha256,
            )

    def test_desktop_scene_replay_recovers_exact_scene_without_recapture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": tmp},
        ):
            scene, _scene_path = self._build_scene_artifact(
                Path(tmp),
                "event-scene-replay",
            )
            body = _FakeBody()
            body.handlers["windows_desktop_scene_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-scene-replay",
                    kind=kind,
                    success=False,
                    data={
                        "replay_blocked": True,
                        "side_effect_uncertain": True,
                    },
                    error="prior scene capture requires observation",
                    event_id=event_id,
                )
            )

            result = self._scene_runtime(body).execute(
                ActionRequest(
                    "windows.desktop.scene.capture",
                    {"application_id": "app.demo"},
                    event_id="event-scene-replay",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.verification.evidence["replay_recovered"])
            self.assertEqual(
                result.observations[-1].data["scene_id"],
                scene.scene_id,
            )
            self.assertEqual(
                result.observations[-1].data["scene"],
                scene.audit(),
            )
            self.assertEqual(len(body.calls), 1)

    def test_desktop_scene_mismatched_body_scene_id_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": tmp},
        ):
            scene, scene_path = self._build_scene_artifact(
                Path(tmp),
                "event-scene-mismatch",
            )
            body = _FakeBody()
            body.handlers["windows_desktop_scene_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-scene-mismatch",
                    kind=kind,
                    success=True,
                    data={
                        "dispatch_sent": True,
                        "artifact_created": True,
                        "scene_artifact_path": scene_path,
                        "scene_id": "desktop-scene-wrong",
                    },
                    event_id=event_id,
                )
            )

            result = self._scene_runtime(body).execute(
                ActionRequest(
                    "windows.desktop.scene.capture",
                    {"application_id": "app.demo"},
                    event_id="event-scene-mismatch",
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.status, "failed")
            self.assertIn(
                "scene_id",
                result.verification.evidence["mismatched_fields"],
            )

    @unittest.skipUnless(os.name == "nt", "Windows screen capture is Windows-only")
    def test_screen_capture_requires_independent_artifact_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": str(Path(tmp) / "path-alias" / "..")},
        ):
            (Path(tmp) / "path-alias").mkdir()
            path = screen_capture_artifact_path("event-screen")
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (20, 10), (1, 2, 3)).save(path)
            observed = inspect_screen_capture_artifact(path)
            self.assertNotEqual(str(path), observed["local_path"])

            body = _FakeBody()
            body.handlers["windows_screen_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-screen",
                    kind=kind,
                    success=True,
                    data={
                        "dispatch_sent": True,
                        "local_path": observed["local_path"],
                        "width": observed["width"],
                        "height": observed["height"],
                        "size_bytes": observed["size_bytes"],
                        "sha256": observed["sha256"],
                    },
                    event_id=event_id,
                )
            )
            result = self._screen_runtime(body).execute(
                ActionRequest(
                    "windows.screen.capture",
                    event_id="event-screen",
                )
            )

            self.assertTrue(result.success)
            self.assertEqual(result.status, "verified")
            self.assertEqual(
                result.observations[-1].source,
                "zn_screen_capture_artifact_readback",
            )
            self.assertEqual(
                result.verification.evidence["sha256"],
                observed["sha256"],
            )

    @unittest.skipUnless(os.name == "nt", "Windows screen capture is Windows-only")
    def test_screen_capture_replay_recovers_from_deterministic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": tmp},
        ):
            path = screen_capture_artifact_path("event-screen-replay")
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (12, 8), (4, 5, 6)).save(path)

            body = _FakeBody()
            body.handlers["windows_screen_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-replay",
                    kind=kind,
                    success=False,
                    data={
                        "replay_blocked": True,
                        "side_effect_uncertain": True,
                    },
                    error="prior dispatch requires observation",
                    event_id=event_id,
                )
            )
            result = self._screen_runtime(body).execute(
                ActionRequest(
                    "windows.screen.capture",
                    event_id="event-screen-replay",
                )
            )

            self.assertTrue(result.success)
            self.assertTrue(result.verification.evidence["replay_recovered"])
            self.assertEqual(
                result.observations[-1].data["local_path"],
                str(path.resolve()),
            )

    @unittest.skipUnless(os.name == "nt", "Windows screen capture is Windows-only")
    def test_screen_capture_mismatched_body_hash_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ZN_AGENT_HOME": tmp},
        ):
            path = screen_capture_artifact_path("event-screen-mismatch")
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (9, 7), (7, 8, 9)).save(path)

            body = _FakeBody()
            body.handlers["windows_screen_capture"] = (
                lambda kind, event_id, args: BodyActionResult(
                    action_id="body-mismatch",
                    kind=kind,
                    success=True,
                    data={
                        "dispatch_sent": True,
                        "local_path": str(path),
                        "sha256": "0" * 64,
                    },
                    event_id=event_id,
                )
            )
            result = self._screen_runtime(body).execute(
                ActionRequest(
                    "windows.screen.capture",
                    event_id="event-screen-mismatch",
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.status, "failed")
            self.assertIn("sha256", result.verification.evidence["mismatched_fields"])

    def test_volume_dispatch_success_is_not_completion_without_fresh_readback(self) -> None:
        body = _FakeBody()
        body.handlers["windows_audio_volume_set"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-set",
                kind=kind,
                success=True,
                data={"verified": True, "observed_level_percent": 30},
                event_id=event_id,
            )
        )
        body.handlers["windows_audio_volume_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read",
                kind=kind,
                success=True,
                data={"level_percent": 70},
                event_id=event_id,
            )
        )
        runtime = self._volume_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.audio.volume.set",
                {"level_percent": 30},
                event_id="event-volume-1",
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.verification.status, "failed")
        self.assertEqual(
            [call[0] for call in body.calls],
            ["windows_audio_volume_set", "windows_audio_volume_read"],
        )
        self.assertEqual(result.observations[-1].data["level_percent"], 70)

    def test_volume_is_verified_only_from_independent_readback(self) -> None:
        body = _FakeBody()
        body.handlers["windows_audio_volume_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read",
                kind=kind,
                success=True,
                data={"level_percent": 30.2},
                event_id=event_id,
            )
        )
        runtime = self._volume_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.audio.volume.set",
                {"level_percent": 30},
                event_id="event-volume-2",
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertLessEqual(
            abs(result.observations[-1].data["level_percent"] - 30),
            0.5,
        )

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=30.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        side_effect=[10.0, 30.0],
    )
    def test_replay_blocked_volume_recovers_by_observation_without_redispatch(
        self,
        read_volume,
        set_volume,
    ) -> None:
        descriptor = ActionDescriptor(
            action_id="windows.audio.volume.set",
            provider="zn.windows",
            description="Set volume",
            body_action_kind="windows_audio_volume_set",
            effect_class="reversible_side_effect",
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = WindowsCompanionAwareBody(
                store=store,
                device_capabilities=SimpleNamespace(),
            )
            runtime = build_machine_action_execution_runtime(
                _registry(descriptor),
                body,
                device_capabilities=None,
            )
            try:
                first = body.act(
                    "windows_audio_volume_set",
                    event_id="event-volume-crash",
                    level_percent=30,
                )
                attempt_id = first.data["side_effect_attempt_id"]
                result = runtime.execute(
                    ActionRequest(
                        "windows.audio.volume.set",
                        {"level_percent": 30},
                        event_id="event-volume-crash",
                    )
                )
                attempt = ResidentSideEffectJournal(store).attempt(attempt_id)
            finally:
                store.close()

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertTrue(result.body_result.data["replay_blocked"])
        self.assertEqual(attempt["status"], "observed")
        set_volume.assert_called_once_with(30.0)
        self.assertEqual(read_volume.call_count, 2)

    def test_brightness_dispatch_success_is_not_completion_without_fresh_readback(self) -> None:
        body = _FakeBody()
        body.handlers["windows_display_brightness_set"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-set-brightness",
                kind=kind,
                success=True,
                data={
                    "verified": True,
                    "instance_name": "DISPLAY\\PANEL",
                    "observed_level_percent": 30,
                },
                event_id=event_id,
            )
        )
        body.handlers["windows_display_brightness_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read-brightness",
                kind=kind,
                success=True,
                data={"instance_name": "DISPLAY\\PANEL", "level_percent": 70},
                event_id=event_id,
            )
        )
        runtime = self._brightness_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.display.brightness.set",
                {"level_percent": 30},
                event_id="event-brightness-1",
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertEqual(
            [call[0] for call in body.calls],
            ["windows_display_brightness_set", "windows_display_brightness_read"],
        )
        self.assertEqual(result.observations[-1].data["level_percent"], 70)

    def test_brightness_is_verified_only_from_independent_readback(self) -> None:
        body = _FakeBody()
        body.handlers["windows_display_brightness_set"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-set-brightness",
                kind=kind,
                success=True,
                data={
                    "dispatch_sent": True,
                    "instance_name": "DISPLAY\\PANEL",
                    "observed_level_percent": 30,
                },
                event_id=event_id,
            )
        )
        body.handlers["windows_display_brightness_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read-brightness",
                kind=kind,
                success=True,
                data={"instance_name": "DISPLAY\\PANEL", "level_percent": 30},
                event_id=event_id,
            )
        )
        runtime = self._brightness_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.display.brightness.set",
                {"level_percent": 30},
                event_id="event-brightness-2",
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.observations[-1].data["instance_name"], "DISPLAY\\PANEL")
        self.assertEqual(result.observations[-1].data["level_percent"], 30)

    def test_brightness_verification_rejects_monitor_identity_drift(self) -> None:
        body = _FakeBody()
        body.handlers["windows_display_brightness_set"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-set-brightness",
                kind=kind,
                success=True,
                data={"dispatch_sent": True, "instance_name": "DISPLAY\\OLD"},
                event_id=event_id,
            )
        )
        body.handlers["windows_display_brightness_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read-brightness",
                kind=kind,
                success=True,
                data={"instance_name": "DISPLAY\\NEW", "level_percent": 30},
                event_id=event_id,
            )
        )
        runtime = self._brightness_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.display.brightness.set",
                {"level_percent": 30},
                event_id="event-brightness-identity-drift",
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertIn("different monitor identity", result.error or "")

    def test_post_dispatch_brightness_uncertainty_can_recover_same_monitor_by_observation(self) -> None:
        body = _FakeBody()
        body.handlers["windows_display_brightness_set"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-set-brightness",
                kind=kind,
                success=False,
                data={
                    "dispatch_sent": True,
                    "side_effect_uncertain": True,
                    "instance_name": "DISPLAY\\PANEL",
                },
                error="post-dispatch readback unavailable",
                event_id=event_id,
            )
        )
        body.handlers["windows_display_brightness_read"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-read-brightness",
                kind=kind,
                success=True,
                data={"instance_name": "DISPLAY\\PANEL", "level_percent": 30},
                event_id=event_id,
            )
        )
        runtime = self._brightness_runtime(body)

        result = runtime.execute(
            ActionRequest(
                "windows.display.brightness.set",
                {"level_percent": 30},
                event_id="event-brightness-uncertain",
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertEqual(
            [call[0] for call in body.calls],
            ["windows_display_brightness_set", "windows_display_brightness_read"],
        )

    @patch(
        "zn_agent.core.windows_companion_body.set_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\PANEL", 30.0),
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_active_brightness",
        side_effect=[
            WindowsBrightnessObservation("DISPLAY\\PANEL", 10.0),
            WindowsBrightnessObservation("DISPLAY\\PANEL", 30.0),
        ],
    )
    def test_replay_blocked_brightness_without_original_monitor_identity_fails_closed(
        self,
        read_brightness,
        set_brightness,
    ) -> None:
        descriptor = ActionDescriptor(
            action_id="windows.display.brightness.set",
            provider="zn.windows",
            description="Set brightness",
            body_action_kind="windows_display_brightness_set",
            effect_class="reversible_side_effect",
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = WindowsCompanionAwareBody(
                store=store,
                device_capabilities=SimpleNamespace(),
            )
            runtime = build_machine_action_execution_runtime(
                _registry(descriptor),
                body,
                device_capabilities=None,
            )
            try:
                first = body.act(
                    "windows_display_brightness_set",
                    event_id="event-brightness-crash",
                    level_percent=30,
                )
                attempt_id = first.data["side_effect_attempt_id"]
                result = runtime.execute(
                    ActionRequest(
                        "windows.display.brightness.set",
                        {"level_percent": 30},
                        event_id="event-brightness-crash",
                    )
                )
                attempt = ResidentSideEffectJournal(store).attempt(attempt_id)
            finally:
                store.close()

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.body_result.data["replay_blocked"])
        self.assertIn("original monitor identity", result.error or "")
        self.assertEqual(attempt["status"], "observed")
        set_brightness.assert_called_once_with(
            30.0,
            expected_instance_name="DISPLAY\\PANEL",
        )
        self.assertEqual(read_brightness.call_count, 2)

    def test_launch_pending_reverification_never_redispatches(self) -> None:
        descriptor = ActionDescriptor(
            action_id="windows.application.launch",
            provider="zn.windows",
            description="Launch application",
            body_action_kind="launch_application",
            effect_class="potential_side_effect",
        )
        body = _FakeBody()
        graph = _FakeGraph()
        runtime = build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=graph,
        )

        first = runtime.execute(
            ActionRequest(
                "windows.application.launch",
                {"application_id": "app.demo"},
                event_id="event-launch-1",
            )
        )
        self.assertFalse(first.success)
        self.assertEqual(first.status, "pending")
        self.assertEqual(len(body.calls), 1)

        graph.processes = (
            SimpleNamespace(process_id=41, resolved_app_id="app.demo"),
        )
        graph.windows_rows = (
            SimpleNamespace(
                hwnd=99,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
            ),
        )

        checkpoint = runtime.reverification_checkpoint(first)
        second = runtime.verify_checkpoint(checkpoint)

        self.assertTrue(second.success)
        self.assertEqual(second.status, "verified")
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(len(second.observations), 2)
        self.assertEqual(second.observations[-1].data["process_ids"], [41])
        self.assertEqual(
            second.observations[-1].data["visible_window_handles"],
            [99],
        )

    def test_activation_reverification_requires_exact_admitted_foreground_window(self) -> None:
        descriptor = ActionDescriptor(
            action_id="windows.application.activate",
            provider="zn.windows",
            description="Activate application",
            body_action_kind="activate_application_window",
            effect_class="potential_side_effect",
        )
        body = _FakeBody()
        body.handlers["activate_application_window"] = (
            lambda kind, event_id, args: BodyActionResult(
                action_id="body-activate",
                kind=kind,
                success=True,
                data={
                    "dispatch_sent": True,
                    "window_handle": 99,
                    "process_id": 41,
                },
                event_id=event_id,
            )
        )
        graph = _FakeGraph()
        graph.processes = (
            SimpleNamespace(process_id=41, resolved_app_id="app.demo"),
        )
        graph.windows_rows = (
            SimpleNamespace(
                hwnd=99,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
                foreground=False,
            ),
        )
        runtime = build_machine_action_execution_runtime(
            _registry(descriptor),
            body,
            device_capabilities=graph,
        )

        first = runtime.execute(
            ActionRequest(
                "windows.application.activate",
                {"application_id": "app.demo"},
                event_id="event-activate-1",
            )
        )
        self.assertEqual(first.status, "pending")
        self.assertEqual(len(body.calls), 1)

        graph.windows_rows = (
            SimpleNamespace(
                hwnd=100,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
                foreground=True,
            ),
            SimpleNamespace(
                hwnd=99,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
                foreground=False,
            ),
        )
        sibling = runtime.verify(first)
        self.assertEqual(sibling.status, "pending")

        graph.windows_rows = (
            SimpleNamespace(
                hwnd=99,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
                foreground=True,
            ),
        )
        verified = runtime.verify(sibling)
        self.assertTrue(verified.success)
        self.assertEqual(verified.status, "verified")
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(
            verified.verification.evidence["expected_window_handle"],
            99,
        )



class ProductActionExecutionIntegrationTests(unittest.TestCase):
    def test_final_resident_exposes_executor_over_same_fabric_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIs(
                    resident.action_executor.fabric,
                    resident.action_fabric,
                )
                self.assertIs(
                    resident.action_executor.body,
                    resident.body,
                )
                self.assertIsNotNone(
                    resident.action_fabric.descriptor("windows.context.read")
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

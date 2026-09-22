from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
    build_machine_action_fabric,
)
from zn_agent.core.windows_brightness import WindowsBrightnessObservation
from zn_agent.core.windows_wifi import (
    WindowsWifiInterfaceObservation,
    WindowsWifiObservation,
)


class ActionFabricRegistryTests(unittest.TestCase):
    @staticmethod
    def _descriptor(
        action_id: str,
        *,
        provider: str = "zn.windows",
        tags: tuple[str, ...] = ("windows", "system"),
    ) -> ActionDescriptor:
        return ActionDescriptor(
            action_id=action_id,
            provider=provider,
            description=f"Perform {action_id}",
            input_schema={"type": "object"},
            effect_class="potential_side_effect",
            required_authority=("body_action", "body_action"),
            preconditions=("windows",),
            verification=("observe_postcondition",),
            reversibility="action_specific",

            replay_semantics="verify_before_replay",
            tags=tags,
        )

    def test_descriptor_normalizes_contract_without_aliasing_schema(self) -> None:
        schema = {"type": "object"}
        descriptor = self._descriptor(" windows.volume.set ")
        descriptor = ActionDescriptor(
            action_id=descriptor.action_id,
            provider=" zn.windows ",
            description="  Set   system volume  ",
            body_action_kind=" Set_Volume ",
            input_schema=schema,
            required_authority=("body_action", "body_action", ""),
            tags=("windows", "audio", "audio"),
        )
        schema["type"] = "changed"

        self.assertEqual(descriptor.action_id, "windows.volume.set")
        self.assertEqual(descriptor.provider, "zn.windows")
        self.assertEqual(descriptor.description, "Set system volume")
        self.assertEqual(descriptor.body_action_kind, "set_volume")
        self.assertEqual(descriptor.input_schema["type"], "object")
        self.assertEqual(descriptor.required_authority, ("body_action",))
        self.assertEqual(descriptor.tags, ("windows", "audio"))

    def test_duplicate_action_owner_fails_closed(self) -> None:
        registry = ActionFabricRegistry()
        registry.register(self._descriptor("windows.volume.set"))

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(
                self._descriptor(
                    "windows.volume.set",
                    provider="third.party",
                )
            )

    def test_registered_without_probe_is_unknown_not_available(self) -> None:
        registry = ActionFabricRegistry()
        registry.register(self._descriptor("windows.bluetooth.set"))

        result = registry.availability("windows.bluetooth.set")

        self.assertFalse(result.available)
        self.assertEqual(result.state, "unknown")
        self.assertIn("no current availability probe", result.reason)

    def test_probe_can_publish_current_available_evidence(self) -> None:
        registry = ActionFabricRegistry()
        descriptor = self._descriptor("windows.volume.set")

        def probe(current: ActionDescriptor) -> ActionAvailability:
            return ActionAvailability(
                current.action_id,
                "available",
                evidence={"endpoint_count": 2, "source": "windows-core-audio"},
            )

        registry.register(descriptor, availability_probe=probe)

        result = registry.availability(descriptor.action_id)

        self.assertTrue(result.available)
        self.assertEqual(result.state, "available")
        self.assertEqual(result.evidence["endpoint_count"], 2)

    def test_probe_failure_degrades_to_unknown(self) -> None:
        registry = ActionFabricRegistry()

        def broken(_descriptor: ActionDescriptor) -> ActionAvailability:
            raise RuntimeError("boom")

        registry.register(
            self._descriptor("windows.display.brightness.set"),
            availability_probe=broken,
        )
        result = registry.availability("windows.display.brightness.set")

        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.reason, "availability probe failed: RuntimeError")

    def test_probe_cannot_publish_evidence_for_another_action(self) -> None:
        registry = ActionFabricRegistry()
        registry.register(
            self._descriptor("windows.camera.set"),
            availability_probe=lambda _descriptor: ActionAvailability(
                "windows.microphone.set",
                "available",
            ),

        )

        result = registry.availability("windows.camera.set")

        self.assertEqual(result.state, "unknown")
        self.assertIn("different action", result.reason)

    def test_descriptor_queries_are_deterministic_and_tag_scoped(self) -> None:
        registry = ActionFabricRegistry()
        registry.register(
            self._descriptor(
                "windows.volume.set",
                tags=("windows", "audio"),
            )
        )
        registry.register(
            self._descriptor(
                "windows.bluetooth.set",
                tags=("windows", "radio"),
            )
        )
        registry.register(
            self._descriptor(
                "browser.navigate",
                provider="zn.browser",
                tags=("browser", "web"),
            )
        )

        self.assertEqual(
            tuple(item.action_id for item in registry.descriptors(provider="zn.windows")),
            ("windows.bluetooth.set", "windows.volume.set"),
        )

        self.assertEqual(
            tuple(item.action_id for item in registry.descriptors(tags=("windows",))),
            ("windows.bluetooth.set", "windows.volume.set"),
        )
        self.assertEqual(
            tuple(item.action_id for item in registry.descriptors(tags=("audio",))),
            ("windows.volume.set",),
        )
        self.assertEqual(
            registry.names(),
            ("browser.navigate", "windows.bluetooth.set", "windows.volume.set"),
        )

    def test_unregister_removes_descriptor_and_probe(self) -> None:
        registry = ActionFabricRegistry()
        registry.register(
            self._descriptor("windows.volume.set"),
            availability_probe=lambda descriptor: ActionAvailability(
                descriptor.action_id,
                "available",
            ),
        )
        registry.unregister("windows.volume.set")

        self.assertIsNone(registry.descriptor("windows.volume.set"))
        with self.assertRaises(KeyError):
            registry.availability("windows.volume.set")

class MachineActionFabricTests(unittest.TestCase):
    class _Graph:
        def __init__(self) -> None:
            self.apps = [SimpleNamespace(launchable=True)]
            self.processes = [SimpleNamespace(process_id=7)]
            self.window_rows = []
            self.platform_supported = True

        def installed_applications(self):
            return tuple(self.apps)

        def running_processes(self):
            return tuple(self.processes)

        def windows(self, *, processes):
            self.last_processes = tuple(processes)
            return tuple(self.window_rows)

        def companion_context(self):
            return SimpleNamespace(
                session=SimpleNamespace(
                    platform_supported=self.platform_supported,
                )
            )

    def test_machine_catalog_maps_semantics_to_existing_body_kinds(self) -> None:
        registry = build_machine_action_fabric(self._Graph())

        self.assertEqual(
            registry.names(),
            (
                "windows.application.activate",
                "windows.application.launch",
                "windows.audio.volume.read",
                "windows.audio.volume.set",
                "windows.context.read",
                "windows.desktop.scene.capture",
                "windows.display.brightness.read",
                "windows.display.brightness.set",
                "windows.network.wifi.read",
                "windows.office.excel.cell.read",
                "windows.office.excel.cell.set",
                "windows.office.session.read",
                "windows.office.word.selection.read",
                "windows.office.word.selection.set_text",
                "windows.screen.capture",
                "windows.ui.control.expand_collapse",
                "windows.ui.control.read",
                "windows.ui.control.select",
                "windows.ui.control.set_value",
                "windows.ui.control.toggle",
                "windows.ui.controls.list",
            ),
        )
        self.assertEqual(
            registry.descriptor("windows.application.launch").body_action_kind,
            "launch_application",
        )
        self.assertEqual(
            registry.descriptor("windows.application.activate").body_action_kind,
            "activate_application_window",
        )
        self.assertEqual(
            registry.descriptor("windows.context.read").body_action_kind,
            "windows_companion_context",
        )
        self.assertEqual(
            registry.descriptor("windows.audio.volume.read").body_action_kind,
            "windows_audio_volume_read",
        )
        self.assertEqual(
            registry.descriptor("windows.audio.volume.set").body_action_kind,
            "windows_audio_volume_set",
        )
        self.assertEqual(
            registry.descriptor("windows.display.brightness.read").body_action_kind,
            "windows_display_brightness_read",
        )
        self.assertEqual(
            registry.descriptor("windows.display.brightness.set").body_action_kind,
            "windows_display_brightness_set",
        )
        self.assertEqual(
            registry.descriptor("windows.network.wifi.read").body_action_kind,
            "windows_network_wifi_read",
        )
        self.assertEqual(
            registry.descriptor("windows.screen.capture").body_action_kind,
            "windows_screen_capture",
        )

    def test_machine_availability_tracks_fresh_graph_evidence(self) -> None:
        graph = self._Graph()
        registry = build_machine_action_fabric(graph)

        self.assertTrue(registry.availability("windows.application.launch").available)
        self.assertEqual(
            registry.availability("windows.application.activate").state,
            "unavailable",
        )
        graph.window_rows.append(
            SimpleNamespace(visible=True, resolved_app_id="app-1")
        )
        self.assertTrue(
            registry.availability("windows.application.activate").available
        )

    @patch(
        "zn_agent.core.action_fabric.read_default_render_volume_percent",
        return_value=44.0,
    )
    def test_audio_actions_share_one_fresh_core_audio_availability_probe(
        self,
        read_volume,
    ) -> None:
        registry = build_machine_action_fabric(self._Graph())

        read_state = registry.availability("windows.audio.volume.read")
        set_state = registry.availability("windows.audio.volume.set")

        self.assertTrue(read_state.available)
        self.assertTrue(set_state.available)
        self.assertEqual(read_state.evidence["current_level_percent"], 44.0)
        self.assertEqual(set_state.evidence["current_level_percent"], 44.0)
        self.assertEqual(read_volume.call_count, 2)

    @patch(
        "zn_agent.core.action_fabric.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\PANEL", 88.0),
    )
    def test_brightness_actions_share_one_fresh_wmi_availability_probe(
        self,
        read_brightness,
    ) -> None:
        registry = build_machine_action_fabric(self._Graph())

        read_state = registry.availability("windows.display.brightness.read")
        set_state = registry.availability("windows.display.brightness.set")

        self.assertTrue(read_state.available)
        self.assertTrue(set_state.available)
        self.assertEqual(read_state.evidence["instance_name"], "DISPLAY\\PANEL")
        self.assertEqual(read_state.evidence["current_level_percent"], 88.0)
        self.assertEqual(set_state.evidence["current_level_percent"], 88.0)
        self.assertEqual(read_brightness.call_count, 2)

    @patch(
        "zn_agent.core.action_fabric.read_windows_wifi_state",
        return_value=WindowsWifiObservation(
            (
                WindowsWifiInterfaceObservation(
                    "Intel Wi-Fi",
                    "connected",
                    True,
                ),
                WindowsWifiInterfaceObservation(
                    "USB Wi-Fi",
                    "disconnected",
                    False,
                ),
            ),
            "2026-09-21T12:00:00Z",
        ),
    )
    def test_wifi_availability_uses_fresh_native_interface_state(
        self,
        read_wifi,
    ) -> None:
        registry = build_machine_action_fabric(self._Graph())

        state = registry.availability("windows.network.wifi.read")

        self.assertTrue(state.available)
        self.assertEqual(state.evidence["interface_count"], 2)
        self.assertEqual(state.evidence["connected_interface_count"], 1)
        self.assertTrue(state.evidence["connected"])
        read_wifi.assert_called_once_with()

    def test_companion_context_fails_closed_when_platform_is_unsupported(self) -> None:
        graph = self._Graph()
        graph.platform_supported = False
        result = build_machine_action_fabric(graph).availability(
            "windows.context.read"
        )

        self.assertEqual(result.state, "unavailable")
        self.assertFalse(result.available)


if __name__ == "__main__":
    unittest.main()

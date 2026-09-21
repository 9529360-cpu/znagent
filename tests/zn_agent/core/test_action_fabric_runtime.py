from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.action_fabric import build_machine_action_fabric
from zn_agent.core.provider_bridge import build_resident_runtime


class _FakeGraph:
    def __init__(self) -> None:
        self.apps = [
            SimpleNamespace(launchable=True),
            SimpleNamespace(launchable=False),
        ]
        self.processes = (SimpleNamespace(process_id=7),)
        self.windows_rows = []
        self.platform_supported = True

    def installed_applications(self):
        return tuple(self.apps)

    def running_processes(self):
        return tuple(self.processes)

    def windows(self, *, processes):
        self.last_processes = tuple(processes)
        return tuple(self.windows_rows)
    def companion_context(self):
        return SimpleNamespace(
            session=SimpleNamespace(
                platform_supported=self.platform_supported,
            )
        )


class MachineActionFabricTests(unittest.TestCase):
    def test_builder_maps_semantic_actions_to_existing_body_kinds(self) -> None:
        registry = build_machine_action_fabric(_FakeGraph())

        self.assertEqual(
            registry.names(),
            (
                "windows.application.activate",
                "windows.application.launch",
                "windows.audio.volume.read",
                "windows.audio.volume.set",
                "windows.context.read",
                "windows.display.brightness.read",
                "windows.display.brightness.set",
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

    def test_availability_comes_from_fresh_device_graph_evidence(self) -> None:
        graph = _FakeGraph()
        registry = build_machine_action_fabric(graph)

        self.assertTrue(
            registry.availability("windows.application.launch").available
        )
        self.assertEqual(
            registry.availability("windows.application.activate").state,
            "unavailable",
        )

        graph.windows_rows.append(
            SimpleNamespace(visible=True, resolved_app_id="app-1")
        )
        self.assertTrue(
            registry.availability("windows.application.activate").available
        )

        graph.platform_supported = False
        context = registry.availability("windows.context.read")
        self.assertEqual(context.state, "unavailable")
        self.assertFalse(context.evidence["platform_supported"])
    def test_launch_fails_closed_without_launchable_identity(self) -> None:
        graph = _FakeGraph()
        graph.apps = [SimpleNamespace(launchable=False)]
        result = build_machine_action_fabric(graph).availability(
            "windows.application.launch"
        )

        self.assertEqual(result.state, "unavailable")
        self.assertEqual(result.evidence["launchable_application_count"], 0)


class ProductActionFabricIntegrationTests(unittest.TestCase):
    def test_final_resident_exposes_one_windows_action_fabric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident.action_fabric.names(),
                    (
                        "windows.application.activate",
                        "windows.application.launch",
                        "windows.audio.volume.read",
                        "windows.audio.volume.set",
                        "windows.context.read",
                        "windows.display.brightness.read",
                        "windows.display.brightness.set",
                    ),
                )
                self.assertIs(
                    resident.body.device_capabilities,
                    resident.device_capabilities,
                )
                context = resident.action_fabric.descriptor("windows.context.read")
                self.assertEqual(
                    context.body_action_kind,
                    "windows_companion_context",
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.machine_capability import ApplicationInventoryCandidate


class MachineCapabilityTests(unittest.TestCase):
    def test_source_fusion_uses_executable_identity_not_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "Google" / "Chrome" / "chrome.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            shortcut = root / "Google Chrome.lnk"
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="start_menu", source_id=str(shortcut), display_name="Google Chrome",
                        executable_path=str(executable), identity_paths=(str(executable),),
                        launch_kind="shell_item", launch_target=str(shortcut),
                    ),
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="hklm:chrome", display_name="chrome",
                        executable_path=str(executable), identity_paths=(str(executable),),
                        launch_kind="executable", launch_target=str(executable),
                    ),
                    ApplicationInventoryCandidate(
                        source="uninstall_registry", source_id="hklm:chrome-uninstall",
                        display_name="Google Chrome", identity_paths=(str(executable),),
                        version="123", publisher="Google LLC",
                    ),
                ],
                cache_path=root / "cache.json", inventory_ttl_seconds=0,
            )
            apps = graph.installed_applications(force_refresh=True)
            self.assertEqual(len(apps), 1)
            app = apps[0]
            self.assertEqual(app.canonical_name, "Google Chrome")
            self.assertEqual(set(app.evidence_source), {"start_menu", "app_paths", "uninstall_registry"})
            self.assertIn("browser", app.capabilities)
            self.assertEqual(graph.resolve_application("Chrome").application.app_id, app.app_id)

    def test_same_name_different_executables_stays_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "one" / "tool.exe"
            second = root / "two" / "tool.exe"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"")
            second.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="one", display_name="Tool",
                        executable_path=str(first), identity_paths=(str(first),),
                        launch_kind="executable", launch_target=str(first),
                    ),
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="two", display_name="Tool",
                        executable_path=str(second), identity_paths=(str(second),),
                        launch_kind="executable", launch_target=str(second),
                    ),
                ],
                cache_path=root / "cache.json", inventory_ttl_seconds=0,
            )
            result = graph.resolve_application("Tool", force_refresh=True)
            self.assertEqual(result.status, "ambiguous")
            self.assertEqual(len(result.candidates), 2)
            self.assertNotEqual(result.candidates[0].app_id, result.candidates[1].app_id)

    def test_known_profile_prefers_unique_runtime_bindable_primary_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / "WindowsApps" / "Notepad.exe"
            alias = root / "Windows" / "notepad.exe"
            primary.parent.mkdir(parents=True)
            alias.parent.mkdir(parents=True)
            primary.write_bytes(b"")
            alias.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="apps_folder",
                        source_id="notepad-aumid",
                        display_name="记事本",
                        aumid="Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
                        package_identity="Microsoft.WindowsNotepad_8wekyb3d8bbwe",
                        launch_kind="aumid",
                        launch_target="Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
                    ),
                    ApplicationInventoryCandidate(
                        source="app_paths",
                        source_id="notepad-primary",
                        display_name="Notepad",
                        executable_path=str(primary),
                        identity_paths=(str(primary),),
                        launch_kind="executable",
                        launch_target=str(primary),
                    ),
                    ApplicationInventoryCandidate(
                        source="path",
                        source_id="notepad-alias",
                        display_name="notepad",
                        executable_path=str(alias),
                        identity_paths=(str(alias),),
                        launch_kind="executable",
                        launch_target=str(alias),
                    ),
                ],
                cache_path=root / "cache.json",
                inventory_ttl_seconds=0,
            )
            apps = graph.installed_applications(force_refresh=True)
            self.assertEqual(len(apps), 3)

            for query in ("Notepad", "记事本"):
                result = graph.resolve_application(query, force_refresh=True)
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.application.executable_path, str(primary))
                self.assertEqual(result.application.evidence_source, ("app_paths",))

    def test_powershell_ise_profile_prefers_runtime_bindable_executable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "WindowsPowerShell" / "v1.0" / "powershell_ise.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="apps_folder",
                        source_id="ise-aumid",
                        display_name="Windows PowerShell ISE",
                        aumid=(
                            "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
                            "\\WindowsPowerShell\\v1.0\\PowerShell_ISE.exe"
                        ),
                        launch_kind="aumid",
                        launch_target=(
                            "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
                            "\\WindowsPowerShell\\v1.0\\PowerShell_ISE.exe"
                        ),
                    ),
                    ApplicationInventoryCandidate(
                        source="path",
                        source_id="ise-executable",
                        display_name="powershell_ise",
                        executable_path=str(executable),
                        identity_paths=(str(executable),),
                        launch_kind="executable",
                        launch_target=str(executable),
                    ),
                ],
                cache_path=root / "cache.json",
                inventory_ttl_seconds=0,
            )

            result = graph.resolve_application(
                "Windows PowerShell ISE",
                force_refresh=True,
            )
            self.assertEqual(result.status, "resolved")
            self.assertEqual(result.application.executable_path, str(executable))
            self.assertEqual(
                result.application.canonical_name,
                "Windows PowerShell ISE",
            )

    def test_exact_alias_wins_over_longer_fuzzy_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            visual_studio = root / "VisualStudio" / "devenv.exe"
            vscode = root / "VSCode" / "code.exe"
            visual_studio.parent.mkdir(parents=True)
            vscode.parent.mkdir(parents=True)
            visual_studio.write_bytes(b"")
            vscode.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="vs", display_name="Visual Studio",
                        executable_path=str(visual_studio), identity_paths=(str(visual_studio),),
                        launch_kind="executable", launch_target=str(visual_studio),
                    ),
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="vscode", display_name="Visual Studio Code",
                        executable_path=str(vscode), identity_paths=(str(vscode),),
                        launch_kind="executable", launch_target=str(vscode),
                    ),
                ],
                cache_path=root / "cache.json", inventory_ttl_seconds=0,
            )
            result = graph.resolve_application("Visual Studio", force_refresh=True)
            self.assertEqual(result.status, "resolved")
            self.assertEqual(result.application.canonical_name, "Visual Studio")

    def test_partial_prefix_collision_stays_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            visual_studio = root / "VisualStudio" / "devenv.exe"
            vscode = root / "VSCode" / "code.exe"
            visual_studio.parent.mkdir(parents=True)
            vscode.parent.mkdir(parents=True)
            visual_studio.write_bytes(b"")
            vscode.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="vs", display_name="Visual Studio",
                        executable_path=str(visual_studio), identity_paths=(str(visual_studio),),
                        launch_kind="executable", launch_target=str(visual_studio),
                    ),
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="vscode", display_name="Visual Studio Code",
                        executable_path=str(vscode), identity_paths=(str(vscode),),
                        launch_kind="executable", launch_target=str(vscode),
                    ),
                ],
                cache_path=root / "cache.json", inventory_ttl_seconds=0,
            )
            result = graph.resolve_application("Visual", force_refresh=True)
            self.assertEqual(result.status, "ambiguous")
            self.assertEqual(
                {item.canonical_name for item in result.candidates},
                {"Visual Studio", "Visual Studio Code"},
            )

    def test_known_alias_never_invents_executable_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "WeChat.exe"
            executable.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="wechat", display_name="WeChat",
                        executable_path=str(executable), identity_paths=(str(executable),),
                        launch_kind="executable", launch_target=str(executable),
                    )
                ],
                cache_path=Path(tmp) / "cache.json", inventory_ttl_seconds=0,
            )
            result = graph.resolve_application("微信", force_refresh=True)
            self.assertEqual(result.status, "resolved")
            self.assertEqual(result.application.executable_path, str(executable))
            self.assertIn("messaging", result.application.capabilities)

    def test_long_unknown_application_is_not_installed(self) -> None:
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [], cache_path=None, inventory_ttl_seconds=0
        )
        result = graph.resolve_application("ZN Definitely Missing Application 7f4f42d7", force_refresh=True)
        self.assertEqual(result.status, "not_installed")
        self.assertIsNone(result.application)
        self.assertEqual(result.candidates, ())

    def test_long_unknown_suffix_does_not_inherit_short_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            executable.write_bytes(b"")
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="notepad", display_name="Notepad",
                        executable_path=str(executable), identity_paths=(str(executable),),
                        launch_kind="executable", launch_target=str(executable),
                    )
                ],
                cache_path=Path(tmp) / "cache.json", inventory_ttl_seconds=0,
            )
            result = graph.resolve_application("Notepad Definitely Missing Edition", force_refresh=True)
            self.assertEqual(result.status, "not_installed")

    def test_installed_running_and_foreground_are_distinct_fresh_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "notepad.exe"
            executable.write_bytes(b"")
            processes: list[dict] = []
            windows: list[dict] = []
            graph = DeviceCapabilityGraph(
                inventory_provider=lambda: [
                    ApplicationInventoryCandidate(
                        source="app_paths", source_id="notepad", display_name="Notepad",
                        executable_path=str(executable), identity_paths=(str(executable),),
                        launch_kind="executable", launch_target=str(executable),
                    )
                ],
                process_provider=lambda: list(processes),
                window_provider=lambda: list(windows),
                cache_path=Path(tmp) / "cache.json", inventory_ttl_seconds=0,
            )
            app = graph.installed_applications(force_refresh=True)[0]
            self.assertEqual(graph.application_runtime(app), ((), ()))
            self.assertIsNone(graph.foreground_application())

            processes.append({"pid": 4242, "name": "notepad.exe", "exe": str(executable)})
            running, app_windows = graph.application_runtime(app)
            self.assertEqual([row.process_id for row in running], [4242])
            self.assertEqual(app_windows, ())
            self.assertIsNone(graph.foreground_application())

            windows.append({
                "hwnd": 9001, "pid": 4242, "title": "notes.txt - Notepad",
                "class_name": "Notepad", "visible": True, "foreground": True,
            })
            foreground = graph.foreground_application()
            self.assertIsNotNone(foreground)
            self.assertEqual(foreground.window.hwnd, 9001)
            self.assertEqual(foreground.process.process_id, 4242)
            self.assertEqual(foreground.application.app_id, app.app_id)


if __name__ == "__main__":
    unittest.main()

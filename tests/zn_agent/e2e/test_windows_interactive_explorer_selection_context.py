from __future__ import annotations

import ctypes
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.device_capability_graph import (
    DeviceCapabilityGraph,
    ResidentDeviceContextSnapshot,
)

import test_windows_interactive_text_entry as text_entry_e2e


class WindowsInteractiveExplorerSelectionContextE2ETests(unittest.TestCase):
    def test_foreground_explorer_selected_file_is_observed_on_demand_only(self) -> None:
        text_entry_e2e.WindowsInteractiveTextEntryE2ETests._require_input_desktop()

        with tempfile.TemporaryDirectory(prefix="zn-explorer-selection-") as tmp:
            root = Path(tmp)
            selected = root / "selected-context.txt"
            secret = "ZN_EXPLORER_SELECTION_CONTENT_MUST_NOT_BE_READ"
            selected.write_text(secret, encoding="utf-8")

            graph = DeviceCapabilityGraph(cache_path=None, inventory_ttl_seconds=0)
            observed = None
            subprocess.Popen(
                ["explorer.exe", "/select," + str(selected)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 15
                last = None
                while time.monotonic() < deadline:
                    last = graph.explorer_selection_context()
                    item = last.single_item
                    if (
                        last.available
                        and last.disposition == "ready"
                        and last.selected_count == 1
                        and item is not None
                        and not item.is_folder
                    ):
                        try:
                            if Path(item.path).resolve() == selected.resolve():
                                observed = last
                                break
                        except OSError:
                            pass
                    time.sleep(0.05)

                self.assertIsNotNone(
                    observed,
                    "foreground Explorer never exposed the owned selected file; "
                    + repr(last),
                )
                assert observed is not None
                self.assertTrue(observed.platform_supported)
                self.assertTrue(observed.available)
                self.assertEqual(observed.disposition, "ready")
                self.assertEqual(observed.selected_count, 1)
                self.assertGreater(int(observed.foreground_process_id or 0), 0)
                self.assertGreater(int(observed.foreground_window_handle or 0), 0)
                self.assertIn("shell-folder-view-selected-items", observed.source)
                self.assertIsNotNone(observed.single_item)
                assert observed.single_item is not None
                self.assertEqual(Path(observed.single_item.path).resolve(), selected.resolve())
                self.assertEqual(observed.single_item.name, selected.name)
                self.assertEqual(observed.single_item.kind, "file")
                self.assertNotIn(secret, repr(observed))

                # Raw Explorer selection is intentionally not ambient Work/device
                # snapshot context. A caller must explicitly request this sense.
                self.assertNotIn(
                    "explorer_selection",
                    ResidentDeviceContextSnapshot.__annotations__,
                )
                self.assertNotIn("selected", ResidentDeviceContextSnapshot.__annotations__)
            finally:
                if observed is not None and int(observed.foreground_window_handle or 0) > 0:
                    # Close only the exact Explorer view that proved our owned
                    # temp file was selected; never close an unrelated foreground
                    # window during cleanup.
                    try:
                        user32 = ctypes.WinDLL("user32", use_last_error=True)
                        user32.PostMessageW.argtypes = [
                            wintypes.HWND,
                            wintypes.UINT,
                            wintypes.WPARAM,
                            wintypes.LPARAM,
                        ]
                        user32.PostMessageW.restype = wintypes.BOOL
                        user32.PostMessageW(
                            wintypes.HWND(int(observed.foreground_window_handle)),
                            0x0010,  # WM_CLOSE
                            0,
                            0,
                        )
                    except Exception:
                        pass


if __name__ == "__main__":
    unittest.main()

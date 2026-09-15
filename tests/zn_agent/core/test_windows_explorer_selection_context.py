from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import (
    DeviceCapabilityGraph,
    ResidentDeviceContextSnapshot,
)
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.windows_explorer_selection_context import (
    NativeWindowsExplorerSelectionSense,
    WindowsExplorerSelectionObservation,
    explorer_selection_changed,
)


def _foreground(
    *,
    process_name: str = "explorer.exe",
    class_name: str = "CabinetWClass",
    process_id: int = 4242,
    window_handle: int = 101,
) -> NativeForegroundWindowSense:
    return NativeForegroundWindowSense(
        probe_fn=lambda: ForegroundWindowObservation(
            process_id=process_id,
            title="Explorer Fixture",
            process_name=process_name,
            class_name=class_name,
            captured_at="2026-09-15T12:00:00Z",
            window_handle=window_handle,
        )
    )


def _sense(raw, **foreground_kwargs) -> NativeWindowsExplorerSelectionSense:
    return NativeWindowsExplorerSelectionSense(
        foreground_sense=_foreground(**foreground_kwargs),
        selection_probe=lambda _hwnd: raw,
    )


class WindowsExplorerSelectionContextTests(unittest.TestCase):
    def test_non_explorer_foreground_short_circuits_without_shell_probe(self) -> None:
        calls = []
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_foreground(process_name="notepad.exe"),
            selection_probe=lambda hwnd: calls.append(hwnd) or {},
        )

        observation = sense.probe()

        self.assertFalse(observation.available)
        self.assertEqual(observation.disposition, "foreground_not_explorer")
        self.assertEqual(observation.foreground_process_id, 4242)
        self.assertEqual(observation.foreground_window_handle, 101)
        self.assertEqual(calls, [])

    def test_exact_foreground_explorer_returns_one_filesystem_file(self) -> None:
        observation = _sense(
            {
                "matched_window": True,
                "selected_count": 1,
                "items": (
                    {
                        "path": r"C:\Users\Fixture\invoice.txt",
                        "name": "invoice.txt",
                        "is_file_system": True,
                        "is_folder": False,
                    },
                ),
                "source": (
                    "shell-application-windows",
                    "shell-folder-view-selected-items",
                ),
            }
        ).probe()

        self.assertTrue(observation.platform_supported)
        self.assertTrue(observation.available)
        self.assertEqual(observation.disposition, "ready")
        self.assertEqual(observation.selected_count, 1)
        self.assertEqual(observation.foreground_process_id, 4242)
        self.assertEqual(observation.foreground_window_handle, 101)
        self.assertIsNotNone(observation.single_item)
        assert observation.single_item is not None
        self.assertEqual(observation.single_item.path, r"C:\Users\Fixture\invoice.txt")
        self.assertEqual(observation.single_item.name, "invoice.txt")
        self.assertEqual(observation.single_item.kind, "file")
        self.assertFalse(observation.single_item.is_folder)

    def test_multiple_items_preserve_order_and_change_detector_ignores_timestamp(self) -> None:
        raw = {
            "matched_window": True,
            "selected_count": 2,
            "items": (
                {
                    "path": r"C:\Work\alpha.txt",
                    "name": "alpha.txt",
                    "is_file_system": True,
                    "is_folder": False,
                },
                {
                    "path": r"C:\Work\Folder",
                    "name": "Folder",
                    "is_file_system": True,
                    "is_folder": True,
                },
            ),
        }
        first = _sense(raw).probe()
        same = _sense(raw).probe()
        changed = _sense(
            {
                **raw,
                "items": (
                    raw["items"][0],
                    {
                        "path": r"C:\Work\Other",
                        "name": "Other",
                        "is_file_system": True,
                        "is_folder": True,
                    },
                ),
            }
        ).probe()

        self.assertEqual([item.kind for item in first.items], ["file", "directory"])
        self.assertFalse(explorer_selection_changed(first, same))
        self.assertTrue(explorer_selection_changed(first, changed))

    def test_non_filesystem_item_fails_closed_without_returning_partial_paths(self) -> None:
        observation = _sense(
            {
                "matched_window": True,
                "selected_count": 2,
                "items": (
                    {
                        "path": r"C:\Work\safe.txt",
                        "name": "safe.txt",
                        "is_file_system": True,
                        "is_folder": False,
                    },
                    {
                        "path": "::{virtual-shell-item}",
                        "name": "Virtual",
                        "is_file_system": False,
                        "is_folder": False,
                    },
                ),
            }
        ).probe()

        self.assertFalse(observation.available)
        self.assertEqual(observation.disposition, "selection_contains_non_filesystem_item")
        self.assertEqual(observation.selected_count, 2)
        self.assertEqual(observation.items, ())
        self.assertNotIn(r"C:\Work\safe.txt", repr(observation))

    def test_oversized_selection_fails_closed_without_partial_items(self) -> None:
        observation = _sense(
            {
                "matched_window": True,
                "selected_count": 17,
                "items": (),
            }
        ).probe()

        self.assertFalse(observation.available)
        self.assertEqual(observation.disposition, "selection_too_large")
        self.assertEqual(observation.selected_count, 17)
        self.assertEqual(observation.items, ())

    def test_malformed_duplicate_and_drive_relative_paths_fail_closed(self) -> None:
        cases = (
            (
                {
                    "matched_window": True,
                    "selected_count": 2,
                    "items": (),
                },
                "selection_items_invalid",
            ),
            (
                {
                    "matched_window": True,
                    "selected_count": 2,
                    "items": (
                        {
                            "path": r"C:\Work\Alpha.txt",
                            "name": "Alpha.txt",
                            "is_file_system": True,
                            "is_folder": False,
                        },
                        {
                            "path": r"c:\work\alpha.TXT",
                            "name": "alpha.TXT",
                            "is_file_system": True,
                            "is_folder": False,
                        },
                    ),
                },
                "selection_contains_duplicate_item",
            ),
            (
                {
                    "matched_window": True,
                    "selected_count": 1,
                    "items": (
                        {
                            "path": r"C:relative.txt",
                            "name": "relative.txt",
                            "is_file_system": True,
                            "is_folder": False,
                        },
                    ),
                },
                "selection_item_path_invalid",
            ),
        )
        for raw, disposition in cases:
            with self.subTest(disposition=disposition):
                observation = _sense(raw).probe()
                self.assertFalse(observation.available)
                self.assertEqual(observation.disposition, disposition)
                self.assertEqual(observation.items, ())

    def test_explorer_view_class_is_required_even_for_explorer_process(self) -> None:
        observation = _sense(
            {
                "matched_window": True,
                "selected_count": 0,
                "items": (),
            },
            class_name="Progman",
        ).probe()

        self.assertFalse(observation.available)
        self.assertEqual(observation.disposition, "foreground_not_explorer_view")

    def test_device_graph_exposes_selection_only_on_explicit_demand(self) -> None:
        expected = WindowsExplorerSelectionObservation(
            platform_supported=True,
            available=True,
            disposition="no_selection",
            foreground_process_id=4242,
            foreground_window_handle=101,
            selected_count=0,
            items=(),
            observed_at="2026-09-15T12:00:00Z",
            source=("fixture-selection",),
        )

        class _SelectionSense:
            def __init__(self):
                self.calls = 0

            def probe(self):
                self.calls += 1
                return expected

        selection = _SelectionSense()
        graph = DeviceCapabilityGraph(
            cache_path=None,
            inventory_ttl_seconds=0,
            explorer_selection_sense=selection,
        )

        observed = graph.explorer_selection_context()

        self.assertIs(observed, expected)
        self.assertEqual(selection.calls, 1)
        self.assertNotIn("explorer_selection", ResidentDeviceContextSnapshot.__annotations__)
        self.assertNotIn("selected", ResidentDeviceContextSnapshot.__annotations__)


if __name__ == "__main__":
    unittest.main()

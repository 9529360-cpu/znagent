from __future__ import annotations

import unittest

from zn_agent.core.windows_explorer_selection import (
    NativeWindowsExplorerSelectionSense,
    same_explorer_file_selection,
)
from zn_agent.core.windows_foreground_companion import WindowsForegroundCompanionObservation


class _ForegroundSense:
    def __init__(self, *, process_name: str = "explorer.exe", hwnd: int = 9001) -> None:
        self.process_name = process_name
        self.hwnd = hwnd

    def probe(self) -> WindowsForegroundCompanionObservation:
        return WindowsForegroundCompanionObservation(
            platform_supported=True,
            available=True,
            process_id=4242,
            process_name=self.process_name,
            window_handle=self.hwnd,
            title_chars=0,
            title_sha256=None,
            class_name_chars=0,
            class_name_sha256=None,
            monitor=None,
            observed_at="2026-09-16T00:00:00+00:00",
            source=("fixture",),
        )


class WindowsExplorerSelectionTests(unittest.TestCase):
    @staticmethod
    def _stat(*, size: int = 123, mtime_ns: int = 456):
        return {
            "regular_file": True,
            "size_bytes": size,
            "mtime_ns": mtime_ns,
            "device": 7,
            "inode": 8,
        }

    def test_exact_foreground_single_local_file_is_observed(self) -> None:
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"C:\Users\ZN\report.txt",) if hwnd == 9001 else (),
            stat_probe=lambda path: self._stat() if path.endswith("report.txt") else {},
        )

        observed = sense.probe()

        self.assertTrue(observed.available)
        self.assertTrue(observed.explorer_foreground)
        self.assertEqual(observed.disposition, "selected_local_file")
        self.assertEqual(observed.path, r"C:\Users\ZN\report.txt")
        self.assertEqual(observed.name, "report.txt")
        self.assertEqual(observed.size_bytes, 123)
        self.assertEqual(observed.mtime_ns, 456)
        self.assertEqual(observed.process_id, 4242)
        self.assertEqual(observed.window_handle, 9001)

    def test_non_explorer_foreground_never_reads_shell_selection(self) -> None:
        calls = []
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(process_name="notepad.exe"),
            selection_probe=lambda hwnd: calls.append(hwnd) or (r"C:\secret.txt",),
            stat_probe=lambda path: self._stat(),
        )

        observed = sense.probe()

        self.assertFalse(observed.available)
        self.assertEqual(observed.disposition, "foreground_not_explorer")
        self.assertEqual(calls, [])
        self.assertIsNone(observed.path)

    def test_multiple_selection_fails_closed_without_statting_paths(self) -> None:
        stats = []
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"C:\a.txt", r"C:\b.txt"),
            stat_probe=lambda path: stats.append(path) or self._stat(),
        )

        observed = sense.probe()

        self.assertFalse(observed.available)
        self.assertEqual(observed.disposition, "multiple_selection")
        self.assertEqual(observed.selected_count, 2)
        self.assertEqual(stats, [])
        self.assertIsNone(observed.path)

    def test_unc_selection_is_rejected_before_file_stat(self) -> None:
        stats = []
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"\\server\share\secret.txt",),
            stat_probe=lambda path: stats.append(path) or self._stat(),
        )

        observed = sense.probe()

        self.assertFalse(observed.available)
        self.assertEqual(observed.disposition, "selection_not_local_file_path")
        self.assertEqual(stats, [])
        self.assertIsNone(observed.path)

    def test_directory_or_non_regular_selection_is_rejected(self) -> None:
        sense = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"D:\Work\Folder",),
            stat_probe=lambda path: {"regular_file": False},
        )

        observed = sense.probe()

        self.assertFalse(observed.available)
        self.assertEqual(observed.disposition, "selection_not_regular_file")
        self.assertIsNone(observed.path)

    def test_fresh_revalidation_detects_window_path_or_metadata_drift(self) -> None:
        stable = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"C:\Work\report.txt",),
            stat_probe=lambda path: self._stat(),
        ).probe()
        same = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"c:\work\REPORT.txt",),
            stat_probe=lambda path: self._stat(),
        ).probe()
        changed = NativeWindowsExplorerSelectionSense(
            foreground_sense=_ForegroundSense(),
            selection_probe=lambda hwnd: (r"C:\Work\report.txt",),
            stat_probe=lambda path: self._stat(mtime_ns=999),
        ).probe()

        self.assertTrue(same_explorer_file_selection(stable, same))
        self.assertFalse(same_explorer_file_selection(stable, changed))


if __name__ == "__main__":
    unittest.main()

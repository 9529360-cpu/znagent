from __future__ import annotations

import ctypes
import os
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


TASK = "我在 Windows 文件资源管理器里当前选中的这个文件是什么？告诉我文件名、大小和修改时间。"


class WindowsInteractiveExplorerSelectedFileE2ETests(unittest.TestCase):
    @staticmethod
    def _require_windows_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Explorer selection E2E runs only on Windows")
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0100)
        if not desktop:
            raise unittest.SkipTest("interactive input desktop is unavailable")
        user32.CloseDesktop(desktop)

    @classmethod
    def _open_select_and_foreground(cls, path: Path):
        from ctypes import wintypes
        from comtypes.client import CreateObject

        shell = CreateObject("Shell.Application", dynamic=True)
        before = {
            int(shell.Windows().Item(index).HWND)
            for index in range(int(shell.Windows().Count))
            if shell.Windows().Item(index) is not None
        }
        shell.Explore(str(path.parent))

        wanted_parent = os.path.normcase(os.path.abspath(str(path.parent)))
        deadline = time.monotonic() + 20.0
        window = None
        observed_folders: set[str] = set()
        while time.monotonic() < deadline:
            windows = shell.Windows()
            for index in range(int(windows.Count)):
                candidate = windows.Item(index)
                try:
                    folder_path = str(candidate.Document.Folder.Self.Path or "")
                    observed_folders.add(folder_path)
                except Exception:
                    continue
                if os.path.normcase(os.path.abspath(folder_path)) == wanted_parent:
                    window = candidate
                    break
            if window is not None:
                break
            time.sleep(0.1)
        if window is None:
            raise AssertionError(
                "real Explorer window for fixture folder did not appear; "
                f"shell_window_count={int(shell.Windows().Count)} "
                f"prior_hwnds={sorted(before)} observed_folders={sorted(observed_folders)!r}"
            )

        document = window.Document
        folder_item = document.Folder.ParseName(path.name)
        if folder_item is None:
            raise AssertionError("real Explorer folder did not resolve fixture file")
        # SVSI_SELECT | SVSI_DESELECTOTHERS | SVSI_ENSUREVISIBLE | SVSI_FOCUSED.
        document.SelectItem(folder_item, 0x0001 | 0x0004 | 0x0008 | 0x0010)

        hwnd = int(window.HWND)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
        user32.SetForegroundWindow(wintypes.HWND(hwnd))

        deadline = time.monotonic() + 5.0
        last_selected: list[str] = []
        last_foreground = 0
        while time.monotonic() < deadline:
            selected = document.SelectedItems()
            last_selected = [
                str(selected.Item(index).Path or "") for index in range(int(selected.Count))
            ]
            last_foreground = int(user32.GetForegroundWindow() or 0)
            if last_selected == [str(path)] and last_foreground == hwnd:
                return window
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            time.sleep(0.1)
        raise AssertionError(
            "fixture did not establish one stable foreground Explorer selection; "
            f"expected_hwnd={hwnd} foreground_hwnd={last_foreground} "
            f"selected={last_selected!r}"
        )

    def test_product_resident_reads_real_foreground_explorer_selection(self) -> None:
        self._require_windows_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected = root / "zn-selected-file.txt"
            selected.write_text("real explorer selection evidence\n", encoding="utf-8")
            window = self._open_select_and_foreground(selected)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                thread_id = "windows-real-explorer-selection"
                resident.work_ledger.create_thread(thread_id=thread_id, title="Explorer selected file")
                _, run = resident.work_ledger.submit(thread_id, TASK)

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertIn(selected.name, run.response)
                self.assertIn(str(selected.stat().st_size), run.response)

                # The product path must not need a body action to infer selection.
                actions = [
                    action
                    for action in resident.body.recent_actions(128)
                    if action.event_id == run.event.event_id
                ]
                self.assertEqual(actions, [])

                root_item = resident.work_ledger.work_item_for_event(run.event.event_id)
                children = [
                    item
                    for item in resident.work_ledger.list_work_items(thread_id, limit=64)
                    if root_item is not None and item.parent_work_item_id == root_item.work_item_id
                ]
                durable = "\n".join(str(item.result or "") for item in children)
                self.assertNotIn(str(selected), durable)
                self.assertNotIn(selected.name, durable)
            finally:
                resident.store.close()
                try:
                    window.Quit()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()

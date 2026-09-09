from __future__ import annotations

import ctypes
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from test_windows_interactive_desktop_modal_recovery import _ModalRecoveryOrderApp, MODAL_TITLE
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


class WindowsInteractiveModalOwnerProbe(unittest.TestCase):
    def test_report_real_winforms_modal_owner_chain(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            app = _ModalRecoveryOrderApp(Path(tmp))
            app.start()
            try:
                app.activate()
                app.trigger_modal()
                deadline = time.monotonic() + 8
                dialog = 0
                while time.monotonic() < deadline:
                    dialog = app.modal_hwnd()
                    if dialog:
                        break
                    time.sleep(0.03)
                self.assertTrue(dialog, f"real {MODAL_TITLE} modal did not appear")

                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetWindow.restype = wintypes.HWND
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                user32.GetParent.argtypes = [wintypes.HWND]
                user32.GetParent.restype = wintypes.HWND
                print(
                    "ZN_E2E15_OWNER_PROBE="
                    + repr(
                        {
                            "parent": int(app.hwnd),
                            "dialog": int(dialog),
                            "gw_owner": int(user32.GetWindow(dialog, 4) or 0),
                            "get_parent": int(user32.GetParent(dialog) or 0),
                            "ga_root": int(user32.GetAncestor(dialog, 2) or 0),
                            "ga_root_owner": int(user32.GetAncestor(dialog, 3) or 0),
                            "parent_ga_root_owner": int(user32.GetAncestor(app.hwnd, 3) or 0),
                        }
                    )
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

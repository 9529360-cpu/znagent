from __future__ import annotations

import ctypes
import json
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "tests" / "zn_agent" / "e2e"))

import test_windows_interactive_user_browser_extension as extension_test  # noqa: E402


last_fixture = None
original_activate = extension_test._ExtensionBrowserFixture.activate
original_press = extension_test._press_extension_action_shortcut


def _foreground() -> tuple[int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    hwnd = int(user32.GetForegroundWindow() or 0)
    pid = wintypes.DWORD(0)
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, int(pid.value)


def diagnostic_activate(self):
    global last_fixture
    last_fixture = self
    original_activate(self)
    hwnd, pid = _foreground()
    family = sorted(self._process_family_ids())
    print(
        "ZN_EXTENSION_FOCUS_AFTER_ACTIVATE="
        + json.dumps(
            {
                "expected_hwnd": int(self.hwnd),
                "foreground_hwnd": hwnd,
                "foreground_pid": pid,
                "fixture_window_pid": int(self.window_pid),
                "foreground_in_browser_family": pid in set(family),
                "browser_family_size": len(family),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def diagnostic_press():
    hwnd, pid = _foreground()
    fixture = last_fixture
    family = set(fixture._process_family_ids()) if fixture is not None else set()
    evidence = {
        "expected_hwnd": int(fixture.hwnd) if fixture is not None else 0,
        "foreground_hwnd": hwnd,
        "foreground_pid": pid,
        "fixture_window_pid": int(fixture.window_pid) if fixture is not None else 0,
        "foreground_in_browser_family": pid in family,
        "exact_fixture_window_foreground": bool(fixture is not None and hwnd == int(fixture.hwnd)),
    }
    print("ZN_EXTENSION_FOCUS_BEFORE_SHORTCUT=" + json.dumps(evidence, sort_keys=True), flush=True)
    original_press()


extension_test._ExtensionBrowserFixture.activate = diagnostic_activate
extension_test._press_extension_action_shortcut = diagnostic_press

suite = unittest.TestSuite()
suite.addTest(
    extension_test.WindowsInteractiveUserBrowserExtensionE2ETests(
        "test_existing_authenticated_session_completes_normal_named_text_task"
    )
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

from __future__ import annotations

import ctypes
import json
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "tests" / "zn_agent" / "e2e"))
sys.path.insert(0, str(repo_root / "runtime" / "python"))

import test_windows_interactive_user_browser_extension as extension_test  # noqa: E402
from zn_agent.core.user_browser_extension_relay import ResidentUserBrowserExtensionRelay  # noqa: E402


last_fixture = None
relay_events = {"authorize_calls": 0, "authorize_success": 0, "revoke_calls": 0}
original_activate = extension_test._ExtensionBrowserFixture.activate
original_press = extension_test._press_extension_action_shortcut
original_authorize = ResidentUserBrowserExtensionRelay.authorize
original_revoke = ResidentUserBrowserExtensionRelay.revoke


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


def _modifiers() -> dict[str, bool]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    keys = {
        "ctrl": 0x11,
        "shift": 0x10,
        "alt": 0x12,
        "lwin": 0x5B,
        "rwin": 0x5C,
        "lctrl": 0xA2,
        "rctrl": 0xA3,
        "lshift": 0xA0,
        "rshift": 0xA1,
        "lalt": 0xA4,
        "ralt": 0xA5,
    }
    return {name: bool(int(user32.GetAsyncKeyState(vk)) & 0x8000) for name, vk in keys.items()}


def diagnostic_authorize(self, *, tab_id, url, title):
    relay_events["authorize_calls"] += 1
    try:
        result = original_authorize(self, tab_id=tab_id, url=url, title=title)
    except Exception:
        print("ZN_EXTENSION_RELAY_EVENT=" + json.dumps({**relay_events, "stage": "authorize_error"}, sort_keys=True), flush=True)
        raise
    relay_events["authorize_success"] += 1
    print("ZN_EXTENSION_RELAY_EVENT=" + json.dumps({**relay_events, "stage": "authorize_success"}, sort_keys=True), flush=True)
    return result


def diagnostic_revoke(self, *, tab_id=None):
    relay_events["revoke_calls"] += 1
    print("ZN_EXTENSION_RELAY_EVENT=" + json.dumps({**relay_events, "stage": "revoke"}, sort_keys=True), flush=True)
    return original_revoke(self, tab_id=tab_id)


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
                "modifiers": _modifiers(),
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
        "modifiers": _modifiers(),
        "relay_events_before_shortcut": dict(relay_events),
    }
    print("ZN_EXTENSION_FOCUS_BEFORE_SHORTCUT=" + json.dumps(evidence, sort_keys=True), flush=True)
    original_press()


ResidentUserBrowserExtensionRelay.authorize = diagnostic_authorize
ResidentUserBrowserExtensionRelay.revoke = diagnostic_revoke
extension_test._ExtensionBrowserFixture.activate = diagnostic_activate
extension_test._press_extension_action_shortcut = diagnostic_press

suite = unittest.TestSuite()
suite.addTest(
    extension_test.WindowsInteractiveUserBrowserExtensionE2ETests(
        "test_existing_authenticated_session_completes_normal_named_text_task"
    )
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print("ZN_EXTENSION_RELAY_FINAL=" + json.dumps(relay_events, sort_keys=True), flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)

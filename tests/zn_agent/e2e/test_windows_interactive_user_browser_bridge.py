from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.provider_bridge import build_resident_runtime


_TITLE = "ZN User Browser Bridge E2E"
_TEXT = "ZN isolated user browser bridge marker"
_TARGET_ID = "zn-user-browser-text-target"


def _find_installed_browsers() -> list[tuple[str, Path]]:
    """Discover stable Edge/Chrome without consulting or copying any user profile."""

    found: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(provider: str, candidate: str | os.PathLike[str] | None) -> None:
        if not candidate:
            return
        path = Path(candidate)
        try:
            if not path.is_file():
                return
            resolved = path.resolve()
        except OSError:
            return
        key = os.path.normcase(str(resolved))
        if key in seen:
            return
        seen.add(key)
        found.append((provider, resolved))

    add("edge", shutil.which("msedge.exe") or shutil.which("msedge"))
    for root_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(root_name)
        if root:
            add("edge", Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    add("chrome", shutil.which("chrome.exe") or shutil.which("chrome"))
    for root_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(root_name)
        if root:
            add("chrome", Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")

    return found


class _IsolatedUserBrowserFixture:
    """Real installed browser with an ephemeral profile and no accessibility override."""

    def __init__(self, provider: str, executable: Path) -> None:
        self.provider = str(provider)
        self.executable = Path(executable)
        self.root = Path(tempfile.mkdtemp(prefix=f"zn-{self.provider}-bridge-e2e-"))
        self.profile = self.root / "profile"
        self.profile.mkdir(parents=True, exist_ok=True)
        self.page = self.root / "fixture.html"
        self.process: subprocess.Popen[bytes] | None = None
        self.hwnd = 0
        self.window_pid = 0
        self.window_title = ""

    def start(self) -> None:
        self.page.write_text(
            f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{_TITLE}</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ display: grid; place-items: center; font-family: sans-serif; }}
    input {{ width: 640px; padding: 18px; font-size: 24px; }}
  </style>
</head>
<body>
  <input id="{_TARGET_ID}" type="text" value="{_TEXT}" autofocus autocomplete="off">
  <script>
    const target = document.getElementById('{_TARGET_ID}');
    const focusTarget = () => {{
      target.focus({{preventScroll: true}});
      target.setSelectionRange(target.value.length, target.value.length);
    }};
    window.addEventListener('load', () => setTimeout(focusTarget, 25));
    window.addEventListener('focus', () => setTimeout(focusTarget, 25));
    document.addEventListener('visibilitychange', () => {{
      if (!document.hidden) setTimeout(focusTarget, 25);
    }});
  </script>
</body>
</html>
""",
            encoding="utf-8",
        )

        args = [
            str(self.executable),
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            f"--app={self.page.as_uri()}",
        ]
        if self.provider == "edge":
            args.insert(4, "--disable-features=msEdgeFirstRunExperience")

        # Deliberately do not pass --force-renderer-accessibility. This proof asks
        # whether the installed browser's normal Windows accessibility provider is
        # sufficient once ZN's real UIA client begins observing it.
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"{self.provider} exited before the isolated browser fixture opened"
                )
            match = self._find_fixture_window()
            if match is not None:
                self.hwnd, self.window_pid, self.window_title = match
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError(
            f"{self.provider} did not expose the isolated browser fixture window in time"
        )

    def activate(self) -> None:
        if not self.hwnd:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow(self.hwnd, 5)
        user32.BringWindowToTop(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)

    def _process_family_ids(self) -> set[int]:
        if self.process is None:
            return set()
        family = {int(self.process.pid)}
        try:
            import psutil

            root = psutil.Process(self.process.pid)
            family.update(int(child.pid) for child in root.children(recursive=True))
        except Exception:
            pass
        return family

    def _find_fixture_window(self) -> tuple[int, int, str] | None:
        family = self._process_family_ids()
        if not family:
            return None

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [wintypes.WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        matches: list[tuple[int, int, str]] = []

        @wintypes.WNDENUMPROC
        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            process_id = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if int(process_id.value) not in family:
                return True
            title_length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
            if title_length <= 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            title = str(title_buffer.value or "")
            if _TITLE.lower() in title.lower():
                matches.append((int(hwnd), int(process_id.value), title))
                return False
            return True

        user32.EnumWindows(callback, 0)
        return matches[0] if matches else None

    def close(self) -> None:
        try:
            if os.name == "nt" and self.hwnd:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                user32.PostMessageW.restype = wintypes.BOOL
                user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
            if self.process is not None:
                try:
                    self.process.wait(timeout=4.0)
                except subprocess.TimeoutExpired:
                    pass
            self._terminate_isolated_profile_processes()
        finally:
            shutil.rmtree(self.root, ignore_errors=True)

    def _terminate_isolated_profile_processes(self) -> None:
        marker = os.path.normcase(str(self.profile))
        try:
            import psutil
        except ImportError:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
            return

        matched = []
        for process in psutil.process_iter(["pid", "cmdline"]):
            try:
                command = " ".join(process.info.get("cmdline") or [])
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            if marker not in os.path.normcase(command):
                continue
            matched.append(process)

        for process in matched:
            try:
                process.terminate()
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                pass
        _, alive = psutil.wait_procs(matched, timeout=2.0)
        for process in alive:
            try:
                process.kill()
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                pass
        if alive:
            psutil.wait_procs(alive, timeout=2.0)


class WindowsInteractiveUserBrowserBridgeProviderE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows user-browser bridge E2E runs only on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user32.SwitchDesktop.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 0x0001 | 0x0080 | 0x0100)
        if not desktop:
            raise AssertionError(
                "GitHub runner process cannot open the Windows input desktop; "
                "user-browser bridge proof requires an unlocked interactive user session"
            )
        try:
            if not user32.SwitchDesktop(desktop):
                raise AssertionError(
                    "GitHub runner process cannot switch to the Windows input desktop"
                )
        finally:
            user32.CloseDesktop(desktop)

    def test_real_installed_edge_or_chrome_exposes_focused_html_edit_state(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail(
                "interactive Windows runner has neither stable Microsoft Edge nor Google Chrome; "
                "User Browser Bridge provider proof cannot proceed"
            )

        print(
            "ZN_USER_BROWSER_BRIDGE_DISCOVERY="
            + json.dumps(
                {
                    "providers": [provider for provider, _ in browsers],
                    "selected": browsers[0][0],
                    "profile_scope": "isolated-temporary",
                    "forced_renderer_accessibility": False,
                },
                sort_keys=True,
            )
        )

        provider, executable = browsers[0]
        fixture = _IsolatedUserBrowserFixture(provider, executable)
        resident = None
        fixture.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                expected_process = executable.name.lower()
                deadline = time.monotonic() + 10.0
                foreground = None
                focused = None
                text_state = None
                last_error = None
                while time.monotonic() < deadline:
                    fixture.activate()
                    try:
                        foreground_candidate = resident.foreground_window.probe()
                        focused_candidate = resident.automation_element.probe_focused()
                        state_candidate = resident.automation_text_state.probe()
                        if (
                            _TITLE.lower() in foreground_candidate.title.lower()
                            and foreground_candidate.process_name.lower() == expected_process
                            and focused_candidate.process_name.lower() == expected_process
                            and state_candidate.process_name.lower() == expected_process
                            and focused_candidate.has_keyboard_focus
                            and state_candidate.has_keyboard_focus
                            and tuple(focused_candidate.runtime_id)
                            == tuple(state_candidate.runtime_id)
                        ):
                            foreground = foreground_candidate
                            focused = focused_candidate
                            text_state = state_candidate
                            break
                    except Exception as exc:
                        last_error = exc
                    time.sleep(0.08)

                if foreground is None or focused is None or text_state is None:
                    raise AssertionError(
                        f"resident did not observe a focused HTML Edit through the default {provider} "
                        "Windows accessibility provider in time; "
                        f"window_title={fixture.window_title!r} last_error={last_error!r}"
                    )

                self.assertEqual(focused.control_type, 50004)  # UIA_EditControlTypeId
                self.assertTrue(focused.is_enabled)
                self.assertTrue(focused.is_keyboard_focusable)
                self.assertFalse(focused.is_offscreen)
                self.assertFalse(focused.is_password)
                self.assertTrue(focused.is_value_pattern_available)
                self.assertFalse(focused.value_is_read_only)
                self.assertFalse(hasattr(focused, "value"))
                self.assertFalse(hasattr(focused, "text"))
                self.assertFalse(hasattr(focused, "name"))

                self.assertEqual(text_state.control_type, 50004)
                self.assertFalse(text_state.is_password)
                self.assertTrue(text_state.is_value_pattern_available)
                self.assertFalse(text_state.value_is_read_only)
                self.assertEqual(text_state.text_length, len(_TEXT))
                self.assertEqual(
                    text_state.text_sha256,
                    NativeFocusedAutomationTextSense.digest_text(_TEXT),
                )
                self.assertFalse(hasattr(text_state, "text"))
                self.assertFalse(hasattr(text_state, "value"))

                print(
                    "ZN_USER_BROWSER_BRIDGE_EVIDENCE="
                    + json.dumps(
                        {
                            "provider": provider,
                            "process_name": focused.process_name,
                            "framework_id": focused.framework_id,
                            "control_type": focused.control_type,
                            "class_name": focused.class_name,
                            "automation_id": focused.automation_id,
                            "native_window_handle": focused.native_window_handle,
                            "runtime_id": list(focused.runtime_id),
                            "is_value_pattern_available": focused.is_value_pattern_available,
                            "is_text_pattern_available": focused.is_text_pattern_available,
                            "value_is_read_only": focused.value_is_read_only,
                            "text_length": text_state.text_length,
                            "text_sha256": text_state.text_sha256,
                            "profile_scope": "isolated-temporary",
                            "forced_renderer_accessibility": False,
                        },
                        sort_keys=True,
                    )
                )
        finally:
            if resident is not None:
                close_browser = getattr(getattr(resident, "managed_browser", None), "close", None)
                if callable(close_browser):
                    close_browser()
                resident.store.close()
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

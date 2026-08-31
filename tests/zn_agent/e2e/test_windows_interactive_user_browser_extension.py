from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.service import ResidentService

from test_windows_interactive_user_browser_bridge import (
    _IsolatedUserBrowserFixture,
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)


_TITLE = "ZN User Browser Bridge E2E"
_TARGET_NAME = "Account search"
_TEXT = "alice@example.test"
_HOST = "zn-extension-e2e.test"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/account":
            self.server.account_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{_TITLE}</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ display: grid; place-items: center; font-family: sans-serif; }}
    main {{ display: grid; gap: 20px; width: 720px; }}
    input {{ padding: 18px; font-size: 24px; }}
  </style>
</head>
<body>
  <main>
    <label for="account-search">{_TARGET_NAME}</label>
    <input id="account-search" aria-label="{_TARGET_NAME}" type="text" value="" autocomplete="off">
  </main>
</body>
</html>
""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return None


class _ExtensionBrowserFixture(_IsolatedUserBrowserFixture):
    def __init__(self, provider: str, executable: Path, url: str, extension: Path):
        super().__init__(provider, executable)
        self.url = str(url)
        self.extension = Path(extension).resolve()

    def start(self) -> None:
        args = [
            str(self.executable),
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            f"--disable-extensions-except={self.extension}",
            f"--load-extension={self.extension}",
            f"--host-resolver-rules=MAP {_HOST} 127.0.0.1,EXCLUDE localhost",
            "--new-window",
            self.url,
        ]
        if self.provider == "edge":
            args.insert(5, "--disable-features=msEdgeFirstRunExperience")
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"{self.provider} exited before the browser-extension fixture opened"
                )
            match = self._find_fixture_window()
            if match is not None:
                self.hwnd, self.window_pid, self.window_title = match
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError(
            f"{self.provider} did not expose the browser-extension fixture window in time"
        )


def _press_extension_action_shortcut() -> None:
    """Generate the user gesture bound to manifest command `_execute_action`."""

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.keybd_event.argtypes = [
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        wintypes.ULONG_PTR,
    ]
    user32.keybd_event.restype = None
    key_up = 0x0002
    vk_control = 0x11
    vk_shift = 0x10
    vk_y = 0x59
    user32.keybd_event(vk_control, 0, 0, 0)
    user32.keybd_event(vk_shift, 0, 0, 0)
    user32.keybd_event(vk_y, 0, 0, 0)
    user32.keybd_event(vk_y, 0, key_up, 0)
    user32.keybd_event(vk_shift, 0, key_up, 0)
    user32.keybd_event(vk_control, 0, key_up, 0)


class WindowsInteractiveUserBrowserExtensionE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_explicit_extension_authorization_completes_normal_named_text_task(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        self.assertTrue((extension / "manifest.json").is_file())
        self.assertTrue((extension / "background.js").is_file())

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.account_requests = 0  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = int(server.server_address[1])
        url = f"http://{_HOST}:{port}/account"

        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(runtime_tmp.name) / "kernel.db",
        )
        service = ResidentService(resident)
        service.acquire()
        try:
            fixture.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.account_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.account_requests), 1)  # type: ignore[attr-defined]
            initial_requests = int(server.account_requests)  # type: ignore[attr-defined]

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8.0
            authorization = None
            while time.monotonic() < deadline:
                candidate = resident.user_browser_authorization()
                if candidate.get("authorized") and candidate.get("provider") == "zn-extension-user-browser":
                    authorization = candidate
                    break
                time.sleep(0.05)
            if authorization is None:
                self.fail(
                    "real loaded ZN extension did not authorize the foreground tab after the "
                    "explicit extension-action user gesture"
                )
            self.assertEqual(authorization["authorization_scope"], "explicit_current_tab")

            result = resident.submit(
                "In my current browser, put alice@example.test in Account search.",
                payload={
                    "resident_goal": {
                        "kind": "user_browser_named_text",
                        "target_name": _TARGET_NAME,
                        "text": _TEXT,
                    },
                    "model_policy": "never",
                },
            )
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(
                int(server.account_requests),  # type: ignore[attr-defined]
                initial_requests,
                "extension-backed USER task unexpectedly navigated or reloaded the page",
            )

            # Independent postcondition path: prove the final text through Windows UIA,
            # not through the extension/CDP provider that performed the mutation.
            fixture.activate()
            deadline = time.monotonic() + 5.0
            named_after = None
            text_after = None
            last_error = None
            while time.monotonic() < deadline:
                try:
                    named_candidate = resident.browser_named_target.probe_exact_edit(_TARGET_NAME)
                    text_candidate = resident.automation_text_state.probe()
                    if (
                        tuple(named_candidate.runtime_id) == tuple(text_candidate.runtime_id)
                        and text_candidate.text_length == len(_TEXT)
                        and text_candidate.text_sha256
                        == NativeFocusedAutomationTextSense.digest_text(_TEXT)
                    ):
                        named_after = named_candidate
                        text_after = text_candidate
                        break
                except Exception as exc:
                    last_error = exc
                time.sleep(0.08)
            if named_after is None or text_after is None:
                raise AssertionError(
                    "independent Windows UIA evidence did not prove the extension-backed final "
                    f"textbox state; last_error={last_error!r}"
                )

            # The extension may inspect the target value locally, but current text is
            # represented outside it only by bounded length/digest evidence.
            self.assertEqual(text_after.text_sha256, hashlib.sha256(_TEXT.encode("utf-8")).hexdigest())

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if not resident.user_browser_extension_status().get("authorized"):
                    break
                time.sleep(0.05)
            self.assertFalse(resident.user_browser_extension_status()["authorized"])

            self.assertIsNotNone(fixture.process)
            assert fixture.process is not None
            self.assertIsNone(
                fixture.process.poll(),
                "revoking ZN extension authority must not close the user's browser",
            )

            print(
                "ZN_USER_BROWSER_EXTENSION_E2E_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "browser_plane": "user",
                        "transport": "chrome-extension-debugger",
                        "authorization": "explicit-extension-action-user-gesture",
                        "profile_scope": "isolated-temporary-test-user-session",
                        "navigation_performed": False,
                        "final_text_chars": text_after.text_length,
                        "independent_verifier": "windows-uia",
                        "browser_process_alive_after_revoke": fixture.process.poll() is None,
                    },
                    sort_keys=True,
                )
            )
        finally:
            try:
                if resident.user_browser_extension_status().get("authorized"):
                    resident.revoke_user_browser_extension_tab()
            except Exception:
                pass
            service.release()
            resident.store.close()
            runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

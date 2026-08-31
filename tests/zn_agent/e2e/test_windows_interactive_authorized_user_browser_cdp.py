from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.provider_bridge import build_resident_runtime

from test_windows_interactive_user_browser_bridge import (
    _IsolatedUserBrowserFixture,
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)


_TARGET_NAME = "Account search"
_TEXT = "alice@example.test"
_TITLE = "ZN User Browser Bridge E2E"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.server.root_requests += 1  # type: ignore[attr-defined]
            body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{_TITLE}</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ display: grid; place-items: center; font-family: sans-serif; }}
    main {{ display: grid; gap: 24px; width: 720px; }}
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


class _CDPBrowserFixture(_IsolatedUserBrowserFixture):
    def __init__(self, provider: str, executable: Path, url: str):
        super().__init__(provider, executable)
        self.url = url
        self.endpoint = ""

    def start(self) -> None:
        args = [
            str(self.executable),
            f"--user-data-dir={self.profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            f"--app={self.url}",
        ]
        if self.provider == "edge":
            args.insert(5, "--disable-features=msEdgeFirstRunExperience")
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        active_port = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + 15.0
        port = ""
        match = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"{self.provider} exited before authorized CDP fixture opened"
                )
            if not port and active_port.exists():
                try:
                    lines = active_port.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                if lines and lines[0].strip().isdigit():
                    port = lines[0].strip()
            if match is None:
                match = self._find_fixture_window()
            if port and match is not None:
                self.hwnd, self.window_pid, self.window_title = match
                self.endpoint = f"http://127.0.0.1:{port}"
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError(
            f"{self.provider} did not expose both the current window and local CDP endpoint"
        )


class WindowsInteractiveAuthorizedUserBrowserCDPE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_authorized_cdp_session_types_without_navigation_and_keeps_browser_open(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.root_requests = 0  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        url = f"http://{host}:{port}/"

        provider, executable = browsers[0]
        fixture = _CDPBrowserFixture(provider, executable, url)
        resident = None
        runtime_tmp = None
        fixture.start()
        try:
            time.sleep(0.25)
            initial_requests = int(server.root_requests)  # type: ignore[attr-defined]
            self.assertGreaterEqual(initial_requests, 1)

            runtime_tmp = tempfile.TemporaryDirectory()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            authorization = resident.authorize_existing_user_browser(fixture.endpoint)
            self.assertTrue(authorization["authorized"])
            self.assertEqual(authorization["plane"], "user")

            fixture.activate()
            result = resident.body.act(
                "browser_type_named_text",
                event_id="evt-authorized-user-browser-cdp",
                url=url,
                target_name=_TARGET_NAME,
                text=_TEXT,
                allow_private_network=True,
            )
            self.assertTrue(result.success, result.error)
            self.assertEqual(result.data["browser_plane"], "user")
            self.assertTrue(result.data["input_sent"])
            self.assertTrue(result.data["exact_node_continuity"])

            # USER-plane text entry must preserve the current page instead of
            # reloading it. The page server should therefore see no second root GET.
            self.assertEqual(
                int(server.root_requests),  # type: ignore[attr-defined]
                initial_requests,
                "authorized user-browser text entry unexpectedly navigated/reloaded",
            )

            # Verify the mutation through an independent Windows UIA evidence path,
            # not by trusting the CDP provider's own action return alone.
            fixture.activate()
            named_after = resident.browser_named_target.probe_exact_edit(_TARGET_NAME)
            self.assertTrue(named_after.has_keyboard_focus)
            final_text = resident.automation_text_state.probe()
            self.assertEqual(tuple(final_text.runtime_id), tuple(named_after.runtime_id))
            self.assertEqual(final_text.text_length, len(_TEXT))
            self.assertEqual(
                final_text.text_sha256,
                NativeFocusedAutomationTextSense.digest_text(_TEXT),
            )

            self.assertIsNotNone(fixture.process)
            assert fixture.process is not None
            self.assertIsNone(
                fixture.process.poll(),
                "closing the ZN bridge must not close the user's browser process",
            )
            self.assertFalse(resident.managed_browser._sessions)

            print(
                "ZN_AUTHORIZED_USER_BROWSER_CDP_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "profile_scope": "isolated-temporary-test-user-session",
                        "transport": "loopback-cdp",
                        "browser_plane": "user",
                        "private_network_explicitly_authorized": True,
                        "root_requests_before": initial_requests,
                        "root_requests_after": int(server.root_requests),  # type: ignore[attr-defined]
                        "final_text_chars": final_text.text_length,
                        "browser_process_alive_after_bridge_close": fixture.process.poll()
                        is None,
                    },
                    sort_keys=True,
                )
            )
        finally:
            if resident is not None:
                try:
                    resident.revoke_existing_user_browser()
                except Exception:
                    pass
                resident.store.close()
            if runtime_tmp is not None:
                runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

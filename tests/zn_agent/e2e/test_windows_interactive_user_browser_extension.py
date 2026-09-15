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
_SESSION_COOKIE_NAME = "zn_existing_session"
_SESSION_COOKIE_VALUE = "already-authenticated-before-zn"
_SESSION_COOKIE = f"{_SESSION_COOKIE_NAME}={_SESSION_COOKIE_VALUE}"
_EDGE_DEV_MODE_WARNING_SNOOZE_END_TIME = "99999999999000000"
_EXTENSION_ID = "likpiakgiamipheeekdgekdahafjinnh"
_EXTENSION_ACTION_COMMAND = "_execute_action"
_EXTENSION_ACTION_SHORTCUT = "Ctrl+Shift+5"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/login":
            self.server.login_requests += 1  # type: ignore[attr-defined]
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Location", "/account")
            self.end_headers()
            return

        if self.path == "/account":
            self.server.account_requests += 1  # type: ignore[attr-defined]
            if not self._has_existing_session():
                self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
                body = b"existing browser login required"
                self.send_response(401)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.server.authenticated_account_requests += 1  # type: ignore[attr-defined]
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

    def _has_existing_session(self) -> bool:
        cookies = [
            item.strip()
            for item in str(self.headers.get("Cookie") or "").split(";")
            if item.strip()
        ]
        return _SESSION_COOKIE in cookies

    def log_message(self, format: str, *args) -> None:
        return None


class _ExtensionBrowserFixture(_IsolatedUserBrowserFixture):
    def __init__(
        self,
        provider: str,
        executable: Path,
        url: str,
        extension: Path,
        *,
        window_title_marker: str = _TITLE,
    ):
        super().__init__(
            provider,
            executable,
            window_title_marker=window_title_marker,
        )
        self.url = str(url)
        self.extension = Path(extension).resolve()

    def _prepare_extension_profile(self) -> None:
        """Provision the disposable profile like an explicit user shortcut assignment.

        Chromium treats manifest ``suggested_key`` as optional and may leave an
        unpacked development extension unbound.  These hosted tests own a fresh
        isolated profile, so establish the one intended user binding directly in
        Chromium's profile-level command preference before launch.  The later
        real SendInput gesture plus Resident authorization transition remains the
        end-to-end proof that Chromium accepted and dispatched the command.
        """

        default_profile = self.profile / "Default"
        default_profile.mkdir(parents=True, exist_ok=True)
        preferences_path = default_profile / "Preferences"
        preferences: dict[str, object] = {}
        if preferences_path.is_file():
            try:
                loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    "isolated Chromium extension profile has unreadable Preferences"
                ) from exc
            if isinstance(loaded, dict):
                preferences = loaded

        extensions = preferences.get("extensions")
        if not isinstance(extensions, dict):
            extensions = {}
            preferences["extensions"] = extensions

        commands = extensions.get("commands")
        if not isinstance(commands, dict):
            commands = {}
            extensions["commands"] = commands
        binding_key = f"Windows:{_EXTENSION_ACTION_SHORTCUT}"
        expected_binding = {
            "command_name": _EXTENSION_ACTION_COMMAND,
            "extension": _EXTENSION_ID,
            "global": False,
        }
        existing_binding = commands.get(binding_key)
        if existing_binding not in (None, expected_binding):
            raise RuntimeError(
                "isolated Chromium extension profile has a conflicting action shortcut binding"
            )
        commands[binding_key] = expected_binding

        if self.provider == "edge":
            ui = extensions.get("ui")
            if not isinstance(ui, dict):
                ui = {}
                extensions["ui"] = ui
            ui["dev_mode_warning_snooze_end_time"] = _EDGE_DEV_MODE_WARNING_SNOOZE_END_TIME

        preferences_path.write_text(
            json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def _wait_for_extension_action_shortcut(self, deadline: float) -> None:
        """Require the isolated profile to retain the explicit command binding.

        This is a pre-gesture fixture invariant, not the completion proof.  The
        command is proven active only when one real SendInput chord causes the
        expected Resident authorization transition later in each acceptance test.
        """

        preferences_path = self.profile / "Default" / "Preferences"
        last_bindings: dict[str, object] = {}
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
                extensions = preferences.get("extensions")
                bindings = (
                    extensions.get("commands")
                    if isinstance(extensions, dict)
                    else None
                )
                if isinstance(bindings, dict):
                    last_bindings = bindings
                    for platform_shortcut, raw_binding in bindings.items():
                        if not isinstance(raw_binding, dict):
                            continue
                        if str(raw_binding.get("extension") or "") != _EXTENSION_ID:
                            continue
                        if str(raw_binding.get("command_name") or "") != _EXTENSION_ACTION_COMMAND:
                            continue
                        shortcut = str(platform_shortcut).split(":", 1)[-1]
                        if shortcut.casefold() == _EXTENSION_ACTION_SHORTCUT.casefold():
                            return
            except (OSError, json.JSONDecodeError) as exc:
                # Chromium may atomically replace or still be flushing the profile
                # while the first window is becoming visible.  Only a proven active
                # binding is success; transient file state is retried until deadline.
                last_error = exc
            time.sleep(0.05)

        observed = [
            str(key)
            for key, value in last_bindings.items()
            if isinstance(value, dict)
            and str(value.get("extension") or "") == _EXTENSION_ID
        ]
        raise RuntimeError(
            "browser window did not retain the explicitly provisioned ZN extension "
            "action shortcut binding; "
            f"observed={observed!r}, last_error={last_error!r}"
        )

    def start(self) -> None:
        self._prepare_extension_profile()
        args = [
            str(self.executable),
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            f"--load-extension={self.extension}",
            "--enable-unsafe-extension-debugging",
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
                self._wait_for_extension_action_shortcut(deadline)
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError(
            f"{self.provider} did not expose the browser-extension fixture window in time"
        )


def _press_extension_action_shortcut() -> None:
    """Generate one verified Windows user-gesture chord for `_execute_action`.

    ``keybd_event`` is superseded and reports no delivery result.  Use one
    ``SendInput`` batch, matching ZN's production keyboard primitive, so the
    modifier/key transitions cannot be interleaved between six independent API
    calls and the fixture fails loudly if Windows accepts only part of the chord.
    """

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ulong_ptr = (
        ctypes.c_ulonglong
        if ctypes.sizeof(ctypes.c_void_p) == 8
        else ctypes.c_ulong
    )

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class InputUnion(ctypes.Union):
        # INPUT uses the size of its largest union member.  Keep all Win32
        # members so sizeof(Input) remains correct on Win64.
        _fields_ = [
            ("mi", MouseInput),
            ("ki", KeyboardInput),
            ("hi", HardwareInput),
        ]

    class Input(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", InputUnion),
        ]

    input_keyboard = 1
    key_up = 0x0002
    vk_control = 0x11
    vk_shift = 0x10
    vk_5 = 0x35

    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    dirty = [
        name
        for name, vk in (
            ("control", vk_control),
            ("shift", vk_shift),
            ("5", vk_5),
        )
        if int(user32.GetAsyncKeyState(vk)) & 0x8000
    ]
    if dirty:
        raise RuntimeError(
            "interactive extension shortcut cannot be injected while keys are already down: "
            + ",".join(dirty)
        )

    event_values = [
        Input(type=input_keyboard, ki=KeyboardInput(vk_control, 0, 0, 0, 0)),
        Input(type=input_keyboard, ki=KeyboardInput(vk_shift, 0, 0, 0, 0)),
        Input(type=input_keyboard, ki=KeyboardInput(vk_5, 0, 0, 0, 0)),
        Input(type=input_keyboard, ki=KeyboardInput(vk_5, 0, key_up, 0, 0)),
        Input(type=input_keyboard, ki=KeyboardInput(vk_shift, 0, key_up, 0, 0)),
        Input(type=input_keyboard, ki=KeyboardInput(vk_control, 0, key_up, 0, 0)),
    ]
    events = (Input * len(event_values))(*event_values)
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(Input),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT
    ctypes.set_last_error(0)
    sent = int(user32.SendInput(len(events), events, ctypes.sizeof(Input)))
    if sent != len(events):
        error = ctypes.get_last_error()
        raise RuntimeError(
            "Windows SendInput accepted only "
            f"{sent}/{len(events)} extension-shortcut events; winerror={error}"
        )


class WindowsInteractiveUserBrowserExtensionE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_fixture_provisions_action_shortcut_and_edge_warning_in_ephemeral_profile(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        fixture = _ExtensionBrowserFixture(
            "edge",
            Path("msedge.exe"),
            "http://example.invalid/",
            extension,
        )
        try:
            fixture._prepare_extension_profile()
            preferences_path = fixture.profile / "Default" / "Preferences"
            preferences = json.loads(preferences_path.read_text(encoding="utf-8"))
            extensions = preferences["extensions"]
            self.assertEqual(
                extensions["commands"][f"Windows:{_EXTENSION_ACTION_SHORTCUT}"],
                {
                    "command_name": _EXTENSION_ACTION_COMMAND,
                    "extension": _EXTENSION_ID,
                    "global": False,
                },
            )
            self.assertEqual(
                extensions["ui"]["dev_mode_warning_snooze_end_time"],
                _EDGE_DEV_MODE_WARNING_SNOOZE_END_TIME,
            )
            self.assertTrue(str(preferences_path).startswith(str(fixture.root)))
        finally:
            fixture.close()

    def test_existing_authenticated_session_completes_normal_named_text_task(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        self.assertTrue((extension / "manifest.json").is_file())
        self.assertTrue((extension / "background.js").is_file())

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = 0  # type: ignore[attr-defined]
        server.authenticated_account_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = int(server.server_address[1])
        login_url = f"http://{_HOST}:{port}/login"

        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        service = None
        try:
            # Establish the authenticated browser session before Resident exists.
            # The login endpoint sets one HttpOnly cookie and redirects into the
            # protected account page. ZN receives no cookie/profile material.
            fixture.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.authenticated_account_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.login_requests), 1)  # type: ignore[attr-defined]
            self.assertGreaterEqual(
                int(server.authenticated_account_requests),  # type: ignore[attr-defined]
                1,
                "browser did not establish its own authenticated session before Resident started",
            )
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            initial_login_requests = int(server.login_requests)  # type: ignore[attr-defined]
            initial_account_requests = int(server.account_requests)  # type: ignore[attr-defined]
            initial_authenticated_requests = int(  # type: ignore[attr-defined]
                server.authenticated_account_requests
            )

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            service = ResidentService(resident)
            service.acquire()

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
                int(server.login_requests),  # type: ignore[attr-defined]
                initial_login_requests,
                "ZN task unexpectedly re-entered the login flow instead of using the existing session",
            )
            self.assertEqual(
                int(server.account_requests),  # type: ignore[attr-defined]
                initial_account_requests,
                "extension-backed USER task unexpectedly navigated or reloaded the page",
            )
            self.assertEqual(
                int(server.authenticated_account_requests),  # type: ignore[attr-defined]
                initial_authenticated_requests,
                "ZN task unexpectedly created a new authenticated page request",
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
                        "existing_authenticated_session": True,
                        "session_established_before_resident": True,
                        "session_cookie_http_only": True,
                        "credential_transfer_to_zn": False,
                        "navigation_performed": False,
                        "final_text_chars": text_after.text_length,
                        "independent_verifier": "windows-uia",
                        "browser_process_alive_after_revoke": fixture.process.poll() is None,
                    },
                    sort_keys=True,
                )
            )
        finally:
            if resident is not None:
                try:
                    if resident.user_browser_extension_status().get("authorized"):
                        resident.revoke_user_browser_extension_tab()
                except Exception:
                    pass
            if service is not None:
                service.release()
            if resident is not None:
                resident.store.close()
            runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
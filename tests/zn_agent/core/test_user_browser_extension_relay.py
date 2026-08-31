from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.service import ResidentService
from zn_agent.core.user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionRelayError,
    ZN_BROWSER_EXTENSION_HEADER,
    ZN_BROWSER_EXTENSION_ID,
    ZN_BROWSER_EXTENSION_ORIGIN,
)


class UserBrowserExtensionRelayTests(unittest.TestCase):
    @staticmethod
    def _post(
        relay,
        path: str,
        payload: dict,
        *,
        origin: str | None = ZN_BROWSER_EXTENSION_ORIGIN,
        extension_id: str | None = ZN_BROWSER_EXTENSION_ID,
    ):
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if extension_id is not None:
            headers[ZN_BROWSER_EXTENSION_HEADER] = extension_id
        request = Request(
            f"{relay.status()['endpoint']}{path}",
            data=json.dumps({"protocol_version": 1, **payload}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_only_stable_zn_extension_request_can_authorize_or_revoke(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        payload = {
            "tab_id": 17,
            "url": "https://example.test/account",
            "title": "Account",
        }
        try:
            with self.assertRaises(HTTPError) as missing_identity:
                self._post(relay, "/v1/attach", payload, extension_id=None)
            self.assertEqual(missing_identity.exception.code, 400)
            self.assertFalse(relay.status()["authorized"])

            with self.assertRaises(HTTPError) as blocked_origin:
                self._post(
                    relay,
                    "/v1/attach",
                    payload,
                    origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                )
            self.assertEqual(blocked_origin.exception.code, 400)
            self.assertFalse(relay.status()["authorized"])

            attached = self._post(relay, "/v1/attach", payload, origin=None)
            self.assertTrue(attached["authorized"])
            self.assertEqual(attached["tab"]["tab_id"], 17)
            self.assertEqual(attached["tab"]["url"], "https://example.test/account")

            with self.assertRaises(HTTPError) as wrong_tab:
                self._post(relay, "/v1/detach", {"tab_id": 18})
            self.assertEqual(wrong_tab.exception.code, 400)
            self.assertTrue(relay.status()["authorized"])

            detached = self._post(relay, "/v1/detach", {"tab_id": 17})
            self.assertFalse(detached["authorized"])
        finally:
            relay.close()

    def test_relay_refuses_non_http_page_and_cross_tab_authority_transfer(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        try:
            with self.assertRaises(HTTPError):
                self._post(
                    relay,
                    "/v1/attach",
                    {"tab_id": 4, "url": "chrome://settings", "title": "Settings"},
                )
            self._post(
                relay,
                "/v1/attach",
                {"tab_id": 4, "url": "https://one.test/", "title": "One"},
            )
            with self.assertRaises(HTTPError):
                self._post(
                    relay,
                    "/v1/attach",
                    {"tab_id": 5, "url": "https://two.test/", "title": "Two"},
                )
            self.assertEqual(relay.status()["tab"]["tab_id"], 4)
        finally:
            relay.close()

    def test_authorized_tab_supports_one_bounded_resident_command_roundtrip(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(
            tab_id=17,
            url="https://example.test/account",
            title="Account",
        )
        outcome: dict[str, object] = {}

        def request_from_resident() -> None:
            try:
                outcome["result"] = relay.request_command(
                    "probe_current_tab",
                    timeout_seconds=2.0,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                outcome["error"] = exc

        worker = threading.Thread(target=request_from_resident)
        worker.start()
        try:
            command_response = self._post(
                relay,
                "/v1/command/next",
                {"tab_id": 17, "wait_seconds": 1.0},
            )
            command = command_response["command"]
            self.assertEqual(command["tab_id"], 17)
            self.assertEqual(command["kind"], "probe_current_tab")
            self.assertEqual(command["args"], {})
            self.assertEqual(relay.status()["inflight_commands"], 1)

            accepted = self._post(
                relay,
                "/v1/command/result",
                {
                    "tab_id": 17,
                    "command_id": command["command_id"],
                    "success": True,
                    "result": {
                        "tab_id": 17,
                        "url": "https://example.test/account?fresh=1",
                        "title": "Account fresh",
                    },
                    "error": None,
                },
            )
            self.assertTrue(accepted["accepted"])
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertNotIn("error", outcome)
            result = outcome["result"]
            self.assertIsInstance(result, dict)
            self.assertTrue(result["success"])
            self.assertEqual(result["result"]["tab_id"], 17)
            self.assertEqual(
                result["result"]["url"],
                "https://example.test/account?fresh=1",
            )
            status = relay.status()
            self.assertEqual(status["pending_commands"], 0)
            self.assertEqual(status["inflight_commands"], 0)
        finally:
            relay.close()
            worker.join(timeout=2.0)

    def test_revocation_withdraws_inflight_command_without_replay(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(
            tab_id=23,
            url="https://example.test/secure",
            title="Secure",
        )
        outcome: dict[str, object] = {}

        def request_from_resident() -> None:
            try:
                outcome["result"] = relay.request_command(
                    "probe_current_tab",
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=request_from_resident)
        worker.start()
        try:
            command = self._post(
                relay,
                "/v1/command/next",
                {"tab_id": 23, "wait_seconds": 1.0},
            )["command"]
            self.assertIsNotNone(command)
            self.assertEqual(relay.status()["inflight_commands"], 1)
            relay.revoke(tab_id=23)
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(outcome.get("error"), UserBrowserExtensionRelayError)
            self.assertNotIn("result", outcome)
            self.assertEqual(relay.status()["pending_commands"], 0)
            self.assertEqual(relay.status()["inflight_commands"], 0)
            with self.assertRaises(UserBrowserExtensionRelayError):
                relay.complete_command(
                    tab_id=23,
                    command_id=command["command_id"],
                    success=True,
                    result={"tab_id": 23},
                )
        finally:
            relay.close()
            worker.join(timeout=2.0)

    def test_command_surface_is_deny_by_default_and_never_crosses_tabs(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        try:
            with self.assertRaises(UserBrowserExtensionRelayError):
                relay.request_command("probe_current_tab", timeout_seconds=0.1)
            relay.authorize(
                tab_id=31,
                url="https://example.test/",
                title="Example",
            )
            with self.assertRaises(ValueError):
                relay.request_command("arbitrary_cdp", timeout_seconds=0.1)
            with self.assertRaises(HTTPError):
                self._post(
                    relay,
                    "/v1/command/next",
                    {"tab_id": 32, "wait_seconds": 0},
                )
        finally:
            relay.close()

    def test_manifest_public_key_keeps_the_expected_extension_identity(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        manifest = json.loads(
            (repo_root / "apps" / "desktop" / "browser-extension" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        key_bytes = base64.b64decode(manifest["key"])
        prefix = hashlib.sha256(key_bytes).hexdigest()[:32]
        extension_id = "".join(chr(ord("a") + int(char, 16)) for char in prefix)
        self.assertEqual(extension_id, ZN_BROWSER_EXTENSION_ID)
        self.assertEqual(
            manifest["host_permissions"],
            ["http://127.0.0.1:19991/*"],
        )

    def test_service_lease_owns_relay_lifetime_not_runtime_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.user_browser_extension = ResidentUserBrowserExtensionRelay(port=0)
            service = ResidentService(resident)
            try:
                self.assertFalse(resident.user_browser_extension_status()["available"])
                service.acquire()
                running = resident.user_browser_extension_status()
                self.assertTrue(running["available"])
                self.assertGreater(int(running["endpoint"].rsplit(":", 1)[1]), 0)
                service.release()
                self.assertFalse(resident.user_browser_extension_status()["available"])
            finally:
                service.release()
                resident.store.close()

    def test_lease_loss_immediately_drops_browser_authorization_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.user_browser_extension = ResidentUserBrowserExtensionRelay(port=0)
            service = ResidentService(resident)
            try:
                service.acquire()
                self.assertTrue(resident.user_browser_extension_status()["available"])
                resident.user_browser_extension.authorize(
                    tab_id=8,
                    url="https://example.test/account",
                    title="Account",
                )
                self.assertTrue(resident.user_browser_extension_status()["authorized"])

                with patch.object(
                    resident.store,
                    "heartbeat_resident_lease",
                    return_value=False,
                ):
                    with self.assertRaisesRegex(RuntimeError, "lease was lost"):
                        service.heartbeat()

                status = resident.user_browser_extension_status()
                self.assertFalse(status["available"])
                self.assertFalse(status["authorized"])
            finally:
                service.release()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

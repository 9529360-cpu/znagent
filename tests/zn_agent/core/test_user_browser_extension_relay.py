from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.service import ResidentService
from zn_agent.core.user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    ZN_BROWSER_EXTENSION_ID,
    ZN_BROWSER_EXTENSION_ORIGIN,
)


class UserBrowserExtensionRelayTests(unittest.TestCase):
    @staticmethod
    def _post(relay, path: str, payload: dict, *, origin: str):
        request = Request(
            f"{relay.status()['endpoint']}{path}",
            data=json.dumps({"protocol_version": 1, **payload}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": origin,
            },
            method="POST",
        )
        with urlopen(request, timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_only_stable_zn_extension_origin_can_authorize_or_revoke(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        try:
            with self.assertRaises(HTTPError) as blocked:
                self._post(
                    relay,
                    "/v1/attach",
                    {
                        "tab_id": 17,
                        "url": "https://example.test/account",
                        "title": "Account",
                    },
                    origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                )
            self.assertEqual(blocked.exception.code, 400)
            self.assertFalse(relay.status()["authorized"])

            attached = self._post(
                relay,
                "/v1/attach",
                {
                    "tab_id": 17,
                    "url": "https://example.test/account",
                    "title": "Account",
                },
                origin=ZN_BROWSER_EXTENSION_ORIGIN,
            )
            self.assertTrue(attached["authorized"])
            self.assertEqual(attached["tab"]["tab_id"], 17)
            self.assertEqual(attached["tab"]["url"], "https://example.test/account")

            with self.assertRaises(HTTPError) as wrong_tab:
                self._post(
                    relay,
                    "/v1/detach",
                    {"tab_id": 18},
                    origin=ZN_BROWSER_EXTENSION_ORIGIN,
                )
            self.assertEqual(wrong_tab.exception.code, 400)
            self.assertTrue(relay.status()["authorized"])

            detached = self._post(
                relay,
                "/v1/detach",
                {"tab_id": 17},
                origin=ZN_BROWSER_EXTENSION_ORIGIN,
            )
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
                    origin=ZN_BROWSER_EXTENSION_ORIGIN,
                )
            self._post(
                relay,
                "/v1/attach",
                {"tab_id": 4, "url": "https://one.test/", "title": "One"},
                origin=ZN_BROWSER_EXTENSION_ORIGIN,
            )
            with self.assertRaises(HTTPError):
                self._post(
                    relay,
                    "/v1/attach",
                    {"tab_id": 5, "url": "https://two.test/", "title": "Two"},
                    origin=ZN_BROWSER_EXTENSION_ORIGIN,
                )
            self.assertEqual(relay.status()["tab"]["tab_id"], 4)
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
            # Use an ephemeral loopback port in the test while preserving the
            # production object's fixed 19991 contract.
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

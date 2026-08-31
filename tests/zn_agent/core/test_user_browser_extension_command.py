from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.service import ResidentService
from zn_agent.core.user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    ZN_BROWSER_EXTENSION_HEADER,
    ZN_BROWSER_EXTENSION_ID,
    ZN_BROWSER_EXTENSION_ORIGIN,
)


class UserBrowserExtensionCommandTests(unittest.TestCase):
    @staticmethod
    def _post(relay, path: str, payload: dict):
        request = Request(
            f"{relay.status()['endpoint']}{path}",
            data=json.dumps({"protocol_version": 1, **payload}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": ZN_BROWSER_EXTENSION_ORIGIN,
                ZN_BROWSER_EXTENSION_HEADER: ZN_BROWSER_EXTENSION_ID,
            },
            method="POST",
        )
        with urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_formal_resident_gets_fresh_current_tab_evidence_through_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.user_browser_extension = ResidentUserBrowserExtensionRelay(port=0)
            service = ResidentService(resident)
            outcome: dict[str, object] = {}
            try:
                service.acquire()
                self._post(
                    resident.user_browser_extension,
                    "/v1/attach",
                    {
                        "tab_id": 44,
                        "url": "https://example.test/account",
                        "title": "Account stale",
                    },
                )

                def resident_probe() -> None:
                    try:
                        outcome["value"] = resident.probe_user_browser_extension_tab()
                    except Exception as exc:  # pragma: no cover - asserted below
                        outcome["error"] = exc

                worker = threading.Thread(target=resident_probe)
                worker.start()
                command = self._post(
                    resident.user_browser_extension,
                    "/v1/command/next",
                    {"tab_id": 44, "wait_seconds": 1.0},
                )["command"]
                self.assertEqual(command["kind"], "probe_current_tab")
                self._post(
                    resident.user_browser_extension,
                    "/v1/command/result",
                    {
                        "tab_id": 44,
                        "command_id": command["command_id"],
                        "success": True,
                        "result": {
                            "tab_id": 44,
                            "url": "https://example.test/account?fresh=1",
                            "title": "Account fresh",
                        },
                        "error": None,
                    },
                )
                worker.join(timeout=2.0)
                self.assertFalse(worker.is_alive())
                self.assertNotIn("error", outcome)
                value = outcome["value"]
                self.assertIsInstance(value, dict)
                self.assertEqual(value["tab_id"], 44)
                self.assertEqual(value["url"], "https://example.test/account?fresh=1")
                self.assertEqual(value["title"], "Account fresh")
                self.assertEqual(value["source"], "zn_browser_extension")
            finally:
                service.release()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

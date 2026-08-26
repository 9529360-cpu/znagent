from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService


class _ClosableBrowser:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class ResidentBrowserShutdownTests(unittest.TestCase):
    @staticmethod
    def _request(endpoint: dict, method: str) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            client.sendall(
                (json.dumps({"id": "shutdown-test", "method": method, "params": {}}) + "\n").encode(
                    "utf-8"
                )
            )
            raw = client.makefile("rb").readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_resident_service_closes_managed_browser_before_shutdown_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            browser = _ClosableBrowser()
            resident.managed_browser = browser
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            endpoint_path = root / "resident-endpoint.json"
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()

            deadline = time.monotonic() + 5.0
            endpoint = None
            while time.monotonic() < deadline:
                if endpoint_path.is_file():
                    try:
                        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                        break
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass
                time.sleep(0.02)
            self.assertIsNotNone(endpoint)

            response = self._request(endpoint, "shutdown")
            self.assertTrue(response["ok"])
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(browser.closed.is_set())
            self.assertFalse(endpoint_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

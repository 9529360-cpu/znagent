from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.resident_server import ResidentSocketService


class ResidentSocketServiceTests(unittest.TestCase):
    @staticmethod
    def _request(endpoint: dict, method: str, params: dict | None = None) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            request = {
                "id": f"test-{method}-{time.time_ns()}",
                "method": method,
                "params": params or {},
            }
            client.sendall((json.dumps(request) + "\n").encode("utf-8"))
            stream = client.makefile("rb")
            raw = stream.readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_client_disconnect_does_not_end_resident_and_next_client_reconnects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            service = ResidentSocketService(
                rpc,
                endpoint_path=endpoint_path,
            )
            thread = threading.Thread(
                target=service.serve_forever,
                name="test-resident-socket",
                daemon=True,
            )
            thread.start()

            deadline = time.monotonic() + 5.0
            endpoint = None
            while time.monotonic() < deadline:
                if endpoint_path.exists():
                    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                    break
                time.sleep(0.02)
            self.assertIsNotNone(endpoint)

            first_ping = self._request(endpoint, "ping")
            self.assertTrue(first_ping["ok"])
            first_pulse = int(first_ping["result"]["pulse_count"])

            perceived = self._request(
                endpoint,
                "perceive",
                {
                    "channel": "vision",
                    "summary": "the desktop face displayed a reconnect marker",
                    "features": ["desktop", "reconnect", "marker"],
                    "source": "test-retina",
                    "salience": 0.8,
                },
            )
            self.assertTrue(perceived["ok"])
            trace_id = perceived["result"]["trace_id"]

            # _request closes its socket after every call. A later connection
            # must reach the same resident instead of recreating the subject.
            time.sleep(0.15)
            second_ping = self._request(endpoint, "ping")
            self.assertTrue(second_ping["ok"])
            self.assertGreaterEqual(
                int(second_ping["result"]["pulse_count"]),
                first_pulse,
            )
            neural = self._request(endpoint, "neural", {"limit": 50})
            self.assertTrue(neural["ok"])
            self.assertTrue(
                any(item["trace_id"] == trace_id for item in neural["result"])
            )
            self.assertTrue(thread.is_alive())

            shutdown = self._request(endpoint, "shutdown")
            self.assertTrue(shutdown["ok"])
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())
            self.assertFalse(endpoint_path.exists())


if __name__ == "__main__":
    unittest.main()

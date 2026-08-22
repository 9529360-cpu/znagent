from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.resident_server import ResidentSocketService
from agent.kernel.service import ResidentService


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

    def test_dead_same_host_lease_is_reclaimed_without_waiting_for_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.store.claim_resident_lease(
                instance_id="dead-resident",
                pid=2_147_483_647,
                hostname=socket.gethostname(),
                stale_after_seconds=3600,
            )
            service = ResidentService(
                resident,
                lease_timeout=3600,
                instance_id="replacement-resident",
            )

            service.acquire()
            lease = resident.store.get_resident_lease()

            self.assertIsNotNone(lease)
            self.assertEqual(lease["instance_id"], "replacement-resident")
            service.release()
            resident.store.close()

    @unittest.skipIf(os.name == "nt", "POSIX SIGTERM lifecycle contract")
    def test_sigterm_releases_lease_and_endpoint_before_process_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "zn-home"
            endpoint_path = home / "kernel" / "resident-endpoint.json"
            store_path = home / "kernel" / "kernel.db"
            repo_root = Path(__file__).resolve().parents[3]
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agent.kernel.resident_server",
                    "--home",
                    str(home),
                ],
                cwd=repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    if endpoint_path.is_file():
                        break
                    if child.poll() is not None:
                        error_text = child.stderr.read() if child.stderr else ""
                        self.fail(
                            f"resident exited before publishing endpoint: {error_text}"
                        )
                    time.sleep(0.05)
                self.assertTrue(endpoint_path.is_file(), "resident endpoint was not published")

                with sqlite3.connect(store_path) as connection:
                    lease = connection.execute(
                        "SELECT instance_id, pid FROM resident_lease WHERE id=1"
                    ).fetchone()
                self.assertIsNotNone(lease)
                self.assertEqual(int(lease[1]), child.pid)

                os.kill(child.pid, signal.SIGTERM)
                try:
                    returncode = child.wait(timeout=8.0)
                except subprocess.TimeoutExpired:
                    self.fail("resident did not exit after SIGTERM")

                error_text = child.stderr.read() if child.stderr else ""
                self.assertEqual(returncode, 0, error_text)
                self.assertFalse(endpoint_path.exists())
                with sqlite3.connect(store_path) as connection:
                    remaining = connection.execute(
                        "SELECT instance_id, pid FROM resident_lease WHERE id=1"
                    ).fetchone()
                self.assertIsNone(remaining)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5.0)
                if child.stderr is not None:
                    child.stderr.close()


if __name__ == "__main__":
    unittest.main()

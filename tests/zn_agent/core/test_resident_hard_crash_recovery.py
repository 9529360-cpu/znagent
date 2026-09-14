from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path


class ResidentHardCrashRecoveryTests(unittest.TestCase):
    @staticmethod
    def _spawn_resident(home: Path, runtime_id: str) -> subprocess.Popen:
        repo_root = Path(__file__).resolve().parents[3]
        env = os.environ.copy()
        env["ZN_RUNTIME_ID"] = runtime_id
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "zn_agent.core.resident_server",
                "--home",
                str(home),
            ],
            cwd=repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def _auth_secret(endpoint: dict) -> str:
        auth = endpoint.get("authentication")
        if not isinstance(auth, dict) or auth.get("scheme") != "session-secret-v1":
            raise AssertionError("resident endpoint does not contain the expected auth scheme")
        secret = auth.get("secret")
        if not isinstance(secret, str) or len(secret) < 32:
            raise AssertionError("resident endpoint auth secret is missing or too short")
        return secret

    @classmethod
    def _wait_for_endpoint(
        cls,
        endpoint_path: Path,
        child: subprocess.Popen,
        *,
        previous_instance_id: str | None = None,
        timeout: float = 12.0,
    ) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if endpoint_path.is_file():
                try:
                    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                    cls._auth_secret(endpoint)
                    pid = int(endpoint.get("pid") or -1)
                    instance_id = str(endpoint.get("instance_id") or "")
                    if pid == child.pid and (
                        previous_instance_id is None or instance_id != previous_instance_id
                    ):
                        return endpoint
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            if child.poll() is not None:
                error_text = child.stderr.read() if child.stderr else ""
                raise AssertionError(
                    f"resident exited before publishing replacement endpoint: {error_text}"
                )
            time.sleep(0.05)
        raise AssertionError("resident replacement endpoint was not published")

    @classmethod
    def _request(
        cls,
        endpoint: dict,
        method: str,
        params: dict | None = None,
        *,
        secret: str | None = None,
    ) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            stream = client.makefile("rb")
            auth_request = {
                "id": f"hard-crash-auth-{time.time_ns()}",
                "method": "authenticate",
                "params": {"secret": secret if secret is not None else cls._auth_secret(endpoint)},
            }
            client.sendall((json.dumps(auth_request) + "\n").encode("utf-8"))
            raw_auth = stream.readline()
            if not raw_auth:
                raise AssertionError("resident endpoint closed before auth response")
            auth_response = json.loads(raw_auth.decode("utf-8"))
            if not auth_response.get("ok"):
                return auth_response

            request = {
                "id": f"hard-crash-{method}-{time.time_ns()}",
                "method": method,
                "params": params or {},
            }
            client.sendall((json.dumps(request) + "\n").encode("utf-8"))
            raw = stream.readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_hard_crash_reclaims_stale_endpoint_and_preserves_same_home_self_and_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "zn-home"
            endpoint_path = home / "kernel" / "resident-endpoint.json"
            store_path = home / "kernel" / "kernel.db"
            first = self._spawn_resident(home, "runtime-crash-proof")
            second: subprocess.Popen | None = None
            try:
                first_endpoint = self._wait_for_endpoint(endpoint_path, first)
                first_secret = self._auth_secret(first_endpoint)
                first_instance_id = str(first_endpoint["instance_id"])
                self.assertEqual(int(first_endpoint["pid"]), first.pid)

                first_self = self._request(first_endpoint, "self")
                self.assertTrue(first_self["ok"])
                created = self._request(
                    first_endpoint,
                    "work_create",
                    {
                        "thread_id": "hard-crash-continuity",
                        "title": "Hard crash continuity marker",
                        "metadata": {"proof": "same-home-hard-crash"},
                    },
                )
                self.assertTrue(created["ok"])

                with closing(sqlite3.connect(store_path)) as connection:
                    lease_before = connection.execute(
                        "SELECT instance_id, pid FROM resident_lease WHERE id=1"
                    ).fetchone()
                self.assertIsNotNone(lease_before)
                self.assertEqual(str(lease_before[0]), first_instance_id)
                self.assertEqual(int(lease_before[1]), first.pid)

                first.kill()
                first.wait(timeout=5.0)

                self.assertTrue(endpoint_path.is_file())
                stale_endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                self.assertEqual(str(stale_endpoint["instance_id"]), first_instance_id)
                self.assertEqual(int(stale_endpoint["pid"]), first.pid)
                with closing(sqlite3.connect(store_path)) as connection:
                    stale_lease = connection.execute(
                        "SELECT instance_id, pid FROM resident_lease WHERE id=1"
                    ).fetchone()
                self.assertIsNotNone(stale_lease)
                self.assertEqual(str(stale_lease[0]), first_instance_id)
                self.assertEqual(int(stale_lease[1]), first.pid)

                second = self._spawn_resident(home, "runtime-crash-proof")
                second_endpoint = self._wait_for_endpoint(
                    endpoint_path,
                    second,
                    previous_instance_id=first_instance_id,
                )
                second_secret = self._auth_secret(second_endpoint)
                self.assertEqual(int(second_endpoint["pid"]), second.pid)
                self.assertNotEqual(str(second_endpoint["instance_id"]), first_instance_id)
                self.assertNotEqual(second_secret, first_secret)

                with closing(sqlite3.connect(store_path)) as connection:
                    replacement_lease = connection.execute(
                        "SELECT instance_id, pid FROM resident_lease WHERE id=1"
                    ).fetchone()
                self.assertIsNotNone(replacement_lease)
                self.assertEqual(str(replacement_lease[0]), str(second_endpoint["instance_id"]))
                self.assertEqual(int(replacement_lease[1]), second.pid)

                stale_auth = self._request(second_endpoint, "ping", secret=first_secret)
                self.assertFalse(stale_auth["ok"])
                self.assertEqual(stale_auth["error"], "authentication failed")

                second_self = self._request(second_endpoint, "self")
                self.assertTrue(second_self["ok"])
                self.assertEqual(second_self["result"]["born_at"], first_self["result"]["born_at"])
                self.assertEqual(second_self["result"]["name"], first_self["result"]["name"])
                self.assertGreaterEqual(
                    int(second_self["result"]["pulse_count"]),
                    int(first_self["result"]["pulse_count"]),
                )

                work = self._request(
                    second_endpoint,
                    "work_get",
                    {"thread_id": "hard-crash-continuity"},
                )
                self.assertTrue(work["ok"])
                self.assertEqual(work["result"]["id"], "hard-crash-continuity")
                self.assertEqual(work["result"]["title"], "Hard crash continuity marker")
                self.assertEqual(work["result"]["metadata"]["proof"], "same-home-hard-crash")

                shutdown = self._request(second_endpoint, "shutdown")
                self.assertTrue(shutdown["ok"])
                self.assertEqual(second.wait(timeout=8.0), 0)
                self.assertFalse(endpoint_path.exists())
            finally:
                for child in (first, second):
                    if child is None:
                        continue
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=5.0)
                    if child.stderr is not None:
                        child.stderr.close()


if __name__ == "__main__":
    unittest.main()

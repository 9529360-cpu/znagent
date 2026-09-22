from __future__ import annotations

import http.server
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = (
            "<!doctype html><html><head><title>ZN Resident Browser RPC</title></head>"
            "<body><main>resident managed browser active caller</main></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ResidentManagedBrowserWindowsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.web_thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.web_thread.start()
        cls.origin = f"http://127.0.0.1:{int(cls.web.server_address[1])}"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.web_thread.join(timeout=5)

    @staticmethod
    def _request(endpoint: dict, request_id: str, method: str, params=None) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])), timeout=5.0
        ) as client:
            client.settimeout(10.0)
            stream = client.makefile("rb")
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": f"{request_id}-auth",
                            "method": "authenticate",
                            "params": {"secret": endpoint["authentication"]["secret"]},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            auth = json.loads(stream.readline().decode("utf-8"))
            if not auth.get("ok"):
                return auth
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": request_id,
                            "method": method,
                            "params": dict(params or {}),
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            raw = stream.readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_resident_endpoint_opens_navigates_observes_and_closes_real_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            rpc = BrowserResidentRpcServer(resident=resident, life_interval=0.1)
            endpoint_path = root / "resident-endpoint.json"
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            resident_thread = threading.Thread(target=service.serve_forever, daemon=True)
            resident_thread.start()

            deadline = time.monotonic() + 10.0
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

            try:
                opened = self._request(
                    endpoint,
                    "open",
                    "browser_open",
                    {
                        "permission": {
                            "allow_navigation": True,
                            "allow_private_network": True,
                            "allowed_origins": [self.origin],
                        }
                    },
                )
                self.assertTrue(opened["ok"], opened)
                session_id = opened["result"]["session_id"]
                self.assertEqual(opened["result"]["provider"], "playwright-chromium")
                self.assertEqual(opened["result"]["profile_scope"], "ephemeral")

                navigated = self._request(
                    endpoint,
                    "navigate",
                    "browser_navigate",
                    {
                        "session_id": session_id,
                        "url": self.origin + "/",
                        "url_equals": self.origin + "/",
                    },
                )
                self.assertTrue(navigated["ok"], navigated)
                self.assertTrue(navigated["result"]["success"], navigated)
                self.assertEqual(navigated["result"]["url_after"], self.origin + "/")
                self.assertEqual(
                    navigated["result"]["postcondition"], "safe_current_page_observed"
                )

                observed = self._request(
                    endpoint,
                    "observe",
                    "browser_observe",
                    {"session_id": session_id},
                )
                self.assertTrue(observed["ok"], observed)
                self.assertEqual(observed["result"]["url"], self.origin + "/")
                self.assertEqual(observed["result"]["title"], "ZN Resident Browser RPC")

                closed = self._request(
                    endpoint,
                    "close",
                    "browser_close",
                    {"session_id": session_id},
                )
                self.assertTrue(closed["ok"], closed)
                self.assertTrue(closed["result"]["closed"])
            finally:
                shutdown = self._request(endpoint, "shutdown", "shutdown")
                self.assertTrue(shutdown["ok"], shutdown)
                resident_thread.join(timeout=10.0)
                self.assertFalse(resident_thread.is_alive())
                self.assertFalse(endpoint_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

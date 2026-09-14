from __future__ import annotations

import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.current_app_text_body import CurrentAppTextAwareBody
from zn_agent.core.store import KernelStore


class LocalServiceDiagnosisE2E(unittest.TestCase):
    def test_real_listener_log_guarded_repair_and_fresh_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "service.state"
            log_path = root / "service.log"
            repair_path = root / "repair.py"
            state_path.write_text("broken", encoding="utf-8")
            repair_path.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[1]).write_text('ready', encoding='utf-8')\n"
                "print('repair applied')\n",
                encoding="utf-8",
            )

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    ready = state_path.read_text(encoding="utf-8").strip() == "ready"
                    status = 200 if ready else 503
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write(f"health status={status} ready={str(ready).lower()}\n")
                    body = b"ready" if ready else b"not ready"
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            store = KernelStore(root / "kernel.db")
            try:
                port = int(server.server_address[1])
                self._wait_for_listener(port)
                body = CurrentAppTextAwareBody(store=store)
                service_args = {
                    "port": port,
                    "host": "127.0.0.1",
                    "expected_process_name": Path(sys.executable).name,
                    "health_url": f"http://127.0.0.1:{port}/health",
                    "log_path": str(log_path),
                    "health_timeout": 1.0,
                }
                repair_command = " ".join(
                    shlex.quote(value)
                    for value in (sys.executable, str(repair_path), str(state_path))
                )

                before = body.act("local_service_state", event_id="e2e21", **service_args)
                self.assertTrue(before.success)
                self.assertFalse(before.data["healthy"])
                self.assertEqual(before.data["health"]["status_code"], 503)
                self.assertTrue(before.data["listeners"])
                self.assertEqual(before.data["listeners"][0]["pid"], os.getpid())
                self.assertIn("ready=false", before.data["log"]["tail"])
                self.assertIsNone(before.data["repair_blocked_reason"])

                repair = body.act(
                    "command",
                    event_id="e2e21",
                    command=repair_command,
                    workdir=str(root),
                    timeout=10.0,
                )
                self.assertTrue(repair.success)
                self.assertIn("repair applied", repair.output)
                self.assertTrue(repair.data["side_effect_dispatch_observed"])

                after = self._wait_for_body_health(body, service_args)
                self.assertTrue(after.success)
                self.assertTrue(after.data["healthy"])
                self.assertEqual(after.data["health"]["status_code"], 200)
            finally:
                store.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=3.0)

    @staticmethod
    def _wait_for_body_health(body, service_args: dict) -> object:
        deadline = time.monotonic() + 5.0
        last = body.act("local_service_state", event_id="e2e21", **service_args)
        while not bool(last.data.get("healthy")) and time.monotonic() < deadline:
            time.sleep(0.05)
            last = body.act("local_service_state", event_id="e2e21", **service_args)
        return last

    @staticmethod
    def _wait_for_listener(port: int) -> None:
        import psutil

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            for connection in psutil.net_connections(kind="inet"):
                local = getattr(connection, "laddr", None)
                if getattr(local, "port", None) == port and str(connection.status).upper() == "LISTEN":
                    return
            time.sleep(0.05)
        raise AssertionError(f"local fixture did not expose listener on port {port}")


if __name__ == "__main__":
    unittest.main()

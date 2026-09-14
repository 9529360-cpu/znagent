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

from zn_agent.core.local_service_diagnosis import LocalServiceDiagnoser, LocalServiceTarget


class LocalServiceDiagnosisE2E(unittest.TestCase):
    def test_real_listener_log_health_repair_and_verification(self) -> None:
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
            try:
                port = int(server.server_address[1])
                self._wait_for_listener(port)
                target = LocalServiceTarget(
                    port=port,
                    host="127.0.0.1",
                    expected_process_name=Path(sys.executable).name,
                    health_url=f"http://127.0.0.1:{port}/health",
                    log_path=str(log_path),
                )
                repair_command = " ".join(
                    shlex.quote(value)
                    for value in (sys.executable, str(repair_path), str(state_path))
                )

                result = LocalServiceDiagnoser().diagnose_and_repair(
                    target,
                    repair_command=repair_command,
                    workdir=str(root),
                    verification_timeout=5.0,
                    verification_interval=0.05,
                    health_timeout=1.0,
                )

                self.assertFalse(result.before.healthy)
                self.assertEqual(result.before.health.status_code, 503)
                self.assertTrue(result.before.listeners)
                self.assertEqual(result.before.listeners[0].pid, os.getpid())
                self.assertIn("ready=false", result.before.log.tail)
                self.assertTrue(result.repair_attempted)
                self.assertTrue(result.repair_result.success)
                self.assertIn("repair applied", result.repair_result.output)
                self.assertTrue(result.after.healthy)
                self.assertEqual(result.after.health.status_code, 200)
                self.assertTrue(result.restored)
                self.assertTrue(result.success)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3.0)

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

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.local_service_recovery_behavior import _ACCEPTANCE
from zn_agent.core.provider_bridge import build_resident_runtime


TASK = (
    "看看这个服务为什么挂了，项目里的 `repair_service.py` 是它的安全修复脚本；"
    "能安全修就修，修好以后确认它真的恢复。"
)


class LocalServiceDiagnosisE2E(unittest.TestCase):
    def test_natural_language_root_work_repairs_once_and_freshly_verifies_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            state_path = workspace / "service.state"
            log_path = workspace / "service.log"
            repair_path = workspace / "repair_service.py"
            state_path.write_text("broken", encoding="utf-8")
            log_path.write_text("service booted\n", encoding="utf-8")
            repair_path.write_text(
                "from pathlib import Path\n"
                "Path('service.state').write_text('ready', encoding='utf-8')\n"
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
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                port = int(server.server_address[1])
                self._wait_for_listener(port)
                ledger = resident.work_ledger
                work_thread = "e2e21-product"
                ledger.create_thread(thread_id=work_thread, title="Local service recovery")
                ledger.attach_workspace(work_thread, workspace)

                _, run = ledger.submit(
                    work_thread,
                    TASK,
                    payload={
                        "local_service_context": {
                            "host": "127.0.0.1",
                            "port": port,
                            "expected_process_name": Path(sys.executable).name,
                            "health_path": "/health",
                            "log_relative_path": "service.log",
                        }
                    },
                )

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertIn("fresh", run.reason)
                self.assertEqual(state_path.read_text(encoding="utf-8"), "ready")

                actions = [
                    item
                    for item in resident.body.recent_actions(256)
                    if item.event_id == run.event.event_id
                ]
                service_actions = [item for item in actions if item.kind == "local_service_state"]
                command_actions = [item for item in actions if item.kind == "command"]
                self.assertGreaterEqual(len(service_actions), 3)
                self.assertEqual(len(command_actions), 1)
                self.assertTrue(command_actions[0].success)
                self.assertEqual(command_actions[0].output, "")
                self.assertTrue(command_actions[0].data.get("output_redacted"))

                root_item = resident.work_ledger.work_item_for_event(run.event.event_id)
                self.assertIsNotNone(root_item)
                children = [
                    item
                    for item in resident.work_ledger.list_work_items(work_thread, limit=64)
                    if root_item is not None
                    and item.parent_work_item_id == root_item.work_item_id
                    and _ACCEPTANCE in item.acceptance_criteria
                ]
                self.assertEqual(len(children), 1)
                child = children[0]
                self.assertEqual(child.status, "completed")
                evidence = json.loads(child.result)
                self.assertEqual(evidence["final_health_status"], 200)
                self.assertTrue(str(evidence["side_effect_attempt_id"]).startswith("sidefx-"))
                self.assertTrue(evidence["command_dispatch_observed"])
                self.assertNotIn(str(workspace), child.result)
                self.assertNotIn("repair_service.py", child.result)
                self.assertNotIn("service.log", child.result)

                with closing(sqlite3.connect(root / "kernel.db")) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions "
                        "WHERE event_id=? AND kind='command' ORDER BY completed_at DESC LIMIT 1",
                        (run.event.event_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                durable = " ".join(str(value) for value in row or ())
                self.assertNotIn(str(workspace), durable)
                self.assertNotIn("repair_service.py", durable)
                self.assertNotIn("repair applied", durable)
                self.assertIn("command_redacted", durable)
                self.assertIn("workdir_redacted", durable)
                self.assertIn("output_redacted", durable)

                self.assertIn("ready=false", log_path.read_text(encoding="utf-8"))
                self.assertIn("ready=true", log_path.read_text(encoding="utf-8"))
                print(
                    "ZN_E2E21_PRODUCT_EVIDENCE="
                    + json.dumps(
                        {
                            "natural_language_root_work": True,
                            "model_invocations": run.model_invocations,
                            "service_observations": len(service_actions),
                            "repair_dispatches": len(command_actions),
                            "initial_health": 503,
                            "final_health": evidence["final_health_status"],
                            "side_effect_attempt": bool(evidence["side_effect_attempt_id"]),
                            "durable_command_redacted": True,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
            finally:
                resident.store.close()
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
    unittest.main(verbosity=2)

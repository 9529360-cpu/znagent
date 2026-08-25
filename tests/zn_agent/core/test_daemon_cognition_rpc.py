from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class ResidentCognitionRpcTests(unittest.TestCase):
    def test_cognitive_history_surfaces_are_readable_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "zn_agent.core.life.shutil.disk_usage",
                return_value=SimpleNamespace(total=100, used=50, free=50),
            ):
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    server = ResidentRpcServer(
                        resident=resident,
                        input_stream=io.StringIO(),
                        output_stream=io.StringIO(),
                    )

                    resident.pulse()

                    situations = server.handle(
                        {"id": "s", "method": "situations", "params": {"limit": 5}}
                    )
                    thoughts = server.handle(
                        {"id": "t", "method": "thoughts", "params": {"limit": 5}}
                    )
                    impasses = server.handle(
                        {"id": "i", "method": "impasses", "params": {"limit": 5}}
                    )
                    learning = server.handle(
                        {"id": "l", "method": "learning", "params": {"limit": 5}}
                    )

                    self.assertTrue(situations["ok"])
                    self.assertGreaterEqual(len(situations["result"]), 1)
                    self.assertEqual(situations["result"][0]["external_brains"], ())
                    self.assertTrue(thoughts["ok"])
                    self.assertGreaterEqual(len(thoughts["result"]), 1)
                    self.assertEqual(thoughts["result"][0]["action_kind"], "observe")
                    self.assertEqual(impasses["result"], [])
                    self.assertEqual(learning["result"], [])
                finally:
                    resident.store.close()

    def test_open_impasse_is_visible_through_rpc_after_event_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )

                run = resident.submit("unknown task with no external brain")
                response = server.handle(
                    {"id": "i", "method": "impasses", "params": {"limit": 5}}
                )

                self.assertFalse(run.success)
                self.assertTrue(response["ok"])
                self.assertEqual(len(response["result"]), 1)
                self.assertEqual(response["result"][0]["event_id"], run.event.event_id)
                self.assertEqual(response["result"][0]["status"], "open")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

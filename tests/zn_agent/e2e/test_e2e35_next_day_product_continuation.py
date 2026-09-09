from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


TASK = "昨天那个产品继续，先看看做到哪了。"


class E2E35NextDayProductContinuationTests(unittest.TestCase):
    @staticmethod
    def _runtime(path: Path):
        return build_resident_runtime(config={"model": {}}, store_path=path)

    @staticmethod
    def _make_yesterday(ledger, thread_id: str) -> None:
        thread = ledger.get_thread(thread_id)
        assert thread is not None
        thread.updated_at = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
        ledger._save_thread(thread)

    def test_next_day_status_inspection_resolves_the_existing_work_through_rpc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zn-e2e35-baseline-") as tmp:
            root = Path(tmp)
            workspace = root / "product"
            workspace.mkdir()
            db = root / "kernel.db"

            first = self._runtime(db)
            try:
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
                ledger = control.ledger
                ledger.create_thread(thread_id="product", title="Local ledger product")
                ledger.attach_workspace("product", workspace, name="Product workspace")
                _, event = ledger.start(
                    "product",
                    "开发一个本地个人记账产品，核心记账和本地保存先跑通。",
                )
                event_id = event.event_id
                self._make_yesterday(ledger, "product")
            finally:
                first.store.close()

            restored = self._runtime(db)
            server = ResidentRpcServer(resident=restored)
            try:
                created = server.handle(
                    {
                        "id": "create-shell",
                        "method": "work_create",
                        "params": {"thread_id": "fresh-ui", "title": "New work"},
                    }
                )
                self.assertTrue(created["ok"])

                inspected = server.handle(
                    {
                        "id": "inspect",
                        "method": "work_start",
                        "params": {"thread_id": "fresh-ui", "task": TASK},
                    }
                )

                self.assertTrue(inspected["ok"])
                self.assertEqual(inspected["result"]["thread"]["id"], "product")
                self.assertEqual(inspected["result"]["progress"]["event_id"], event_id)
                self.assertIn(
                    "continuation_inspection",
                    inspected["result"]["progress"],
                )
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

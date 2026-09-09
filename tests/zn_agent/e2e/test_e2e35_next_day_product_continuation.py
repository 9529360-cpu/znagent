from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work import WorkArtifact
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


TASK = "昨天那个产品继续，先看看做到哪了。"
ROOT_GOAL = "开发一个本地个人记账产品，核心记账和本地保存先跑通。"


class E2E35NextDayProductContinuationTests(unittest.TestCase):
    @staticmethod
    def _runtime(path: Path):
        return build_resident_runtime(config={"model": {}}, store_path=path)

    @staticmethod
    def _yesterday() -> str:
        return (datetime.now().astimezone() - timedelta(days=1)).isoformat()

    @classmethod
    def _make_yesterday(cls, ledger, thread_id: str) -> None:
        thread = ledger.get_thread(thread_id)
        assert thread is not None
        thread.updated_at = cls._yesterday()
        ledger._save_thread(thread)

    @classmethod
    def _seed_day_one(cls, resident, workspace: Path):
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="product", title="Local ledger product")
        ledger.attach_workspace("product", workspace, name="Product workspace")
        _, event = ledger.start(
            "product",
            ROOT_GOAL,
            objective=ROOT_GOAL,
            acceptance_criteria=[
                "核心记账流程有 durable Work evidence",
                "本地保存结果有独立验证",
            ],
        )
        root = ledger.work_item_for_event(event.event_id)
        assert root is not None

        model = ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="建立本地收支数据结构",
            acceptance_criteria=["durable structure evidence"],
            title="Initial data structure",
        )
        worker = ledger.start_worker_run(
            work_item_id=model.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )
        ledger.complete_worker_run(
            worker.worker_run_id,
            result_summary="local-first structure checked",
            verification_status="accepted",
        )
        model = ledger.complete_child_item(
            model.work_item_id,
            result="local-first structure checked",
        )

        flow = ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="实现新增收入和支出流程",
            acceptance_criteria=["durable flow evidence"],
            title="Income and expense flow",
        )
        flow = ledger.complete_child_item(
            flow.work_item_id,
            result="flow accepted",
        )

        save = ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="验证本地保存结果",
            acceptance_criteria=["persisted result reloads"],
            title="Persisted save verification",
        )
        save = ledger.block_child_item(
            save.work_item_id,
            blocker="本地保存验证还没通过，等待重新核对持久化结果。",
        )

        day_one = cls._yesterday()
        for item in (root, model, flow, save):
            item.updated_at = day_one
            if item.status == "completed":
                item.completed_at = day_one
            ledger._save_item(item)

        app = workspace / "app.py"
        data = workspace / "data.json"
        app.write_text("def add_entry(amount):\n    return {'amount': amount}\n", encoding="utf-8")
        data.write_text('{"entries": []}\n', encoding="utf-8")
        subprocess.run(
            ["git", "init", str(workspace)],
            check=True,
            capture_output=True,
            text=True,
        )
        for artifact_id, path in (("artifact-app", app), ("artifact-data", data)):
            ledger._save_artifact(
                WorkArtifact(
                    artifact_id=artifact_id,
                    thread_id="product",
                    event_id=event.event_id,
                    kind="file",
                    name=path.name,
                    content=path.read_text(encoding="utf-8"),
                    path=str(path),
                    metadata={
                        "workspace_relative_path": path.name,
                        "source": "body",
                        "truncated": False,
                        "historical_verified": True,
                    },
                    created_at=day_one,
                )
            )

        cls._make_yesterday(ledger, "product")
        return {
            "control": control,
            "ledger": ledger,
            "event_id": event.event_id,
            "root_id": root.work_item_id,
            "worker_id": worker.worker_run_id,
            "app": app,
            "data": data,
        }

    @staticmethod
    def _rpc_start(server: ResidentRpcServer, thread_id: str, task: str):
        return server.handle(
            {
                "id": f"start-{thread_id}",
                "method": "work_start",
                "params": {"thread_id": thread_id, "task": task},
            }
        )

    @staticmethod
    def _create_shell(server: ResidentRpcServer, thread_id: str = "fresh-ui") -> None:
        created = server.handle(
            {
                "id": f"create-{thread_id}",
                "method": "work_create",
                "params": {"thread_id": thread_id, "title": "New work"},
            }
        )
        assert created["ok"], created

    def test_restart_happy_path_reconstructs_same_work_with_fresh_read_only_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zn-e2e35-happy-") as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "product"
            workspace.mkdir()
            db = root_dir / "kernel.db"

            first = self._runtime(db)
            try:
                seeded = self._seed_day_one(first, workspace)
                event_id = seeded["event_id"]
                root_id = seeded["root_id"]
            finally:
                first.store.close()

            restored = self._runtime(db)
            server = ResidentRpcServer(resident=restored)
            try:
                self._create_shell(server)
                ledger = server.work_control.ledger
                before_events = [item.event_id for item in restored.store.list_events(limit=256)]
                before_workers = [
                    run.worker_run_id for run in ledger.list_worker_runs(thread_id="product", limit=256)
                ]
                before_plan = ledger.plan_version("product")
                before_items = [
                    (item.work_item_id, item.status, item.blocker, item.plan_version)
                    for item in ledger.list_work_items("product", limit=256)
                ]
                before_model = restored.store.get_runtime_metrics().model_invocations
                before_actions = len(restored.body.recent_actions(limit=512))
                before_app = seeded["app"].read_text(encoding="utf-8")
                before_data = seeded["data"].read_text(encoding="utf-8")

                inspected = self._rpc_start(server, "fresh-ui", TASK)
                self.assertTrue(inspected["ok"], inspected)
                result = inspected["result"]
                progress = result["progress"]
                status = progress["continuation_inspection"]

                self.assertEqual(result["thread"]["id"], "product")
                self.assertEqual(progress["thread_id"], "product")
                self.assertEqual(progress["event_id"], event_id)
                self.assertTrue(status["read_only"])
                self.assertTrue(status["inspection_complete"])
                self.assertEqual(status["root_goal"], ROOT_GOAL)
                self.assertEqual(status["plan_version"], before_plan)
                self.assertEqual(len(status["completed"]), 2)
                self.assertEqual(len(status["blocked"]), 1)
                self.assertEqual(len(status["blockers"]), 1)
                self.assertEqual(len(status["artifacts"]), 2)
                self.assertFalse(status["drift_detected"])
                self.assertTrue(status["environment"]["workspace_present"])
                self.assertTrue(status["environment"]["git"]["is_repository"])
                self.assertTrue(status["inspected_at"])
                self.assertIn("delegation", status)
                self.assertTrue(all(
                    item["current"]["status"] == "unchanged"
                    for item in status["artifacts"]
                ))

                after_events = [item.event_id for item in restored.store.list_events(limit=256)]
                after_workers = [
                    run.worker_run_id for run in ledger.list_worker_runs(thread_id="product", limit=256)
                ]
                after_items = [
                    (item.work_item_id, item.status, item.blocker, item.plan_version)
                    for item in ledger.list_work_items("product", limit=256)
                ]
                self.assertEqual(after_events, before_events)
                self.assertEqual(after_workers, before_workers)
                self.assertEqual(ledger.plan_version("product"), before_plan)
                self.assertEqual(after_items, before_items)
                self.assertEqual(restored.store.get_runtime_metrics().model_invocations, before_model)
                self.assertEqual(seeded["app"].read_text(encoding="utf-8"), before_app)
                self.assertEqual(seeded["data"].read_text(encoding="utf-8"), before_data)
                self.assertEqual(ledger._work_item_by_id(root_id).work_item_id, root_id)

                new_actions = restored.body.recent_actions(limit=512)[:]
                self.assertGreater(len(new_actions), before_actions)
                mutation_kinds = {
                    "write_text",
                    "write_file",
                    "command",
                    "terminal",
                    "shell",
                    "pointer_click",
                    "pointer_move",
                }
                self.assertFalse(any(action.kind in mutation_kinds for action in new_actions))

                continued = self._rpc_start(server, "product", "继续")
                self.assertTrue(continued["ok"], continued)
                self.assertEqual(continued["result"]["thread"]["id"], "product")
                self.assertEqual(continued["result"]["progress"]["event_id"], event_id)
                self.assertEqual(
                    [item.event_id for item in restored.store.list_events(limit=256)],
                    before_events,
                )
                self.assertEqual(ledger.plan_version("product"), before_plan)
                self.assertEqual(restored.store.get_runtime_metrics().model_invocations, before_model)
            finally:
                restored.store.close()

    def test_restart_detects_modified_and_missing_artifacts_without_erasing_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zn-e2e35-drift-") as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "product"
            workspace.mkdir()
            db = root_dir / "kernel.db"

            first = self._runtime(db)
            try:
                seeded = self._seed_day_one(first, workspace)
                event_id = seeded["event_id"]
            finally:
                first.store.close()

            seeded["app"].write_text(
                "def add_entry(amount):\n    return {'amount': amount, 'edited': True}\n",
                encoding="utf-8",
            )
            seeded["data"].unlink()

            restored = self._runtime(db)
            server = ResidentRpcServer(resident=restored)
            try:
                self._create_shell(server)
                ledger = server.work_control.ledger
                before_model = restored.store.get_runtime_metrics().model_invocations
                before_workers = len(ledger.list_worker_runs(thread_id="product", limit=256))
                before_events = len(restored.store.list_events(limit=256))
                completed_before = {
                    item.work_item_id
                    for item in ledger.list_work_items("product", limit=256)
                    if item.status == "completed"
                }

                inspected = self._rpc_start(server, "fresh-ui", TASK)
                self.assertTrue(inspected["ok"], inspected)
                progress = inspected["result"]["progress"]
                status = progress["continuation_inspection"]
                self.assertEqual(progress["event_id"], event_id)
                self.assertTrue(status["drift_detected"])
                by_path = {item["path"]: item for item in status["artifacts"]}
                self.assertEqual(by_path["app.py"]["historical"]["status"], "recorded")
                self.assertEqual(by_path["app.py"]["current"]["status"], "modified")
                self.assertEqual(by_path["data.json"]["historical"]["status"], "recorded")
                self.assertEqual(by_path["data.json"]["current"]["status"], "missing")
                self.assertEqual(len(status["completed"]), 2)

                completed_after = {
                    item.work_item_id
                    for item in ledger.list_work_items("product", limit=256)
                    if item.status == "completed"
                }
                self.assertEqual(completed_after, completed_before)
                self.assertEqual(len(ledger.list_worker_runs(thread_id="product", limit=256)), before_workers)
                self.assertEqual(len(restored.store.list_events(limit=256)), before_events)
                self.assertEqual(restored.store.get_runtime_metrics().model_invocations, before_model)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

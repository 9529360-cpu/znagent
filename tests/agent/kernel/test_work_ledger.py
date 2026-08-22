from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.work import ResidentWorkLedger


class ResidentWorkLedgerTests(unittest.TestCase):
    def test_work_history_survives_resident_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-persistent")
            snapshot, run = ledger.submit(
                thread.thread_id,
                "unknown task with no external brain",
            )

            self.assertFalse(run.success)
            saved_thread, messages = snapshot
            self.assertEqual(saved_thread.thread_id, "work-persistent")
            self.assertEqual(saved_thread.title, "unknown task with no external brain")
            self.assertEqual([message.role for message in messages], ["user", "zn", "activity"])
            self.assertEqual(messages[-1].detail["event_id"], run.event.event_id)
            self.assertEqual(run.event.payload["work_thread_id"], "work-persistent")
            self.assertEqual(
                run.event.payload["work_message_id"],
                messages[0].message_id,
            )
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            snapshots = restored_ledger.list_snapshots()

            self.assertEqual(len(snapshots), 1)
            restored_thread, restored_messages = snapshots[0]
            self.assertEqual(restored_thread.thread_id, "work-persistent")
            self.assertEqual(
                [message.message_id for message in restored_messages],
                [message.message_id for message in messages],
            )
            restored.store.close()

    def test_workspace_association_persists_and_anchors_native_git_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "project"
            workspace.mkdir()
            subprocess.run(
                ["git", "init", str(workspace)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(workspace), "symbolic-ref", "HEAD", "refs/heads/zn-workspace"],
                check=True,
                capture_output=True,
                text=True,
            )

            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-workspace")
            attached = ledger.attach_workspace(thread.thread_id, workspace, name="Project")
            association = ledger.workspace_for(attached)

            self.assertIsNotNone(association)
            assert association is not None
            self.assertEqual(association.path, str(workspace.resolve()))
            self.assertEqual(association.name, "Project")

            snapshot, run = ledger.submit(
                thread.thread_id,
                "what is current git branch?",
            )
            self.assertTrue(run.success)
            self.assertEqual(run.response, "zn-workspace")
            self.assertEqual(run.event.payload["workspace_path"], str(workspace.resolve()))
            self.assertEqual(run.event.payload["workdir"], str(workspace.resolve()))
            saved_thread, messages = snapshot
            self.assertEqual(saved_thread.metadata["workspace"]["path"], str(workspace.resolve()))
            self.assertEqual(messages[-1].detail["workspace"]["name"], "Project")
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            restored_thread, _ = restored_ledger.get_snapshot("work-workspace")
            restored_workspace = restored_ledger.workspace_for(restored_thread)
            self.assertIsNotNone(restored_workspace)
            assert restored_workspace is not None
            self.assertEqual(restored_workspace.path, str(workspace.resolve()))
            restored.store.close()

    def test_workspace_is_reserved_metadata_and_requires_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(
                thread_id="work-reserved",
                metadata={
                    "workspace": {"path": str(root), "name": "forged"},
                    "tag": "keep",
                },
            )
            self.assertNotIn("workspace", thread.metadata)
            self.assertEqual(thread.metadata["tag"], "keep")

            file_path = root / "not-a-folder.txt"
            file_path.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a directory"):
                ledger.attach_workspace(thread.thread_id, file_path)
            resident.store.close()

    def test_dirty_workspace_produces_persistent_file_and_diff_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "project"
            workspace.mkdir()
            subprocess.run(
                ["git", "init", str(workspace)],
                check=True,
                capture_output=True,
                text=True,
            )
            target = workspace / "notes.txt"
            target.write_text("before\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(workspace), "add", "notes.txt"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(workspace),
                    "-c", "user.name=ZN Test",
                    "-c", "user.email=zn-test@example.invalid",
                    "commit", "-m", "baseline",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            target.write_text("after\n", encoding="utf-8")
            status = subprocess.run(
                ["git", "-C", str(workspace), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("notes.txt", status.stdout)

            store_path = root / "kernel.db"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = ResidentWorkLedger(resident)
            thread = ledger.create_thread(thread_id="work-artifacts")
            ledger.attach_workspace(thread.thread_id, workspace, name="Project")

            snapshot, run = ledger.submit(
                thread.thread_id,
                "which files changed in this workspace?",
            )
            self.assertTrue(run.success)

            artifacts = ledger.list_artifacts(thread.thread_id)
            self.assertTrue(any(item.kind == "file" for item in artifacts))
            self.assertTrue(any(item.kind == "diff" for item in artifacts))
            file_artifact = next(item for item in artifacts if item.kind == "file")
            diff_artifact = next(item for item in artifacts if item.kind == "diff")
            self.assertEqual(file_artifact.name, "notes.txt")
            self.assertEqual(file_artifact.content, "after\n")
            self.assertIn("-before", diff_artifact.content)
            self.assertIn("+after", diff_artifact.content)
            self.assertEqual(
                diff_artifact.metadata["scope"],
                "current_workspace_after_event",
            )
            self.assertEqual(
                snapshot[1][-1].detail["artifacts"][0]["id"].split("-")[0],
                "artifact",
            )

            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )
            rpc = server.handle(
                {
                    "id": "get-artifacts",
                    "method": "work_get",
                    "params": {"thread_id": thread.thread_id},
                }
            )
            self.assertTrue(rpc["ok"])
            self.assertTrue(any(item["kind"] == "diff" for item in rpc["result"]["artifacts"]))
            resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            restored_ledger = ResidentWorkLedger(restored)
            restored_artifacts = restored_ledger.list_artifacts(thread.thread_id)
            self.assertEqual(
                {item.artifact_id for item in restored_artifacts},
                {item.artifact_id for item in artifacts},
            )
            restored.store.close()

    def test_work_rpc_is_resident_backed_and_updates_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )

            created = server.handle(
                {
                    "id": "create",
                    "method": "work_create",
                    "params": {"thread_id": "work-rpc"},
                }
            )
            self.assertTrue(created["ok"])
            self.assertEqual(created["result"]["id"], "work-rpc")
            self.assertEqual(created["result"]["messages"], [])
            self.assertEqual(created["result"]["artifacts"], [])

            attached = server.handle(
                {
                    "id": "attach",
                    "method": "work_attach_workspace",
                    "params": {
                        "thread_id": "work-rpc",
                        "workspace_path": str(workspace),
                        "workspace_name": "Workspace",
                    },
                }
            )
            self.assertTrue(attached["ok"])
            self.assertEqual(
                attached["result"]["metadata"]["workspace"]["path"],
                str(workspace.resolve()),
            )

            submitted = server.handle(
                {
                    "id": "submit",
                    "method": "work_submit",
                    "params": {
                        "thread_id": "work-rpc",
                        "task": "unknown task with no external brain",
                    },
                }
            )
            self.assertTrue(submitted["ok"])
            self.assertEqual(submitted["result"]["thread"]["id"], "work-rpc")
            self.assertEqual(
                [message["role"] for message in submitted["result"]["thread"]["messages"]],
                ["user", "zn", "activity"],
            )
            self.assertEqual(
                submitted["result"]["thread"]["messages"][-1]["detail"]["workspace"]["path"],
                str(workspace.resolve()),
            )
            self.assertFalse(submitted["result"]["run"]["success"])

            detached = server.handle(
                {
                    "id": "detach",
                    "method": "work_detach_workspace",
                    "params": {"thread_id": "work-rpc"},
                }
            )
            self.assertTrue(detached["ok"])
            self.assertNotIn("workspace", detached["result"]["metadata"])

            listed = server.handle(
                {"id": "list", "method": "work_list", "params": {"limit": 24}}
            )
            self.assertTrue(listed["ok"])
            self.assertEqual(len(listed["result"]), 1)
            self.assertEqual(listed["result"][0]["id"], "work-rpc")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

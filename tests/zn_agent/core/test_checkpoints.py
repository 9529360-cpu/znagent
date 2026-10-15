from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.checkpoint import (
    EXTERNAL_SIDE_EFFECTS_NOTICE,
    CheckpointStore,
)
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


def _write(root: Path, rel: str, content: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read(root: Path, rel: str) -> bytes:
    return (root / rel).read_bytes()


class CheckpointStoreTests(unittest.TestCase):
    def test_create_lists_snapshot_under_hidden_files_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/note.txt", b"v1")
            _write(root, "drafts/plan.md", b"draft")
            store = CheckpointStore(root)
            created = store.create(trigger="manual", reason="before edit")
            self.assertEqual(created.trigger, "manual")
            self.assertFalse(created.reused)
            listed = store.list()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["checkpoint_id"], created.checkpoint_id)
            # Git-free: no .git anywhere in the workspace, yet it works.
            self.assertFalse((root / ".git").exists())
            # Stored under hidden_files (internal bookkeeping), not your_files.
            snapshot_dir = root / "hidden_files" / "checkpoints" / created.checkpoint_id
            self.assertTrue((snapshot_dir / "manifest.json").is_file())
            self.assertEqual(
                _read(snapshot_dir / "files", "your_files/note.txt"), b"v1"
            )
            self.assertFalse((root / "your_files" / "checkpoints").exists())

    def test_snapshot_excludes_hidden_files_and_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/keep.txt", b"keep")
            _write(root, "hidden_files/ledger.json", b"internal")
            _write(root, ".trash/deleted.txt", b"trashed")
            store = CheckpointStore(root)
            created = store.create(trigger="manual")
            paths = [entry.path for entry in created.files]
            self.assertEqual(paths, ["your_files/keep.txt"])

    def test_create_dedups_identical_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/note.txt", b"same")
            store = CheckpointStore(root)
            first = store.create(trigger="manual")
            second = store.create(trigger="manual")
            self.assertEqual(second.checkpoint_id, first.checkpoint_id)
            self.assertTrue(second.reused)
            self.assertEqual(len(store.list()), 1)
            _write(root, "your_files/note.txt", b"changed")
            third = store.create(trigger="manual")
            self.assertNotEqual(third.checkpoint_id, first.checkpoint_id)
            self.assertFalse(third.reused)
            self.assertEqual(len(store.list()), 2)

    def test_preview_reports_diff_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/a.txt", b"a1")
            _write(root, "your_files/b.txt", b"b1")
            _write(root, "your_files/c.txt", b"c1")
            store = CheckpointStore(root)
            created = store.create(trigger="manual")
            before = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            _write(root, "your_files/a.txt", b"a2")
            (root / "your_files/b.txt").unlink()
            _write(root, "your_files/d.txt", b"d1")
            preview = store.preview(created.checkpoint_id)
            by_path = {row["path"]: row["status"] for row in preview["diff"]}
            self.assertEqual(by_path["your_files/a.txt"], "modified")
            # Statuses describe what a restore WILL DO: b.txt is in the
            # snapshot but gone now, so restore adds it back; d.txt
            # exists now but is not in the snapshot, so restore deletes it.
            self.assertEqual(by_path["your_files/b.txt"], "added")
            self.assertEqual(by_path["your_files/c.txt"], "unchanged")
            self.assertEqual(by_path["your_files/d.txt"], "deleted")
            self.assertIn("外部副作用", preview["external_side_effects_notice"])
            after = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before.keys() | {"a.txt", "d.txt"}, after.keys())
            self.assertEqual(_read(root, "your_files/a.txt"), b"a2")

    def test_restore_recovers_snapshot_and_backup_recovers_pre_restore_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/note.txt", b"original")
            _write(root, "drafts/plan.md", b"plan v1")
            store = CheckpointStore(root)
            snapshot = store.create(trigger="manual", reason="v1")
            _write(root, "your_files/note.txt", b"edited")
            (root / "drafts/plan.md").unlink()
            _write(root, "your_files/new.txt", b"added later")
            result = store.restore(snapshot.checkpoint_id)
            self.assertEqual(result["restored_checkpoint_id"], snapshot.checkpoint_id)
            self.assertIn("外部副作用", result["external_side_effects_notice"])
            self.assertIn("核对清单", result["external_side_effects_checklist"])
            # Restored exactly to the snapshot.
            self.assertEqual(_read(root, "your_files/note.txt"), b"original")
            self.assertEqual(_read(root, "drafts/plan.md"), b"plan v1")
            self.assertFalse((root / "your_files/new.txt").exists())
            # The pre-restore state was NOT destroyed: the automatic
            # backup snapshot brings it back.
            backup_id = result["backup_checkpoint_id"]
            self.assertNotEqual(backup_id, snapshot.checkpoint_id)
            store.restore(backup_id)
            self.assertEqual(_read(root, "your_files/note.txt"), b"edited")
            self.assertFalse((root / "drafts/plan.md").exists())
            self.assertEqual(_read(root, "your_files/new.txt"), b"added later")

    def test_restore_only_restores_the_selected_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/note.txt", b"v1")
            store = CheckpointStore(root)
            first = store.create(trigger="manual", reason="v1")
            _write(root, "your_files/note.txt", b"v2")
            second = store.create(trigger="manual", reason="v2")
            _write(root, "your_files/note.txt", b"v3")
            store.restore(first.checkpoint_id)
            self.assertEqual(_read(root, "your_files/note.txt"), b"v1")
            store.restore(second.checkpoint_id)
            self.assertEqual(_read(root, "your_files/note.txt"), b"v2")

    def test_restore_and_preview_reject_unknown_and_unsafe_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            store = CheckpointStore(root)
            with self.assertRaises(ValueError):
                store.restore("no-such-checkpoint")
            with self.assertRaises(ValueError):
                store.preview("../escape")
            with self.assertRaises(ValueError):
                store.get("a/b")
            with self.assertRaises(ValueError):
                store.create(trigger="forged-trigger")

    def test_snapshot_refuses_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/real.txt", b"real")
            outside = Path(tmp) / "outside.txt"
            outside.write_bytes(b"outside")
            link = root / "your_files/link.txt"
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(outside)
            store = CheckpointStore(root)
            with self.assertRaises(ValueError):
                store.create(trigger="manual")

    def test_binary_files_round_trip_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            blob = bytes(range(256)) * 4
            _write(root, "your_files/blob.bin", blob)
            store = CheckpointStore(root)
            snapshot = store.create(trigger="manual")
            _write(root, "your_files/blob.bin", b"clobbered")
            store.restore(snapshot.checkpoint_id)
            self.assertEqual(_read(root, "your_files/blob.bin"), blob)

    def test_pre_change_snapshot_records_its_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            _write(root, "your_files/note.txt", b"x")
            store = CheckpointStore(root)
            snapshot = store.ensure_pre_change_snapshot(
                trigger="pre_undo", reason="before undo"
            )
            self.assertEqual(snapshot.trigger, "pre_undo")
            self.assertEqual(store.get(snapshot.checkpoint_id).trigger, "pre_undo")


def _make_server(tmp: str) -> ResidentRpcServer:
    resident = build_resident_runtime_from_existing_stack(
        config={"model": {}},
        store_path=Path(tmp) / "kernel.db",
    )
    return ResidentRpcServer(
        resident=resident,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )


class CheckpointRpcTests(unittest.TestCase):
    def test_checkpoint_rpcs_create_preview_restore_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp)
            try:
                workspace = str(Path(tmp) / "workspace")
                root = Path(workspace)
                _write(root, "your_files/note.txt", b"before")
                created = server.handle(
                    {
                        "id": "c1",
                        "method": "checkpoint_create",
                        "params": {"workspace_root": workspace, "reason": "demo"},
                    }
                )
                self.assertTrue(created["ok"])
                checkpoint_id = created["result"]["checkpoint_id"]
                self.assertEqual(created["result"]["trigger"], "manual")
                listed = server.handle(
                    {
                        "id": "c2",
                        "method": "checkpoint_list",
                        "params": {"workspace_root": workspace},
                    }
                )
                self.assertTrue(listed["ok"])
                self.assertEqual(len(listed["result"]), 1)
                _write(root, "your_files/note.txt", b"after")
                preview = server.handle(
                    {
                        "id": "c3",
                        "method": "checkpoint_preview",
                        "params": {
                            "workspace_root": workspace,
                            "checkpoint_id": checkpoint_id,
                        },
                    }
                )
                self.assertTrue(preview["ok"])
                statuses = {
                    row["path"]: row["status"] for row in preview["result"]["diff"]
                }
                self.assertEqual(statuses["your_files/note.txt"], "modified")
                restored = server.handle(
                    {
                        "id": "c4",
                        "method": "checkpoint_restore",
                        "params": {
                            "workspace_root": workspace,
                            "checkpoint_id": checkpoint_id,
                        },
                    }
                )
                self.assertTrue(restored["ok"])
                self.assertEqual(
                    restored["result"]["restored_checkpoint_id"], checkpoint_id
                )
                self.assertTrue(restored["result"]["backup_checkpoint_id"])
                self.assertIn(
                    EXTERNAL_SIDE_EFFECTS_NOTICE,
                    restored["result"]["external_side_effects_notice"],
                )
                self.assertEqual(_read(root, "your_files/note.txt"), b"before")
            finally:
                server.resident.store.close()

    def test_checkpoint_rpc_rejects_unknown_params_and_missing_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp)
            try:
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "x",
                            "method": "checkpoint_create",
                            "params": {"workspace_root": tmp, "trigger": "pre_restore"},
                        }
                    )
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "x",
                            "method": "checkpoint_restore",
                            "params": {"workspace_root": tmp},
                        }
                    )
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "x",
                            "method": "checkpoint_preview",
                            "params": {
                                "workspace_root": tmp,
                                "checkpoint_id": "missing",
                            },
                        }
                    )
            finally:
                server.resident.store.close()

    def test_approval_undo_takes_pre_undo_checkpoint_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _make_server(tmp)
            try:
                workspace = Path(tmp) / "workspace"
                _write(workspace, "your_files/note.txt", b"after")
                store = server._approvals()
                request = store.request_approval(
                    action_kind="production_change",
                    target="your_files/note.txt",
                    scope="workspace:your_files/note.txt",
                    previous_content="before",
                    previous_captured=True,
                )
                store.decide(request.request_id, "allow_once")
                self.assertTrue(store.consume(request.request_id))
                with patch(
                    "zn_agent.core.daemon.default_workspace_root",
                    return_value=workspace,
                ):
                    response = server.handle(
                        {
                            "id": "u",
                            "method": "approval_undo",
                            "params": {"request_id": request.request_id},
                        }
                    )
                self.assertTrue(response["ok"])
                pre_undo_id = response["result"]["pre_undo_checkpoint_id"]
                self.assertTrue(pre_undo_id)
                # Undo restored the file; the pre-undo checkpoint holds
                # the state from before the undo.
                self.assertEqual(_read(workspace, "your_files/note.txt"), b"before")
                checkpoint_store = CheckpointStore(workspace)
                pre_undo = checkpoint_store.get(pre_undo_id)
                self.assertEqual(pre_undo.trigger, "pre_undo")
                checkpoint_store.restore(pre_undo_id)
                self.assertEqual(_read(workspace, "your_files/note.txt"), b"after")
            finally:
                server.resident.store.close()


if __name__ == "__main__":
    unittest.main()

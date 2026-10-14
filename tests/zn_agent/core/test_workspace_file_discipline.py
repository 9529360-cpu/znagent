from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_authority import (
    ActionAuthorityContext,
    WorkerActionAuthorityEnforcer,
    WorkerActionAuthorityError,
)
from zn_agent.core.body import NativeBody
from zn_agent.core.workspace_file_discipline import (
    WorkspaceFileDisciplineError,
    WorkspaceLayout,
    check_write,
    classify_path,
    default_workspace_root,
    empty_trash,
    list_trash,
    promote_draft_to_deliverable,
    purge_trashed,
    resolve_write_path,
    restore_path,
    trash_path,
    write_bytes,
    write_text,
)


def _layout(tmp: Path) -> WorkspaceLayout:
    return WorkspaceLayout(tmp / "workspace").ensure()


class LayoutTests(unittest.TestCase):
    def test_three_dirs_plus_trash_and_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            for directory in (
                layout.deliverables_dir,
                layout.drafts_dir,
                layout.internal_dir,
                layout.trash_dir,
            ):
                self.assertTrue(directory.is_dir())
            self.assertEqual(
                classify_path(layout.deliverables_dir / "report.md", root=layout.root),
                "deliverable",
            )
            self.assertEqual(
                classify_path(layout.drafts_dir / "scratch.txt", root=layout.root),
                "draft",
            )
            self.assertEqual(
                classify_path(layout.internal_dir / "watermark.json", root=layout.root),
                "internal",
            )
            self.assertEqual(
                classify_path(layout.trash_dir / "entry" / "payload", root=layout.root),
                "trash",
            )
            self.assertIsNone(classify_path(layout.root / "stray.txt", root=layout.root))
            self.assertIsNone(classify_path("/etc/passwd", root=layout.root))

    def test_default_root_lives_under_zn_home(self):
        root = default_workspace_root(home="/tmp/fake-zn-home")
        self.assertEqual(root, Path("/tmp/fake-zn-home") / "workspace")


class WriteGuardTests(unittest.TestCase):
    def test_internal_ledger_never_writes_into_deliverables(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            deliverable_target = layout.deliverables_dir / "watermark.json"
            with self.assertRaises(WorkspaceFileDisciplineError):
                check_write(deliverable_target, "internal", root=layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                write_text(
                    layout.root, "internal", "../your_files/watermark.json", "{}"
                )
            # And the reverse direction is equally rejected.
            with self.assertRaises(WorkspaceFileDisciplineError):
                check_write(layout.internal_dir / "report.md", "deliverable", root=layout.root)
            self.assertFalse(deliverable_target.exists())

    def test_unclassified_and_outside_writes_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            with self.assertRaises(WorkspaceFileDisciplineError):
                check_write(layout.root / "stray.txt", "draft", root=layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                check_write("/tmp/outside-workspace.txt", "draft", root=layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                resolve_write_path(layout.root, "draft", "../escape.txt")
            with self.assertRaises(WorkspaceFileDisciplineError):
                resolve_write_path(layout.root, "draft", "/absolute.txt")

    def test_write_text_and_bytes_happy_path_and_overwrite_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            target = write_text(layout.root, "draft", "notes.txt", "hello")
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            with self.assertRaises(FileExistsError):
                write_text(layout.root, "draft", "notes.txt", "again")
            replaced = write_text(
                layout.root, "draft", "notes.txt", "again", overwrite=True
            )
            self.assertEqual(replaced.read_text(encoding="utf-8"), "again")
            blob = write_bytes(layout.root, "internal", "state.bin", b"\x00\x01")
            self.assertEqual(blob.read_bytes(), b"\x00\x01")


class PromoteTests(unittest.TestCase):
    def test_promote_moves_never_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            draft = write_text(layout.root, "draft", "report.md", "final content")
            dest = promote_draft_to_deliverable(layout.root, draft, "report.md")
            self.assertEqual(dest, layout.deliverables_dir / "report.md")
            self.assertEqual(dest.read_text(encoding="utf-8"), "final content")
            self.assertFalse(draft.exists())  # no duplicate left to drift
            self.assertEqual(
                classify_path(dest, root=layout.root), "deliverable"
            )

    def test_promote_refuses_internal_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            internal = write_text(layout.root, "internal", "log.json", "{}")
            with self.assertRaises(WorkspaceFileDisciplineError):
                promote_draft_to_deliverable(layout.root, internal, "log.json")
            first = write_text(layout.root, "draft", "a.md", "a")
            write_text(layout.root, "deliverable", "a.md", "existing")
            with self.assertRaises(FileExistsError):
                promote_draft_to_deliverable(layout.root, first, "a.md")
            self.assertTrue(first.exists())


class TrashRestoreTests(unittest.TestCase):
    def test_trash_file_then_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            target = write_text(layout.root, "draft", "note.txt", "keep me")
            entry = trash_path(target, layout.root)
            self.assertFalse(target.exists())
            self.assertEqual(entry.original_path, str(target))
            self.assertTrue(entry.deleted_at)
            self.assertEqual(entry.kind, "file")
            listed = list_trash(layout.root)
            self.assertEqual([item.entry_id for item in listed], [entry.entry_id])
            self.assertEqual(listed[0].original_path, str(target))
            restored = restore_path(entry.entry_id, layout.root)
            self.assertEqual(restored, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(list_trash(layout.root), [])

    def test_trash_directory_requires_explicit_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            folder = layout.drafts_dir / "bundle"
            (folder / "nested").mkdir(parents=True)
            (folder / "nested" / "a.txt").write_text("a", encoding="utf-8")
            (folder / "b.txt").write_text("b", encoding="utf-8")
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(folder, layout.root)
            self.assertTrue(folder.is_dir())  # refused delete leaves it intact
            entry = trash_path(folder, layout.root, confirm=True)
            self.assertEqual(entry.kind, "directory")
            self.assertFalse(folder.exists())
            restored = restore_path(entry.entry_id, layout.root)
            self.assertEqual(
                (restored / "nested" / "a.txt").read_text(encoding="utf-8"), "a"
            )
            self.assertEqual((restored / "b.txt").read_text(encoding="utf-8"), "b")

    def test_restore_collision_refuses_then_overwrite_trashes_occupant(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            target = write_text(layout.root, "draft", "note.txt", "original")
            entry = trash_path(target, layout.root)
            write_text(layout.root, "draft", "note.txt", "occupant")
            with self.assertRaises(FileExistsError):
                restore_path(entry.entry_id, layout.root)
            restored = restore_path(entry.entry_id, layout.root, overwrite=True)
            self.assertEqual(restored.read_text(encoding="utf-8"), "original")
            # The displaced occupant is itself recoverable, not destroyed.
            remaining = list_trash(layout.root)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].original_path, str(target))
            occupant_restored = restore_path(
                remaining[0].entry_id, layout.root, overwrite=True
            )
            self.assertEqual(
                occupant_restored.read_text(encoding="utf-8"), "occupant"
            )

    def test_trash_refuses_structure_symlink_and_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(layout.root, layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(layout.deliverables_dir, layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(layout.trash_dir, layout.root)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("x", encoding="utf-8")
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(outside, layout.root)
            self.assertTrue(outside.exists())
            missing = layout.drafts_dir / "nope.txt"
            with self.assertRaises(FileNotFoundError):
                trash_path(missing, layout.root)

    def test_trash_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            real = write_text(layout.root, "draft", "real.txt", "real")
            link = layout.drafts_dir / "link.txt"
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with self.assertRaises(WorkspaceFileDisciplineError):
                trash_path(link, layout.root)
            self.assertTrue(link.is_symlink())
            self.assertTrue(real.exists())

    def test_trash_entry_metadata_survives_and_lists_original_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            target = write_text(layout.root, "internal", "watermark.json", "{}")
            entry = trash_path(target, layout.root)
            meta_path = layout.trash_dir / entry.entry_id / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["original_path"], str(target))
            self.assertEqual(meta["deleted_at"], entry.deleted_at)
            self.assertEqual(meta["kind"], "file")


class PurgeTests(unittest.TestCase):
    def test_purge_and_empty_trash_require_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            first = write_text(layout.root, "draft", "a.txt", "a")
            second = write_text(layout.root, "draft", "b.txt", "b")
            entry_a = trash_path(first, layout.root)
            trash_path(second, layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                purge_trashed(entry_a.entry_id, layout.root)
            self.assertEqual(len(list_trash(layout.root)), 2)
            with self.assertRaises(WorkspaceFileDisciplineError):
                empty_trash(layout.root)
            self.assertEqual(len(list_trash(layout.root)), 2)
            self.assertEqual(
                purge_trashed(entry_a.entry_id, layout.root, confirm=True),
                entry_a.entry_id,
            )
            self.assertEqual(len(list_trash(layout.root)), 1)
            remaining_id = list_trash(layout.root)[0].entry_id
            self.assertEqual(empty_trash(layout.root, confirm=True), [remaining_id])
            self.assertEqual(list_trash(layout.root), [])

    def test_restore_unknown_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            with self.assertRaises(FileNotFoundError):
                restore_path("20260101T000000-000000-missing", layout.root)
            with self.assertRaises(WorkspaceFileDisciplineError):
                restore_path("../escape", layout.root)


class BodyWiringTests(unittest.TestCase):
    def test_body_trash_restore_list_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            body = NativeBody()
            target = write_text(layout.root, "draft", "note.txt", "via body")
            trashed = body.act(
                "trash_path",
                path=str(target),
                workspace_root=str(layout.root),
            )
            self.assertTrue(trashed.success, trashed.error)
            self.assertFalse(target.exists())
            listed = body.act("list_trash", workspace_root=str(layout.root))
            self.assertTrue(listed.success, listed.error)
            self.assertEqual(listed.data["count"], 1)
            entry_id = listed.data["entries"][0]["entry_id"]
            self.assertEqual(
                listed.data["entries"][0]["original_path"], str(target)
            )
            restored = body.act(
                "restore_trashed",
                workspace_root=str(layout.root),
                entry_id=entry_id,
            )
            self.assertTrue(restored.success, restored.error)
            self.assertEqual(target.read_text(encoding="utf-8"), "via body")

    def test_body_trash_requires_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = _layout(Path(tmp))
            body = NativeBody()
            target = write_text(layout.root, "draft", "note.txt", "x")
            denied = body.act("trash_path", path=str(target))
            self.assertFalse(denied.success)
            self.assertTrue(target.exists())


class WorkerRunAuthorityTests(unittest.TestCase):
    def test_trash_is_not_admitted_for_worker_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = ActionAuthorityContext(
                work_thread_id="thread-1",
                work_item_id="item-1",
                worker_run_id="run-1",
                plan_version=1,
                executor_kind="worker",
                expected_action="write_file",
                tool_scope=("workspace.write",),
                authority_scope=("workspace_write",),
                workspace_root=tmp,
            )
            with self.assertRaises(WorkerActionAuthorityError):
                WorkerActionAuthorityEnforcer.authorize(
                    "trash_path",
                    {"path": str(Path(tmp) / "note.txt")},
                    context,
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.approval_review import (
    build_unified_diff,
    capture_file_review,
    undo_approved_change,
)
from zn_agent.core.body import NativeBody
from zn_agent.core.workspace_file_actions import (
    WORKSPACE_FILE_DELETE,
    WORKSPACE_FILE_OVERWRITE,
    WORKSPACE_FILE_WRITE,
    register_workspace_file_actions,
    register_workspace_file_verification,
)
from zn_agent.core.workspace_file_discipline import (
    WorkspaceLayout,
    list_trash,
)


def _runtime(root: Path, store: ApprovalCardStore) -> ActionExecutionRuntime:
    registry = ActionFabricRegistry()
    register_workspace_file_actions(
        registry, workspace_root=root, approval_available=True
    )
    runtime = ActionExecutionRuntime(
        registry, NativeBody(store=None), approval_gate=ApprovalGate(store)
    )
    register_workspace_file_verification(runtime, workspace_root=root)
    return runtime


class DiffBuilderTests(unittest.TestCase):
    def test_overwrite_diff_shows_removed_and_added_lines(self) -> None:
        diff, truncated = build_unified_diff(
            "line one\nline two\n", "line one\nline TWO\n", path_label="note.txt"
        )
        self.assertFalse(truncated)
        self.assertIn("-line two", diff)
        self.assertIn("+line TWO", diff)
        self.assertIn("note.txt", diff)

    def test_create_diff_marks_file_as_not_existing(self) -> None:
        diff, _ = build_unified_diff(None, "hello\n", path_label="new.txt")
        self.assertIn("(file did not exist)", diff)
        self.assertIn("+hello", diff)

    def test_delete_diff_marks_file_as_deleted(self) -> None:
        diff, _ = build_unified_diff("hello\n", None, path_label="old.txt")
        self.assertIn("(deleted)", diff)
        self.assertIn("-hello", diff)

    def test_identical_content_reports_no_changes(self) -> None:
        diff, _ = build_unified_diff("same\n", "same\n", path_label="same.txt")
        self.assertIn("no changes", diff)

    def test_oversized_diff_is_truncated_with_a_note(self) -> None:
        diff, truncated = build_unified_diff(
            "x\n" * 20000, "y\n", path_label="big.txt", max_chars=100
        )
        self.assertTrue(truncated)
        self.assertIn("truncated", diff)


class CaptureReviewTests(unittest.TestCase):
    def test_text_file_captures_diff_and_faithful_snapshot(self) -> None:
        review = capture_file_review(
            old_bytes=b"before\n",
            new_text="after\n",
            path_label="note.txt",
        )
        self.assertTrue(review["previous_captured"])
        self.assertEqual(review["previous_content"], "before\n")
        self.assertIn("-before", review["diff_text"])
        self.assertIn("+after", review["diff_text"])
        self.assertEqual(review["review_note"], "")

    def test_empty_file_snapshot_is_captured_not_confused_with_missing(self) -> None:
        review = capture_file_review(
            old_bytes=b"", new_text="fresh\n", path_label="empty.txt"
        )
        self.assertTrue(review["previous_captured"])
        self.assertEqual(review["previous_content"], "")

    def test_missing_file_has_no_snapshot(self) -> None:
        review = capture_file_review(
            old_bytes=None, new_text="fresh\n", path_label="new.txt"
        )
        self.assertFalse(review["previous_captured"])
        self.assertEqual(review["previous_content"], "")

    def test_binary_file_has_no_diff_and_no_snapshot(self) -> None:
        review = capture_file_review(
            old_bytes=b"\x00\xff\xfe binary",
            new_text="text\n",
            path_label="blob.bin",
        )
        self.assertFalse(review["previous_captured"])
        self.assertEqual(review["previous_content"], "")
        self.assertIn("binary", review["diff_text"])
        self.assertIn("binary", review["review_note"])

    def test_oversized_file_has_truncated_diff_but_no_snapshot(self) -> None:
        big = b"x\n" * 300000
        review = capture_file_review(
            old_bytes=big, new_text="small\n", path_label="big.txt"
        )
        self.assertFalse(review["previous_captured"])
        self.assertEqual(review["previous_content"], "")
        self.assertIn("undo cap", review["review_note"])
        # The diff still shows the file existed (not "did not exist").
        self.assertNotIn("(file did not exist)", review["diff_text"])
        self.assertIn("truncated", review["diff_text"])


class ApprovalReviewStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_request_round_trips_review_fields(self) -> None:
        request = self.store.request_approval(
            action_kind="production_change",
            target="workspace:your_files/note.txt",
            scope="workspace:your_files/note.txt",
            diff_text="--- a/note\n+++ b/note\n-before\n+after\n",
            previous_content="before\n",
            previous_captured=True,
            review_note="",
        )
        reread = self.store.get_request(request.request_id)
        assert reread is not None
        self.assertEqual(reread.diff_text, request.diff_text)
        self.assertEqual(reread.previous_content, "before\n")
        self.assertTrue(reread.previous_captured)
        self.assertFalse(reread.undone)

    def test_uncaptured_snapshot_is_never_stored(self) -> None:
        request = self.store.request_approval(
            action_kind="production_change",
            target="workspace:your_files/note.txt",
            scope="workspace:your_files/note.txt",
            previous_content="should not be stored",
            previous_captured=False,
        )
        reread = self.store.get_request(request.request_id)
        assert reread is not None
        self.assertEqual(reread.previous_content, "")

    def test_old_database_without_review_columns_is_migrated(self) -> None:
        db_path = str(Path(self._tmp.name) / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE approval_requests(
                request_id TEXT PRIMARY KEY,
                action_kind TEXT NOT NULL,
                target TEXT NOT NULL,
                scope TEXT NOT NULL,
                value_text TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                decided_at TEXT,
                decision TEXT,
                event_id TEXT,
                approved_command TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE approval_rules(
                rule_id TEXT PRIMARY KEY,
                action_kind TEXT NOT NULL,
                scope TEXT NOT NULL,
                effect TEXT NOT NULL,
                created_at TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                UNIQUE(action_kind, scope, effect)
            );
            CREATE TABLE approval_audit(
                audit_id TEXT PRIMARY KEY,
                request_id TEXT,
                decision TEXT NOT NULL,
                action_kind TEXT NOT NULL,
                scope TEXT NOT NULL,
                rule_id TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()
        legacy = ApprovalCardStore(db_path)
        request = legacy.request_approval(
            action_kind="delete",
            target="workspace:your_files/gone.txt",
            scope="workspace:your_files/gone.txt",
            diff_text="diff here",
            previous_content="old\n",
            previous_captured=True,
        )
        reread = legacy.get_request(request.request_id)
        assert reread is not None
        self.assertEqual(reread.diff_text, "diff here")
        self.assertTrue(reread.previous_captured)

    def test_gate_check_stores_review_on_the_created_request(self) -> None:
        gate = ApprovalGate(self.store)
        outcome = gate.check(
            action_kind="production_change",
            target="workspace:your_files/note.txt",
            scope="workspace:your_files/note.txt",
            value_text="preview",
            review={
                "diff_text": "diff",
                "previous_content": "old\n",
                "previous_captured": True,
                "review_note": "",
            },
        )
        self.assertFalse(outcome.allowed)
        assert outcome.request_id is not None
        stored = self.store.get_request(outcome.request_id)
        assert stored is not None
        self.assertEqual(stored.diff_text, "diff")
        self.assertEqual(stored.previous_content, "old\n")

    def test_mark_undone_runs_once_and_audits(self) -> None:
        request = self.store.request_approval(
            action_kind="production_change",
            target="workspace:your_files/note.txt",
            scope="workspace:your_files/note.txt",
        )
        self.store.decide(request.request_id, "allow_once")
        self.assertTrue(self.store.consume(request.request_id))
        self.assertTrue(self.store.mark_undone(request.request_id))
        self.assertFalse(self.store.mark_undone(request.request_id))
        decisions = [entry.decision for entry in self.store.list_audit(limit=10)]
        self.assertIn("undone", decisions)


class UndoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # Resolve like production: Windows CI temp dirs can be 8.3 short
        # paths while production stores resolved long paths.
        self.root = (Path(self._tmp.name) / "workspace").resolve(strict=False)
        WorkspaceLayout(self.root).ensure()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "approvals.db"))
        self.runtime = _runtime(self.root, self.store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _execute(self, action_id: str, args: dict) -> object:
        return self.runtime.execute(
            ActionRequest(action_id, dict(args), event_id="event-1")
        )

    def _approve_pending_overwrite(self, content: str) -> str:
        blocked = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": content},
        )
        assert not blocked.success, blocked.error
        pending = self.store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.store.decide(pending[0].request_id, "allow_once")
        allowed = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": content},
        )
        assert allowed.success, allowed.error
        consumed = self.store.consumed_requests()
        self.assertEqual(len(consumed), 1)
        return consumed[0].request_id

    def test_pending_overwrite_card_carries_diff_and_snapshot(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "before\n"},
        )
        blocked = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "after\n"},
        )
        self.assertFalse(blocked.success)
        pending = self.store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertIn("-before", pending[0].diff_text)
        self.assertIn("+after", pending[0].diff_text)
        self.assertTrue(pending[0].previous_captured)
        self.assertEqual(pending[0].previous_content, "before\n")

    def test_denied_overwrite_leaves_file_unchanged(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "before\n"},
        )
        self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "after\n"},
        )
        pending = self.store.pending_requests()
        self.store.decide(pending[0].request_id, "deny")
        retry = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "after\n"},
        )
        self.assertFalse(retry.success)
        self.assertEqual(
            (self.root / "your_files/note.txt").read_text(), "before\n"
        )

    def test_undo_overwrite_restores_previous_content(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "before\n"},
        )
        request_id = self._approve_pending_overwrite("after\n")
        self.assertEqual(
            (self.root / "your_files/note.txt").read_text(), "after\n"
        )
        result = undo_approved_change(self.store, request_id, workspace_root=self.root)
        self.assertTrue(result["restored"])
        self.assertEqual(
            (self.root / "your_files/note.txt").read_text(), "before\n"
        )
        # The replaced version is recoverable in trash, not destroyed.
        trashed = [
            entry
            for entry in list_trash(self.root)
            if entry.original_path.endswith("note.txt")
        ]
        self.assertEqual(len(trashed), 1)
        # Undo runs at most once.
        with self.assertRaises(ValueError):
            undo_approved_change(self.store, request_id, workspace_root=self.root)

    def test_undo_delete_restores_file(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/gone.txt", "content": "keep me\n"},
        )
        blocked = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertFalse(blocked.success)
        pending = self.store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertIn("-keep me", pending[0].diff_text)
        self.assertTrue(pending[0].previous_captured)
        self.store.decide(pending[0].request_id, "allow_once")
        allowed = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertTrue(allowed.success, allowed.error)
        self.assertFalse((self.root / "your_files/gone.txt").exists())
        consumed = self.store.consumed_requests()
        result = undo_approved_change(
            self.store, consumed[0].request_id, workspace_root=self.root
        )
        self.assertTrue(result["restored"])
        self.assertEqual(
            (self.root / "your_files/gone.txt").read_text(), "keep me\n"
        )

    def test_undo_refuses_pending_denied_and_non_workspace(self) -> None:
        request = self.store.request_approval(
            action_kind="production_change",
            target="workspace:your_files/note.txt",
            scope="workspace:your_files/note.txt",
            previous_content="old\n",
            previous_captured=True,
        )
        with self.assertRaises(ValueError):
            undo_approved_change(self.store, request.request_id, workspace_root=self.root)
        self.store.decide(request.request_id, "deny")
        with self.assertRaises(ValueError):
            undo_approved_change(self.store, request.request_id, workspace_root=self.root)
        other = self.store.request_approval(
            action_kind="send",
            target="someone@example.com",
            scope="email:someone",
            previous_content="old\n",
            previous_captured=True,
        )
        self.store.decide(other.request_id, "allow_once")
        self.assertTrue(self.store.consume(other.request_id))
        with self.assertRaises(ValueError):
            undo_approved_change(self.store, other.request_id, workspace_root=self.root)

    def test_undo_refuses_without_snapshot(self) -> None:
        request = self.store.request_approval(
            action_kind="production_change",
            target="workspace:your_files/blob.bin",
            scope="workspace:your_files/blob.bin",
            review_note="binary file: diff not shown, no undo snapshot was saved",
        )
        self.store.decide(request.request_id, "allow_once")
        self.assertTrue(self.store.consume(request.request_id))
        with self.assertRaises(ValueError) as ctx:
            undo_approved_change(self.store, request.request_id, workspace_root=self.root)
        self.assertIn("binary", str(ctx.exception))

    def test_undo_when_already_at_previous_state_rewrites_nothing(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "same\n"},
        )
        request_id = self._approve_pending_overwrite("same\n")
        result = undo_approved_change(self.store, request_id, workspace_root=self.root)
        self.assertFalse(result["restored"])
        self.assertEqual(
            (self.root / "your_files/note.txt").read_text(), "same\n"
        )
        self.assertEqual(list_trash(self.root), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
)
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.models import AgentEvent, ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import (
    build_resident_runtime_from_existing_stack,
)
from zn_agent.core.workspace_file_actions import (
    WORKSPACE_FILE_DELETE,
    WORKSPACE_FILE_OVERWRITE,
    WORKSPACE_FILE_READ,
    WORKSPACE_FILE_WRITE,
    register_workspace_file_actions,
    register_workspace_file_verification,
)
from zn_agent.core.workspace_file_discipline import WorkspaceLayout


class WorkspaceFileActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "workspace"
        WorkspaceLayout(self.root).ensure()
        self.approval_store = ApprovalCardStore(
            str(Path(self._tmp.name) / "approvals.db")
        )
        self.runtime = self._runtime(with_gate=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _runtime(self, *, with_gate: bool) -> ActionExecutionRuntime:
        registry = ActionFabricRegistry()
        register_workspace_file_actions(
            registry, workspace_root=self.root, approval_available=True
        )
        gate = ApprovalGate(self.approval_store) if with_gate else None
        runtime = ActionExecutionRuntime(
            registry, NativeBody(store=None), approval_gate=gate
        )
        register_workspace_file_verification(runtime, workspace_root=self.root)
        return runtime

    def _execute(self, action_id: str, args: dict) -> object:
        return self.runtime.execute(
            ActionRequest(action_id, dict(args), event_id="event-1")
        )

    def _file(self, rel: str) -> Path:
        return self.root / rel

    def test_write_creates_file_and_verifies_content(self) -> None:
        execution = self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "hello workspace"},
        )
        self.assertTrue(execution.success, execution.error)
        self.assertEqual(self._file("your_files/note.txt").read_text(), "hello workspace")
        self.assertEqual(
            execution.verification.evidence.get("observed_sha256"),
            execution.body_result.data.get("sha256"),
        )

    def test_write_refuses_existing_file(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "first"},
        )
        execution = self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "second"},
        )
        self.assertFalse(execution.success)
        self.assertIn("already exists", execution.error or "")
        self.assertEqual(self._file("your_files/note.txt").read_text(), "first")

    def test_read_returns_written_content(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "drafts/draft.md", "content": "draft body"},
        )
        execution = self._execute(
            WORKSPACE_FILE_READ, {"path": "drafts/draft.md"}
        )
        self.assertTrue(execution.success, execution.error)
        self.assertEqual(execution.body_result.output, "draft body")

    def test_overwrite_requires_approval_then_executes(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/note.txt", "content": "before"},
        )
        blocked = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "after"},
        )
        self.assertFalse(blocked.success)
        self.assertIn("approval_required", blocked.error or "")
        pending = self.approval_store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "production_change")
        self.assertEqual(pending[0].scope, "workspace:your_files/note.txt")

        # allow_once executes once and is consumed: the next attempt blocks.
        self.approval_store.decide(pending[0].request_id, "allow_once")
        allowed = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "after"},
        )
        self.assertTrue(allowed.success, allowed.error)
        self.assertEqual(self._file("your_files/note.txt").read_text(), "after")
        again = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/note.txt", "content": "third"},
        )
        self.assertFalse(again.success)
        self.assertIn("approval_required", again.error or "")

    def test_overwrite_deny_blocks_that_file(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/denied.txt", "content": "before"},
        )
        self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/denied.txt", "content": "after"},
        )
        request = self.approval_store.pending_requests()[0]
        self.approval_store.decide(request.request_id, "deny")
        # Deny is sticky for this file: re-attempts stay blocked, no new card.
        denied = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/denied.txt", "content": "after"},
        )
        self.assertFalse(denied.success)
        self.assertEqual(self.approval_store.pending_requests(), [])
        self.assertEqual(self._file("your_files/denied.txt").read_text(), "before")

    def test_overwrite_on_missing_file_fails_after_approval(self) -> None:
        # The gate runs before Body: the card comes first, then Body
        # refuses because there is no existing file to overwrite.
        blocked = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/missing.txt", "content": "x"},
        )
        self.assertFalse(blocked.success)
        self.assertIn("approval_required", blocked.error or "")
        request = self.approval_store.pending_requests()[0]
        self.approval_store.decide(request.request_id, "allow_once")
        execution = self._execute(
            WORKSPACE_FILE_OVERWRITE,
            {"path": "your_files/missing.txt", "content": "x"},
        )
        self.assertFalse(execution.success)
        self.assertIn("existing file", execution.error or "")

    def test_delete_requires_approval_deny_keeps_file(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/gone.txt", "content": "keep me"},
        )
        blocked = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertFalse(blocked.success)
        self.assertIn("approval_required", blocked.error or "")
        pending = self.approval_store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "delete")
        self.assertEqual(pending[0].scope, "workspace:your_files/gone.txt")

        self.approval_store.decide(pending[0].request_id, "deny")
        denied = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertFalse(denied.success)
        self.assertTrue(self._file("your_files/gone.txt").is_file())

    def test_delete_after_allow_once_moves_file_to_trash(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/gone.txt", "content": "trash me"},
        )
        self._execute(WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"})
        request = self.approval_store.pending_requests()[0]
        self.approval_store.decide(request.request_id, "allow_once")
        execution = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertTrue(execution.success, execution.error)
        self.assertFalse(self._file("your_files/gone.txt").exists())
        trash = WorkspaceLayout(self.root).list_trash()
        self.assertEqual(len(trash), 1)
        self.assertEqual(
            trash[0].original_path, str(self._file("your_files/gone.txt"))
        )
        # The deletion is recoverable: restore puts the file back.
        WorkspaceLayout(self.root).restore(trash[0].entry_id)
        self.assertEqual(
            self._file("your_files/gone.txt").read_text(), "trash me"
        )

    def test_delete_with_auto_allow_rule_executes_without_card(self) -> None:
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/gone.txt", "content": "x"},
        )
        self.approval_store.create_rule(
            action_kind="delete",
            scope="workspace:your_files/gone.txt",
            effect="auto_allow",
        )
        execution = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertTrue(execution.success, execution.error)
        self.assertEqual(self.approval_store.pending_requests(), [])
        self.assertFalse(self._file("your_files/gone.txt").exists())

    def test_broad_auto_allow_rule_does_not_bless_deletes(self) -> None:
        # An auto_allow rule on the bare action id must not bless deletes:
        # scopes are derived from the canonical file path, so only a
        # per-file rule can auto-allow.
        self.approval_store.create_rule(
            action_kind="delete",
            scope=WORKSPACE_FILE_DELETE,
            effect="auto_allow",
        )
        self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/gone.txt", "content": "x"},
        )
        execution = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/gone.txt"}
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        self.assertTrue(self._file("your_files/gone.txt").is_file())
        pending = self.approval_store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].scope, "workspace:your_files/gone.txt")

    def test_out_of_workspace_paths_rejected(self) -> None:
        outside = Path(self._tmp.name) / "outside.txt"
        for bad in (
            "../outside.txt",
            "your_files/../../outside.txt",
            "/etc/passwd",
            str(outside),
            "note.txt",
        ):
            execution = self._execute(
                WORKSPACE_FILE_WRITE, {"path": bad, "content": "evil"}
            )
            self.assertFalse(execution.success, bad)
        self.assertFalse(outside.exists())
        self.assertFalse((self.root / "note.txt").exists())

    def test_symlink_escape_rejected(self) -> None:
        outside_dir = Path(self._tmp.name) / "outside_dir"
        outside_dir.mkdir()
        link = self.root / "your_files" / "link"
        link.symlink_to(outside_dir, target_is_directory=True)
        execution = self._execute(
            WORKSPACE_FILE_WRITE,
            {"path": "your_files/link/evil.txt", "content": "evil"},
        )
        self.assertFalse(execution.success)
        self.assertFalse((outside_dir / "evil.txt").exists())

    def test_internal_and_trash_paths_refused(self) -> None:
        for bad in ("hidden_files/ledger.txt", ".trash/evil.txt"):
            execution = self._execute(
                WORKSPACE_FILE_WRITE, {"path": bad, "content": "evil"}
            )
            self.assertFalse(execution.success, bad)
            execution = self._execute(WORKSPACE_FILE_DELETE, {"path": bad})
            self.assertFalse(execution.success, bad)
        self.assertFalse((self.root / "hidden_files" / "ledger.txt").exists())

    def test_delete_refuses_directories(self) -> None:
        (self.root / "your_files" / "subdir").mkdir()
        self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/subdir"}
        )
        request = self.approval_store.pending_requests()[0]
        self.approval_store.decide(request.request_id, "allow_once")
        execution = self._execute(
            WORKSPACE_FILE_DELETE, {"path": "your_files/subdir"}
        )
        self.assertFalse(execution.success)
        self.assertIn("regular file", execution.error or "")
        self.assertTrue((self.root / "your_files" / "subdir").is_dir())

    def test_no_gate_means_no_blocking(self) -> None:
        # Documents the fail-open executor semantic when no gate is wired:
        # the product resident never runs this way -- it fail-closes by
        # not offering the actions when the approval store is missing.
        runtime = self._runtime(with_gate=False)
        runtime.execute(
            ActionRequest(
                WORKSPACE_FILE_WRITE,
                {"path": "your_files/gone.txt", "content": "x"},
                event_id="event-1",
            )
        )
        execution = runtime.execute(
            ActionRequest(
                WORKSPACE_FILE_DELETE,
                {"path": "your_files/gone.txt"},
                event_id="event-1",
            )
        )
        self.assertTrue(execution.success, execution.error)

    def test_fabric_offers_actions_and_fail_closes_without_approval(self) -> None:
        registry = ActionFabricRegistry()
        register_workspace_file_actions(
            registry, workspace_root=self.root, approval_available=True
        )
        for action_id in (
            WORKSPACE_FILE_READ,
            WORKSPACE_FILE_WRITE,
            WORKSPACE_FILE_OVERWRITE,
            WORKSPACE_FILE_DELETE,
        ):
            self.assertIsNotNone(registry.descriptor(action_id))
            self.assertTrue(registry.availability(action_id).available)

        gated_registry = ActionFabricRegistry()
        register_workspace_file_actions(
            gated_registry, workspace_root=self.root, approval_available=False
        )
        for action_id in (
            WORKSPACE_FILE_READ,
            WORKSPACE_FILE_WRITE,
            WORKSPACE_FILE_OVERWRITE,
            WORKSPACE_FILE_DELETE,
        ):
            self.assertFalse(gated_registry.availability(action_id).available)


class WorkspaceFileLoopTests(unittest.TestCase):
    """The generic action loop offers and executes a workspace file write."""

    def test_loop_write_executes_and_completes_on_verified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            WorkspaceLayout(root).ensure()
            approval_store = ApprovalCardStore(str(Path(tmp) / "approvals.db"))
            fabric = ActionFabricRegistry()
            register_workspace_file_actions(
                fabric, workspace_root=root, approval_available=True
            )
            executor = ActionExecutionRuntime(
                fabric,
                NativeBody(store=None),
                approval_gate=ApprovalGate(approval_store),
            )
            register_workspace_file_verification(executor, workspace_root=root)

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.action_fabric = fabric
            resident.action_executor = executor
            resident._accept_generic_action_increment = (
                lambda event, state, increment: 1
            )
            try:
                event = AgentEvent(
                    event_id="evt-workspace-write",
                    task="write hello into a file",
                    kind="desktop_user_event",
                )
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="impasse-test",
                    source="external:test",
                    question=event.task,
                    content=(
                        '{"zn_action_proposal":{"action_id":"workspace.file.write",'
                        '"arguments":{"path":"your_files/hello.txt",'
                        '"content":"hello from the loop"}}}'
                    ),
                    quality=1.0,
                    confidence=1.0,
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="cognition_integration",
                    data={
                        "cognition_request": {
                            "context": {"generic_action_loop": {"version": 1}},
                        },
                        "cognitive_increment": increment.to_dict(),
                        "external_cognition_result": {"model_invocations": 1},
                    },
                )
                resident.store.save_working_state(state)
                admitted = resident._cognition_integration_step(
                    event, state, readiness=SimpleNamespace()
                )
                self.assertIsNone(admitted)
                self.assertEqual(state.stage, resident._GENERIC_ACTION_STAGE)
                executed = resident._generic_action_step(event, state)
                self.assertIsNone(executed)
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(len(loop["history"]), 1)
                self.assertTrue(loop["history"][0]["verified"])
                self.assertEqual(
                    (root / "your_files" / "hello.txt").read_text(),
                    "hello from the loop",
                )
                evidence_id = loop["history"][0]["execution_id"]

                completion = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="impasse-test",
                    source="external:test",
                    question=event.task,
                    content=(
                        '{"zn_action_completion":{"execution_ids":["'
                        + evidence_id
                        + '"],"response":"file written"}}'
                    ),
                    quality=1.0,
                    confidence=1.0,
                )
                state.stage = "cognition_integration"
                state.data["cognition_request"] = {
                    "context": {"generic_action_loop": {"version": 1}},
                }
                state.data["cognitive_increment"] = completion.to_dict()
                state.data["external_cognition_result"] = {"model_invocations": 1}
                completed = resident._cognition_integration_step(
                    event, state, readiness=SimpleNamespace()
                )
                self.assertIsNotNone(completed)
                self.assertTrue(completed.success)
                self.assertIs(completed.execution_path, ExecutionPath.BODY)
            finally:
                resident.store.close()

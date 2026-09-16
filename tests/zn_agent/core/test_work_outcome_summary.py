from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.models import ExecutionPath, ResidentRunResult
from zn_agent.core.outcome_aware_work_control import OutcomeAwareRestoreWorkControl
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_outcome_summary import (
    project_work_outcome,
    public_work_text,
    render_work_outcome_summary,
)


class _FakeLedger:
    def __init__(self, *, root, run, children, version=1):
        self.root = root
        self.run = run
        self.children = list(children)
        self.version = version

    def work_item_for_event(self, _event_id):
        return self.root

    def get_run(self, _event_id):
        return self.run

    def plan_version(self, _thread_id):
        return self.version

    def list_work_items(self, _thread_id, *, limit=256):
        return [self.root, *self.children][:limit]


class WorkOutcomeProjectionTests(unittest.TestCase):
    def test_partial_projection_is_current_plan_bounded_and_redacted(self) -> None:
        root = SimpleNamespace(
            work_item_id="root",
            work_thread_id="thread",
            parent_work_item_id=None,
            title="Root",
            status="blocked",
            plan_version=2,
            acceptance_criteria=["all required steps verified"],
            blocker="password=hunter2 final verification failed",
            updated_at="2026-09-16T12:00:03+00:00",
        )
        completed = SimpleNamespace(
            work_item_id="done",
            work_thread_id="thread",
            parent_work_item_id="root",
            title="Prepared local result",
            status="completed",
            plan_version=2,
            acceptance_criteria=["file exists", "content verified"],
            blocker=None,
            completed_at="2026-09-16T12:00:01+00:00",
            updated_at="2026-09-16T12:00:01+00:00",
        )
        blocked = SimpleNamespace(
            work_item_id="blocked",
            work_thread_id="thread",
            parent_work_item_id="root",
            title="Publish result",
            status="blocked",
            plan_version=2,
            acceptance_criteria=["remote confirmation"],
            blocker="authorization=sk-abcdefghijklmnop remote denied request",
            completed_at=None,
            updated_at="2026-09-16T12:00:02+00:00",
        )
        stale = SimpleNamespace(
            work_item_id="stale",
            work_thread_id="thread",
            parent_work_item_id="root",
            title="Old plan result",
            status="completed",
            plan_version=1,
            acceptance_criteria=["must not appear"],
            blocker=None,
            completed_at="2026-09-16T11:00:00+00:00",
            updated_at="2026-09-16T11:00:00+00:00",
        )
        ledger = _FakeLedger(
            root=root,
            run=SimpleNamespace(thread_id="thread", ledger_state="finalized"),
            children=[completed, blocked, stale],
            version=2,
        )

        projection = project_work_outcome(ledger, "evt")
        assert projection is not None
        self.assertEqual(projection["status"], "partial")
        self.assertEqual(projection["reason"], "PartiallyCompleted")
        self.assertEqual(projection["counts"], {"completed": 1, "blocked": 1, "active": 0})
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertIn("Prepared local result", encoded)
        self.assertIn("Publish result", encoded)
        self.assertNotIn("Old plan result", encoded)
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("sk-abcdefghijklmnop", encoded)
        self.assertIn("<redacted>", encoded)

        summary = render_work_outcome_summary(projection)
        assert summary is not None
        self.assertIn("Partially completed.", summary)
        self.assertIn("Completed:", summary)
        self.assertIn("Blocked:", summary)
        self.assertNotIn("hunter2", summary)
        self.assertNotIn("sk-abcdefghijklmnop", summary)

    def test_stale_plan_never_receives_a_fresh_outcome(self) -> None:
        root = SimpleNamespace(
            work_item_id="root",
            work_thread_id="thread",
            parent_work_item_id=None,
            status="blocked",
            plan_version=1,
        )
        ledger = _FakeLedger(
            root=root,
            run=SimpleNamespace(thread_id="thread", ledger_state="stale_finalized"),
            children=[],
            version=2,
        )
        self.assertIsNone(project_work_outcome(ledger, "evt"))

    def test_completed_projection_does_not_replace_success_text(self) -> None:
        root = SimpleNamespace(
            work_item_id="root",
            work_thread_id="thread",
            parent_work_item_id=None,
            title="Root",
            status="completed",
            plan_version=1,
            acceptance_criteria=[],
            blocker=None,
            updated_at="2026-09-16T12:00:00+00:00",
        )
        ledger = _FakeLedger(
            root=root,
            run=SimpleNamespace(thread_id="thread", ledger_state="finalized"),
            children=[],
            version=1,
        )
        projection = project_work_outcome(ledger, "evt")
        assert projection is not None
        self.assertEqual(projection["status"], "completed")
        self.assertIsNone(render_work_outcome_summary(projection))

    def test_public_text_redacts_common_secret_shapes(self) -> None:
        rendered = public_work_text(
            "api_key=sk-abcdefghijklmnop token eyJabcdefghijklmnop.qwertyuiop.asdfghjkl"
        )
        self.assertNotIn("sk-abcdefghijklmnop", rendered)
        self.assertNotIn("eyJabcdefghijklmnop", rendered)
        self.assertIn("<redacted>", rendered)


class OutcomeAwareControlIntegrationTests(unittest.TestCase):
    def test_finalized_partial_work_rewrites_existing_zn_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            control = OutcomeAwareRestoreWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            try:
                ledger.create_thread(thread_id="partial", title="Partial")
                _, event = ledger.start(
                    "partial",
                    "Prepare locally and publish remotely",
                    acceptance_criteria=["local and remote results verified"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Prepare the local result",
                    title="Prepare local result",
                    acceptance_criteria=["local artifact exists"],
                )
                ledger.complete_child_item(child.work_item_id, result="local artifact verified")
                ledger._finalize_run(
                    event.event_id,
                    run=ResidentRunResult(
                        event=event,
                        execution_path=ExecutionPath.CONTROL,
                        success=False,
                        reason="password=hunter2 remote publish blocked",
                    ),
                )

                _thread, messages = control.get_snapshot("partial")
                zn = [message for message in messages if message.role == "zn"][-1]
                self.assertIn("Partially completed.", zn.text)
                self.assertIn("Prepare local result", zn.text)
                self.assertIn("Final acceptance: blocked", zn.text)
                self.assertNotIn("hunter2", zn.text)
                self.assertEqual(zn.detail["work_outcome"]["status"], "partial")
                self.assertTrue(zn.detail["partial"])
                self.assertFalse(zn.detail["blocked"])
            finally:
                resident.store.close()

    def test_restart_rebuilds_terminal_summary_from_durable_work_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime(config={"model": {}}, store_path=db)
            first_control = OutcomeAwareRestoreWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = first_control.ledger
            ledger.create_thread(thread_id="restart-partial", title="Restart partial")
            _, event = ledger.start(
                "restart-partial",
                "Complete one step then hit a bounded blocker",
                acceptance_criteria=["all steps verified"],
            )
            root = ledger.work_item_for_event(event.event_id)
            assert root is not None
            child = ledger.create_child_item(
                root_work_item_id=root.work_item_id,
                objective="Finish the durable first step",
                title="Durable first step",
                acceptance_criteria=["first step retained"],
            )
            ledger.complete_child_item(child.work_item_id, result="done")
            ledger._finalize_run(
                event.event_id,
                run=ResidentRunResult(
                    event=event,
                    execution_path=ExecutionPath.CONTROL,
                    success=False,
                    reason="remote approval unavailable",
                ),
            )
            # Deliberately do not call first_control.progress/get_snapshot: the
            # next process must rebuild the presentation from durable Work truth.
            first.store.close()

            restored = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                restored_control = OutcomeAwareRestoreWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                _thread, messages = restored_control.get_snapshot("restart-partial")
                zn = [message for message in messages if message.role == "zn"][-1]
                self.assertIn("Partially completed.", zn.text)
                self.assertIn("Durable first step", zn.text)
                self.assertIn("remote approval unavailable", zn.text)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()

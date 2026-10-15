from __future__ import annotations

"""LG-1: two-phase writes + "checkpoint not older than parent chain".

Known pit (found by the smoke P1 worker, not fixed there):
overwrite-recovery, when a TEAM event is interrupted at a pulse boundary,
returned a terminal success straight from ``_side_effect_recovery_step`` --
the verified overwrite effect completed the whole event, bypassing the
team claim / runner-verify gates (no evidence on the WorkerRun, no claim,
no fresh-observation verification), because the completion never went
through the checkpointed ``_complete_successful_body_action`` path.

Fix shape (LangGraph invariant, ZN-owned machinery -- no Pregel runtime):

- Phase 1 (event write): the recovery step records the claim/verify
  outcome (verified effect + evidence action id) and persists it inside
  the state checkpoint (``native_completion``) via
  ``_complete_successful_body_action``.
- Phase 2 (terminal outcome): only the caller publishes the EventOutcome
  (``complete_event``). A crash between the two phases restarts at
  ``native_completion`` and rebuilds the same result -- no re-run, no
  re-verification, no replay.
- Team / rolling interceptors consume the phase-1 checkpoint (evidence
  recorded, event kept alive) so claim/verify still run.
- Team checkpoints form a parent chain: ``save`` rejects a checkpoint
  older than the stored latest pulse, and a child whose parent is
  unknown (broken chain). Completion state is rebuilt from the latest
  checkpoint + the durable ledger, never from a stale checkpoint alone.
"""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.team_runner import (
    Checkpoint,
    InMemoryCheckpointStorage,
)
from zn_agent.core.team_work_owner import EVIDENCE_KEY
from zn_agent.core.team_work_resident import TeamWorkResidentRuntime


class _Base(unittest.TestCase):
    @staticmethod
    def _attempts(store_path: Path, event_id: str):
        with closing(sqlite3.connect(store_path)) as conn:
            return conn.execute(
                "SELECT attempt_id,status,result_action_id,result_success "
                "FROM resident_side_effect_attempts WHERE event_id=? "
                "ORDER BY started_at ASC",
                (event_id,),
            ).fetchall()

    @staticmethod
    def _write_text_actions(resident, event_id: str):
        return [
            item
            for item in resident.body.recent_actions(100)
            if item.event_id == event_id and item.kind == "write_text"
        ]

    @staticmethod
    def _crash_after_real_write(resident):
        original = resident.body._write_text

        def write_then_crash(action, started):
            original(action, started)
            raise SystemExit(
                "simulate process death after overwrite reached filesystem"
            )

        resident.body._write_text = write_then_crash

    def _make_team_run(self, resident, *, thread_id: str):
        """One Root + child + live WorkerRun in the resident's ledger."""
        ledger = resident.work_ledger
        ledger.create_thread(thread_id=thread_id, title="LG-1 team")
        root = WorkItem(
            work_item_id="root-lg1",
            work_thread_id=thread_id,
            parent_work_item_id=None,
            title="LG-1 team root",
            objective="LG-1 team root objective",
            status="running",
            plan_version=ledger.plan_version(thread_id),
            acceptance_criteria=["team done"],
        )
        ledger._save_item(root)
        child = ledger.create_child_item(
            root_work_item_id="root-lg1",
            objective="write the team note",
            title="team note",
            acceptance_criteria=["text_equals: note.md"],
        )
        run = ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="team-specialist",
            tool_scope=("terminal",),
            authority_scope=(f"work:{thread_id}",),
        )
        return root, child, run

    def _seed_overwrite_event(
        self,
        resident,
        target: Path,
        content: str,
        *,
        team_step: dict | None,
    ):
        """Seed a native_action state and crash after the real write."""
        event = resident.enqueue(
            "replace the file with the requested exact text",
            payload={"required_capabilities": ["filesystem"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        assert claimed is not None
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": str(target),
                "content": content,
                "append": False,
                "create_parents": True,
            },
            source=(
                "resident_team_specialist_choice"
                if team_step is not None
                else "native_deliberation"
            ),
        )
        data: dict = {"native_action_intent": intent.to_dict()}
        if team_step is not None:
            data[TeamWorkResidentRuntime._TEAM_STEP_KEY] = dict(team_step)
            data["team_id"] = "team-lg1"
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_action",
            next_action="move body: write_text",
            data=data,
        )
        resident.store.save_working_state(state)
        return event, state

    def _drive_to_recovery(self, store_path: Path, target: Path, content: str, *,
                           team_step: dict | None):
        """Phase 1: real write + crash. Restart: enter side_effect_recovery."""
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=store_path,
        )
        run_id = None
        try:
            if team_step is not None:
                _, _, run = self._make_team_run(
                    resident, thread_id="thread-lg1"
                )
                run_id = run.worker_run_id
                team_step = {**team_step, "run_id": run_id}
            event, state = self._seed_overwrite_event(
                resident, target, content, team_step=team_step
            )
            self._crash_after_real_write(resident)
            try:
                with self.assertRaises(SystemExit):
                    resident._native_action_step(event, state, readiness=None)
            finally:
                resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                restored_event = restored.store.get_event(event.event_id)
                assert restored_event is not None
                restored_state = restored.store.get_working_state()
                self.assertIsNone(
                    restored._native_action_step(
                        restored_event,
                        restored_state,
                        readiness=None,
                    )
                )
                recovery_state = restored.store.get_working_state()
                self.assertEqual(recovery_state.stage, "side_effect_recovery")
                return restored, restored_event, recovery_state, run_id
            except Exception:
                restored.store.close()
                raise
        except Exception:
            resident.store.close()
            raise


class LG1TeamRecoveryTests(_Base):
    def test_team_step_recovery_does_not_complete_event(self):
        """Pulse-boundary interrupt: the team event must stay alive.

        The verified overwrite effect is recorded as team evidence and the
        event continues to claim/verify -- it is NOT terminally completed
        by the recovery path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "note.md"
            target.write_text("old", encoding="utf-8")
            intended = "team note exact state"

            restored, event, recovery_state, run_id = self._drive_to_recovery(
                store_path,
                target,
                intended,
                team_step={
                    "run_id": "",
                    "work_item_id": "",
                    "objective": "write the team note",
                    "relative_path": "note.md",
                    "action_kind": "write_text",
                    "increment_id": "inc-lg1",
                },
            )
            try:
                assert run_id is not None
                result = restored._side_effect_recovery_step(
                    event,
                    recovery_state,
                    readiness=None,
                )
                # LG-1: no terminal success from the recovery path. The
                # event stays alive so claim + runner verify still run.
                self.assertIsNone(result)
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                persisted = restored.store.get_working_state()
                self.assertEqual(persisted.stage, "native_deliberation")
                self.assertNotIn(
                    TeamWorkResidentRuntime._TEAM_STEP_KEY, persisted.data
                )

                run = restored.work_ledger.worker_run(run_id)
                assert run is not None
                self.assertFalse(run.claimed_completion)
                evidence = [
                    entry
                    for entry in run.metrics.get(EVIDENCE_KEY, [])
                    if isinstance(entry, dict)
                    and entry.get("kind") == "verified_body_step"
                ]
                self.assertEqual(len(evidence), 1)
                self.assertEqual(
                    evidence[0].get("objective"), "write the team note"
                )
                self.assertTrue(evidence[0].get("verified"))

                # The child item is NOT completed by recovery: only the
                # runner's verify + complete may do that, after a claim.
                child = next(
                    item
                    for item in restored.work_ledger.list_work_items("thread-lg1")
                    if item.parent_work_item_id == "root-lg1"
                )
                self.assertEqual(child.status, "running")

                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "verified_effect")
                self.assertEqual(self._write_text_actions(restored, event.event_id), [])
                self.assertEqual(target.read_text(encoding="utf-8"), intended)
            finally:
                restored.store.close()

    def test_team_resume_from_native_completion_checkpoint_records_evidence(self):
        """Crash between the phase-1 checkpoint and the interceptor save.

        Restart sees stage=native_completion + the team step key and
        rebuilds the completion from the checkpoint: evidence recorded,
        no re-verification, no replay.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "note.md"
            target.write_text("old", encoding="utf-8")
            intended = "team note exact state"

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                _, child, run = self._make_team_run(
                    resident, thread_id="thread-lg1"
                )
                event = resident.enqueue(
                    "replace the file with the requested exact text",
                    payload={"required_capabilities": ["filesystem"]},
                )
                claimed = resident.store.claim_event(event.event_id)
                assert claimed is not None
                intent = NativeActionIntent(
                    intent_id=f"intent-{event.event_id}",
                    event_id=event.event_id,
                    kind="write_text",
                    args={
                        "path": str(target),
                        "content": intended,
                        "append": False,
                        "create_parents": True,
                    },
                    source="resident_team_specialist_choice",
                )
                # Mid-window persisted state: phase-1 checkpoint is durable,
                # the interceptor's save never happened (simulated crash).
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_completion",
                    next_action="publish terminal EventOutcome",
                    data={
                        "native_action_intent": intent.to_dict(),
                        "native_completion": {
                            "execution_path": "body",
                            "success": True,
                            "response": str(target),
                            "model_invocations": 0,
                            "reason": (
                                "ZN independently observed the exact requested "
                                "overwrite state after interruption and completed "
                                "without replaying the stale mutation"
                            ),
                        },
                        TeamWorkResidentRuntime._TEAM_STEP_KEY: {
                            "run_id": run.worker_run_id,
                            "work_item_id": child.work_item_id,
                            "objective": "write the team note",
                            "relative_path": "note.md",
                            "action_kind": "write_text",
                            "increment_id": "inc-lg1",
                        },
                        "team_id": "team-lg1",
                        "side_effect_recovery": {
                            "status": "verified_effect",
                            "decision": "complete_without_replay",
                            "replay_blocked": False,
                            "intent_id": intent.intent_id,
                            "attempt_id": "attempt-lg1",
                        },
                    },
                )
                resident.store.save_working_state(state)

                result = resident._resume_native_completion(event, state)
                self.assertIsNone(result)
                persisted = resident.store.get_working_state()
                self.assertEqual(persisted.stage, "native_deliberation")
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))

                refreshed = resident.work_ledger.worker_run(run.worker_run_id)
                assert refreshed is not None
                evidence = [
                    entry
                    for entry in refreshed.metrics.get(EVIDENCE_KEY, [])
                    if isinstance(entry, dict)
                    and entry.get("kind") == "verified_body_step"
                ]
                self.assertEqual(len(evidence), 1)
                self.assertEqual(self._write_text_actions(resident, event.event_id), [])
            finally:
                resident.store.close()


class LG1TwoPhasePlainEventTests(_Base):
    def test_recovery_persists_completion_checkpoint_before_outcome(self):
        """Phase 1 checkpoint exists before any terminal outcome is published."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            intended = "new exact state"

            restored, event, recovery_state, _ = self._drive_to_recovery(
                store_path, target, intended, team_step=None
            )
            try:
                result = restored._side_effect_recovery_step(
                    event,
                    recovery_state,
                    readiness=None,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertIn("without replaying", result.reason)

                # Two-phase proof: the completion checkpoint is durable
                # BEFORE complete_event publishes the outcome (not called
                # here -- this is the crash window).
                persisted = restored.store.get_working_state()
                self.assertEqual(persisted.stage, "native_completion")
                completion = persisted.data.get("native_completion")
                self.assertIsInstance(completion, dict)
                self.assertIs(completion.get("success"), True)
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))

                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "verified_effect")
            finally:
                restored.store.close()

    def test_resume_native_completion_rebuilds_without_rerun(self):
        """Crash after phase 1, before outcome: resume replays, never re-runs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            intended = "new exact state"

            restored, event, recovery_state, _ = self._drive_to_recovery(
                store_path, target, intended, team_step=None
            )
            try:
                first = restored._side_effect_recovery_step(
                    event,
                    recovery_state,
                    readiness=None,
                )
                self.assertIsNotNone(first)
                assert first is not None
                self.assertTrue(first.success)
            finally:
                restored.store.close()

            # Restart without ever publishing the outcome: the checkpoint
            # rebuilds the same completion, no second verification, no replay.
            restarted = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                restarted_event = restarted.store.get_event(event.event_id)
                assert restarted_event is not None
                state = restarted.store.get_working_state()
                self.assertEqual(state.stage, "native_completion")
                rebuilt = restarted._resume_native_completion(
                    restarted_event, state
                )
                self.assertIsNotNone(rebuilt)
                assert rebuilt is not None
                self.assertTrue(rebuilt.success)
                self.assertEqual(rebuilt.response, first.response)
                self.assertEqual(
                    self._write_text_actions(restarted, event.event_id), []
                )
                attempts = self._attempts(store_path, event.event_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0][1], "verified_effect")
                self.assertEqual(target.read_text(encoding="utf-8"), intended)
            finally:
                restarted.store.close()


class LG1CheckpointChainTests(unittest.TestCase):
    def test_save_rejects_checkpoint_older_than_latest(self):
        storage = InMemoryCheckpointStorage()
        storage.save(Checkpoint(checkpoint_id="tx:pulse-2", team_id="tx", pulse=2))
        with self.assertRaises(ValueError):
            storage.save(
                Checkpoint(checkpoint_id="tx:pulse-1", team_id="tx", pulse=1)
            )
        # Same-pulse re-save (retry) and newer saves are fine.
        storage.save(
            Checkpoint(
                checkpoint_id="tx:pulse-2",
                team_id="tx",
                pulse=2,
                completed_step_ids=("a",),
            )
        )
        storage.save(
            Checkpoint(
                checkpoint_id="tx:pulse-3",
                team_id="tx",
                pulse=3,
                parent_checkpoint_id="tx:pulse-2",
                completed_step_ids=("a",),
            )
        )
        self.assertEqual(
            storage.latest(team_id="tx").checkpoint_id, "tx:pulse-3"
        )

    def test_save_rejects_unknown_parent(self):
        storage = InMemoryCheckpointStorage()
        with self.assertRaises(ValueError):
            storage.save(
                Checkpoint(
                    checkpoint_id="tx:pulse-1",
                    team_id="tx",
                    pulse=1,
                    parent_checkpoint_id="tx:pulse-0",
                )
            )
        with self.assertRaises(ValueError):
            storage.save(
                Checkpoint(
                    checkpoint_id="tx:pulse-1",
                    team_id="tx",
                    pulse=1,
                    parent_checkpoint_id="tx:pulse-1",
                )
            )

    def test_checkpoint_parent_round_trip(self):
        checkpoint = Checkpoint(
            checkpoint_id="tx:pulse-2",
            team_id="tx",
            pulse=2,
            parent_checkpoint_id="tx:pulse-1",
            completed_step_ids=("a",),
            pending_step_ids=("b",),
        )
        restored = Checkpoint.from_dict(checkpoint.to_dict())
        self.assertEqual(restored, checkpoint)
        # Old dicts without the parent field still load (genesis).
        legacy = Checkpoint.from_dict(
            {
                "checkpoint_id": "tx:pulse-1",
                "team_id": "tx",
                "pulse": 1,
            }
        )
        self.assertEqual(legacy.parent_checkpoint_id, "")


if __name__ == "__main__":
    unittest.main()

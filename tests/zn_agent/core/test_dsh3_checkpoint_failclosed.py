"""DSH-3: checkpoint fail-closed + interrupted tool calls are unknown.

(a) A checkpoint write/read failure is an explicit error: the pulse was
    NOT durably recorded, and recovery must not proceed as if it were.
    ``save_checkpoint`` / ``save_interrupt_checkpoint`` raise
    CheckpointSaveError; ``latest_checkpoint`` / ``pending_step_ids``
    raise CheckpointLoadError on a load failure (never "no checkpoint").
(b) An interrupted pulse leaves its in-flight tool calls with UNKNOWN
    outcomes: the recovery pulse marks those steps uncertain
    (``outcome_uncertain`` on the live run + ``uncertain_step_ids`` on
    the checkpoint) and never re-dispatches them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    Checkpoint,
    CheckpointLoadError,
    CheckpointSaveError,
    InMemoryCheckpointStorage,
    TeamRunner,
    VerificationOutcome,
)
from zn_agent.core.team_termination import (
    load_termination_state,
    save_termination_state,
)
from zn_agent.core.team_work_owner import TeamWorkOwner


class StubVerifier:
    def __init__(self, passed: bool = True):
        self.passed = passed

    def verify(self, *, item, run):
        return VerificationOutcome(
            passed=self.passed, notes="stub checked the artifacts"
        )


class FailingSaveStorage(InMemoryCheckpointStorage):
    def save(self, checkpoint: Checkpoint) -> None:
        raise OSError("disk full (simulated)")


class FailingLoadStorage(InMemoryCheckpointStorage):
    def latest(self, *, team_id: str) -> Checkpoint | None:
        raise OSError("read failed (simulated)")


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-dsh3-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-dsh3"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        self.ledger._save_item(
            WorkItem(
                work_item_id="root-1",
                work_thread_id=self.thread_id,
                title="XX 项目",
                objective="把 XX 项目做完",
                status="running",
                plan_version=1,
            )
        )
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id=self.thread_id,
        )
        self.plan_ids = [item.item_id for item in self.team.plan]
        self.verifier = StubVerifier()
        self.storage = InMemoryCheckpointStorage()
        self.runner = self._new_runner(self.storage)

    def tearDown(self):
        self.store.close()

    def _new_runner(self, storage):
        return TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=self.verifier,
            root_work_item_id="root-1",
            checkpoint_storage=storage,
        )

    def _wid(self, plan_item_id: str) -> str:
        shared = team_shared_memory(self.memory, "tx")
        return shared.recall("plan_item_map").value[plan_item_id]

    def _runs(self, wid: str):
        return self.ledger.list_worker_runs(work_item_id=wid, limit=50)

    def _bump_termination_pulses(self, pulses: int) -> None:
        """Simulate a pulse that started (state saved) but crashed before
        its end-of-pulse checkpoint saved."""
        shared = team_shared_memory(self.memory, "tx")
        state = load_termination_state(shared)
        state.pulses = pulses
        save_termination_state(shared, state)

    def _claim(self, work_item_id: str, summary: str = "做完了"):
        runs = self._runs(work_item_id)
        self.assertTrue(runs, f"no run for {work_item_id}")
        run = runs[-1]
        self.ledger.complete_worker_run(
            run.worker_run_id,
            result_summary=summary,
            claimed_completion=True,
            verification_status="pending",
        )


class FailClosedTests(_Fixture):
    def test_save_failure_raises_instead_of_silent_none(self):
        runner = self._new_runner(FailingSaveStorage())
        with self.assertRaises(CheckpointSaveError):
            runner.save_checkpoint()

    def test_step_propagates_checkpoint_save_failure(self):
        runner = self._new_runner(FailingSaveStorage())
        with self.assertRaises(CheckpointSaveError):
            runner.step()

    def test_load_failure_raises_instead_of_fake_no_checkpoint(self):
        runner = self._new_runner(FailingLoadStorage())
        with self.assertRaises(CheckpointLoadError):
            runner.latest_checkpoint()
        with self.assertRaises(CheckpointLoadError):
            runner.pending_step_ids()

    def test_no_storage_still_means_no_checkpoint(self):
        runner = self._new_runner(None)
        self.assertIsNone(runner.save_checkpoint())
        self.assertIsNone(runner.latest_checkpoint())
        self.assertFalse(runner.interrupted_pulse_detected())

    def test_owner_save_interrupt_checkpoint_failure_raises(self):
        owner = TeamWorkOwner(
            ledger=self.ledger,
            memory=self.memory,
            checkpoint_storage=FailingSaveStorage(),
        )
        with self.assertRaises(CheckpointSaveError):
            owner.save_interrupt_checkpoint(
                team=self.team, root_work_item_id="root-1"
            )

    def test_owner_no_storage_save_interrupt_checkpoint_is_none(self):
        owner = TeamWorkOwner(
            ledger=self.ledger, memory=self.memory, checkpoint_storage=None
        )
        self.assertIsNone(
            owner.save_interrupt_checkpoint(
                team=self.team, root_work_item_id="root-1"
            )
        )

    def test_owner_load_failure_raises(self):
        owner = TeamWorkOwner(
            ledger=self.ledger,
            memory=self.memory,
            checkpoint_storage=FailingLoadStorage(),
        )
        with self.assertRaises(CheckpointLoadError):
            owner.latest_checkpoint("tx")


class UncertainStepTests(_Fixture):
    def test_clean_pulse_marks_nothing_uncertain(self):
        self.runner.step()  # dispatch item 1, checkpoint pulse 1 saved
        fresh = self._new_runner(self.storage)
        result = fresh.step()
        self.assertEqual(result.uncertain_step_ids, [])
        checkpoint = self.storage.latest(team_id="tx")
        assert checkpoint is not None
        self.assertEqual(list(checkpoint.uncertain_step_ids), [])

    def test_interrupted_pulse_marks_live_run_uncertain_no_redispatch(self):
        self.runner.step()  # dispatch item 1, checkpoint pulse 1 saved
        wid1 = self._wid(self.plan_ids[0])
        self.assertEqual(len(self._runs(wid1)), 1)

        # Crash window: pulse 2 started (termination state saved) but
        # its end-of-pulse checkpoint never saved.
        self._bump_termination_pulses(2)

        # Restart: a fresh runner on the same durable ledger + storage.
        resumed = self._new_runner(self.storage)
        self.assertTrue(resumed.interrupted_pulse_detected())
        result = resumed.step()

        # Unknown outcome, explicitly marked -- not retried.
        self.assertEqual(result.uncertain_step_ids, [self.plan_ids[0]])
        self.assertIn(f"uncertain:{self.plan_ids[0]}", result.actions)
        self.assertEqual(len(self._runs(wid1)), 1)  # no second dispatch
        self.assertNotIn(f"dispatched:{wid1}", result.actions)
        live = self._runs(wid1)[-1]
        self.assertIs(live.metrics.get("outcome_uncertain"), True)
        checkpoint = self.storage.latest(team_id="tx")
        assert checkpoint is not None
        self.assertEqual(
            list(checkpoint.uncertain_step_ids), [self.plan_ids[0]]
        )

    def test_first_pulse_crash_with_live_run_is_uncertain(self):
        # A live run exists but no checkpoint at all: pulse 1 started,
        # dispatched, then crashed before the first checkpoint saved.
        self.runner.ensure_plan_items()
        wid1 = self._wid(self.plan_ids[0])
        self.ledger.start_worker_run(
            work_item_id=wid1,
            executor_kind="team-specialist",
            tool_scope=("terminal",),
            authority_scope=("work:thread-dsh3",),
        )
        self._bump_termination_pulses(1)
        self.assertIsNone(self.storage.latest(team_id="tx"))

        resumed = self._new_runner(self.storage)
        self.assertTrue(resumed.interrupted_pulse_detected())
        result = resumed.step()
        self.assertEqual(result.uncertain_step_ids, [self.plan_ids[0]])
        self.assertEqual(len(self._runs(wid1)), 1)
        live = self._runs(wid1)[-1]
        self.assertIs(live.metrics.get("outcome_uncertain"), True)

    def test_uncertainty_clears_when_step_completes(self):
        self.runner.step()
        wid1 = self._wid(self.plan_ids[0])
        self._bump_termination_pulses(2)
        resumed = self._new_runner(self.storage)
        result = resumed.step()
        self.assertEqual(result.uncertain_step_ids, [self.plan_ids[0]])

        # Drive item 1 to completion: claim -> verify -> complete.
        # Completion implies the CP-3 verdict verified the outcome, so
        # the step is no longer unknown.
        self._claim(wid1)
        resumed.step()  # verify
        resumed.step()  # complete
        checkpoint = self.storage.latest(team_id="tx")
        assert checkpoint is not None
        self.assertIn(self.plan_ids[0], list(checkpoint.completed_step_ids))
        self.assertEqual(list(checkpoint.uncertain_step_ids), [])

    def test_checkpoint_uncertain_round_trip_and_old_dict_compat(self):
        checkpoint = Checkpoint(
            checkpoint_id="tx:pulse-2",
            team_id="tx",
            pulse=2,
            pending_step_ids=("tx-item-02",),
            uncertain_step_ids=("tx-item-01",),
        )
        restored = Checkpoint.from_dict(checkpoint.to_dict())
        self.assertEqual(restored, checkpoint)
        self.assertEqual(restored.uncertain_step_ids, ("tx-item-01",))
        # Checkpoints written before DSH-3 have no uncertain key.
        raw = checkpoint.to_dict()
        del raw["uncertain_step_ids"]
        self.assertEqual(Checkpoint.from_dict(raw).uncertain_step_ids, ())


if __name__ == "__main__":
    unittest.main()

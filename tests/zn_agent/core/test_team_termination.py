"""CP-1: team hard termination + STOP_REASON.

Covers the four hard caps (pulses / wall clock / tokens / tool calls),
the external stops (user_cancel / error), the refusal to ever emit
``converged`` without the CP-3 structured verdict, and the runner wiring:
a stopped team dispatches nothing more, and a re-checked stopped team
reports the same stored stop with no side effects.

The runner tests use the real EvidenceBoundSteerableWorkLedger on a temp
sqlite file, like test_team_runner.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    TeamRunner,
    VerificationOutcome,
)
from zn_agent.core.team_termination import (
    TerminationLimits,
    TerminationState,
    evaluate_termination,
    request_stop,
    take_stop,
)


class StubVerifier:
    def verify(self, *, item, run):
        return VerificationOutcome(passed=True, notes="stub")


def _state(**overrides) -> TerminationState:
    state = TerminationState()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


class TerminationCheckerTests(unittest.TestCase):
    NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)

    def test_no_cap_means_keep_going(self):
        self.assertIsNone(
            evaluate_termination(
                _state(pulses=1, started_at=self.NOW.isoformat()),
                TerminationLimits(),
                now=self.NOW,
            )
        )

    def test_max_pulses_cap(self):
        result = evaluate_termination(
            _state(pulses=300), TerminationLimits(), now=self.NOW
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.stop_reason, "max_pulses")
        self.assertEqual(result.trigger["pulses"], 300)
        self.assertEqual(result.trigger["limit_pulses"], 300)

    def test_time_cap(self):
        started = (self.NOW - timedelta(seconds=1800)).isoformat()
        result = evaluate_termination(
            _state(pulses=1, started_at=started),
            TerminationLimits(),
            now=self.NOW,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.stop_reason, "time_cap")
        self.assertGreaterEqual(result.trigger["elapsed_seconds"], 1800.0)

    def test_token_cap(self):
        result = evaluate_termination(
            _state(tokens_used=1_000_000), TerminationLimits(), now=self.NOW
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.stop_reason, "token_cap")
        self.assertEqual(result.trigger["tokens_used"], 1_000_000)

    def test_tool_cap(self):
        result = evaluate_termination(
            _state(tool_calls=300), TerminationLimits(), now=self.NOW
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.stop_reason, "tool_cap")
        self.assertEqual(result.trigger["tool_calls"], 300)

    def test_time_cap_wins_when_several_fire(self):
        started = (self.NOW - timedelta(seconds=9999)).isoformat()
        result = evaluate_termination(
            _state(
                pulses=999, tokens_used=9_999_999, tool_calls=999,
                started_at=started,
            ),
            TerminationLimits(),
            now=self.NOW,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.stop_reason, "time_cap")

    def test_converged_is_never_a_cap_result(self):
        # Even with every counter maxed out, the checker must not emit
        # converged: convergence is CP-3's verdict, not a cap.
        result = evaluate_termination(
            _state(pulses=999, tokens_used=9_999_999, tool_calls=999,
                   started_at=(self.NOW - timedelta(seconds=9999)).isoformat()),
            TerminationLimits(),
            now=self.NOW,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertNotEqual(result.stop_reason, "converged")

    def test_request_stop_accepts_user_cancel_and_error(self):
        for reason in ("user_cancel", "error"):
            state = TerminationState()
            request_stop(state, reason, detail="d")
            self.assertEqual(state.requested_stop, reason)

    def test_request_stop_rejects_converged_and_caps(self):
        for reason in (
            "converged",
            "time_cap",
            "token_cap",
            "tool_cap",
            "max_pulses",
            "nope",
        ):
            with self.assertRaises(ValueError, msg=reason):
                request_stop(TerminationState(), reason)

    def test_first_stop_wins(self):
        state = TerminationState()
        first = evaluate_termination(
            _state(pulses=999), TerminationLimits(), now=self.NOW
        )
        assert first is not None
        take_stop(state, first, now=self.NOW)
        self.assertEqual(state.stop_reason, "max_pulses")
        # A later stop attempt must not overwrite the first one.
        second = evaluate_termination(
            _state(
                started_at=(self.NOW - timedelta(seconds=9999)).isoformat()
            ),
            TerminationLimits(),
            now=self.NOW,
        )
        assert second is not None
        self.assertEqual(second.stop_reason, "time_cap")
        take_stop(state, second, now=self.NOW)
        self.assertEqual(state.stop_reason, "max_pulses")

    def test_invalid_limits_rejected(self):
        for kwargs in (
            {"max_pulses": 0},
            {"max_wall_clock_seconds": -1},
            {"max_total_tokens": 0},
            {"max_tool_calls": -5},
        ):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                TerminationLimits(**kwargs)


class TeamRunnerTerminationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-term-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-term-1"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        root = WorkItem(
            work_item_id="root-1",
            work_thread_id=self.thread_id,
            title="XX 项目",
            objective="把 XX 项目做完",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(root)
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="tx",
            work_thread_id=self.thread_id,
        )
        self.now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.store.close()

    def _runner(self, **kwargs) -> TeamRunner:
        kwargs.setdefault("now_fn", lambda: self.now)
        return TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=StubVerifier(),
            root_work_item_id="root-1",
            **kwargs,
        )

    def _journal_texts(self) -> list[str]:
        return [
            m.text
            for m in self.ledger.list_messages(self.thread_id, limit=500)
        ]

    def test_zero_progress_idle_stops_within_pulse_cap(self):
        # The bug: a specialist spinning with zero progress ran 30 minutes /
        # 150 pulses. The pulse backstop must stop it, with STOP_REASON.
        runner = self._runner(
            termination_limits=TerminationLimits(max_pulses=3)
        )
        r1 = runner.step()
        self.assertFalse(r1.stopped)
        self.assertTrue(any(a.startswith("dispatched:") for a in r1.actions))
        r2 = runner.step()
        self.assertFalse(r2.stopped)
        r3 = runner.step()
        self.assertTrue(r3.stopped, r3)
        self.assertEqual(r3.stop_reason, "max_pulses")
        self.assertEqual(r3.stop_trigger["pulses"], 3)
        self.assertEqual(r3.stop_progress["plan_items_completed"], 0)
        self.assertEqual(r3.stop_progress["plan_items_total"], 2)
        # The stop is journaled with its STOP_REASON.
        self.assertTrue(
            any("STOP_REASON=max_pulses" in t for t in self._journal_texts()),
            self._journal_texts(),
        )

    def test_stopped_team_is_idempotent_and_dispatches_nothing(self):
        runner = self._runner(
            termination_limits=TerminationLimits(max_pulses=1)
        )
        first = runner.step()
        self.assertTrue(first.stopped)
        self.assertEqual(first.stop_reason, "max_pulses")
        # Re-checking reports the same stored stop and dispatches nothing.
        again = runner.step()
        self.assertTrue(again.stopped)
        self.assertEqual(again.stop_reason, "max_pulses")
        self.assertEqual(again.stop_trigger, first.stop_trigger)
        self.assertEqual(again.actions, [])
        # A fresh runner on the same durable state sees the same stop.
        runner2 = self._runner(
            termination_limits=TerminationLimits(max_pulses=1)
        )
        third = runner2.step()
        self.assertTrue(third.stopped)
        self.assertEqual(third.stop_reason, "max_pulses")
        # Pulse counter did not advance on the idempotent re-checks.
        self.assertEqual(runner2.termination_state().pulses, 1)

    def test_time_cap_stops(self):
        runner = self._runner(
            termination_limits=TerminationLimits(
                max_wall_clock_seconds=60.0
            )
        )
        r1 = runner.step()
        self.assertFalse(r1.stopped)
        # 61 seconds later the same team hits the wall-clock cap.
        self.now = self.now + timedelta(seconds=61)
        r2 = runner.step()
        self.assertTrue(r2.stopped)
        self.assertEqual(r2.stop_reason, "time_cap")
        self.assertGreaterEqual(r2.stop_trigger["elapsed_seconds"], 60.0)

    def test_token_cap_stops(self):
        runner = self._runner(
            termination_limits=TerminationLimits(max_total_tokens=1000)
        )
        runner.record_token_usage(1000)
        result = runner.step()
        self.assertTrue(result.stopped)
        self.assertEqual(result.stop_reason, "token_cap")
        self.assertEqual(result.stop_trigger["tokens_used"], 1000)

    def test_tool_cap_stops(self):
        runner = self._runner(
            termination_limits=TerminationLimits(max_tool_calls=2)
        )
        runner.record_tool_call()
        runner.record_tool_call()
        result = runner.step()
        self.assertTrue(result.stopped)
        self.assertEqual(result.stop_reason, "tool_cap")
        self.assertEqual(result.stop_trigger["tool_calls"], 2)

    def test_user_cancel_stops_before_any_dispatch(self):
        runner = self._runner()
        runner.request_stop("user_cancel", detail="用户说停")
        result = runner.step()
        self.assertTrue(result.stopped)
        self.assertEqual(result.stop_reason, "user_cancel")
        self.assertEqual(result.actions, [])
        self.assertFalse(
            any("dispatched:" in a for a in result.actions), result.actions
        )

    def test_error_stop(self):
        runner = self._runner()
        runner.request_stop("error", detail="上游炸了")
        result = runner.step()
        self.assertTrue(result.stopped)
        self.assertEqual(result.stop_reason, "error")

    def test_converged_can_never_appear(self):
        runner = self._runner()
        with self.assertRaises(ValueError):
            runner.request_stop("converged")
        # Run to the pulse cap: the reason is the cap, never converged.
        capped = self._runner(
            termination_limits=TerminationLimits(max_pulses=1)
        )
        result = capped.step()
        self.assertEqual(result.stop_reason, "max_pulses")
        self.assertNotEqual(result.stop_reason, "converged")

    def test_completed_team_does_not_stop(self):
        # A team that finishes all plan items reports team_complete, not a
        # stop -- caps must not fire on a healthy run.
        runner = self._runner()
        r1 = runner.step()
        self.assertFalse(r1.stopped)
        shared = team_shared_memory(self.memory, "tx")
        wid1 = shared.recall("plan_item_map").value[
            self.team.plan[0].item_id
        ]
        runs = self.ledger.list_worker_runs(work_item_id=wid1)
        self.ledger.complete_worker_run(
            runs[-1].worker_run_id,
            result_summary="做完了",
            claimed_completion=True,
            verification_status="pending",
        )
        r2 = runner.step()  # verify
        self.assertFalse(r2.stopped)
        r3 = runner.step()  # complete item 1
        self.assertFalse(r3.stopped)
        self.assertIn(f"completed:{wid1}", r3.actions)


class TeamOwnerTerminationTests(unittest.TestCase):
    """Owner propagates a runner stop: no live run, blocked state."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-team-term-owner-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-team-term-owner"
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
        self.event = SimpleNamespace(
            event_id="evt-team-term-owner",
            payload={
                "work_thread_id": self.thread_id,
                "work_item_id": "root-1",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher", "developer"],
                },
            },
        )
        self.state = SimpleNamespace(data={})

    def tearDown(self):
        self.store.close()

    def test_user_cancel_propagates_through_owner(self):
        from zn_agent.core.team_work_owner import (
            ResidentTeamVerifier,
            TeamWorkOwner,
        )

        owner = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        first = owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-1"
        )
        self.assertIsNotNone(first.live_run_id)
        team = owner.resolve_team(
            event=self.event, state=self.state, thread_id=self.thread_id
        )
        runner = TeamRunner(
            team=team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=ResidentTeamVerifier(self.ledger),
            root_work_item_id="root-1",
        )
        runner.request_stop("user_cancel", detail="用户说停")
        stopped = owner.advance(
            event=self.event, state=self.state, root_work_item_id="root-1"
        )
        self.assertEqual(stopped.stop_reason, "user_cancel")
        self.assertEqual(stopped.state, "blocked")
        self.assertIsNone(stopped.live_run_id)
        self.assertIsNone(stopped.live_context)


class TeamResidentTerminationTests(unittest.TestCase):
    """Real resident loop: cancel stops the team, tool steps are counted."""

    def test_user_cancel_stops_resident_team_and_counts_tool_calls(self):
        from zn_agent.core.cognitive_resource import (
            CognitiveIncrement,
            CognitiveResourceWorkerFactory,
        )
        from zn_agent.core.models import ModelRoute
        from zn_agent.core.provider_bridge import build_resident_runtime
        from zn_agent.core.recovery_bounded_work import (
            RecoveryBoundedWorkLedger,
        )
        from zn_agent.core.team_work_owner import (
            ResidentTeamVerifier,
            TeamWorkOwner,
        )
        from zn_agent.core.work_restore_control import (
            RestoreAwareWorkControl,
        )

        class _OneStepCognition:
            """Fixture: propose one write_file step, then prose forever."""

            def __init__(self) -> None:
                self.calls = 0

            def invoke(self, *, question: str, context: str):
                self.calls += 1
                if "调研-01" in question and self.calls <= 2:
                    proposal = {
                        "zn_work_step": {
                            "objective": "调研-01 写一份可验证的工作产物",
                            "action": {
                                "kind": "write_file",
                                "path": "research-notes.md",
                                "content": "调研-01 verified step\n",
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "research-notes.md",
                                "expected_text": "调研-01 verified step\n",
                            },
                        }
                    }
                    return CognitiveIncrement(
                        text=json.dumps(proposal, ensure_ascii=False),
                        provider="fixture-cognition",
                        model="team-specialist-fixture",
                    )
                return CognitiveIncrement(
                    text="继续按现有证据推进。",
                    provider="fixture-cognition",
                    model="team-specialist-fixture",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "team-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _OneStepCognition()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="team-term-cognition",
                            provider="fixture",
                            model="team-specialist-fixture",
                            capabilities={
                                "general": 1.0,
                                "reasoning": 1.0,
                                "coding": 1.0,
                                "research": 1.0,
                                "language_understanding": 1.0,
                            },
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(
                        resource_builder=lambda _route: cognition,
                    ),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(resident)
                )
                ledger = control.ledger
                ledger.create_thread(thread_id="team-term-e2e", title="XX 项目")
                ledger.attach_workspace(
                    "team-term-e2e", workspace, name="Team Workspace"
                )
                _, event = control.start(
                    "team-term-e2e",
                    "给 XX 项目组个团队",
                    payload={
                        "model_policy": "on_demand",
                        "team_request": {
                            "project_title": "XX 项目",
                            "role_keys": ["researcher", "developer"],
                        },
                    },
                )
                # Drive until the first Body-verified specialist step lands
                # as evidence on its WorkerRun (file on disk alone is not
                # evidence -- the Body must verify the postcondition first).
                from zn_agent.core.team_work_owner import verified_evidence

                def _evidence_count() -> int:
                    total = 0
                    for item in ledger.list_work_items("team-term-e2e"):
                        for run in ledger.list_worker_runs(
                            work_item_id=item.work_item_id
                        ):
                            total += len(verified_evidence(run))
                    return total

                for _ in range(120):
                    resident.live_once()
                    if _evidence_count() >= 1:
                        break
                self.assertGreaterEqual(
                    _evidence_count(),
                    1,
                    "first verified specialist step never landed as evidence",
                )
                self.assertTrue(
                    (workspace / "research-notes.md").is_file(),
                    "first specialist step never executed",
                )
                # The executed Body step was counted against the tool cap.
                owner = TeamWorkOwner(
                    ledger=resident.work_ledger, memory=resident.memory
                )
                state = resident.store.get_working_state()
                team = owner.resolve_team(
                    event=event, state=state, thread_id="team-term-e2e"
                )
                runner = TeamRunner(
                    team=team,
                    ledger=resident.work_ledger,
                    memory=resident.memory,
                    verifier=ResidentTeamVerifier(resident.work_ledger),
                    root_work_item_id=ledger.work_item_for_event(
                        event.event_id
                    ).work_item_id,
                )
                self.assertEqual(
                    runner.termination_state().tool_calls, 1
                )
                # Now the user cancels: the next pulses must stop the team
                # instead of dispatching the second specialist.
                runner.request_stop("user_cancel", detail="用户说停")
                for _ in range(40):
                    resident.live_once()
                self.assertEqual(
                    runner.termination_state().stop_reason, "user_cancel"
                )
                self.assertFalse(
                    (workspace / "implementation.md").exists(),
                    "second specialist was dispatched after user_cancel",
                )
                journal = [
                    m.text
                    for m in ledger.list_messages("team-term-e2e", limit=500)
                ]
                self.assertTrue(
                    any(
                        "STOP_REASON=user_cancel" in text for text in journal
                    ),
                    journal,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

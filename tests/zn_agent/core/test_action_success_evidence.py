"""Q13: prior success evidence in action retrieval (Blueprint §7.5).

Covers the four acceptance points:
  1. same-score actions are ordered by historical verified counts;
  2. actions with no history are still retrievable and not penalized;
  3. counts survive a store close/reopen (restart);
  4. verdicts are written at the post-verification settlement point.
Plus: relevance/availability order is untouched by success evidence, and a
failing observer never breaks execution.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Callable

from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.store import KernelStore


def _descriptor(action_id: str) -> ActionDescriptor:
    return ActionDescriptor(
        action_id=action_id,
        provider="zn.test",
        description="Echo message text aloud",
        body_action_kind="test_echo",
        effect_class="read_only",
        tags=("echo", "message"),
    )


def _registry(*action_ids: str) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    for action_id in action_ids:
        registry.register(
            _descriptor(action_id),
            availability_probe=lambda current: ActionAvailability(
                current.action_id,
                "available",
                evidence={"source": "test"},
            ),
        )
    return registry


class _FakeBody:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success

    def act(self, kind: str, *, event_id=None, **args):
        return BodyActionResult(
            action_id=f"body-{kind}",
            kind=kind,
            success=self.success,
            data={} if self.success else {},
            error=None if self.success else "boom",
            event_id=event_id,
        )


class SuccessEvidenceRankingTests(unittest.TestCase):
    def test_tied_actions_rank_by_historical_verified_count(self) -> None:
        # demo.echo.alpha and demo.echo.beta score identically for
        # "echo message" (same tags, same description, both available);
        # the beta action has prior verified executions, so it ranks first.
        registry = _registry("demo.echo.alpha", "demo.echo.beta")
        registry.set_success_evidence_provider(
            lambda action_id: 5 if action_id == "demo.echo.beta" else 0
        )

        actions = registry.relevant_actions(task="echo message")

        self.assertEqual(actions[0].action_id, "demo.echo.beta")
        self.assertEqual(actions[1].action_id, "demo.echo.alpha")
        self.assertEqual(actions[0].score, actions[1].score)

    def test_success_evidence_never_overrides_relevance_or_availability(
        self,
    ) -> None:
        # A low-relevance action with a huge verified history still ranks
        # behind a more relevant action with no history: token relevance is
        # the primary order, availability priority is untouched.
        registry = ActionFabricRegistry()
        low = ActionDescriptor(
            action_id="demo.unrelated.noise",
            provider="zn.test",
            description="Unrelated background noise",
            body_action_kind="test_noise",
            effect_class="read_only",
            tags=("noise",),
        )
        registry.register(
            low,
            availability_probe=lambda current: ActionAvailability(
                current.action_id, "available", evidence={"source": "test"}
            ),
        )
        registry.register(
            _descriptor("demo.echo.only"),
            availability_probe=lambda current: ActionAvailability(
                current.action_id, "available", evidence={"source": "test"}
            ),
        )
        registry.set_success_evidence_provider(
            lambda action_id: 1000 if action_id == "demo.unrelated.noise" else 0
        )

        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(actions[0].action_id, "demo.echo.only")

        # Unavailable actions still sort after available ones even when
        # they carry prior success evidence.
        registry2 = ActionFabricRegistry()
        avail = _descriptor("demo.echo.fresh")
        stale = _descriptor("demo.echo.stale")
        registry2.register(
            avail,
            availability_probe=lambda current: ActionAvailability(
                current.action_id, "available", evidence={"source": "test"}
            ),
        )
        registry2.register(
            stale,
            availability_probe=lambda current: ActionAvailability(
                current.action_id,
                "unavailable",
                reason="device offline",
                evidence={"source": "test"},
            ),
        )
        registry2.set_success_evidence_provider(
            lambda action_id: 100 if action_id == "demo.echo.stale" else 0
        )
        actions2 = registry2.relevant_actions(task="echo message")
        self.assertEqual(actions2[0].action_id, "demo.echo.fresh")
        self.assertEqual(actions2[1].action_id, "demo.echo.stale")

    def test_no_history_actions_are_retrievable_and_not_penalized(self) -> None:
        # With no provider at all, order falls back to the old deterministic
        # rule (availability, -score, action_id); with a provider that
        # raises, nothing is hidden and nothing explodes.
        registry = _registry("demo.echo.alpha", "demo.echo.beta")
        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            ["demo.echo.alpha", "demo.echo.beta"],
        )

        def bad_provider(_: str) -> int:
            raise RuntimeError("evidence backend down")

        registry.set_success_evidence_provider(bad_provider)
        recovered = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in recovered],
            ["demo.echo.alpha", "demo.echo.beta"],
        )


class SuccessEvidenceStoreTests(unittest.TestCase):
    def test_counts_survive_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "kernel.db")
            store = KernelStore(path)
            store.record_action_verdict("demo.echo.beta", verified=True)
            store.record_action_verdict("demo.echo.beta", verified=True)
            store.record_action_verdict("demo.echo.beta", verified=False)
            store.record_action_verdict("demo.echo.other", verified=True)
            self.assertEqual(
                store.get_action_verdict_counts("demo.echo.beta"), (2, 1)
            )
            store.close()

            # Simulate a restart: reopen the same file.
            reopened = KernelStore(path)
            try:
                self.assertEqual(
                    reopened.get_action_verdict_counts("demo.echo.beta"), (2, 1)
                )
                self.assertEqual(
                    reopened.get_action_verdict_counts("demo.echo.other"), (1, 0)
                )
                self.assertEqual(
                    reopened.get_action_verdict_counts("never.seen"), (0, 0)
                )
            finally:
                reopened.close()

    def test_blank_action_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(str(Path(tmp) / "kernel.db"))
            try:
                with self.assertRaises(ValueError):
                    store.record_action_verdict("  ", verified=True)
            finally:
                store.close()


class SuccessEvidenceSettlementTests(unittest.TestCase):
    def _wire(self, store: KernelStore) -> Callable[[str, bool], None]:
        def observer(action_id: str, verified: bool) -> None:
            store.record_action_verdict(action_id, verified=verified)

        return observer

    def test_settled_verdicts_are_recorded_at_the_verdict_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(str(Path(tmp) / "kernel.db"))
            try:
                descriptor = _descriptor("demo.echo.probe")

                ok_runtime = ActionExecutionRuntime(
                    _registry("demo.echo.probe"),
                    _FakeBody(success=True),
                    success_observer=self._wire(store),
                )
                result = ok_runtime.execute(ActionRequest("demo.echo.probe"))
                self.assertEqual(result.verification.status, "verified")
                self.assertEqual(
                    store.get_action_verdict_counts("demo.echo.probe"), (1, 0)
                )

                fail_runtime = ActionExecutionRuntime(
                    _registry("demo.echo.probe"),
                    _FakeBody(success=False),
                    success_observer=self._wire(store),
                )
                failed = fail_runtime.execute(ActionRequest("demo.echo.probe"))
                self.assertEqual(failed.verification.status, "failed")
                self.assertEqual(
                    store.get_action_verdict_counts("demo.echo.probe"), (1, 1)
                )

                # No observer attached: execution still works, nothing recorded.
                plain = ActionExecutionRuntime(
                    _registry("demo.echo.probe"), _FakeBody(success=True)
                )
                plain_result = plain.execute(ActionRequest("demo.echo.probe"))
                self.assertEqual(plain_result.verification.status, "verified")
                self.assertEqual(
                    store.get_action_verdict_counts("demo.echo.probe"), (1, 1)
                )
            finally:
                store.close()

    def test_failing_observer_never_breaks_execution(self) -> None:
        def bad_observer(action_id: str, verified: bool) -> None:
            raise RuntimeError("evidence backend down")

        runtime = ActionExecutionRuntime(
            _registry("demo.echo.probe"),
            _FakeBody(success=True),
            success_observer=bad_observer,
        )
        result = runtime.execute(ActionRequest("demo.echo.probe"))
        self.assertEqual(result.verification.status, "verified")
        self.assertTrue(result.success)
        self.assertEqual(runtime._success_observer_failures, 1)

    def test_end_to_end_retrieval_uses_store_evidence(self) -> None:
        # Full loop: execute -> store counts -> retrieval ranks by them.
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(str(Path(tmp) / "kernel.db"))
            try:
                registry = _registry("demo.echo.alpha", "demo.echo.beta")
                registry.set_success_evidence_provider(
                    lambda action_id: store.get_action_verdict_counts(action_id)[0]
                )
                runtime = ActionExecutionRuntime(
                    registry,
                    _FakeBody(success=True),
                    success_observer=self._wire(store),
                )
                for _ in range(3):
                    runtime.execute(ActionRequest("demo.echo.beta"))

                actions = registry.relevant_actions(task="echo message")
                self.assertEqual(actions[0].action_id, "demo.echo.beta")
                self.assertEqual(actions[1].action_id, "demo.echo.alpha")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

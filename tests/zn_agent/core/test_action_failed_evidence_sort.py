"""Q17: prior failed evidence joins action retrieval ranking (Q13 follow-up).

Covers the acceptance points:
  1. same-score actions sort by (verified desc, failure rate asc);
  2. a high-failure-rate action is demoted (before/after contrast: without
     the failed provider it only ties on the action_id);
  3. actions with no history keep rate 0.0 -- not penalized, still
     retrievable (Q13 acceptance semantics preserved);
  4. failure rate never overrides the verified order;
  5. a missing/failing failed provider falls back to Q13 behavior;
  6. counts persist via the existing action_success_counts table
     (no schema change) and drive the rate end to end.
The failed dimension is a *rate* (failed / (verified + failed)), not a raw
count, so an old burst of environmental failures cannot bury an action
forever -- later verified runs pull the rate back down.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
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


class FailedEvidenceSortTests(unittest.TestCase):
    def _wire(self, registry: ActionFabricRegistry, counts) -> None:
        registry.set_success_evidence_provider(
            lambda action_id: counts.get(action_id, (0, 0))[0]
        )
        registry.set_failed_evidence_provider(
            lambda action_id: counts.get(action_id, (0, 0))[1]
        )

    def test_tied_actions_rank_by_verified_then_failure_rate(self) -> None:
        # All four score identically for "echo message" (same tags,
        # description, availability). Verified-high still ranks first;
        # inside a verified tie the lower failure rate wins.
        counts = {
            "demo.echo.alpha": (5, 1),  # rate 1/6
            "demo.echo.beta": (5, 9),  # rate 9/14
            "demo.echo.gamma": (3, 0),  # rate 0
            "demo.echo.delta": (0, 0),  # no history, rate 0
        }
        registry = _registry(*counts)
        self._wire(registry, counts)

        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            [
                "demo.echo.alpha",
                "demo.echo.beta",
                "demo.echo.gamma",
                "demo.echo.delta",
            ],
        )
        # Same relevance segment for all of them.
        scores = {item.score for item in actions}
        self.assertEqual(len(scores), 1)

    def test_high_failure_rate_demoted_only_when_failed_evidence_attached(
        self,
    ) -> None:
        # Before/after contrast: with only the Q13 verified provider, the
        # flaky action ties and falls back to action_id order; attaching
        # the failed provider demotes it.
        counts = {
            "demo.echo.zzz": (4, 0),  # clean
            "demo.echo.aaa": (4, 12),  # flaky, rate 0.75
        }
        registry = _registry(*counts)
        registry.set_success_evidence_provider(
            lambda action_id: counts.get(action_id, (0, 0))[0]
        )

        before = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in before],
            ["demo.echo.aaa", "demo.echo.zzz"],
        )

        registry.set_failed_evidence_provider(
            lambda action_id: counts.get(action_id, (0, 0))[1]
        )
        after = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in after],
            ["demo.echo.zzz", "demo.echo.aaa"],
        )

    def test_no_history_actions_are_not_penalized(self) -> None:
        # No history means rate 0.0: fresh actions keep the old
        # deterministic order among themselves and are never hidden;
        # the action with only failed history sinks inside the segment
        # but stays retrievable.
        counts = {
            "demo.echo.fresh1": (0, 0),
            "demo.echo.fresh2": (0, 0),
            "demo.echo.burned": (0, 3),  # rate 1.0
        }
        registry = _registry(*counts)
        self._wire(registry, counts)

        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            ["demo.echo.fresh1", "demo.echo.fresh2", "demo.echo.burned"],
        )

    def test_failure_rate_never_overrides_verified_order(self) -> None:
        # Verified-high first is the Q13 semantic and stays: a
        # high-verified/high-rate action still outranks a low-verified
        # clean one; the rate only demotes inside a verified tie.
        counts = {
            "demo.echo.mid": (10, 2),  # rate 2/12
            "demo.echo.high": (10, 40),  # rate 40/50
            "demo.echo.low": (2, 0),  # rate 0
        }
        registry = _registry(*counts)
        self._wire(registry, counts)

        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            ["demo.echo.mid", "demo.echo.high", "demo.echo.low"],
        )

    def test_failing_failed_provider_is_not_a_penalty(self) -> None:
        # A backend that raises for failed counts degrades to Q13
        # behavior: order by -verified, then action_id; nothing hidden.
        counts = {
            "demo.echo.beta": (5, 99),
            "demo.echo.alpha": (5, 0),
        }
        registry = _registry(*counts)
        registry.set_success_evidence_provider(
            lambda action_id: counts.get(action_id, (0, 0))[0]
        )

        def bad_failed_provider(_: str) -> int:
            raise RuntimeError("evidence backend down")

        registry.set_failed_evidence_provider(bad_failed_provider)
        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            ["demo.echo.alpha", "demo.echo.beta"],
        )

    def test_negative_and_none_counts_are_clamped_to_no_evidence(self) -> None:
        registry = _registry("demo.echo.alpha", "demo.echo.beta")
        registry.set_success_evidence_provider(lambda _: None)
        registry.set_failed_evidence_provider(lambda _: -7)

        actions = registry.relevant_actions(task="echo message")
        self.assertEqual(
            [item.action_id for item in actions],
            ["demo.echo.alpha", "demo.echo.beta"],
        )

    def test_store_counts_drive_failure_rate_sort_and_persist(self) -> None:
        # End to end through the real table: failed counts persist across
        # a store reopen (no schema change) and drive the ranking.
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "kernel.db")
            store = KernelStore(path)
            try:
                for _ in range(3):
                    store.record_action_verdict("demo.echo.alpha", verified=True)
                for _ in range(3):
                    store.record_action_verdict("demo.echo.beta", verified=True)
                for _ in range(6):
                    store.record_action_verdict("demo.echo.beta", verified=False)
                self.assertEqual(
                    store.get_action_verdict_counts("demo.echo.beta"), (3, 6)
                )
            finally:
                store.close()

            reopened = KernelStore(path)
            try:
                self.assertEqual(
                    reopened.get_action_verdict_counts("demo.echo.beta"), (3, 6)
                )
                registry = _registry("demo.echo.alpha", "demo.echo.beta")
                registry.set_success_evidence_provider(
                    lambda action_id: reopened.get_action_verdict_counts(
                        action_id
                    )[0]
                )
                registry.set_failed_evidence_provider(
                    lambda action_id: reopened.get_action_verdict_counts(
                        action_id
                    )[1]
                )
                actions = registry.relevant_actions(task="echo message")
                # Same verified count (3); alpha's rate 0 beats beta's 6/9.
                self.assertEqual(
                    [item.action_id for item in actions],
                    ["demo.echo.alpha", "demo.echo.beta"],
                )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()

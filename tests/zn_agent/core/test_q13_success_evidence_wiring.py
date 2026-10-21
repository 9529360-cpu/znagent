"""Q13 production wiring: KernelStore on the real product resident path.

Covers the Q13-assemble acceptance points end to end on the instances the
product actually uses (not hand-built fixtures):

  1. a verified verdict executed through the PRODUCT executor increments
     the product KernelStore's verified count by exactly one;
  2. tie-break retrieval ranking reads the product store: an action with
     prior verified executions ranks before a tie-score action with no
     history (which stays retrievable and unpenalized);
  3. counts survive a store close/reopen (restart) at the product path;
  4. a failing observer on the product executor's observer slot never
     breaks execution (fail closed, failure counted).

Every test builds the real product resident via
``provider_bridge.build_resident_runtime`` with a temp store file -- the
same chain the daemon uses (``daemon.py`` ->
``build_resident_runtime_from_existing_stack``). Only the Body is swapped
for a deterministic fake so a read_only probe can settle to "verified"
without touching real device effects; the fabric, the executor, the
observer slot, the provider hook, and the store are all the product ones.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_execution import ActionRequest
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.store import KernelStore


def _probe_descriptor(action_id: str) -> ActionDescriptor:
    return ActionDescriptor(
        action_id=action_id,
        provider="zn.test",
        description="Q13 wiring tie probe blorpz message text",
        body_action_kind="test_q13_probe",
        effect_class="read_only",
        tags=("blorpz", "message"),
    )


class _FakeBody:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success

    def act(self, kind: str, *, event_id=None, **args):
        return BodyActionResult(
            action_id=f"body-{kind}",
            kind=kind,
            success=self.success,
            data={},
            error=None if self.success else "boom",
            event_id=event_id,
        )


def _make_resident(tmp: str):
    resident = build_resident_runtime(
        config={"model": {}},
        store_path=Path(tmp) / "kernel.db",
    )
    fabric = resident.action_fabric
    for action_id in ("test.q13.alpha", "test.q13.beta"):
        fabric.register(
            _probe_descriptor(action_id),
            availability_probe=lambda current: ActionAvailability(
                current.action_id,
                "available",
                evidence={"source": "q13-wiring-test"},
            ),
        )
    # Deterministic Body so the read_only probe settles to "verified"
    # without real device effects. The executor (with its wired observer),
    # the fabric (with its wired provider), and the store stay product.
    resident.action_executor.body = _FakeBody(success=True)
    return resident


class ProductSuccessEvidenceWiringTests(unittest.TestCase):
    def test_wiring_hooks_are_attached_on_product_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = _make_resident(tmp)
            self.assertIsNotNone(resident.action_fabric._success_evidence)
            self.assertIsNotNone(resident.action_executor._success_observer)

    def test_verified_verdict_increments_product_store_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = _make_resident(tmp)
            executor = resident.action_executor
            store = resident.store

            result = executor.execute(ActionRequest("test.q13.beta"))
            self.assertEqual(result.verification.status, "verified")

            # The wired observer wrote the settled verdict into the product
            # KernelStore (the same store object the resident owns).
            self.assertEqual(store.get_action_verdict_counts("test.q13.beta"), (1, 0))
            self.assertEqual(store.get_action_verdict_counts("test.q13.alpha"), (0, 0))

            second = executor.execute(ActionRequest("test.q13.beta"))
            self.assertEqual(second.verification.status, "verified")
            self.assertEqual(store.get_action_verdict_counts("test.q13.beta"), (2, 0))

    def test_tie_break_ranking_reads_product_store_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = _make_resident(tmp)
            executor = resident.action_executor

            def probe_order() -> list[str]:
                actions = resident.action_fabric.relevant_actions(
                    task="blorpz q13 tie probe message"
                )
                return [
                    item.action_id
                    for item in actions
                    if item.action_id in ("test.q13.alpha", "test.q13.beta")
                ]

            # Before any history: pure deterministic tie-break
            # (availability, score, action_id) -- alpha first.
            self.assertEqual(probe_order(), ["test.q13.alpha", "test.q13.beta"])

            for _ in range(3):
                result = executor.execute(ActionRequest("test.q13.beta"))
                self.assertEqual(result.verification.status, "verified")

            # After beta's prior verified executions (written through the
            # product wiring): beta breaks the tie. Alpha has no history:
            # still retrievable, unpenalized, and not hidden.
            self.assertEqual(probe_order(), ["test.q13.beta", "test.q13.alpha"])

            # Same (availability, score) segment: only the evidence tie-break
            # moved beta up; the two probes' relevance scores are equal.
            ranked = {
                item.action_id: item
                for item in resident.action_fabric.relevant_actions(
                    task="blorpz q13 tie probe message"
                )
            }
            self.assertEqual(
                ranked["test.q13.alpha"].score, ranked["test.q13.beta"].score
            )

    def test_counts_survive_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "kernel.db")
            resident = _make_resident(tmp)
            result = resident.action_executor.execute(ActionRequest("test.q13.beta"))
            self.assertEqual(result.verification.status, "verified")
            self.assertEqual(
                resident.store.get_action_verdict_counts("test.q13.beta"), (1, 0)
            )
            resident.store.close()

            # Simulate a restart: reopen the same file with a fresh store.
            reopened = KernelStore(path)
            try:
                self.assertEqual(
                    reopened.get_action_verdict_counts("test.q13.beta"), (1, 0)
                )
                self.assertEqual(
                    reopened.get_action_verdict_counts("test.q13.alpha"), (0, 0)
                )
            finally:
                reopened.close()

    def test_failing_observer_on_product_slot_never_breaks_execution(self) -> None:
        def bad_observer(action_id: str, verified: bool) -> None:
            raise RuntimeError("evidence backend down")

        with tempfile.TemporaryDirectory() as tmp:
            resident = _make_resident(tmp)
            executor = resident.action_executor
            # Replace the product-wired observer with a broken one on the
            # same slot the wiring used: execution must stay fail-closed.
            executor.register_success_observer(bad_observer)

            result = executor.execute(ActionRequest("test.q13.beta"))
            self.assertEqual(result.verification.status, "verified")
            self.assertTrue(result.success)
            self.assertEqual(executor._success_observer_failures, 1)

            # The product store got nothing from the broken observer, and
            # the failure never leaked into the execution path.
            self.assertEqual(
                resident.store.get_action_verdict_counts("test.q13.beta"), (0, 0)
            )


if __name__ == "__main__":
    unittest.main()

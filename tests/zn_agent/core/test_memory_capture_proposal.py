from __future__ import annotations

"""P1-4: memory-capture proposals (confirm before writing).

Covers: Work completion produces a memory_capture approval card; approving
the card writes the fact through the existing remember path (recallable);
deny/expire means nothing is written; secret-shaped or <private> content
never becomes a proposal; at most one candidate per completion; repeated
completions do not open a second card; no approval path fail-closes.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.approval_cards import (
    APPROVAL_KINDS,
    ApprovalCardStore,
    validate_approval_kind,
)
from zn_agent.core.store import KernelStore
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.memory_capture_proposal import (
    APPROVAL_KIND_MEMORY_CAPTURE,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_BLOCKED,
    PROPOSAL_STATUS_DENIED,
    PROPOSAL_STATUS_NO_CANDIDATE,
    PROPOSAL_STATUS_PROPOSED,
    PROPOSAL_STATUS_WRITTEN,
    MemoryCaptureDriver,
    extract_memory_capture_candidate,
)

PREFERENCE_RESPONSE = "任务已完成。请记住，以后都用 pnpm，不要用 npm。依赖安装也一样。"


def _decision_to(decision: str, store: ApprovalCardStore, request_id: str) -> None:
    store.decide(request_id, decision)


class MemoryCaptureKindTests(unittest.TestCase):
    def test_kind_registered(self) -> None:
        self.assertIn(APPROVAL_KIND_MEMORY_CAPTURE, APPROVAL_KINDS)
        self.assertEqual(validate_approval_kind("memory_capture"), "memory_capture")


class MemoryCaptureDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.kernel = KernelStore(self.root / "memory.db")
        self.addCleanup(self.kernel.close)
        self.memory = StructuredMemory(self.kernel)
        self.approval_store = ApprovalCardStore(self.root / "approvals.db")
        self.driver = MemoryCaptureDriver(
            memory=self.memory, approval_store=self.approval_store
        )

    def _pending(self):
        return self.approval_store.pending_requests()

    def _complete(self, response: str = PREFERENCE_RESPONSE) -> None:
        self.driver.on_work_completed(
            task="把依赖装好",
            response=response,
            reason="",
            thread_id="thread-1",
            event_id="event-1",
        )

    # -- propose ----------------------------------------------------------

    def test_completion_produces_memory_capture_card(self) -> None:
        self._complete()
        pending = self._pending()
        self.assertEqual(len(pending), 1)
        card = pending[0]
        self.assertEqual(card.action_kind, "memory_capture")
        self.assertEqual(card.source, "resident")
        self.assertEqual(card.event_id, "event-1")
        self.assertTrue(card.target.startswith("memory_capture:"))
        self.assertIn("以后都用 pnpm，不要用 npm", card.value_text)

    def test_no_signal_no_proposal(self) -> None:
        self._complete(response="任务已完成，一切正常，没有其他事项。")
        self.assertEqual(self._pending(), [])

    def test_at_most_one_candidate(self) -> None:
        self._complete(
            response="请记住，以后都用 pnpm。另外请记住，我喜欢用深色主题。"
        )
        pending = self._pending()
        self.assertEqual(len(pending), 1)
        # The first signal sentence wins.
        self.assertIn("以后都用 pnpm", pending[0].value_text)
        self.assertNotIn("深色主题", pending[0].value_text)

    def test_idempotent_same_fact_single_card(self) -> None:
        self._complete()
        self._complete()
        self.assertEqual(len(self._pending()), 1)

    # -- approve -> remember -> recall -------------------------------------

    def test_approve_writes_fact_recallable(self) -> None:
        self._complete()
        card = self._pending()[0]
        _decision_to("allow_once", self.approval_store, card.request_id)
        self.driver.poll_pending()

        proposals = self.driver.poll_pending()
        self.assertEqual(proposals[0].status, PROPOSAL_STATUS_WRITTEN)
        candidate = proposals[0].candidate
        self.assertIsNotNone(candidate)
        match = self.memory.recall(candidate.alias)
        self.assertIsNotNone(match)
        self.assertEqual(match.key, candidate.fact_key)
        self.assertIn("以后都用 pnpm", str(match.value))

    def test_approve_twice_does_not_reopen(self) -> None:
        self._complete()
        card = self._pending()[0]
        _decision_to("allow_once", self.approval_store, card.request_id)
        self.driver.poll_pending()
        # A later completion with the same fact must not open a new card.
        self._complete()
        self.assertEqual(self._pending(), [])

    # -- deny / expire -> never written ------------------------------------

    def test_deny_never_writes(self) -> None:
        self._complete()
        card = self._pending()[0]
        proposal = self.driver.propose_from_completion(
            task="把依赖装好", response=PREFERENCE_RESPONSE, reason=""
        )
        _decision_to("deny", self.approval_store, card.request_id)
        self.driver.poll_pending()

        self.assertEqual(proposal.status, PROPOSAL_STATUS_DENIED)
        self.assertIsNone(self.memory.recall(proposal.candidate.alias))
        self.assertEqual(
            [key for key in (fact["key"] for fact in self.kernel.list_facts()) if key.startswith("memory_capture:")],
            [],
        )

    def test_expired_card_never_writes(self) -> None:
        self._complete()
        card = self._pending()[0]
        proposal = self.driver.propose_from_completion(
            task="把依赖装好", response=PREFERENCE_RESPONSE, reason=""
        )
        # "Ignored" = the card lapses without a decision.
        self.approval_store.expire_overdue(
            now=datetime.now(timezone.utc) + timedelta(days=2)
        )
        self.driver.poll_pending()

        self.assertEqual(proposal.status, PROPOSAL_STATUS_DENIED)
        self.assertIsNone(self.memory.recall(proposal.candidate.alias))

    def test_denied_fact_never_reopens_card(self) -> None:
        self._complete()
        card = self._pending()[0]
        _decision_to("deny", self.approval_store, card.request_id)
        self.driver.poll_pending()
        self._complete()
        self.assertEqual(self._pending(), [])

    # -- secrets never proposed --------------------------------------------

    def test_secret_value_never_proposed(self) -> None:
        candidate = extract_memory_capture_candidate(
            "把密钥配好",
            "请记住，api_key=sk-test-abc123 是内部服务的密钥。",
            "",
        )
        self.assertIsNone(candidate)
        self._complete(response="请记住，api_key=sk-test-abc123 是内部服务的密钥。")
        self.assertEqual(self._pending(), [])

    def test_bearer_secret_never_proposed(self) -> None:
        self._complete(
            response="记住，Authorization: Bearer abcdef123456 用于调用内部接口。"
        )
        self.assertEqual(self._pending(), [])

    def test_private_block_never_proposed(self) -> None:
        self._complete(
            response="<private>记住我喜欢用 pnpm</private>，任务已完成。"
        )
        self.assertEqual(self._pending(), [])

    # -- fail-closed --------------------------------------------------------

    def test_no_approval_path_blocks_and_never_writes(self) -> None:
        driver = MemoryCaptureDriver(memory=self.memory, approval_store=None)
        proposal = driver.propose_from_completion(
            task="把依赖装好",
            response=PREFERENCE_RESPONSE,
            reason="",
            thread_id="t",
            event_id="e",
        )
        self.assertEqual(proposal.status, PROPOSAL_STATUS_BLOCKED)
        driver.poll_pending()
        self.assertIsNone(self.memory.recall(proposal.candidate.alias))

    def test_on_work_completed_never_raises(self) -> None:
        driver = MemoryCaptureDriver(memory=None, approval_store=None)
        # A broken memory/approval setup must not break Work finalization.
        driver.on_work_completed(
            task=None, response=None, reason=None, thread_id=None, event_id=None
        )

    def test_proposal_is_advisory_before_approval(self) -> None:
        self._complete()
        # Pending card alone must not write anything.
        self.driver.poll_pending()
        self.assertEqual(self._pending(), [self._pending()[0]])
        self.assertEqual(
            [fact["key"] for fact in self.kernel.list_facts()],
            [],
        )


if __name__ == "__main__":
    unittest.main()

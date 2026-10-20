from __future__ import annotations

"""P1-5: proactive skill proposal on the 2nd verified completion.

Acceptance:
1. 第 2 次验证通过后出现提案 (proposal appears after the 2nd verified pass)
2. 确认后 Skill 可引用 (confirmable through the existing skill_confirm flow,
   then referenceable)
3. 拒绝后不保存 (decline removes the draft; nothing becomes active)
4. 不重复提案 (no re-proposal: 3rd+ pass, declined, confirmed, or a
   same-name pending draft)
5. 跨重启计数持久 (the counter survives a store reopen)
"""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.models import AgentEvent
from zn_agent.core.skill_ledger import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    SkillLedger,
    SkillOwner,
    SkillRecord,
)
from zn_agent.core.skill_proposal import (
    PROPOSAL_STATE_DECLINED,
    PROPOSAL_STATE_PROPOSED,
    SkillProposalDriver,
    append_proposal_message,
    propose_skill_for_verified_completion,
    task_fingerprint,
)
from zn_agent.core.store import KernelStore

_TASK = "汇总每日进展"
_OBJECTIVE = "把今天各项目的进展汇总成一份日报"
_CRITERIA = ["覆盖全部 3 个项目", "每项有负责人和下一步"]


def _temp_store(test: unittest.TestCase) -> KernelStore:
    tmp = test.enterContext(tempfile.TemporaryDirectory())
    store = KernelStore(Path(tmp) / "kernel.db")
    test.addCleanup(store.close)
    return store


def _verify(
    driver: SkillProposalDriver,
    *,
    task: str = _TASK,
    thread_id: str = "thread-1",
    event_id: str = "evt-1",
):
    return driver.on_verified_completion(
        task=task,
        objective=_OBJECTIVE,
        acceptance_criteria=_CRITERIA,
        response="日报已生成。",
        thread_id=thread_id,
        event_id=event_id,
    )


class FingerprintTests(unittest.TestCase):
    def test_deterministic(self) -> None:
        first = task_fingerprint(
            task=_TASK, objective=_OBJECTIVE, acceptance_criteria=_CRITERIA
        )
        second = task_fingerprint(
            task=_TASK, objective=_OBJECTIVE, acceptance_criteria=_CRITERIA
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("taskfp:"))

    def test_criteria_order_does_not_matter(self) -> None:
        first = task_fingerprint(
            task=_TASK, objective=_OBJECTIVE, acceptance_criteria=_CRITERIA
        )
        second = task_fingerprint(
            task=_TASK,
            objective=_OBJECTIVE,
            acceptance_criteria=list(reversed(_CRITERIA)),
        )
        self.assertEqual(first, second)

    def test_different_shapes_differ(self) -> None:
        base = task_fingerprint(
            task=_TASK, objective=_OBJECTIVE, acceptance_criteria=_CRITERIA
        )
        other_task = task_fingerprint(
            task="写周报", objective=_OBJECTIVE, acceptance_criteria=_CRITERIA
        )
        other_criteria = task_fingerprint(
            task=_TASK, objective=_OBJECTIVE, acceptance_criteria=["覆盖全部 3 个项目"]
        )
        self.assertNotEqual(base, other_task)
        self.assertNotEqual(base, other_criteria)


class ProposalFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _temp_store(self)
        self.driver = SkillProposalDriver(store=self.store)
        self.ledger = SkillLedger(self.store)

    def test_first_verified_only_counts(self) -> None:
        outcome = _verify(self.driver)
        self.assertFalse(outcome.proposed)
        self.assertEqual(outcome.verified_count, 1)
        self.assertEqual(self.ledger.list_skills(status=STATUS_DRAFT), [])

    def test_second_verified_proposes_draft(self) -> None:
        _verify(self.driver)
        outcome = _verify(self.driver, event_id="evt-2")
        self.assertTrue(outcome.proposed)
        self.assertEqual(outcome.verified_count, 2)
        self.assertIsNotNone(outcome.record)
        self.assertTrue(outcome.user_text)
        self.assertIn(outcome.record.name, outcome.user_text)
        # The draft is inert: still a draft, not active.
        drafts = self.ledger.list_skills(status=STATUS_DRAFT)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].skill_id, outcome.record.skill_id)
        self.assertEqual(self.ledger.list_skills(status=STATUS_ACTIVE), [])
        # Proposal state recorded durably.
        state = self.store.get_skill_proposal_state(outcome.fingerprint)
        self.assertIsNotNone(state)
        self.assertEqual(state["proposal_state"], PROPOSAL_STATE_PROPOSED)
        self.assertEqual(state["proposal_skill_id"], outcome.record.skill_id)

    def test_third_verified_does_not_repropose(self) -> None:
        _verify(self.driver)
        second = _verify(self.driver, event_id="evt-2")
        third = _verify(self.driver, event_id="evt-3")
        self.assertTrue(second.proposed)
        self.assertFalse(third.proposed)
        self.assertEqual(third.verified_count, 3)
        self.assertEqual(len(self.ledger.list_skills(status=STATUS_DRAFT)), 1)

    def test_same_name_pending_draft_suppresses_proposal(self) -> None:
        # A hand-made (P1-3) draft with the name the proposal would use.
        existing = SkillRecord(
            skill_id="skill-handmade",
            name="汇总每日进展",
            status=STATUS_DRAFT,
            when_to_use="x",
            inputs_permissions="x",
            steps=("做日报",),
            verification_method="x",
            return_format="x",
            approval_boundary="x",
            failure_handling="x",
        )
        self.ledger.save_draft(existing)
        _verify(self.driver)
        outcome = _verify(self.driver, event_id="evt-2")
        self.assertFalse(outcome.proposed)
        self.assertIn("already pending", outcome.reason)
        # No second draft was created.
        self.assertEqual(len(self.ledger.list_skills(status=STATUS_DRAFT)), 1)

    def test_confirm_through_existing_skill_confirm_flow(self) -> None:
        _verify(self.driver)
        outcome = _verify(self.driver, event_id="evt-2")
        self.assertTrue(outcome.proposed)
        # The proposal draft lives in the work thread; the user confirms
        # with the existing skill_confirm phrase.
        owner = SkillOwner(store=self.store, ledger=SimpleNamespace())
        event = AgentEvent(
            event_id="confirm-evt",
            task="确认保存技能",
            payload={"skill_confirm": {"explicit": True}, "work_thread_id": "thread-1"},
        )
        self.assertTrue(owner.handles(event))
        reply = owner.handle(event)
        self.assertIn(outcome.record.name, reply)
        # Confirmed -> active -> referenceable by the existing matcher.
        matches = self.ledger.relevant_skills("汇总每日进展日报")
        self.assertTrue(any(skill.name == outcome.record.name for skill in matches))
        # A 3rd verified completion now refreshes to confirmed, no re-proposal.
        third = _verify(self.driver, event_id="evt-3")
        self.assertFalse(third.proposed)
        state = self.store.get_skill_proposal_state(third.fingerprint)
        self.assertEqual(state["proposal_state"], "confirmed")

    def test_decline_removes_draft_and_never_reproposes(self) -> None:
        _verify(self.driver)
        outcome = _verify(self.driver, event_id="evt-2")
        self.assertTrue(outcome.proposed)
        declined = self.driver.decline_proposal(outcome.record.skill_id)
        self.assertTrue(declined)
        # Nothing was saved: no active skill, draft gone.
        self.assertEqual(self.ledger.list_skills(status=STATUS_ACTIVE), [])
        self.assertEqual(self.ledger.list_skills(status=STATUS_DRAFT), [])
        self.assertIsNone(self.ledger.get_skill(outcome.record.skill_id))
        state = self.store.get_skill_proposal_state(outcome.fingerprint)
        self.assertEqual(state["proposal_state"], PROPOSAL_STATE_DECLINED)
        # A 3rd verified completion does not re-propose.
        third = _verify(self.driver, event_id="evt-3")
        self.assertFalse(third.proposed)
        self.assertEqual(self.ledger.list_skills(status=STATUS_DRAFT), [])

    def test_decline_unknown_skill_is_noop(self) -> None:
        self.assertFalse(self.driver.decline_proposal("skill-does-not-exist"))
        self.assertFalse(self.driver.decline_proposal(""))

    def test_driver_never_raises_into_the_gate(self) -> None:
        broken = SkillProposalDriver(store=object())
        outcome = broken.on_verified_completion(
            task=_TASK,
            objective=_OBJECTIVE,
            acceptance_criteria=_CRITERIA,
            response="x",
            thread_id="t",
            event_id="e",
        )
        self.assertFalse(outcome.proposed)
        self.assertIn("fail-closed", outcome.reason)


class PersistenceTests(unittest.TestCase):
    def test_counter_survives_store_reopen(self) -> None:
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(tmp) / "kernel.db"
        store = KernelStore(path)
        driver = SkillProposalDriver(store=store)
        first = _verify(driver)
        self.assertFalse(first.proposed)
        store.close()
        # "Restart": a new store on the same DB file keeps the count, so
        # the next verified completion is the 2nd and proposes.
        reopened = KernelStore(path)
        self.addCleanup(reopened.close)
        driver2 = SkillProposalDriver(store=reopened)
        second = _verify(driver2, event_id="evt-2")
        self.assertTrue(second.proposed)
        self.assertEqual(second.verified_count, 2)


class MessageAppendTests(unittest.TestCase):
    def _message_ledger(self, test: unittest.TestCase):
        tmp = test.enterContext(tempfile.TemporaryDirectory())
        path = Path(tmp) / "work.db"
        first = sqlite3.connect(path, check_same_thread=False)
        test.addCleanup(first.close)
        first.execute(
            "CREATE TABLE work_messages("
            "message_id TEXT PRIMARY KEY, thread_id TEXT, role TEXT, "
            "text TEXT, detail_json TEXT, created_at TEXT)"
        )
        first.commit()

        def _connect():
            return sqlite3.connect(path, check_same_thread=False)

        return SimpleNamespace(_connect=_connect, _lock=threading.RLock()), path

    def _read_messages(self, path: Path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute(
                "SELECT message_id, thread_id, text FROM work_messages"
            ).fetchall()
        finally:
            conn.close()

    def test_proposal_message_appended_to_thread(self) -> None:
        ledger, path = self._message_ledger(self)
        written = append_proposal_message(
            ledger, thread_id="thread-1", event_id="evt-9", text="要不要存成技能？"
        )
        self.assertTrue(written)
        rows = self._read_messages(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "evt-9-skill-proposal")
        self.assertEqual(rows[0][1], "thread-1")
        self.assertIn("存成技能", rows[0][2])
        # Idempotent on retry: same message id is not duplicated.
        append_proposal_message(
            ledger, thread_id="thread-1", event_id="evt-9", text="要不要存成技能？"
        )
        self.assertEqual(len(self._read_messages(path)), 1)

    def test_entry_point_writes_draft_and_message(self) -> None:
        store = _temp_store(self)
        ledger, path = self._message_ledger(self)
        kwargs = dict(
            store=store,
            ledger=ledger,
            task=_TASK,
            objective=_OBJECTIVE,
            acceptance_criteria=_CRITERIA,
            response="日报已生成。",
            thread_id="thread-1",
            event_id="evt-1",
        )
        first = propose_skill_for_verified_completion(**kwargs)
        self.assertFalse(first.proposed)
        second = propose_skill_for_verified_completion(
            **{**kwargs, "event_id": "evt-2"}
        )
        self.assertTrue(second.proposed)
        rows = self._read_messages(path)
        self.assertEqual(len(rows), 1)
        self.assertIn("确认保存技能", rows[0][2])
        drafts = SkillLedger(store).list_skills(status=STATUS_DRAFT)
        self.assertEqual(len(drafts), 1)


if __name__ == "__main__":
    unittest.main()

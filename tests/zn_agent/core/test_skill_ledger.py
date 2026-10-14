from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import (
    AgentEvent,
    EventOutcome,
    EventStatus,
    ExecutionPath,
    WorkingState,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.skill_ledger import (
    SKILL_FIELDS,
    SkillLedger,
    SkillOwner,
    SkillRecord,
    build_skill_draft,
    validate_for_activation,
)
from zn_agent.core.skill_request import (
    parse_skill_confirm,
    parse_skill_reference,
    parse_skill_save_request,
)
from zn_agent.core.store import KernelStore
from zn_agent.core.team_work_owner import TeamWorkOwner


def _temp_store(test: unittest.TestCase) -> KernelStore:
    tmp = test.enterContext(tempfile.TemporaryDirectory())
    return KernelStore(Path(tmp) / "kernel.db")


def _completed_event(
    store: KernelStore,
    *,
    event_id: str,
    thread_id: str,
    task: str,
    response: str = "done",
) -> AgentEvent:
    event = AgentEvent(
        event_id=event_id,
        task=task,
        payload={"work_thread_id": thread_id},
    )
    store.enqueue_event(event)
    store.finish_event(event_id, success=True)
    store.save_event_outcome(
        EventOutcome(
            event_id=event_id,
            success=True,
            execution_path=ExecutionPath.BODY,
            response=response,
        )
    )
    return event


class SkillLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _temp_store(self)
        self.ledger = SkillLedger(self.store)

    def test_draft_has_all_seven_fields(self) -> None:
        record = build_skill_draft(
            {
                "task": "汇总昨天的进展",
                "objective": "汇总昨天的进展并输出摘要",
                "acceptance_criteria": ["摘要覆盖全部已完成任务"],
                "response": "汇总完成，共 3 项。",
                "event_id": "evt-1",
                "thread_id": "thread-1",
            }
        )
        self.assertEqual(record.status, "draft")
        for key in SKILL_FIELDS:
            value = getattr(record, key)
            self.assertTrue(value, f"{key} must be filled")
        self.assertEqual(validate_for_activation(record), [])

    def test_missing_approval_boundary_refuses_confirm(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        record.approval_boundary = ""
        self.assertIn("approval_boundary must not be empty", validate_for_activation(record))
        self.ledger.save_draft(record)
        with self.assertRaises(ValueError) as caught:
            self.ledger.confirm(record.skill_id)
        self.assertIn("approval_boundary", str(caught.exception))
        self.assertEqual(self.ledger.get_skill(record.skill_id).status, "draft")

    def test_draft_does_not_take_effect_until_confirmed(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        self.ledger.save_draft(record)
        self.assertEqual(self.ledger.relevant_skills("汇总昨天的进展"), [])
        self.ledger.confirm(record.skill_id)
        matched = self.ledger.relevant_skills("请帮我汇总昨天的进展")
        self.assertEqual([skill.skill_id for skill in matched], [record.skill_id])

    def test_unrelated_query_does_not_match(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        self.ledger.save_draft(record)
        self.ledger.confirm(record.skill_id)
        self.assertEqual(self.ledger.relevant_skills("帮我订一张机票"), [])

    def test_delete_skill_leaves_work_records_untouched(self) -> None:
        _completed_event(
            self.store, event_id="evt-1", thread_id="t1", task="汇总昨天的进展"
        )
        record = build_skill_draft({"task": "汇总昨天的进展"})
        self.ledger.save_draft(record)
        self.ledger.confirm(record.skill_id)
        self.ledger.delete_skill(record.skill_id)
        self.assertIsNone(self.ledger.get_skill(record.skill_id))
        outcome = self.store.get_event_outcome("evt-1")
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.success)
        event = self.store.get_event("evt-1")
        self.assertEqual(event.status, EventStatus.COMPLETED)


class SkillRequestTests(unittest.TestCase):
    def test_save_request_with_name_hint(self) -> None:
        parsed = parse_skill_save_request("把刚才的任务存成技能，命名为周报汇总")
        self.assertEqual(parsed, {"name_hint": "周报汇总"})

    def test_save_request_without_name_hint(self) -> None:
        self.assertEqual(
            parse_skill_save_request("把刚才的任务存成技能"),
            {"name_hint": None},
        )

    def test_how_to_question_is_not_a_save_request(self) -> None:
        self.assertIsNone(parse_skill_save_request("技能怎么存成技能？"))
        self.assertIsNone(parse_skill_save_request("如何把任务存成技能"))

    def test_plain_task_is_not_a_save_request(self) -> None:
        self.assertIsNone(parse_skill_save_request("帮我写个脚本"))

    def test_reference_parses_name_and_remainder(self) -> None:
        parsed = parse_skill_reference("/周报汇总 帮我汇总昨天的进展")
        self.assertEqual(
            parsed, {"name": "周报汇总", "remainder": "帮我汇总昨天的进展"}
        )

    def test_bare_slash_name_is_not_a_reference(self) -> None:
        self.assertIsNone(parse_skill_reference("/周报汇总"))
        self.assertIsNone(parse_skill_reference("帮我写个脚本"))

    def test_confirm_phrases(self) -> None:
        self.assertTrue(parse_skill_confirm("确认保存技能"))
        self.assertTrue(parse_skill_confirm("确认存成技能"))
        # Bare "确认" is owner-level (single pending draft), not a parser match.
        self.assertFalse(parse_skill_confirm("确认"))
        self.assertFalse(parse_skill_confirm("好的"))


class SkillOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _temp_store(self)
        self.ledger = SimpleNamespace(
            work_item_for_event=lambda event_id: None,
        )
        self.owner = SkillOwner(store=self.store, ledger=self.ledger)

    def _save_event(self, task: str, *, payload_extra: dict | None = None) -> AgentEvent:
        payload = {"work_thread_id": "t1", **(payload_extra or {})}
        return AgentEvent(event_id="cur", task=task, payload=payload)

    def test_save_without_completed_work_fails_closed(self) -> None:
        event = self._save_event(
            "把刚才的任务存成技能",
            payload_extra={"skill_save_request": {"name_hint": None}},
        )
        with self.assertRaises(ValueError) as caught:
            self.owner.handle(event)
        self.assertIn("没有已完成的任务", str(caught.exception))

    def test_save_builds_draft_from_last_completed_work(self) -> None:
        _completed_event(
            self.store,
            event_id="evt-1",
            thread_id="t1",
            task="汇总昨天的进展",
            response="汇总完成，共 3 项。",
        )
        event = self._save_event(
            "把刚才的任务存成技能",
            payload_extra={"skill_save_request": {"name_hint": None}},
        )
        response = self.owner.handle(event)
        self.assertIn("技能草稿", response)
        self.assertIn("未入库", response)
        drafts = self.owner.skills.list_skills(status="draft")
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].source_event_id, "evt-1")
        self.assertEqual(drafts[0].status, "draft")

    def test_confirm_without_draft_fails_closed(self) -> None:
        event = self._save_event(
            "确认保存技能", payload_extra={"skill_confirm": {"explicit": True}}
        )
        with self.assertRaises(ValueError) as caught:
            self.owner.handle(event)
        self.assertIn("没有待确认", str(caught.exception))

    def test_confirm_activates_latest_draft(self) -> None:
        _completed_event(
            self.store, event_id="evt-1", thread_id="t1", task="汇总昨天的进展"
        )
        save = self._save_event(
            "把刚才的任务存成技能",
            payload_extra={"skill_save_request": {"name_hint": "周报汇总"}},
        )
        self.owner.handle(save)
        event = self._save_event(
            "确认保存技能", payload_extra={"skill_confirm": {"explicit": True}}
        )
        response = self.owner.handle(event)
        self.assertIn("周报汇总", response)
        self.assertIn("已确认入库", response)
        record = self.owner.skills.get_skill_by_name("周报汇总", status="active")
        self.assertIsNotNone(record)

    def test_bare_confirm_only_with_pending_draft(self) -> None:
        bare = self._save_event("确认")
        self.assertFalse(self.owner.handles(bare))
        _completed_event(
            self.store, event_id="evt-1", thread_id="t1", task="汇总昨天的进展"
        )
        save = self._save_event(
            "把刚才的任务存成技能",
            payload_extra={"skill_save_request": {"name_hint": None}},
        )
        self.owner.handle(save)
        self.assertTrue(self.owner.handles(bare))
        response = self.owner.handle(bare)
        self.assertIn("已确认入库", response)

    def test_reference_unknown_skill_fails_closed(self) -> None:
        event = self._save_event(
            "汇总昨天的进展",
            payload_extra={"skill_reference": {"name": "不存在的技能"}},
        )
        with self.assertRaises(ValueError) as caught:
            self.owner.handle(event)
        self.assertIn("不存在或未确认入库", str(caught.exception))

    def test_reference_draft_does_not_validate(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        self.owner.skills.save_draft(record)
        event = self._save_event(
            "汇总昨天的进展",
            payload_extra={"skill_reference": {"name": record.name}},
        )
        with self.assertRaises(ValueError):
            self.owner.handle(event)

    def test_reference_active_skill_falls_through(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        self.owner.skills.save_draft(record)
        self.owner.skills.confirm(record.skill_id)
        event = self._save_event(
            "汇总昨天的进展",
            payload_extra={"skill_reference": {"name": record.name}},
        )
        self.assertTrue(self.owner.handles(event))
        self.assertIsNone(self.owner.handle(event))


class SkillResidentHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="skill-route", title="Skill Route")
        self.ledger.attach_workspace("skill-route", self.workspace, name="Workspace")

    def tearDown(self) -> None:
        self.resident.store.close()
        self.temp.cleanup()

    def _start(self, task: str, **payload_extra) -> AgentEvent:
        _, event = self.ledger.start("skill-route", task)
        event.payload.update(payload_extra)
        return event

    def _complete_prior(self, task: str, *, response: str = "汇总完成，共 3 项。") -> None:
        _, prior = self.ledger.start("skill-route", task)
        self.resident.store.finish_event(prior.event_id, success=True)
        self.resident.store.save_event_outcome(
            EventOutcome(
                event_id=prior.event_id,
                success=True,
                execution_path=ExecutionPath.BODY,
                response=response,
            )
        )

    def _call(self, event: AgentEvent):
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_deliberation",
            next_action="deliberate",
            data={},
        )
        return self.resident._deliberation_step(
            event,
            state,
            readiness=None,
            learning_evidence=[],
            thought=None,
        )

    def test_hook_saves_draft_without_model_call(self) -> None:
        self._complete_prior("汇总昨天的进展")
        event = self._start(
            "把刚才的任务存成技能",
            skill_save_request={"name_hint": None},
        )
        result = self._call(event)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertIn("技能草稿", result.response)
        drafts = SkillLedger(self.resident.store).list_skills(status="draft")
        self.assertEqual(len(drafts), 1)

    def test_hook_confirms_draft(self) -> None:
        self._complete_prior("汇总昨天的进展")
        save = self._start(
            "把刚才的任务存成技能",
            skill_save_request={"name_hint": "周报汇总"},
        )
        self.assertTrue(self._call(save).success)
        # Mirror the terminal transition run_once would publish.
        self.resident.store.finish_event(save.event_id, success=True)
        self.resident.store.save_event_outcome(
            EventOutcome(
                event_id=save.event_id,
                success=True,
                execution_path=ExecutionPath.BODY,
                response="draft saved",
            )
        )
        confirm = self._start(
            "确认保存技能", skill_confirm={"explicit": True}
        )
        result = self._call(confirm)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertIn("已确认入库", result.response)
        record = SkillLedger(self.resident.store).get_skill_by_name(
            "周报汇总", status="active"
        )
        self.assertIsNotNone(record)

    def test_hook_reference_unknown_skill_fails_closed(self) -> None:
        event = self._start(
            "汇总昨天的进展",
            skill_reference={"name": "不存在的技能"},
        )
        result = self._call(event)
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertIn("不存在或未确认入库", result.reason)

    def test_cognition_request_injects_referenced_skill(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        ledger = SkillLedger(self.resident.store)
        ledger.save_draft(record)
        ledger.confirm(record.skill_id)
        event = self._start(
            "汇总昨天的进展",
            skill_reference={"name": record.name},
        )
        impasse = SimpleNamespace(impasse_id="imp-1", local_failure="")
        request = self.resident._build_cognition_request(event, impasse, ())
        self.assertIn(record.name, request.question)
        self.assertIn(record.approval_boundary, request.question)

    def test_team_specialist_brief_carries_matching_skill(self) -> None:
        record = build_skill_draft({"task": "汇总昨天的进展"})
        ledger = SkillLedger(self.resident.store)
        ledger.save_draft(record)
        ledger.confirm(record.skill_id)
        owner = TeamWorkOwner(
            ledger=None, memory=SimpleNamespace(store=self.resident.store)
        )
        block = owner._skills_block_for("请帮我汇总昨天的进展")
        self.assertIn(record.name, block)
        self.assertIn(record.approval_boundary, block)

    def test_team_specialist_brief_empty_without_skills(self) -> None:
        owner = TeamWorkOwner(
            ledger=None, memory=SimpleNamespace(store=self.resident.store)
        )
        self.assertEqual(owner._skills_block_for("请帮我汇总昨天的进展"), "")
        owner_no_store = TeamWorkOwner(ledger=None, memory=SimpleNamespace())
        self.assertEqual(
            owner_no_store._skills_block_for("请帮我汇总昨天的进展"), ""
        )


class SkillDaemonIngressTests(unittest.TestCase):
    def test_work_start_tags_skill_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )
            try:
                thread = server.work.create_thread(title="Skill ingress")
                started = server.handle(
                    {
                        "id": "start-skill-ref",
                        "method": "work_start",
                        "params": {
                            "thread_id": thread.thread_id,
                            "task": "/周报汇总 帮我汇总昨天的进展",
                            "kind": "desktop_user_event",
                        },
                    }
                )
                self.assertTrue(started["ok"])
                event = resident.store.get_event(
                    started["result"]["progress"]["event_id"]
                )
                self.assertEqual(event.task, "帮我汇总昨天的进展")
                self.assertEqual(event.payload["skill_reference"]["name"], "周报汇总")

                started = server.handle(
                    {
                        "id": "start-skill-save",
                        "method": "work_start",
                        "params": {
                            "thread_id": thread.thread_id,
                            "task": "把刚才的任务存成技能",
                            "kind": "desktop_user_event",
                        },
                    }
                )
                self.assertTrue(started["ok"])
                event = resident.store.get_event(
                    started["result"]["progress"]["event_id"]
                )
                self.assertEqual(
                    event.payload["skill_save_request"], {"name_hint": None}
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

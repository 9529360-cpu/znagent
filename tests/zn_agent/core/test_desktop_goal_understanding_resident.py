from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser_goal_understanding_resident import (
    _validated_desktop_goal_proposal,
)
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.desktop_task_goal import (
    DESKTOP_TASK_GOAL_KIND,
    explicit_desktop_task_goal_hint,
)
from zn_agent.core.models import AgentEvent, ModelRoute
from tests.zn_agent.core.test_natural_named_desktop_input_work import (
    NaturalNamedDesktopInputWorkTests,
)


_PROPOSAL = {
    "kind": DESKTOP_TASK_GOAL_KIND,
    "source_name_hint": "订单",
    "input_name": "订单编号",
    "button_name": "查找记录",
    "expected_title": None,
    "source_modified_yesterday": True,
}

_PARAPHRASES = (
    "找到昨天那份订单资料，把里面的编号填到我现在开的软件里，帮我把对应记录查出来并确认结果出来了。",
    "昨天改过的那个订单文件里有个编号，用它在这个程序里把对应记录找出来。",
    "帮我拿昨天那个订单资料里的编号，在我现在开的软件里查一下，最后确认记录页面出来了。",
    "昨天下午那份订单资料里留了一个编号，我现在这个程序要用它找到那条记录，办完帮我确认一下。",
)


class _DesktopGoalProposalResource:
    def __init__(self, proposal=None):
        self.proposal = dict(proposal or _PROPOSAL)
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        return CognitiveIncrement(
            text=json.dumps(self.proposal, ensure_ascii=False),
            provider="test-cognition",
            model="bounded-language-fixture",
        )


def _enable_language_resource(resident, resource: _DesktopGoalProposalResource) -> None:
    resident.kernel.reconfigure_resources(
        routes=[
            ModelRoute(
                route_id="test-desktop-language-understanding",
                provider="fixture",
                model="bounded-language-fixture",
                capabilities={"language_understanding": 1.0, "general": 0.8},
            )
        ],
        worker_factory=CognitiveResourceWorkerFactory(
            resource_builder=lambda _route: resource,
        ),
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )


class DesktopGoalUnderstandingTests(unittest.TestCase):
    def test_desktop_proposal_is_semantic_only_and_rejects_authority_fields(self) -> None:
        task = _PARAPHRASES[0]
        accepted = _validated_desktop_goal_proposal(
            task,
            json.dumps(_PROPOSAL, ensure_ascii=False),
        )
        self.assertEqual(accepted, _PROPOSAL)

        for forbidden in (
            "workspace_path",
            "file_path",
            "process_name",
            "window_title",
            "runtime_id",
            "automation_id",
            "x_fraction",
            "authority",
            "side_effect_complete",
            "completed",
            "steps",
        ):
            with self.subTest(forbidden=forbidden):
                value = dict(_PROPOSAL)
                value[forbidden] = "model-minted"
                self.assertIsNone(
                    _validated_desktop_goal_proposal(
                        task,
                        json.dumps(value, ensure_ascii=False),
                    )
                )

        invented_source = dict(_PROPOSAL, source_name_hint="客户密码")
        self.assertIsNone(
            _validated_desktop_goal_proposal(
                task,
                json.dumps(invented_source, ensure_ascii=False),
            )
        )
        invented_completion = dict(_PROPOSAL, expected_title="模型声称已经完成")
        self.assertIsNone(
            _validated_desktop_goal_proposal(
                task,
                json.dumps(invented_completion, ensure_ascii=False),
            )
        )

    def test_four_non_regex_paraphrases_reach_same_resident_goal_and_real_action_loop(self) -> None:
        for index, task in enumerate(_PARAPHRASES):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                workspace = base / "authorized"
                workspace.mkdir()
                source = workspace / "订单资料.txt"
                source.write_text(f"ORDER-{4100 + index}", encoding="utf-8")
                NaturalNamedDesktopInputWorkTests._stamp_yesterday(source)

                hint_event = AgentEvent(
                    event_id=f"evt-paraphrase-{index}",
                    kind="desktop_user_event",
                    task=task,
                    payload={"workspace_path": str(workspace)},
                )
                self.assertIsNone(
                    explicit_desktop_task_goal_hint(hint_event),
                    "acceptance paraphrase must not be rescued by the deterministic regex fast path",
                )

                resident, world, body, controls, ledger = NaturalNamedDesktopInputWorkTests._setup(
                    base,
                    workspace,
                    f"desktop-language-{index}",
                )
                cognition = _DesktopGoalProposalResource()
                _enable_language_resource(resident, cognition)
                try:
                    _, run = ledger.submit(f"desktop-language-{index}", task)

                    self.assertTrue(run.success, run)
                    self.assertEqual(run.model_invocations, 1)
                    self.assertEqual(cognition.calls, 1)
                    self.assertEqual(body.keyboard_calls, [f"ORDER-{4100 + index}"])
                    self.assertEqual(body.focus_click_count, 1)
                    self.assertEqual(body.submit_click_count, 1)
                    self.assertEqual(world.title, "查询结果")
                    self.assertGreaterEqual(controls.edit_calls, 3)
                    self.assertGreaterEqual(controls.button_calls, 2)

                    persisted = resident.store.get_event(run.event.event_id)
                    self.assertIsNotNone(persisted)
                    self.assertEqual(persisted.payload.get("desktop_task_goal"), _PROPOSAL)
                    understanding = persisted.payload.get("_resident_goal_understanding") or {}
                    self.assertEqual(understanding.get("source"), "bounded_cognition_proposal")
                    self.assertEqual(understanding.get("goal_kind"), DESKTOP_TASK_GOAL_KIND)
                finally:
                    resident.store.close()

    def test_model_understood_goal_still_fails_closed_on_ambiguous_workspace_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            first = workspace / "订单-A.txt"
            second = workspace / "订单-B.txt"
            first.write_text("ORDER-A", encoding="utf-8")
            second.write_text("ORDER-B", encoding="utf-8")
            NaturalNamedDesktopInputWorkTests._stamp_yesterday(first)
            NaturalNamedDesktopInputWorkTests._stamp_yesterday(second)

            resident, _, body, controls, ledger = NaturalNamedDesktopInputWorkTests._setup(
                base,
                workspace,
                "desktop-language-ambiguous",
            )
            cognition = _DesktopGoalProposalResource()
            _enable_language_resource(resident, cognition)
            try:
                _, run = ledger.submit("desktop-language-ambiguous", _PARAPHRASES[1])

                self.assertFalse(run.success)
                self.assertEqual(run.model_invocations, 1)
                self.assertEqual(cognition.calls, 1)
                self.assertEqual(body.focus_click_count, 0)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.submit_click_count, 0)
                self.assertEqual(controls.edit_calls, 0)
                self.assertIn("ambiguous", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

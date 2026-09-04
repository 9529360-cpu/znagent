from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.browser_goal_understanding_resident import (
    _validated_desktop_goal_proposal,
    _validated_desktop_grounding_selection,
)
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.desktop_task_goal import (
    DESKTOP_TASK_GOAL_KIND,
    explicit_desktop_task_goal_hint,
)
from zn_agent.core.models import AgentEvent, ModelRoute, utc_now
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
_SEMANTIC_PROPOSAL = {
    "kind": DESKTOP_TASK_GOAL_KIND,
    "source_name_hint": "订单",
    "input_name": "用于识别对应订单的字段",
    "button_name": "执行查找对应记录的操作",
    "expected_title": None,
    "source_modified_yesterday": True,
}
_GROUNDING = {
    "status": "selected",
    "input_name": "订单编号",
    "button_name": "查找",
}
_PARAPHRASES = (
    "找到昨天那份订单资料，把里面的编号填到我现在开的软件里，帮我把对应记录查出来并确认结果出来了。",
    "昨天改过的那个订单文件里有个编号，用它在这个程序里把对应记录找出来。",
    "帮我拿昨天那个订单资料里的编号，在我现在开的软件里查一下，最后确认记录页面出来了。",
    "昨天下午那份订单资料里留了一个编号，我现在这个程序要用它找到那条记录，办完帮我确认一下。",
)


def _candidate(
    *,
    name: str,
    control_type: int,
    tail: int,
) -> NamedAutomationControlObservation:
    return NamedAutomationControlObservation(
        runtime_id=(42, 330, tail),
        process_id=330,
        process_name="customerapp.exe",
        name=name,
        control_type=control_type,
        class_name="TextBox" if control_type == 50004 else "Button",
        is_enabled=True,
        is_offscreen=False,
        left=100 + tail,
        top=100,
        right=300 + tail,
        bottom=140,
        center_x_fraction=0.30 if control_type == 50004 else 0.50,
        center_y_fraction=0.30 if control_type == 50004 else 0.4625,
        captured_at=utc_now(),
        is_keyboard_focusable=control_type == 50004,
        is_password=False,
        is_value_pattern_available=control_type == 50004,
        value_is_read_only=False if control_type == 50004 else None,
        source="test-fresh-grounding-candidate",
    )


def _install_candidates(controls, *, duplicate_order_id: bool = False) -> None:
    def edits(*, process_id: int, process_name: str):
        assert process_id == 330
        assert process_name == "customerapp.exe"
        values = [
            _candidate(name="客户名称", control_type=50004, tail=31),
            _candidate(name="订单编号", control_type=50004, tail=32),
            _candidate(name="备注", control_type=50004, tail=33),
        ]
        if duplicate_order_id:
            values.append(_candidate(name="订单编号", control_type=50004, tail=34))
        return tuple(values)

    def buttons(*, process_id: int, process_name: str):
        assert process_id == 330
        assert process_name == "customerapp.exe"
        return (
            _candidate(name="查找", control_type=50000, tail=41),
            _candidate(name="取消", control_type=50000, tail=42),
        )

    controls.list_safe_edits = edits
    controls.list_buttons = buttons


class _DesktopGoalProposalResource:
    def __init__(self, proposal=None, *, grounding=None):
        self.proposal = dict(proposal or _PROPOSAL)
        self.grounding = dict(grounding or _GROUNDING)
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        value = self.grounding if "Fresh Edit names:" in question else self.proposal
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
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

    def test_grounding_accepts_only_uniquely_observed_names(self) -> None:
        edits = ("客户名称", "订单编号", "备注")
        buttons = ("查找", "取消")
        self.assertEqual(
            _validated_desktop_grounding_selection(
                json.dumps(_GROUNDING, ensure_ascii=False),
                edit_names=edits,
                button_names=buttons,
            ),
            ("订单编号", "查找"),
        )
        forged = dict(_GROUNDING, input_name="模型发明字段")
        self.assertIsNone(
            _validated_desktop_grounding_selection(
                json.dumps(forged, ensure_ascii=False),
                edit_names=edits,
                button_names=buttons,
            )
        )
        self.assertIsNone(
            _validated_desktop_grounding_selection(
                json.dumps(_GROUNDING, ensure_ascii=False),
                edit_names=("订单编号", "订单编号"),
                button_names=buttons,
            )
        )
        authority = dict(_GROUNDING, runtime_id=[42, 330, 9])
        self.assertIsNone(
            _validated_desktop_grounding_selection(
                json.dumps(authority, ensure_ascii=False),
                edit_names=edits,
                button_names=buttons,
            )
        )

    def test_non_exact_user_goal_is_grounded_from_fresh_desktop_candidates(self) -> None:
        task = "昨天那个订单文件里有编号，在我现在开的软件里帮我把对应记录找出来。"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text("ORDER-7788", encoding="utf-8")
            NaturalNamedDesktopInputWorkTests._stamp_yesterday(source)

            hint_event = AgentEvent(
                event_id="evt-semantic-grounding",
                kind="desktop_user_event",
                task=task,
                payload={"workspace_path": str(workspace)},
            )
            self.assertIsNone(explicit_desktop_task_goal_hint(hint_event))

            resident, world, body, controls, ledger = NaturalNamedDesktopInputWorkTests._setup(
                base,
                workspace,
                "semantic-grounding",
            )
            _install_candidates(controls)
            cognition = _DesktopGoalProposalResource(proposal=_SEMANTIC_PROPOSAL)
            _enable_language_resource(resident, cognition)
            try:
                _, run = ledger.submit("semantic-grounding", task)

                self.assertTrue(run.success, run)
                self.assertEqual(run.model_invocations, 2)
                self.assertEqual(cognition.calls, 2)
                self.assertEqual(body.keyboard_calls, ["ORDER-7788"])
                self.assertEqual(body.focus_click_count, 1)
                self.assertEqual(body.submit_click_count, 1)
                self.assertEqual(world.title, "查询结果")

                persisted = resident.store.get_event(run.event.event_id)
                self.assertIsNotNone(persisted)
                self.assertEqual(
                    persisted.payload.get("_resident_desktop_semantic_goal"),
                    _SEMANTIC_PROPOSAL,
                )
                grounded = persisted.payload.get("desktop_task_goal") or {}
                self.assertEqual(grounded.get("input_name"), "订单编号")
                self.assertEqual(grounded.get("button_name"), "查找")
                grounding_question = cognition.questions[1]
                self.assertIn("客户名称", grounding_question)
                self.assertIn("订单编号", grounding_question)
                self.assertIn("备注", grounding_question)
                self.assertIn("查找", grounding_question)
                self.assertIn("取消", grounding_question)
                self.assertNotIn("(42, 330", grounding_question)
            finally:
                resident.store.close()

    def test_duplicate_equally_named_edit_fails_closed_before_desktop_side_effect(self) -> None:
        task = "昨天那个订单文件里有编号，在我现在开的软件里帮我把对应记录找出来。"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text("ORDER-8899", encoding="utf-8")
            NaturalNamedDesktopInputWorkTests._stamp_yesterday(source)

            resident, _, body, controls, ledger = NaturalNamedDesktopInputWorkTests._setup(
                base,
                workspace,
                "semantic-grounding-ambiguous",
            )
            _install_candidates(controls, duplicate_order_id=True)
            cognition = _DesktopGoalProposalResource(proposal=_SEMANTIC_PROPOSAL)
            _enable_language_resource(resident, cognition)
            try:
                _, run = ledger.submit("semantic-grounding-ambiguous", task)

                self.assertFalse(run.success)
                self.assertEqual(cognition.calls, 2)
                self.assertEqual(body.focus_click_count, 0)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.submit_click_count, 0)
                self.assertIn("ambiguous", run.reason)
            finally:
                resident.store.close()

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
                _install_candidates(controls)
                cognition = _DesktopGoalProposalResource()
                _enable_language_resource(resident, cognition)
                try:
                    _, run = ledger.submit(f"desktop-language-{index}", task)

                    self.assertTrue(run.success, run)
                    self.assertEqual(run.model_invocations, 2)
                    self.assertEqual(cognition.calls, 2)
                    self.assertEqual(body.keyboard_calls, [f"ORDER-{4100 + index}"])
                    self.assertEqual(body.focus_click_count, 1)
                    self.assertEqual(body.submit_click_count, 1)
                    self.assertEqual(world.title, "查询结果")
                    self.assertGreaterEqual(controls.edit_calls, 3)
                    self.assertGreaterEqual(controls.button_calls, 2)

                    persisted = resident.store.get_event(run.event.event_id)
                    self.assertIsNotNone(persisted)
                    grounded = dict(_PROPOSAL)
                    grounded["input_name"] = "订单编号"
                    grounded["button_name"] = "查找"
                    self.assertEqual(persisted.payload.get("desktop_task_goal"), grounded)
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
            _install_candidates(controls)
            cognition = _DesktopGoalProposalResource()
            _enable_language_resource(resident, cognition)
            try:
                _, run = ledger.submit("desktop-language-ambiguous", _PARAPHRASES[1])

                self.assertFalse(run.success)
                self.assertEqual(run.model_invocations, 2)
                self.assertEqual(cognition.calls, 2)
                self.assertEqual(body.focus_click_count, 0)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.submit_click_count, 0)
                self.assertGreaterEqual(
                    controls.edit_calls,
                    1,
                    "read-only UIA semantic sensing is allowed before the workspace ambiguity is surfaced",
                )
                self.assertIn("ambiguous", run.reason)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

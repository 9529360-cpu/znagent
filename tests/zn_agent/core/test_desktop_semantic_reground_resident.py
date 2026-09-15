from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser_goal_understanding_resident import (
    _DESKTOP_SEMANTIC_GOAL_KEY,
    _DESKTOP_SEMANTIC_REGROUND_KEY,
)
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.desktop_task_goal import DESKTOP_TASK_GOAL_KIND
from zn_agent.core.models import ModelRoute
from tests.zn_agent.core.test_desktop_goal_understanding_resident import (
    _SEMANTIC_PROPOSAL,
    _candidate,
)
from tests.zn_agent.core import test_natural_named_desktop_input_work as _natural_named_desktop_input_work


class _RegroundResource:
    def __init__(self):
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        return CognitiveIncrement(
            text=json.dumps(
                {
                    "status": "selected",
                    "input_name": "订单号",
                    "button_name": "查询订单",
                },
                ensure_ascii=False,
            ),
            provider="test-cognition",
            model="bounded-language-fixture",
        )


class DesktopSemanticRegroundTests(unittest.TestCase):
    def test_exact_name_loss_reuses_semantic_goal_and_fresh_candidates(self) -> None:
        task = "昨天那个订单文件里有编号，在我现在开的软件里帮我把对应记录找出来。"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text("ORDER-REGROUND-1", encoding="utf-8")
            _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._stamp_yesterday(source)
            resident, _, body, controls, ledger = _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._setup(
                base,
                workspace,
                "desktop-semantic-reground",
            )
            resource = _RegroundResource()
            resident.kernel.reconfigure_resources(
                routes=[
                    ModelRoute(
                        route_id="test-desktop-semantic-reground",
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

            def find_edit(*, process_id: int, process_name: str, name: str):
                if name == "订单编号":
                    raise RuntimeError("old semantic label is gone")
                if name != "订单号":
                    raise RuntimeError("unexpected edit name")
                return _candidate(name="订单号", control_type=50004, tail=51)

            def find_button(*, process_id: int, process_name: str, name: str):
                if name == "查找":
                    raise RuntimeError("old semantic label is gone")
                if name != "查询订单":
                    raise RuntimeError("unexpected button name")
                return _candidate(name="查询订单", control_type=50000, tail=61)

            controls.find_unique_edit = find_edit
            controls.find_unique_button = find_button
            controls.list_safe_edits = lambda **_: (
                _candidate(name="客户名称", control_type=50004, tail=50),
                _candidate(name="订单号", control_type=50004, tail=51),
                _candidate(name="备注", control_type=50004, tail=52),
            )
            controls.list_buttons = lambda **_: (
                _candidate(name="查询订单", control_type=50000, tail=61),
                _candidate(name="取消", control_type=50000, tail=62),
            )

            try:
                _, event = ledger.start(
                    "desktop-semantic-reground",
                    task,
                    payload={"model_policy": "on_demand"},
                )
                event.payload = dict(event.payload or {})
                event.payload[_DESKTOP_SEMANTIC_GOAL_KEY] = dict(_SEMANTIC_PROPOSAL)
                event.payload["desktop_task_goal"] = {
                    "kind": DESKTOP_TASK_GOAL_KIND,
                    "source_name_hint": "订单",
                    "input_name": "订单编号",
                    "button_name": "查找",
                    "expected_title": None,
                    "source_modified_yesterday": True,
                }
                event.payload["_resident_goal_understanding"] = {
                    "source": "bounded_cognition_proposal",
                    "goal_id": "goal-original",
                    "goal_kind": DESKTOP_TASK_GOAL_KIND,
                    "model_invocations": 2,
                    "route_id": "fixture",
                }
                resident.store._save_event(event)
                state = resident.store.get_working_state()
                state.current_event_id = event.event_id
                state.stage = "native_investigation"
                resident.store.save_working_state(state)

                result = resident._desktop_task_investigation(
                    event,
                    state,
                    readiness=None,
                    thought=None,
                )

                self.assertIsNone(result)
                persisted = resident.store.get_event(event.event_id)
                self.assertEqual(
                    persisted.payload[_DESKTOP_SEMANTIC_GOAL_KEY],
                    _SEMANTIC_PROPOSAL,
                )
                grounded = persisted.payload["desktop_task_goal"]
                self.assertEqual(grounded["input_name"], "订单号")
                self.assertEqual(grounded["button_name"], "查询订单")
                self.assertEqual(resource.calls, 1)
                self.assertIn("订单号", resource.questions[0])
                self.assertIn("查询订单", resource.questions[0])
                self.assertNotIn("RuntimeId", resource.questions[0].split("Fresh Edit names:", 1)[1])
                saved = resident.store.get_working_state()
                reground = saved.data.get(_DESKTOP_SEMANTIC_REGROUND_KEY) or {}
                self.assertEqual(reground.get("count"), 1)
                self.assertEqual(
                    (persisted.payload.get("_resident_goal_understanding") or {}).get(
                        "model_invocations"
                    ),
                    3,
                )
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.focus_click_count, 0)
                self.assertEqual(body.submit_click_count, 0)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.browser_file_desktop_handoff_behavior import (
    _STATE_KEY,
    _extract_customer_fact,
    _request,
    _roll_forward_verified_file,
    _select_desktop_names,
)


class BrowserFileDesktopHandoffBehaviorTests(unittest.TestCase):
    @staticmethod
    def _event(task: str, *, model_policy: str = "never"):
        return SimpleNamespace(
            event_id="evt-e2e24-core",
            task=task,
            kind="desktop_user_event",
            priority=0,
            payload={
                "workspace_path": "/authorized/workspace",
                "model_policy": model_policy,
            },
        )

    def test_natural_request_keeps_only_semantic_file_hint(self) -> None:
        event = self._event(
            "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
            "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
        )
        request = _request(event)
        self.assertEqual(
            request,
            {
                "workspace_path": "/authorized/workspace",
                "file_hint": "客户状态",
                "status_anchor": "需跟进",
            },
        )

    def test_structured_browser_row_establishes_literal_customer_without_model(self) -> None:
        event = self._event("unused")
        result, failure, invocations = _extract_customer_fact(
            None,
            event,
            context="CUST-AB12CD34 需跟进",
            status_anchor="需跟进",
        )
        self.assertIsNone(failure)
        self.assertEqual(invocations, 0)
        self.assertEqual(
            result,
            {"customer_id": "CUST-AB12CD34", "status": "需跟进"},
        )

    def test_fresh_accessible_names_select_unique_semantic_controls_without_index_fallback(self) -> None:
        event = self._event(
            "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
            "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
        )
        selection, failure, invocations = _select_desktop_names(
            None,
            event,
            edit_names=("客户备注", "客户编号"),
            button_names=("关闭记录", "标记待跟进"),
        )
        self.assertIsNone(failure)
        self.assertEqual(invocations, 0)
        self.assertEqual(selection, ("客户编号", "标记待跟进"))

    def test_duplicate_semantic_targets_do_not_use_first_item(self) -> None:
        class _Budget:
            @staticmethod
            def decide(*args, **kwargs):
                return SimpleNamespace(use_model=False)

        resident = SimpleNamespace(budget=_Budget())
        event = self._event(
            "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
            "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
        )
        selection, failure, invocations = _select_desktop_names(
            resident,
            event,
            edit_names=("客户编号", "客户编号"),
            button_names=("标记待跟进",),
        )
        self.assertEqual(selection, ())
        self.assertIn("ambiguous", failure)
        self.assertEqual(invocations, 0)

    def test_verified_file_rolls_into_canonical_orient_checkpoint(self) -> None:
        event = self._event(
            "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
            "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
        )
        customer_id = "CUST-AB12CD34"
        state = SimpleNamespace(
            stage="native_completion",
            next_action="publish terminal EventOutcome",
            data={
                _STATE_KEY: {
                    "phase": "file_write_pending",
                    "customer_id": customer_id,
                    "status": "需跟进",
                    "exact_file_hint": "客户状态-华东",
                },
                "native_completion": {"success": True},
            },
        )

        class _Store:
            def __init__(self):
                self.saved = 0

            def save_working_state(self, _state):
                self.saved += 1

        reset_calls: list[str] = []
        resident = SimpleNamespace(
            body=object(),
            store=_Store(),
            _reset_investigation_after_goal_substep=lambda _event, _state, intent: reset_calls.append(
                intent.intent_id
            ),
            _sync_execution_context=lambda *_args, **_kwargs: None,
        )
        intent = SimpleNamespace(intent_id="e2e24-file-test")
        source = {
            "path": "/authorized/workspace/客户状态-华东.txt",
            "identity": {"size": len(customer_id)},
            "text_sha256": "fresh-sha",
        }

        with (
            patch(
                "zn_agent.core.browser_file_desktop_handoff_behavior.observe_workspace_text_source",
                return_value=(source, None),
            ),
            patch(
                "zn_agent.core.browser_file_desktop_handoff_behavior.fresh_workspace_text",
                return_value=(customer_id, None),
            ),
        ):
            result = _roll_forward_verified_file(
                resident,
                event,
                state,
                intent=intent,
                result=SimpleNamespace(success=True),
            )

        self.assertIsNone(result)
        self.assertEqual(state.stage, "orient")
        self.assertEqual(
            state.next_action,
            "freshly sense the current desktop application and ground the customer operation",
        )
        self.assertEqual(state.data[_STATE_KEY]["phase"], "desktop_ground")
        self.assertNotIn("native_completion", state.data)
        self.assertEqual(reset_calls, [intent.intent_id])
        self.assertEqual(resident.store.saved, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

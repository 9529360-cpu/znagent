from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.automation_text_content import AutomationTextRead, AutomationTextTargetSnapshot, text_sha256
from zn_agent.core.body import BodyActionResult
from zn_agent.core.current_app_text_cleanup_behavior import (
    _STATE_KEY,
    _begin,
    _final_verify,
    _replace,
    _save_prepare,
    _verify_replacement,
)
from zn_agent.core.current_app_text_cleanup_goal import CurrentAppTextCleanupGoal
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.models import AgentEvent, ExecutionPath, ResidentRunResult


TASK = "把我现在这个软件里的这份工作记录整理一下：去掉空行和完全重复的行，每行首尾空格也去掉，保留原来的顺序，然后保存。"
SOURCE = "  客户已确认方案  \r\n\r\n等待合同\r\n 客户已确认方案\r\n下周回访  "
RESULT = "客户已确认方案\r\n等待合同\r\n下周回访"
RID1 = (1, 2, 3)
RID2 = (1, 2, 4)
BUTTON_RID = (8, 8, 1)
FINAL_RID = (9, 9, 1)


@dataclass
class _State:
    data: dict
    stage: str = "orient"
    next_action: str | None = None
    blocked_by: str | None = None


class _Store:
    def __init__(self):
        self.snapshots: list[str] = []

    def save_working_state(self, state):
        self.snapshots.append(json.dumps(state.data, ensure_ascii=False, sort_keys=True, default=str))


class _WorkLedger:
    def work_item_for_event(self, _event_id):
        return SimpleNamespace(parent_work_item_id=None)


class _Foreground:
    def __init__(self, observations):
        self.observations = list(observations)
        self.last = self.observations[-1]

    def probe(self):
        if self.observations:
            self.last = self.observations.pop(0)
        return self.last


def _fg(hwnd=101, title="ZN 工作记录"):
    return ForegroundWindowObservation(
        process_id=4242,
        title=title,
        process_name="fixture.exe",
        class_name="WindowsForms10.Window",
        captured_at="2026-09-12T00:00:00+00:00",
        window_handle=hwnd,
    )


def _named_edit(runtime_id=RID1):
    return NamedAutomationControlObservation(
        runtime_id=runtime_id,
        process_id=4242,
        process_name="fixture.exe",
        name="工作记录",
        control_type=50004,
        class_name="WindowsForms10.EDIT",
        is_enabled=True,
        is_offscreen=False,
        left=0,
        top=0,
        right=200,
        bottom=120,
        center_x_fraction=0.25,
        center_y_fraction=0.30,
        captured_at="2026-09-12T00:00:00+00:00",
        is_keyboard_focusable=True,
        has_keyboard_focus=True,
        is_password=False,
        is_value_pattern_available=True,
        value_is_read_only=False,
    )


def _button():
    return NamedAutomationControlObservation(
        runtime_id=BUTTON_RID,
        process_id=4242,
        process_name="fixture.exe",
        name="保存",
        control_type=50000,
        class_name="WindowsForms10.BUTTON",
        is_enabled=True,
        is_offscreen=False,
        left=200,
        top=140,
        right=280,
        bottom=170,
        center_x_fraction=0.75,
        center_y_fraction=0.70,
        captured_at="2026-09-12T00:00:00+00:00",
    )


def _snapshot(text_name="工作记录", runtime_id=RID1, *, read_only=False, hwnd=101):
    return AutomationTextTargetSnapshot(
        runtime_id=runtime_id,
        process_id=4242,
        process_name="fixture.exe",
        window_handle=hwnd,
        name=text_name,
        control_type=50004,
        class_name="WindowsForms10.EDIT",
        is_enabled=True,
        is_offscreen=False,
        is_password=False,
        is_value_pattern_available=True,
        value_is_read_only=read_only,
        captured_at="2026-09-12T00:00:00+00:00",
        source="test",
    )


class _Named:
    def __init__(self, edits=None, *, ambiguous=False):
        self.edits = list(edits or [_named_edit()])
        self.last_edit = self.edits[-1]
        self.ambiguous = ambiguous
        self.button_calls = 0

    def find_unique_edit(self, **_kwargs):
        if self.ambiguous:
            raise RuntimeError("exact named UIA Edit is ambiguous")
        if self.edits:
            self.last_edit = self.edits.pop(0)
        return self.last_edit

    def find_unique_button(self, **_kwargs):
        self.button_calls += 1
        return _button()


class _Content:
    def __init__(self, reads, final_text=RESULT):
        self.reads = list(reads)
        self.final_text = final_text
        self.read_calls = 0

    def read_exact(self, **kwargs):
        self.read_calls += 1
        name = kwargs["name"]
        if name == "保存内容":
            snap = _snapshot("保存内容", FINAL_RID, read_only=True, hwnd=202)
            return AutomationTextRead(self.final_text, snap, snap)
        text, runtime_id = self.reads.pop(0) if self.reads else (RESULT, RID1)
        snap = _snapshot(runtime_id=runtime_id)
        return AutomationTextRead(text, snap, snap)

    def list_value_edits(self, **_kwargs):
        return (_snapshot("保存内容", FINAL_RID, read_only=True, hwnd=202),)


class _Body:
    def __init__(self):
        self.calls = []
        self.resolved = []

    def act(self, kind, *, event_id=None, **kwargs):
        self.calls.append((kind, dict(kwargs)))
        return BodyActionResult(
            action_id="replace-1",
            kind=kind,
            success=True,
            data={
                "success": True,
                "mutation_dispatched": True,
                "postcondition_verified": True,
                "process_id": 4242,
                "process_name": "fixture.exe",
                "window_handle": 101,
                "name": "工作记录",
                "runtime_id": list(RID1),
                "source_chars": kwargs["source_chars"],
                "source_sha256": kwargs["source_sha256"],
                "result_chars": kwargs["result_chars"],
                "result_sha256": kwargs["result_sha256"],
            },
            event_id=event_id,
        )

    def resolve_uncertain_attempt(self, attempt_id, **kwargs):
        self.resolved.append((attempt_id, kwargs))
        return True


class _Resident:
    _POINTER_CLICK_EXECUTION_KEY = "native_pointer_click_execution"

    def __init__(self, *, foreground=None, named=None, content=None):
        self.store = _Store()
        self.work_ledger = _WorkLedger()
        self.foreground_window = foreground or _Foreground([_fg()] * 20)
        self.named_automation_control = named or _Named()
        self.current_app_text_content = content or _Content([(SOURCE, RID1), (SOURCE, RID1), (RESULT, RID1)])
        self.body = _Body()
        self.intents = []

    def _checkpoint_terminal_failure(self, event, state, *, reason):
        state.stage = "terminal_failure"
        state.next_action = None
        self.store.save_working_state(state)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BUDGET_BLOCKED,
            success=False,
            model_invocations=0,
            reason=reason,
        )

    def _begin_native_action_cycle(self, _event, state, intent):
        self.intents.append(intent)
        state.data["native_action_intent"] = intent.to_dict()
        state.stage = "native_action"
        state.next_action = "move body"


class CurrentAppCleanupResidentTests(unittest.TestCase):
    def _event(self):
        return AgentEvent(event_id="evt-e2e13", task=TASK, kind="desktop_user_event", payload={})

    @staticmethod
    def _goal():
        return CurrentAppTextCleanupGoal(
            kind="foreground_desktop_text_cleanup",
            field_name="工作记录",
            save_button_name="保存",
            transform="trim_drop_blank_dedupe_stable",
        )

    def test_natural_task_uses_resident_state_without_persisting_raw_content(self):
        resident = _Resident()
        state = _State(data={})
        event = self._event()
        self.assertIsNone(_begin(resident, event, state, self._goal()))
        self.assertEqual(state.stage, "e2e13_replace")
        durable = json.dumps(state.data, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(SOURCE, durable)
        self.assertNotIn(RESULT, durable)
        self.assertIn(text_sha256(SOURCE), durable)
        self.assertIn(text_sha256(RESULT), durable)
        self.assertEqual(resident.named_automation_control.button_calls, 1)

        self.assertIsNone(_replace(resident, event, state))
        self.assertEqual(state.stage, "e2e13_verify_replacement")
        self.assertEqual(len(resident.body.calls), 1)
        self.assertEqual(resident.body.calls[0][1]["replacement_text"], RESULT)
        for snapshot in resident.store.snapshots:
            self.assertNotIn(SOURCE, snapshot)
            self.assertNotIn(RESULT, snapshot)

    def test_stale_runtime_id_is_reacquired_and_zero_mutation_occurs(self):
        named = _Named(edits=[_named_edit(RID1), _named_edit(RID2), _named_edit(RID2)])
        content = _Content([(SOURCE, RID1), (SOURCE, RID2)])
        resident = _Resident(named=named, content=content)
        state = _State(data={})
        event = self._event()
        _begin(resident, event, state, self._goal())
        self.assertIsNone(_replace(resident, event, state))
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(state.stage, "e2e13_replace")
        self.assertEqual(state.data[_STATE_KEY]["reground_count"], 1)
        self.assertEqual(tuple(state.data[_STATE_KEY]["source_target"]["runtime_id"]), RID2)

    def test_content_drift_recomputes_from_fresh_reality_before_any_mutation(self):
        changed = "客户已确认方案\r\n 新增真实行 \r\n等待合同"
        resident = _Resident(content=_Content([(SOURCE, RID1), (changed, RID1), (changed, RID1)]))
        state = _State(data={})
        event = self._event()
        _begin(resident, event, state, self._goal())
        self.assertIsNone(_replace(resident, event, state))
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(state.data[_STATE_KEY]["reground_count"], 1)
        self.assertEqual(state.data[_STATE_KEY]["source_evidence"]["sha256"], text_sha256(changed))

    def test_ambiguous_target_blocks_before_mutation(self):
        resident = _Resident(named=_Named(ambiguous=True))
        state = _State(data={})
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            _begin(resident, self._event(), state, self._goal())
        self.assertEqual(resident.body.calls, [])

    def test_save_intent_contains_semantic_authority_but_no_raw_text(self):
        resident = _Resident()
        state = _State(data={})
        event = self._event()
        _begin(resident, event, state, self._goal())
        _replace(resident, event, state)
        _verify_replacement(resident, event, state)
        _save_prepare(resident, event, state)
        self.assertEqual(len(resident.intents), 1)
        intent = resident.intents[0]
        self.assertEqual(intent.kind, "pointer_click")
        self.assertEqual(intent.expected_outcome["kind"], "e2e13_save_click")
        serialized = json.dumps(intent.to_dict(), ensure_ascii=False)
        self.assertNotIn(SOURCE, serialized)
        self.assertNotIn(RESULT, serialized)

    def test_completion_requires_fresh_new_same_process_window_and_exact_readback(self):
        foreground = _Foreground([_fg()] * 5 + [_fg(hwnd=202, title="ZN 工作记录已保存")])
        resident = _Resident(foreground=foreground)
        state = _State(data={})
        event = self._event()
        _begin(resident, event, state, self._goal())
        _replace(resident, event, state)
        _verify_replacement(resident, event, state)
        _save_prepare(resident, event, state)
        state.data[resident._POINTER_CLICK_EXECUTION_KEY] = {
            "status": "completed",
            "success": True,
            "action_id": "save-click-1",
        }
        # Drive final verification after the fixture's foreground sequence reaches the result HWND.
        outcome = None
        for _ in range(8):
            outcome = _final_verify(resident, event, state)
            if outcome is not None:
                break
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome.success)
        self.assertEqual(state.stage, "complete")
        self.assertEqual(state.data[_STATE_KEY]["save_dispatch_count"], 1)
        final = state.data[_STATE_KEY]["final_verification"]
        self.assertEqual(final["new_window_handle"], 202)
        self.assertEqual(final["sha256"], text_sha256(RESULT))

    def test_final_mismatch_does_not_complete(self):
        resident = _Resident(
            foreground=_Foreground([_fg()] * 4 + [_fg(hwnd=202, title="ZN 工作记录已保存")]),
            content=_Content([(SOURCE, RID1), (SOURCE, RID1), (RESULT, RID1)], final_text="错误内容"),
        )
        state = _State(data={})
        event = self._event()
        _begin(resident, event, state, self._goal())
        _replace(resident, event, state)
        _verify_replacement(resident, event, state)
        _save_prepare(resident, event, state)
        state.data[resident._POINTER_CLICK_EXECUTION_KEY] = {
            "status": "completed",
            "success": True,
            "action_id": "save-click-1",
        }
        outcome = None
        for _ in range(8):
            outcome = _final_verify(resident, event, state)
            if outcome is not None:
                break
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.success)
        self.assertNotEqual(state.stage, "complete")


if __name__ == "__main__":
    unittest.main()

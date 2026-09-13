from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from zn_agent.core.browser_desktop_record_transfer_behavior import (
    _STATE_KEY,
    _begin,
    _bounded_audit,
    _final_verify,
    _parse_source_context,
    _replace,
    _resolve_uncertain_replacement,
    _verify_replacement,
)


CUSTOMER_A = "CUST-ALPHA-42"
CUSTOMER_B = "CUST-BETA-77"
SOURCE_VALUE = "需跟进"
INITIAL_VALUE = "未跟进"


def _control(name: str, runtime: tuple[int, ...], *, read_only: bool, button: bool = False):
    return SimpleNamespace(
        runtime_id=runtime,
        process_id=4242,
        process_name="fixture.exe",
        name=name,
        control_type=50000 if button else 50004,
        class_name="WindowsForms10.EDIT.app.0" if not button else "WindowsForms10.BUTTON.app.0",
        is_enabled=True,
        is_offscreen=False,
        is_password=False,
        is_value_pattern_available=not button,
        value_is_read_only=read_only if not button else None,
        captured_at="2026-09-13T12:00:00Z",
        source="test-uia",
        center_x_fraction=0.8 if button else 0.3,
        center_y_fraction=0.8 if button else 0.3,
    )


class _NamedControls:
    def __init__(self):
        self.controls = {
            "客户编号": _control("客户编号", (1, 1), read_only=True),
            "跟进状态": _control("跟进状态", (2, 1), read_only=False),
            "保存": _control("保存", (3, 1), read_only=False, button=True),
        }
        self.ambiguous: set[str] = set()

    def find_unique_edit(self, *, name, **_kwargs):
        if name in self.ambiguous:
            raise RuntimeError(f"ambiguous {name}")
        return self.controls[name]

    def find_unique_button(self, *, name, **_kwargs):
        if name in self.ambiguous:
            raise RuntimeError(f"ambiguous {name}")
        return self.controls[name]


class _Content:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def read_exact(self, *, name, runtime_id, **_kwargs):
        return SimpleNamespace(text=self.values[name], audit={"runtime_id": list(runtime_id)})


class _Body:
    def __init__(self, content: _Content):
        self.content = content
        self.calls: list[dict] = []
        self.attempts: list[dict] = []
        self.resolved: list[tuple[str, str]] = []
        self.mismatch_after_write = False

    def act(self, kind: str, **kwargs):
        self.calls.append({"kind": kind, **kwargs})
        replacement = str(kwargs["replacement_text"])
        self.content.values["跟进状态"] = "错误值" if self.mismatch_after_write else replacement
        return SimpleNamespace(success=True, data={"mutation_dispatched": True}, error=None)

    def value_replacement_attempts(self, _event_id: str):
        return list(self.attempts)

    def resolve_uncertain_attempt(self, attempt_id: str, *, event_id: str, status: str):
        self.resolved.append((attempt_id, status))
        return True


class _Store:
    def save_working_state(self, _state):
        return None


class _Ledger:
    def __init__(self):
        self.root = SimpleNamespace(
            work_item_id="root",
            parent_work_item_id=None,
            acceptance_criteria=["exact cross-app transfer"],
            work_thread_id="thread",
            plan_version=1,
            status="active",
        )
        self.items = []

    def work_item_for_event(self, _event_id):
        return self.root

    def list_work_items(self, _thread_id, limit=256):
        return list(self.items)

    def create_child_item(self, *, root_work_item_id, objective, acceptance_criteria, title):
        item = SimpleNamespace(
            work_item_id=f"child-{len(self.items) + 1}",
            parent_work_item_id=root_work_item_id,
            plan_version=1,
            title=title,
            objective=objective,
            acceptance_criteria=list(acceptance_criteria),
            status="active",
            work_thread_id="thread",
        )
        self.items.append(item)
        return item

    def complete_child_item(self, work_item_id, *, result):
        item = next(item for item in self.items if item.work_item_id == work_item_id)
        item.status = "completed"
        item.result = result
        return item

    def accept_root_with_current_evidence(self, *_args, **_kwargs):
        self.root.status = "completed"
        return self.root


class _Resident:
    _POINTER_CLICK_EXECUTION_KEY = "native_pointer_click_execution"

    def __init__(self):
        self.values = {"客户编号": CUSTOMER_A, "跟进状态": INITIAL_VALUE}
        self.named_automation_control = _NamedControls()
        self.current_app_text_content = _Content(self.values)
        self.body = _Body(self.current_app_text_content)
        self.store = _Store()
        self.work_ledger = _Ledger()
        self.browser_status = SOURCE_VALUE
        self.browser_ambiguous = False
        self.authorization = SimpleNamespace(tab_id=91, attached_at="auth-generation-1")
        self.user_browser_extension = SimpleNamespace(authorized_tab=lambda: self.authorization)
        self.foreground = SimpleNamespace(
            process_id=4242,
            process_name="fixture.exe",
            window_handle=5151,
            title="客户记录编辑",
        )
        self.foreground_window = SimpleNamespace(probe=lambda: self.foreground)
        self.native_intents = []
        self.failures = []

    def _observe_authorized_anchor(self, anchor):
        if self.browser_ambiguous:
            raise RuntimeError("multiple visible structured results contain the requested subject")
        return {
            "tab_id": 91,
            "url": "https://example.test/customers",
            "title": "客户跟进列表",
            "context": f"{anchor} {self.browser_status}",
            "observed_at": "2026-09-13T12:00:00Z",
            "source": "zn-extension-user-browser",
        }

    def _checkpoint_terminal_failure(self, event, state, *, reason):
        self.failures.append(reason)
        state.stage = "terminal_failure"
        state.blocked_by = reason
        return SimpleNamespace(event=event, success=False, reason=reason)

    def _begin_native_action_cycle(self, event, state, intent):
        self.native_intents.append(intent)
        state.stage = "native_dispatch"
        state.data[self._POINTER_CLICK_EXECUTION_KEY] = {
            "status": "pending",
            "success": None,
            "action_id": intent.intent_id,
        }


class _State:
    def __init__(self):
        self.data = {}
        self.stage = "orient"
        self.next_action = None
        self.blocked_by = None


EVENT = SimpleNamespace(event_id="evt-14", kind="desktop_user_event", task="task", payload={})


class BrowserDesktopRecordTransferTests(unittest.TestCase):
    def _begin(self):
        resident = _Resident()
        state = _State()
        self.assertIsNone(_begin(resident, EVENT, state))
        self.assertEqual(state.stage, "e2e14_replace")
        return resident, state

    def test_parser_accepts_one_bounded_scalar_for_exact_business_key(self):
        self.assertEqual(_parse_source_context(f"{CUSTOMER_A} 需跟进", CUSTOMER_A), SOURCE_VALUE)
        with self.assertRaises(RuntimeError):
            _parse_source_context(f"prefix {CUSTOMER_A} 需跟进", CUSTOMER_A)
        with self.assertRaises(RuntimeError):
            _parse_source_context(f"{CUSTOMER_A} {CUSTOMER_A} 需跟进", CUSTOMER_A)

    def test_happy_path_reacquires_stale_destination_runtime_and_keeps_raw_data_transient(self):
        resident, state = self._begin()
        persisted = json.dumps(state.data[_STATE_KEY], ensure_ascii=False, sort_keys=True)
        self.assertNotIn(CUSTOMER_A, persisted)
        self.assertNotIn(SOURCE_VALUE, persisted)
        self.assertEqual(state.data[_STATE_KEY]["business_key"], _bounded_audit(CUSTOMER_A))

        resident.named_automation_control.controls["跟进状态"] = _control(
            "跟进状态", (2, 99), read_only=False
        )
        self.assertIsNone(_replace(resident, EVENT, state))
        self.assertEqual(len(resident.body.calls), 1)
        self.assertEqual(resident.body.calls[0]["runtime_id"], [2, 99])
        self.assertEqual(resident.values["跟进状态"], SOURCE_VALUE)
        self.assertEqual(state.stage, "e2e14_verify_replacement")
        self.assertIsNone(_verify_replacement(resident, EVENT, state))
        self.assertEqual(state.stage, "e2e14_save_prepare")

    def test_source_drift_fails_closed_before_any_desktop_mutation(self):
        resident, state = self._begin()
        resident.browser_status = "已联系"
        result = _replace(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.values["跟进状态"], INITIAL_VALUE)

    def test_destination_record_drift_fails_closed_before_any_mutation(self):
        resident, state = self._begin()
        resident.values["客户编号"] = CUSTOMER_B
        result = _replace(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.values["跟进状态"], INITIAL_VALUE)

    def test_ambiguous_source_fails_preflight_with_zero_mutation(self):
        resident = _Resident()
        resident.browser_ambiguous = True
        state = _State()
        result = _begin(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.native_intents, [])

    def test_ambiguous_target_fails_preflight_with_zero_mutation_or_save(self):
        resident = _Resident()
        resident.named_automation_control.ambiguous.add("跟进状态")
        state = _State()
        result = _begin(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.native_intents, [])

    def test_value_mismatch_after_write_is_rejected_before_save(self):
        resident, state = self._begin()
        resident.body.mismatch_after_write = True
        self.assertIsNone(_replace(resident, EVENT, state))
        result = _verify_replacement(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.native_intents, [])
        self.assertEqual(len(resident.body.calls), 1)

    def test_restart_after_mutation_attempt_reconciles_verified_effect_without_replay(self):
        resident, state = self._begin()
        resident.values["跟进状态"] = SOURCE_VALUE
        resident.body.attempts = [{"attempt_id": "attempt-1", "status": "started"}]
        handled, result = _resolve_uncertain_replacement(resident, EVENT, state)
        self.assertTrue(handled)
        self.assertIsNone(result)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.body.resolved, [("attempt-1", "verified_effect")])
        self.assertEqual(state.stage, "e2e14_verify_replacement")
        recovery = state.data[_STATE_KEY]["replacement_recovery"]
        self.assertEqual(recovery["additional_replacement_dispatches"], 0)

    def test_restart_mismatch_refuses_new_signature_and_blind_replay(self):
        resident, state = self._begin()
        resident.body.attempts = [{"attempt_id": "attempt-1", "status": "observed"}]
        handled, result = _resolve_uncertain_replacement(resident, EVENT, state)
        self.assertTrue(handled)
        self.assertFalse(result.success)
        self.assertEqual(resident.body.calls, [])
        self.assertEqual(resident.body.resolved, [])

    def test_final_saved_value_mismatch_fails_without_second_save(self):
        resident, state = self._begin()
        resident.values["跟进状态"] = SOURCE_VALUE
        state.data[_STATE_KEY]["phase"] = "save_dispatch"
        state.data[resident._POINTER_CLICK_EXECUTION_KEY] = {
            "status": "completed",
            "success": True,
            "action_id": "save-1",
        }
        resident.foreground = SimpleNamespace(
            process_id=4242,
            process_name="fixture.exe",
            window_handle=6161,
            title="客户记录已保存",
        )
        resident.values["跟进状态"] = "错误保存值"
        result = _final_verify(resident, EVENT, state)
        self.assertFalse(result.success)
        self.assertEqual(resident.native_intents, [])


if __name__ == "__main__":
    unittest.main()

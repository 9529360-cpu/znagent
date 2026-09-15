from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.automation_text_content import text_sha256
from zn_agent.core.browser_desktop_record_transfer_behavior import (
    _STATE_KEY,
    _begin,
    _browser_fact,
    _recover_replacement_dispatch,
    _replace,
    _request,
)


TASK = (
    "把当前网站里需跟进客户的状态填到我现在开的客户管理软件对应记录的“客户状态”字段里，"
    "并确认没有填错客户。"
)
FILE_TASK = (
    "看看当前网站里的客户状态，把需跟进的客户整理到昨天那份客户状态文件里，"
    "再到我现在开的客户管理软件里把这个异常客户标记待跟进，最后确认文件和软件都处理对了。"
)
CUSTOMER = "CUST-AB12CD34"
STATUS = "需跟进"
FIELD = "客户状态"
RID_OLD = (11, 12, 13)
RID_FRESH = (11, 12, 99)


def _event(task: str = TASK):
    return SimpleNamespace(
        event_id="evt-e2e14-core",
        kind="desktop_user_event",
        task=task,
        payload={"model_policy": "never"},
    )


class _Authorization:
    def __init__(self, tab_id=17, attached_at="generation-a"):
        self.tab_id = int(tab_id)
        self.attached_at = str(attached_at)


class _Extension:
    def __init__(self, values=None):
        self.values = list(values or [_Authorization()])
        self.last = self.values[-1]

    def authorized_tab(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class _Foreground:
    def __init__(self, *, customer=CUSTOMER):
        self.customer = customer

    def probe(self):
        return SimpleNamespace(
            process_id=222,
            process_name="fixture.exe",
            window_handle=8181,
            title=f"客户 {self.customer} — 当前记录",
        )


class _Named:
    def __init__(self, runtime_id=RID_FRESH):
        self.runtime_id = tuple(runtime_id)

    def find_unique_edit(self, **kwargs):
        return SimpleNamespace(runtime_id=self.runtime_id)


class _Text:
    def __init__(self, text="未同步"):
        self.text = text

    def read_exact(self, **kwargs):
        return SimpleNamespace(
            text=self.text,
            audit={"read_identity_stable": True},
        )


class _Store:
    def __init__(self):
        self.saved = 0

    def save_working_state(self, _state):
        self.saved += 1


class _Body:
    def __init__(self, *, attempts=None):
        self.attempts = list(attempts or [])
        self.act_calls = []
        self.resolve_calls = []

    def value_replacement_attempts(self, _event_id):
        return list(self.attempts)

    def act(self, kind, **kwargs):
        self.act_calls.append((kind, dict(kwargs)))
        return SimpleNamespace(
            success=True,
            error=None,
            data={
                "mutation_dispatched": True,
                "postcondition_verified": True,
                "side_effect_attempt_id": "sidefx-e2e14-new",
            },
        )

    def resolve_uncertain_attempt(self, attempt_id, *, event_id, status, **kwargs):
        self.resolve_calls.append((attempt_id, event_id, status))
        return True


class _Ledger:
    @staticmethod
    def work_item_for_event(_event_id):
        return SimpleNamespace(parent_work_item_id=None)


class _Resident:
    def __init__(self, *, customer=CUSTOMER, text="未同步", extension=None, body=None):
        self.user_browser_extension = extension or _Extension()
        self.foreground_window = _Foreground(customer=customer)
        self.named_automation_control = _Named()
        self.current_app_text_content = _Text(text)
        self.store = _Store()
        self.body = body or _Body()
        self.work_ledger = _Ledger()
        self.terminal_reasons = []

    @staticmethod
    def _observe_authorized_anchor(anchor):
        return {
            "tab_id": 17,
            "context": f"{CUSTOMER} {anchor}",
            "observed_at": "2026-09-15T12:00:00Z",
        }

    def _checkpoint_terminal_failure(self, event, state, *, reason):
        self.terminal_reasons.append(reason)
        state.stage = "terminal_failure"
        return "terminal"


def _state(meta=None, *, stage="e2e14_replace"):
    return SimpleNamespace(
        stage=stage,
        next_action=None,
        blocked_by=None,
        data={_STATE_KEY: dict(meta or {})},
    )


def _meta(*, source_text="未同步"):
    context = f"{CUSTOMER} {STATUS}"
    return {
        "version": 1,
        "phase": "replace",
        "customer_id": CUSTOMER,
        "status": STATUS,
        "field_name": FIELD,
        "browser_source": {
            "customer_id": CUSTOMER,
            "status": STATUS,
            "tab_id": 17,
            "authorization_attached_at": "generation-a",
            "context_sha256": __import__("hashlib").sha256(context.encode("utf-8")).hexdigest(),
            "observed_at": "2026-09-15T12:00:00Z",
        },
        "desktop_record": {
            "process_id": 222,
            "process_name": "fixture.exe",
            "window_handle": 8181,
            "field_name": FIELD,
            "initial_runtime_id": list(RID_OLD),
        },
        "source_value": {
            "chars": len(source_text),
            "sha256": text_sha256(source_text),
        },
        "expected_value": {
            "chars": len(STATUS),
            "sha256": text_sha256(STATUS),
        },
        "replacement_dispatch_count": 0,
    }


class BrowserDesktopRecordTransferBehaviorTests(unittest.TestCase):
    def test_request_is_direct_browser_desktop_only_and_does_not_capture_e2e24(self):
        self.assertEqual(
            _request(_event()),
            {"status_anchor": STATUS, "field_name": FIELD},
        )
        self.assertIsNone(_request(_event(FILE_TASK)))

    def test_browser_generation_drift_fails_closed(self):
        resident = _Resident(
            extension=_Extension(
                [
                    _Authorization(attached_at="generation-a"),
                    _Authorization(attached_at="generation-b"),
                ]
            )
        )
        fact, failure = _browser_fact(resident, status_anchor=STATUS)
        self.assertIsNone(fact)
        self.assertIn("authorization generation changed", str(failure))

    def test_wrong_current_desktop_record_is_rejected_before_any_mutation(self):
        resident = _Resident(customer="CUST-SIBLING")
        state = _state({}, stage="orient")

        result = _begin(
            resident,
            _event(),
            state,
            request={"status_anchor": STATUS, "field_name": FIELD},
        )

        self.assertEqual(result, "terminal")
        self.assertEqual(state.stage, "terminal_failure")
        self.assertEqual(resident.body.act_calls, [])
        self.assertTrue(
            any("does not match the Browser customer" in reason for reason in resident.terminal_reasons)
        )

    def test_replace_re_resolves_fresh_uia_runtime_and_dispatches_exactly_once(self):
        resident = _Resident(text="未同步")
        resident.named_automation_control = _Named(RID_FRESH)
        state = _state(_meta(source_text="未同步"))

        result = _replace(resident, _event(), state)

        self.assertIsNone(result)
        self.assertEqual(len(resident.body.act_calls), 1)
        kind, args = resident.body.act_calls[0]
        self.assertEqual(kind, "automation_value_replace")
        self.assertEqual(tuple(args["runtime_id"]), RID_FRESH)
        self.assertNotEqual(tuple(args["runtime_id"]), RID_OLD)
        self.assertEqual(args["replacement_text"], STATUS)
        self.assertEqual(args["source_sha256"], text_sha256("未同步"))
        self.assertEqual(args["result_sha256"], text_sha256(STATUS))
        self.assertEqual(state.stage, "e2e14_verify")
        self.assertEqual(state.data[_STATE_KEY]["replacement_dispatch_count"], 1)

    def test_started_attempt_recovery_uses_fresh_expected_result_and_zero_replay(self):
        body = _Body(
            attempts=[
                {
                    "attempt_id": "sidefx-e2e14-started",
                    "status": "started",
                    "kind": "automation_value_replace",
                }
            ]
        )
        resident = _Resident(text=STATUS, body=body)
        resident.named_automation_control = _Named(RID_FRESH)
        state = _state(_meta(source_text="未同步"))

        handled, result = _recover_replacement_dispatch(
            resident,
            _event(),
            state,
        )

        self.assertTrue(handled)
        self.assertIsNone(result)
        self.assertEqual(body.act_calls, [])
        self.assertEqual(
            body.resolve_calls,
            [("sidefx-e2e14-started", "evt-e2e14-core", "verified_effect")],
        )
        self.assertEqual(state.stage, "e2e14_verify")
        recovery = state.data[_STATE_KEY]["replacement_recovery"]
        self.assertEqual(tuple(recovery["runtime_id"]), RID_FRESH)
        self.assertEqual(recovery["additional_replacement_dispatches"], 0)

    def test_started_attempt_mismatch_fails_closed_and_never_replays(self):
        body = _Body(
            attempts=[
                {
                    "attempt_id": "sidefx-e2e14-started",
                    "status": "started",
                    "kind": "automation_value_replace",
                }
            ]
        )
        resident = _Resident(text="外部改动", body=body)
        state = _state(_meta(source_text="未同步"))

        handled, result = _recover_replacement_dispatch(resident, _event(), state)

        self.assertTrue(handled)
        self.assertEqual(result, "terminal")
        self.assertEqual(body.act_calls, [])
        self.assertEqual(body.resolve_calls, [])
        self.assertEqual(state.stage, "terminal_failure")
        self.assertTrue(any("refusing replay" in reason for reason in resident.terminal_reasons))


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.automation_text_content import (
    AutomationTextTargetSnapshot,
    AutomationValueReplacementResult,
    _WindowsAutomationTextWorker,
    text_sha256,
)
from zn_agent.core.provider_bridge import build_resident_runtime


RID = (71, 72, 73)
SOURCE = " A \r\nA"
RESULT = "A"


def _target(**overrides):
    values = {
        "runtime_id": RID,
        "process_id": 222,
        "process_name": "fixture.exe",
        "window_handle": 8181,
        "name": "工作记录",
        "control_type": 50004,
        "class_name": "WindowsForms10.EDIT.app.0",
        "is_enabled": True,
        "is_offscreen": False,
        "is_password": False,
        "is_value_pattern_available": True,
        "value_is_read_only": False,
        "captured_at": "2026-09-12T00:00:00+00:00",
        "source": "test-uia",
    }
    values.update(overrides)
    return AutomationTextTargetSnapshot(**values)


class NativeReplacementTargetPolicyTests(unittest.TestCase):
    def _require(self, target, *, allow_read_only=False):
        _WindowsAutomationTextWorker._require_target(
            target,
            process_id=222,
            process_name="fixture.exe",
            window_handle=8181,
            name="工作记录",
            runtime_id=RID,
            allow_read_only=allow_read_only,
        )

    def test_password_read_only_disabled_offscreen_and_missing_valuepattern_are_rejected(self):
        cases = [
            _target(is_password=True),
            _target(value_is_read_only=True),
            _target(is_enabled=False),
            _target(is_offscreen=True),
            _target(is_value_pattern_available=False),
        ]
        for target in cases:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self._require(target)

    def test_stale_runtime_wrong_process_wrong_hwnd_and_wrong_control_type_are_rejected(self):
        cases = [
            _target(runtime_id=(1, 2, 999)),
            _target(process_id=333),
            _target(process_name="other.exe"),
            _target(window_handle=9999),
            _target(control_type=50000),
        ]
        for target in cases:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self._require(target)

    def test_read_only_is_permitted_only_for_explicit_verification(self):
        self._require(_target(value_is_read_only=True), allow_read_only=True)


class _SuccessfulReplacement:
    def replace_exact(self, **kwargs):
        return AutomationValueReplacementResult(
            success=True,
            mutation_dispatched=True,
            postcondition_verified=True,
            process_id=kwargs["process_id"],
            process_name=kwargs["process_name"],
            window_handle=kwargs["window_handle"],
            name=kwargs["name"],
            runtime_id=tuple(kwargs["runtime_id"]),
            source_chars=kwargs["source_chars"],
            source_sha256=kwargs["source_sha256"],
            result_chars=kwargs["result_chars"],
            result_sha256=kwargs["result_sha256"],
        )


class DurableBodyRedactionTests(unittest.TestCase):
    def test_product_body_history_never_persists_raw_replacement_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.body._automation_value_replacement = _SuccessfulReplacement()
            response = resident.body.act(
                "automation_value_replace",
                event_id="evt-e2e13-redaction",
                process_id=222,
                process_name="fixture.exe",
                window_handle=8181,
                name="工作记录",
                runtime_id=list(RID),
                source_chars=len(SOURCE),
                source_sha256=text_sha256(SOURCE),
                replacement_text=RESULT,
                result_chars=len(RESULT),
                result_sha256=text_sha256(RESULT),
            )
            self.assertTrue(response.success, response.error)
            actions = [
                action
                for action in resident.body.recent_actions(32)
                if action.event_id == "evt-e2e13-redaction"
            ]
            self.assertEqual(len(actions), 1)
            args = actions[0].args
            self.assertNotIn("replacement_text", args)
            self.assertTrue(args.get("replacement_text_redacted"))
            self.assertEqual(args.get("replacement_chars"), len(RESULT))
            self.assertEqual(args.get("replacement_sha256"), text_sha256(RESULT))
            serialized = json.dumps(args, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(SOURCE, serialized)
            self.assertNotIn(RESULT, serialized)


if __name__ == "__main__":
    unittest.main()

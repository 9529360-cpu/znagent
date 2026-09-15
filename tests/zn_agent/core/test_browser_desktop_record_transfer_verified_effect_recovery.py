from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core import browser_desktop_record_transfer_behavior as transfer


class _Body:
    def __init__(self) -> None:
        self.resolve_calls: list[tuple[str, str]] = []

    def value_replacement_attempts(self, _event_id: str):
        return [{"attempt_id": "attempt-verified", "status": "verified_effect"}]

    def resolve_uncertain_attempt(self, attempt_id: str, *, event_id: str, status: str):
        self.resolve_calls.append((attempt_id, status))
        raise AssertionError("a durable verified_effect must not be rewritten or replayed")


class _Store:
    def save_working_state(self, _state) -> None:
        return None


class VerifiedEffectRestartTests(unittest.TestCase):
    def test_crash_after_verified_effect_before_stage_advance_uses_fresh_reality_without_replay(self):
        body = _Body()
        resident = SimpleNamespace(body=body, store=_Store())
        event = SimpleNamespace(event_id="evt-e2e14-verified")
        state = SimpleNamespace(
            stage="e2e14_replace",
            next_action=None,
            blocked_by=None,
            data={
                transfer._STATE_KEY: {
                    "phase": "replace",
                    "source": {"value": transfer._bounded_audit("需跟进")},
                }
            },
        )
        foreground = SimpleNamespace(process_id=4242, window_handle=5151)
        field_read = SimpleNamespace(text="需跟进")

        with patch.object(
            transfer,
            "_fresh_binding",
            return_value=(foreground, None, None, None, field_read, "CUST-TEST", "需跟进"),
        ) as fresh_binding:
            handled, result = transfer._resolve_uncertain_replacement(resident, event, state)

        self.assertTrue(handled)
        self.assertIsNone(result)
        fresh_binding.assert_called_once()
        self.assertEqual(body.resolve_calls, [])
        self.assertEqual(state.stage, "e2e14_verify_replacement")
        recovery = state.data[transfer._STATE_KEY]["replacement_recovery"]
        self.assertEqual(recovery["attempt_id"], "attempt-verified")
        self.assertEqual(recovery["status_before"], "verified_effect")
        self.assertEqual(recovery["status_after"], "verified_effect")
        self.assertEqual(recovery["additional_replacement_dispatches"], 0)


if __name__ == "__main__":
    unittest.main()

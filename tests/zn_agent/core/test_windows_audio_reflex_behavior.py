from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.models import AgentEvent, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime


def _event(event_id: str, task: str) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        task=task,
        kind="desktop_user_event",
        priority=0,
        payload={},
    )


def _state(event: AgentEvent) -> WorkingState:
    return WorkingState(
        current_event_id=event.event_id,
        stage="orient",
    )


def _advance(resident, event, state):
    return resident._advance_event_step(
        event,
        state,
        readiness=SimpleNamespace(),
        learning_evidence=[],
    )


class WindowsAudioReflexBehaviorTests(unittest.TestCase):
    def _runtime(self, tmp: str):
        return build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )

    def _zero_model_guards(self, resident):
        return (
            patch.object(
                resident.memory,
                "recall",
                side_effect=AssertionError("audio reflex must precede memory"),
            ),
            patch.object(
                resident.capabilities,
                "resolve",
                side_effect=AssertionError("audio reflex must precede compiled capability lookup"),
            ),
            patch.object(
                resident.kernel,
                "run_goal",
                side_effect=AssertionError("audio reflex must not call a model"),
            ),
        )

    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        return_value=37.0,
    )
    def test_direct_volume_read_completes_before_memory_or_model(self, read_volume) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-read", "现在音量是多少")
            state = _state(event)
            try:
                guards = self._zero_model_guards(resident)
                with guards[0], guards[1], guards[2]:
                    result = _advance(resident, event, state)
            finally:
                resident.store.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertIn("37", result.response)
        self.assertEqual(state.stage, "native_completion")
        read_volume.assert_called_once_with()

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=40.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        side_effect=[31.0, 40.0],
    )
    def test_direct_volume_set_uses_action_executor_and_fresh_readback(
        self,
        read_volume,
        set_volume,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-set", "把音量调到 40%")
            state = _state(event)
            try:
                guards = self._zero_model_guards(resident)
                with guards[0], guards[1], guards[2]:
                    result = _advance(resident, event, state)
            finally:
                resident.store.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertIn("40", result.response)
        set_volume.assert_called_once_with(40.0)
        self.assertEqual(read_volume.call_count, 2)
        self.assertEqual(state.data["windows_audio_reflex_v1"]["verification_status"], "verified")


    def test_out_of_range_volume_fails_closed_without_dispatch_or_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-invalid", "把音量调到 150%")
            state = _state(event)
            try:
                guards = self._zero_model_guards(resident)
                with (
                    guards[0],
                    guards[1],
                    guards[2],
                    patch(
                        "zn_agent.core.windows_companion_body.set_default_render_volume_percent"
                    ) as set_volume,
                ):
                    result = _advance(resident, event, state)
            finally:
                resident.store.close()

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(state.stage, "failed")
        self.assertEqual(state.blocked_by, "audio_action_failed")
        set_volume.assert_not_called()

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=40.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        side_effect=[31.0, RuntimeError("transient readback"), 40.0],
    )
    def test_uncertain_set_reverifies_same_event_without_redispatch(
        self,
        read_volume,
        set_volume,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-reverify", "把音量调到 40%")
            state = _state(event)
            try:
                guards = self._zero_model_guards(resident)
                with guards[0], guards[1], guards[2]:
                    first = _advance(resident, event, state)
                    self.assertIsNone(first)
                    self.assertEqual(state.stage, "windows_audio_reflex_reverify")
                    persisted = resident.store.get_working_state()
                    self.assertEqual(persisted.stage, "windows_audio_reflex_reverify")

                    second = _advance(resident, event, state)
            finally:
                resident.store.close()

        self.assertIsNotNone(second)
        self.assertTrue(second.success)
        self.assertEqual(second.model_invocations, 0)
        self.assertEqual(state.stage, "native_completion")
        set_volume.assert_called_once_with(40.0)
        self.assertEqual(read_volume.call_count, 3)

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=40.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        side_effect=[31.0, RuntimeError("transient readback"), 40.0],
    )
    def test_restart_reverifies_same_durable_attempt_without_redispatch(
        self,
        read_volume,
        set_volume,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            event = _event("evt-audio-restart", "把音量调到 40%")

            first_resident = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            state = _state(event)
            try:
                guards = self._zero_model_guards(first_resident)
                with guards[0], guards[1], guards[2]:
                    self.assertIsNone(_advance(first_resident, event, state))
                self.assertEqual(state.stage, "windows_audio_reflex_reverify")
            finally:
                first_resident.store.close()

            restarted = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                persisted = restarted.store.get_working_state()
                self.assertEqual(persisted.stage, "windows_audio_reflex_reverify")
                guards = self._zero_model_guards(restarted)
                with guards[0], guards[1], guards[2]:
                    result = _advance(restarted, event, persisted)
            finally:
                restarted.store.close()

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(persisted.stage, "native_completion")
        set_volume.assert_called_once_with(40.0)
        self.assertEqual(read_volume.call_count, 3)

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=40.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        side_effect=[
            31.0,
            RuntimeError("first readback failed"),
            RuntimeError("second readback failed"),
        ],
    )
    def test_repeated_uncertainty_enters_existing_side_effect_recovery(
        self,
        _read_volume,
        set_volume,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-recovery", "把音量调到 40%")
            state = _state(event)
            try:
                guards = self._zero_model_guards(resident)
                with guards[0], guards[1], guards[2]:
                    self.assertIsNone(_advance(resident, event, state))
                    self.assertEqual(state.stage, "windows_audio_reflex_reverify")
                    self.assertIsNone(_advance(resident, event, state))
            finally:
                resident.store.close()

        self.assertEqual(state.stage, "side_effect_recovery")
        self.assertEqual(state.blocked_by, "outside_world_effect_uncertain")
        recovery = state.data["side_effect_recovery"]
        self.assertTrue(recovery["replay_blocked"])
        self.assertEqual(recovery["decision"], "user_decision_required")
        set_volume.assert_called_once_with(40.0)

    def test_missing_action_binding_fails_closed_without_model_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._runtime(tmp)
            event = _event("evt-audio-missing", "现在音量是多少")
            state = _state(event)
            try:
                resident.action_fabric.unregister("windows.audio.volume.read")
                guards = self._zero_model_guards(resident)
                with guards[0], guards[1], guards[2]:
                    result = _advance(resident, event, state)
            finally:
                resident.store.close()

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(state.blocked_by, "audio_action_unavailable")


if __name__ == "__main__":
    unittest.main()

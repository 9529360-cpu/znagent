from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent, derive_native_action_intents
from zn_agent.core.embodied_resident import EmbodiedResidentRuntime
from zn_agent.core.models import AgentEvent, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.procedural_resident import ProcedurallyInfluencedResidentRuntime
from zn_agent.core.world_closed_loop import WorldAwareTransferResidentRuntime


class NativeChoiceRecoveryTests(unittest.TestCase):
    @staticmethod
    def _resident(tmp: str) -> ProcedurallyInfluencedResidentRuntime:
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        if not isinstance(resident, ProcedurallyInfluencedResidentRuntime):
            raise AssertionError(type(resident))
        return resident

    @staticmethod
    def _event() -> AgentEvent:
        return AgentEvent(
            event_id="evt-native-choice-recovery",
            task="perform one of the current structured repair alternatives",
            payload={
                "native_action_options": [
                    {"kind": "command", "args": {"command": "repair-a"}},
                    {"kind": "command", "args": {"command": "repair-b"}},
                ]
            },
        )

    def test_active_runtime_preserves_world_aware_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            self.assertIsInstance(resident, WorldAwareTransferResidentRuntime)
            resident.store.close()

    def test_blocked_first_structured_choice_recovers_to_second_without_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            intents = derive_native_action_intents(event)
            self.assertEqual(len(intents), 2)
            self.assertEqual(tuple(item.source for item in intents), ("structured_choice",) * 2)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
            )

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v1",
            ):
                resident._record_failed_action(
                    event,
                    state,
                    intents[0],
                    source="body",
                    failure="first choice failed",
                )
                recovered = resident._recover_from_blocked_structured_choices(
                    event,
                    state,
                    intents,
                )

            self.assertTrue(recovered)
            self.assertEqual(state.stage, "native_action")
            selected = state.data.get("native_action_intent") or {}
            self.assertEqual(selected.get("kind"), "command")
            self.assertEqual(selected.get("args", {}).get("command"), "repair-b")
            recovery = state.data.get(resident._NATIVE_CHOICE_RECOVERY_KEY) or {}
            self.assertEqual(recovery.get("selected_index"), 1)
            self.assertEqual(recovery.get("choice_count"), 2)
            self.assertEqual(recovery.get("blocked_prior_choices"), 1)
            self.assertEqual(recovery.get("action_kind"), "command")
            self.assertEqual(recovery.get("evidence_version"), "reality-v1")
            self.assertNotIn(resident._PROCEDURAL_INFLUENCE_KEY, state.data)
            resident.store.close()

    def test_unblocked_first_choice_keeps_historical_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = self._event()
            intents = derive_native_action_intents(event)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
            )

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v1",
            ):
                recovered = resident._recover_from_blocked_structured_choices(
                    event,
                    state,
                    intents,
                )

            self.assertFalse(recovered)
            self.assertNotIn("native_action_intent", state.data)
            self.assertNotIn(resident._NATIVE_CHOICE_RECOVERY_KEY, state.data)
            resident.store.close()

    def test_single_or_non_choice_intents_do_not_trigger_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = AgentEvent(
                event_id="evt-single-native-action",
                task="perform the explicitly requested movement",
                payload={"body_action": {"kind": "command", "command": "only-one"}},
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
            )
            intents = derive_native_action_intents(event)
            self.assertEqual(len(intents), 1)
            self.assertEqual(intents[0].source, "structured_event")

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v1",
            ):
                resident._record_failed_action(
                    event,
                    state,
                    intents[0],
                    source="body",
                    failure="explicit movement failed",
                )
                recovered = resident._recover_from_blocked_structured_choices(
                    event,
                    state,
                    intents,
                )

            self.assertFalse(recovered)
            self.assertNotIn(resident._NATIVE_CHOICE_RECOVERY_KEY, state.data)
            resident.store.close()

    def test_recovery_never_invents_args_from_failed_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            event = AgentEvent(
                event_id="evt-choice-current-args",
                task="use one current structured write alternative",
                payload={
                    "native_action_options": [
                        {
                            "kind": "write_text",
                            "args": {"path": "/current/a", "content": "A"},
                        },
                        {
                            "kind": "write_text",
                            "args": {"path": "/current/b", "content": "B"},
                        },
                    ]
                },
            )
            intents = derive_native_action_intents(event)
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
            )

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="reality-v2",
            ):
                resident._record_failed_action(
                    event,
                    state,
                    intents[0],
                    source="verification",
                    failure="old content was contradicted",
                )
                recovered = resident._recover_from_blocked_structured_choices(
                    event,
                    state,
                    intents,
                )

            self.assertTrue(recovered)
            selected = NativeActionIntent.from_dict(state.data["native_action_intent"])
            self.assertEqual(selected.args["path"], "/current/b")
            self.assertEqual(selected.args["content"], "B")
            self.assertNotIn("old content was contradicted", selected.args.values())
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

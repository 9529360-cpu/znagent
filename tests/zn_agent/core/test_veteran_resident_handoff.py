from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from zn_agent.core.broad_goal_work_resident import BroadGoalWorkResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.veteran_work_owner import VeteranWorkOwnerStep


class VeteranResidentHandoffTests(unittest.TestCase):
    def test_resident_advances_veteran_then_hands_back_to_zn_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "repo"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="veteran-resident", title="Veteran")
                ledger.attach_workspace(
                    "veteran-resident",
                    workspace,
                    name="Workspace",
                )
                _, event = ledger.start(
                    "veteran-resident",
                    "Implement the bounded repository change.",
                    payload={
                        "engineering_mode": "veteran",
                        "model_policy": "on_demand",
                        "data_classification": "cloud_allowed",
                        "route_policy": {"allowed_providers": ["openai"]},
                    },
                    acceptance_criteria=[
                        "the requested repository behavior is implemented",
                        "focused verification passes",
                    ],
                )
                root_item = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_item)
                assert root_item is not None

                state = resident.store.get_working_state()
                state.current_event_id = event.event_id
                state.stage = "native_deliberation"
                state.next_action = "advance engineering work"
                resident.store.save_working_state(state)

                owner_instance = MagicMock()
                owner_instance.advance.side_effect = [
                    VeteranWorkOwnerStep(
                        state="planned",
                        worker_run_id="worker-veteran",
                        work_item_id="item-veteran",
                        mission_id="mission-1",
                        phase="execution",
                        message="planned",
                    ),
                    VeteranWorkOwnerStep(
                        state="projected",
                        worker_run_id="worker-veteran",
                        work_item_id="item-veteran",
                        mission_id="mission-1",
                        phase="finalize",
                        message="projected",
                        candidate_commit="c" * 40,
                        projected_paths=("app.py",),
                    ),
                ]

                with patch(
                    "zn_agent.core.broad_goal_coding_resident.VeteranEngineeringWorkOwner"
                ) as owner_type:
                    owner_type.handles.return_value = True
                    owner_type.policy_block_reason.return_value = None
                    owner_type.return_value = owner_instance

                    first = resident._deliberation_step(
                        event,
                        state,
                        readiness=SimpleNamespace(),
                        learning_evidence=[],
                    )
                    self.assertIsNone(first)
                    self.assertEqual(state.stage, "native_deliberation")
                    self.assertFalse(
                        bool(
                            state.data.get(
                                resident._VETERAN_HANDOFF_KEY
                            )
                        )
                    )
                    self.assertEqual(
                        state.data[resident._VETERAN_STATE_KEY]["status"],
                        "planned",
                    )

                    second = resident._deliberation_step(
                        event,
                        state,
                        readiness=SimpleNamespace(),
                        learning_evidence=[],
                    )
                    self.assertIsNone(second)
                    self.assertTrue(
                        state.data[resident._VETERAN_HANDOFF_KEY]
                    )
                    self.assertEqual(
                        state.data[resident._VETERAN_STATE_KEY]["status"],
                        "projected",
                    )
                    self.assertEqual(
                        state.data[resident._VETERAN_STATE_KEY]["candidate_commit"],
                        "c" * 40,
                    )
                    self.assertEqual(
                        state.next_action,
                        "independently verify the projected Veteran candidate against Root acceptance",
                    )
                    self.assertEqual(owner_instance.advance.call_count, 2)

                    sentinel = object()
                    with patch.object(
                        BroadGoalWorkResidentRuntime,
                        "_deliberation_step",
                        return_value=sentinel,
                    ) as original_path:
                        third = resident._deliberation_step(
                            event,
                            state,
                            readiness=SimpleNamespace(),
                            learning_evidence=[],
                        )
                    self.assertIs(third, sentinel)
                    original_path.assert_called_once()
                    self.assertEqual(owner_instance.advance.call_count, 2)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.veteran_work_owner import VeteranWorkOwnerStep


class BroadGoalVeteranEngineeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="veteran-route", title="Veteran Route")
        self.ledger.attach_workspace(
            "veteran-route",
            self.workspace,
            name="Workspace",
        )
        _, self.event = self.ledger.start(
            "veteran-route",
            "Implement one repository change.",
            acceptance_criteria=["focused verifier passes"],
        )
        self.event.payload["engineering_mode"] = "veteran"
        self.state = WorkingState(
            current_event_id=self.event.event_id,
            stage="native_deliberation",
            next_action="deliberate",
            data={},
        )

    def tearDown(self) -> None:
        self.resident.store.close()
        self.temp.cleanup()

    def _call(self):
        return self.resident._deliberation_step(
            self.event,
            self.state,
            readiness=None,
            learning_evidence=[],
            thought=None,
        )

    def test_veteran_mode_advances_without_external_cognition(self) -> None:
        progress = VeteranWorkOwnerStep(
            state="advanced",
            worker_run_id="worker-1",
            work_item_id="item-1",
            mission_id="mission-1",
            phase="validation",
            message="advanced",
        )
        with patch(
            "zn_agent.core.veteran_work_owner.VeteranEngineeringWorkOwner.advance",
            return_value=progress,
        ):
            result = self._call()
        self.assertIsNone(result)
        self.assertEqual(self.state.stage, "native_deliberation")
        self.assertEqual(
            self.state.data["veteran_engineering"]["mission_id"],
            "mission-1",
        )
        self.assertEqual(
            self.state.data["veteran_engineering"]["phase"],
            "validation",
        )
        self.assertNotIn("cognition_request", self.state.data)
        self.assertFalse(
            self.state.data.get("veteran_engineering_handoff_complete", False)
        )

    def test_projected_candidate_hands_back_to_existing_root_verifier_once(self) -> None:
        progress = VeteranWorkOwnerStep(
            state="projected",
            worker_run_id="worker-1",
            work_item_id="item-1",
            mission_id="mission-1",
            phase="finalize",
            candidate_commit="c" * 40,
            projected_paths=("app.py",),
            message="projected",
        )
        with patch(
            "zn_agent.core.veteran_work_owner.VeteranEngineeringWorkOwner.advance",
            return_value=progress,
        ):
            self.assertIsNone(self._call())
        self.assertTrue(self.state.data["veteran_engineering_handoff_complete"])
        self.assertEqual(
            self.state.next_action,
            "independently verify the projected Veteran candidate against Root acceptance",
        )

        # On the next pulse the Veteran branch is bypassed. Existing native
        # deliberation resumes and starts investigation/verifier work instead
        # of re-projecting or re-running the Mission.
        with patch(
            "zn_agent.core.veteran_work_owner.VeteranEngineeringWorkOwner.advance",
            side_effect=AssertionError("Veteran owner must not run after handoff"),
        ):
            result = self._call()
        self.assertIsNone(result)
        self.assertEqual(self.state.stage, "native_investigation")

    def test_zero_model_policy_blocks_before_veteran_owner(self) -> None:
        self.event.payload["model_policy"] = "never"
        with patch(
            "zn_agent.core.veteran_work_owner.VeteranEngineeringWorkOwner.advance",
            side_effect=AssertionError("model-disabled Work must not start Veteran"),
        ):
            result = self._call()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.success)
        self.assertEqual(result.model_invocations, 0)
        self.assertIn("disabled by policy 'never'", str(result.reason))
        self.assertEqual(
            self.state.data["veteran_engineering"]["status"],
            "blocked",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

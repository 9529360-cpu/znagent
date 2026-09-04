from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.broad_goal_research_resident import BroadGoalResearchResidentRuntime
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _ResearchCognition:
    _BROAD_STEP_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self) -> None:
        self.calls = 0
        self.step_questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        if self._BROAD_STEP_MARKER not in question:
            return CognitiveIncrement(
                text="Use the attached workspace and continue the durable objective.",
                provider="fixture",
                model="research-fixture",
            )
        self.step_questions.append(question)
        proposal = {
            "zn_work_step": {
                "objective": "read one authoritative product page from current reality",
                "action": {"kind": "research_page", "url": "https://example.test/product-docs"},
                "acceptance": {"kind": "page_read", "url": "https://example.test/product-docs"},
            }
        }
        return CognitiveIncrement(
            text=json.dumps(proposal),
            provider="fixture",
            model="research-fixture",
        )


class BroadGoalResearchLayerTests(unittest.TestCase):
    def _start(self, root: Path):
        workspace = root / "workspace"
        workspace.mkdir()
        kernel = build_runtime(config={"model": {}}, store_path=root / "kernel.db")
        resident = BroadGoalResearchResidentRuntime(
            kernel=kernel,
            budget=CognitiveBudgetManager(),
        )
        cognition = _ResearchCognition()
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="research-fixture",
                    provider="fixture",
                    model="research-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "research": 1.0,
                        "language_understanding": 1.0,
                    },
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(resource_builder=lambda _route: cognition),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="research-loop", title="Research loop")
        ledger.attach_workspace("research-loop", workspace, name="Research Workspace")
        _, event = control.start(
            "research-loop",
            "Research one current external fact before continuing a broad local product task.",
            payload={"model_policy": "on_demand"},
            acceptance_criteria=["later independent product verification still required"],
        )
        root_item = ledger.work_item_for_event(event.event_id)
        self.assertIsNotNone(root_item)
        for _ in range(64):
            resident.live_once()
            if resident.store.get_working_state().stage == "broad_goal_research":
                break
        self.assertEqual(resident.store.get_working_state().stage, "broad_goal_research")
        return resident, cognition, ledger, event, root_item

    def test_research_child_completes_only_from_fresh_managed_page_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event, root_item = self._start(Path(tmp))
            try:
                session = SimpleNamespace(session_id="research-session")
                page = {
                    "url": "https://example.test/product-docs",
                    "title": "Product docs",
                    "captured_at": "2026-09-04T20:00:00Z",
                    "page_id": "page-1",
                    "text": "Current product docs say local data is persisted on this device.",
                    "links": [],
                    "provider": "test-managed-browser",
                    "profile_scope": "ephemeral",
                }
                with (
                    patch.object(resident.managed_browser, "open_session", return_value=session),
                    patch.object(resident.managed_browser, "close_session", return_value=None),
                    patch.object(resident, "_navigate_and_read", return_value=page) as navigate,
                ):
                    self.assertIsNone(resident.live_once())
                navigate.assert_called_once()
                children = [
                    item for item in ledger.list_work_items("research-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "completed")
                self.assertIn("captured_at", children[0].result or "")
                self.assertIn("local data is persisted", children[0].result or "")
                self.assertEqual(resident.store.get_working_state().stage, "native_deliberation")
                self.assertIsNone(resident.result_for(event.event_id))
                self.assertGreaterEqual(len(cognition.step_questions), 1)
            finally:
                resident.store.close()

    def test_browser_failure_blocks_child_and_reaches_later_broad_cognition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, cognition, ledger, event, root_item = self._start(Path(tmp))
            try:
                session = SimpleNamespace(session_id="research-session")
                with (
                    patch.object(resident.managed_browser, "open_session", return_value=session),
                    patch.object(resident.managed_browser, "close_session", return_value=None),
                    patch.object(
                        resident,
                        "_navigate_and_read",
                        side_effect=RuntimeError("network-evidence-boom"),
                    ),
                ):
                    self.assertIsNone(resident.live_once())
                children = [
                    item for item in ledger.list_work_items("research-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "blocked")
                self.assertIn("network-evidence-boom", children[0].blocker or "")
                self.assertEqual(resident.store.get_working_state().stage, "native_investigation")

                before = len(cognition.step_questions)
                for _ in range(64):
                    resident.live_once()
                    if len(cognition.step_questions) > before:
                        break
                self.assertGreater(len(cognition.step_questions), before)
                self.assertTrue(
                    any("network-evidence-boom" in question for question in cognition.step_questions[before:]),
                    "the real managed-browser failure never reached a later Broad cognition request",
                )
                self.assertIsNone(resident.result_for(event.event_id))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

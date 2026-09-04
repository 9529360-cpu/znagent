from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _ResearchCognition:
    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        proposal = {
            "zn_work_step": {
                "objective": "read one authoritative product page from current reality",
                "action": {
                    "kind": "research_page",
                    "url": "https://example.test/product-docs",
                },
                "acceptance": {
                    "kind": "page_read",
                    "url": "https://example.test/product-docs",
                },
            }
        }
        return CognitiveIncrement(
            text=json.dumps(proposal),
            provider="e2e-cognition",
            model="bounded-research-fixture",
        )


class BroadGoalManagedResearchTests(unittest.TestCase):
    @staticmethod
    def _configure(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="e2e-26-research-cognition",
                    provider="fixture",
                    model="bounded-research-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "research": 1.0,
                        "language_understanding": 1.0,
                    },
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: cognition,
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def _start(self, root: Path):
        workspace = root / "workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        cognition = _ResearchCognition()
        self._configure(resident, cognition)
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
        for _ in range(48):
            resident.live_once()
            if resident.store.get_working_state().stage == "broad_goal_research":
                break
        self.assertEqual(resident.store.get_working_state().stage, "broad_goal_research")
        return resident, cognition, ledger, event, root_item

    def test_research_proposal_becomes_fresh_page_evidence_before_child_completion(self) -> None:
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
                    item
                    for item in ledger.list_work_items("research-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "completed")
                self.assertIn("captured_at", children[0].result or "")
                self.assertIn("local data is persisted", children[0].result or "")
                self.assertEqual(resident.store.get_working_state().stage, "native_deliberation")
                self.assertIsNone(resident.result_for(event.event_id))
                self.assertGreaterEqual(cognition.calls, 1)
            finally:
                resident.store.close()

    def test_real_research_failure_blocks_child_and_returns_failure_to_cognition(self) -> None:
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
                    item
                    for item in ledger.list_work_items("research-loop")
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "blocked")
                self.assertIn("network-evidence-boom", children[0].blocker or "")
                self.assertEqual(resident.store.get_working_state().stage, "native_investigation")

                for _ in range(48):
                    resident.live_once()
                    if cognition.calls >= 2:
                        break
                self.assertGreaterEqual(cognition.calls, 2)
                self.assertIn("network-evidence-boom", cognition.questions[1])
                self.assertIsNone(resident.result_for(event.event_id))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

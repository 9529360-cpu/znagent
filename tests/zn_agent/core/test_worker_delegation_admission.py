from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerDelegationAdmissionTests(unittest.TestCase):
    def test_v1_delegation_requires_explicit_research_build_and_review_goal(self) -> None:
        probe = SimpleNamespace
        ordinary_goals = [
            "Create a tiny local Python artifact, execute it, and recover from real failures until its contract passes.",
            "Create and independently verify one tiny runnable local artifact.",
            "帮我开发一个本地个人记账小产品。先调研一下同类产品最核心的功能，然后自己推进，做出一个能真正运行的第一版。",
        ]
        for objective in ordinary_goals:
            with self.subTest(objective=objective):
                self.assertFalse(
                    BroadGoalCompletionResidentRuntime._root_requests_delegated_worker_sequence(
                        probe(objective=objective)
                    )
                )

        delegated_goal = (
            "帮我开发一个本地个人记账小产品。先调研一个权威的当前资料来确认核心功能，"
            "然后开发一个可运行的最小版本，实际运行测试，再做一次独立 review/test。"
        )
        self.assertTrue(
            BroadGoalCompletionResidentRuntime._root_requests_delegated_worker_sequence(
                probe(objective=delegated_goal)
            )
        )

    def test_worker_context_pack_carries_bounded_failed_effect_without_other_worker_internals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="delegation-admission", title="Delegation admission")
                ledger.attach_workspace("delegation-admission", workspace, name="Workspace")
                _, event = ledger.start(
                    "delegation-admission",
                    "Research a current source, develop a runnable MVP, then do an independent review.",
                    acceptance_criteria=["real research, runnable implementation, and independent review evidence"],
                )
                root = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                assert root is not None

                failed_effect = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Read one authoritative source",
                    acceptance_criteria=["page_read: https://old.example.invalid/source"],
                    title="Failed real browser effect",
                )
                failure = "managed browser research failed: TimeoutError: source unavailable"
                ledger.block_child_item(failed_effect.work_item_id, blocker=failure)

                delegated_child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Research one authoritative current source needed by the Root Work",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                    title="Research worker",
                )
                profile = resident._WORKER_SCOPE_PROFILES["research"]
                worker = ledger.start_worker_run(
                    work_item_id=delegated_child.work_item_id,
                    executor_kind="research",
                    tool_scope=profile["tool_scope"],
                    authority_scope=profile["authority_scope"],
                )
                request = SimpleNamespace(
                    request_id="request-before-binding",
                    required_capabilities=(),
                    context={},
                    question="bounded research request",
                )
                resident._bind_worker_request(
                    event,
                    root,
                    request,
                    worker,
                    delegated_child,
                    expected_action="research_page",
                    completed=[],
                )

                pack = request.context["worker_context_pack"]
                evidence = pack["relevant_evidence"]
                self.assertTrue(evidence)
                self.assertEqual(evidence[-1]["kind"], "failed_effect")
                self.assertIn("TimeoutError", evidence[-1]["blocker"])
                serialized = json.dumps(pack, ensure_ascii=False, sort_keys=True)
                for forbidden in (
                    "worker_run_id",
                    "model_route_id",
                    "other_workers",
                    "credentials",
                    "self_model",
                    "transcript",
                ):
                    self.assertNotIn(forbidden, serialized)
                self.assertIn("do not blindly repeat", request.question)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

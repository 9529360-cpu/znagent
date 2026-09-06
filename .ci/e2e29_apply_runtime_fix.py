from __future__ import annotations

from pathlib import Path
import py_compile


ROOT = Path(__file__).resolve().parents[1]
COMPLETION = ROOT / "runtime/python/zn_agent/core/broad_goal_completion_resident.py"
E2E = ROOT / "tests/zn_agent/e2e/test_e2e29_one_model_multi_worker.py"
REGRESSION = ROOT / "tests/zn_agent/core/test_worker_delegation_admission.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise RuntimeError(f"{label}: expected exactly one old block, found {count}")


source = COMPLETION.read_text(encoding="utf-8")
source = replace_once(
    source,
    "    def _build_cognition_request(self, event, impasse, required, deliberation=None):\n",
    """    @staticmethod
    def _root_requests_delegated_worker_sequence(root: WorkItem) -> bool:
        text = " ".join(str(root.objective or "").casefold().split())
        required_groups = (
            ("调研", "研究", "research"),
            ("开发", "实现", "做出", "build", "implement", "develop"),
            ("review", "评审", "审查", "复核"),
        )
        return all(any(marker in text for marker in markers) for markers in required_groups)

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
""",
    label="delegation admission helper",
)
source = replace_once(
    source,
    """        request.context = {
            **dict(request.context or {}),
            "root_finish_contract": "current-plan-python-plus-persisted-read-verifier-v2",
        }
        return self._prepare_delegated_worker_request(event, root, request, completed)
""",
    """        request.context = {
            **dict(request.context or {}),
            "root_finish_contract": "current-plan-python-plus-persisted-read-verifier-v2",
        }
        if not self._root_requests_delegated_worker_sequence(root):
            return request
        return self._prepare_delegated_worker_request(event, root, request, completed)
""",
    label="delegation admission gate",
)
source = replace_once(
    source,
    """        profile = self._WORKER_SCOPE_PROFILES[worker.executor_kind]
        evidence = tuple(
            {
                "work_item_id": item.work_item_id,
                "objective": item.objective[:400],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:1200],
            }
            for item in completed[-6:]
            if item.work_item_id != child.work_item_id
        )
        refs: list[dict[str, Any]] = []
""",
    """        profile = self._WORKER_SCOPE_PROFILES[worker.executor_kind]
        accepted_evidence = [
            {
                "kind": "accepted_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective[:400],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:1200],
            }
            for item in completed[-6:]
            if item.work_item_id != child.work_item_id
        ]
        current_items = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.work_item_id != child.work_item_id
        ]
        failed_evidence = [
            {
                "kind": "failed_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective[:400],
                "acceptance": list(item.acceptance_criteria)[:4],
                "blocker": str(item.blocker or "")[:1200],
                "result": str(item.result or "")[:1200],
            }
            for item in current_items
            if item.status == "blocked"
            and (item.blocker or item.result)
            and not any(
                criterion.startswith("delegated_worker_evidence:")
                for criterion in item.acceptance_criteria
            )
        ][-4:]
        evidence = tuple((accepted_evidence + failed_evidence)[-8:])
        refs: list[dict[str, Any]] = []
""",
    label="failed real effect evidence",
)
source = replace_once(
    source,
    """        if executor_kind == "research":
            return " DELEGATED WORKER: research. Return ONLY the research_page form. You have managed-browser read authority only. Workspace writes, Terminal execution, messaging, releases, and Root acceptance are forbidden."
""",
    """        if executor_kind == "research":
            return (
                " DELEGATED WORKER: research. Return ONLY the research_page form. You have managed-browser "
                "read authority only. Use worker_context_pack.relevant_evidence, including prior failed real "
                "page effects, and do not blindly repeat an already failed URL or assumption; choose another "
                "authoritative primary source when the evidence supports that repair. Workspace writes, Terminal "
                "execution, messaging, releases, and Root acceptance are forbidden."
            )
""",
    label="research retry instruction",
)
COMPLETION.write_text(source, encoding="utf-8")

REGRESSION.write_text(
    '''from __future__ import annotations

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
''',
    encoding="utf-8",
)

e2e = E2E.read_text(encoding="utf-8")
e2e = replace_once(
    e2e,
    '''                    if pulse % 40 == 0:
                        runs = work_ledger.list_worker_runs(thread_id="e2e-29-real", limit=64)
                        print(
                            "ZN_E2E29_HEARTBEAT="
                            + json.dumps(
                                {
                                    "pulse": pulse,
                                    "stage": resident.store.get_working_state().stage,
                                    "workers": [
''',
    '''                    if pulse % 40 == 0:
                        runs = work_ledger.list_worker_runs(thread_id="e2e-29-real", limit=64)
                        state = resident.store.get_working_state()
                        blocked = [
                            item
                            for item in work_ledger.list_work_items("e2e-29-real", limit=256)
                            if item.status == "blocked" and (item.blocker or item.result)
                        ][-4:]
                        print(
                            "ZN_E2E29_HEARTBEAT="
                            + json.dumps(
                                {
                                    "pulse": pulse,
                                    "stage": state.stage,
                                    "local_failure": str(state.data.get("local_failure") or "")[:1600],
                                    "blocked_tail": [
                                        {
                                            "id": item.work_item_id,
                                            "criteria": list(item.acceptance_criteria)[:4],
                                            "blocker": str(item.blocker or item.result or "")[:1600],
                                        }
                                        for item in blocked
                                    ],
                                    "workers": [
''',
    label="real E2E diagnostic heartbeat",
)
E2E.write_text(e2e, encoding="utf-8")

for path in (COMPLETION, REGRESSION, E2E):
    py_compile.compile(str(path), doraise=True)

print("E2E29_PATCH_APPLIED=1")

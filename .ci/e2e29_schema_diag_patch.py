from __future__ import annotations

from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
COMPLETION = ROOT / 'runtime/python/zn_agent/core/broad_goal_completion_resident.py'
E2E = ROOT / 'tests/zn_agent/e2e/test_e2e29_one_model_multi_worker.py'
TEST = ROOT / 'tests/zn_agent/core/test_worker_write_repair_contract.py'


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise RuntimeError(f'{label}: expected exactly one old block, found {count}')

source = COMPLETION.read_text(encoding='utf-8')
source = replace_once(
    source,
    '''        if expected_action == "write_file":
            return (
                " DELEGATED WORKER: coding. Return ONLY the write_file form. The write must stay inside the "
                "attached workspace. Use worker_context_pack.relevant_evidence. If the latest failed_effect is "
                "a real command/output mismatch, repair the existing implementation or its observable test "
                "signal instead of replaying the same run unchanged. Git push, release, messaging, "
                "outside-workspace mutation, and Root acceptance are forbidden."
            )
''',
    '''        if expected_action == "write_file":
            return (
                " DELEGATED WORKER: coding. Return ONLY the write_file form. The write must stay inside the "
                "attached workspace. Use worker_context_pack.relevant_evidence. If the latest failed_effect is "
                "a real command/output mismatch, repair the existing implementation or its observable test "
                "signal instead of replaying the same run unchanged. V1 write_file is a COMPLETE replacement "
                "of exactly one target file, not a diff, patch, search/replace helper, or a script whose purpose "
                "is to patch another file. acceptance.kind must be text_equals; acceptance.path must exactly "
                "equal action.path; acceptance.expected_text must exactly equal action.content. When repairing "
                "an existing file, incorporate the repair directly into that complete replacement content. "
                "Git push, release, messaging, outside-workspace mutation, and Root acceptance are forbidden."
            )
''',
    label='write repair instruction',
)
source = replace_once(
    source,
    '''    def _proposal_contract_valid(self, event, root, expected_action: str, content: str) -> bool:
        if expected_action == "research_page":
            return self._parse_research_page_step(root, content) is not None
        if expected_action == "write_file":
            return self._parse_write_file_step(event, root, content) is not None
        if expected_action == "run_python":
            return self._parse_run_python_step(event, root, content) is not None
        return False

    @staticmethod
    def _proposal_action_kind(content: str) -> str | None:
''',
    '''    def _proposal_contract_valid(self, event, root, expected_action: str, content: str) -> bool:
        if expected_action == "research_page":
            return self._parse_research_page_step(root, content) is not None
        if expected_action == "write_file":
            return self._parse_write_file_step(event, root, content) is not None
        if expected_action == "run_python":
            return self._parse_run_python_step(event, root, content) is not None
        return False

    def _proposal_contract_failure_reason(self, event, root, expected_action: str, content: str) -> str:
        if expected_action != "write_file":
            return f"{expected_action} proposal failed its bounded schema/workspace validation"
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return "write_file proposal must contain exactly one zn_work_step JSON envelope"
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            return "write_file zn_work_step must be an object"
        objective = " ".join(str(step.get("objective") or "").strip().split())
        if not objective or len(objective) > 600:
            return "write_file objective must be non-empty and at most 600 characters"
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not isinstance(action, dict) or not isinstance(acceptance, dict):
            return "write_file action and acceptance must both be objects"
        if str(action.get("kind") or "").strip() != "write_file":
            return "write_file action.kind must be write_file"
        if str(acceptance.get("kind") or "").strip() != "text_equals":
            return "write_file acceptance.kind must be text_equals"
        relative_path = str(action.get("path") or "").strip()
        acceptance_path = str(acceptance.get("path") or "").strip()
        if not relative_path or relative_path != acceptance_path:
            return "write_file acceptance.path must exactly equal action.path"
        body = action.get("content")
        expected = acceptance.get("expected_text")
        if not isinstance(body, str) or not isinstance(expected, str):
            return "write_file action.content and acceptance.expected_text must both be strings"
        if body != expected:
            return "write_file acceptance.expected_text must exactly equal action.content"
        if len(body) > self._MAX_STEP_CONTENT:
            return "write_file complete replacement content exceeds the bounded size limit"
        rel = Path(relative_path)
        if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            return "write_file path must be a safe relative path inside the attached workspace"
        workspace = Path(str(event.payload.get("workspace_path") or "")).expanduser()
        try:
            root_path = workspace.resolve(strict=True)
            candidate = root_path.joinpath(*rel.parts)
            parent = candidate.parent.resolve(strict=True)
            parent.relative_to(root_path)
            if candidate.exists():
                candidate.resolve(strict=True).relative_to(root_path)
        except (OSError, RuntimeError, ValueError):
            return "write_file target parent must already exist inside the attached workspace"
        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return "write_file proposal belongs to a stale Work plan"
        return "write_file proposal failed bounded workspace/text_equals validation"

    @staticmethod
    def _proposal_action_kind(content: str) -> str | None:
''',
    label='proposal diagnostic helper',
)
source = replace_once(
    source,
    '''            if not valid:
                status = "scope_rejected" if action_kind and action_kind != expected_action else "schema_rejected"
                failure = (
                    f"ZN rejected delegated {str(delegated.get('executor_kind') or 'worker')} proposal: "
                    f"expected {expected_action or 'bounded schema'}, received {action_kind or 'unstructured result'}; "
                    "WorkerRun self-report cannot expand tool/authority scope or accept Root Work"
                )
''',
    '''            if not valid:
                status = "scope_rejected" if action_kind and action_kind != expected_action else "schema_rejected"
                detail = (
                    "proposal action kind exceeded the delegated scope"
                    if status == "scope_rejected"
                    else self._proposal_contract_failure_reason(
                        event,
                        root,
                        expected_action,
                        increment.content,
                    )
                )
                failure = (
                    f"ZN rejected delegated {str(delegated.get('executor_kind') or 'worker')} proposal: "
                    f"expected {expected_action or 'bounded schema'}, received {action_kind or 'unstructured result'}; "
                    f"{detail}; WorkerRun self-report cannot expand tool/authority scope or accept Root Work"
                )
''',
    label='schema rejection detail',
)
COMPLETION.write_text(source, encoding='utf-8')

TEST.write_text(r'''from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerWriteRepairContractTests(unittest.TestCase):
    def test_write_repair_instruction_requires_complete_replacement_and_exact_text(self) -> None:
        instruction = BroadGoalCompletionResidentRuntime._delegated_worker_instruction(
            "coding", "write_file"
        )
        self.assertIn("COMPLETE replacement", instruction)
        self.assertIn("acceptance.expected_text must exactly equal action.content", instruction)
        self.assertIn("not a diff, patch, search/replace helper", instruction)

    def test_same_kind_invalid_write_reports_exact_schema_failure_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            target = workspace / "app.py"
            target.write_text("print('before')\n", encoding="utf-8")
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="write-repair", title="Write repair")
                ledger.attach_workspace("write-repair", workspace, name="Workspace")
                _, event = ledger.start(
                    "write-repair",
                    "Research, implement, and review a bounded local product.",
                    acceptance_criteria=["runnable product and independent review"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Repair the implementation",
                    acceptance_criteria=["delegated_worker_evidence: coding/write_file"],
                )
                profile = resident._WORKER_SCOPE_PROFILES["coding"]
                worker = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="coding",
                    tool_scope=profile["tool_scope"],
                    authority_scope=profile["authority_scope"],
                )
                proposal = json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "repair app",
                            "action": {
                                "kind": "write_file",
                                "path": "app.py",
                                "content": "print('after')\n",
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "app.py",
                                "expected_text": "print('different')\n",
                            },
                        }
                    }
                )
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="imp-write-repair",
                    source="external:only-route",
                    question="repair",
                    content=proposal,
                    quality=1.0,
                    confidence=1.0,
                )
                state = resident.store.get_working_state()
                state.data["cognition_request"] = {
                    "context": {
                        "delegated_worker": {
                            "worker_run_id": worker.worker_run_id,
                            "work_item_id": child.work_item_id,
                            "root_work_item_id": root.work_item_id,
                            "plan_version": root.plan_version,
                            "executor_kind": "coding",
                            "expected_action": "write_file",
                            "model_goal_id": worker.model_goal_id,
                        }
                    }
                }
                state.data["cognitive_increment"] = increment.to_dict()
                marker = object()
                with patch.object(resident, "_accept_borrowed_increment", return_value=None), patch.object(
                    resident, "_return_to_investigation_after_rejection", return_value=marker
                ):
                    result = resident._cognition_integration_step(event, state, readiness=None)
                self.assertIs(result, marker)
                rejected = ledger.worker_run(worker.worker_run_id)
                assert rejected is not None
                self.assertEqual(rejected.verification_status, "schema_rejected")
                self.assertEqual(rejected.model_route_id, "only-route")
                self.assertIn(
                    "acceptance.expected_text must exactly equal action.content",
                    rejected.error or "",
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "print('before')\n")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
''', encoding='utf-8')

e2e = E2E.read_text(encoding='utf-8')
e2e = replace_once(
    e2e,
    '''                                        {
                                            "id": run.worker_run_id,
                                            "kind": run.executor_kind,
                                            "state": run.state,
                                            "route": run.model_route_id,
                                            "verification": run.verification_status,
                                        }
                                        for run in runs
''',
    '''                                        {
                                            "id": run.worker_run_id,
                                            "kind": run.executor_kind,
                                            "state": run.state,
                                            "route": run.model_route_id,
                                            "verification": run.verification_status,
                                            "error": str(run.error or "")[:1200],
                                            "result": str(run.result_summary or "")[:1200],
                                        }
                                        for run in runs[-12:]
''',
    label='heartbeat worker diagnostics',
)
e2e = replace_once(
    e2e,
    '''                self.assertIsNotNone(terminal, "E2E-29 did not reach evidence-bound Root completion")
                assert terminal is not None
                self.assertTrue(terminal.success, terminal.reason)
''',
    '''                if terminal is not None:
                    print(
                        "ZN_E2E29_TERMINAL="
                        + json.dumps(
                            {
                                "success": terminal.success,
                                "reason": str(terminal.reason or "")[:4000],
                                "response": str(terminal.response or "")[:4000],
                                "model_invocations": terminal.model_invocations,
                                "execution_path": terminal.execution_path.value,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                self.assertIsNotNone(terminal, "E2E-29 did not reach evidence-bound Root completion")
                assert terminal is not None
                self.assertTrue(terminal.success, terminal.reason)
''',
    label='terminal diagnostic',
)
E2E.write_text(e2e, encoding='utf-8')

for path in (COMPLETION, TEST, E2E):
    py_compile.compile(str(path), doraise=True)
print('E2E29_SCHEMA_DIAG_PATCH_APPLIED=1')

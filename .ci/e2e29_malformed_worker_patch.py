from __future__ import annotations

from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / 'runtime/python/zn_agent/core/broad_goal_autonomous_resident.py'
COMPLETION = ROOT / 'runtime/python/zn_agent/core/broad_goal_completion_resident.py'
TEST = ROOT / 'tests/zn_agent/core/test_worker_malformed_retry_identity.py'


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise RuntimeError(f'{label}: expected exactly one old block, found {count}')

auto = AUTO.read_text(encoding='utf-8')
auto = replace_once(
    auto,
    '''        state.data["local_failure"] = failure
        state.data["structured_proposal_rejection"] = {
            "increment_id": increment.increment_id,
            "reason": failure,
        }
        investigation = self.investigator.current(event.event_id)
''',
    '''        state.data["local_failure"] = failure
        state.data["structured_proposal_rejection"] = {
            "increment_id": increment.increment_id,
            "reason": failure,
        }
        rejection_hook = getattr(self, "_on_malformed_structured_proposal_rejection", None)
        if callable(rejection_hook):
            rejection_hook(event, state, increment, failure)
        investigation = self.investigator.current(event.event_id)
''',
    label='autonomous malformed rejection hook',
)
AUTO.write_text(auto, encoding='utf-8')

completion = COMPLETION.read_text(encoding='utf-8')
completion = replace_once(
    completion,
    '''    def _return_to_investigation_after_rejection(self, event, state, failure: str):
        state.data["local_failure"] = failure
''',
    '''    def _on_malformed_structured_proposal_rejection(
        self,
        event,
        state,
        increment: CognitiveIncrement,
        failure: str,
    ) -> None:
        delegated = self._delegated_meta_from_state(state)
        if delegated is None:
            return
        worker_run_id = str(delegated.get("worker_run_id") or "").strip()
        work_item_id = str(delegated.get("work_item_id") or "").strip()
        worker = self.work_ledger.worker_run(worker_run_id)
        route_id = self._route_id_from_increment(increment)
        if worker is not None and worker.state in {"queued", "running"}:
            self.work_ledger.fail_worker_run(
                worker.worker_run_id,
                error=failure,
                result_summary=increment.content,
                claimed_completion=self._claims_completion(increment.content),
                verification_status="schema_rejected",
                model_route_id=route_id,
                metrics={
                    "source": increment.source,
                    "increment_id": increment.increment_id,
                    "malformed_envelope": True,
                },
            )
        if work_item_id:
            try:
                self.work_ledger.block_child_item(work_item_id, blocker=failure)
            except ValueError:
                pass

    def _return_to_investigation_after_rejection(self, event, state, failure: str):
        state.data["local_failure"] = failure
''',
    label='delegated malformed rejection ownership',
)
COMPLETION.write_text(completion, encoding='utf-8')

TEST.write_text(r'''from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.provider_bridge import build_resident_runtime


class WorkerMalformedRetryIdentityTests(unittest.TestCase):
    def test_malformed_delegated_result_terminates_worker_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="malformed-worker", title="Malformed worker")
                ledger.attach_workspace("malformed-worker", workspace, name="Workspace")
                _, event = ledger.start(
                    "malformed-worker",
                    "Research, implement, and review a bounded local product.",
                    acceptance_criteria=["runnable product", "independent review"],
                )
                root = ledger.work_item_for_event(event.event_id)
                assert root is not None
                child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Implement bounded repair",
                    acceptance_criteria=["delegated_worker_evidence: coding/write_file"],
                )
                profile = resident._WORKER_SCOPE_PROFILES["coding"]
                first = ledger.start_worker_run(
                    work_item_id=child.work_item_id,
                    executor_kind="coding",
                    tool_scope=profile["tool_scope"],
                    authority_scope=profile["authority_scope"],
                )
                state = resident.store.get_working_state()
                state.data["cognition_request"] = {
                    "request_id": first.cognition_request_id,
                    "context": {
                        "delegated_worker": {
                            "worker_run_id": first.worker_run_id,
                            "work_item_id": child.work_item_id,
                            "root_work_item_id": root.work_item_id,
                            "plan_version": root.plan_version,
                            "executor_kind": "coding",
                            "expected_action": "write_file",
                            "model_goal_id": first.model_goal_id,
                        }
                    },
                }
                increment = CognitiveIncrement.create(
                    event_id=event.event_id,
                    impasse_id="imp-malformed",
                    source="external:only-route",
                    question="repair",
                    content='{"zn_work_step":{"objective":"repair","action":{"kind":"write_file"}',
                    quality=1.0,
                    confidence=1.0,
                )
                resident._reject_malformed_structured_proposal(event, state, increment)

                failed = ledger.worker_run(first.worker_run_id)
                assert failed is not None
                self.assertEqual(failed.state, "failed")
                self.assertEqual(failed.verification_status, "schema_rejected")
                self.assertEqual(failed.model_route_id, "only-route")
                self.assertTrue(failed.metrics.get("malformed_envelope"))
                blocked = next(
                    item for item in ledger.list_work_items(root.work_thread_id)
                    if item.work_item_id == child.work_item_id
                )
                self.assertEqual(blocked.status, "blocked")

                items = ledger.list_work_items(root.work_thread_id, limit=256)
                runs = ledger.list_worker_runs(thread_id=root.work_thread_id, limit=256)
                phase = resident._next_worker_phase(root, items, runs)
                self.assertEqual(phase, ("research", "research_page"))

                research_profile = resident._WORKER_SCOPE_PROFILES["research"]
                retry_child = ledger.create_child_item(
                    root_work_item_id=root.work_item_id,
                    objective="Retry with a fresh bounded request",
                    acceptance_criteria=["delegated_worker_evidence: research/research_page"],
                )
                retry = ledger.start_worker_run(
                    work_item_id=retry_child.work_item_id,
                    executor_kind="research",
                    tool_scope=research_profile["tool_scope"],
                    authority_scope=research_profile["authority_scope"],
                )
                self.assertNotEqual(first.worker_run_id, retry.worker_run_id)
                self.assertNotEqual(first.cognition_request_id, retry.cognition_request_id)
                self.assertNotEqual(first.model_goal_id, retry.model_goal_id)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
''', encoding='utf-8')

for path in (AUTO, COMPLETION, TEST):
    py_compile.compile(str(path), doraise=True)
print('E2E29_MALFORMED_WORKER_PATCH_APPLIED=1')

from __future__ import annotations

from pathlib import Path
import py_compile


ROOT = Path(__file__).resolve().parents[1]
COMPLETION = ROOT / "runtime/python/zn_agent/core/broad_goal_completion_resident.py"
E2E = ROOT / "tests/zn_agent/e2e/test_e2e29_one_model_multi_worker.py"
REGRESSION = ROOT / "tests/zn_agent/core/test_worker_phase_repair.py"


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
    '''    def _next_worker_phase(self, root, items, runs):
        current_children = [
            item
            for item in items
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        completed_run_items: dict[str, WorkerRun] = {}
        for run in runs:
            item = next(
                (value for value in current_children if value.work_item_id == run.work_item_id),
                None,
            )
            if run.state == "completed" and item is not None and item.status == "completed":
                completed_run_items[run.work_item_id] = run
        if not any(run.executor_kind == "research" for run in completed_run_items.values()):
            return "research", "research_page"
        real_completed = [item for item in current_children if item.status == "completed"]
        if not any(
            any(criterion.startswith("text_equals:") for criterion in item.acceptance_criteria)
            for item in real_completed
        ):
            return "coding", "write_file"
        if not any(
            any(criterion.startswith("command_exit:") for criterion in item.acceptance_criteria)
            for item in real_completed
        ):
            return "coding", "run_python"
        if not any(run.executor_kind == "review" for run in completed_run_items.values()):
            return "review", "run_python"
        return None
''',
    '''    def _next_worker_phase(self, root, items, runs):
        current_children = [
            item
            for item in items
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        positions = {
            item.work_item_id: index
            for index, item in enumerate(current_children)
        }
        item_by_id = {item.work_item_id: item for item in current_children}
        accepted_run_items: dict[str, WorkerRun] = {}
        for run in runs:
            item = item_by_id.get(run.work_item_id)
            if (
                run.state == "completed"
                and run.verification_status == "accepted"
                and item is not None
                and item.status == "completed"
            ):
                accepted_run_items[run.work_item_id] = run
        if not any(run.executor_kind == "research" for run in accepted_run_items.values()):
            return "research", "research_page"

        def has_criterion(item: WorkItem, prefix: str) -> bool:
            return any(
                criterion.startswith(prefix)
                for criterion in item.acceptance_criteria
            )

        real_children = [
            item
            for item in current_children
            if not has_criterion(item, "delegated_worker_evidence:")
        ]
        completed_writes = [
            item
            for item in real_children
            if item.status == "completed" and has_criterion(item, "text_equals:")
        ]
        if not completed_writes:
            return "coding", "write_file"

        completed_commands = [
            item
            for item in real_children
            if item.status == "completed" and has_criterion(item, "command_exit:")
        ]
        blocked_commands = [
            item
            for item in real_children
            if item.status == "blocked" and has_criterion(item, "command_exit:")
        ]
        latest_write = completed_writes[-1]
        latest_completed_command = completed_commands[-1] if completed_commands else None
        latest_blocked_command = blocked_commands[-1] if blocked_commands else None

        if latest_completed_command is None:
            if (
                latest_blocked_command is not None
                and positions[latest_blocked_command.work_item_id]
                > positions[latest_write.work_item_id]
            ):
                return "coding", "write_file"
            return "coding", "run_python"

        latest_write_position = positions[latest_write.work_item_id]
        latest_completed_command_position = positions[latest_completed_command.work_item_id]
        if latest_write_position > latest_completed_command_position:
            return "coding", "run_python"
        if (
            latest_blocked_command is not None
            and positions[latest_blocked_command.work_item_id]
            > max(latest_write_position, latest_completed_command_position)
        ):
            return "coding", "write_file"

        if not any(run.executor_kind == "review" for run in accepted_run_items.values()):
            return "review", "run_python"
        return None
''',
    label="delegated repair phase machine",
)
source = replace_once(
    source,
    '''        if executor_kind == "review":
            return " DELEGATED WORKER: review. Return ONLY the run_python form against an existing workspace artifact. You may inspect/run verification but must not write workspace files, mutate Git, push/release/message, or accept the Root."
        if expected_action == "write_file":
            return " DELEGATED WORKER: coding. Return ONLY the write_file form. The write must stay inside the attached workspace. Git push, release, messaging, outside-workspace mutation, and Root acceptance are forbidden."
        return " DELEGATED WORKER: coding. Return ONLY the run_python form for an existing workspace artifact. ZN chooses the Python interpreter. Git push, release, messaging, outside-workspace mutation, and Root acceptance are forbidden."
''',
    '''        if executor_kind == "review":
            return (
                " DELEGATED WORKER: review. Return ONLY the run_python form against an existing workspace "
                "artifact. Use worker_context_pack.relevant_evidence and choose a root-relevant output_contains "
                "fragment that the existing artifact should really emit; do not invent output to force success. "
                "A failed review is durable evidence and ZN may route it back to a coding repair phase. You may "
                "inspect/run verification but must not write workspace files, mutate Git, push/release/message, "
                "or accept the Root."
            )
        if expected_action == "write_file":
            return (
                " DELEGATED WORKER: coding. Return ONLY the write_file form. The write must stay inside the "
                "attached workspace. Use worker_context_pack.relevant_evidence. If the latest failed_effect is "
                "a real command/output mismatch, repair the existing implementation or its observable test "
                "signal instead of replaying the same run unchanged. Git push, release, messaging, "
                "outside-workspace mutation, and Root acceptance are forbidden."
            )
        return (
            " DELEGATED WORKER: coding. Return ONLY the run_python form for an existing workspace artifact. "
            "ZN chooses the Python interpreter. Use worker_context_pack.relevant_evidence and set "
            "output_contains only to root-relevant output that this exact artifact is expected to emit; do not "
            "invent fragments merely to make verification pass. If real execution proves a write repair is "
            "needed, that failed effect must remain evidence and ZN will route the next coding phase back to "
            "write_file. Git push, release, messaging, outside-workspace mutation, and Root acceptance are "
            "forbidden."
        )
''',
    label="delegated repair instructions",
)
COMPLETION.write_text(source, encoding="utf-8")

REGRESSION.write_text(
    '''from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.steerable_work import WorkItem


class WorkerPhaseRepairTests(unittest.TestCase):
    @staticmethod
    def _item(item_id: str, *, status: str, criterion: str) -> WorkItem:
        return WorkItem(
            work_item_id=item_id,
            work_thread_id="phase-repair",
            parent_work_item_id="root",
            title=item_id,
            objective=item_id,
            status=status,
            plan_version=1,
            acceptance_criteria=[criterion],
        )

    @staticmethod
    def _run(item_id: str, kind: str, verification: str = "accepted"):
        return SimpleNamespace(
            work_item_id=item_id,
            executor_kind=kind,
            state="completed",
            verification_status=verification,
        )

    def test_failed_command_routes_back_to_write_then_run(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        first_write = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        failed_run = self._item(
            "run-failed",
            status="blocked",
            criterion="command_exit: 0; output_contains: expected",
        )
        runs = [self._run("research-meta", "research")]

        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, failed_run],
            runs,
        )
        self.assertEqual(phase, ("coding", "write_file"))

        repair_write = self._item(
            "write-2",
            status="completed",
            criterion="text_equals: app.py",
        )
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, failed_run, repair_write],
            runs,
        )
        self.assertEqual(phase, ("coding", "run_python"))

    def test_failed_review_routes_to_coding_repair_before_reviewing_again(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        first_write = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        accepted_run = self._item(
            "run-1",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        failed_review_effect = self._item(
            "review-effect-failed",
            status="blocked",
            criterion="command_exit: 0; output_contains: root-signal",
        )
        runs = [self._run("research-meta", "research")]

        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, accepted_run, failed_review_effect],
            runs,
        )
        self.assertEqual(phase, ("coding", "write_file"))

        repair_write = self._item(
            "write-2",
            status="completed",
            criterion="text_equals: app.py",
        )
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, first_write, accepted_run, failed_review_effect, repair_write],
            runs,
        )
        self.assertEqual(phase, ("coding", "run_python"))

    def test_accepted_review_finishes_delegated_sequence(self) -> None:
        root = SimpleNamespace(work_item_id="root", plan_version=1)
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_page",
        )
        write_effect = self._item(
            "write-1",
            status="completed",
            criterion="text_equals: app.py",
        )
        coding_effect = self._item(
            "run-1",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        review_meta = self._item(
            "review-meta",
            status="completed",
            criterion="delegated_worker_evidence: review/run_python",
        )
        review_effect = self._item(
            "review-effect",
            status="completed",
            criterion="command_exit: 0; output_contains: ok",
        )
        runs = [
            self._run("research-meta", "research"),
            self._run("review-meta", "review"),
        ]
        phase = BroadGoalCompletionResidentRuntime._next_worker_phase(
            None,
            root,
            [research_meta, write_effect, coding_effect, review_meta, review_effect],
            runs,
        )
        self.assertIsNone(phase)


if __name__ == "__main__":
    unittest.main(verbosity=2)
''',
    encoding="utf-8",
)

e2e = E2E.read_text(encoding="utf-8")
e2e = replace_once(
    e2e,
    '''                self.assertTrue(all(run.work_item_id for run in current_runs))
                self.assertTrue(all(run.verification_status == "accepted" for run in current_runs))

                research = next(run for run in current_runs if run.executor_kind == "research")
                coding = next(run for run in current_runs if run.executor_kind == "coding")
                review = next(run for run in current_runs if run.executor_kind == "review")
''',
    '''                self.assertTrue(all(run.work_item_id for run in current_runs))
                self.assertTrue(all(run.verification_status != "pending" for run in current_runs))
                accepted_current_runs = [
                    run for run in current_runs
                    if run.verification_status == "accepted"
                ]
                accepted_kinds = {run.executor_kind for run in accepted_current_runs}
                self.assertTrue(
                    {"research", "coding", "review"}.issubset(accepted_kinds),
                    "each delegated role needs at least one verified accepted run; failed attempts remain durable evidence",
                )

                research = next(
                    run for run in accepted_current_runs
                    if run.executor_kind == "research"
                )
                coding = next(
                    run for run in accepted_current_runs
                    if run.executor_kind == "coding"
                )
                review = next(
                    run for run in accepted_current_runs
                    if run.executor_kind == "review"
                )
''',
    label="real E2E failed WorkerRun provenance assertion",
)
E2E.write_text(e2e, encoding="utf-8")

for path in (COMPLETION, REGRESSION, E2E):
    py_compile.compile(str(path), doraise=True)

print("E2E29_PHASE_REPAIR_PATCH_APPLIED=1")

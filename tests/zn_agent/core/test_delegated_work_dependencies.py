from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.steerable_work import WorkItem


class DelegatedWorkDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root_dir = Path(self.tmp.name)
        self.db = root_dir / "kernel.db"
        self.workspace = root_dir / "workspace"
        self.workspace.mkdir()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.ledger = self.resident.work_ledger
        self.ledger.create_thread(thread_id="dependencies", title="Dependencies")
        self.ledger.attach_workspace("dependencies", self.workspace, name="Workspace")
        _, self.event = self.ledger.start(
            "dependencies",
            "Execute bounded dependency-aware delegated work.",
            acceptance_criteria=["fresh independent root verification"],
        )
        self.root = self.ledger.work_item_for_event(self.event.event_id)
        assert self.root is not None

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    def _child(
        self,
        name: str,
        *,
        root: WorkItem | None = None,
        dependency_ids=(),
    ) -> WorkItem:
        parent = root or self.root
        return self.ledger.create_child_item(
            root_work_item_id=parent.work_item_id,
            objective=f"{name} objective",
            acceptance_criteria=[f"delegated_worker_evidence: research/{name}"],
            title=name,
            dependency_ids=dependency_ids,
        )

    def _start_research(self, item: WorkItem):
        return self.ledger.start_worker_run(
            work_item_id=item.work_item_id,
            executor_kind="research",
            tool_scope=("managed_browser.read",),
            authority_scope=("web_read",),
        )

    def _persisted_item(self, work_item_id: str) -> WorkItem:
        item = self.ledger._work_item_by_id(work_item_id)
        assert item is not None
        return item

    def test_dependency_free_child_is_backward_compatible(self) -> None:
        child = self._child("independent")
        self.assertEqual(child.dependency_ids, [])
        readiness = self.ledger.dependency_readiness(child.work_item_id)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.state, "ready")
        run = self._start_research(child)
        self.assertEqual(run.work_item_id, child.work_item_id)
        self.assertEqual(run.tool_scope, ("managed_browser.read",))
        self.assertEqual(run.authority_scope, ("web_read",))
        self.assertEqual(self.root.dependency_ids, [])

    def test_unmet_dependency_blocks_worker_run_before_model_or_attempt_creation(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        before = self.ledger.list_worker_runs(work_item_id=downstream.work_item_id)
        with patch.object(
            self.resident.kernel,
            "run_goal",
            side_effect=AssertionError("model/provider execution must not be reached"),
        ) as run_goal:
            with self.assertRaisesRegex(ValueError, "dependency readiness rejected waiting"):
                self._start_research(downstream)
        run_goal.assert_not_called()
        after = self.ledger.list_worker_runs(work_item_id=downstream.work_item_id)
        self.assertEqual(before, after)
        self.assertEqual(self._persisted_item(upstream.work_item_id).work_item_id, upstream.work_item_id)
        self.assertEqual(self._persisted_item(downstream.work_item_id).work_item_id, downstream.work_item_id)

    def test_only_work_owned_completed_dependency_unlocks_downstream(self) -> None:
        upstream = self._child("upstream")
        upstream_run = self._start_research(upstream)
        self.ledger.complete_worker_run(
            upstream_run.worker_run_id,
            result_summary="worker says done",
            verification_status="scope_admitted",
        )
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        self.assertFalse(self.ledger.dependency_readiness(downstream.work_item_id).ready)

        self.ledger.complete_child_item(upstream.work_item_id, result="accepted upstream result")
        readiness = self.ledger.dependency_readiness(downstream.work_item_id)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.state, "ready")
        run = self._start_research(downstream)
        self.assertEqual(run.work_item_id, downstream.work_item_id)

    def test_blocked_upstream_waits_until_real_completion(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        self.ledger.block_child_item(upstream.work_item_id, blocker="temporary blocker")
        readiness = self.ledger.dependency_readiness(downstream.work_item_id)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.state, "waiting")
        self.assertEqual(readiness.waiting_on, (upstream.work_item_id,))

        self.ledger.complete_child_item(upstream.work_item_id, result="retry produced accepted evidence")
        self.assertTrue(self.ledger.dependency_readiness(downstream.work_item_id).ready)

    def test_completion_cannot_bypass_unmet_dependency(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        with self.assertRaisesRegex(ValueError, "dependency readiness rejected waiting"):
            self.ledger.complete_child_item(downstream.work_item_id, result="fake completion")
        persisted = self._persisted_item(downstream.work_item_id)
        self.assertEqual(persisted.status, "running")
        self.assertIsNone(persisted.completed_at)

    def test_restart_restores_exact_dependency_identity_and_readiness(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        upstream_id = upstream.work_item_id
        downstream_id = downstream.work_item_id
        self.assertFalse(self.ledger.dependency_readiness(downstream_id).ready)

        self.resident.store.close()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.db)
        self.ledger = self.resident.work_ledger
        restored_upstream = self._persisted_item(upstream_id)
        restored_downstream = self._persisted_item(downstream_id)
        self.assertEqual(restored_upstream.work_item_id, upstream_id)
        self.assertEqual(restored_downstream.dependency_ids, [upstream_id])
        self.assertFalse(self.ledger.dependency_readiness(downstream_id).ready)

        self.ledger.complete_child_item(upstream_id, result="accepted after restart")
        self.assertTrue(self.ledger.dependency_readiness(downstream_id).ready)
        run = self._start_research(self._persisted_item(downstream_id))
        self.assertEqual(run.work_item_id, downstream_id)
        self.assertEqual(self._persisted_item(upstream_id).work_item_id, upstream_id)

    def test_cross_thread_dependency_is_rejected(self) -> None:
        self.ledger.create_thread(thread_id="other-thread", title="Other")
        _, other_event = self.ledger.start(
            "other-thread",
            "Other root",
            acceptance_criteria=["other verification"],
        )
        other_root = self.ledger.work_item_for_event(other_event.event_id)
        assert other_root is not None
        other_child = self._child("other-child", root=other_root)
        with self.assertRaisesRegex(ValueError, "current-plan sibling"):
            self._child("illegal-cross-thread", dependency_ids=(other_child.work_item_id,))

    def test_cross_root_dependency_is_rejected_even_in_same_thread_and_plan(self) -> None:
        other_root = WorkItem(
            work_item_id="item-test-second-root",
            work_thread_id=self.root.work_thread_id,
            title="Second Root",
            objective="Second root objective",
            status="running",
            plan_version=self.root.plan_version,
        )
        self.ledger._save_item(other_root)
        other_child = self._child("other-root-child", root=other_root)
        with self.assertRaisesRegex(ValueError, "current-plan sibling"):
            self._child("illegal-cross-root", dependency_ids=(other_child.work_item_id,))

    def test_cross_plan_dependency_is_rejected(self) -> None:
        old_child = self._child("old-plan-child")
        self.ledger._set_plan_version(self.root.work_thread_id, 2)
        self.ledger._supersede_items_before(self.root.work_thread_id, 2)
        new_root = WorkItem(
            work_item_id="item-test-plan-two-root",
            work_thread_id=self.root.work_thread_id,
            title="Plan two Root",
            objective="Plan two root objective",
            status="running",
            plan_version=2,
        )
        self.ledger._save_item(new_root)
        with self.assertRaisesRegex(ValueError, "current-plan sibling"):
            self._child(
                "illegal-cross-plan",
                root=new_root,
                dependency_ids=(old_child.work_item_id,),
            )

    def test_unknown_and_duplicate_dependencies_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self._child("unknown", dependency_ids=("item-does-not-exist",))
        upstream = self._child("upstream")
        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            self._child(
                "duplicate",
                dependency_ids=(upstream.work_item_id, upstream.work_item_id),
            )

    def test_dependency_vector_is_bounded(self) -> None:
        upstream = self._child("upstream")
        with self.assertRaisesRegex(ValueError, "bounded limit of 32"):
            self._child(
                "too-many",
                dependency_ids=tuple(f"item-{index:03d}" for index in range(33)),
            )
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            self._child("bad-id", dependency_ids=(f" {upstream.work_item_id}",))

    def test_malformed_persisted_dependency_json_fails_closed(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE work_items SET dependency_ids_json=? WHERE work_item_id=?",
                ("{not-json", downstream.work_item_id),
            )
            conn.commit()
        with self.assertRaisesRegex(RuntimeError, "dependency metadata is malformed"):
            self.ledger.dependency_readiness(downstream.work_item_id)
        with self.assertRaises(RuntimeError):
            self._start_research(downstream)
        self.assertEqual(
            self.ledger.list_worker_runs(work_item_id=downstream.work_item_id),
            [],
        )

    def test_cyclic_persisted_graph_is_invalid_and_never_ready(self) -> None:
        upstream = self._child("upstream")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            conn.execute(
                "UPDATE work_items SET dependency_ids_json=? WHERE work_item_id=?",
                (json.dumps([downstream.work_item_id]), upstream.work_item_id),
            )
            conn.commit()
        readiness = self.ledger.dependency_readiness(downstream.work_item_id)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.state, "invalid")
        self.assertIn("cycle", readiness.reason or "")
        with self.assertRaisesRegex(ValueError, "dependency readiness rejected invalid"):
            self._start_research(downstream)

    def test_dependency_completion_does_not_inherit_authority(self) -> None:
        upstream = self._child("upstream")
        upstream_run = self._start_research(upstream)
        self.ledger.complete_worker_run(
            upstream_run.worker_run_id,
            result_summary="research completed",
            verification_status="accepted",
        )
        self.ledger.complete_child_item(upstream.work_item_id, result="accepted research")
        downstream = self._child(
            "downstream",
            dependency_ids=(upstream.work_item_id,),
        )
        downstream_run = self.ledger.start_worker_run(
            work_item_id=downstream.work_item_id,
            executor_kind="coding",
            tool_scope=("workspace.write", "terminal.test"),
            authority_scope=("workspace_write", "terminal_verify"),
        )
        self.assertEqual(downstream_run.tool_scope, ("workspace.write", "terminal.test"))
        self.assertEqual(
            downstream_run.authority_scope,
            ("workspace_write", "terminal_verify"),
        )
        self.assertNotEqual(downstream_run.tool_scope, upstream_run.tool_scope)
        self.assertNotEqual(downstream_run.authority_scope, upstream_run.authority_scope)

    def test_fan_in_requires_all_direct_dependencies(self) -> None:
        first = self._child("first")
        second = self._child("second")
        fan_in = self._child(
            "fan-in",
            dependency_ids=(first.work_item_id, second.work_item_id),
        )
        self.ledger.complete_child_item(first.work_item_id, result="first accepted")
        waiting = self.ledger.dependency_readiness(fan_in.work_item_id)
        self.assertFalse(waiting.ready)
        self.assertEqual(waiting.waiting_on, (second.work_item_id,))

        self.ledger.complete_child_item(second.work_item_id, result="second accepted")
        ready = self.ledger.dependency_readiness(fan_in.work_item_id)
        self.assertTrue(ready.ready)
        self.assertEqual(ready.waiting_on, ())


if __name__ == "__main__":
    unittest.main(verbosity=2)

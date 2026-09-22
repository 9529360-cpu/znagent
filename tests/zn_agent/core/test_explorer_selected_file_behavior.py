from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.explorer_selected_file_behavior import _ACCEPTANCE
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.windows_explorer_selection import WindowsExplorerSelectionObservation


TASK = "我在 Windows 文件资源管理器里当前选中的这个文件是什么？告诉我文件名、大小和修改时间。"


def _observation(
    path: str,
    *,
    hwnd: int = 9001,
    size_bytes: int = 321,
    mtime_ns: int = 1_789_000_000_000_000_000,
) -> WindowsExplorerSelectionObservation:
    return WindowsExplorerSelectionObservation(
        platform_supported=True,
        explorer_foreground=True,
        available=True,
        disposition="selected_local_file",
        process_id=4242,
        window_handle=hwnd,
        selected_count=1,
        path=path,
        name=Path(path.replace("\\", "/")).name,
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        device=7,
        inode=8,
        observed_at="2026-09-16T00:00:00+00:00",
        source=("fixture",),
    )


class _SequenceSense:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = 0

    def probe(self):
        self.calls += 1
        if not self.observations:
            raise AssertionError("unexpected extra Explorer selection probe")
        return self.observations.pop(0)


class ExplorerSelectedFileBehaviorTests(unittest.TestCase):
    def test_natural_request_completes_zero_model_after_two_fresh_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                selected_path = r"C:\Users\Alice\Private\quarterly-plan.txt"
                sense = _SequenceSense([_observation(selected_path), _observation(selected_path)])
                resident.device_capabilities._explorer_selection_sense = sense

                thread_id = "explorer-selection"
                resident.work_ledger.create_thread(thread_id=thread_id, title="Explorer selection")
                _, run = resident.work_ledger.submit(thread_id, TASK)

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(sense.calls, 2)
                self.assertIn("quarterly-plan.txt", run.response)
                self.assertIn("321", run.response)
                self.assertIn("UTC", run.response)

                root = resident.work_ledger.work_item_for_event(run.event.event_id)
                self.assertIsNotNone(root)
                children = [
                    item
                    for item in resident.work_ledger.list_work_items(thread_id, limit=64)
                    if root is not None
                    and item.parent_work_item_id == root.work_item_id
                    and _ACCEPTANCE in item.acceptance_criteria
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "completed")
                evidence = json.loads(children[0].result)
                self.assertTrue(evidence["fresh_revalidated"])
                self.assertEqual(evidence["size_bytes"], 321)
                self.assertNotIn(selected_path, children[0].result)
                self.assertNotIn("quarterly-plan.txt", children[0].result)

                state = resident.store.get_working_state()
                durable_state = json.dumps(state.data, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(selected_path, durable_state)
                self.assertNotIn("quarterly-plan.txt", durable_state)
            finally:
                resident.store.close()

    def test_selection_drift_blocks_instead_of_reporting_stale_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                first = _observation(r"C:\Work\first.txt")
                second = _observation(r"C:\Work\second.txt")
                sense = _SequenceSense([first, second])
                resident.device_capabilities._explorer_selection_sense = sense

                thread_id = "explorer-selection-drift"
                resident.work_ledger.create_thread(thread_id=thread_id, title="Explorer selection drift")
                _, run = resident.work_ledger.submit(thread_id, TASK)

                self.assertFalse(run.success)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(sense.calls, 2)
                self.assertIn("发生了变化", run.response)
                self.assertNotIn("first.txt", run.response)
                self.assertNotIn("second.txt", run.response)

                root = resident.work_ledger.work_item_for_event(run.event.event_id)
                children = [
                    item
                    for item in resident.work_ledger.list_work_items(thread_id, limit=64)
                    if root is not None
                    and item.parent_work_item_id == root.work_item_id
                    and _ACCEPTANCE in item.acceptance_criteria
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].status, "blocked")
                self.assertNotIn("first.txt", children[0].result)
                self.assertNotIn("second.txt", children[0].result)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

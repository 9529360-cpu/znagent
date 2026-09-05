from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.provider_bridge import build_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class BroadGoalProtocolContractV2Tests(unittest.TestCase):
    def test_write_file_v2_is_compact_but_host_acceptance_stays_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            kernel = build_runtime(config={"model": {}}, store_path=root_dir / "kernel.db")
            resident = BroadGoalCompletionResidentRuntime(
                kernel=kernel,
                budget=CognitiveBudgetManager(),
            )
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            ledger.create_thread(thread_id="compact-v2", title="Compact V2")
            ledger.attach_workspace("compact-v2", workspace, name="Compact V2 Workspace")
            _, event = control.start(
                "compact-v2",
                "Create one exact local artifact.",
                payload={"model_policy": "on_demand"},
                acceptance_criteria=["an exact artifact exists"],
            )
            try:
                root = resident._criterion_bound_root(event)
                self.assertIsNotNone(root)
                assert root is not None
                body = 'print("READY")\n'

                compact = {
                    "zn_work_step": {
                        "objective": "write the probe",
                        "action": {
                            "kind": "write_file",
                            "path": "probe.py",
                            "content": body,
                        },
                    }
                }
                parsed = resident._parse_write_file_step(
                    event, root, json.dumps(compact)
                )
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertEqual(parsed["relative_path"], "probe.py")
                self.assertEqual(parsed["content"], body)

                legacy_exact = {
                    "zn_work_step": {
                        "objective": "write the probe",
                        "action": {
                            "kind": "write_file",
                            "path": "probe.py",
                            "content": body,
                        },
                        "acceptance": {
                            "kind": "text_equals",
                            "path": "probe.py",
                            "expected_text": body,
                        },
                    }
                }
                self.assertIsNotNone(
                    resident._parse_write_file_step(
                        event, root, json.dumps(legacy_exact)
                    )
                )

                weaker = {
                    "zn_work_step": {
                        "objective": "write the probe",
                        "action": {
                            "kind": "write_file",
                            "path": "probe.py",
                            "content": body,
                        },
                        "acceptance": {
                            "kind": "file_exists",
                            "path": "probe.py",
                        },
                    }
                }
                self.assertIsNone(
                    resident._parse_write_file_step(event, root, json.dumps(weaker))
                )

                mismatched = {
                    "zn_work_step": {
                        "objective": "write the probe",
                        "action": {
                            "kind": "write_file",
                            "path": "probe.py",
                            "content": body,
                        },
                        "acceptance": {
                            "kind": "text_equals",
                            "path": "probe.py",
                            "expected_text": "different",
                        },
                    }
                }
                self.assertIsNone(
                    resident._parse_write_file_step(
                        event, root, json.dumps(mismatched)
                    )
                )

                escaped = {
                    "zn_work_step": {
                        "objective": "escape workspace",
                        "action": {
                            "kind": "write_file",
                            "path": "../outside.py",
                            "content": body,
                        },
                    }
                }
                self.assertIsNone(
                    resident._parse_write_file_step(event, root, json.dumps(escaped))
                )

                fenced = "```json\n" + json.dumps(compact) + "\n```"
                self.assertIsNone(
                    resident._parse_write_file_step(event, root, fenced)
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

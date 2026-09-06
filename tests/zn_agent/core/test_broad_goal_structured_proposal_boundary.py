from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.structured_proposal import (
    looks_like_structured_payload,
    parse_exact_json_payload,
)
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class BroadGoalStructuredProposalBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.script = self.workspace / "app.py"
        self.script.write_text('print("READY")\n', encoding="utf-8")
        self.resident = build_resident_runtime(
            config={"model": {}},
            store_path=self.root / "kernel.db",
        )
        self.control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(self.resident))
        self.ledger = self.control.ledger
        self.ledger.create_thread(thread_id="proposal-boundary", title="Proposal Boundary")
        self.ledger.attach_workspace(
            "proposal-boundary",
            self.workspace,
            name="Proposal Boundary Workspace",
        )
        _, self.event = self.control.start(
            "proposal-boundary",
            "Build and run one tiny local artifact.",
            acceptance_criteria=["a later independent verifier still owns Root completion"],
        )
        self.root_item = self.ledger.work_item_for_event(self.event.event_id)
        assert self.root_item is not None

    def tearDown(self) -> None:
        self.resident.store.close()
        self.tmp.cleanup()

    @staticmethod
    def _write_payload() -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": "write one exact artifact",
                    "action": {
                        "kind": "write_file",
                        "path": "note.txt",
                        "content": "hello\n",
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": "note.txt",
                        "expected_text": "hello\n",
                    },
                }
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _run_payload() -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": "run the existing artifact",
                    "action": {
                        "kind": "run_python",
                        "path": "app.py",
                        "args": [],
                    },
                    "acceptance": {
                        "kind": "command",
                        "expected_exit_code": 0,
                        "output_contains": ["READY"],
                    },
                }
            },
            ensure_ascii=False,
        )

    def test_bare_and_fenced_write_file_are_recognized(self) -> None:
        bare = self._write_payload()
        fenced = f"```json\n{bare}\n```"
        self.assertIsNotNone(
            self.resident._parse_write_file_step(self.event, self.root_item, bare)
        )
        self.assertIsNotNone(
            self.resident._parse_write_file_step(self.event, self.root_item, fenced)
        )

    def test_bare_and_fenced_run_python_are_recognized(self) -> None:
        bare = self._run_payload()
        fenced = f"```json\n{bare}\n```"
        self.assertIsNotNone(
            self.resident._parse_run_python_step(self.event, self.root_item, bare)
        )
        self.assertIsNotNone(
            self.resident._parse_run_python_step(self.event, self.root_item, fenced)
        )
        self.assertEqual(parse_exact_json_payload(fenced), parse_exact_json_payload(bare))

    def test_surrounding_whitespace_is_allowed_but_prose_extraction_is_forbidden(self) -> None:
        bare = self._write_payload()
        self.assertIsNotNone(
            self.resident._parse_write_file_step(
                self.event,
                self.root_item,
                f" \n\t{bare}\n \t",
            )
        )
        prose = f"Here is the action I recommend: {bare}"
        self.assertIsNone(parse_exact_json_payload(prose))
        self.assertIsNone(
            self.resident._parse_write_file_step(self.event, self.root_item, prose)
        )
        self.assertFalse(
            looks_like_structured_payload(prose, top_level_key="zn_work_step")
        )

    def test_multiple_json_or_duplicate_action_proposals_fail_closed(self) -> None:
        first = self._write_payload()
        second = self._run_payload()
        concatenated = first + "\n" + second
        self.assertIsNone(parse_exact_json_payload(concatenated))
        self.assertTrue(
            looks_like_structured_payload(concatenated, top_level_key="zn_work_step")
        )
        self.assertIsNone(
            self.resident._parse_write_file_step(
                self.event,
                self.root_item,
                concatenated,
            )
        )
        self.assertIsNone(
            self.resident._parse_run_python_step(
                self.event,
                self.root_item,
                concatenated,
            )
        )

        duplicate_key = (
            '{"zn_work_step":{"objective":"first"},'
            '"zn_work_step":{"objective":"second"}}'
        )
        self.assertIsNone(parse_exact_json_payload(duplicate_key))
        self.assertTrue(
            looks_like_structured_payload(duplicate_key, top_level_key="zn_work_step")
        )

        two_fences = f"```json\n{first}\n```\n```json\n{second}\n```"
        self.assertIsNone(parse_exact_json_payload(two_fences))
        self.assertTrue(
            looks_like_structured_payload(two_fences, top_level_key="zn_work_step")
        )

    def test_malformed_fence_and_wrong_schema_never_execute(self) -> None:
        malformed = (
            "```json\n"
            '{"zn_work_step":{"objective":"broken","action":{"kind":"write_file"}}'
            "\n```"
        )
        self.assertIsNone(parse_exact_json_payload(malformed))
        self.assertTrue(
            looks_like_structured_payload(malformed, top_level_key="zn_work_step")
        )
        self.assertIsNone(
            self.resident._parse_write_file_step(
                self.event,
                self.root_item,
                malformed,
            )
        )

        wrong_schema = json.dumps(
            {
                "zn_work_step": {
                    "objective": "not a permitted action schema",
                    "action": {"kind": "delete_file", "path": "note.txt"},
                    "acceptance": {"kind": "text_equals", "path": "note.txt", "expected_text": ""},
                }
            }
        )
        self.assertIsNone(
            self.resident._parse_write_file_step(
                self.event,
                self.root_item,
                wrong_schema,
            )
        )
        self.assertIsNone(
            self.resident._parse_run_python_step(
                self.event,
                self.root_item,
                wrong_schema,
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

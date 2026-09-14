from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _WrongPathCognition:
    """Propose one stale path; ZN must discover reality rather than trust a replacement."""

    _BROAD_STEP_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self) -> None:
        self.calls = 0
        self.step_calls = 0

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        if self._BROAD_STEP_MARKER not in question:
            return CognitiveIncrement(
                text="Use the attached workspace and continue the bounded goal.",
                provider="e2e-cognition",
                model="wrong-path-fixture",
            )
        self.step_calls += 1
        return CognitiveIncrement(
            text=json.dumps(
                {
                    "zn_work_step": {
                        "objective": "run the existing project readiness probe",
                        "action": {
                            "kind": "run_python",
                            "path": "expected/probe.py",
                            "args": [],
                        },
                        "acceptance": {
                            "kind": "command",
                            "expected_exit_code": 0,
                            "output_contains": ["E2E23_READY"],
                        },
                    }
                },
                ensure_ascii=False,
            ),
            provider="e2e-cognition",
            model="wrong-path-fixture",
        )


class CommandPathRealityResolutionTests(unittest.TestCase):
    def test_exact_path_wins_without_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            expected = root / "tools" / "probe.py"
            expected.parent.mkdir()
            expected.write_text("print('exact')\n", encoding="utf-8")

            resolved = BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                root,
                Path("tools/probe.py"),
            )
            self.assertIsNotNone(resolved)
            assert resolved is not None
            script, relative_path, replanned = resolved
            self.assertEqual(script, expected.resolve())
            self.assertEqual(relative_path, "tools/probe.py")
            self.assertFalse(replanned)

    def test_missing_path_uses_one_unique_same_basename_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = root / "scripts" / "probe.py"
            actual.parent.mkdir()
            actual.write_text("print('actual')\n", encoding="utf-8")

            resolved = BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                root,
                Path("expected/probe.py"),
            )
            self.assertIsNotNone(resolved)
            assert resolved is not None
            script, relative_path, replanned = resolved
            self.assertEqual(script, actual.resolve())
            self.assertEqual(relative_path, "scripts/probe.py")
            self.assertTrue(replanned)

    def test_ambiguous_same_basename_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for folder in ("a", "b"):
                target = root / folder / "probe.py"
                target.parent.mkdir()
                target.write_text(f"print({folder!r})\n", encoding="utf-8")

            self.assertIsNone(
                BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                    root,
                    Path("expected/probe.py"),
                )
            )

    def test_generated_vendor_tree_is_not_accepted_as_replacement_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / ".venv" / "probe.py"
            target.parent.mkdir()
            target.write_text("print('wrong authority')\n", encoding="utf-8")

            self.assertIsNone(
                BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                    root,
                    Path("expected/probe.py"),
                )
            )

    def test_windows_reparse_directory_is_pruned_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            junction = root / "junction"
            target = junction / "probe.py"
            junction.mkdir()
            target.write_text("print('must not discover')\n", encoding="utf-8")

            real_lstat = os.lstat
            reparse_attribute = int(
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400)
            )

            def lstat_with_reparse(path):
                metadata = real_lstat(path)
                if Path(path) == junction:
                    return SimpleNamespace(
                        st_mode=metadata.st_mode,
                        st_file_attributes=reparse_attribute,
                    )
                return metadata

            with patch(
                "zn_agent.core.broad_goal_coding_resident.os.lstat",
                side_effect=lstat_with_reparse,
            ):
                self.assertIsNone(
                    BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                        root,
                        Path("expected/probe.py"),
                    )
                )


class E2E23CommandPathReplanTests(unittest.TestCase):
    def test_product_resident_discovers_unique_actual_path_then_executes_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            actual = workspace / "scripts" / "probe.py"
            actual.parent.mkdir(parents=True)
            actual.write_text('print("E2E23_READY")\n', encoding="utf-8")

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _WrongPathCognition()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="e2e23-path-cognition",
                            provider="fixture",
                            model="wrong-path-fixture",
                            capabilities={
                                "general": 1.0,
                                "reasoning": 1.0,
                                "coding": 1.0,
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
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                thread = "e2e23-path-replan"
                ledger.create_thread(thread_id=thread, title="Command path replanning")
                ledger.attach_workspace(thread, workspace, name="E2E-23 Workspace")
                _, event = control.start(
                    thread,
                    "Create a tiny local Python artifact, execute it, and recover from real failures until its contract passes.",
                    payload={"model_policy": "on_demand"},
                    acceptance_criteria=[
                        "a later product-level verifier still has to accept the Root Work",
                    ],
                )
                root_item = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_item)
                assert root_item is not None

                terminal = None
                completed_command = None
                replan_evidence = None
                observed_attempt_id = None
                for _ in range(120):
                    result = resident.live_once()
                    if result is not None and result.event.event_id == event.event_id:
                        terminal = result
                        break

                    state = resident.store.get_working_state()
                    rolling = state.data.get(resident._ROLLING_STEP_KEY)
                    if isinstance(rolling, dict) and rolling.get("path_replanned") is True:
                        replan_evidence = dict(rolling)
                    raw_action = state.data.get("native_action_result")
                    if isinstance(raw_action, dict):
                        data = raw_action.get("data")
                        if isinstance(data, dict):
                            attempt_id = str(data.get("side_effect_attempt_id") or "").strip()
                            if attempt_id:
                                observed_attempt_id = attempt_id

                    children = [
                        item
                        for item in ledger.list_work_items(thread)
                        if item.parent_work_item_id == root_item.work_item_id
                    ]
                    completed_command = next(
                        (
                            item
                            for item in children
                            if item.status == "completed"
                            and any(
                                criterion.startswith("command_exit:")
                                for criterion in item.acceptance_criteria
                            )
                        ),
                        None,
                    )
                    if completed_command is not None:
                        break

                self.assertIsNone(
                    terminal,
                    "one repaired command path must not independently complete the broad Root Work",
                )
                self.assertIsNotNone(completed_command)
                self.assertGreaterEqual(cognition.step_calls, 1)
                self.assertIn("E2E23_READY", completed_command.result or "")
                self.assertIsNotNone(replan_evidence)
                assert isinstance(replan_evidence, dict)
                self.assertEqual(
                    replan_evidence.get("requested_relative_path"),
                    "expected/probe.py",
                )
                self.assertEqual(replan_evidence.get("relative_path"), "scripts/probe.py")
                self.assertTrue(str(observed_attempt_id or "").startswith("sidefx-"))

                actions = [
                    item
                    for item in resident.body.recent_actions(256)
                    if item.event_id == event.event_id and item.kind == "command"
                ]
                self.assertEqual(len(actions), 1)
                command = str(actions[0].data.get("command") or "").replace("\\", "/")
                self.assertIn("scripts/probe.py", command)
                self.assertNotIn("expected/probe.py", command)

                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertNotEqual(root_after.status, "completed")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
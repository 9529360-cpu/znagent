from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class RepoTargetedTestVerificationTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def _init_repo(cls, root: Path, *, test_body: str) -> tuple[Path, Path]:
        cls._git(root, "init")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "config", "user.email", "zn-test@example.invalid")
        target = root / "target.txt"
        test_file = root / "tests" / "test_target.py"
        test_file.parent.mkdir(parents=True)
        target.write_text("before\n", encoding="utf-8")
        test_file.write_text(textwrap.dedent(test_body), encoding="utf-8")
        cls._git(root, "add", "target.txt", "tests/test_target.py")
        cls._git(root, "commit", "-m", "baseline")
        return target, test_file

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 32) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 64):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    @staticmethod
    def _event_actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(160))
            if item.event_id == event_id
        ]

    @staticmethod
    def _payload(root: Path, target: Path, *, targeted_test: dict) -> dict:
        return {
            "path": str(target),
            "content": "after\n",
            "append": False,
            "workspace_path": str(root),
            "required_capabilities": ["filesystem", "it/git"],
            "model_policy": "never",
            "expected_outcome": {
                "kind": "text_equals",
                "path": str(target),
                "expected_text": "after\n",
                "targeted_test": targeted_test,
            },
        }

    def test_tracked_replace_runs_bounded_targeted_unittest_before_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _ = self._init_repo(
                root,
                test_body="""
                    import unittest
                    from pathlib import Path

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            self.assertEqual(
                                (Path(__file__).parents[1] / "target.txt").read_text(encoding="utf-8"),
                                "after\\n",
                            )
                """,
            )
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} and run its bounded targeted test",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                    },
                ),
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("targeted unittest", result.reason)
            actions = self._event_actions(resident, event.event_id)
            commands = [item for item in actions if item.kind == "command"]
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].data.get("exit_code"), 0)
            self.assertIn("unittest discover", commands[0].data.get("command") or "")
            self.assertIn("tests", commands[0].data.get("command") or "")
            scoped_test = [
                item
                for item in actions
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path") == "tests/test_target.py"
            ]
            self.assertEqual(len(scoped_test), 3)
            self.assertTrue(all(item.data.get("scope_tracked") is True for item in scoped_test))
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            serialized = str(experiences[0].to_dict())
            self.assertNotIn("tests/test_target.py", serialized)
            self.assertNotIn(str(target), serialized)
            resident.store.close()

    def test_targeted_unittest_failure_blocks_completion_and_positive_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _ = self._init_repo(
                root,
                test_body="""
                    import unittest

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            self.fail("intentional targeted failure")
                """,
            )
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} and verify it with the bounded test",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                    },
                ),
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("targeted unittest exited with code", state.data["local_failure"])
            verification = state.data["native_verification_result"]
            self.assertFalse(verification["verified"])
            self.assertFalse(verification["targeted_test"]["verified"])
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            resident.store.close()

    def test_restart_with_inflight_targeted_test_marker_refuses_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _ = self._init_repo(
                root,
                test_body="""
                    import unittest

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            self.assertTrue(True)
                """,
            )
            db = base / "resident" / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                f"replace {target} and verify it with the bounded test",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                    },
                ),
            )
            self._advance_until_stage(first, "native_action")
            self.assertIsNone(first.live_once())
            state = first.store.get_working_state()
            self.assertEqual(state.stage, "native_verification")
            intent_id = state.data["native_action_intent"]["intent_id"]
            targeted = state.data["native_repo_text_baseline"]["targeted_test"]
            state.data["native_targeted_test_execution"] = {
                "intent_id": intent_id,
                "kind": "python_unittest",
                "state_sha256": targeted["state_sha256"],
                "status": "started",
                "action_id": None,
            }
            first.store.save_working_state(state)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertEqual(second.store.get_working_state().stage, "native_verification")
            self.assertIsNone(second.live_once())
            restored = second.store.get_working_state()
            self.assertEqual(restored.stage, "native_investigation")
            self.assertIn(
                "refusing replay after interruption",
                restored.data["local_failure"],
            )
            commands = [
                item
                for item in self._event_actions(second, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(commands, [])
            experiences = second.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            second.store.close()

    def test_dirty_targeted_test_file_blocks_write_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, test_file = self._init_repo(
                root,
                test_body="""
                    import unittest

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            self.assertTrue(True)
                """,
            )
            test_file.write_text(test_file.read_text(encoding="utf-8") + "# dirty\n", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} and verify it with the bounded test",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                    },
                ),
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("targeted test file has unstaged changes", state.data["local_failure"])
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")
            writes = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "write_text"
            ]
            self.assertEqual(writes, [])
            resident.store.close()

    def test_cross_target_and_extra_command_authority_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _ = self._init_repo(
                root,
                test_body="""
                    import unittest

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            self.assertTrue(True)
                """,
            )
            for targeted_test, message in (
                (
                    {
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "other.txt",
                    },
                    "for_path must exactly match",
                ),
                (
                    {
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                        "command": "python -m unittest",
                    },
                    "unsupported authority fields: command",
                ),
            ):
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=base / f"resident-{len(message)}" / "kernel.db",
                )
                event = resident.enqueue(
                    f"replace {target} and verify it with the bounded test",
                    payload=self._payload(root, target, targeted_test=targeted_test),
                )
                self._advance_until_stage(resident, "native_action")
                self.assertIsNone(resident.live_once())
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertIn(message, state.data["local_failure"])
                writes = [
                    item
                    for item in self._event_actions(resident, event.event_id)
                    if item.kind == "write_text"
                ]
                self.assertEqual(writes, [])
                resident.store.close()

    def test_wrong_workdir_and_timeout_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target, _ = self._init_repo(
                root,
                test_body="""
                    import time
                    import unittest

                    class TargetTest(unittest.TestCase):
                        def test_target(self):
                            time.sleep(0.2)
                            self.assertTrue(True)
                """,
            )
            wrong = base / "wrong"
            wrong.mkdir()
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "wrong-workdir" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} with wrong targeted test workdir",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                        "workdir": str(wrong),
                    },
                ),
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertIn(
                "workdir must resolve exactly",
                resident.store.get_working_state().data["local_failure"],
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "before\n")
            resident.store.close()

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "timeout" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} and run a bounded timeout test",
                payload=self._payload(
                    root,
                    target,
                    targeted_test={
                        "kind": "python_unittest",
                        "path": "tests/test_target.py",
                        "for_path": "target.txt",
                        "timeout": 0.05,
                    },
                ),
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("targeted unittest timed out", state.data["local_failure"])
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

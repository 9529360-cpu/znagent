from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.goal_resident import ResidentGoalRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class ResidentMultiStepRepoGoalTests(unittest.TestCase):
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
    def _init_repo(cls, root: Path, *, content: str = "before\n") -> Path:
        cls._git(root, "init")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "config", "user.email", "zn-test@example.invalid")
        target = root / "target.txt"
        target.write_text(content, encoding="utf-8")
        cls._git(root, "add", "target.txt")
        cls._git(root, "commit", "-m", "baseline")
        return target

    @staticmethod
    def _enqueue_goal(resident, root: Path, target: Path, text: str):
        return resident.enqueue(
            f"Make repository file {target} contain the requested text and leave that file staged.",
            payload={
                "path": str(target),
                "content": text,
                "append": False,
                "workspace_path": str(root),
                "required_capabilities": ["filesystem", "it/git"],
                "model_policy": "never",
                "resident_goal": {"kind": "repo_text_staged"},
            },
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 192):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        state = resident.store.get_working_state()
        raise AssertionError(
            f"resident did not reach terminal result; stage={state.stage} next={state.next_action}"
        )

    @staticmethod
    def _advance_until_progress(resident, count: int, limit: int = 128) -> None:
        for _ in range(limit):
            state = resident.store.get_working_state()
            progress = state.data.get("resident_goal_progress")
            if (
                isinstance(progress, list)
                and len(progress) >= count
                and state.stage == "native_investigation"
            ):
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"resident terminated before goal progress {count}: {result}"
                )
        state = resident.store.get_working_state()
        raise AssertionError(
            f"resident did not reach goal progress {count}; stage={state.stage}"
        )

    @staticmethod
    def _event_actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(256))
            if item.event_id == event_id
        ]

    def test_one_user_goal_writes_then_resenses_and_stages_before_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target = self._init_repo(root)
            store_path = base / "resident" / "kernel.db"
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            self.assertIsInstance(resident, ResidentGoalRuntime)
            event = self._enqueue_goal(resident, root, target, "after\n")

            self._advance_until_progress(resident, 1)

            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only").stdout.strip(),
                "",
            )
            self.assertIsNone(resident.result_for(event.event_id))
            state = resident.store.get_working_state()
            progress = state.data["resident_goal_progress"]
            self.assertEqual(progress[0]["action_kind"], "write_text")
            self.assertEqual(progress[0]["verification_kind"], "text_equals")
            self.assertTrue(progress[0]["experience_id"])
            self.assertNotIn("native_action_intent", state.data)
            investigation = resident.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            self.assertEqual(investigation.facts, {})
            self.assertEqual(investigation.probe_keys, ())

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("fresh file-content", result.reason)
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only").stdout.strip(),
                "target.txt",
            )
            self.assertEqual(
                self._git(root, "diff", "--name-only").stdout.strip(),
                "",
            )

            actions = self._event_actions(resident, event.event_id)
            writes = [item for item in actions if item.kind == "write_text"]
            stage_commands = [
                item
                for item in actions
                if item.kind == "command"
                and (item.data.get("command") or "").startswith(("git add", "git update-index"))
            ]
            self.assertEqual(len(writes), 1)
            self.assertEqual(len(stage_commands), 1)
            self.assertGreaterEqual(
                len([item for item in actions if item.kind == "read_text"]),
                3,
            )
            self.assertGreaterEqual(
                len([item for item in actions if item.kind == "git_state"]),
                3,
            )

            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 2)
            self.assertEqual(
                {item.verdict for item in experiences},
                {"verified"},
            )
            self.assertEqual(
                {item.action_kind for item in experiences},
                {"write_text", "command"},
            )
            resident.store.close()

    def test_restart_after_verified_write_continues_same_goal_without_replaying_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target = self._init_repo(root)
            store_path = base / "resident" / "kernel.db"
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            event = self._enqueue_goal(resident, root, target, "after\n")
            self._advance_until_progress(resident, 1)
            resident.store.close()

            restarted = build_resident_runtime(
                config={"model": {}},
                store_path=store_path,
            )
            result = self._run_to_terminal(restarted)

            self.assertTrue(result.success)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only").stdout.strip(),
                "target.txt",
            )
            actions = self._event_actions(restarted, event.event_id)
            self.assertEqual(
                len([item for item in actions if item.kind == "write_text"]),
                1,
            )
            self.assertEqual(
                len(
                    [
                        item
                        for item in actions
                        if item.kind == "command"
                        and (item.data.get("command") or "").startswith(
                            ("git add", "git update-index")
                        )
                    ]
                ),
                1,
            )
            restarted.store.close()

    def test_already_satisfied_composite_goal_finishes_from_fresh_observation_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            target = self._init_repo(root)
            target.write_text("after\n", encoding="utf-8")
            self._git(root, "add", "target.txt")
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue_goal(resident, root, target, "after\n")

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("simultaneously proved the final state", result.reason)
            actions = self._event_actions(resident, event.event_id)
            self.assertFalse([item for item in actions if item.kind == "write_text"])
            self.assertFalse(
                [
                    item
                    for item in actions
                    if item.kind == "command"
                    and (item.data.get("command") or "").startswith(
                        ("git add", "git update-index")
                    )
                ]
            )
            self.assertTrue([item for item in actions if item.kind == "read_text"])
            self.assertTrue([item for item in actions if item.kind == "git_state"])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

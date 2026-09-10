from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class E2E38LearnedVerifiedWorkflow(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return proc.stdout.strip()

    @classmethod
    def _repo(cls, root: Path) -> list[Path]:
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-e2e@example.invalid")
        cls._git(root, "config", "user.name", "ZN E2E")
        targets = []
        for index in range(6):
            target = root / f"task-{index}.txt"
            target.write_text(f"base-{index}\n", encoding="utf-8")
            targets.append(target)
        cls._git(root, "add", "--", *[item.name for item in targets])
        cls._git(root, "commit", "-qm", "initial")
        return targets

    @staticmethod
    def _payload(root: Path, target: Path) -> dict:
        return {
            "path": str(target),
            "repo_path": str(root),
            "expected_outcome": {"kind": "git_path_staged", "path": str(target)},
            "model_policy": "never",
            "required_capabilities": ["it/git", "filesystem"],
        }

    @staticmethod
    def _run(resident, limit: int = 120):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach terminal result")

    @staticmethod
    def _event_deliberations(resident, event_id: str) -> int:
        return sum(
            item.action_kind == "deliberate"
            for item in resident.life.recent_thoughts(500)
            if item.action_target == event_id
        )

    @staticmethod
    def _event_movements(resident, event_id: str) -> list[str]:
        return [
            item.kind
            for item in resident.body.recent_actions(500)
            if item.event_id == event_id
        ]

    def test_repeated_verified_git_work_becomes_resident_owned_fast_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            db = root / ".zn" / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)

            cold_event = None
            cold_result = None
            for index, target in enumerate(targets[:4]):
                target.write_text(f"changed-{index}\n", encoding="utf-8")
                event = resident.enqueue(
                    "stage this repository path in the current Git index",
                    payload=self._payload(root, target),
                )
                result = self._run(resident)
                self.assertTrue(result.success)
                self.assertEqual(result.model_invocations, 0)
                if index == 0:
                    cold_event, cold_result = event, result

            self.assertIsNotNone(cold_event)
            self.assertIsNotNone(cold_result)
            cold_deliberations = self._event_deliberations(resident, cold_event.event_id)
            cold_movements = self._event_movements(resident, cold_event.event_id)
            self.assertGreaterEqual(cold_deliberations, 1)
            self.assertIn("inspect_path", cold_movements)
            self.assertGreaterEqual(cold_movements.count("git_state"), 2)

            learned = [
                item
                for item in resident.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ]
            self.assertEqual(len(learned), 1)
            self.assertEqual(learned[0].support_count, 4)
            self.assertEqual(learned[0].maturity_state, "practiced")
            resident.store.close()

            # Resident restart + external models disabled. The competence must
            # remain because it belongs to durable verified experience, not a prompt.
            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            restored = [
                item
                for item in restarted.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertEqual(restored.maturity_state, "practiced")

            novel_target = targets[4]
            novel_target.write_text("new-input-after-learning\n", encoding="utf-8")
            mature_event = restarted.enqueue(
                "stage this new repository path in the current Git index",
                payload=self._payload(root, novel_target),
            )
            mature_result = self._run(restarted)
            self.assertTrue(mature_result.success)
            self.assertEqual(mature_result.model_invocations, 0)

            mature_deliberations = self._event_deliberations(restarted, mature_event.event_id)
            mature_movements = self._event_movements(restarted, mature_event.event_id)
            self.assertLess(mature_deliberations, cold_deliberations)
            self.assertIn("inspect_path", mature_movements)
            self.assertIn("command", mature_movements)
            self.assertGreaterEqual(mature_movements.count("git_state"), 2)
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only", "--", novel_target.name),
                novel_target.name,
            )
            experience = restarted.verified_experiences.for_event(mature_event.event_id)
            self.assertEqual(len(experience), 1)
            self.assertEqual(experience[0].verdict, "verified")

            # It was a new event, target, Body mutation and verification rather
            # than a cached result from an earlier task.
            self.assertNotIn(mature_event.event_id, {cold_event.event_id})
            self.assertNotEqual(novel_target, targets[0])
            restarted.store.close()


if __name__ == "__main__":
    unittest.main()

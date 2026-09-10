from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.learned_behavior_resident import MemoryLearnedBehaviorResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class LearnedBehaviorResidentTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return proc.stdout.strip()

    @classmethod
    def _repo(cls, root: Path, count: int = 10) -> list[Path]:
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-tests@example.invalid")
        cls._git(root, "config", "user.name", "ZN Tests")
        targets = []
        for index in range(count):
            target = root / f"tracked-{index}.txt"
            target.write_text(f"base-{index}\n", encoding="utf-8")
            targets.append(target)
        cls._git(root, "add", "--", *[item.name for item in targets])
        cls._git(root, "commit", "-qm", "initial")
        return targets

    @staticmethod
    def _payload(root: Path, target: Path, *, model_policy: str = "never") -> dict:
        return {
            "path": str(target),
            "repo_path": str(root),
            "expected_outcome": {"kind": "git_path_staged", "path": str(target)},
            "model_policy": model_policy,
            "required_capabilities": ["it/git", "filesystem"],
        }

    @staticmethod
    def _run(resident, limit: int = 100):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach terminal result")

    @classmethod
    def _verified_stage(cls, resident, root: Path, target: Path, index: int):
        target.write_text(f"changed-{index}\n", encoding="utf-8")
        event = resident.enqueue(
            "stage this repository path in the current Git index",
            payload=cls._payload(root, target),
        )
        result = cls._run(resident)
        if not result.success:
            raise AssertionError(result.reason)
        return event, result

    @staticmethod
    def _git_candidates(resident):
        return [
            item
            for item in resident.verified_experiences.candidate_tendencies(limit=16)
            if item.expected_kind == "git_path_staged"
        ]

    @classmethod
    def _candidate(cls, resident, *, tendency_id: str | None = None):
        matches = cls._git_candidates(resident)
        if tendency_id is not None:
            matches = [item for item in matches if item.tendency_id == tendency_id]
        if len(matches) != 1:
            suffix = f" for tendency {tendency_id}" if tendency_id else ""
            raise AssertionError(
                f"expected one matching scoped git competence{suffix}, got {len(matches)}"
            )
        return matches[0]

    def test_product_builder_uses_memory_learned_behavior_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            self.assertIsInstance(resident, MemoryLearnedBehaviorResidentRuntime)
            resident.store.close()

    def test_practiced_git_procedure_skips_deliberation_but_keeps_current_sense_and_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            resident = build_resident_runtime(
                config={"model": {}}, store_path=root / ".zn" / "kernel.db"
            )

            cold_event, cold = self._verified_stage(resident, root, targets[0], 0)
            cold_thoughts = [
                item
                for item in resident.life.recent_thoughts(200)
                if item.action_target == cold_event.event_id
            ]
            cold_deliberation = sum(item.action_kind == "deliberate" for item in cold_thoughts)
            self.assertGreaterEqual(cold_deliberation, 1)
            self.assertEqual(cold.model_invocations, 0)

            for index, target in enumerate(targets[1:4], start=1):
                self._verified_stage(resident, root, target, index)

            candidates = resident.verified_experiences.candidate_tendencies(limit=16)
            practiced = [
                item
                for item in candidates
                if item.expected_kind == "git_path_staged"
                and item.maturity_state == "practiced"
            ]
            self.assertEqual(len(practiced), 1)
            self.assertEqual(practiced[0].support_count, 4)

            mature_event, mature = self._verified_stage(resident, root, targets[4], 4)
            mature_thoughts = [
                item
                for item in resident.life.recent_thoughts(250)
                if item.action_target == mature_event.event_id
            ]
            mature_deliberation = sum(
                item.action_kind == "deliberate" for item in mature_thoughts
            )
            self.assertLess(mature_deliberation, cold_deliberation)
            self.assertEqual(mature.model_invocations, 0)

            movements = [
                item.kind
                for item in resident.body.recent_actions(300)
                if item.event_id == mature_event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("command", movements)
            self.assertGreaterEqual(movements.count("git_state"), 2)
            experiences = resident.verified_experiences.for_event(mature_event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            resident.store.close()

    def test_repeated_prediction_contradiction_inhibits_and_restart_keeps_it_then_relearns_gradually(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            db = root / ".zn" / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            for index, target in enumerate(targets[:4]):
                self._verified_stage(resident, root, target, index)

            learned = self._candidate(resident)
            learned_tendency_id = learned.tendency_id
            learned_variant = learned.applicability.get("stable_action_variant")

            for offset, target in enumerate(targets[4:6], start=4):
                target.write_text(f"drift-{offset}\n", encoding="utf-8")
                event = resident.enqueue(
                    "stage this repository path in the current Git index",
                    payload=self._payload(root, target),
                )
                reached_verification = False
                for _ in range(100):
                    result = resident.live_once()
                    self.assertIsNone(result)
                    state = resident.store.get_working_state()
                    if state.current_event_id == event.event_id and state.stage == "native_verification":
                        fast = state.data.get("procedural_fast_path")
                        self.assertIsInstance(fast, dict)
                        self.assertEqual(fast.get("status"), "active")
                        self.assertEqual(fast.get("tendency_id"), learned_tendency_id)
                        reached_verification = True
                        break
                self.assertTrue(reached_verification)

                self._git(root, "reset", "-q", "HEAD", "--", target.name)
                verification_result = resident.live_once()
                self.assertIsNone(verification_result)
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                event_experiences = resident.verified_experiences.for_event(event.event_id)
                self.assertEqual(len(event_experiences), 1)
                self.assertEqual(event_experiences[0].verdict, "contradicted")

                self._git(root, "add", "--", target.name)
                terminal = self._run(resident)
                self.assertTrue(terminal.success)

            candidate = self._candidate(resident, tendency_id=learned_tendency_id)
            self.assertEqual(candidate.contradiction_count, 2)
            self.assertEqual(candidate.maturity_state, "inhibited")
            self.assertTrue(candidate.inhibited)

            for alternate in self._git_candidates(resident):
                if alternate.tendency_id == learned_tendency_id:
                    continue
                self.assertNotEqual(
                    alternate.applicability.get("stable_action_variant"),
                    learned_variant,
                )
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            restored = self._candidate(restarted, tendency_id=learned_tendency_id)
            self.assertTrue(restored.inhibited)

            self._git(root, "reset", "-q", "HEAD", "--", targets[6].name)
            self._verified_stage(restarted, root, targets[6], 6)
            after_one = self._candidate(restarted, tendency_id=learned_tendency_id)
            self.assertNotEqual(after_one.maturity_state, "practiced")

            for index, target in enumerate(targets[7:10], start=7):
                self._git(root, "reset", "-q", "HEAD", "--", target.name)
                self._verified_stage(restarted, root, target, index)
            relearned = self._candidate(restarted, tendency_id=learned_tendency_id)
            self.assertEqual(relearned.support_count, 8)
            self.assertEqual(relearned.contradiction_count, 2)
            self.assertEqual(relearned.reliability, 0.8)
            self.assertEqual(relearned.maturity_state, "practiced")
            self.assertFalse(relearned.inhibited)
            restarted.store.close()


if __name__ == "__main__":
    unittest.main()

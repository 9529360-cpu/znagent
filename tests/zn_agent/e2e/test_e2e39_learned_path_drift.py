from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class E2E39LearnedPathDrift(unittest.TestCase):
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
        for index in range(12):
            target = root / f"drift-{index}.txt"
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
    def _run(resident, limit: int = 140):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach terminal result")

    @classmethod
    def _success(cls, resident, root: Path, target: Path, index: int):
        target.write_text(f"changed-{index}\n", encoding="utf-8")
        event = resident.enqueue(
            "stage this repository path in the current Git index",
            payload=cls._payload(root, target),
        )
        result = cls._run(resident)
        if not result.success:
            raise AssertionError(result.reason)
        return event

    def test_precondition_and_prediction_drift_stop_old_competence_and_persist_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            db = root / ".zn" / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            for index, target in enumerate(targets[:4]):
                self._success(resident, root, target, index)

            practiced = [
                item
                for item in resident.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertEqual(practiced.maturity_state, "practiced")

            # A. Pre-action mismatch: the old family is mature, but the current
            # target does not exist. Fresh Sense must prevent learned mutation.
            missing = root / "disappeared.txt"
            pre_event = resident.enqueue(
                "stage this repository path in the current Git index",
                payload=self._payload(root, missing),
            )
            pre_result = self._run(resident)
            self.assertFalse(pre_result.success)
            pre_movements = [
                item.kind
                for item in resident.body.recent_actions(500)
                if item.event_id == pre_event.event_id
            ]
            self.assertIn("inspect_path", pre_movements)
            self.assertIn("git_state", pre_movements)
            self.assertNotIn("command", pre_movements)

            # B. Post-action prediction drift, twice. Let the learned mutation
            # happen, then change the real Git index before its independent
            # verification. The resident must record contradiction and return to
            # Investigation instead of trusting historical success.
            for index, target in enumerate(targets[4:6], start=4):
                target.write_text(f"prediction-drift-{index}\n", encoding="utf-8")
                event = resident.enqueue(
                    "stage this repository path in the current Git index",
                    payload=self._payload(root, target),
                )
                for _ in range(140):
                    result = resident.live_once()
                    self.assertIsNone(result)
                    state = resident.store.get_working_state()
                    if state.current_event_id == event.event_id and state.stage == "native_verification":
                        break
                else:
                    raise AssertionError("learned path never reached independent verification")

                self._git(root, "reset", "-q", "HEAD", "--", target.name)
                self.assertIsNone(resident.live_once())
                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                rows = resident.verified_experiences.for_event(event.event_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].verdict, "contradicted")

                # Make the requested state true by a fresh external reality
                # change, then let ZN observe it. This avoids replaying the
                # contradicted learned movement merely to finish the test event.
                self._git(root, "add", "--", target.name)
                self.assertTrue(self._run(resident).success)

            inhibited = [
                item
                for item in resident.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertEqual(inhibited.support_count, 4)
            self.assertEqual(inhibited.contradiction_count, 2)
            self.assertTrue(inhibited.inhibited)
            self.assertEqual(inhibited.maturity_state, "inhibited")
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            restored = [
                item
                for item in restarted.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertTrue(restored.inhibited)
            self.assertEqual(restored.contradiction_count, 2)

            # New verified evidence can relearn, but one success cannot erase two
            # contradictions or jump immediately back to practiced.
            self._success(restarted, root, targets[6], 6)
            one = [
                item
                for item in restarted.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertNotEqual(one.maturity_state, "practiced")
            self.assertEqual(one.contradiction_count, 2)

            for index, target in enumerate(targets[7:10], start=7):
                self._success(restarted, root, target, index)
            recovered = [
                item
                for item in restarted.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ][0]
            self.assertEqual(recovered.support_count, 8)
            self.assertEqual(recovered.contradiction_count, 2)
            self.assertEqual(recovered.reliability, 0.8)
            self.assertEqual(recovered.maturity_state, "practiced")
            self.assertFalse(recovered.inhibited)
            restarted.store.close()


if __name__ == "__main__":
    unittest.main()

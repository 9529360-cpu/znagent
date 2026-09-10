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

    @staticmethod
    def _candidate(resident):
        matches = [
            item
            for item in resident.verified_experiences.candidate_tendencies(limit=16)
            if item.expected_kind == "git_path_staged"
        ]
        if len(matches) != 1:
            raise AssertionError(f"expected one scoped git competence, got {len(matches)}")
        return matches[0]

    @classmethod
    def _train_practiced(cls, resident, root: Path, targets: list[Path]) -> None:
        for index, target in enumerate(targets[:4]):
            cls._success(resident, root, target, index)
        practiced = cls._candidate(resident)
        if practiced.maturity_state != "practiced":
            raise AssertionError(
                f"expected practiced competence, got {practiced.maturity_state}"
            )

    @classmethod
    def _prediction_drift_once(cls, resident, root: Path, target: Path, index: int) -> None:
        target.write_text(f"prediction-drift-{index}\n", encoding="utf-8")
        event = resident.enqueue(
            "stage this repository path in the current Git index",
            payload=cls._payload(root, target),
        )
        for _ in range(140):
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event terminated before verification: success={result.success}; reason={result.reason}"
                )
            state = resident.store.get_working_state()
            if state.current_event_id == event.event_id and state.stage == "native_verification":
                fast = state.data.get("procedural_fast_path")
                if not isinstance(fast, dict) or fast.get("status") != "active":
                    raise AssertionError(
                        f"prediction-drift acceptance did not use active learned fast path: {fast!r}"
                    )
                break
        else:
            raise AssertionError("learned path never reached independent verification")

        cls._git(root, "reset", "-q", "HEAD", "--", target.name)
        if resident.live_once() is not None:
            raise AssertionError("contradicted verification must return to investigation")
        state = resident.store.get_working_state()
        if state.stage != "native_investigation":
            raise AssertionError(f"expected native_investigation after drift, got {state.stage}")
        rows = resident.verified_experiences.for_event(event.event_id)
        if len(rows) != 1:
            raise AssertionError(
                f"expected one contradicted experience for drift event, got {len(rows)}"
            )
        if rows[0].verdict != "contradicted":
            raise AssertionError(f"expected contradicted verdict, got {rows[0].verdict}")

        # Satisfy the requested state externally, then let ZN observe completion.
        # This verifies revocation/recovery without replaying the contradicted move.
        cls._git(root, "add", "--", target.name)
        terminal = cls._run(resident)
        if not terminal.success:
            raise AssertionError(terminal.reason)

    @classmethod
    def _build_inhibited(cls, root: Path, targets: list[Path], db: Path):
        resident = build_resident_runtime(config={"model": {}}, store_path=db)
        cls._train_practiced(resident, root, targets)
        cls._prediction_drift_once(resident, root, targets[4], 4)
        cls._prediction_drift_once(resident, root, targets[5], 5)
        inhibited = cls._candidate(resident)
        if inhibited.support_count != 4 or inhibited.contradiction_count != 2:
            raise AssertionError(
                "drift evidence did not aggregate into the scoped competence: "
                f"support={inhibited.support_count}, contradiction={inhibited.contradiction_count}"
            )
        if not inhibited.inhibited or inhibited.maturity_state != "inhibited":
            raise AssertionError(
                f"expected inhibited competence, got {inhibited.maturity_state}, inhibited={inhibited.inhibited}"
            )
        return resident

    def test_pre_action_drift_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            resident = build_resident_runtime(
                config={"model": {}}, store_path=root / ".zn" / "kernel.db"
            )
            self._train_practiced(resident, root, targets)

            missing = root / "disappeared.txt"
            event = resident.enqueue(
                "stage this repository path in the current Git index",
                payload=self._payload(root, missing),
            )
            result = self._run(resident)
            self.assertFalse(result.success)
            movements = [
                item.kind
                for item in resident.body.recent_actions(500)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("git_state", movements)
            self.assertNotIn("command", movements)
            resident.store.close()

    def test_prediction_drift_inhibits_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            db = root / ".zn" / "kernel.db"
            resident = self._build_inhibited(root, targets, db)
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            restored = self._candidate(restarted)
            self.assertTrue(restored.inhibited)
            self.assertEqual(restored.maturity_state, "inhibited")
            self.assertEqual(restored.support_count, 4)
            self.assertEqual(restored.contradiction_count, 2)
            restarted.store.close()

    def test_inhibited_competence_relearns_gradually(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = self._repo(root)
            db = root / ".zn" / "kernel.db"
            resident = self._build_inhibited(root, targets, db)
            resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            self._success(restarted, root, targets[6], 6)
            after_one = self._candidate(restarted)
            self.assertNotEqual(after_one.maturity_state, "practiced")
            self.assertEqual(after_one.support_count, 5)
            self.assertEqual(after_one.contradiction_count, 2)

            for index, target in enumerate(targets[7:10], start=7):
                self._success(restarted, root, target, index)
            recovered = self._candidate(restarted)
            self.assertEqual(recovered.support_count, 8)
            self.assertEqual(recovered.contradiction_count, 2)
            self.assertEqual(recovered.reliability, 0.8)
            self.assertEqual(recovered.maturity_state, "practiced")
            self.assertFalse(recovered.inhibited)
            restarted.store.close()


if __name__ == "__main__":
    unittest.main()

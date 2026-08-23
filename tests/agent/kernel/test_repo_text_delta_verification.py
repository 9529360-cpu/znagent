from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class RepoTextDeltaVerificationTests(unittest.TestCase):
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
    def _init_repo(cls, root: Path) -> None:
        cls._git(root, "init")
        cls._git(root, "config", "user.name", "ZN Test")
        cls._git(root, "config", "user.email", "zn-test@example.invalid")

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
            for item in reversed(resident.body.recent_actions(120))
            if item.event_id == event_id
        ]

    def test_scoped_git_diff_excludes_unrelated_dirty_paths_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = root / "target.txt"
            unrelated = root / "unrelated.txt"
            target.write_text("before\n", encoding="utf-8")
            unrelated.write_text("other-before\n", encoding="utf-8")
            self._git(root, "add", "target.txt", "unrelated.txt")
            self._git(root, "commit", "-m", "baseline")

            target.write_text("after\n", encoding="utf-8")
            unrelated.write_text("other-after\n", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )

            scoped = resident.body.act(
                "git_diff",
                event_id="evt-scoped-diff",
                path=str(root),
                relative_path="target.txt",
            )
            whole = resident.body.act(
                "git_diff",
                event_id="evt-whole-diff",
                path=str(root),
            )
            escaped = resident.body.act(
                "git_diff",
                event_id="evt-escaped-diff",
                path=str(root),
                relative_path="../escape.txt",
            )
            absolute = resident.body.act(
                "git_diff",
                event_id="evt-absolute-diff",
                path=str(root),
                relative_path=str(target),
            )

            self.assertTrue(scoped.success)
            self.assertEqual(scoped.data["scope_relative_path"], "target.txt")
            self.assertIs(scoped.data["scope_tracked"], True)
            self.assertEqual(scoped.data["changed_paths"], ["target.txt"])
            self.assertEqual(scoped.data["worktree"]["paths"], ["target.txt"])
            self.assertNotIn("unrelated.txt", scoped.output)
            self.assertTrue(whole.success)
            self.assertEqual(
                set(whole.data["changed_paths"]),
                {"target.txt", "unrelated.txt"},
            )
            self.assertFalse(escaped.success)
            self.assertIn("must not escape", escaped.error or "")
            self.assertFalse(absolute.success)
            self.assertIn("repository-relative", absolute.error or "")
            resident.store.close()

    def test_tracked_exact_replace_proves_target_delta_while_unrelated_dirty_state_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = root / "target.txt"
            unrelated = root / "unrelated.txt"
            target.write_text("baseline\n", encoding="utf-8")
            unrelated.write_text("unrelated-baseline\n", encoding="utf-8")
            self._git(root, "add", "target.txt", "unrelated.txt")
            self._git(root, "commit", "-m", "baseline")

            target.write_text("preexisting-target-change\n", encoding="utf-8")
            unrelated.write_text("keep-this-unrelated-change\n", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} with the requested content",
                payload={
                    "path": str(target),
                    "content": "after\n",
                    "append": False,
                    "workspace_path": str(root),
                    "required_capabilities": ["filesystem", "it/git"],
                    "model_policy": "never",
                },
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(
                unrelated.read_text(encoding="utf-8"),
                "keep-this-unrelated-change\n",
            )
            state = resident.store.get_working_state()
            baseline = state.data.get("native_repo_text_baseline")
            verification = state.data.get("native_verification_result")
            self.assertIsInstance(baseline, dict)
            self.assertIsInstance(verification, dict)
            assert isinstance(baseline, dict)
            assert isinstance(verification, dict)
            self.assertEqual(baseline["relative_path"], "target.txt")
            self.assertTrue(verification["verified"])
            self.assertTrue(verification["repo_delta"]["verified"])
            self.assertTrue(verification["repo_delta"]["worktree_changed"])
            self.assertTrue(verification["repo_delta"]["state_changed"])

            actions = self._event_actions(resident, event.event_id)
            scoped = [
                item
                for item in actions
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path") == "target.txt"
            ]
            self.assertEqual(len(scoped), 2)
            self.assertNotEqual(
                scoped[0].data["state_sha256"],
                scoped[1].data["state_sha256"],
            )
            self.assertTrue(
                all("unrelated.txt" not in item.data.get("changed_paths", []) for item in scoped)
            )
            kinds = [item.kind for item in actions]
            self.assertLess(actions.index(scoped[0]), kinds.index("write_text"))
            self.assertLess(kinds.index("write_text"), kinds.index("read_text"))
            self.assertLess(kinds.index("read_text"), actions.index(scoped[1]))

            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            serialized = str(experiences[0].to_dict())
            self.assertNotIn(str(target), serialized)
            self.assertNotIn("preexisting-target-change", serialized)
            self.assertNotIn("after\\n", serialized)
            resident.store.close()

    def test_head_change_after_write_contradicts_repo_delta_before_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = root / "target.txt"
            unrelated = root / "unrelated.txt"
            target.write_text("before\n", encoding="utf-8")
            unrelated.write_text("other\n", encoding="utf-8")
            self._git(root, "add", "target.txt", "unrelated.txt")
            self._git(root, "commit", "-m", "baseline")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} with the requested content",
                payload={
                    "path": str(target),
                    "content": "after\n",
                    "append": False,
                    "workspace_path": str(root),
                    "required_capabilities": ["filesystem", "it/git"],
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")

            unrelated.write_text("committed-after-write\n", encoding="utf-8")
            self._git(root, "add", "unrelated.txt")
            self._git(root, "commit", "-m", "move head after mutation")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            verification = state.data["native_verification_result"]
            self.assertFalse(verification["verified"])
            self.assertFalse(verification["repo_delta"]["head_match"])
            self.assertIn("repository delta contradicted baseline", state.data["local_failure"])
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            writes = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "write_text"
            ]
            self.assertEqual(len(writes), 1)
            resident.store.close()

    def test_truncated_target_baseline_blocks_write_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = root / "target.txt"
            target.write_text("baseline\n", encoding="utf-8")
            self._git(root, "add", "target.txt")
            self._git(root, "commit", "-m", "baseline")
            existing = ("preexisting-" + ("x" * 40_000) + "\n")
            target.write_text(existing, encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} with the requested content",
                payload={
                    "path": str(target),
                    "content": "after\n",
                    "append": False,
                    "workspace_path": str(root),
                    "required_capabilities": ["filesystem", "it/git"],
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("baseline is truncated", state.data["local_failure"])
            self.assertEqual(target.read_text(encoding="utf-8"), existing)
            writes = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "write_text"
            ]
            self.assertEqual(writes, [])
            resident.store.close()

    def test_untracked_target_keeps_existing_text_verification_without_claiming_repo_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            anchor = root / "anchor.txt"
            anchor.write_text("tracked\n", encoding="utf-8")
            self._git(root, "add", "anchor.txt")
            self._git(root, "commit", "-m", "baseline")
            target = root / "untracked.txt"
            target.write_text("before\n", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = resident.enqueue(
                f"replace {target} with the requested content",
                payload={
                    "path": str(target),
                    "content": "after\n",
                    "append": False,
                    "workspace_path": str(root),
                    "required_capabilities": ["filesystem", "it/git"],
                    "model_policy": "never",
                },
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
            state = resident.store.get_working_state()
            self.assertNotIn("native_repo_text_baseline", state.data)
            self.assertTrue(state.data["native_verification_result"]["verified"])
            self.assertNotIn("repo_delta", state.data["native_verification_result"])
            scoped = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path") == "untracked.txt"
            ]
            self.assertEqual(scoped, [])
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

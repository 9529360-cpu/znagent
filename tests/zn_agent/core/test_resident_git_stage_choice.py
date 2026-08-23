from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent, derive_native_action_intents
from zn_agent.core.embodied_resident import EmbodiedResidentRuntime
from zn_agent.core.models import AgentEvent, ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.procedural_resident import ProcedurallyInfluencedResidentRuntime


class ResidentGitStageChoiceTests(unittest.TestCase):
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
    def _repo(cls, root: Path) -> Path:
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-tests@example.invalid")
        cls._git(root, "config", "user.name", "ZN Tests")
        target = root / "tracked.txt"
        target.write_text("base\n", encoding="utf-8")
        cls._git(root, "add", "--", target.name)
        cls._git(root, "commit", "-qm", "initial")
        return target

    @staticmethod
    def _facts(root: Path, target: Path, *, state: str = "unstaged") -> dict:
        rel = target.relative_to(root).as_posix()
        return {
            "paths": [
                {
                    "path": str(target),
                    "exists": True,
                    "type": "file",
                    "size_bytes": target.stat().st_size,
                }
            ],
            "git": {
                "available": True,
                "root": str(root),
                "branch": "main",
                "staged_paths": [rel] if state == "staged" else [],
                "unstaged_paths": [rel] if state == "unstaged" else [],
                "untracked_paths": [rel] if state == "untracked" else [],
                "conflicted_paths": [rel] if state == "conflicted" else [],
            },
        }

    @staticmethod
    def _event(root: Path, target: Path, event_id: str = "evt-git-stage") -> AgentEvent:
        return AgentEvent(
            event_id=event_id,
            task="stage this repository path in the current Git index",
            payload={
                "path": str(target),
                "repo_path": str(root),
                "expected_outcome": {
                    "kind": "git_path_staged",
                    "path": str(target),
                },
                "model_policy": "never",
                "required_capabilities": ["it/git", "filesystem"],
            },
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 80):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_current_git_and_path_evidence_forms_two_distinct_resident_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            event = self._event(root, target)

            choices = derive_native_action_intents(
                event,
                facts=self._facts(root, target, state="unstaged"),
            )

            self.assertEqual(len(choices), 2)
            self.assertTrue(all(item.source == "resident_choice" for item in choices))
            self.assertTrue(all(item.kind == "command" for item in choices))
            self.assertEqual(choices[0].args["workdir"], str(root))
            self.assertEqual(choices[1].args["workdir"], str(root))
            self.assertNotEqual(choices[0].args["command"], choices[1].args["command"])
            self.assertTrue(choices[0].args["command"].startswith("git add -- "))
            self.assertTrue(
                choices[1].args["command"].startswith("git update-index --add -- ")
            )
            self.assertEqual(
                choices[0].expected_outcome["action_variant"],
                "git_add",
            )
            self.assertEqual(
                choices[1].expected_outcome["action_variant"],
                "git_update_index",
            )
            self.assertEqual(
                choices[0].expected_outcome["relative_path"],
                "tracked.txt",
            )
            self.assertEqual(
                choices[1].expected_outcome["path"],
                choices[0].expected_outcome["path"],
            )

    def test_untracked_file_is_stageable_by_same_typed_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "new.txt"
            target.write_text("new\n", encoding="utf-8")
            choices = derive_native_action_intents(
                self._event(root, target, "evt-git-untracked"),
                facts=self._facts(root, target, state="untracked"),
            )
            self.assertEqual(len(choices), 2)

    def test_missing_ambiguous_or_unsafe_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            event = self._event(root, target)
            good = self._facts(root, target, state="unstaged")

            cases: list[tuple[str, dict]] = [
                ("missing_git", {"paths": good["paths"]}),
                ("missing_path", {"git": good["git"]}),
                ("conflict", self._facts(root, target, state="conflicted")),
                ("already_satisfied", self._facts(root, target, state="staged")),
            ]
            directory = root / "directory"
            directory.mkdir()
            cases.append(
                (
                    "directory",
                    {
                        "paths": [
                            {"path": str(directory), "exists": True, "type": "directory"}
                        ],
                        "git": {
                            **good["git"],
                            "unstaged_paths": ["directory"],
                        },
                    },
                )
            )

            outside = Path(tmp).parent / f"outside-{Path(tmp).name}.txt"
            outside.write_text("outside", encoding="utf-8")
            try:
                outside_event = self._event(root, outside, "evt-git-outside")
                outside_facts = {
                    "paths": [{"path": str(outside), "exists": True, "type": "file"}],
                    "git": {
                        **good["git"],
                        "unstaged_paths": [outside.name],
                    },
                }
                cases.append(("outside_root", outside_facts))

                for name, facts in cases:
                    with self.subTest(case=name):
                        candidate_event = outside_event if name == "outside_root" else event
                        self.assertEqual(
                            derive_native_action_intents(candidate_event, facts=facts),
                            (),
                        )
            finally:
                outside.unlink(missing_ok=True)

    def test_blocked_first_resident_git_choice_recovers_to_plumbing_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            self.assertIsInstance(resident, ProcedurallyInfluencedResidentRuntime)
            event = self._event(root, target, "evt-git-recovery")
            intents = derive_native_action_intents(
                event,
                facts=self._facts(root, target, state="unstaged"),
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_deliberation",
            )

            with patch.object(
                EmbodiedResidentRuntime,
                "_evidence_fingerprint",
                return_value="git-reality-v1",
            ):
                resident._record_failed_action(
                    event,
                    state,
                    intents[0],
                    source="body",
                    failure="porcelain staging failed",
                )
                recovered = resident._recover_from_blocked_structured_choices(
                    event,
                    state,
                    intents,
                )

            self.assertTrue(recovered)
            selected = NativeActionIntent.from_dict(state.data["native_action_intent"])
            self.assertEqual(selected.source, "resident_choice")
            self.assertEqual(
                selected.expected_outcome["action_variant"],
                "git_update_index",
            )
            self.assertTrue(
                selected.args["command"].startswith("git update-index --add -- ")
            )
            self.assertNotIn("porcelain staging failed", selected.args.values())
            resident.store.close()

    def test_active_resident_stages_then_verifies_with_fresh_git_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = self._repo(root)
            target.write_text("changed\n", encoding="utf-8")
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / ".zn" / "kernel.db",
            )
            event = resident.enqueue(
                "stage this repository path in the current Git index",
                payload={
                    "path": str(target),
                    "repo_path": str(root),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": str(target),
                    },
                    "model_policy": "never",
                    "required_capabilities": ["it/git", "filesystem"],
                },
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(self._git(root, "diff", "--name-only", "--", target.name), "")
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only", "--", target.name),
                target.name,
            )

            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            experience = experiences[0]
            self.assertEqual(experience.verdict, "verified")
            self.assertEqual(experience.expected_outcome["kind"], "git_path_staged")
            self.assertEqual(experience.expected_outcome["action_variant"], "git_add")
            self.assertNotIn(str(target), str(experience.expected_outcome))
            self.assertNotIn("git add", str(experience.expected_outcome))
            self.assertTrue(experience.verification["staged"])
            self.assertFalse(experience.verification["unstaged"])
            self.assertFalse(experience.verification["untracked"])
            self.assertFalse(experience.verification["conflicted"])

            movements = [
                item.kind
                for item in resident.body.recent_actions(50)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("command", movements)
            self.assertGreaterEqual(movements.count("git_state"), 2)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

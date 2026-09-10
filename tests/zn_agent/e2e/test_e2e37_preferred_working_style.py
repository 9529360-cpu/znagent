from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class E2E37PreferredWorkingStyle(unittest.TestCase):
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
    def _repo(cls, root: Path, names: list[str]) -> list[Path]:
        root.mkdir(parents=True, exist_ok=True)
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-e2e@example.invalid")
        cls._git(root, "config", "user.name", "ZN E2E")
        targets = []
        for name in names:
            target = root / name
            target.write_text(f"base:{name}\n", encoding="utf-8")
            targets.append(target)
        cls._git(root, "add", "--", *names)
        cls._git(root, "commit", "-qm", "initial")
        return targets

    @staticmethod
    def _run(resident, limit: int = 120):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach terminal result")

    @staticmethod
    def _payload(root: Path, target: Path) -> dict:
        return {
            "path": str(target),
            "repo_path": str(root),
            "expected_outcome": {"kind": "git_path_staged", "path": str(target)},
            "model_policy": "never",
            "required_capabilities": ["it/git", "filesystem"],
        }

    @classmethod
    def _train_git_project(
        cls,
        resident,
        root: Path,
        targets: list[Path],
        *,
        prefix: str,
    ) -> list[str]:
        event_ids: list[str] = []
        for index, target in enumerate(targets):
            target.write_text(f"{prefix}-{index}\n", encoding="utf-8")
            event = resident.enqueue(
                "stage this repository path in the current Git index",
                payload=cls._payload(root, target),
            )
            result = cls._run(resident)
            if not result.success:
                raise AssertionError(result.reason)
            event_ids.append(event.event_id)
        return event_ids

    def test_current_project_reuses_only_bounded_verified_context_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            project = base / "project-a"
            noise_project = base / "project-b"
            targets = self._repo(project, [f"a-{index}.txt" for index in range(5)])
            noise_targets = self._repo(
                noise_project, [f"b-{index}.txt" for index in range(4)]
            )
            db = base / "zn" / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)

            prior_event_ids = self._train_git_project(
                resident,
                project,
                targets[:4],
                prefix="changed-a",
            )
            noise_event_ids = self._train_git_project(
                resident,
                noise_project,
                noise_targets,
                prefix="changed-b",
            )

            # Same action family, same maturity and same runtime, but two project
            # identities must remain two learned competences. This is the harder
            # isolation case than merely adding an unrelated action family.
            learned_git = [
                item
                for item in resident.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
                and item.maturity_state == "practiced"
            ]
            self.assertEqual(len(learned_git), 2)

            current = targets[4]
            current.write_text("fresh-current-state\n", encoding="utf-8")
            event = resident.enqueue(
                "还是按照我以前这个项目的方式处理，把这个文件加入当前 Git 暂存区。",
                payload=self._payload(project, current),
            )

            reached_action = False
            context = None
            for _ in range(120):
                result = resident.live_once()
                self.assertIsNone(result)
                state = resident.store.get_working_state()
                if state.current_event_id != event.event_id:
                    continue
                if state.stage == "native_action":
                    reached_action = True
                    context = state.data.get("verified_prior_working_context")
                    break
            self.assertTrue(reached_action)
            self.assertIsInstance(context, dict)
            self.assertEqual(context.get("status"), "resolved")
            matches = context.get("matches") or []
            self.assertLessEqual(len(matches), 3)
            selected = context.get("selected") or {}
            self.assertEqual(selected.get("action_variant"), "git_add")
            self.assertEqual(selected.get("support_count"), 4)
            self.assertEqual(selected.get("maturity_state"), "practiced")
            self.assertEqual(selected.get("reliability"), 1.0)
            self.assertLessEqual(len(selected.get("source_event_ids") or []), 4)
            self.assertLessEqual(len(selected.get("source_experience_ids") or []), 4)
            selected_events = set(selected.get("source_event_ids") or [])
            self.assertTrue(selected_events.issubset(set(prior_event_ids)))
            self.assertTrue(selected_events.isdisjoint(set(noise_event_ids)))

            # The bounded context is provenance/fingerprint metadata, not a dump
            # of either project's raw path or file contents.
            serialized = repr(context)
            self.assertNotIn(str(project), serialized)
            self.assertNotIn(str(noise_project), serialized)
            self.assertNotIn("changed-b", serialized)

            before = [
                item.kind
                for item in resident.body.recent_actions(500)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", before)
            self.assertIn("git_state", before)
            self.assertNotIn("command", before)

            terminal = self._run(resident)
            self.assertTrue(terminal.success)
            after = [
                item.kind
                for item in resident.body.recent_actions(500)
                if item.event_id == event.event_id
            ]
            self.assertIn("command", after)
            self.assertGreaterEqual(after.count("git_state"), 2)
            self.assertEqual(
                self._git(
                    project,
                    "diff",
                    "--cached",
                    "--name-only",
                    "--",
                    current.name,
                ),
                current.name,
            )
            resident.store.close()

    def test_two_historical_projects_without_current_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            first_project = base / "alpha"
            second_project = base / "beta"
            first_targets = self._repo(
                first_project, [f"alpha-{index}.txt" for index in range(2)]
            )
            second_targets = self._repo(
                second_project, [f"beta-{index}.txt" for index in range(2)]
            )
            resident = build_resident_runtime(
                config={"model": {}}, store_path=base / "kernel.db"
            )
            self._train_git_project(
                resident, first_project, first_targets, prefix="alpha-change"
            )
            self._train_git_project(
                resident, second_project, second_targets, prefix="beta-change"
            )
            candidates = [
                item
                for item in resident.verified_experiences.candidate_tendencies(limit=16)
                if item.expected_kind == "git_path_staged"
            ]
            self.assertEqual(len(candidates), 2)

            # Both prior procedures are real and equally plausible, but the new
            # request supplies no current project/path identity. History cannot
            # invent the target or mutation args, so the request must fail closed.
            event = resident.enqueue(
                "还是按照我以前这个项目的方式处理。",
                payload={"model_policy": "never", "required_capabilities": ["it/git"]},
            )
            result = self._run(resident)
            self.assertFalse(result.success)
            movements = [
                item.kind
                for item in resident.body.recent_actions(200)
                if item.event_id == event.event_id
            ]
            self.assertNotIn("command", movements)
            self.assertNotIn("write_text", movements)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

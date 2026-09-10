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

    def test_current_project_reuses_only_bounded_verified_context_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            project = base / "project-a"
            noise_project = base / "project-b"
            targets = self._repo(project, [f"a-{index}.txt" for index in range(5)])
            noise_targets = self._repo(noise_project, [f"b-{index}.txt" for index in range(4)])
            db = base / "zn" / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)

            prior_event_ids: list[str] = []
            for index, target in enumerate(targets[:4]):
                target.write_text(f"changed-a-{index}\n", encoding="utf-8")
                event = resident.enqueue(
                    "stage this repository path in the current Git index",
                    payload=self._payload(project, target),
                )
                self.assertTrue(self._run(resident).success)
                prior_event_ids.append(event.event_id)

            # Real but irrelevant historical Work in a second project/action family.
            for index, target in enumerate(noise_targets):
                event = resident.enqueue(
                    "replace this project note with the requested current text",
                    payload={
                        "path": str(target),
                        "content": f"noise-{index}\n",
                        "model_policy": "never",
                        "required_capabilities": ["filesystem"],
                    },
                )
                self.assertTrue(self._run(resident).success)
                self.assertTrue(resident.verified_experiences.for_event(event.event_id))

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
            self.assertTrue(set(selected.get("source_event_ids") or []).issubset(set(prior_event_ids)))

            # The bounded context is provenance/fingerprint metadata, not a dump
            # of another project's private text/path contents.
            serialized = repr(context)
            self.assertNotIn(str(noise_project), serialized)
            self.assertNotIn("noise-", serialized)

            before = [
                item.kind
                for item in resident.body.recent_actions(400)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", before)
            self.assertIn("git_state", before)
            self.assertNotIn("command", before)

            terminal = self._run(resident)
            self.assertTrue(terminal.success)
            after = [
                item.kind
                for item in resident.body.recent_actions(400)
                if item.event_id == event.event_id
            ]
            self.assertIn("command", after)
            self.assertGreaterEqual(after.count("git_state"), 2)
            self.assertEqual(
                self._git(project, "diff", "--cached", "--name-only", "--", current.name),
                current.name,
            )
            resident.store.close()

    def test_ambiguous_prior_style_without_current_project_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            resident = build_resident_runtime(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            # Deliberately provide no project/path/current target identity. The
            # resident must not invent it from history or dispatch any mutation.
            event = resident.enqueue(
                "还是按照我以前这个项目的方式处理。",
                payload={"model_policy": "never", "required_capabilities": ["it/git"]},
            )
            result = self._run(resident)
            self.assertFalse(result.success)
            movements = [
                item.kind
                for item in resident.body.recent_actions(100)
                if item.event_id == event.event_id
            ]
            self.assertNotIn("command", movements)
            self.assertNotIn("write_text", movements)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

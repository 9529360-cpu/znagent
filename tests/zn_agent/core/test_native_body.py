from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import EmbodiedInvestigator, NativeBody
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class NativeBodyTests(unittest.TestCase):
    def test_normal_resident_has_body_without_registering_a_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            self.assertIsInstance(resident.body, NativeBody)
            self.assertIsInstance(resident.investigator, EmbodiedInvestigator)
            self.assertIs(resident.investigator.resident.body, resident.body)
            self.assertEqual(resident.capabilities.names(), ())

            sensed = resident.body.act("sense", event_id="evt-sense")
            self.assertTrue(sensed.success)
            self.assertEqual(sensed.data["pid"], os.getpid())
            self.assertTrue(sensed.data["cwd"])
            self.assertGreater(sensed.data["disk_total_bytes"], 0)
            resident.store.close()

    def test_file_movement_is_body_action_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "body" / "note.txt"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            written = first.body.act(
                "write_text",
                event_id="evt-body-file",
                path=str(target),
                content="ZN body evidence",
            )
            read = first.body.act(
                "read_text",
                event_id="evt-body-file",
                path=str(target),
            )

            self.assertTrue(written.success)
            self.assertTrue(read.success)
            self.assertEqual(read.output, "ZN body evidence")
            self.assertEqual(first.capabilities.names(), ())
            action_ids = {item.action_id for item in first.body.recent_actions(10)}
            self.assertIn(written.action_id, action_ids)
            self.assertIn(read.action_id, action_ids)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.body.recent_actions(10)
            restored_ids = {item.action_id for item in restored}

            self.assertIn(written.action_id, restored_ids)
            self.assertIn(read.action_id, restored_ids)
            self.assertEqual(second.capabilities.names(), ())
            second.store.close()

    def test_process_observation_is_a_body_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.body.act(
                "process_state",
                event_id="evt-process",
                pid=os.getpid(),
            )

            self.assertTrue(result.success)
            self.assertTrue(result.data["alive"])
            self.assertEqual(result.data["pid"], os.getpid())
            self.assertEqual(resident.capabilities.names(), ())
            resident.store.close()

    def test_git_repository_state_is_structured_body_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()

            def git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            git("init")
            git("config", "user.name", "ZN Test")
            git("config", "user.email", "zn-test@example.invalid")
            git("checkout", "-b", "dev/test")
            tracked = root / "tracked.txt"
            tracked.write_text("baseline\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "baseline")
            head = git("rev-parse", "HEAD").stdout.strip()

            staged = root / "staged.txt"
            staged.write_text("staged\n", encoding="utf-8")
            git("add", "staged.txt")
            tracked.write_text("baseline\nunstaged\n", encoding="utf-8")
            untracked = root / "untracked.txt"
            untracked.write_text("untracked\n", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            observed = resident.body.act(
                "git_state",
                event_id="evt-git-state",
                path=str(root),
            )

            self.assertTrue(observed.success)
            self.assertEqual(observed.data["root"], str(root.resolve()))
            self.assertEqual(observed.data["branch"], "dev/test")
            self.assertEqual(observed.data["head"], head)
            self.assertEqual(observed.data["head_short"], head[:12])
            self.assertFalse(observed.data["detached"])
            self.assertIsNone(observed.data["upstream"])
            self.assertIsNone(observed.data["ahead"])
            self.assertIsNone(observed.data["behind"])
            self.assertTrue(observed.data["dirty"])
            self.assertEqual(
                set(observed.data["changed_paths"]),
                {"tracked.txt", "staged.txt", "untracked.txt"},
            )
            self.assertEqual(observed.data["staged_paths"], ["staged.txt"])
            self.assertEqual(observed.data["unstaged_paths"], ["tracked.txt"])
            self.assertEqual(observed.data["untracked_paths"], ["untracked.txt"])
            self.assertEqual(observed.data["conflicted_paths"], [])
            resident.store.close()

    def test_git_diff_is_structured_read_only_body_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()

            def git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            git("init")
            git("config", "user.name", "ZN Test")
            git("config", "user.email", "zn-test@example.invalid")
            tracked = root / "tracked.txt"
            tracked.write_text("before\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "baseline")
            head = git("rev-parse", "HEAD").stdout.strip()

            tracked.write_text("after\n", encoding="utf-8")
            staged = root / "staged.txt"
            staged.write_text("staged-body-evidence\n", encoding="utf-8")
            git("add", "staged.txt")
            untracked = root / "untracked.txt"
            untracked.write_text("not-in-patch\n", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            observed = resident.body.act(
                "git_diff",
                event_id="evt-git-diff",
                path=str(root),
            )

            self.assertTrue(observed.success)
            self.assertEqual(observed.data["root"], str(root.resolve()))
            self.assertEqual(observed.data["head"], head)
            self.assertTrue(observed.data["dirty"])
            self.assertEqual(
                set(observed.data["changed_paths"]),
                {"tracked.txt", "staged.txt", "untracked.txt"},
            )
            self.assertEqual(observed.data["worktree"]["paths"], ["tracked.txt"])
            self.assertIn("-before", observed.data["worktree"]["patch"])
            self.assertIn("+after", observed.data["worktree"]["patch"])
            self.assertEqual(observed.data["staged"]["paths"], ["staged.txt"])
            self.assertIn("+staged-body-evidence", observed.data["staged"]["patch"])
            self.assertEqual(observed.data["untracked_paths"], ["untracked.txt"])
            self.assertNotIn("not-in-patch", observed.output)
            self.assertEqual(len(observed.data["worktree"]["patch_sha256"]), 64)
            self.assertEqual(len(observed.data["staged"]["patch_sha256"]), 64)
            self.assertEqual(len(observed.data["state_sha256"]), 64)
            actions = [
                item
                for item in resident.body.recent_actions(10)
                if item.event_id == "evt-git-diff"
            ]
            self.assertEqual([item.kind for item in actions], ["git_diff"])
            resident.store.close()

    def test_resident_reports_changed_paths_from_its_git_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            git("init")
            git("config", "user.name", "ZN Test")
            git("config", "user.email", "zn-test@example.invalid")
            tracked = root / "tracked.txt"
            tracked.write_text("baseline\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "baseline")
            tracked.write_text("changed\n", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / ".zn-test" / "kernel.db",
            )
            result = resident.submit(
                "which files changed in the current git workspace?",
                payload={"workspace_path": str(root), "model_policy": "never"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("tracked.txt", result.response)
            latest = resident.investigator.recent(1)[0]
            self.assertIn("tracked.txt", latest.facts["git"]["changed_paths"])
            resident.store.close()

    def test_engineering_investigation_observes_git_state_then_diff_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            git("init")
            git("config", "user.name", "ZN Test")
            git("config", "user.email", "zn-test@example.invalid")
            tracked = root / "tracked.txt"
            tracked.write_text("before\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "baseline")
            tracked.write_text("after\n", encoding="utf-8")

            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / ".zn-test" / "kernel.db",
            )
            result = resident.submit(
                "inspect the current workspace diff before changing code",
                payload={
                    "workspace_path": str(root),
                    "required_capabilities": ["it/git"],
                    "model_policy": "never",
                },
            )

            self.assertFalse(result.success)
            self.assertEqual(result.model_invocations, 0)
            latest = resident.investigator.current(result.event.event_id)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertIn("git", latest.facts)
            self.assertIn("git_diff", latest.facts)
            self.assertTrue(latest.facts["git_diff"]["available"])
            self.assertIn("tracked.txt", latest.facts["git_diff"]["changed_paths"])
            event_actions = [
                item
                for item in reversed(resident.body.recent_actions(50))
                if item.event_id == result.event.event_id
            ]
            kinds = [item.kind for item in event_actions]
            self.assertIn("git_state", kinds)
            self.assertIn("git_diff", kinds)
            self.assertLess(kinds.index("git_state"), kinds.index("git_diff"))
            self.assertFalse(any(item.kind == "command" for item in event_actions))
            resident.store.close()

    def test_multi_pulse_investigation_uses_body_for_evidence_and_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "evidence.txt"
            target.write_text("evidence from the world", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )

            result = resident.submit(
                f"read {target}",
                payload={"path": str(target)},
            )
            event_actions = [
                item
                for item in reversed(resident.body.recent_actions(20))
                if item.event_id == result.event.event_id
            ]

            self.assertTrue(result.success)
            self.assertEqual(result.output if hasattr(result, "output") else result.response, "evidence from the world")
            self.assertGreaterEqual(len(event_actions), 2)
            self.assertEqual(event_actions[0].kind, "inspect_path")
            self.assertEqual(event_actions[1].kind, "read_text")
            self.assertEqual(resident.capabilities.names(), ())
            self.assertEqual(result.model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

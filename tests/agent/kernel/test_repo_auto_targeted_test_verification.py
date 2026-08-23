from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.repo_test_semantics import (
    canonical_kernel_unittest_identity,
    ci_source_runs_kernel_unittest_suite,
    test_source_directly_imports_target,
)


class RepoTestSemanticsTests(unittest.TestCase):
    def test_canonical_kernel_identity_is_narrow_and_literal(self):
        identity = canonical_kernel_unittest_identity("agent/kernel/channel.py")
        self.assertEqual(
            identity,
            {
                "kind": "python_unittest",
                "target_relative_path": "agent/kernel/channel.py",
                "test_relative_path": "tests/agent/kernel/test_channel.py",
                "target_module": "agent.kernel.channel",
                "ci_relative_path": ".github/workflows/zn-ci.yml",
            },
        )
        for rejected in (
            "agent/kernel/__init__.py",
            "agent/kernel/nested/channel.py",
            "agent/other/channel.py",
            "agent/kernel/channel.txt",
            "../agent/kernel/channel.py",
            "C:/repo/agent/kernel/channel.py",
        ):
            with self.subTest(rejected=rejected):
                self.assertIsNone(canonical_kernel_unittest_identity(rejected))

    def test_direct_import_proof_uses_python_structure_not_text_mentions(self):
        module = "agent.kernel.channel"
        self.assertTrue(
            test_source_directly_imports_target(
                "from agent.kernel.channel import ResidentChannelService\n",
                module,
            )
        )
        self.assertTrue(
            test_source_directly_imports_target(
                "import agent.kernel.channel\n",
                module,
            )
        )
        self.assertTrue(
            test_source_directly_imports_target(
                "from agent.kernel import channel\n",
                module,
            )
        )
        self.assertFalse(
            test_source_directly_imports_target(
                '# from agent.kernel.channel import X\nVALUE = "agent.kernel.channel"\n',
                module,
            )
        )
        self.assertFalse(
            test_source_directly_imports_target(
                "from agent.kernel.channel_runtime import ChannelRuntime\n",
                module,
            )
        )
        self.assertFalse(test_source_directly_imports_target("from [broken", module))

    def test_ci_contract_requires_exact_current_kernel_unittest_suite(self):
        current = (
            "steps:\n"
            "  - name: Run ZN kernel tests\n"
            "    run: uv run python -m unittest discover -s tests/agent/kernel "
            "-p 'test_*.py' -v\n"
        )
        self.assertTrue(ci_source_runs_kernel_unittest_suite(current))
        self.assertFalse(
            ci_source_runs_kernel_unittest_suite(
                current.replace("tests/agent/kernel", "tests/agent")
            )
        )
        self.assertFalse(
            ci_source_runs_kernel_unittest_suite(
                current.replace("unittest discover", "pytest")
            )
        )


class RepoAutoTargetedTestVerificationTests(unittest.TestCase):
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
    def _run_to_terminal(resident, limit: int = 72):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 40) -> None:
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
    def _event_actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(200))
            if item.event_id == event_id
        ]

    @classmethod
    def _write_repo(
        cls,
        root: Path,
        *,
        test_source: str | None = None,
        ci_source: str | None = None,
    ) -> Path:
        (root / "agent/kernel").mkdir(parents=True)
        (root / "tests/agent/kernel").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "agent/__init__.py").write_text("", encoding="utf-8")
        (root / "agent/kernel/__init__.py").write_text("", encoding="utf-8")
        target = root / "agent/kernel/sample.py"
        target.write_text(
            'def current_value():\n    return "before"\n',
            encoding="utf-8",
        )
        if test_source is not None:
            (root / "tests/agent/kernel/test_sample.py").write_text(
                test_source,
                encoding="utf-8",
            )
        if ci_source is None:
            ci_source = (
                "name: Test\n"
                "jobs:\n"
                "  kernel:\n"
                "    steps:\n"
                "      - name: Run ZN kernel tests\n"
                "        run: uv run python -m unittest discover "
                "-s tests/agent/kernel -p 'test_*.py' -v\n"
            )
        (root / ".github/workflows/zn-ci.yml").write_text(
            ci_source,
            encoding="utf-8",
        )
        cls._git(root, "add", ".")
        cls._git(root, "commit", "-m", "baseline")
        return target

    @staticmethod
    def _passing_test_source() -> str:
        return (
            "import unittest\n"
            "from agent.kernel.sample import current_value\n\n"
            "class SampleTests(unittest.TestCase):\n"
            "    def test_current_value(self):\n"
            "        self.assertEqual(current_value(), 'after')\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )

    def _enqueue_replacement(self, resident, root: Path, target: Path):
        return resident.enqueue(
            f"replace {target} with the requested content",
            payload={
                "path": str(target),
                "content": 'def current_value():\n    return "after"\n',
                "append": False,
                "workspace_path": str(root),
                "required_capabilities": ["filesystem", "it/git"],
                "model_policy": "never",
            },
        )

    def test_resident_forms_and_runs_mirrored_kernel_unittest_from_repo_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = self._write_repo(root, test_source=self._passing_test_source())
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue_replacement(resident, root, target)

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("resident-derived targeted unittest", result.reason)
            actions = self._event_actions(resident, event.event_id)
            commands = [item for item in actions if item.kind == "command"]
            self.assertEqual(len(commands), 1)
            self.assertIn("unittest", commands[0].data.get("command", "") or commands[0].output)
            test_scopes = [
                item
                for item in actions
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path")
                == "tests/agent/kernel/test_sample.py"
            ]
            ci_scopes = [
                item
                for item in actions
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path") == ".github/workflows/zn-ci.yml"
            ]
            self.assertGreaterEqual(len(test_scopes), 4)
            self.assertGreaterEqual(len(ci_scopes), 3)
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            resident.store.close()

    def test_resident_formed_test_failure_contradicts_mutation_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            failing = self._passing_test_source().replace("'after'", "'never'")
            target = self._write_repo(root, test_source=failing)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue_replacement(resident, root, target)
            self._advance_until_stage(resident, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("targeted unittest exited with code", state.data["local_failure"])
            commands = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(len(commands), 1)
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            resident.store.close()

    def test_missing_mirrored_test_keeps_repo_delta_without_guessing_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = self._write_repo(root, test_source=None)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue_replacement(resident, root, target)

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertNotIn("targeted unittest", result.reason)
            commands = [
                item
                for item in self._event_actions(resident, event.event_id)
                if item.kind == "command"
            ]
            self.assertEqual(commands, [])
            resident.store.close()

    def test_indirect_test_or_changed_ci_contract_cannot_form_execution_authority(self):
        cases = {
            "indirect-test": (
                "import unittest\nfrom agent.kernel import models\n\n"
                "class SampleTests(unittest.TestCase):\n"
                "    def test_placeholder(self):\n        self.assertTrue(models)\n",
                None,
            ),
            "changed-ci": (
                self._passing_test_source(),
                "name: Test\njobs:\n  kernel:\n    steps:\n"
                "      - run: uv run python -m unittest discover -s tests/agent "
                "-p 'test_*.py' -v\n",
            ),
        }
        for name, (test_source, ci_source) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / "repo"
                root.mkdir()
                self._init_repo(root)
                target = self._write_repo(
                    root,
                    test_source=test_source,
                    ci_source=ci_source,
                )
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=base / "resident" / "kernel.db",
                )
                event = self._enqueue_replacement(resident, root, target)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success)
                commands = [
                    item
                    for item in self._event_actions(resident, event.event_id)
                    if item.kind == "command"
                ]
                self.assertEqual(commands, [])
                resident.store.close()

    def test_dirty_test_or_ci_contract_cannot_form_initial_execution_authority(self):
        for dirty_relative in (
            "tests/agent/kernel/test_sample.py",
            ".github/workflows/zn-ci.yml",
        ):
            with self.subTest(dirty_relative=dirty_relative), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / "repo"
                root.mkdir()
                self._init_repo(root)
                target = self._write_repo(root, test_source=self._passing_test_source())
                dirty = root / dirty_relative
                dirty.write_text(
                    dirty.read_text(encoding="utf-8") + "\n# local dirty evidence\n",
                    encoding="utf-8",
                )
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=base / "resident" / "kernel.db",
                )
                event = self._enqueue_replacement(resident, root, target)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success)
                commands = [
                    item
                    for item in self._event_actions(resident, event.event_id)
                    if item.kind == "command"
                ]
                self.assertEqual(commands, [])
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

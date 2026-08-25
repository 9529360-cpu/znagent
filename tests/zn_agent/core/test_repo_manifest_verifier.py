from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.repo_test_semantics import (
    ZN_VERIFIER_MANIFEST_PATH,
    mapped_kernel_unittest_identity,
    test_source_directly_imports_target,
    test_source_has_discoverable_unittest_case,
)


class RepoManifestVerifierTests(unittest.TestCase):
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
    def _actions(resident, event_id: str):
        return [
            item
            for item in reversed(resident.body.recent_actions(240))
            if item.event_id == event_id
        ]

    @staticmethod
    def _manifest(*mappings: dict[str, str]) -> str:
        return json.dumps({"version": 1, "mappings": list(mappings)}, indent=2) + "\n"

    @classmethod
    def _write_repo(
        cls,
        root: Path,
        *,
        manifest_source: str,
        test_source: str,
    ) -> Path:
        (root / "runtime/python/zn_agent/core").mkdir(parents=True)
        (root / "tests/zn_agent/core").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / ".agent").mkdir(parents=True)
        (root / "runtime/python/zn_agent/__init__.py").write_text("", encoding="utf-8")
        (root / "runtime/python/zn_agent/core/__init__.py").write_text("", encoding="utf-8")
        target = root / "runtime/python/zn_agent/core/sample.py"
        target.write_text('def current_value():\n    return "before"\n', encoding="utf-8")
        (root / "tests/zn_agent/core/test_semantics.py").write_text(test_source, encoding="utf-8")
        (root / ZN_VERIFIER_MANIFEST_PATH).write_text(
            manifest_source,
            encoding="utf-8",
        )
        (root / ".github/workflows/zn-ci.yml").write_text(
            "name: Test\nsteps:\n"
            "  - name: Run ZN kernel tests\n"
            "    run: python -m unittest discover "
            "-s tests/zn_agent/core -p 'test_*.py' -v\n",
            encoding="utf-8",
        )
        cls._git(root, "add", ".")
        cls._git(root, "commit", "-m", "baseline")
        return target

    @staticmethod
    def _passing_test_source() -> str:
        return (
            "import unittest\n"
            "from zn_agent.core.sample import current_value\n\n"
            "class SampleTests(unittest.TestCase):\n"
            "    def test_current_value(self):\n"
            "        self.assertEqual(current_value(), 'after')\n"
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

    def test_manifest_semantics_require_one_literal_unambiguous_mapping(self):
        target = "runtime/python/zn_agent/core/sample.py"
        mapping = {
            "target": target,
            "test": "tests/zn_agent/core/test_semantics.py",
        }
        self.assertEqual(
            mapped_kernel_unittest_identity(self._manifest(mapping), target),
            {
                "kind": "python_unittest",
                "target_relative_path": target,
                "test_relative_path": "tests/zn_agent/core/test_semantics.py",
                "target_module": "zn_agent.core.sample",
                "ci_relative_path": ".github/workflows/zn-ci.yml",
            },
        )
        rejected = (
            "not json",
            json.dumps({"version": 2, "mappings": [mapping]}),
            json.dumps({"version": 1, "mappings": [mapping, mapping]}),
            json.dumps({"version": 1, "mappings": [{**mapping, "command": "pytest"}]}),
            json.dumps({"version": 1, "mappings": [{**mapping, "test": "../test.py"}]}),
        )
        for source in rejected:
            with self.subTest(source=source):
                self.assertIsNone(mapped_kernel_unittest_identity(source, target))

    def test_repository_manifest_mappings_are_real_test_relations(self):
        root = Path(__file__).resolve().parents[3]
        manifest_path = root / ZN_VERIFIER_MANIFEST_PATH
        manifest_source = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_source)

        for mapping in manifest["mappings"]:
            with self.subTest(mapping=mapping):
                identity = mapped_kernel_unittest_identity(
                    manifest_source,
                    mapping["target"],
                )
                self.assertIsNotNone(identity)
                target_path = root / identity["target_relative_path"]
                test_path = root / identity["test_relative_path"]
                self.assertTrue(target_path.is_file())
                self.assertTrue(test_path.is_file())
                test_source = test_path.read_text(encoding="utf-8")
                self.assertTrue(
                    test_source_directly_imports_target(
                        test_source,
                        identity["target_module"],
                    )
                )
                self.assertTrue(test_source_has_discoverable_unittest_case(test_source))

    def test_tracked_clean_manifest_can_select_noncanonical_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            self._init_repo(root)
            target = self._write_repo(
                root,
                manifest_source=self._manifest(
                    {
                        "target": "runtime/python/zn_agent/core/sample.py",
                        "test": "tests/zn_agent/core/test_semantics.py",
                    }
                ),
                test_source=self._passing_test_source(),
            )
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=base / "resident" / "kernel.db",
            )
            event = self._enqueue_replacement(resident, root, target)

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertIn("resident-derived targeted unittest", result.reason)
            commands = [item for item in self._actions(resident, event.event_id) if item.kind == "command"]
            self.assertEqual(len(commands), 1)
            self.assertIn("test_semantics.py", commands[0].data.get("command", "") or commands[0].output)
            manifest_scopes = [
                item
                for item in self._actions(resident, event.event_id)
                if item.kind == "git_diff"
                and item.data.get("scope_relative_path") == ZN_VERIFIER_MANIFEST_PATH
            ]
            self.assertGreaterEqual(len(manifest_scopes), 3)
            resident.store.close()

    def test_dirty_manifest_or_indirect_test_cannot_create_command_authority(self):
        cases = {
            "dirty-manifest": self._passing_test_source(),
            "indirect-test": (
                "import unittest\nfrom zn_agent.core import models\n\n"
                "class SampleTests(unittest.TestCase):\n"
                "    def test_placeholder(self):\n        self.assertTrue(models)\n"
            ),
        }
        for name, test_source in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / "repo"
                root.mkdir()
                self._init_repo(root)
                target = self._write_repo(
                    root,
                    manifest_source=self._manifest(
                        {
                            "target": "runtime/python/zn_agent/core/sample.py",
                            "test": "tests/zn_agent/core/test_semantics.py",
                        }
                    ),
                    test_source=test_source,
                )
                if name == "dirty-manifest":
                    manifest = root / ZN_VERIFIER_MANIFEST_PATH
                    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=base / "resident" / "kernel.db",
                )
                event = self._enqueue_replacement(resident, root, target)
                result = self._run_to_terminal(resident)
                self.assertTrue(result.success)
                commands = [item for item in self._actions(resident, event.event_id) if item.kind == "command"]
                self.assertEqual(commands, [])
                self.assertNotIn("targeted unittest", result.reason)
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = REPO_ROOT / "runtime" / "python" / "zn_agent" / "core"
RUNTIME_PROJECT = REPO_ROOT / "runtime" / "python" / "pyproject.toml"
STAGE_SCRIPT = REPO_ROOT / "apps" / "desktop" / "scripts" / "stage-zn-runtime.mjs"

RETIRED_CLI = bytes.fromhex("6865726d65735f636c69").decode("utf-8")
RETIRED_DIST = bytes.fromhex("6865726d65732d6167656e74").decode("utf-8")


class RuntimeOwnershipTests(unittest.TestCase):
    def test_kernel_has_no_inherited_product_imports(self):
        forbidden_roots = {RETIRED_CLI, "run_agent"}
        violations: list[str] = []
        for path in sorted(KERNEL_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if name.split(".", 1)[0] in forbidden_roots:
                        violations.append(f"{path.name}:{getattr(node, 'lineno', '?')} -> {name}")
        self.assertEqual(violations, [])

    def test_runtime_distribution_is_zn_owned(self):
        text = RUNTIME_PROJECT.read_text(encoding="utf-8")
        self.assertIn('name = "znagent"', text)
        self.assertIn('zn-resident = "zn_agent.resident:main"', text)
        self.assertNotIn(RETIRED_DIST, text)
        self.assertNotIn(RETIRED_CLI, text)
        self.assertNotIn("run_agent", text)

    def test_default_visual_capture_dependency_is_installed(self):
        self.assertIsNotNone(importlib.util.find_spec("PIL"))

    def test_staging_installs_runtime_project_not_repository_root(self):
        text = STAGE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("runtimeProject", text)
        self.assertIn("zn_agent", text)
        self.assertNotIn(f"import {RETIRED_CLI}", text)
        self.assertNotIn(f"{RETIRED_CLI}/main.py", text)


if __name__ == "__main__":
    unittest.main()

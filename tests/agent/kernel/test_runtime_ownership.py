from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
KERNEL_ROOT = REPO_ROOT / "agent" / "kernel"
RUNTIME_PROJECT = REPO_ROOT / "runtime" / "python" / "pyproject.toml"
STAGE_SCRIPT = REPO_ROOT / "apps" / "desktop" / "scripts" / "stage-zn-runtime.mjs"


class RuntimeOwnershipTests(unittest.TestCase):
    def test_kernel_has_no_inherited_product_imports(self):
        forbidden_roots = {"hermes_cli", "run_agent"}
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
        self.assertNotIn("hermes-agent", text)
        self.assertNotIn("hermes_cli", text)
        self.assertNotIn("run_agent", text)

    def test_staging_installs_runtime_project_not_repository_root(self):
        text = STAGE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("runtimeProject", text)
        self.assertIn("zn_agent", text)
        self.assertNotIn("import hermes_cli", text)
        self.assertNotIn("hermes_cli/main.py", text)


if __name__ == "__main__":
    unittest.main()

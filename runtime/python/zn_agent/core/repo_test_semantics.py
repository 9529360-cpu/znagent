from __future__ import annotations

"""Pure semantics for one resident-owned repository test identity.

This module deliberately does not inspect the filesystem or execute anything.
It only answers whether already-observed current repository text proves the
first narrow ZN engineering-test relation:

``runtime/python/zn_agent/core/<module>.py``
    -> ``tests/zn_agent/core/test_<module>.py``
    -> current ZN CI still runs the kernel unittest discovery suite.

The resident must separately prove root/HEAD/tracked/clean identity through its
Body before these semantics can grant any test-verification authority.
"""

import ast
import shlex
from pathlib import PurePosixPath
from typing import Any


ZN_KERNEL_SOURCE_DIR = PurePosixPath("runtime/python/zn_agent/core")
ZN_KERNEL_TEST_DIR = PurePosixPath("tests/zn_agent/core")
ZN_CI_WORKFLOW_PATH = ".github/workflows/zn-ci.yml"
ZN_KERNEL_UNITTEST_KIND = "python_unittest"
_ZN_KERNEL_UNITTEST_ARGV = (
    "python",
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests/zn_agent/core",
    "-p",
    "test_*.py",
    "-v",
)


def _repo_relative_path(value: Any) -> PurePosixPath | None:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text:
        return None
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        return None
    return path


def canonical_kernel_unittest_identity(
    target_relative_path: Any,
) -> dict[str, str] | None:
    """Return the one canonical mirrored unittest identity for a kernel module."""

    target = _repo_relative_path(target_relative_path)
    if target is None or len(target.parts) != 5:
        return None
    if PurePosixPath(*target.parts[:4]) != ZN_KERNEL_SOURCE_DIR:
        return None
    if target.suffix != ".py" or target.name == "__init__.py":
        return None
    module_leaf = target.stem
    if not module_leaf.isidentifier():
        return None
    test = ZN_KERNEL_TEST_DIR / f"test_{module_leaf}.py"
    return {
        "kind": ZN_KERNEL_UNITTEST_KIND,
        "target_relative_path": target.as_posix(),
        "test_relative_path": test.as_posix(),
        "target_module": f"zn_agent.core.{module_leaf}",
        "ci_relative_path": ZN_CI_WORKFLOW_PATH,
    }


def _parse_python(source: str) -> ast.Module | None:
    try:
        return ast.parse(str(source or ""))
    except (SyntaxError, ValueError, TypeError):
        return None


def test_source_directly_imports_target(source: str, target_module: str) -> bool:
    """Require a module-level direct import edge from the mirrored test to target."""

    module = str(target_module or "").strip()
    if not module or "." not in module:
        return False
    package, leaf = module.rsplit(".", 1)
    tree = _parse_python(source)
    if tree is None:
        return False

    # Only imports that are direct statements in the module body count. Imports
    # hidden in a function, class, branch, try-block or dead code do not prove a
    # load-time dependency and therefore cannot form execution authority.
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == module for alias in node.names):
                return True
            continue
        if not isinstance(node, ast.ImportFrom) or node.level != 0:
            continue
        imported_from = str(node.module or "")
        if imported_from == module:
            return True
        if imported_from == package and any(alias.name == leaf for alias in node.names):
            return True
    return False


def test_source_has_discoverable_unittest_case(source: str) -> bool:
    """Prove at least one top-level unittest TestCase exposes a test_* method."""

    tree = _parse_python(source)
    if tree is None:
        return False

    unittest_modules: set[str] = set()
    testcase_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "unittest":
                    unittest_modules.add(alias.asname or "unittest")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "unittest":
            for alias in node.names:
                if alias.name == "TestCase":
                    testcase_names.add(alias.asname or "TestCase")

    def is_testcase_base(base: ast.expr) -> bool:
        if isinstance(base, ast.Name):
            return base.id in testcase_names
        return bool(
            isinstance(base, ast.Attribute)
            and base.attr == "TestCase"
            and isinstance(base.value, ast.Name)
            and base.value.id in unittest_modules
        )

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(is_testcase_base(base) for base in node.bases):
            continue
        if any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name.startswith("test_")
            for member in node.body
        ):
            return True
    return False


def ci_source_runs_kernel_unittest_suite(source: str) -> bool:
    """Require the exact current kernel suite in an executable one-line run step."""

    for raw_line in str(source or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("run:"):
            continue
        line = line[4:].strip()
        if not line or line in {"|", ">", "|-", ">-"}:
            continue
        try:
            argv = tuple(shlex.split(line, posix=True))
        except ValueError:
            continue
        if argv == _ZN_KERNEL_UNITTEST_ARGV:
            return True
    return False

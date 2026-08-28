from __future__ import annotations

"""Pure semantics for resident-owned repository test identities.

This module deliberately does not inspect the filesystem or execute anything.
It only answers whether already-observed current repository text proves one of
ZN's bounded engineering-test relations. The resident separately proves
root/HEAD/tracked/clean identity through its Body before these semantics can
grant any test-verification authority.
"""

import ast
import json
import shlex
from pathlib import PurePosixPath
from typing import Any


ZN_KERNEL_SOURCE_DIR = PurePosixPath("runtime/python/zn_agent/core")
ZN_KERNEL_TEST_DIR = PurePosixPath("tests/zn_agent/core")
ZN_CI_WORKFLOW_PATH = ".github/workflows/zn-ci.yml"
ZN_VERIFIER_MANIFEST_PATH = ".agent/zn-engineering-verifiers.json"
ZN_KERNEL_UNITTEST_KIND = "python_unittest"
_ZN_VERIFIER_MANIFEST_VERSION = 1
_ZN_MAX_VERIFIER_MAPPINGS = 64
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
_ZN_WINDOWS_KERNEL_RUN_BLOCK = (
    r"$env:PYTHONPATH = Join-Path $env:GITHUB_WORKSPACE 'runtime\python'",
    r"& .\.ci\runtime-venv\Scripts\python.exe -m unittest discover -s tests/zn_agent/core -p 'test_*.py' -v",
)
_ZN_LITERAL_RUN_BLOCK_MARKERS = frozenset({"|", "|-"})


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


def _kernel_target_identity(target_relative_path: Any) -> tuple[PurePosixPath, str] | None:
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
    return target, f"zn_agent.core.{module_leaf}"


def _kernel_test_path(test_relative_path: Any) -> PurePosixPath | None:
    test = _repo_relative_path(test_relative_path)
    if test is None or len(test.parts) != 4:
        return None
    if PurePosixPath(*test.parts[:3]) != ZN_KERNEL_TEST_DIR:
        return None
    if test.suffix != ".py" or not test.name.startswith("test_"):
        return None
    return test


def canonical_kernel_unittest_identity(
    target_relative_path: Any,
) -> dict[str, str] | None:
    """Return the canonical mirrored unittest identity for one kernel module."""

    target_identity = _kernel_target_identity(target_relative_path)
    if target_identity is None:
        return None
    target, target_module = target_identity
    test = ZN_KERNEL_TEST_DIR / f"test_{target.stem}.py"
    return {
        "kind": ZN_KERNEL_UNITTEST_KIND,
        "target_relative_path": target.as_posix(),
        "test_relative_path": test.as_posix(),
        "target_module": target_module,
        "ci_relative_path": ZN_CI_WORKFLOW_PATH,
    }


def mapped_kernel_unittest_identity(
    manifest_source: str,
    target_relative_path: Any,
) -> dict[str, str] | None:
    """Resolve one explicit repo-owned non-canonical unittest relation.

    The manifest can only name a candidate relation. It cannot prove that the
    manifest is tracked/clean/current, that the test imports the target, or that
    CI executes the suite; the resident must prove all of those independently.
    Any malformed or ambiguous manifest fails closed as a whole.
    """

    target_identity = _kernel_target_identity(target_relative_path)
    if target_identity is None:
        return None
    requested_target, requested_module = target_identity

    try:
        manifest = json.loads(str(manifest_source or ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(manifest, dict) or set(manifest) != {"version", "mappings"}:
        return None
    version = manifest.get("version")
    if isinstance(version, bool) or version != _ZN_VERIFIER_MANIFEST_VERSION:
        return None
    mappings = manifest.get("mappings")
    if (
        not isinstance(mappings, list)
        or len(mappings) > _ZN_MAX_VERIFIER_MAPPINGS
    ):
        return None

    matched: dict[str, str] | None = None
    seen_targets: set[str] = set()
    for item in mappings:
        if not isinstance(item, dict) or set(item) != {"target", "test"}:
            return None
        mapped_target_identity = _kernel_target_identity(item.get("target"))
        mapped_test = _kernel_test_path(item.get("test"))
        if mapped_target_identity is None or mapped_test is None:
            return None
        mapped_target, mapped_module = mapped_target_identity
        target_text = mapped_target.as_posix()
        if target_text in seen_targets:
            return None
        seen_targets.add(target_text)
        if mapped_test.as_posix() == target_text:
            return None
        if mapped_target != requested_target:
            continue
        matched = {
            "kind": ZN_KERNEL_UNITTEST_KIND,
            "target_relative_path": target_text,
            "test_relative_path": mapped_test.as_posix(),
            "target_module": mapped_module,
            "ci_relative_path": ZN_CI_WORKFLOW_PATH,
        }

    if matched is None or matched["target_module"] != requested_module:
        return None
    return matched


def _parse_python(source: str) -> ast.Module | None:
    try:
        return ast.parse(str(source or ""))
    except (SyntaxError, ValueError, TypeError):
        return None


def test_source_directly_imports_target(source: str, target_module: str) -> bool:
    """Require a module-level direct import edge from the selected test to target."""

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


def _line_indent(raw_line: str) -> int:
    return len(raw_line) - len(raw_line.lstrip(" "))


def _previous_nonblank_line(lines: list[str], index: int) -> tuple[int, str] | None:
    for previous in range(index - 1, -1, -1):
        if lines[previous].strip():
            return previous, lines[previous]
    return None


def _literal_run_block(lines: list[str], index: int, indent: int) -> tuple[str, ...]:
    commands: list[str] = []
    for following in range(index + 1, len(lines)):
        raw = lines[following]
        if raw.strip() and _line_indent(raw) <= indent:
            break
        if raw.strip():
            commands.append(raw.strip())
    return tuple(commands)


def ci_source_runs_kernel_unittest_suite(source: str) -> bool:
    """Require a current repo-owned kernel unittest execution contract.

    The historical one-line ``python -m unittest`` form remains recognized. The
    active Windows CI form is deliberately stricter: it must be a literal
    PowerShell run block, explicitly use the isolated runtime interpreter, set
    the working-tree Python source root, and contain no extra executable lines.
    Small CI wording changes therefore fail closed until ZN re-proves the
    verifier relation from current repository evidence.
    """

    lines = str(source or "").splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("run:"):
            continue
        run_value = line[4:].strip()
        if not run_value:
            continue
        if run_value not in _ZN_LITERAL_RUN_BLOCK_MARKERS:
            try:
                argv = tuple(shlex.split(run_value, posix=True))
            except ValueError:
                continue
            if argv == _ZN_KERNEL_UNITTEST_ARGV:
                return True
            continue

        run_indent = _line_indent(raw_line)
        previous = _previous_nonblank_line(lines, index)
        if previous is None:
            continue
        previous_index, previous_line = previous
        if (
            previous_index != index - 1
            or _line_indent(previous_line) != run_indent
            or previous_line.strip().lower() != "shell: powershell"
        ):
            continue
        if _literal_run_block(lines, index, run_indent) == _ZN_WINDOWS_KERNEL_RUN_BLOCK:
            return True
    return False

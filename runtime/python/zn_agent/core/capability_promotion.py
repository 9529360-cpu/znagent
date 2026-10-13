from __future__ import annotations

"""Capability promotion gate, ZN-owned.

A candidate capability file becomes eligible for resident startup loading
only after it passes validate -> test. This is the "future evolution
pipeline" that PromotedCapabilityLoader's docstring calls for, in minimal
form.

Adapted from CLI-Anything's toolchain idea (generate -> structural validate
-> test before trust). There is no auto-generation here: ZN promotes
explicitly authored candidates, and the gate only checks them.

Stages:
  validate_capability_source: static AST checks, no code executed.
  test_capability_source:    import + build + protocol check in a subprocess
                            with a timeout, so a broken candidate cannot wedge
                            the promoter. A module-level self_test(), when
                            present, must pass.
  promote_capability:        validate -> test -> copy into the promoted dir.
"""

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .home import get_zn_home

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REQUIRED_ATTRS = ("name", "match", "execute")
_DEFAULT_TEST_TIMEOUT_SECONDS = 20.0

_PROBE_SCRIPT = r"""
import importlib.util, json, sys, traceback
path = sys.argv[1]
report = {"ok": True, "issues": [], "name": ""}
try:
    spec = importlib.util.spec_from_file_location("zn_candidate_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = getattr(module, "build_capability", None)
    if not callable(builder):
        raise RuntimeError("build_capability is not callable")
    cap = builder()
    report["name"] = str(getattr(cap, "name", "") or "")
    if not report["name"].strip():
        report["issues"].append("capability name must not be empty")
    for attr in ("match", "execute"):
        if not callable(getattr(cap, attr, None)):
            report["issues"].append(f"capability missing callable {attr}()")
    self_test = getattr(module, "self_test", None)
    if callable(self_test):
        try:
            result = self_test()
        except Exception as exc:
            report["issues"].append(f"self_test raised {type(exc).__name__}")
        else:
            if result is not True:
                report["issues"].append(f"self_test failed: {str(result)[:200]!r}")
except Exception as exc:
    report["issues"].append(f"probe failed: {type(exc).__name__}: {str(exc)[:200]}")
report["ok"] = not report["issues"]
print(json.dumps(report))
"""


def describe_capability_source(path: str | Path) -> dict[str, Any]:
    """AST-derived description draft. Executes nothing.

    Gives a reviewer something to read without importing the candidate:
    the module docstring plus top-level defined names.
    """
    source = Path(path)
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=source.name)
    except (OSError, UnicodeError, SyntaxError):
        return {"docstring": None, "top_level_names": []}
    names = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    docstring = ast.get_docstring(tree)
    return {
        "docstring": docstring.strip() if docstring else None,
        "top_level_names": names,
    }


@dataclass(slots=True)
class PromotionReport:
    promoted: bool
    violations: list[str] = field(default_factory=list)
    test_issues: list[str] = field(default_factory=list)
    dest: str | None = None
    capability_name: str | None = None
    description: str | None = None

    def problems(self) -> list[str]:
        return [*self.violations, *self.test_issues]


def validate_capability_source(path: str | Path) -> list[str]:
    """Static checks on a candidate file. Executes nothing."""
    source = Path(path)
    violations: list[str] = []
    if not source.is_file():
        return [f"candidate not found: {source}"]
    if source.suffix.lower() != ".py":
        return [f"candidate must be a .py file: {source.name}"]
    stem = source.stem
    if not _NAME_RE.match(stem):
        violations.append(f"unsafe module stem: {stem!r}")
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read candidate: {type(exc).__name__}"]
    try:
        tree = ast.parse(text, filename=source.name)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]
    docstring = ast.get_docstring(tree)
    if not docstring or not docstring.strip():
        violations.append(
            "module docstring required: document what the capability does, "
            "its trigger conditions, and its side-effect profile"
        )
    builders = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "build_capability"
    ]
    if not builders:
        violations.append("must define module-level build_capability()")
    else:
        args = builders[0].args
        # Positional args without defaults are required arguments.
        positional = args.args[: len(args.args) - len(args.defaults)]
        if positional or args.vararg or args.kwarg:
            violations.append("build_capability() must take no required arguments")
    return violations


def test_capability_source(
    path: str | Path,
    *,
    timeout_seconds: float = _DEFAULT_TEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Import + build the candidate in a subprocess. Returns the probe report."""
    source = Path(path)
    if not source.is_file():
        return {"ok": False, "issues": [f"candidate not found: {source}"],
                "name": ""}
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as probe_file:
        probe_file.write(_PROBE_SCRIPT)
        probe_path = probe_file.name
    try:
        completed = subprocess.run(
            [sys.executable, probe_path, str(source)],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_seconds)),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "issues": ["probe timed out"], "name": ""}
    except OSError as exc:
        return {"ok": False, "issues": [f"probe failed to run: {exc}"], "name": ""}
    finally:
        try:
            Path(probe_path).unlink()
        except OSError:
            pass
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()
        tail = "; ".join(stderr[-3:]) if stderr else "unknown error"
        return {"ok": False, "issues": [f"probe crashed: {tail[:200]}"], "name": ""}
    try:
        report = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError, ValueError):
        return {"ok": False, "issues": ["probe returned unreadable output"],
                "name": ""}
    if not isinstance(report, dict):
        return {"ok": False, "issues": ["probe returned invalid report"],
                "name": ""}
    return {
        "ok": bool(report.get("ok")),
        "issues": [str(i) for i in report.get("issues", [])],
        "name": str(report.get("name", "") or ""),
    }


def promote_capability(
    candidate: str | Path,
    *,
    promoted_root: str | Path | None = None,
    timeout_seconds: float = _DEFAULT_TEST_TIMEOUT_SECONDS,
) -> PromotionReport:
    """Run validate -> test; copy into the promoted dir only if both pass."""
    source = Path(candidate)
    root = Path(promoted_root) if promoted_root is not None else (
        get_zn_home() / "capabilities" / "promoted"
    )
    violations = validate_capability_source(source)
    if violations:
        return PromotionReport(promoted=False, violations=violations)
    probe = test_capability_source(source, timeout_seconds=timeout_seconds)
    if not probe["ok"]:
        return PromotionReport(
            promoted=False,
            test_issues=probe["issues"],
            capability_name=probe["name"] or None,
        )
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{source.stem}.py"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    description = describe_capability_source(source)["docstring"]
    if dest.exists():
        existing_digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if existing_digest == digest:
            return PromotionReport(
                promoted=True, dest=str(dest),
                capability_name=probe["name"] or None,
                description=description,
            )
        return PromotionReport(
            promoted=False,
            violations=[f"promoted file already exists with different content: {dest.name}"],
            capability_name=probe["name"] or None,
        )
    shutil.copy2(source, dest)
    return PromotionReport(
        promoted=True, dest=str(dest), capability_name=probe["name"] or None,
        description=description,
    )

#!/usr/bin/env python3
"""Floor-guard CI script (AS-1): fail on test suppression in a diff.

Reads a unified diff and exits non-zero when the floor guard finds a
violation (suppression comment, skip marker, deleted test/assertion,
stub, or weakening of the floor itself). Warnings are printed but never
fail the run; the author must disposition each one in the PR.

Modes:
    python scripts/floor_guard.py --diff-file PATH
        Check the diff stored in PATH.
    python scripts/floor_guard.py --base REF --head REF
        Check ``git diff REF...HEAD`` (REF defaults to origin/main).
        This is the mode the CI workflow runs.
    git diff ... | python scripts/floor_guard.py
        Check a diff on stdin (default when neither option is given).
    python scripts/floor_guard.py --diff-file PATH --json
        Print only a JSON report (for CI parsing).

No model calls, no network, no file writes. Pure stdlib.
Exit code: 0 when the diff passes (no violations), 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "python"))

from zn_agent.core.floor_guard import check_diff, check_diff_file


def _git_diff(base: str, head: str) -> str:
    proc = subprocess.run(
        ["git", "diff", f"{base}...{head}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git diff {base}...{head} failed: {proc.stderr.strip()}")
    return proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Floor guard: check a diff for test suppression.")
    parser.add_argument("--diff-file", type=Path, default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.diff_file is not None:
        result = check_diff_file(args.diff_file)
    elif args.base is not None:
        result = check_diff(_git_diff(args.base, args.head))
    else:
        result = check_diff(sys.stdin.read())

    if args.json:
        print(
            json.dumps(
                {
                    "passed": result.passed,
                    "violations": list(result.violations),
                    "warnings": list(result.warnings),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if result.violations:
            print(f"floor-guard: FAIL ({len(result.violations)} violation(s))")
            for violation in result.violations:
                print(f"  violation: {violation}")
        else:
            print("floor-guard: PASS (no violations)")
        if result.warnings:
            print(f"floor-guard: {len(result.warnings)} warning(s) (disposition in PR):")
            for warning in result.warnings:
                print(f"  warning: {warning}")
        if not result.violations and not result.warnings:
            print("floor-guard: no findings")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

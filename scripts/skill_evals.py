#!/usr/bin/env python3
"""Skill evals CI script (AS-4: Tier 1 + Tier 2, deterministic, zero-token).

Runs the evals over skill files and prints a human-readable summary plus
an optional JSON report. No model calls, no network, no file writes.

Modes:
    python scripts/skill_evals.py
        Tier 1 over every skill file in this repo (repo-wide scan), plus
        Tier 2 over the repo's ``skills/`` directory when it exists.
        This is the mode the CI workflow runs. A repo with no skill
        files reports zero files and exits 0 — an honest empty result,
        not a fake pass over fixtures.
    python scripts/skill_evals.py --root PATH
        Tier 1 + Tier 2 over one skills root (a directory whose
        subdirectories are skill bundles, e.g. ``$ZN_HOME/skills``).
    python scripts/skill_evals.py --root PATH --json
        Same, but print only the JSON report (for CI parsing).

Requires the ZN runtime dependencies (same as the rest of
``runtime/python``: PyYAML, psutil, ...). The CI workflow installs them
via uv; locally, run with the project venv.

Exit code: 0 when Tier 1 and Tier 2 both pass (no violations), 1
otherwise. Warnings never fail the run; they are listed in the report
and must be dispositioned by the author.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "python"))

from zn_agent.core.skill_evals import (  # noqa: E402
    EvalReport,
    Tier2Result,
    eval_skills_root,
    eval_tier1_files,
    find_skill_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = REPO_ROOT / "skills"


def _print_tier1(report: EvalReport) -> None:
    print(f"Tier 1: {len(report.tier1)} skill file(s)")
    for item in report.tier1:
        status = "PASS" if item.passed else "FAIL"
        print(f"  [{status}] {item.skill_name} ({item.path})")
        for violation in item.violations:
            print(f"    violation: {violation}")
        for warning in item.warnings:
            print(f"    warning: {warning}")
    if not report.tier1:
        print("  (no skill files found)")


def _print_tier2(tier2: Tier2Result, *, skipped_reason: str | None = None) -> None:
    if skipped_reason is not None:
        print(f"Tier 2: SKIPPED ({skipped_reason})")
        return
    n_checks = len(tier2.checks)
    n_failed = sum(1 for item in tier2.checks if not item.passed)
    n_collisions = len(tier2.collisions)
    print(
        f"Tier 2: {n_checks} trigger check(s), "
        f"{n_failed} failed, {n_collisions} collision(s)"
    )
    for item in tier2.checks:
        if item.passed:
            continue
        print(
            f"  [FAIL] {item.kind} query={item.query!r} "
            f"matched={list(item.matched_names)}: {item.detail}"
        )
    for item in tier2.collisions:
        print(f"  [{item.severity}] {item.skill_a} <-> {item.skill_b}: {item.reason}")
    for warning in tier2.warnings:
        print(f"  warning: {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Skills root to eval (default: scan this repo).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report.",
    )
    args = parser.parse_args(argv)

    if args.root is not None:
        report = eval_skills_root(args.root)
        tier2_skipped = None
    else:
        # Repo mode: Tier 1 over every skill file in the repo; Tier 2
        # over the repo's skills/ directory when it exists (the router
        # needs one root whose subdirectories are skill bundles).
        tier1 = eval_tier1_files(find_skill_files(REPO_ROOT))
        if DEFAULT_SKILLS_DIR.is_dir():
            tier2 = eval_skills_root(DEFAULT_SKILLS_DIR).tier2
            tier2_skipped = None
        else:
            tier2 = Tier2Result(
                passed=True,
                warnings=("no skills/ directory in repo; Tier 2 skipped",),
            )
            tier2_skipped = "no skills/ directory in repo"
        report = EvalReport(
            passed=all(item.passed for item in tier1) and tier2.passed,
            tier1=tuple(tier1),
            tier2=tier2,
        )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_tier1(report)
        _print_tier2(report.tier2, skipped_reason=tier2_skipped)
        print(f"Overall: {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

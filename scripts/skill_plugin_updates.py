#!/usr/bin/env python3
"""Nightly external skill-plugin update check (KWP-3 / FastClaw lockfile).

Reads the skills lockfile, checks each external plugin's latest git SHA
against its pinned SHA, and -- in ``bump`` mode -- opens one PR per
update-available plugin. One plugin's failure never blocks the others:
every check and every bump is isolated in try/except and reported.

Usage:
    python scripts/skill_plugin_updates.py check [--lockfile PATH]
    python scripts/skill_plugin_updates.py bump [--lockfile PATH] [--dry-run]

``check`` prints a JSON report and exits 0 even when individual checks
fail (the failures are in the report). ``bump`` runs inside a git
checkout: per plan it creates a branch from origin/main, bumps only
that plugin's SHA in the lockfile, commits, pushes, and opens a PR via
``gh``. ``--dry-run`` prints the planned git/gh commands without running
them. No secrets are read or written: the lockfile holds SHAs, never keys.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "python"))

from zn_agent.core.skill_lock import (  # noqa: E402
    LOCKFILE_NAME,
    SkillLock,
    check_plugin_updates,
    plan_upgrades,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCKFILE = REPO_ROOT / LOCKFILE_NAME


@dataclass
class BumpResult:
    name: str
    status: str  # bumped | dry-run | failed | skipped
    detail: str = ""
    commands: list[list[str]] = field(default_factory=list)


def _git_url(source: str) -> str:
    return source[3:] if source.startswith("git+") else source


def latest_sha_from_git(source: str) -> str:
    """Latest commit SHA of a plugin repo via ``git ls-remote``."""
    proc = subprocess.run(
        ["git", "ls-remote", _git_url(source), "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-remote failed for {source}: {proc.stderr.strip()}")
    parts = proc.stdout.split()
    if not parts:
        raise RuntimeError(f"git ls-remote returned no refs for {source}")
    return parts[0]


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")


def load_lock(lockfile: Path) -> SkillLock:
    """Load a lockfile, or an empty registry when none exists yet."""
    if not lockfile.is_file():
        lock = SkillLock.__new__(SkillLock)
        lock.root = lockfile.parent
        lock.path = lockfile
        lock.entries = {}
        return lock
    return SkillLock(lockfile.parent)


def bump_plugins(
    lock: SkillLock,
    plans: list[Any],
    *,
    runner: Callable[[list[str]], None] = _run,
    dry_run: bool = False,
) -> list[BumpResult]:
    """One branch + commit + PR per plan; each plan isolated from the rest."""
    results: list[BumpResult] = []
    for plan in plans:
        result = BumpResult(name=plan.name, status="bumped")
        commands: list[list[str]] = [
            ["git", "fetch", "origin"],
            ["git", "checkout", "-b", plan.branch, "origin/main"],
        ]
        try:
            if dry_run:
                commands.append(["#", "update", plan.name, "SHA", plan.to_sha, "in", str(lock.path)])
                commands.append(["git", "add", str(lock.path)])
                commands.append(["git", "commit", "-m", f"Skill plugin: bump {plan.name} to {plan.to_sha[:7]}"])
            else:
                for cmd in commands:
                    runner(cmd)
                entry = lock.entries.get(plan.name)
                if entry is None:
                    raise RuntimeError(f"plugin {plan.name!r} vanished from the lockfile")
                entry.sha = plan.to_sha
                from datetime import datetime, timezone

                entry.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                lock.save()
                commands.append(["git", "add", str(lock.path)])
                commands.append(["git", "commit", "-m", f"Skill plugin: bump {plan.name} to {plan.to_sha[:7]}"])
            commands.append(["git", "push", "-u", "origin", plan.branch])
            commands.append(
                ["gh", "pr", "create", "--base", "main", "--head", plan.branch,
                 "--title", plan.title,
                 "--body", f"Bump external skill plugin `{plan.name}` from `{plan.from_sha}` to `{plan.to_sha}`.\n\nNightly lockfile bump: one plugin per PR; lockfile SHA only, no code change."]
            )
            if dry_run:
                result.status = "dry-run"
                result.detail = "planned only, nothing executed"
            else:
                for cmd in commands[2:]:
                    runner(cmd)
            result.commands = commands
        except Exception as exc:  # noqa: BLE001 -- isolation: record, continue
            result.status = "failed"
            result.detail = str(exc) or exc.__class__.__name__
            result.commands = commands
        results.append(result)
    return results


def cmd_check(args: argparse.Namespace) -> int:
    lock = load_lock(Path(args.lockfile))
    checks = check_plugin_updates(lock, fetcher=latest_sha_from_git)
    report = {
        "lockfile": str(args.lockfile),
        "plugins_checked": len(checks),
        "up_to_date": sum(1 for c in checks if c.status == "up-to-date"),
        "update_available": sum(1 for c in checks if c.status == "update-available"),
        "failed": sum(1 for c in checks if c.status == "failed"),
        "checks": [c.to_dict() for c in checks],
        "upgrade_plans": [
            {"name": p.name, "from_sha": p.from_sha, "to_sha": p.to_sha, "branch": p.branch}
            for p in plan_upgrades(checks)
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    lock = load_lock(Path(args.lockfile))
    checks = check_plugin_updates(lock, fetcher=latest_sha_from_git)
    plans = plan_upgrades(checks)
    if not plans:
        print(json.dumps({"bumped": [], "note": "no plugin updates available"}, ensure_ascii=False))
        return 0
    results = bump_plugins(lock, plans, dry_run=args.dry_run)
    print(json.dumps(
        [{"name": r.name, "status": r.status, "detail": r.detail} for r in results],
        ensure_ascii=False, indent=2,
    ))
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lockfile", default=str(DEFAULT_LOCKFILE))
    parser = argparse.ArgumentParser(description="Nightly external skill-plugin update check.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", parents=[common], help="Report latest SHAs vs pinned SHAs (no writes).")
    bump = sub.add_parser("bump", parents=[common], help="Open one PR per update-available plugin.")
    bump.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    return cmd_bump(args)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

"""Bounded isolated source-repair attempts for resident self-maintenance.

This is the first source-write authority in the maintenance path. It is deliberately
narrower than NativeBody file/terminal capability: one high-confidence open task,
one previously observed clean ZN baseline, one fresh ``work/*`` Git worktree under
the repository-adjacent maintenance directory, bounded replacement of existing ZN
core Python/test files, one fixed unittest oracle, and privacy-safe diff evidence.

The operator never writes the observed source root, ``main``, the running installed
body, arbitrary filesystem paths, shell commands, commits, pushes, merges, releases,
or updater state.
"""

import hashlib
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .maintenance_investigation import MaintenanceInvestigationLedger
from .models import utc_now

_EXPECTED_REPOSITORY = "9529360-cpu/znagent"
_ATTEMPT_DIR = ".zn-maintenance-worktrees"
_MAX_REPLACEMENTS = 12
_MAX_FILE_BYTES = 512 * 1024
_MAX_CHANGED_PATHS = 64
_MAX_BRANCH = 180
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_ALLOWED_PREFIXES = (
    PurePosixPath("runtime/python/zn_agent/core"),
    PurePosixPath("tests/zn_agent/core"),
)


class MaintenanceIsolatedRepairOperator:
    """Create and verify one bounded isolated repair attempt."""

    def __init__(
        self,
        store,
        ledger: MaintenanceInvestigationLedger,
        *,
        expected_repository: str = _EXPECTED_REPOSITORY,
    ):
        self.store = store
        self.ledger = ledger
        self.expected_repository = self._repository_slug(expected_repository)
        self._init_schema()

    def execute(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        attempt_root: str | Path,
        branch_ref: str,
        replacements: Mapping[str, str],
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Create a fresh worktree, apply bounded replacements and run the oracle."""

        task = self.ledger.get(task_id)
        if task is None:
            raise ValueError("maintenance investigation does not exist")
        if str(task.get("source_task_status") or "") != "open":
            raise RuntimeError("closed maintenance task cannot create a repair attempt")
        if str(task.get("authority") or "") != "evidence_only":
            raise RuntimeError("maintenance investigation authority is not evidence_only")
        if str(task.get("failure_class") or "") != "probable_zn_defect":
            raise RuntimeError("maintenance repair requires a high-confidence ZN defect")
        if str(task.get("status") or "") != "investigating":
            raise RuntimeError("maintenance source investigation must begin before repair")

        source = Path(source_root).expanduser().resolve(strict=True)
        branch = self._branch_ref(branch_ref)
        validated_replacements = self._replacement_contract(source, replacements)
        bounded_timeout = max(5.0, min(300.0, float(timeout)))
        evidence = self._source_evidence(str(task_id))
        if evidence is None:
            raise RuntimeError("trusted maintenance source evidence is unavailable")
        if str(evidence["authority"] or "") != "read_only":
            raise RuntimeError("maintenance source evidence is not read_only")
        if str(evidence["repository"] or "") != self.expected_repository:
            raise RuntimeError("maintenance source evidence repository is not ZN")
        if bool(evidence["dirty"]):
            raise RuntimeError("maintenance repair requires a clean observed source baseline")
        if not bool(evidence["oracle_available"]):
            raise RuntimeError("maintenance regression oracle is unavailable")

        baseline_head = str(evidence["head"] or "").strip()
        oracle = str(evidence["regression_oracle"] or "").strip()
        if str(task.get("baseline_ref") or "") != f"commit:{baseline_head}":
            raise RuntimeError("maintenance repair baseline contract is stale")
        if str(task.get("regression_oracle") or "") != oracle:
            raise RuntimeError("maintenance repair oracle contract is stale")

        def git(root: Path, *parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(root), *parts],
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                check=False,
            )

        top = git(source, "rev-parse", "--show-toplevel")
        remote = git(source, "remote", "get-url", "origin")
        head = git(source, "rev-parse", "--verify", "HEAD")
        status = git(source, "status", "--porcelain=v1", "-z")
        for proc in (top, remote, head, status):
            if proc.returncode != 0:
                raise RuntimeError("maintenance repair source verification failed")
        observed_top = Path(top.stdout.strip()).expanduser().resolve(strict=True)
        if observed_top != source:
            raise RuntimeError("maintenance repair source must remain the repository root")
        if self._repository_slug(remote.stdout.strip()) != self.expected_repository:
            raise RuntimeError("maintenance repair source origin changed")
        if head.stdout.strip() != baseline_head:
            raise RuntimeError("maintenance repair source HEAD drifted from observed baseline")
        if status.stdout:
            raise RuntimeError("maintenance repair source became dirty after observation")

        root_fingerprint = self._fingerprint("zn-maintenance-root-v1", str(source))
        if root_fingerprint != str(evidence["root_fingerprint"] or ""):
            raise RuntimeError("maintenance repair source root changed after observation")

        attempt = Path(attempt_root).expanduser().resolve(strict=False)
        allowed_parent = (source.parent / _ATTEMPT_DIR).resolve(strict=False)
        if attempt.parent != allowed_parent:
            raise ValueError("maintenance repair attempt must use the dedicated worktree directory")
        if attempt.exists():
            raise FileExistsError("maintenance repair attempt path already exists")
        allowed_parent.mkdir(parents=True, exist_ok=True)

        existing_branch = git(source, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        if existing_branch.returncode == 0:
            raise FileExistsError("maintenance repair work branch already exists")
        if existing_branch.returncode not in {0, 1}:
            raise RuntimeError("maintenance repair could not verify branch availability")

        add = git(source, "worktree", "add", "-b", branch, str(attempt), baseline_head)
        if add.returncode != 0:
            raise RuntimeError("maintenance repair could not create isolated worktree")

        attempt_top = git(attempt, "rev-parse", "--show-toplevel")
        attempt_head = git(attempt, "rev-parse", "--verify", "HEAD")
        attempt_branch = git(attempt, "branch", "--show-current")
        attempt_status = git(attempt, "status", "--porcelain=v1", "-z")
        for proc in (attempt_top, attempt_head, attempt_branch, attempt_status):
            if proc.returncode != 0:
                raise RuntimeError("maintenance repair isolated worktree verification failed")
        if Path(attempt_top.stdout.strip()).expanduser().resolve(strict=True) != attempt:
            raise RuntimeError("maintenance repair worktree root mismatch")
        if attempt_head.stdout.strip() != baseline_head or attempt_branch.stdout.strip() != branch:
            raise RuntimeError("maintenance repair worktree baseline/branch mismatch")
        if attempt_status.stdout:
            raise RuntimeError("maintenance repair worktree is not initially clean")

        for relative, content in validated_replacements.items():
            target = attempt / relative
            if target.is_symlink() or not target.is_file():
                raise RuntimeError("maintenance repair replacement target changed in worktree")
            target.write_text(content, encoding="utf-8", newline="")

        changed_proc = git(attempt, "diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB")
        check_proc = git(attempt, "diff", "--check")
        diff_proc = git(attempt, "diff", "--no-ext-diff", "--unified=0", "--")
        for proc in (changed_proc, check_proc, diff_proc):
            if proc.returncode not in ({0} if proc is not check_proc else {0, 2}):
                raise RuntimeError("maintenance repair diff observation failed")

        changed_paths = [item for item in changed_proc.stdout.split("\0") if item]
        if not changed_paths:
            raise RuntimeError("maintenance repair produced no source diff")
        if len(changed_paths) > _MAX_CHANGED_PATHS:
            raise RuntimeError("maintenance repair diff exceeds changed-path bound")
        allowed_paths = set(validated_replacements)
        if any(path not in allowed_paths for path in changed_paths):
            raise RuntimeError("maintenance repair changed an undeclared source path")

        oracle_path = self._oracle_path(attempt, oracle)
        if not oracle_path.is_file():
            raise RuntimeError("maintenance regression oracle disappeared in isolated worktree")
        module = self._oracle_module(oracle)
        env = dict(os.environ)
        runtime_path = str(attempt / "runtime" / "python")
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = runtime_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        # The regression oracle is evidence, not a source mutation. Python normally
        # writes __pycache__ files while importing the candidate and tests, which
        # leaves a verified worktree dirty and makes later exact publication
        # ambiguous. Fail closed on any real filesystem mutation, but prevent the
        # interpreter's own bytecode cache side effect at the source.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        oracle_proc = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", module],
            cwd=str(attempt),
            env=env,
            capture_output=True,
            text=True,
            timeout=bounded_timeout,
            check=False,
        )

        diff_check_passed = check_proc.returncode == 0
        regression_passed = oracle_proc.returncode == 0 and diff_check_passed
        changed_fingerprint = self._fingerprint(
            "zn-maintenance-repair-paths-v1", "\n".join(changed_paths)
        )
        diff_fingerprint = self._fingerprint(
            "zn-maintenance-repair-diff-v1", diff_proc.stdout
        )
        attempt_key = self._fingerprint(
            "zn-maintenance-repair-attempt-v1",
            "\x00".join(
                [str(task_id), baseline_head, branch, oracle, changed_fingerprint, diff_fingerprint]
            ),
        )
        evidence_ref = f"resident-db:maintenance-repair:{attempt_key}"
        now = utc_now()

        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO resident_maintenance_repair_attempt_evidence("
                "task_id,attempt_key,branch_ref,baseline_head,changed_files,"
                "changed_fingerprint,diff_fingerprint,regression_oracle,regression_passed,"
                "diff_check_passed,authority,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(task_id,attempt_key) DO NOTHING",
                (
                    str(task_id),
                    attempt_key,
                    branch,
                    baseline_head,
                    len(changed_paths),
                    changed_fingerprint,
                    diff_fingerprint,
                    oracle,
                    1 if regression_passed else 0,
                    1 if diff_check_passed else 0,
                    "isolated_source_write",
                    now,
                ),
            )
            conn.commit()

        investigation = self.ledger.record_attempt(
            str(task_id),
            attempt_key=attempt_key,
            branch_ref=branch,
            regression_passed=regression_passed,
            evidence_ref=evidence_ref,
        )
        return {
            "task_id": str(task_id),
            "attempt_key": attempt_key,
            "branch_ref": branch,
            "baseline_head": baseline_head,
            "attempt_root": str(attempt),
            "changed_files": len(changed_paths),
            "changed_paths": changed_paths,
            "changed_fingerprint": changed_fingerprint,
            "diff_fingerprint": diff_fingerprint,
            "diff_check_passed": diff_check_passed,
            "regression_oracle": oracle,
            "regression_passed": regression_passed,
            "authority": "isolated_source_write",
            "created_at": now,
            "investigation": investigation,
        }

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,changed_files,"
                "changed_fingerprint,diff_fingerprint,regression_oracle,regression_passed,"
                "diff_check_passed,authority,created_at FROM "
                "resident_maintenance_repair_attempt_evidence ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_repair_attempt_evidence"
                ).fetchone()[0]
            )
        return {
            "attempt_evidence_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "attempts": [self._row_snapshot(row) for row in rows],
        }

    def _source_evidence(self, task_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,repository,root_fingerprint,branch,head,dirty,changed_files,"
                "changed_fingerprint,regression_oracle,oracle_available,authority,observed_at "
                "FROM resident_maintenance_source_evidence WHERE task_id=?",
                (task_id,),
            ).fetchone()

    @staticmethod
    def _replacement_contract(source: Path, replacements: Mapping[str, str]) -> dict[str, str]:
        items = dict(replacements or {})
        if not items:
            raise ValueError("maintenance repair requires at least one replacement")
        if len(items) > _MAX_REPLACEMENTS:
            raise ValueError("maintenance repair replacement count exceeds bound")
        validated: dict[str, str] = {}
        for raw_path, raw_content in items.items():
            text = str(raw_path or "").strip().replace("\\", "/")
            candidate = PurePosixPath(text)
            if (
                not text
                or text.startswith("/")
                or not candidate.parts
                or any(part in {"", ".", ".."} for part in candidate.parts)
                or candidate.suffix != ".py"
            ):
                raise ValueError("maintenance repair paths must be repository-relative Python files")
            allowed = any(candidate == prefix or prefix in candidate.parents for prefix in _ALLOWED_PREFIXES)
            if not allowed:
                raise ValueError("maintenance repair path is outside the ZN core repair boundary")
            original = (source / candidate.as_posix()).resolve(strict=True)
            try:
                original.relative_to(source)
            except ValueError as exc:
                raise ValueError("maintenance repair path escapes the repository") from exc
            if original.is_symlink() or not original.is_file():
                raise ValueError("maintenance repair may only replace existing regular files")
            content = str(raw_content)
            if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
                raise ValueError("maintenance repair replacement content exceeds bound")
            validated[candidate.as_posix()] = content
        return validated

    @staticmethod
    def _branch_ref(value: str) -> str:
        branch = str(value or "").strip()[:_MAX_BRANCH]
        if (
            not branch.startswith("work/")
            or not _BRANCH_RE.fullmatch(branch)
            or ".." in branch
            or "//" in branch
            or branch.endswith("/")
            or branch.endswith(".lock")
        ):
            raise ValueError("maintenance repair branch must be a safe isolated work/* ref")
        return branch

    @staticmethod
    def _oracle_path(root: Path, oracle: str) -> Path:
        if not oracle.startswith("test:"):
            raise RuntimeError("maintenance regression oracle contract is invalid")
        relative = oracle[len("test:") :]
        candidate = (root / relative).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("maintenance regression oracle escapes the worktree") from exc
        return candidate

    @staticmethod
    def _oracle_module(oracle: str) -> str:
        relative = oracle[len("test:") :]
        if not relative.endswith(".py"):
            raise RuntimeError("maintenance regression oracle must be a Python unittest file")
        module = relative[:-3].replace("/", ".").replace("\\", ".")
        if not module or any(not part.isidentifier() for part in module.split(".")):
            raise RuntimeError("maintenance regression oracle module is invalid")
        return module

    @staticmethod
    def _repository_slug(value: str) -> str:
        raw = str(value or "").strip().rstrip("/")
        if raw.endswith(".git"):
            raw = raw[:-4]
        if raw.startswith("git@github.com:"):
            raw = raw[len("git@github.com:") :]
        elif raw.startswith("ssh://git@github.com/"):
            raw = raw[len("ssh://git@github.com/") :]
        elif raw.startswith("https://github.com/"):
            raw = raw[len("https://github.com/") :]
        elif raw.startswith("http://github.com/"):
            raw = raw[len("http://github.com/") :]
        return raw.strip("/").lower()

    @staticmethod
    def _fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(value.encode("utf-8"))
        return digest.hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.store.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_repair_attempt_evidence("
                "task_id TEXT NOT NULL,attempt_key TEXT NOT NULL,branch_ref TEXT NOT NULL,"
                "baseline_head TEXT NOT NULL,changed_files INTEGER NOT NULL,"
                "changed_fingerprint TEXT NOT NULL,diff_fingerprint TEXT NOT NULL,"
                "regression_oracle TEXT NOT NULL,regression_passed INTEGER NOT NULL,"
                "diff_check_passed INTEGER NOT NULL,authority TEXT NOT NULL,"
                "created_at TEXT NOT NULL,PRIMARY KEY(task_id,attempt_key))"
            )
            conn.commit()

    @staticmethod
    def _row_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "attempt_key": str(row["attempt_key"]),
            "branch_ref": str(row["branch_ref"]),
            "baseline_head": str(row["baseline_head"]),
            "changed_files": int(row["changed_files"]),
            "changed_fingerprint": str(row["changed_fingerprint"]),
            "diff_fingerprint": str(row["diff_fingerprint"]),
            "regression_oracle": str(row["regression_oracle"]),
            "regression_passed": bool(row["regression_passed"]),
            "diff_check_passed": bool(row["diff_check_passed"]),
            "authority": str(row["authority"]),
            "created_at": str(row["created_at"]),
        }

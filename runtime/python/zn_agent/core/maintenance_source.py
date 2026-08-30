from __future__ import annotations

"""Read-only source investigation for resident maintenance tasks.

A maintenance task may justify looking at ZN source evidence, but it never grants
source mutation authority. This module binds one explicit local source checkout,
observes a bounded Git state using only fixed read-only subprocess arguments,
verifies the ZN ownership markers and a declared regression-oracle path, and
records privacy-safe investigation evidence in the resident database.

The source origin is pinned only by a one-way fingerprint. The installed runtime
contains no canonical private-repository slug and source identity is never inferred
from the product update channel. Ordinary Work workspace associations, terminal
execution and NativeBody write capabilities are intentionally not inputs to this
authority path.
"""

import hashlib
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from .maintenance_investigation import MaintenanceInvestigationLedger
from .models import utc_now

_MAX_CHANGED_PATHS = 200
_MAX_ORACLE = 1000


class MaintenanceSourceInvestigator:
    """Bind an open maintenance task to bounded, read-only ZN source evidence."""

    def __init__(self, store, ledger: MaintenanceInvestigationLedger):
        self.store = store
        self.ledger = ledger
        self._init_schema()

    def investigate(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        regression_oracle: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Collect one source-state observation without granting mutation authority."""

        task = self.ledger.get(task_id)
        if task is None:
            raise ValueError("maintenance investigation does not exist")
        if str(task.get("source_task_status") or "") != "open":
            raise RuntimeError("closed maintenance task cannot investigate source")
        if str(task.get("authority") or "") != "evidence_only":
            raise RuntimeError("maintenance investigation authority is not evidence_only")

        requested = Path(source_root).expanduser().resolve(strict=True)
        bounded_timeout = max(1.0, min(30.0, float(timeout)))

        def run(*parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(requested), *parts],
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                check=False,
            )

        root_proc = run("rev-parse", "--show-toplevel")
        if root_proc.returncode != 0:
            raise ValueError("maintenance source root is not a Git repository")
        root = Path(root_proc.stdout.strip()).expanduser().resolve(strict=True)
        if root != requested:
            raise ValueError("maintenance source root must be the repository root")
        self._verify_zn_ownership(root)

        remote_proc = run("remote", "get-url", "origin")
        if remote_proc.returncode != 0 or not remote_proc.stdout.strip():
            raise ValueError("maintenance source requires an origin remote")
        origin_fingerprint = self._origin_fingerprint(remote_proc.stdout.strip())

        head_proc = run("rev-parse", "--verify", "HEAD")
        branch_proc = run("branch", "--show-current")
        status_proc = run("status", "--porcelain=v1", "-z")
        staged_proc = run(
            "diff", "--cached", "--name-only", "-z", "--diff-filter=ACDMRTUXB"
        )
        unstaged_proc = run("diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB")
        untracked_proc = run("ls-files", "--others", "--exclude-standard", "-z")
        for proc in (head_proc, branch_proc, status_proc, staged_proc, unstaged_proc, untracked_proc):
            if proc.returncode != 0:
                raise RuntimeError("maintenance source Git observation failed")

        head = head_proc.stdout.strip()
        if not head:
            raise RuntimeError("maintenance source HEAD is unavailable")
        branch = branch_proc.stdout.strip()
        staged = self._nul_paths(staged_proc.stdout)
        unstaged = self._nul_paths(unstaged_proc.stdout)
        untracked = self._nul_paths(untracked_proc.stdout)
        changed_paths = list(dict.fromkeys([*staged, *unstaged, *untracked]))[
            :_MAX_CHANGED_PATHS
        ]
        dirty = bool(status_proc.stdout)

        oracle = self._oracle(regression_oracle)
        oracle_path = self._oracle_path(root, oracle)
        oracle_available = oracle_path.is_file()
        if not oracle_available:
            raise ValueError("maintenance regression oracle path is unavailable")

        root_fingerprint = self._fingerprint("zn-maintenance-root-v1", str(root))
        changed_fingerprint = self._fingerprint(
            "zn-maintenance-changes-v1",
            json.dumps(changed_paths, ensure_ascii=False, separators=(",", ":")),
        )
        now = utc_now()
        baseline_ref = f"commit:{head}"

        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO resident_maintenance_source_evidence("
                "task_id,repository,root_fingerprint,branch,head,dirty,changed_files,"
                "changed_fingerprint,regression_oracle,oracle_available,authority,observed_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET repository=excluded.repository,"
                "root_fingerprint=excluded.root_fingerprint,branch=excluded.branch,"
                "head=excluded.head,dirty=excluded.dirty,changed_files=excluded.changed_files,"
                "changed_fingerprint=excluded.changed_fingerprint,"
                "regression_oracle=excluded.regression_oracle,"
                "oracle_available=excluded.oracle_available,authority=excluded.authority,"
                "observed_at=excluded.observed_at",
                (
                    str(task_id),
                    origin_fingerprint,
                    root_fingerprint,
                    branch,
                    head,
                    1 if dirty else 0,
                    len(changed_paths),
                    changed_fingerprint,
                    oracle,
                    1,
                    "read_only",
                    now,
                ),
            )
            conn.commit()

        investigation = self.ledger.begin(
            task_id,
            baseline_ref=baseline_ref,
            regression_oracle=oracle,
        )
        return {
            "task_id": str(task_id),
            "origin_fingerprint": origin_fingerprint,
            "root": str(root),
            "root_fingerprint": root_fingerprint,
            "branch": branch,
            "head": head,
            "head_short": head[:12],
            "dirty": dirty,
            "changed_files": len(changed_paths),
            "changed_paths": changed_paths,
            "changed_fingerprint": changed_fingerprint,
            "regression_oracle": oracle,
            "oracle_available": True,
            "authority": "read_only",
            "observed_at": now,
            "investigation": investigation,
        }

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT task_id,repository,root_fingerprint,branch,head,dirty,changed_files,"
                "changed_fingerprint,regression_oracle,oracle_available,authority,observed_at "
                "FROM resident_maintenance_source_evidence ORDER BY observed_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_source_evidence"
                ).fetchone()[0]
            )
        return {
            "evidence_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "evidence": [self._row_snapshot(row) for row in rows],
        }

    @staticmethod
    def _nul_paths(raw: str) -> list[str]:
        return [item for item in raw.split("\0") if item][:_MAX_CHANGED_PATHS]

    @staticmethod
    def _fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(value.encode("utf-8", errors="replace"))
        return digest.hexdigest()

    @classmethod
    def _origin_fingerprint(cls, value: str) -> str:
        origin = str(value or "").strip()
        if not origin:
            raise ValueError("maintenance source origin is required")
        return cls._fingerprint("zn-maintenance-origin-v1", origin)

    @staticmethod
    def _oracle(value: str) -> str:
        oracle = str(value or "").strip()[:_MAX_ORACLE]
        if not oracle.startswith("test:"):
            raise ValueError("maintenance regression oracle must use test:<repository-path>")
        relative = oracle[len("test:") :].strip().replace("\\", "/")
        candidate = PurePosixPath(relative)
        if (
            not relative
            or relative.startswith("/")
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError("maintenance regression oracle must be repository-relative")
        normalized = candidate.as_posix()
        if not normalized.startswith("tests/zn_agent/core/"):
            raise ValueError("maintenance regression oracle must name a ZN core test")
        return f"test:{normalized}"

    @staticmethod
    def _oracle_path(root: Path, oracle: str) -> Path:
        relative = oracle[len("test:") :]
        candidate = (root / relative).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("maintenance regression oracle escapes the repository") from exc
        return candidate

    @staticmethod
    def _verify_zn_ownership(root: Path) -> None:
        required = (
            root / "ZN.md",
            root / "AGENTS.md",
            root / "runtime" / "python" / "zn_agent" / "core",
            root / "tests" / "zn_agent" / "core",
        )
        if not all(path.exists() for path in required):
            raise ValueError("maintenance source root does not satisfy the ZN ownership boundary")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_source_evidence ("
                "task_id TEXT PRIMARY KEY,"
                "repository TEXT NOT NULL,"
                "root_fingerprint TEXT NOT NULL,"
                "branch TEXT NOT NULL,"
                "head TEXT NOT NULL,"
                "dirty INTEGER NOT NULL,"
                "changed_files INTEGER NOT NULL,"
                "changed_fingerprint TEXT NOT NULL,"
                "regression_oracle TEXT NOT NULL,"
                "oracle_available INTEGER NOT NULL,"
                "authority TEXT NOT NULL,"
                "observed_at TEXT NOT NULL"
                ")"
            )
            conn.commit()

    @staticmethod
    def _row_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "origin_fingerprint": str(row["repository"]),
            "root_fingerprint": str(row["root_fingerprint"]),
            "branch": str(row["branch"]),
            "head": str(row["head"]),
            "head_short": str(row["head"])[:12],
            "dirty": bool(row["dirty"]),
            "changed_files": max(0, int(row["changed_files"] or 0)),
            "changed_fingerprint": str(row["changed_fingerprint"]),
            "regression_oracle": str(row["regression_oracle"]),
            "oracle_available": bool(row["oracle_available"]),
            "authority": str(row["authority"]),
            "observed_at": str(row["observed_at"]),
        }

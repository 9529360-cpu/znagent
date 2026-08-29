from __future__ import annotations

"""Lifecycle cleanup for rejected isolated maintenance repair attempts.

Rejected candidates are disposable evidence, while accepted candidates must remain
available for a later publication stage.  This owner therefore removes only the
exact rejected ``work/*`` worktree recorded by the maintenance ledger, only while
its branch still points at the observed baseline commit, and only under the
repository-adjacent maintenance worktree directory.

Unknown, accepted, committed, moved, or otherwise drifted worktrees are never
removed automatically.
"""

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from .maintenance_investigation import MaintenanceInvestigationLedger
from .models import utc_now

_EXPECTED_REPOSITORY = "9529360-cpu/znagent"
_ATTEMPT_DIR = ".zn-maintenance-worktrees"


class MaintenanceRepairAttemptLifecycle:
    """Safely retire one durable rejected repair worktree and local branch."""

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

    def cleanup_rejected(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Remove only the exact rejected, uncommitted maintenance worktree."""

        normalized_task = str(task_id or "").strip()
        if not normalized_task:
            raise ValueError("maintenance cleanup requires task_id")
        investigation = self.ledger.get(normalized_task)
        if investigation is None:
            raise ValueError("maintenance investigation does not exist")
        status = str(investigation.get("status") or "")
        acceptance = str(investigation.get("acceptance_state") or "")
        if status == "accepted" or acceptance == "accepted":
            raise RuntimeError("accepted maintenance repair must be retained for publication")
        if status != "rejected":
            raise RuntimeError("only a rejected maintenance repair may be cleaned automatically")

        attempt = self._latest_attempt(normalized_task)
        if attempt is None:
            raise RuntimeError("rejected maintenance investigation has no durable repair attempt")
        attempt_key = str(attempt["attempt_key"])
        existing = self._cleanup_evidence(normalized_task, attempt_key)
        if existing is not None:
            return self._row_snapshot(existing)

        branch = str(attempt["branch_ref"] or "").strip()
        baseline_head = str(attempt["baseline_head"] or "").strip()
        if not branch.startswith("work/") or not baseline_head:
            raise RuntimeError("maintenance cleanup attempt contract is invalid")

        source = Path(source_root).expanduser().resolve(strict=True)
        bounded_timeout = max(3.0, min(60.0, float(timeout)))

        def git(*parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(source), *parts],
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                check=False,
            )

        top = git("rev-parse", "--show-toplevel")
        remote = git("remote", "get-url", "origin")
        if top.returncode != 0 or remote.returncode != 0:
            raise RuntimeError("maintenance cleanup source verification failed")
        if Path(top.stdout.strip()).expanduser().resolve(strict=True) != source:
            raise RuntimeError("maintenance cleanup source must be the repository root")
        if self._repository_slug(remote.stdout.strip()) != self.expected_repository:
            raise RuntimeError("maintenance cleanup source origin is not ZN")

        branch_head = git("rev-parse", "--verify", f"refs/heads/{branch}")
        if branch_head.returncode != 0:
            raise RuntimeError("maintenance cleanup branch is unavailable")
        if branch_head.stdout.strip() != baseline_head:
            raise RuntimeError("maintenance cleanup refuses a branch that advanced from baseline")

        worktrees = git("worktree", "list", "--porcelain")
        if worktrees.returncode != 0:
            raise RuntimeError("maintenance cleanup could not enumerate worktrees")
        worktree = self._find_worktree(worktrees.stdout, branch)
        if worktree is None:
            raise RuntimeError("maintenance cleanup could not resolve the recorded worktree")
        attempt_root = Path(worktree["path"]).expanduser().resolve(strict=True)
        allowed_parent = (source.parent / _ATTEMPT_DIR).resolve(strict=False)
        if attempt_root.parent != allowed_parent:
            raise RuntimeError("maintenance cleanup worktree escaped the dedicated directory")
        if str(worktree.get("head") or "") != baseline_head:
            raise RuntimeError("maintenance cleanup worktree HEAD drifted from baseline")

        remove = git("worktree", "remove", "--force", str(attempt_root))
        if remove.returncode != 0:
            raise RuntimeError("maintenance cleanup could not remove rejected worktree")
        delete_branch = git("branch", "-D", branch)
        if delete_branch.returncode != 0:
            raise RuntimeError("maintenance cleanup could not remove rejected local branch")

        removed_at = utc_now()
        path_fingerprint = self._fingerprint(
            "zn-maintenance-cleanup-worktree-v1", str(attempt_root)
        )
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO resident_maintenance_attempt_cleanup("
                "task_id,attempt_key,branch_ref,baseline_head,worktree_fingerprint,"
                "disposition,removed_at) VALUES(?,?,?,?,?,?,?)",
                (
                    normalized_task,
                    attempt_key,
                    branch,
                    baseline_head,
                    path_fingerprint,
                    "rejected_removed",
                    removed_at,
                ),
            )
            conn.commit()
        row = self._cleanup_evidence(normalized_task, attempt_key)
        assert row is not None
        return self._row_snapshot(row)

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_attempt_cleanup"
                ).fetchone()[0]
            )
            rows = conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,worktree_fingerprint,"
                "disposition,removed_at FROM resident_maintenance_attempt_cleanup "
                "ORDER BY removed_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return {
            "cleanup_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "cleanups": [self._row_snapshot(row) for row in rows],
        }

    def _latest_attempt(self, task_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT a.task_id,a.attempt_key,a.branch_ref,a.regression_passed,a.created_at,"
                "e.baseline_head,e.diff_fingerprint,e.changed_fingerprint "
                "FROM resident_maintenance_attempts a JOIN "
                "resident_maintenance_repair_attempt_evidence e "
                "ON e.task_id=a.task_id AND e.attempt_key=a.attempt_key "
                "WHERE a.task_id=? ORDER BY a.created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()

    def _cleanup_evidence(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,worktree_fingerprint,"
                "disposition,removed_at FROM resident_maintenance_attempt_cleanup "
                "WHERE task_id=? AND attempt_key=?",
                (task_id, attempt_key),
            ).fetchone()

    @staticmethod
    def _find_worktree(raw: str, branch: str) -> dict[str, str] | None:
        expected_ref = f"refs/heads/{branch}"
        current: dict[str, str] = {}
        records: list[dict[str, str]] = []
        for line in str(raw or "").splitlines():
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            value = value.strip()
            if key == "worktree":
                current["path"] = value
            elif key == "HEAD":
                current["head"] = value
            elif key == "branch":
                current["branch"] = value
        if current:
            records.append(current)
        matches = [row for row in records if row.get("branch") == expected_ref]
        if len(matches) != 1 or not matches[0].get("path"):
            return None
        return matches[0]

    @staticmethod
    def _repository_slug(value: str) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if text.startswith("git@github.com:"):
            text = text[len("git@github.com:") :]
        elif text.startswith("ssh://git@github.com/"):
            text = text[len("ssh://git@github.com/") :]
        elif text.startswith("https://github.com/"):
            text = text[len("https://github.com/") :]
        elif text.startswith("http://github.com/"):
            text = text[len("http://github.com/") :]
        text = text.strip("/")
        if text.endswith(".git"):
            text = text[:-4]
        parts = [part for part in text.split("/") if part]
        if len(parts) != 2:
            raise ValueError("maintenance cleanup repository must identify one GitHub repository")
        return f"{parts[0]}/{parts[1]}"

    @staticmethod
    def _fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(value).encode("utf-8", errors="replace"))
        return digest.hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_attempt_cleanup ("
                "task_id TEXT NOT NULL,attempt_key TEXT NOT NULL,branch_ref TEXT NOT NULL,"
                "baseline_head TEXT NOT NULL,worktree_fingerprint TEXT NOT NULL,"
                "disposition TEXT NOT NULL,removed_at TEXT NOT NULL,"
                "PRIMARY KEY(task_id,attempt_key))"
            )
            conn.commit()

    @staticmethod
    def _row_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "attempt_key": str(row["attempt_key"]),
            "branch_ref": str(row["branch_ref"]),
            "baseline_head": str(row["baseline_head"]),
            "baseline_head_short": str(row["baseline_head"])[:12],
            "worktree_fingerprint": str(row["worktree_fingerprint"]),
            "disposition": str(row["disposition"]),
            "removed_at": str(row["removed_at"]),
        }

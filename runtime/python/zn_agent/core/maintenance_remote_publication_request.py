from __future__ import annotations

"""Create a credentialless handoff request for remote maintenance publication.

This owner deliberately stops before any remote side effect. It takes an already
verified ``local_commit_only`` maintenance publication object, re-proves that the
recorded worktree still points at the exact clean commit, and persists a bounded
request envelope for a future separately-authorized publisher.

It never reads repository credentials, contacts GitHub, pushes refs, creates pull
requests, merges, releases, updates an installed body, rolls back, or signs code.
"""

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from .maintenance_publication import MaintenancePublicationPreparation
from .models import utc_now

_EXPECTED_REPOSITORY = "9529360-cpu/znagent"
_ATTEMPT_DIR = ".zn-maintenance-worktrees"
_TARGET_BASE_REF = "dev/zn-agent"
_ACTION = "push_branch_open_pull_request"


class MaintenanceRemotePublicationRequest:
    """Persist one fail-closed request envelope without remote authority."""

    def __init__(
        self,
        store,
        preparation: MaintenancePublicationPreparation,
        *,
        expected_repository: str = _EXPECTED_REPOSITORY,
        target_base_ref: str = _TARGET_BASE_REF,
    ):
        self.store = store
        self.preparation = preparation
        self.expected_repository = self._repository_slug(expected_repository)
        self.target_base_ref = str(target_base_ref or "").strip()
        if self.target_base_ref != _TARGET_BASE_REF:
            raise ValueError("maintenance remote publication base must remain dev/zn-agent")
        self._init_schema()

    def request(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        normalized_task = str(task_id or "").strip()
        if not normalized_task:
            raise ValueError("maintenance remote publication request requires task_id")

        prepared = self.preparation.prepare(
            normalized_task,
            source_root=source_root,
            timeout=timeout,
        )
        if str(prepared.get("authority") or "") != "local_commit_only":
            raise RuntimeError("maintenance remote publication requires local_commit_only evidence")

        attempt_key = str(prepared.get("attempt_key") or "").strip()
        branch = str(prepared.get("branch_ref") or "").strip()
        baseline_head = str(prepared.get("baseline_head") or "").strip()
        commit_sha = str(prepared.get("commit_sha") or "").strip()
        commit_fingerprint = str(prepared.get("commit_fingerprint") or "").strip()
        changed_fingerprint = str(prepared.get("changed_fingerprint") or "").strip()
        diff_fingerprint = str(prepared.get("diff_fingerprint") or "").strip()
        if (
            not attempt_key
            or not branch.startswith("work/")
            or not baseline_head
            or not commit_sha
            or not commit_fingerprint
            or not changed_fingerprint
            or not diff_fingerprint
        ):
            raise RuntimeError("maintenance remote publication preparation evidence is incomplete")

        source = Path(source_root).expanduser().resolve(strict=True)
        bounded_timeout = max(3.0, min(90.0, float(timeout)))

        def git_at(root: Path, *parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(root), *parts],
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                check=False,
            )

        top = git_at(source, "rev-parse", "--show-toplevel")
        remote = git_at(source, "remote", "get-url", "origin")
        if top.returncode != 0 or remote.returncode != 0:
            raise RuntimeError("maintenance remote publication source verification failed")
        if Path(top.stdout.strip()).expanduser().resolve(strict=True) != source:
            raise RuntimeError("maintenance remote publication source must be repository root")
        if self._repository_slug(remote.stdout.strip()) != self.expected_repository:
            raise RuntimeError("maintenance remote publication source origin is not ZN")

        worktrees = git_at(source, "worktree", "list", "--porcelain")
        if worktrees.returncode != 0:
            raise RuntimeError("maintenance remote publication could not enumerate worktrees")
        record = self._find_worktree(worktrees.stdout, branch)
        if record is None:
            raise RuntimeError("maintenance remote publication worktree is unavailable")
        attempt_root = Path(record["path"]).expanduser().resolve(strict=True)
        if attempt_root.parent != (source.parent / _ATTEMPT_DIR).resolve(strict=False):
            raise RuntimeError("maintenance remote publication worktree escaped dedicated directory")

        current_branch = git_at(attempt_root, "branch", "--show-current")
        current_head = git_at(attempt_root, "rev-parse", "--verify", "HEAD")
        parent = git_at(attempt_root, "rev-parse", "--verify", "HEAD^")
        status = git_at(attempt_root, "status", "--porcelain=v1", "-z")
        if any(proc.returncode != 0 for proc in (current_branch, current_head, parent, status)):
            raise RuntimeError("maintenance remote publication worktree verification failed")
        if current_branch.stdout.strip() != branch:
            raise RuntimeError("maintenance remote publication branch drifted")
        if current_head.stdout.strip() != commit_sha or str(record.get("head") or "") != commit_sha:
            raise RuntimeError("maintenance remote publication commit drifted")
        if parent.stdout.strip() != baseline_head:
            raise RuntimeError("maintenance remote publication commit parent drifted")
        if status.stdout:
            raise RuntimeError("maintenance remote publication requires a clean prepared worktree")

        request_key = self._fingerprint(
            "zn-maintenance-remote-publication-request-v1",
            "\x00".join(
                [
                    normalized_task,
                    attempt_key,
                    self.expected_repository,
                    self.target_base_ref,
                    branch,
                    baseline_head,
                    commit_sha,
                    commit_fingerprint,
                    changed_fingerprint,
                    diff_fingerprint,
                    _ACTION,
                ]
            ),
        )
        existing = self._request(normalized_task, attempt_key)
        if existing is not None:
            if str(existing["request_key"]) != request_key:
                raise RuntimeError("maintenance remote publication request evidence drifted")
            return self._row_snapshot(existing)

        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO resident_maintenance_remote_publication_requests("
                "task_id,attempt_key,request_key,repository,target_base_ref,branch_ref,"
                "baseline_head,commit_sha,commit_fingerprint,changed_fingerprint,"
                "diff_fingerprint,requested_action,authority,state,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    normalized_task,
                    attempt_key,
                    request_key,
                    self.expected_repository,
                    self.target_base_ref,
                    branch,
                    baseline_head,
                    commit_sha,
                    commit_fingerprint,
                    changed_fingerprint,
                    diff_fingerprint,
                    _ACTION,
                    "request_only",
                    "awaiting_repository_authority",
                    now,
                ),
            )
            conn.commit()
        row = self._request(normalized_task, attempt_key)
        assert row is not None
        return self._row_snapshot(row)

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_remote_publication_requests"
                ).fetchone()[0]
            )
            rows = conn.execute(
                "SELECT task_id,attempt_key,request_key,repository,target_base_ref,branch_ref,"
                "baseline_head,commit_sha,commit_fingerprint,changed_fingerprint,diff_fingerprint,"
                "requested_action,authority,state,created_at FROM "
                "resident_maintenance_remote_publication_requests ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return {
            "request_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "requests": [self._row_snapshot(row) for row in rows],
        }

    def _request(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,attempt_key,request_key,repository,target_base_ref,branch_ref,"
                "baseline_head,commit_sha,commit_fingerprint,changed_fingerprint,diff_fingerprint,"
                "requested_action,authority,state,created_at FROM "
                "resident_maintenance_remote_publication_requests WHERE task_id=? AND attempt_key=?",
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
            raise ValueError("maintenance remote publication repository must identify one GitHub repository")
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
                "CREATE TABLE IF NOT EXISTS resident_maintenance_remote_publication_requests("
                "task_id TEXT NOT NULL,attempt_key TEXT NOT NULL,request_key TEXT NOT NULL UNIQUE,"
                "repository TEXT NOT NULL,target_base_ref TEXT NOT NULL,branch_ref TEXT NOT NULL,"
                "baseline_head TEXT NOT NULL,commit_sha TEXT NOT NULL,commit_fingerprint TEXT NOT NULL,"
                "changed_fingerprint TEXT NOT NULL,diff_fingerprint TEXT NOT NULL,"
                "requested_action TEXT NOT NULL,authority TEXT NOT NULL,state TEXT NOT NULL,"
                "created_at TEXT NOT NULL,PRIMARY KEY(task_id,attempt_key))"
            )
            conn.commit()

    @staticmethod
    def _row_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "attempt_key": str(row["attempt_key"]),
            "request_key": str(row["request_key"]),
            "repository": str(row["repository"]),
            "target_base_ref": str(row["target_base_ref"]),
            "branch_ref": str(row["branch_ref"]),
            "baseline_head": str(row["baseline_head"]),
            "baseline_head_short": str(row["baseline_head"])[:12],
            "commit_sha": str(row["commit_sha"]),
            "commit_sha_short": str(row["commit_sha"])[:12],
            "commit_fingerprint": str(row["commit_fingerprint"]),
            "changed_fingerprint": str(row["changed_fingerprint"]),
            "diff_fingerprint": str(row["diff_fingerprint"]),
            "requested_action": str(row["requested_action"]),
            "authority": str(row["authority"]),
            "state": str(row["state"]),
            "created_at": str(row["created_at"]),
        }

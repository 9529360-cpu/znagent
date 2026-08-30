from __future__ import annotations

"""Prepare an accepted maintenance repair for publication without remote authority.

This owner is deliberately narrower than a publisher. It can turn one already
accepted, semantically reviewed isolated repair attempt into one local commit on
the exact recorded ``work/*`` branch. It cannot push, create a pull request,
merge, release, update an installed body, or consume repository credentials.

The commit is produced only after re-proving the repair evidence against the live
worktree. Source-origin continuity is checked against the opaque fingerprint from
the trusted-source investigation; no private repository identity is compiled into
the installed runtime.
"""

import hashlib
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from .maintenance_investigation import MaintenanceInvestigationLedger
from .models import utc_now

_ATTEMPT_DIR = ".zn-maintenance-worktrees"
_MAX_CHANGED_PATHS = 64


class MaintenancePublicationPreparation:
    """Create exactly one local commit from one accepted maintenance attempt."""

    def __init__(self, store, ledger: MaintenanceInvestigationLedger):
        self.store = store
        self.ledger = ledger
        self._init_schema()

    def prepare(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        normalized_task = str(task_id or "").strip()
        if not normalized_task:
            raise ValueError("maintenance publication preparation requires task_id")
        investigation = self.ledger.get(normalized_task)
        if investigation is None:
            raise ValueError("maintenance investigation does not exist")
        if str(investigation.get("source_task_status") or "") != "open":
            raise RuntimeError("closed maintenance task cannot be prepared for publication")
        if str(investigation.get("status") or "") != "accepted":
            raise RuntimeError("maintenance publication preparation requires accepted investigation")
        if str(investigation.get("acceptance_state") or "") != "accepted":
            raise RuntimeError("maintenance publication preparation requires accepted evidence")
        attempt_key = str(investigation.get("accepted_attempt_key") or "").strip()
        if not attempt_key:
            raise RuntimeError("accepted maintenance investigation has no accepted attempt")

        evidence = self._attempt_evidence(normalized_task, attempt_key)
        if evidence is None:
            raise RuntimeError("accepted maintenance repair evidence is unavailable")
        if not bool(evidence["regression_passed"]) or not bool(evidence["diff_check_passed"]):
            raise RuntimeError("maintenance publication preparation requires passing repair evidence")
        if str(evidence["authority"] or "") != "isolated_source_write":
            raise RuntimeError("maintenance publication preparation repair authority is invalid")

        review = self._semantic_review(normalized_task, attempt_key)
        if review is None or str(review["decision"] or "") != "accept":
            raise RuntimeError("maintenance publication preparation requires semantic acceptance")

        expected_origin = self._source_origin(normalized_task)
        if not expected_origin:
            raise RuntimeError("maintenance publication source origin fingerprint is unavailable")

        existing = self._prepared(normalized_task, attempt_key)
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
            raise RuntimeError("maintenance publication source verification failed")
        if Path(top.stdout.strip()).expanduser().resolve(strict=True) != source:
            raise RuntimeError("maintenance publication source must be repository root")
        if self._origin_fingerprint(remote.stdout.strip()) != expected_origin:
            raise RuntimeError("maintenance publication source origin changed")

        branch = str(evidence["branch_ref"] or "").strip()
        baseline_head = str(evidence["baseline_head"] or "").strip()
        if not branch.startswith("work/") or not baseline_head:
            raise RuntimeError("maintenance publication branch contract is invalid")
        worktrees = git_at(source, "worktree", "list", "--porcelain")
        if worktrees.returncode != 0:
            raise RuntimeError("maintenance publication could not enumerate worktrees")
        record = self._find_worktree(worktrees.stdout, branch)
        if record is None:
            raise RuntimeError("maintenance publication accepted worktree is unavailable")
        attempt_root = Path(record["path"]).expanduser().resolve(strict=True)
        if attempt_root.parent != (source.parent / _ATTEMPT_DIR).resolve(strict=False):
            raise RuntimeError("maintenance publication worktree escaped dedicated directory")

        branch_now = git_at(attempt_root, "branch", "--show-current")
        head_now = git_at(attempt_root, "rev-parse", "--verify", "HEAD")
        if branch_now.returncode != 0 or head_now.returncode != 0:
            raise RuntimeError("maintenance publication worktree identity verification failed")
        if branch_now.stdout.strip() != branch:
            raise RuntimeError("maintenance publication worktree branch drifted")

        if existing is not None:
            commit_sha = str(existing["commit_sha"])
            if head_now.stdout.strip() != commit_sha:
                raise RuntimeError("prepared maintenance publication branch moved after preparation")
            parent = git_at(attempt_root, "rev-parse", "--verify", "HEAD^")
            status = git_at(attempt_root, "status", "--porcelain=v1", "-z")
            if parent.returncode != 0 or parent.stdout.strip() != baseline_head or status.stdout:
                raise RuntimeError("prepared maintenance publication no longer matches evidence")
            return self._row_snapshot(existing)

        if head_now.stdout.strip() != baseline_head or str(record.get("head") or "") != baseline_head:
            raise RuntimeError("maintenance publication branch advanced before preparation")

        changed = git_at(
            attempt_root,
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            "--",
        )
        if changed.returncode != 0:
            raise RuntimeError("maintenance publication could not enumerate repair diff")
        changed_paths = [path for path in changed.stdout.split("\x00") if path]
        if not changed_paths or len(changed_paths) > _MAX_CHANGED_PATHS:
            raise RuntimeError("maintenance publication changed-path evidence is invalid")
        changed_fingerprint = self._fingerprint(
            "zn-maintenance-repair-paths-v1", "\n".join(changed_paths)
        )
        if changed_fingerprint != str(evidence["changed_fingerprint"]):
            raise RuntimeError("maintenance publication changed paths drifted from repair evidence")

        diff = git_at(attempt_root, "diff", "--no-ext-diff", "--unified=0", "--")
        diff_check = git_at(attempt_root, "diff", "--check")
        if diff.returncode != 0 or diff_check.returncode != 0:
            raise RuntimeError("maintenance publication live diff failed validation")
        diff_fingerprint = self._fingerprint(
            "zn-maintenance-repair-diff-v1", diff.stdout
        )
        if diff_fingerprint != str(evidence["diff_fingerprint"]):
            raise RuntimeError("maintenance publication diff drifted from repair evidence")

        add = git_at(attempt_root, "add", "--", *changed_paths)
        if add.returncode != 0:
            raise RuntimeError("maintenance publication could not stage accepted repair")
        staged = git_at(
            attempt_root,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            "--",
        )
        staged_paths = [path for path in staged.stdout.split("\x00") if path]
        if staged.returncode != 0 or staged_paths != changed_paths:
            self._unstage(attempt_root, git_at, baseline_head)
            raise RuntimeError("maintenance publication staged scope differs from accepted repair")

        subject = f"ZN maintenance repair {normalized_task[:12]}"
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(attempt_root),
                "-c",
                "user.name=ZN Maintenance",
                "-c",
                "user.email=maintenance@zn.invalid",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "--no-verify",
                "--no-gpg-sign",
                "-m",
                subject,
            ],
            capture_output=True,
            text=True,
            timeout=bounded_timeout,
            check=False,
        )
        if commit.returncode != 0:
            self._unstage(attempt_root, git_at, baseline_head)
            raise RuntimeError("maintenance publication could not create local repair commit")

        commit_sha_proc = git_at(attempt_root, "rev-parse", "--verify", "HEAD")
        parent = git_at(attempt_root, "rev-parse", "--verify", "HEAD^")
        status = git_at(attempt_root, "status", "--porcelain=v1", "-z")
        committed_paths = git_at(
            attempt_root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-z",
            "-r",
            "HEAD",
            "--",
        )
        if any(proc.returncode != 0 for proc in (commit_sha_proc, parent, status, committed_paths)):
            raise RuntimeError("maintenance publication commit verification failed")
        commit_sha = commit_sha_proc.stdout.strip()
        final_paths = [path for path in committed_paths.stdout.split("\x00") if path]
        if parent.stdout.strip() != baseline_head:
            raise RuntimeError("maintenance publication commit parent is not accepted baseline")
        if final_paths != changed_paths:
            raise RuntimeError("maintenance publication commit scope differs from accepted repair")
        if status.stdout:
            raise RuntimeError("maintenance publication worktree is dirty after local commit")

        now = utc_now()
        commit_fingerprint = self._fingerprint(
            "zn-maintenance-publication-commit-v1",
            "\x00".join(
                [normalized_task, attempt_key, branch, baseline_head, commit_sha, diff_fingerprint]
            ),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO resident_maintenance_publication_preparation("
                "task_id,attempt_key,branch_ref,baseline_head,commit_sha,commit_fingerprint,"
                "changed_files,changed_fingerprint,diff_fingerprint,authority,prepared_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    normalized_task,
                    attempt_key,
                    branch,
                    baseline_head,
                    commit_sha,
                    commit_fingerprint,
                    len(changed_paths),
                    changed_fingerprint,
                    diff_fingerprint,
                    "local_commit_only",
                    now,
                ),
            )
            conn.commit()
        row = self._prepared(normalized_task, attempt_key)
        assert row is not None
        return self._row_snapshot(row)

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_publication_preparation"
                ).fetchone()[0]
            )
            rows = conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,commit_sha,"
                "commit_fingerprint,changed_files,changed_fingerprint,diff_fingerprint,"
                "authority,prepared_at FROM resident_maintenance_publication_preparation "
                "ORDER BY prepared_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return {
            "prepared_count": total,
            "returned_count": len(rows),
            "truncated": total > len(rows),
            "prepared": [self._row_snapshot(row) for row in rows],
        }

    def _source_origin(self, task_id: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT repository FROM resident_maintenance_source_evidence WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        value = str(row["repository"] or "").strip()
        return value or None

    def _attempt_evidence(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,changed_files,"
                "changed_fingerprint,diff_fingerprint,regression_oracle,regression_passed,"
                "diff_check_passed,authority,created_at FROM "
                "resident_maintenance_repair_attempt_evidence WHERE task_id=? AND attempt_key=?",
                (task_id, attempt_key),
            ).fetchone()

    def _semantic_review(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,attempt_key,candidate_key,decision,reason_code,route_id,provider,"
                "model,independent_route,created_at FROM resident_maintenance_semantic_reviews "
                "WHERE task_id=? AND attempt_key=?",
                (task_id, attempt_key),
            ).fetchone()

    def _prepared(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,attempt_key,branch_ref,baseline_head,commit_sha,"
                "commit_fingerprint,changed_files,changed_fingerprint,diff_fingerprint,"
                "authority,prepared_at FROM resident_maintenance_publication_preparation "
                "WHERE task_id=? AND attempt_key=?",
                (task_id, attempt_key),
            ).fetchone()

    @staticmethod
    def _unstage(root: Path, git_at, baseline_head: str) -> None:
        try:
            git_at(root, "reset", "--mixed", baseline_head)
        except Exception:
            pass

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

    @classmethod
    def _origin_fingerprint(cls, value: str) -> str:
        origin = str(value or "").strip()
        if not origin:
            raise RuntimeError("maintenance publication source origin is unavailable")
        return cls._fingerprint("zn-maintenance-origin-v1", origin)

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
                "CREATE TABLE IF NOT EXISTS resident_maintenance_publication_preparation ("
                "task_id TEXT NOT NULL,attempt_key TEXT NOT NULL,branch_ref TEXT NOT NULL,"
                "baseline_head TEXT NOT NULL,commit_sha TEXT NOT NULL,"
                "commit_fingerprint TEXT NOT NULL,changed_files INTEGER NOT NULL,"
                "changed_fingerprint TEXT NOT NULL,diff_fingerprint TEXT NOT NULL,"
                "authority TEXT NOT NULL,prepared_at TEXT NOT NULL,"
                "PRIMARY KEY(task_id,attempt_key))"
            )
            conn.commit()

    @staticmethod
    def _row_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        commit_sha = str(row["commit_sha"])
        baseline_head = str(row["baseline_head"])
        return {
            "task_id": str(row["task_id"]),
            "attempt_key": str(row["attempt_key"]),
            "branch_ref": str(row["branch_ref"]),
            "baseline_head": baseline_head,
            "baseline_head_short": baseline_head[:12],
            "commit_sha": commit_sha,
            "commit_sha_short": commit_sha[:12],
            "commit_fingerprint": str(row["commit_fingerprint"]),
            "changed_files": int(row["changed_files"]),
            "changed_fingerprint": str(row["changed_fingerprint"]),
            "diff_fingerprint": str(row["diff_fingerprint"]),
            "authority": str(row["authority"]),
            "prepared_at": str(row["prepared_at"]),
        }

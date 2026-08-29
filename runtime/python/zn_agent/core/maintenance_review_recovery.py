from __future__ import annotations

"""Recovery of an isolated repair that waited for an independent semantic reviewer.

The recovery path is intentionally narrow: it only resumes attempts whose durable
semantic state says that no independent route was available and for which no
semantic-review provider dispatch has ever been recorded. Candidate source is
reconstructed from the still-isolated worktree and revalidated against the original
repair fingerprints before cognition is allowed to continue.
"""

import hashlib
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from .maintenance_cognitive import MaintenanceRepairCandidate

_ATTEMPT_DIR = ".zn-maintenance-worktrees"


class MaintenancePendingReviewRecovery:
    """Resume semantic review without replaying an ambiguous model call."""

    def __init__(self, store, ledger, orchestrator):
        self.store = store
        self.ledger = ledger
        self.orchestrator = orchestrator

    def review(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        normalized_task = str(task_id or "").strip()
        if not normalized_task:
            raise ValueError("maintenance review recovery requires task_id")
        investigation = self.ledger.get(normalized_task)
        if investigation is None:
            raise ValueError("maintenance investigation does not exist")
        if str(investigation.get("status") or "") != "investigating":
            raise RuntimeError("maintenance review recovery requires an investigating task")
        if str(investigation.get("acceptance_state") or "") != "unreviewed":
            raise RuntimeError("maintenance review recovery requires an unreviewed attempt")

        attempt = self._latest_attempt(normalized_task)
        if attempt is None:
            raise RuntimeError("maintenance review recovery has no durable repair attempt")
        if not bool(attempt["regression_passed"]) or not bool(attempt["diff_check_passed"]):
            raise RuntimeError("maintenance review recovery requires a verified repair attempt")

        review = self._semantic_review(normalized_task, str(attempt["attempt_key"]))
        if review is None or str(review["decision"] or "") != "unreviewed":
            raise RuntimeError("maintenance review recovery requires durable unreviewed evidence")
        if str(review["reason_code"] or "") not in {
            "independent_route_unavailable",
            "author_route_unavailable",
        }:
            raise RuntimeError("maintenance review recovery reason is not resumable")
        if self._semantic_dispatch_count(normalized_task) != 0:
            raise RuntimeError("maintenance semantic dispatch already exists; recovery replay is blocked")

        branch = str(attempt["branch_ref"] or "").strip()
        baseline = str(attempt["baseline_head"] or "").strip()
        if not branch.startswith("work/") or not baseline:
            raise RuntimeError("maintenance review recovery attempt contract is invalid")
        candidate_row = self._candidate(normalized_task, branch, baseline)
        if candidate_row is None:
            raise RuntimeError("maintenance review recovery candidate evidence is unavailable")
        author_route = str(candidate_row["route_id"] or "").strip()
        if not author_route:
            raise RuntimeError("maintenance review recovery author route is unavailable")

        task, evidence, source = self.orchestrator._trusted_context(normalized_task, source_root)
        if str(evidence["head"] or "") != baseline:
            raise RuntimeError("maintenance review recovery baseline evidence drifted")
        bounded_timeout = max(3.0, min(60.0, float(timeout)))

        def git(root: Path, *parts: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "-C", str(root), *parts],
                capture_output=True,
                text=True,
                timeout=bounded_timeout,
                check=False,
            )

        branch_head = git(source, "rev-parse", "--verify", f"refs/heads/{branch}")
        worktrees = git(source, "worktree", "list", "--porcelain")
        if branch_head.returncode != 0 or worktrees.returncode != 0:
            raise RuntimeError("maintenance review recovery could not verify isolated branch")
        if branch_head.stdout.strip() != baseline:
            raise RuntimeError("maintenance review recovery branch advanced before review")
        worktree = self._find_worktree(worktrees.stdout, branch)
        if worktree is None:
            raise RuntimeError("maintenance review recovery could not resolve isolated worktree")
        isolated = Path(worktree["path"]).expanduser().resolve(strict=True)
        if isolated.parent != (source.parent / _ATTEMPT_DIR).resolve(strict=False):
            raise RuntimeError("maintenance review recovery worktree escaped dedicated directory")
        if str(worktree.get("head") or "") != baseline:
            raise RuntimeError("maintenance review recovery worktree HEAD drifted")

        changed_proc = git(isolated, "diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB")
        check_proc = git(isolated, "diff", "--check")
        diff_proc = git(isolated, "diff", "--no-ext-diff", "--unified=0", "--")
        if any(proc.returncode != 0 for proc in (changed_proc, check_proc, diff_proc)):
            raise RuntimeError("maintenance review recovery diff verification failed")
        changed_paths = [item for item in changed_proc.stdout.split("\0") if item]
        if not changed_paths:
            raise RuntimeError("maintenance review recovery candidate diff disappeared")
        changed_fingerprint = self._fingerprint(
            "zn-maintenance-repair-paths-v1", "\n".join(changed_paths)
        )
        diff_fingerprint = self._fingerprint(
            "zn-maintenance-repair-diff-v1", diff_proc.stdout
        )
        if changed_fingerprint != str(attempt["changed_fingerprint"] or ""):
            raise RuntimeError("maintenance review recovery changed-path fingerprint drifted")
        if diff_fingerprint != str(attempt["diff_fingerprint"] or ""):
            raise RuntimeError("maintenance review recovery diff fingerprint drifted")

        raw_replacements = {
            path: (isolated / path).read_text(encoding="utf-8") for path in changed_paths
        }
        replacements = self.orchestrator._replacement_contract(
            source,
            raw_replacements,
            allowed_paths=set(changed_paths),
        )
        candidate = MaintenanceRepairCandidate(
            task_id=normalized_task,
            candidate_key=str(candidate_row["candidate_key"]),
            baseline_head=baseline,
            regression_oracle=str(evidence["regression_oracle"]),
            branch_ref=branch,
            replacements=replacements,
            rationale="",
            author_route_id=author_route,
            author_provider=str(candidate_row["provider"] or ""),
            author_model=str(candidate_row["model"] or ""),
        )
        review_result = self.orchestrator.review_attempt(
            normalized_task,
            candidate=candidate,
            source_root=source,
            attempt_root=isolated,
            attempt={
                "attempt_key": str(attempt["attempt_key"]),
                "regression_passed": True,
            },
        )
        return {
            "task_id": normalized_task,
            "attempt_key": str(attempt["attempt_key"]),
            "branch_ref": branch,
            "semantic_review": review_result,
            "investigation": self.ledger.get(normalized_task),
        }

    def _latest_attempt(self, task_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT a.task_id,a.attempt_key,a.branch_ref,a.regression_passed,a.created_at,"
                "e.baseline_head,e.changed_fingerprint,e.diff_fingerprint,e.diff_check_passed "
                "FROM resident_maintenance_attempts a JOIN "
                "resident_maintenance_repair_attempt_evidence e "
                "ON e.task_id=a.task_id AND e.attempt_key=a.attempt_key "
                "WHERE a.task_id=? ORDER BY a.created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()

    def _semantic_review(self, task_id: str, attempt_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT decision,reason_code,independent_route FROM "
                "resident_maintenance_semantic_reviews WHERE task_id=? AND attempt_key=?",
                (task_id, attempt_key),
            ).fetchone()

    def _semantic_dispatch_count(self, task_id: str) -> int:
        with closing(self._connect()) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_cognition_dispatch "
                    "WHERE task_id=? AND phase='semantic_review'",
                    (task_id,),
                ).fetchone()[0]
            )

    def _candidate(self, task_id: str, branch: str, baseline: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT candidate_key,route_id,provider,model FROM resident_maintenance_candidates "
                "WHERE task_id=? AND branch_ref=? AND baseline_head=? "
                "ORDER BY created_at DESC LIMIT 1",
                (task_id, branch, baseline),
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
            if key == "worktree":
                current["path"] = value.strip()
            elif key == "HEAD":
                current["head"] = value.strip()
            elif key == "branch":
                current["branch"] = value.strip()
        if current:
            records.append(current)
        matches = [row for row in records if row.get("branch") == expected_ref]
        if len(matches) != 1 or not matches[0].get("path"):
            return None
        return matches[0]

    @staticmethod
    def _fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(value).encode("utf-8", errors="replace"))
        return digest.hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.store.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class VeteranProjectionError(RuntimeError):
    """Candidate projection cannot proceed without crossing ZN's workspace authority."""


@dataclass(frozen=True, slots=True)
class VeteranFinalCandidate:
    mission_id: str
    candidate_id: str
    candidate_commit: str
    source_head: str
    merge_proposal_id: str
    candidate_ref: str | None = None


@dataclass(frozen=True, slots=True)
class VeteranProjectionResult:
    source_head: str
    candidate_commit: str
    paths: tuple[str, ...]
    already_applied: bool


def final_candidate_from_status(status: Mapping[str, Any]) -> VeteranFinalCandidate:
    mission = status.get("mission")
    if not isinstance(mission, dict):
        raise VeteranProjectionError("Veteran status has no mission object")
    mission_id = str(mission.get("id") or "").strip()
    candidate_id = str(mission.get("activeCandidateId") or "").strip()
    proposal_id = str(mission.get("activeMergeProposalId") or "").strip()
    if (
        not mission_id
        or mission.get("phase") != "finalize"
        or mission.get("status") != "awaiting-operator-merge"
        or not candidate_id
        or not proposal_id
    ):
        raise VeteranProjectionError(
            "Veteran mission is not at the operator-owned final candidate boundary"
        )

    candidates = status.get("candidates")
    proposals = status.get("mergeProposals")
    candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("id") == candidate_id
        ),
        None,
    ) if isinstance(candidates, list) else None
    proposal = next(
        (
            item
            for item in proposals
            if isinstance(item, dict) and item.get("id") == proposal_id
        ),
        None,
    ) if isinstance(proposals, list) else None
    if not isinstance(candidate, dict) or not isinstance(proposal, dict):
        raise VeteranProjectionError("Veteran final candidate/proposal identity is missing")

    commit_sha = str(candidate.get("commitSha") or "").strip()
    source_head = str(candidate.get("sourceHead") or "").strip()
    if (
        not commit_sha
        or not source_head
        or proposal.get("status") != "proposed"
        or proposal.get("candidateId") != candidate_id
        or str(proposal.get("candidateCommitSha") or "").strip() != commit_sha
        or str(proposal.get("expectedSourceHead") or "").strip() != source_head
        or proposal.get("automaticMerge") is not False
        or proposal.get("automaticPush") is not False
        or proposal.get("requiresOperatorAction") is not True
    ):
        raise VeteranProjectionError("Veteran merge proposal is not bound to the immutable candidate")

    proof = proposal.get("proof")
    if not isinstance(proof, dict):
        raise VeteranProjectionError("Veteran merge proposal has no proof bundle")
    for name in ("validation", "review", "semanticReview"):
        item = proof.get(name)
        if not isinstance(item, dict) or item.get("status") not in {"passed", "skipped"}:
            raise VeteranProjectionError(f"Veteran {name} proof is not complete")

    return VeteranFinalCandidate(
        mission_id=mission_id,
        candidate_id=candidate_id,
        candidate_commit=commit_sha,
        source_head=source_head,
        merge_proposal_id=proposal_id,
        candidate_ref=str(candidate.get("ref") or "").strip() or None,
    )


class VeteranCandidateProjector:
    """Project a proved candidate into a clean checkout without changing HEAD or index."""

    _MAX_PATHS = 128
    _MAX_FILE_BYTES = 2_000_000
    _MAX_TOTAL_BYTES = 12_000_000
    _REGULAR_MODES = frozenset({"100644", "100755"})

    def __init__(self, workspace: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
        root = Path(self._git_text(["rev-parse", "--show-toplevel"])).resolve(strict=True)
        if root != self.workspace:
            raise VeteranProjectionError(
                "Veteran candidate projection V1 requires the attached workspace to be the Git root"
            )

    def project(self, candidate: VeteranFinalCandidate) -> VeteranProjectionResult:
        head = self._git_text(["rev-parse", "HEAD"])
        if head != candidate.source_head:
            raise VeteranProjectionError(
                f"workspace HEAD changed: expected {candidate.source_head}, observed {head}"
            )
        self._require_commit(candidate.candidate_commit)
        ancestor = self._git(
            ["merge-base", "--is-ancestor", candidate.source_head, candidate.candidate_commit],
            allow=(0, 1),
        )
        if ancestor.returncode != 0:
            raise VeteranProjectionError("Veteran candidate is not descended from the bound source HEAD")

        paths = self._candidate_paths(candidate.source_head, candidate.candidate_commit)
        if not paths:
            raise VeteranProjectionError("Veteran candidate contains no workspace change")
        if len(paths) > self._MAX_PATHS:
            raise VeteranProjectionError(
                f"Veteran candidate changes {len(paths)} paths; V1 limit is {self._MAX_PATHS}"
            )

        identities = self._path_identities(
            candidate.source_head,
            candidate.candidate_commit,
            paths,
        )
        self._require_index_clean()
        self._require_no_extra_workspace_changes(paths)
        before = self._classify_workspace(identities)
        if all(value == "candidate" for value in before.values()):
            return VeteranProjectionResult(
                source_head=candidate.source_head,
                candidate_commit=candidate.candidate_commit,
                paths=paths,
                already_applied=True,
            )
        unknown = [path for path, state in before.items() if state == "unknown"]
        if unknown:
            raise VeteranProjectionError(
                "workspace contains content that is neither the bound base nor candidate: "
                + ", ".join(unknown[:12])
            )

        path_input = b"".join(path.encode("utf-8") + b"\0" for path in paths)
        restored = self._git(
            [
                "--literal-pathspecs",
                "restore",
                f"--source={candidate.candidate_commit}",
                "--worktree",
                "--no-overlay",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
            ],
            input_bytes=path_input,
        )
        if restored.returncode != 0:
            raise VeteranProjectionError(
                "git restore could not project the immutable Veteran candidate: "
                + self._bounded_error(restored)
            )

        if self._git_text(["rev-parse", "HEAD"]) != candidate.source_head:
            raise VeteranProjectionError("workspace HEAD changed during candidate projection")
        self._require_index_clean()
        self._require_no_extra_workspace_changes(paths)
        after = self._classify_workspace(identities)
        mismatched = [path for path, state in after.items() if state != "candidate"]
        if mismatched:
            raise VeteranProjectionError(
                "workspace did not match projected candidate content: "
                + ", ".join(mismatched[:12])
            )
        return VeteranProjectionResult(
            source_head=candidate.source_head,
            candidate_commit=candidate.candidate_commit,
            paths=paths,
            already_applied=False,
        )

    def _candidate_paths(self, source_head: str, candidate_commit: str) -> tuple[str, ...]:
        result = self._git(
            [
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                source_head,
                candidate_commit,
                "--",
            ]
        )
        if result.returncode != 0:
            raise VeteranProjectionError("failed to enumerate Veteran candidate paths")
        raw_paths = [
            item.decode("utf-8", errors="strict")
            for item in result.stdout.split(b"\0")
            if item
        ]
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in raw_paths:
            path = raw.replace("\\", "/")
            parts = Path(path).parts
            if (
                not path
                or path.startswith("/")
                or not parts
                or any(part in {"", ".", ".."} for part in parts)
                or parts[0].casefold() == ".git"
            ):
                raise VeteranProjectionError(f"unsafe candidate path: {raw!r}")
            if path not in seen:
                seen.add(path)
                normalized.append(path)
        return tuple(normalized)

    def _path_identities(
        self,
        source_head: str,
        candidate_commit: str,
        paths: tuple[str, ...],
    ) -> dict[str, tuple[str | None, str | None]]:
        identities: dict[str, tuple[str | None, str | None]] = {}
        total_bytes = 0
        for path in paths:
            base_mode, base_oid = self._tree_entry(source_head, path)
            candidate_mode, candidate_oid = self._tree_entry(candidate_commit, path)
            for mode in (base_mode, candidate_mode):
                if mode is not None and mode not in self._REGULAR_MODES:
                    raise VeteranProjectionError(
                        f"candidate path is not a regular file in V1: {path} mode={mode}"
                    )
            if candidate_oid is not None:
                size_text = self._git_text(["cat-file", "-s", candidate_oid])
                try:
                    size = int(size_text)
                except ValueError as exc:
                    raise VeteranProjectionError(
                        f"invalid candidate blob size for {path}"
                    ) from exc
                if size > self._MAX_FILE_BYTES:
                    raise VeteranProjectionError(
                        f"candidate file exceeds {self._MAX_FILE_BYTES} bytes: {path}"
                    )
                total_bytes += size
                if total_bytes > self._MAX_TOTAL_BYTES:
                    raise VeteranProjectionError(
                        f"candidate exceeds {self._MAX_TOTAL_BYTES} projected bytes"
                    )
            identities[path] = (base_oid, candidate_oid)
        return identities

    def _tree_entry(self, treeish: str, path: str) -> tuple[str | None, str | None]:
        result = self._git(
            ["--literal-pathspecs", "ls-tree", "-z", treeish, "--", path]
        )
        if result.returncode != 0:
            raise VeteranProjectionError(f"failed to inspect Git tree entry for {path}")
        if not result.stdout:
            return None, None
        line = result.stdout.split(b"\0", 1)[0]
        try:
            metadata, _ = line.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ", 2)
        except (ValueError, UnicodeDecodeError) as exc:
            raise VeteranProjectionError(f"invalid Git tree entry for {path}") from exc
        if kind != "blob":
            raise VeteranProjectionError(f"candidate path is not a blob: {path}")
        return mode, oid

    def _classify_workspace(
        self,
        identities: Mapping[str, tuple[str | None, str | None]],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for relative_path, (base_oid, candidate_oid) in identities.items():
            target = self.workspace / Path(relative_path)
            if target.is_symlink():
                result[relative_path] = "unknown"
                continue
            current_oid: str | None
            if target.exists():
                if not target.is_file():
                    result[relative_path] = "unknown"
                    continue
                hashed = self._git(
                    ["--literal-pathspecs", "hash-object", "--", relative_path]
                )
                if hashed.returncode != 0:
                    result[relative_path] = "unknown"
                    continue
                current_oid = hashed.stdout.decode("ascii", errors="strict").strip() or None
            else:
                current_oid = None
            if current_oid == candidate_oid:
                result[relative_path] = "candidate"
            elif current_oid == base_oid:
                result[relative_path] = "base"
            else:
                result[relative_path] = "unknown"
        return result

    def _require_index_clean(self) -> None:
        result = self._git(["diff", "--cached", "--quiet", "--exit-code"], allow=(0, 1))
        if result.returncode == 1:
            raise VeteranProjectionError("candidate projection refuses staged workspace changes")
        if result.returncode != 0:
            raise VeteranProjectionError("could not verify Git index state")

    def _require_no_extra_workspace_changes(self, expected_paths: tuple[str, ...]) -> None:
        expected = set(expected_paths)
        result = self._git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
        )
        if result.returncode != 0:
            raise VeteranProjectionError("could not verify working tree state")
        dirty = self._porcelain_paths(result.stdout)
        extra = sorted(path for path in dirty if path not in expected)
        if extra:
            raise VeteranProjectionError(
                "workspace has changes outside the Veteran candidate: "
                + ", ".join(extra[:12])
            )

    @staticmethod
    def _porcelain_paths(payload: bytes) -> set[str]:
        fields = payload.split(b"\0")
        paths: set[str] = set()
        index = 0
        while index < len(fields):
            field = fields[index]
            index += 1
            if not field:
                continue
            if len(field) < 4 or field[2:3] != b" ":
                raise VeteranProjectionError("unrecognized git status record")
            status = field[:2]
            path = field[3:].decode("utf-8", errors="strict").replace("\\", "/")
            if b"R" in status or b"C" in status:
                if index >= len(fields) or not fields[index]:
                    raise VeteranProjectionError("incomplete git rename/copy status")
                second = fields[index].decode("utf-8", errors="strict").replace("\\", "/")
                index += 1
                paths.add(second)
            paths.add(path)
        return paths

    def _require_commit(self, revision: str) -> None:
        result = self._git(["cat-file", "-e", f"{revision}^{{commit}}"])
        if result.returncode != 0:
            raise VeteranProjectionError(f"Veteran candidate commit does not exist: {revision}")

    def _git_text(self, args: list[str]) -> str:
        result = self._git(args)
        if result.returncode != 0:
            raise VeteranProjectionError(
                "Git command failed: " + self._bounded_error(result)
            )
        return result.stdout.decode("utf-8", errors="strict").strip()

    def _git(
        self,
        args: list[str],
        *,
        allow: tuple[int, ...] = (0,),
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.workspace,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VeteranProjectionError(f"Git invocation failed: {exc}") from exc
        if result.returncode not in allow:
            return result
        return result

    @staticmethod
    def _bounded_error(result: subprocess.CompletedProcess[bytes]) -> str:
        text = result.stderr.decode("utf-8", errors="replace").strip()
        if not text:
            text = result.stdout.decode("utf-8", errors="replace").strip()
        return text[-2000:] or f"exit code {result.returncode}"

from __future__ import annotations

"""Bounded cognitive authoring and semantic review for resident maintenance.

External models remain replaceable cognitive resources. They never receive Git,
terminal, arbitrary filesystem, merge, release, updater, or installation authority
through this module. Source text is read only from a previously trusted clean ZN
checkout and only inside the existing maintenance repair boundary. Every model
output is parsed into a narrow JSON contract and revalidated locally before the
existing isolated repair operator is allowed to write anything.
"""

import hashlib
import json
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .maintenance_investigation import MaintenanceInvestigationLedger
from .maintenance_repair import MaintenanceIsolatedRepairOperator
from .models import Goal
from .router import NoRouteAvailable

_ALLOWED_PREFIXES = (
    PurePosixPath("runtime/python/zn_agent/core"),
    PurePosixPath("tests/zn_agent/core"),
)
_MAX_CATALOG_PATHS = 512
_MAX_TARGETS = 4
_MAX_SOURCE_FILE_BYTES = 128 * 1024
_MAX_SOURCE_BYTES = 320 * 1024
_MAX_REPLACEMENT_FILE_BYTES = 512 * 1024
_MAX_MODEL_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_DIFF_BYTES = 256 * 1024
_REASON_RE = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(slots=True)
class MaintenanceRepairCandidate:
    task_id: str
    candidate_key: str
    baseline_head: str
    regression_oracle: str
    branch_ref: str
    replacements: dict[str, str]
    rationale: str
    author_route_id: str
    author_provider: str
    author_model: str


class MaintenanceCognitiveRepairOrchestrator:
    """Derive, execute, and semantically review one bounded repair candidate."""

    def __init__(
        self,
        store,
        ledger: MaintenanceInvestigationLedger,
        operator: MaintenanceIsolatedRepairOperator,
        kernel,
    ):
        self.store = store
        self.ledger = ledger
        self.operator = operator
        self.kernel = kernel
        self._init_schema()

    def derive_candidate(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        branch_ref: str,
    ) -> MaintenanceRepairCandidate:
        task, evidence, source = self._trusted_context(task_id, source_root)
        catalog = self._source_catalog(source)
        if not catalog:
            raise RuntimeError("maintenance candidate source catalog is empty")

        select_question = (
            "Choose the smallest set of existing Python files that should be inspected "
            "for this ZN defect. Return strict JSON only with shape "
            '{"paths":["repository/path.py"],"rationale":"short reason"}. '
            f"Choose 1-{_MAX_TARGETS} paths, only from the supplied catalog."
        )
        select_context = json.dumps(
            {
                "role": "ZN bounded maintenance target selector",
                "task": self._task_context(task),
                "baseline_head": evidence["head"],
                "regression_oracle": evidence["regression_oracle"],
                "source_catalog": catalog,
                "constraints": {
                    "no_tools": True,
                    "no_git": True,
                    "no_shell": True,
                    "existing_python_files_only": True,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        select_text, select_meta = self._invoke(
            question=select_question,
            context=select_context,
            excluded_routes=frozenset(),
        )
        selection = self._json_object(select_text)
        paths = self._selected_paths(selection.get("paths"), catalog)

        sources = self._read_sources(source, paths)
        author_question = (
            "Produce the smallest complete repair for the supplied files. Return strict JSON "
            "only with shape {\"replacements\":{\"repository/path.py\":\"full UTF-8 file "
            "content\"},\"rationale\":\"short reason\"}. Do not add paths that were not "
            "selected. Do not emit markdown fences, shell commands, Git commands, or prose "
            "outside the JSON object."
        )
        author_context = json.dumps(
            {
                "role": "ZN bounded maintenance repair author",
                "task": self._task_context(task),
                "baseline_head": evidence["head"],
                "regression_oracle": evidence["regression_oracle"],
                "selected_sources": sources,
                "constraints": {
                    "no_tools": True,
                    "no_git": True,
                    "no_shell": True,
                    "full_file_replacements_only": True,
                    "max_files": _MAX_TARGETS,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        author_text, author_meta = self._invoke(
            question=author_question,
            context=author_context,
            excluded_routes=frozenset(),
        )
        authored = self._json_object(author_text)
        replacements = self._replacement_contract(
            source,
            authored.get("replacements"),
            allowed_paths=set(paths),
        )
        rationale = str(authored.get("rationale") or selection.get("rationale") or "").strip()
        rationale = rationale[:2000]
        candidate_key = self._fingerprint(
            "zn-maintenance-candidate-v1",
            json.dumps(
                {
                    "task_id": str(task_id),
                    "head": str(evidence["head"]),
                    "oracle": str(evidence["regression_oracle"]),
                    "branch": str(branch_ref),
                    "paths": sorted(replacements),
                    "content_hashes": {
                        path: self._fingerprint("zn-maintenance-replacement-v1", content)
                        for path, content in sorted(replacements.items())
                    },
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        route_id = str(author_meta.get("route_id") or select_meta.get("route_id") or "")
        provider = str(author_meta.get("provider") or "")
        model = str(author_meta.get("model") or "")
        self._record_candidate(
            task_id=str(task_id),
            candidate_key=candidate_key,
            baseline_head=str(evidence["head"]),
            branch_ref=str(branch_ref),
            paths=sorted(replacements),
            rationale=rationale,
            route_id=route_id,
            provider=provider,
            model=model,
        )
        return MaintenanceRepairCandidate(
            task_id=str(task_id),
            candidate_key=candidate_key,
            baseline_head=str(evidence["head"]),
            regression_oracle=str(evidence["regression_oracle"]),
            branch_ref=str(branch_ref),
            replacements=replacements,
            rationale=rationale,
            author_route_id=route_id,
            author_provider=provider,
            author_model=model,
        )

    def derive_execute_and_review(
        self,
        task_id: str,
        *,
        source_root: str | Path,
        attempt_root: str | Path,
        branch_ref: str,
    ) -> dict[str, Any]:
        candidate = self.derive_candidate(
            task_id,
            source_root=source_root,
            branch_ref=branch_ref,
        )
        attempt = self.operator.execute(
            task_id,
            source_root=source_root,
            attempt_root=attempt_root,
            branch_ref=branch_ref,
            replacements=candidate.replacements,
        )
        review = self.review_attempt(
            task_id,
            candidate=candidate,
            source_root=source_root,
            attempt_root=attempt_root,
            attempt=attempt,
        )
        return {
            "task_id": str(task_id),
            "candidate_key": candidate.candidate_key,
            "branch_ref": branch_ref,
            "changed_paths": list(attempt.get("changed_paths") or []),
            "regression_passed": bool(attempt.get("regression_passed")),
            "attempt_key": attempt.get("attempt_key"),
            "semantic_review": review,
            "investigation": self.ledger.get(str(task_id)),
        }

    def review_attempt(
        self,
        task_id: str,
        *,
        candidate: MaintenanceRepairCandidate,
        source_root: str | Path,
        attempt_root: str | Path,
        attempt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if str(attempt.get("attempt_key") or "").strip() == "":
            raise ValueError("maintenance semantic review requires an attempt key")
        if not bool(attempt.get("regression_passed")):
            return {
                "reviewed": False,
                "decision": "unreviewed",
                "reason_code": "regression_failed",
            }

        task, evidence, source = self._trusted_context(task_id, source_root)
        if candidate.baseline_head != str(evidence["head"]):
            raise RuntimeError("maintenance candidate baseline is stale before review")
        isolated = Path(attempt_root).expanduser().resolve(strict=True)
        expected_parent = (source.parent / ".zn-maintenance-worktrees").resolve(strict=False)
        if isolated.parent != expected_parent:
            raise ValueError("maintenance semantic review requires the dedicated worktree")

        diff = self._bounded_diff(source, isolated, sorted(candidate.replacements))
        review_question = (
            "Review whether this isolated ZN repair actually addresses the stated defect without "
            "introducing an obvious semantic regression. The regression oracle already passed. "
            "Return strict JSON only with shape "
            '{"decision":"accept"|"reject","reason_code":"lower_snake_case","rationale":"short reason"}. '
            "Passing tests alone is not sufficient reason to accept."
        )
        review_context = json.dumps(
            {
                "role": "ZN maintenance semantic reviewer",
                "task": self._task_context(task),
                "baseline_head": evidence["head"],
                "regression_oracle": evidence["regression_oracle"],
                "candidate_rationale": candidate.rationale,
                "changed_paths": sorted(candidate.replacements),
                "diff": diff,
                "oracle_passed": True,
                "constraints": {"no_tools": True, "no_git": True, "no_shell": True},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        review_text, review_meta = self._invoke(
            question=review_question,
            context=review_context,
            excluded_routes=frozenset({candidate.author_route_id}) if candidate.author_route_id else frozenset(),
            allow_excluded_fallback=True,
        )
        parsed = self._json_object(review_text)
        decision = str(parsed.get("decision") or "").strip().lower()
        if decision not in {"accept", "reject"}:
            raise ValueError("maintenance semantic review decision must be accept or reject")
        reason_code = str(parsed.get("reason_code") or "semantic_review").strip().lower()
        if not _REASON_RE.fullmatch(reason_code):
            raise ValueError("maintenance semantic review reason_code is invalid")
        rationale = str(parsed.get("rationale") or "").strip()[:2000]
        route_id = str(review_meta.get("route_id") or "")
        independent_route = bool(
            candidate.author_route_id and route_id and route_id != candidate.author_route_id
        )

        if decision == "accept":
            investigation = self.ledger.accept(
                str(task_id), attempt_key=str(attempt["attempt_key"])
            )
        else:
            investigation = self.ledger.reject(
                str(task_id), reason=f"semantic_{reason_code}"[:128]
            )
        self._record_review(
            task_id=str(task_id),
            attempt_key=str(attempt["attempt_key"]),
            candidate_key=candidate.candidate_key,
            decision=decision,
            reason_code=reason_code,
            rationale=rationale,
            route_id=route_id,
            provider=str(review_meta.get("provider") or ""),
            model=str(review_meta.get("model") or ""),
            independent_route=independent_route,
        )
        return {
            "reviewed": True,
            "decision": decision,
            "reason_code": reason_code,
            "independent_route": independent_route,
            "route_id": route_id,
            "investigation": investigation,
        }

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            candidates = conn.execute(
                "SELECT task_id,candidate_key,baseline_head,branch_ref,path_count,path_fingerprint,"
                "rationale_fingerprint,route_id,provider,model,created_at FROM "
                "resident_maintenance_candidates ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            reviews = conn.execute(
                "SELECT task_id,attempt_key,candidate_key,decision,reason_code,rationale_fingerprint,"
                "route_id,provider,model,independent_route,created_at FROM "
                "resident_maintenance_semantic_reviews ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return {
            "candidate_count": len(candidates),
            "review_count": len(reviews),
            "candidates": [dict(row) for row in candidates],
            "reviews": [
                {**dict(row), "independent_route": bool(row["independent_route"])}
                for row in reviews
            ],
        }

    def _trusted_context(self, task_id: str, source_root: str | Path):
        task = self.ledger.get(str(task_id))
        if task is None:
            raise ValueError("maintenance investigation does not exist")
        if str(task.get("source_task_status") or "") != "open":
            raise RuntimeError("closed maintenance task cannot author a repair candidate")
        if str(task.get("failure_class") or "") != "probable_zn_defect":
            raise RuntimeError("maintenance candidate requires a high-confidence ZN defect")
        if str(task.get("status") or "") != "investigating":
            raise RuntimeError("maintenance source investigation must begin before candidate authoring")
        evidence = self._source_evidence(str(task_id))
        if evidence is None or str(evidence["authority"] or "") != "read_only":
            raise RuntimeError("trusted maintenance source evidence is unavailable")
        if bool(evidence["dirty"]):
            raise RuntimeError("maintenance candidate requires a clean observed source baseline")
        source = Path(source_root).expanduser().resolve(strict=True)
        self._verify_live_source(source, str(evidence["head"]), str(evidence["root_fingerprint"]))
        if str(task.get("baseline_ref") or "") != f"commit:{evidence['head']}":
            raise RuntimeError("maintenance candidate baseline contract is stale")
        if str(task.get("regression_oracle") or "") != str(evidence["regression_oracle"]):
            raise RuntimeError("maintenance candidate oracle contract is stale")
        return task, evidence, source

    def _verify_live_source(self, source: Path, expected_head: str, expected_root_fingerprint: str) -> None:
        def git(*parts: str):
            return subprocess.run(
                ["git", "-C", str(source), *parts],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        top = git("rev-parse", "--show-toplevel")
        head = git("rev-parse", "--verify", "HEAD")
        status = git("status", "--porcelain=v1", "-z")
        if any(proc.returncode != 0 for proc in (top, head, status)):
            raise RuntimeError("maintenance candidate source verification failed")
        if Path(top.stdout.strip()).expanduser().resolve(strict=True) != source:
            raise RuntimeError("maintenance candidate source must remain repository root")
        if head.stdout.strip() != expected_head:
            raise RuntimeError("maintenance candidate source HEAD drifted")
        if status.stdout:
            raise RuntimeError("maintenance candidate source became dirty")
        if self._fingerprint("zn-maintenance-root-v1", str(source)) != expected_root_fingerprint:
            raise RuntimeError("maintenance candidate source root changed")

    def _source_catalog(self, source: Path) -> list[str]:
        paths: list[str] = []
        for prefix in _ALLOWED_PREFIXES:
            root = source / prefix.as_posix()
            if not root.is_dir():
                continue
            for candidate in root.rglob("*.py"):
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                relative = candidate.relative_to(source).as_posix()
                paths.append(relative)
                if len(paths) >= _MAX_CATALOG_PATHS:
                    return sorted(paths)
        return sorted(paths)

    def _read_sources(self, source: Path, paths: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        total = 0
        for relative in paths:
            target = (source / relative).resolve(strict=True)
            try:
                target.relative_to(source)
            except ValueError as exc:
                raise ValueError("maintenance candidate source path escapes repository") from exc
            if target.is_symlink() or not target.is_file():
                raise ValueError("maintenance candidate may read only regular source files")
            raw = target.read_bytes()
            if len(raw) > _MAX_SOURCE_FILE_BYTES:
                raise ValueError("maintenance candidate source file exceeds cognition bound")
            total += len(raw)
            if total > _MAX_SOURCE_BYTES:
                raise ValueError("maintenance candidate source context exceeds cognition bound")
            result[relative] = raw.decode("utf-8")
        return result

    @staticmethod
    def _selected_paths(raw: Any, catalog: list[str]) -> list[str]:
        if not isinstance(raw, list):
            raise ValueError("maintenance target selection must contain a paths list")
        if not 1 <= len(raw) <= _MAX_TARGETS:
            raise ValueError("maintenance target selection exceeds path bound")
        allowed = set(catalog)
        normalized: list[str] = []
        for item in raw:
            path = str(item or "").strip().replace("\\", "/")
            if path not in allowed:
                raise ValueError("maintenance target selection named a path outside the catalog")
            if path not in normalized:
                normalized.append(path)
        if not normalized:
            raise ValueError("maintenance target selection is empty")
        return normalized

    @staticmethod
    def _replacement_contract(
        source: Path,
        raw: Any,
        *,
        allowed_paths: set[str],
    ) -> dict[str, str]:
        if not isinstance(raw, dict) or not raw:
            raise ValueError("maintenance repair author must return replacements")
        if len(raw) > _MAX_TARGETS:
            raise ValueError("maintenance repair author exceeded replacement bound")
        replacements: dict[str, str] = {}
        for raw_path, raw_content in raw.items():
            path = str(raw_path or "").strip().replace("\\", "/")
            if path not in allowed_paths:
                raise ValueError("maintenance repair author changed an unselected path")
            candidate = PurePosixPath(path)
            if candidate.suffix != ".py" or not any(
                candidate == prefix or prefix in candidate.parents for prefix in _ALLOWED_PREFIXES
            ):
                raise ValueError("maintenance repair author path is outside core repair boundary")
            target = (source / path).resolve(strict=True)
            if target.is_symlink() or not target.is_file():
                raise ValueError("maintenance repair author target is not a regular file")
            content = str(raw_content)
            if len(content.encode("utf-8")) > _MAX_REPLACEMENT_FILE_BYTES:
                raise ValueError("maintenance repair author content exceeds bound")
            if content == target.read_text(encoding="utf-8"):
                continue
            replacements[path] = content
        if not replacements:
            raise ValueError("maintenance repair author produced no source change")
        return replacements

    def _bounded_diff(self, source: Path, isolated: Path, paths: list[str]) -> str:
        parts: list[str] = []
        used = 0
        for path in paths:
            before = (source / path).read_text(encoding="utf-8").splitlines(keepends=True)
            after = (isolated / path).read_text(encoding="utf-8").splitlines(keepends=True)
            chunk = "".join(
                unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", n=3)
            )
            raw = chunk.encode("utf-8")
            if used + len(raw) > _MAX_DIFF_BYTES:
                remaining = max(0, _MAX_DIFF_BYTES - used)
                parts.append(raw[:remaining].decode("utf-8", errors="ignore"))
                parts.append("\n[diff truncated]\n")
                break
            parts.append(chunk)
            used += len(raw)
        return "".join(parts)

    def _invoke(
        self,
        *,
        question: str,
        context: str,
        excluded_routes: frozenset[str],
        allow_excluded_fallback: bool = False,
    ) -> tuple[str, dict[str, str]]:
        goal = Goal(
            goal_id="maintenance-ephemeral",
            task=str(question),
            required_capabilities=("general",),
            metadata={"maintenance_cognition": True},
        )
        with self.kernel._resource_lock:
            router = self.kernel.router
            factory = self.kernel.worker_factory
        try:
            route = router.select(goal, excluded=set(excluded_routes))
        except NoRouteAvailable:
            if not allow_excluded_fallback or not excluded_routes:
                raise RuntimeError("maintenance cognition has no available model route")
            route = router.select(goal, excluded=set())
        worker = factory.create(route)
        result = worker.run(goal, context)
        if not result.success:
            raise RuntimeError("maintenance cognition resource failed")
        text = str(result.response or "").strip()
        if not text:
            raise RuntimeError("maintenance cognition returned empty response")
        if len(text.encode("utf-8")) > _MAX_MODEL_RESPONSE_BYTES:
            raise RuntimeError("maintenance cognition response exceeds bound")
        return text, {
            "route_id": str(route.route_id),
            "provider": str(route.provider),
            "model": str(route.model),
        }

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raise ValueError("maintenance cognition must return bare JSON")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("maintenance cognition returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("maintenance cognition JSON must be an object")
        return value

    @staticmethod
    def _task_context(task: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "task_id": str(task.get("task_id") or ""),
            "organ": str(task.get("organ") or ""),
            "task_fingerprint": str(task.get("task_fingerprint") or ""),
            "failure_class": str(task.get("failure_class") or ""),
            "exception_type": str(task.get("exception_type") or ""),
            "observed_occurrences": int(task.get("observed_occurrences") or 0),
        }

    def _source_evidence(self, task_id: str) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT task_id,repository,root_fingerprint,branch,head,dirty,changed_files,"
                "changed_fingerprint,regression_oracle,oracle_available,authority,observed_at "
                "FROM resident_maintenance_source_evidence WHERE task_id=?",
                (task_id,),
            ).fetchone()

    def _record_candidate(
        self,
        *,
        task_id: str,
        candidate_key: str,
        baseline_head: str,
        branch_ref: str,
        paths: list[str],
        rationale: str,
        route_id: str,
        provider: str,
        model: str,
    ) -> None:
        from .models import utc_now

        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resident_maintenance_candidates("
                "task_id,candidate_key,baseline_head,branch_ref,path_count,path_fingerprint,"
                "rationale_fingerprint,route_id,provider,model,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    candidate_key,
                    baseline_head,
                    branch_ref,
                    len(paths),
                    self._fingerprint("zn-maintenance-candidate-paths-v1", "\n".join(paths)),
                    self._fingerprint("zn-maintenance-candidate-rationale-v1", rationale),
                    route_id,
                    provider,
                    model,
                    utc_now(),
                ),
            )
            conn.commit()

    def _record_review(
        self,
        *,
        task_id: str,
        attempt_key: str,
        candidate_key: str,
        decision: str,
        reason_code: str,
        rationale: str,
        route_id: str,
        provider: str,
        model: str,
        independent_route: bool,
    ) -> None:
        from .models import utc_now

        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resident_maintenance_semantic_reviews("
                "task_id,attempt_key,candidate_key,decision,reason_code,rationale_fingerprint,"
                "route_id,provider,model,independent_route,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    attempt_key,
                    candidate_key,
                    decision,
                    reason_code,
                    self._fingerprint("zn-maintenance-review-rationale-v1", rationale),
                    route_id,
                    provider,
                    model,
                    1 if independent_route else 0,
                    utc_now(),
                ),
            )
            conn.commit()

    @staticmethod
    def _fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(value).encode("utf-8", errors="replace"))
        return digest.hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_candidates ("
                "task_id TEXT NOT NULL,candidate_key TEXT NOT NULL,baseline_head TEXT NOT NULL,"
                "branch_ref TEXT NOT NULL,path_count INTEGER NOT NULL,path_fingerprint TEXT NOT NULL,"
                "rationale_fingerprint TEXT NOT NULL,route_id TEXT NOT NULL,provider TEXT NOT NULL,"
                "model TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(task_id,candidate_key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_semantic_reviews ("
                "task_id TEXT NOT NULL,attempt_key TEXT NOT NULL,candidate_key TEXT NOT NULL,"
                "decision TEXT NOT NULL,reason_code TEXT NOT NULL,rationale_fingerprint TEXT NOT NULL,"
                "route_id TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,"
                "independent_route INTEGER NOT NULL,created_at TEXT NOT NULL,"
                "PRIMARY KEY(task_id,attempt_key))"
            )
            conn.commit()

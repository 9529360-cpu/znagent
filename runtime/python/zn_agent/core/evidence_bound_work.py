from __future__ import annotations

"""Evidence-bound completion and delegated WorkerRun truth for steerable Work.

A Resident event can finish successfully while the WorkItem it serves still has
unmet acceptance criteria. This layer preserves the event/result as evidence but
prevents executor/model success from becoming Work acceptance by itself.

A Work-owned WorkerRun ledger records disposable execution attempts. WorkerRun is a disposable
execution attempt bound to an existing WorkItem and plan version; it is not a
Resident, Agent identity, scheduler, provider Worker, model route, or second
store. Provider dispatch durability remains owned by ZNKernelRuntime.
"""

import json
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

from .models import ResidentRunResult, utc_now
from .steerable_work import SteerableWorkLedger, WorkItem


@dataclass(slots=True)
class WorkerRun:
    worker_run_id: str
    work_item_id: str
    plan_version: int
    executor_kind: str
    model_goal_id: str
    model_route_id: str | None
    provider: str | None
    tool_scope: tuple[str, ...]
    authority_scope: tuple[str, ...]
    state: str
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: str | None = None
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    claimed_completion: bool = False
    verification_status: str = "pending"
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def cognition_request_id(self) -> str:
        return f"cog-{self.worker_run_id}"


@dataclass(slots=True, frozen=True)
class DependencyReadiness:
    """Derived readiness for one WorkItem; never persisted as a second truth."""

    ready: bool
    state: str
    dependency_ids: tuple[str, ...]
    waiting_on: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(slots=True)
class WorkerContextPack:
    root_goal_summary: str
    work_item_objective: str
    acceptance_criteria: tuple[str, ...]
    plan_version: int
    relevant_evidence: tuple[dict[str, Any], ...]
    artifact_refs: tuple[dict[str, Any], ...]
    tool_scope: tuple[str, ...]
    authority_scope: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    expected_result_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_goal_summary": self.root_goal_summary[:2000],
            "work_item_objective": self.work_item_objective[:1200],
            "acceptance_criteria": [str(value)[:600] for value in self.acceptance_criteria[:8]],
            "plan_version": int(self.plan_version),
            "relevant_evidence": [dict(item) for item in self.relevant_evidence[:8]],
            "artifact_refs": [dict(item) for item in self.artifact_refs[:12]],
            "tool_scope": list(self.tool_scope),
            "authority_scope": list(self.authority_scope),
            "forbidden_actions": list(self.forbidden_actions),
            "expected_result_schema": dict(self.expected_result_schema),
        }


class EvidenceBoundSteerableWorkLedger(SteerableWorkLedger):
    """Keep Root acceptance and delegated WorkerRun lifecycle in Work truth."""

    _UNVERIFIED_BLOCKER = (
        "resident event succeeded, but this WorkItem has acceptance criteria that "
        "still require independent current-world evidence"
    )
    _ACCEPTANCE_KEY = "zn_independent_acceptance"
    _WORKER_STATES = frozenset({"queued", "running", "completed", "failed", "stale"})
    _WORKER_TERMINAL_STATES = frozenset({"completed", "failed", "stale"})
    _MAX_DEPENDENCY_GRAPH_NODES = 256

    def __init__(self, resident):
        super().__init__(resident)
        self._init_worker_run_schema()
        self.reconcile_stale_worker_runs()

    def _init_worker_run_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS worker_runs(
                    worker_run_id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    executor_kind TEXT NOT NULL,
                    model_goal_id TEXT NOT NULL,
                    model_route_id TEXT,
                    provider TEXT,
                    tool_scope_json TEXT NOT NULL,
                    authority_scope_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_summary TEXT,
                    artifact_refs_json TEXT NOT NULL,
                    claimed_completion INTEGER NOT NULL DEFAULT 0,
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    metrics_json TEXT NOT NULL,
                    FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_worker_runs_item
                    ON worker_runs(work_item_id, started_at ASC);
                CREATE INDEX IF NOT EXISTS idx_worker_runs_plan_state
                    ON worker_runs(plan_version, state, started_at ASC);
                CREATE INDEX IF NOT EXISTS idx_worker_runs_model_goal
                    ON worker_runs(model_goal_id);
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(worker_runs)")
            }
            if "provider" not in columns:
                conn.execute("ALTER TABLE worker_runs ADD COLUMN provider TEXT")
            conn.commit()

    @staticmethod
    def _normalized_scope(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw or "").strip()
            if not value or len(value) > 200:
                raise ValueError("worker scope entries must be non-empty and bounded")
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            raise ValueError("worker scope must fail closed rather than be empty")
        return tuple(normalized)

    @staticmethod
    def _json_list(raw: str | None) -> list[Any]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
        return value if isinstance(value, list) else []

    @staticmethod
    def _json_dict(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _worker_from_row(cls, row) -> WorkerRun:
        tool_scope = tuple(str(value) for value in cls._json_list(row["tool_scope_json"]))
        authority_scope = tuple(
            str(value) for value in cls._json_list(row["authority_scope_json"])
        )
        artifact_refs = [
            dict(value)
            for value in cls._json_list(row["artifact_refs_json"])
            if isinstance(value, dict)
        ]
        return WorkerRun(
            worker_run_id=str(row["worker_run_id"]),
            work_item_id=str(row["work_item_id"]),
            plan_version=max(1, int(row["plan_version"])),
            executor_kind=str(row["executor_kind"]),
            model_goal_id=str(row["model_goal_id"]),
            model_route_id=(str(row["model_route_id"]) if row["model_route_id"] else None),
            provider=(str(row["provider"]) if row["provider"] else None),
            tool_scope=tool_scope,
            authority_scope=authority_scope,
            state=str(row["state"]),
            started_at=(str(row["started_at"]) if row["started_at"] else None),
            finished_at=(str(row["finished_at"]) if row["finished_at"] else None),
            result_summary=(
                str(row["result_summary"]) if row["result_summary"] is not None else None
            ),
            artifact_refs=artifact_refs,
            claimed_completion=bool(row["claimed_completion"]),
            verification_status=str(row["verification_status"] or "pending"),
            error=str(row["error"]) if row["error"] is not None else None,
            metrics=cls._json_dict(row["metrics_json"]),
        )

    def _work_item_by_id(self, work_item_id: str) -> WorkItem | None:
        normalized = str(work_item_id or "").strip()
        if not normalized:
            return None
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE work_item_id=?",
                (normalized,),
            ).fetchone()
        return self._item_from_row(row) if row is not None else None

    @staticmethod
    def _invalid_dependency_readiness(
        item: WorkItem,
        reason: str,
    ) -> DependencyReadiness:
        return DependencyReadiness(
            ready=False,
            state="invalid",
            dependency_ids=tuple(item.dependency_ids),
            reason=str(reason or "invalid durable dependency graph")[:1200],
        )

    def _validate_dependency_subgraph(
        self,
        item: WorkItem,
        *,
        root_work_item_id: str,
        work_thread_id: str,
        plan_version: int,
        visiting: set[str],
        visited: set[str],
    ) -> str | None:
        if item.work_item_id in visiting:
            return f"dependency cycle detected at {item.work_item_id}"
        if item.work_item_id in visited:
            return None
        if len(visited) + len(visiting) >= self._MAX_DEPENDENCY_GRAPH_NODES:
            return "dependency graph exceeds the bounded node limit"
        if (
            item.parent_work_item_id != root_work_item_id
            or item.work_thread_id != work_thread_id
            or item.plan_version != plan_version
        ):
            return f"dependency node {item.work_item_id} escaped the current Root/plan"

        visiting.add(item.work_item_id)
        direct: list[WorkItem] = []
        for dependency_id in item.dependency_ids:
            dependency = self._work_item_by_id(dependency_id)
            if dependency is None:
                visiting.remove(item.work_item_id)
                return f"dependency {dependency_id} is missing"
            if (
                dependency.parent_work_item_id != root_work_item_id
                or dependency.work_thread_id != work_thread_id
                or dependency.plan_version != plan_version
            ):
                visiting.remove(item.work_item_id)
                return f"dependency {dependency_id} belongs to another Root or plan"
            if dependency.status not in {"proposed", "ready", "running", "blocked", "completed"}:
                visiting.remove(item.work_item_id)
                return f"dependency {dependency_id} has invalid state {dependency.status!r}"
            direct.append(dependency)
            invalid = self._validate_dependency_subgraph(
                dependency,
                root_work_item_id=root_work_item_id,
                work_thread_id=work_thread_id,
                plan_version=plan_version,
                visiting=visiting,
                visited=visited,
            )
            if invalid is not None:
                visiting.remove(item.work_item_id)
                return invalid

        if item.status == "completed" and any(
            dependency.status != "completed" for dependency in direct
        ):
            visiting.remove(item.work_item_id)
            return f"completed dependency node {item.work_item_id} has unmet prerequisites"
        visiting.remove(item.work_item_id)
        visited.add(item.work_item_id)
        return None

    def dependency_readiness(self, work_item_id: str) -> DependencyReadiness:
        """Derive readiness only from current durable Work dependency/state truth."""

        normalized = str(work_item_id or "").strip()
        if not normalized or len(normalized) > self._MAX_WORK_ITEM_ID_LENGTH:
            raise ValueError("dependency readiness requires a bounded WorkItem ID")
        item = self._work_item_by_id(normalized)
        if item is None:
            raise ValueError("dependency readiness requires an existing WorkItem")
        current_version = self.plan_version(item.work_thread_id)
        if item.plan_version != current_version:
            return self._invalid_dependency_readiness(
                item,
                "WorkItem belongs to a stale Work plan",
            )
        if (
            item.parent_work_item_id is not None
            and item.status not in {"proposed", "ready", "running", "blocked", "completed"}
        ):
            return self._invalid_dependency_readiness(
                item,
                f"WorkItem has invalid dependency state {item.status!r}",
            )
        if item.parent_work_item_id is None:
            if item.dependency_ids:
                return self._invalid_dependency_readiness(
                    item,
                    "Root WorkItem must not carry dependency edges",
                )
            return DependencyReadiness(
                ready=True,
                state="ready",
                dependency_ids=(),
            )

        root = self._work_item_by_id(item.parent_work_item_id)
        if (
            root is None
            or root.parent_work_item_id is not None
            or root.work_thread_id != item.work_thread_id
            or root.plan_version != current_version
        ):
            return self._invalid_dependency_readiness(
                item,
                "WorkItem is not bound to the current Root",
            )
        if root.dependency_ids:
            return self._invalid_dependency_readiness(
                item,
                "Root WorkItem carries invalid dependency edges",
            )

        invalid = self._validate_dependency_subgraph(
            item,
            root_work_item_id=root.work_item_id,
            work_thread_id=item.work_thread_id,
            plan_version=current_version,
            visiting=set(),
            visited=set(),
        )
        if invalid is not None:
            return self._invalid_dependency_readiness(item, invalid)

        if not item.dependency_ids:
            return DependencyReadiness(
                ready=True,
                state="ready",
                dependency_ids=(),
            )
        direct = [self._work_item_by_id(value) for value in item.dependency_ids]
        if any(dependency is None for dependency in direct):
            return self._invalid_dependency_readiness(
                item,
                "dependency disappeared during readiness check",
            )
        if any(
            dependency is not None
            and (
                dependency.parent_work_item_id != root.work_item_id
                or dependency.work_thread_id != item.work_thread_id
                or dependency.plan_version != current_version
                or dependency.status
                not in {"proposed", "ready", "running", "blocked", "completed"}
            )
            for dependency in direct
        ):
            return self._invalid_dependency_readiness(
                item,
                "dependency changed to an invalid Root/plan/state during readiness check",
            )
        waiting_on = tuple(
            dependency.work_item_id
            for dependency in direct
            if dependency is not None and dependency.status != "completed"
        )
        if waiting_on:
            return DependencyReadiness(
                ready=False,
                state="waiting",
                dependency_ids=tuple(item.dependency_ids),
                waiting_on=waiting_on,
                reason="required WorkItem dependencies are not Work-owned completed",
            )
        return DependencyReadiness(
            ready=True,
            state="ready",
            dependency_ids=tuple(item.dependency_ids),
        )

    def assert_dependencies_ready(self, work_item_id: str) -> DependencyReadiness:
        readiness = self.dependency_readiness(work_item_id)
        if readiness.ready:
            return readiness
        waiting = ",".join(readiness.waiting_on[:8])
        detail = str(readiness.reason or readiness.state)[:800]
        if waiting:
            detail = f"{detail}; waiting_on={waiting}"
        raise ValueError(
            f"WorkItem dependency readiness rejected {readiness.state}: {detail}"
        )

    def create_child_item(
        self,
        *,
        root_work_item_id: str,
        objective: str,
        acceptance_criteria: list[str],
        title: str | None = None,
        dependency_ids: tuple[str, ...] | list[str] = (),
    ) -> WorkItem:
        """Create one flat current-plan child with resident-owned identity/version."""
        root = self._work_item_by_id(root_work_item_id)
        if root is None or root.parent_work_item_id is not None:
            raise ValueError("delegated child requires an existing Root WorkItem")
        current_version = self.plan_version(root.work_thread_id)
        if root.plan_version != current_version or root.status not in {"running", "blocked"}:
            raise ValueError("delegated child rejected stale or terminal Root Work")
        if root.dependency_ids:
            raise ValueError("delegated child rejected Root Work with invalid dependency edges")
        dependencies = self._normalize_dependency_ids(dependency_ids)
        for dependency_id in dependencies:
            dependency = self._work_item_by_id(dependency_id)
            if dependency is None:
                raise ValueError(f"delegated child dependency does not exist: {dependency_id}")
            if (
                dependency.parent_work_item_id != root.work_item_id
                or dependency.work_thread_id != root.work_thread_id
                or dependency.plan_version != current_version
            ):
                raise ValueError(
                    "delegated child dependency must be a current-plan sibling under the same Root"
                )
            readiness = self.dependency_readiness(dependency_id)
            if readiness.state == "invalid":
                raise ValueError(
                    f"delegated child dependency graph is invalid: {readiness.reason}"
                )
        normalized_objective = " ".join(str(objective or "").strip().split())
        if not normalized_objective or len(normalized_objective) > 1200:
            raise ValueError("delegated child objective must be non-empty and bounded")
        criteria = [" ".join(str(value).strip().split()) for value in acceptance_criteria]
        if not criteria or any(not value for value in criteria):
            raise ValueError("delegated child requires explicit acceptance criteria")
        now = utc_now()
        child = WorkItem(
            work_item_id=f"item-{uuid.uuid4().hex[:16]}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=(str(title or normalized_objective).strip()[:200] or "Delegated Work"),
            objective=normalized_objective,
            status="running",
            plan_version=current_version,
            acceptance_criteria=criteria,
            dependency_ids=dependencies,
            created_at=now,
            updated_at=now,
        )
        self._save_item(child)
        return child

    def complete_child_item(self, work_item_id: str, *, result: str) -> WorkItem:
        item = self._work_item_by_id(work_item_id)
        if item is None or item.parent_work_item_id is None:
            raise ValueError("child completion requires an existing non-Root WorkItem")
        current_version = self.plan_version(item.work_thread_id)
        if item.plan_version != current_version:
            raise ValueError("child completion rejected stale Work evidence")
        if item.status == "completed":
            self.assert_dependencies_ready(item.work_item_id)
            return item
        if item.status not in {"running", "blocked", "ready"}:
            raise ValueError(f"child completion rejected state {item.status!r}")
        self.assert_dependencies_ready(item.work_item_id)
        now = utc_now()
        item.status = "completed"
        item.result = str(result or "").strip()[:6000] or None
        item.blocker = None
        item.completed_at = now
        item.updated_at = now
        self._save_item(item)
        return item

    def block_child_item(self, work_item_id: str, *, blocker: str) -> WorkItem:
        item = self._work_item_by_id(work_item_id)
        if item is None or item.parent_work_item_id is None:
            raise ValueError("child blocking requires an existing non-Root WorkItem")
        current_version = self.plan_version(item.work_thread_id)
        if item.plan_version != current_version:
            item.status = "superseded"
            item.updated_at = utc_now()
            self._save_item(item)
            return item
        if item.status == "completed":
            return item
        failure = str(blocker or "delegated Work failed").strip()[:6000]
        item.status = "blocked"
        item.blocker = failure
        item.result = failure
        item.completed_at = None
        item.updated_at = utc_now()
        self._save_item(item)
        return item

    def start_worker_run(
        self,
        *,
        work_item_id: str,
        executor_kind: str,
        tool_scope: tuple[str, ...] | list[str],
        authority_scope: tuple[str, ...] | list[str],
    ) -> WorkerRun:
        """Start one Work-owned disposable execution attempt.

        Caller/model cannot supply worker_run_id, plan_version or model_goal_id.
        The stable model goal is derived from the resident-owned worker_run_id so
        Kernel provider dispatch can keep its existing at-most-once semantics.
        """
        item = self._work_item_by_id(work_item_id)
        if item is None or item.parent_work_item_id is None:
            raise ValueError("WorkerRun requires an existing child WorkItem")
        current_version = self.plan_version(item.work_thread_id)
        if item.plan_version != current_version or item.status not in {"running", "ready"}:
            raise ValueError("WorkerRun rejected stale or non-runnable WorkItem")
        root = self._work_item_by_id(item.parent_work_item_id)
        if (
            root is None
            or root.parent_work_item_id is not None
            or root.work_thread_id != item.work_thread_id
            or root.plan_version != current_version
        ):
            raise ValueError("WorkerRun WorkItem is not bound to the current Root")
        self.assert_dependencies_ready(item.work_item_id)
        kind = str(executor_kind or "").strip().lower()
        if not kind:
            raise ValueError("WorkerRun executor_kind must not be empty")
        tools = self._normalized_scope(tool_scope)
        authority = self._normalized_scope(authority_scope)
        worker_run_id = f"worker-{uuid.uuid4().hex[:16]}"
        model_goal_id = f"goal-cog-{worker_run_id}"
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO worker_runs(
                    worker_run_id,work_item_id,plan_version,executor_kind,model_goal_id,
                    model_route_id,provider,tool_scope_json,authority_scope_json,state,started_at,
                    finished_at,result_summary,artifact_refs_json,claimed_completion,
                    verification_status,error,metrics_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    worker_run_id,
                    item.work_item_id,
                    current_version,
                    kind,
                    model_goal_id,
                    None,
                    None,
                    json.dumps(tools, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(authority, ensure_ascii=False, separators=(",", ":")),
                    "running",
                    now,
                    None,
                    None,
                    "[]",
                    0,
                    "pending",
                    None,
                    "{}",
                ),
            )
            conn.commit()
        run = self.worker_run(worker_run_id)
        if run is None:
            raise RuntimeError("WorkerRun creation did not persist")
        return run

    def worker_run(self, worker_run_id: str) -> WorkerRun | None:
        normalized = str(worker_run_id or "").strip()
        if not normalized:
            return None
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM worker_runs WHERE worker_run_id=?",
                (normalized,),
            ).fetchone()
        return self._worker_from_row(row) if row is not None else None

    def update_worker_run_metrics(
        self,
        worker_run_id: str,
        *,
        metrics: dict[str, Any],
    ) -> WorkerRun:
        """Persist bounded execution identity while a WorkerRun is still live.

        This is intentionally narrower than a generic WorkerRun update. Callers
        may checkpoint executor-owned recovery identity (for example an external
        Mission id) but cannot change state, scopes, WorkItem binding, provider,
        or plan version through this path.
        """

        run = self.worker_run(worker_run_id)
        if run is None:
            raise ValueError("unknown WorkerRun")
        if run.state not in {"queued", "running"}:
            raise ValueError("WorkerRun metrics may only change while queued or running")
        item = self._work_item_by_id(run.work_item_id)
        if item is None or item.plan_version != run.plan_version:
            raise RuntimeError("WorkerRun lost its immutable WorkItem binding")
        if self.plan_version(item.work_thread_id) != run.plan_version:
            self.mark_worker_stale(
                worker_run_id,
                reason="WorkerRun recovery identity belongs to a stale plan",
            )
            refreshed = self.worker_run(worker_run_id)
            assert refreshed is not None
            return refreshed
        metric_values = dict(run.metrics)
        metric_values.update(dict(metrics or {}))
        with self._lock, closing(self._connect()) as conn:
            updated = conn.execute(
                "UPDATE worker_runs SET metrics_json=? "
                "WHERE worker_run_id=? AND state IN ('queued','running')",
                (
                    json.dumps(
                        metric_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    run.worker_run_id,
                ),
            )
            conn.commit()
        if updated.rowcount != 1:
            raise RuntimeError("WorkerRun metrics update lost a concurrent state change")
        persisted = self.worker_run(run.worker_run_id)
        if persisted is None:
            raise RuntimeError("WorkerRun metrics update did not persist")
        return persisted

    def list_worker_runs(
        self,
        *,
        thread_id: str | None = None,
        work_item_id: str | None = None,
        limit: int = 256,
    ) -> list[WorkerRun]:
        clauses: list[str] = []
        params: list[Any] = []
        join = ""
        if thread_id is not None:
            join = " JOIN work_items ON work_items.work_item_id=worker_runs.work_item_id"
            clauses.append("work_items.work_thread_id=?")
            params.append(self._normalize_thread_id(thread_id))
        if work_item_id is not None:
            clauses.append("worker_runs.work_item_id=?")
            params.append(str(work_item_id or "").strip())
        sql = "SELECT worker_runs.* FROM worker_runs" + join
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY worker_runs.started_at ASC LIMIT ?"
        params.append(max(1, min(1024, int(limit))))
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def _provider_for_worker_route(self, run: WorkerRun, route_id: str | None) -> str | None:
        """Resolve provider only from Kernel's durable final route snapshot.

        WorkerRun owns the audit copy, while Kernel remains the provider-dispatch
        truth. Synthetic ledger tests and pre-dispatch/stale runs can legitimately
        have no completed Kernel goal yet; real provider-dispatched terminal runs
        resolve and persist the provider here without guessing from route names.
        """

        if route_id is None:
            return None
        kernel = getattr(self.resident, "kernel", None)
        load = getattr(kernel, "load_goal_result", None)
        if not callable(load):
            return None
        result = load(run.model_goal_id)
        if result is None:
            return None
        durable_route_id = str(result.route.route_id or "").strip()
        if durable_route_id and durable_route_id != route_id:
            raise RuntimeError("WorkerRun model route disagrees with Kernel durable route trace")
        provider = str(result.route.provider or "").strip()
        return provider or None

    def _finish_worker_run(
        self,
        worker_run_id: str,
        *,
        state: str,
        result_summary: str | None,
        artifact_refs: list[dict[str, Any]] | None,
        claimed_completion: bool,
        verification_status: str,
        error: str | None,
        model_route_id: str | None,
        metrics: dict[str, Any] | None,
    ) -> WorkerRun:
        if state not in self._WORKER_TERMINAL_STATES:
            raise ValueError("WorkerRun finish state must be terminal")
        run = self.worker_run(worker_run_id)
        if run is None:
            raise ValueError("unknown WorkerRun")
        item = self._work_item_by_id(run.work_item_id)
        if item is None or item.plan_version != run.plan_version:
            raise RuntimeError("WorkerRun lost its immutable WorkItem binding")
        current_version = self.plan_version(item.work_thread_id)
        final_state = state if run.plan_version == current_version else "stale"
        if run.state in self._WORKER_TERMINAL_STATES:
            if run.state == "stale" or run.state == final_state:
                return run
            if final_state == "stale":
                self.mark_worker_stale(worker_run_id, reason="WorkerRun result belongs to a stale plan")
                refreshed = self.worker_run(worker_run_id)
                assert refreshed is not None
                return refreshed
            raise ValueError(f"WorkerRun transition {run.state!r} -> {final_state!r} is not allowed")
        if run.state not in {"queued", "running"}:
            raise ValueError(f"WorkerRun has invalid state {run.state!r}")
        route_id = str(model_route_id or "").strip() or None
        provider = self._provider_for_worker_route(run, route_id)
        refs = [dict(value) for value in (artifact_refs or []) if isinstance(value, dict)][:32]
        metric_values = dict(metrics or {})
        now = utc_now()
        status = str(verification_status or "pending").strip()[:120] or "pending"
        if final_state == "stale":
            status = "stale_plan"
        with self._lock, closing(self._connect()) as conn:
            updated = conn.execute(
                """
                UPDATE worker_runs SET
                    model_route_id=?,provider=?,state=?,finished_at=?,result_summary=?,artifact_refs_json=?,
                    claimed_completion=?,verification_status=?,error=?,metrics_json=?
                WHERE worker_run_id=? AND state IN ('queued','running')
                """,
                (
                    route_id,
                    provider,
                    final_state,
                    now,
                    str(result_summary or "").strip()[:12000] or None,
                    json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
                    1 if claimed_completion else 0,
                    status,
                    str(error or "").strip()[:6000] or None,
                    json.dumps(metric_values, ensure_ascii=False, separators=(",", ":")),
                    run.worker_run_id,
                ),
            )
            conn.commit()
        if updated.rowcount != 1:
            raise RuntimeError("WorkerRun transition lost a concurrent state change")
        persisted = self.worker_run(run.worker_run_id)
        if persisted is None:
            raise RuntimeError("WorkerRun transition did not persist")
        return persisted

    def complete_worker_run(
        self,
        worker_run_id: str,
        *,
        result_summary: str,
        artifact_refs: list[dict[str, Any]] | None = None,
        claimed_completion: bool = False,
        verification_status: str = "scope_admitted",
        model_route_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> WorkerRun:
        return self._finish_worker_run(
            worker_run_id,
            state="completed",
            result_summary=result_summary,
            artifact_refs=artifact_refs,
            claimed_completion=claimed_completion,
            verification_status=verification_status,
            error=None,
            model_route_id=model_route_id,
            metrics=metrics,
        )

    def fail_worker_run(
        self,
        worker_run_id: str,
        *,
        error: str,
        result_summary: str | None = None,
        claimed_completion: bool = False,
        verification_status: str = "failed",
        model_route_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> WorkerRun:
        return self._finish_worker_run(
            worker_run_id,
            state="failed",
            result_summary=result_summary,
            artifact_refs=None,
            claimed_completion=claimed_completion,
            verification_status=verification_status,
            error=error,
            model_route_id=model_route_id,
            metrics=metrics,
        )

    def mark_worker_stale(self, worker_run_id: str, *, reason: str) -> WorkerRun:
        run = self.worker_run(worker_run_id)
        if run is None:
            raise ValueError("unknown WorkerRun")
        if run.state == "stale":
            return run
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET state='stale',finished_at=COALESCE(finished_at,?),"
                "verification_status='stale_plan',error=COALESCE(error,?) WHERE worker_run_id=?",
                (now, str(reason or "stale plan")[:6000], run.worker_run_id),
            )
            conn.commit()
        persisted = self.worker_run(run.worker_run_id)
        if persisted is None:
            raise RuntimeError("stale WorkerRun transition did not persist")
        return persisted

    def record_worker_verification(
        self,
        worker_run_id: str,
        *,
        verification_status: str,
        artifact_refs: list[dict[str, Any]] | None = None,
    ) -> WorkerRun:
        run = self.worker_run(worker_run_id)
        if run is None:
            raise ValueError("unknown WorkerRun")
        if run.state == "stale":
            return run
        item = self._work_item_by_id(run.work_item_id)
        if item is None or item.plan_version != self.plan_version(item.work_thread_id):
            return self.mark_worker_stale(worker_run_id, reason="verification arrived for a stale plan")
        refs = run.artifact_refs
        if artifact_refs is not None:
            refs = [dict(value) for value in artifact_refs if isinstance(value, dict)][:32]
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE worker_runs SET verification_status=?,artifact_refs_json=? WHERE worker_run_id=?",
                (
                    str(verification_status or "pending").strip()[:120] or "pending",
                    json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
                    run.worker_run_id,
                ),
            )
            conn.commit()
        persisted = self.worker_run(run.worker_run_id)
        if persisted is None:
            raise RuntimeError("WorkerRun verification update did not persist")
        return persisted

    def reconcile_stale_worker_runs(self, *, thread_id: str | None = None) -> int:
        params: list[Any] = [utc_now()]
        thread_clause = ""
        if thread_id is not None:
            thread_clause = " AND work_items.work_thread_id=?"
            params.append(self._normalize_thread_id(thread_id))
        with self._lock, closing(self._connect()) as conn:
            updated = conn.execute(
                """
                UPDATE worker_runs SET
                    state='stale',
                    finished_at=COALESCE(finished_at,?),
                    verification_status='stale_plan',
                    error=COALESCE(error,'WorkerRun belongs to a superseded Work plan')
                WHERE worker_run_id IN (
                    SELECT worker_runs.worker_run_id
                    FROM worker_runs
                    JOIN work_items ON work_items.work_item_id=worker_runs.work_item_id
                    JOIN work_plan_state ON work_plan_state.thread_id=work_items.work_thread_id
                    WHERE worker_runs.plan_version < work_plan_state.plan_version
                      AND worker_runs.state IN ('queued','running','completed')
                """
                + thread_clause
                + ")",
                params,
            )
            conn.commit()
        return max(0, int(updated.rowcount))

    def steer_active(self, *args, **kwargs):
        result = super().steer_active(*args, **kwargs)
        thread_id = str(args[0] if args else kwargs.get("thread_id") or "").strip()
        self.reconcile_stale_worker_runs(thread_id=thread_id or None)
        return result

    def _finalize_run(self, event_id: str, *, run: ResidentRunResult) -> None:
        before = self.work_item_for_event(event_id)
        criteria_bound = bool(before is not None and before.acceptance_criteria)
        run_version = self._run_plan_version(event_id)
        work_run = self.get_run(event_id)
        current_version = (
            self.plan_version(work_run.thread_id) if work_run is not None else None
        )
        stale = bool(
            work_run is not None
            and (
                work_run.ledger_state == "stale"
                or (run_version is not None and run_version != current_version)
            )
        )

        super()._finalize_run(event_id, run=run)

        if not criteria_bound or not run.success or stale:
            return
        item = self.work_item_for_event(event_id)
        if item is None or item.status != "completed":
            return
        if self._accepted_by_current_evidence(item):
            return

        item.status = "blocked"
        item.blocker = self._UNVERIFIED_BLOCKER
        item.completed_at = None
        item.updated_at = utc_now()
        self._save_item(item)

    def initialize_root_acceptance(
        self,
        event_id: str,
        *,
        acceptance_criteria: list[str],
    ) -> WorkItem:
        """Define acceptance exactly once for one active criteria-less Root.

        Generic WorkItem saves deliberately keep acceptance criteria immutable.
        Broad-goal intake therefore uses this one narrow transition from the
        creation-time empty vector to a non-empty contract. The Work ledger owns
        the mutation and revalidates Root identity, active run, and current plan.
        """

        criteria = [str(item) for item in acceptance_criteria]
        if not criteria or any(not item.strip() for item in criteria):
            raise ValueError("autonomous Root acceptance requires non-empty criteria")

        root = self.work_item_for_event(event_id)
        run = self.get_run(event_id)
        if root is None or run is None:
            raise ValueError("autonomous Root acceptance requires a durable Work run")
        if root.parent_work_item_id is not None:
            raise ValueError("autonomous Root acceptance only applies to Root Work")
        current_version = self.plan_version(root.work_thread_id)
        if (
            run.ledger_state != "active"
            or run.thread_id != root.work_thread_id
            or root.plan_version != current_version
            or self._run_plan_version(event_id) != current_version
        ):
            raise ValueError("autonomous Root acceptance rejected stale Work")
        if root.acceptance_criteria:
            if list(root.acceptance_criteria) == criteria:
                return root
            raise ValueError("autonomous Root acceptance is immutable once defined")

        criteria_json = json.dumps(criteria, ensure_ascii=False, separators=(",", ":"))
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            updated = conn.execute(
                "UPDATE work_items SET acceptance_criteria_json=?,updated_at=? "
                "WHERE work_item_id=? AND work_thread_id=? AND plan_version=? "
                "AND parent_work_item_id IS NULL AND acceptance_criteria_json='[]'",
                (
                    criteria_json,
                    now,
                    root.work_item_id,
                    root.work_thread_id,
                    current_version,
                ),
            )
            conn.commit()
        if updated.rowcount not in {0, 1}:
            raise RuntimeError("autonomous Root acceptance changed an unexpected number of rows")

        persisted = self.work_item_for_event(event_id)
        if persisted is None or list(persisted.acceptance_criteria) != criteria:
            raise RuntimeError("autonomous Root acceptance did not persist the exact criteria")
        return persisted

    def recover_steered_root_acceptance(self, event) -> WorkItem | None:
        """Durably recover criteria for the exact next Root after same-Work steering.

        Generic WorkItem saves intentionally cannot mutate acceptance criteria.
        Steering currently creates its replacement Root with an empty criteria
        vector, so criterion-bound Broad Work needs one narrowly authorized
        transition. The transition is accepted only when durable steering metadata,
        current plan binding, active run identity, and the immediately superseded
        Root all agree. Re-running it after a crash is idempotent.
        """

        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        steering = payload.get("work_steering")
        if not isinstance(steering, dict) or str(steering.get("mode") or "") != "active_steer":
            return None

        root = self.work_item_for_event(event.event_id)
        run = self.get_run(event.event_id)
        if root is None or run is None or root.parent_work_item_id is not None:
            return None
        if root.acceptance_criteria:
            return root
        thread_id = str(payload.get("work_thread_id") or root.work_thread_id or "").strip()
        item_id = str(payload.get("work_item_id") or "").strip()
        if (
            not thread_id
            or item_id != root.work_item_id
            or run.thread_id != thread_id
            or run.ledger_state != "active"
        ):
            return None
        try:
            current_version = int(steering.get("plan_version"))
            previous_version = int(steering.get("previous_plan_version"))
        except (TypeError, ValueError):
            return None
        if (
            current_version != self.plan_version(thread_id)
            or root.plan_version != current_version
            or self._run_plan_version(event.event_id) != current_version
            or previous_version + 1 != current_version
        ):
            return None

        previous_event_id = str(steering.get("previous_event_id") or "").strip()
        previous = self.work_item_for_event(previous_event_id)
        previous_run = self.get_run(previous_event_id)
        if (
            previous is None
            or previous_run is None
            or previous.work_thread_id != thread_id
            or previous.parent_work_item_id is not None
            or previous.plan_version != previous_version
            or previous_run.thread_id != thread_id
            or not previous.acceptance_criteria
        ):
            return None

        criteria_json = json.dumps(
            list(previous.acceptance_criteria),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            updated = conn.execute(
                "UPDATE work_items SET acceptance_criteria_json=?,updated_at=? "
                "WHERE work_item_id=? AND work_thread_id=? AND plan_version=? "
                "AND parent_work_item_id IS NULL AND acceptance_criteria_json='[]'",
                (
                    criteria_json,
                    now,
                    root.work_item_id,
                    thread_id,
                    current_version,
                ),
            )
            conn.commit()
        if updated.rowcount not in {0, 1}:
            raise RuntimeError("steered Root acceptance recovery changed an unexpected number of rows")

        recovered = self.work_item_for_event(event.event_id)
        if recovered is None or list(recovered.acceptance_criteria) != list(previous.acceptance_criteria):
            raise RuntimeError("steered Root acceptance recovery did not persist exact previous criteria")
        return recovered

    def accept_root_with_current_evidence(
        self,
        event_id: str,
        *,
        verifier_work_item_id: str,
        verification_summary: str,
    ) -> WorkItem:
        """Accept one Root only from a completed verifier in the active plan.

        Concrete verification remains Resident/Body work. This ledger only owns
        the final identity/version/evidence gate, so neither model prose nor one
        executor success bit can complete criterion-bound Root Work directly.
        """

        root = self.work_item_for_event(event_id)
        run = self.get_run(event_id)
        if root is None or run is None:
            raise ValueError("independent acceptance requires a durable Work run")
        if root.parent_work_item_id is not None or not root.acceptance_criteria:
            raise ValueError("independent acceptance only applies to criterion-bound Root Work")
        current_version = self.plan_version(root.work_thread_id)
        run_version = self._run_plan_version(event_id)
        if (
            run.ledger_state != "active"
            or root.plan_version != current_version
            or run_version != current_version
        ):
            raise ValueError("independent acceptance rejected stale Work evidence")

        children = [
            item
            for item in self.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == current_version
        ]
        verifier = next(
            (item for item in children if item.work_item_id == verifier_work_item_id),
            None,
        )
        if verifier is None or verifier.status != "completed":
            raise ValueError("independent acceptance verifier is not completed current-plan evidence")
        if not any(
            criterion.startswith("independent_python_verification:")
            for criterion in verifier.acceptance_criteria
        ):
            raise ValueError("independent acceptance requires a dedicated verification WorkItem")
        unresolved = [
            item
            for item in children
            if item.status in {"proposed", "ready", "running"}
            and item.work_item_id != verifier.work_item_id
        ]
        if unresolved:
            raise ValueError("independent acceptance rejected unresolved current-plan WorkItems")
        completed = [item for item in children if item.status == "completed"]
        if len(completed) < 2:
            raise ValueError("independent acceptance requires prior completed work plus fresh verification")

        now = utc_now()
        payload = {
            self._ACCEPTANCE_KEY: {
                "version": 1,
                "plan_version": current_version,
                "verifier_work_item_id": verifier.work_item_id,
                "completed_evidence_work_item_ids": [
                    item.work_item_id for item in completed[-32:]
                ],
                "verification_summary": str(verification_summary or "").strip()[:4000],
                "accepted_at": now,
            }
        }
        root.status = "completed"
        root.result = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        root.blocker = None
        root.completed_at = now
        root.updated_at = now
        self._save_item(root)
        return root

    def _accepted_by_current_evidence(self, item: WorkItem) -> bool:
        if item.status != "completed" or not item.result:
            return False
        try:
            raw = json.loads(item.result)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(raw, dict):
            return False
        acceptance = raw.get(self._ACCEPTANCE_KEY)
        if not isinstance(acceptance, dict) or acceptance.get("version") != 1:
            return False
        try:
            accepted_version = int(acceptance.get("plan_version"))
        except (TypeError, ValueError):
            return False
        if accepted_version != item.plan_version:
            return False
        if self.plan_version(item.work_thread_id) != item.plan_version:
            return False
        verifier_id = str(acceptance.get("verifier_work_item_id") or "").strip()
        evidence_ids = acceptance.get("completed_evidence_work_item_ids")
        if not verifier_id or not isinstance(evidence_ids, list) or verifier_id not in evidence_ids:
            return False
        children = {
            child.work_item_id: child
            for child in self.list_work_items(item.work_thread_id, limit=256)
            if child.parent_work_item_id == item.work_item_id
            and child.plan_version == item.plan_version
        }
        verifier = children.get(verifier_id)
        return bool(
            verifier is not None
            and verifier.status == "completed"
            and any(
                criterion.startswith("independent_python_verification:")
                for criterion in verifier.acceptance_criteria
            )
        )

    def progress(self, thread_id: str, event_id: str) -> dict[str, object]:
        progress = super().progress(thread_id, event_id)
        item = self.work_item_for_event(event_id)
        if item is not None and self._accepted_by_current_evidence(item):
            progress["accepted"] = True
            progress["acceptance_pending"] = False
            progress["acceptance_criteria"] = list(item.acceptance_criteria)
            return progress
        if (
            item is not None
            and item.status == "blocked"
            and item.acceptance_criteria
            and item.blocker == self._UNVERIFIED_BLOCKER
        ):
            progress["accepted"] = False
            progress["acceptance_pending"] = True
            progress["acceptance_criteria"] = list(item.acceptance_criteria)
            progress["acceptance_blocker"] = item.blocker
        return progress

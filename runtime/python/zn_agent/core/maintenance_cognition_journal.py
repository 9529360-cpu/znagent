from __future__ import annotations

"""Durable at-most-once dispatch accounting for maintenance cognition.

Maintenance cognition may transiently contain source text or repair diffs that must
not be copied into durable resident state. This orchestrator keeps those inputs in
memory while persisting only fingerprints and route metadata around the external
model dispatch. Once a call is reserved, the same logical call is never replayed
automatically after a crash or ambiguous provider outcome. Automatic semantic
acceptance additionally requires a model route independent from the repair author.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Any, Mapping

from .maintenance_cognitive import (
    MaintenanceCognitiveRepairOrchestrator,
    MaintenanceRepairCandidate,
)
from .models import Goal, utc_now
from .router import NoRouteAvailable


class DurableMaintenanceCognitiveRepairOrchestrator(MaintenanceCognitiveRepairOrchestrator):
    """Maintenance cognition with durable dispatch and independent acceptance."""

    def __init__(self, store, ledger, operator, kernel):
        super().__init__(store, ledger, operator, kernel)
        self._init_dispatch_schema()

    def review_attempt(
        self,
        task_id: str,
        *,
        candidate: MaintenanceRepairCandidate,
        source_root,
        attempt_root,
        attempt: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not bool(attempt.get("regression_passed")):
            return super().review_attempt(
                task_id,
                candidate=candidate,
                source_root=source_root,
                attempt_root=attempt_root,
                attempt=attempt,
            )

        author_route = str(candidate.author_route_id or "").strip()
        if not author_route or not self._independent_review_route_available(author_route):
            reason_code = (
                "author_route_unavailable"
                if not author_route
                else "independent_route_unavailable"
            )
            self._record_review(
                task_id=str(task_id),
                attempt_key=str(attempt.get("attempt_key") or ""),
                candidate_key=candidate.candidate_key,
                decision="unreviewed",
                reason_code=reason_code,
                rationale="",
                route_id="",
                provider="",
                model="",
                independent_route=False,
            )
            return {
                "reviewed": False,
                "decision": "unreviewed",
                "reason_code": reason_code,
                "independent_route": False,
                "route_id": "",
                "investigation": self.ledger.get(str(task_id)),
            }

        review = super().review_attempt(
            task_id,
            candidate=candidate,
            source_root=source_root,
            attempt_root=attempt_root,
            attempt=attempt,
        )
        # Route health/configuration can change between the availability probe and
        # actual dispatch. Never leave an automatic acceptance behind if the real
        # reviewer fell back to the author route during that race.
        if review.get("decision") == "accept" and not bool(review.get("independent_route")):
            investigation = self.ledger.reject(
                str(task_id), reason="semantic_independence_lost"
            )
            self._record_review(
                task_id=str(task_id),
                attempt_key=str(attempt.get("attempt_key") or ""),
                candidate_key=candidate.candidate_key,
                decision="reject",
                reason_code="independent_route_lost",
                rationale="",
                route_id=str(review.get("route_id") or ""),
                provider="",
                model="",
                independent_route=False,
            )
            return {
                "reviewed": True,
                "decision": "reject",
                "reason_code": "independent_route_lost",
                "independent_route": False,
                "route_id": str(review.get("route_id") or ""),
                "investigation": investigation,
            }
        return review

    def _independent_review_route_available(self, author_route: str) -> bool:
        goal = Goal(
            goal_id="maintenance-semantic-review-route-probe",
            task="Select an independent semantic review resource.",
            required_capabilities=("general",),
            metadata={"maintenance_cognition": True, "phase": "semantic_review_route_probe"},
        )
        with self.kernel._resource_lock:
            router = self.kernel.router
        try:
            route = router.select(goal, excluded={author_route})
        except NoRouteAvailable:
            return False
        return bool(str(route.route_id) and str(route.route_id) != author_route)

    def _invoke(
        self,
        *,
        question: str,
        context: str,
        excluded_routes: frozenset[str],
        allow_excluded_fallback: bool = False,
    ) -> tuple[str, dict[str, str]]:
        task_id, phase = self._dispatch_identity(context)
        input_fingerprint = self._dispatch_fingerprint(
            "zn-maintenance-cognition-input-v1",
            json.dumps(
                {
                    "phase": phase,
                    "question": question,
                    "context": context,
                    "excluded_routes": sorted(excluded_routes),
                    "allow_excluded_fallback": bool(allow_excluded_fallback),
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        call_key = self._dispatch_fingerprint(
            "zn-maintenance-cognition-call-v1",
            "\x00".join([task_id, phase, input_fingerprint]),
        )
        goal = Goal(
            goal_id=f"maintenance-{phase}",
            task=str(question),
            required_capabilities=("general",),
            metadata={"maintenance_cognition": True, "phase": phase},
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
        self._reserve_dispatch(
            task_id=task_id,
            call_key=call_key,
            phase=phase,
            input_fingerprint=input_fingerprint,
            route_id=str(route.route_id),
            provider=str(route.provider),
            model=str(route.model),
        )
        try:
            result = worker.run(goal, context)
        except BaseException as exc:
            self._finish_dispatch(
                call_key,
                status="outcome_uncertain",
                output_fingerprint="",
                error_type=type(exc).__name__,
            )
            raise RuntimeError("maintenance cognition outcome is uncertain; automatic replay is blocked") from exc

        if not result.success:
            self._finish_dispatch(
                call_key,
                status="failed_terminal",
                output_fingerprint="",
                error_type="WorkerResultFailure",
            )
            raise RuntimeError("maintenance cognition resource failed; automatic replay is blocked")

        text = str(result.response or "").strip()
        output_fingerprint = self._dispatch_fingerprint(
            "zn-maintenance-cognition-output-v1", text
        )
        self._finish_dispatch(
            call_key,
            status="completed",
            output_fingerprint=output_fingerprint,
            error_type="",
        )
        if not text:
            raise RuntimeError("maintenance cognition returned empty response")
        if len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise RuntimeError("maintenance cognition response exceeds bound")
        return text, {
            "route_id": str(route.route_id),
            "provider": str(route.provider),
            "model": str(route.model),
        }

    def snapshot(self, *, limit: int = 128) -> dict[str, Any]:
        base = super().snapshot(limit=limit)
        bounded = max(1, min(512, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT task_id,call_key,phase,input_fingerprint,route_id,provider,model,status,"
                "output_fingerprint,error_type,created_at,finished_at FROM "
                "resident_maintenance_cognition_dispatch ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM resident_maintenance_cognition_dispatch"
                ).fetchone()[0]
            )
        base["dispatch_count"] = total
        base["dispatch_returned_count"] = len(rows)
        base["dispatch_truncated"] = total > len(rows)
        base["dispatches"] = [dict(row) for row in rows]
        return base

    @staticmethod
    def _dispatch_identity(context: str) -> tuple[str, str]:
        try:
            payload = json.loads(context)
        except json.JSONDecodeError as exc:
            raise RuntimeError("maintenance cognition context identity is invalid") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("maintenance cognition context identity is invalid")
        task = payload.get("task")
        if not isinstance(task, dict):
            raise RuntimeError("maintenance cognition task identity is unavailable")
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError("maintenance cognition task identity is unavailable")
        role = str(payload.get("role") or "").strip()
        phase_by_role = {
            "ZN bounded maintenance target selector": "target_selection",
            "ZN bounded maintenance repair author": "repair_authoring",
            "ZN maintenance semantic reviewer": "semantic_review",
        }
        phase = phase_by_role.get(role)
        if phase is None:
            raise RuntimeError("maintenance cognition phase identity is unavailable")
        return task_id, phase

    def _reserve_dispatch(
        self,
        *,
        task_id: str,
        call_key: str,
        phase: str,
        input_fingerprint: str,
        route_id: str,
        provider: str,
        model: str,
    ) -> None:
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT status FROM resident_maintenance_cognition_dispatch WHERE call_key=?",
                (call_key,),
            ).fetchone()
            if existing is not None:
                conn.rollback()
                raise RuntimeError(
                    "maintenance cognition dispatch already recorded; automatic replay is blocked"
                )
            conn.execute(
                "INSERT INTO resident_maintenance_cognition_dispatch("
                "task_id,call_key,phase,input_fingerprint,route_id,provider,model,status,"
                "output_fingerprint,error_type,created_at,finished_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    call_key,
                    phase,
                    input_fingerprint,
                    route_id,
                    provider,
                    model,
                    "dispatching",
                    "",
                    "",
                    now,
                    "",
                ),
            )
            conn.commit()

    def _finish_dispatch(
        self,
        call_key: str,
        *,
        status: str,
        output_fingerprint: str,
        error_type: str,
    ) -> None:
        if status not in {"completed", "failed_terminal", "outcome_uncertain"}:
            raise ValueError("invalid maintenance cognition dispatch status")
        with closing(self._connect()) as conn:
            updated = conn.execute(
                "UPDATE resident_maintenance_cognition_dispatch SET "
                "status=?,output_fingerprint=?,error_type=?,finished_at=? "
                "WHERE call_key=? AND status='dispatching'",
                (status, output_fingerprint, error_type[:128], utc_now(), call_key),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise RuntimeError("maintenance cognition dispatch state changed unexpectedly")
            conn.commit()

    def _init_dispatch_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resident_maintenance_cognition_dispatch("
                "task_id TEXT NOT NULL,call_key TEXT PRIMARY KEY,phase TEXT NOT NULL,"
                "input_fingerprint TEXT NOT NULL,route_id TEXT NOT NULL,provider TEXT NOT NULL,"
                "model TEXT NOT NULL,status TEXT NOT NULL,output_fingerprint TEXT NOT NULL,"
                "error_type TEXT NOT NULL,created_at TEXT NOT NULL,finished_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_maintenance_cognition_dispatch_task "
                "ON resident_maintenance_cognition_dispatch(task_id,created_at)"
            )
            conn.commit()

    @staticmethod
    def _dispatch_fingerprint(namespace: str, value: str) -> str:
        digest = hashlib.sha256()
        digest.update(namespace.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(value).encode("utf-8", errors="replace"))
        return digest.hexdigest()

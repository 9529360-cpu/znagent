from __future__ import annotations

"""Evidence-bound completion for the existing steerable Work ledger.

A Resident event can finish successfully while the WorkItem it serves still has
unmet acceptance criteria. This layer preserves the event/result as evidence but
prevents that executor/model success bit from becoming Work acceptance by
itself. It deliberately adds no scheduler, planner, worker identity, or second
store; the existing WorkItem and plan-version tables remain authoritative.
"""

import json

from .models import ResidentRunResult, utc_now
from .steerable_work import SteerableWorkLedger, WorkItem


class EvidenceBoundSteerableWorkLedger(SteerableWorkLedger):
    """Do not equate a successful Resident event with accepted criterion-bound Work."""

    _UNVERIFIED_BLOCKER = (
        "resident event succeeded, but this WorkItem has acceptance criteria that "
        "still require independent current-world evidence"
    )
    _ACCEPTANCE_KEY = "zn_independent_acceptance"

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

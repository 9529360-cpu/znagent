from __future__ import annotations

"""Evidence-bound completion for the existing steerable Work ledger.

A Resident event can finish successfully while the WorkItem it serves still has
unmet acceptance criteria. This layer preserves the event/result as evidence but
prevents that executor/model success bit from becoming Work acceptance by
itself. It deliberately adds no scheduler, planner, worker identity, or second
store; the existing WorkItem and plan-version tables remain authoritative.
"""

from .models import ResidentRunResult, utc_now
from .steerable_work import SteerableWorkLedger


class EvidenceBoundSteerableWorkLedger(SteerableWorkLedger):
    """Do not equate a successful Resident event with accepted criterion-bound Work."""

    _UNVERIFIED_BLOCKER = (
        "resident event succeeded, but this WorkItem has acceptance criteria that "
        "still require independent current-world evidence"
    )

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

        # Preserve the successful event response/artifacts as evidence, but do
        # not turn that success claim into acceptance. ``blocked`` is an existing
        # active WorkItem state, so steering/replan continues to supersede it
        # correctly without adding another lifecycle vocabulary in this slice.
        item.status = "blocked"
        item.blocker = self._UNVERIFIED_BLOCKER
        item.completed_at = None
        item.updated_at = utc_now()
        self._save_item(item)

    def progress(self, thread_id: str, event_id: str) -> dict[str, object]:
        progress = super().progress(thread_id, event_id)
        item = self.work_item_for_event(event_id)
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

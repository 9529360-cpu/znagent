from __future__ import annotations

"""Bind E2E-13 fresh application evidence into existing Root Work truth.

The cleanup behavior owns task execution. This tiny composition layer runs only
when that behavior has already produced its fresh final UIA evidence, then uses
the existing EvidenceBoundSteerableWorkLedger independent-acceptance gate so a
successful Save dispatch alone can never complete the Root Work.
"""

import json

from .current_app_text_cleanup_behavior import _STATE_KEY
from .models import ExecutionPath, ResidentRunResult, utc_now

_INSTALL_MARKER = "_e2e13_current_app_text_cleanup_completion_installed"
_VERIFIER_TITLE = "E2E-13 saved result verifier"
_VERIFIER_OBJECTIVE = (
    "Verify the fresh same-process result window independently matches the "
    "Resident-owned deterministic cleanup result"
)
_VERIFIER_CRITERION = (
    "fresh same-process new-window UIA readback hash equals deterministic cleanup result"
)


def _safe_summary(meta: dict) -> str:
    transform = dict(meta.get("transform") or {})
    final = dict(meta.get("final_verification") or {})
    payload = {
        "e2e13_verifier": True,
        "version": 1,
        "source_sha256": str(transform.get("source_sha256") or ""),
        "source_chars": int(transform.get("source_chars") or 0),
        "source_line_count": int(transform.get("source_line_count") or 0),
        "result_sha256": str(transform.get("result_sha256") or ""),
        "result_chars": int(transform.get("result_chars") or 0),
        "result_line_count": int(transform.get("result_line_count") or 0),
        "removed_blank_line_count": int(transform.get("removed_blank_line_count") or 0),
        "removed_duplicate_line_count": int(transform.get("removed_duplicate_line_count") or 0),
        "new_window_handle": int(final.get("new_window_handle") or 0),
        "same_process": bool(final.get("same_process")),
        "title_postcondition": bool(final.get("title_postcondition")),
        "semantic_target_name": str(final.get("semantic_target_name") or ""),
        "final_sha256": str(final.get("sha256") or ""),
        "final_chars": int(final.get("chars") or 0),
        "read_identity_stable": bool(final.get("read_identity_stable")),
        "verified_at": str(final.get("verified_at") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _find_or_create_verifier(resident, root, meta: dict):
    verifier_id = str(meta.get("verifier_work_item_id") or "").strip()
    items = resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
    if verifier_id:
        found = next((item for item in items if item.work_item_id == verifier_id), None)
        if found is not None:
            return found

    current = [
        item
        for item in items
        if item.parent_work_item_id == root.work_item_id
        and item.plan_version == root.plan_version
        and item.title == _VERIFIER_TITLE
        and item.objective == _VERIFIER_OBJECTIVE
        and list(item.acceptance_criteria) == [_VERIFIER_CRITERION]
    ]
    if len(current) > 1:
        raise RuntimeError("E2E-13 independent acceptance found ambiguous verifier WorkItems")
    if current:
        verifier = current[0]
    else:
        verifier = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=_VERIFIER_OBJECTIVE,
            acceptance_criteria=[_VERIFIER_CRITERION],
            title=_VERIFIER_TITLE,
        )
    meta["verifier_work_item_id"] = verifier.work_item_id
    meta["verifier_bound_at"] = utc_now()
    return verifier


def install_current_app_text_cleanup_completion(resident) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        result = original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )
        if not isinstance(result, ResidentRunResult) or not result.success:
            return result

        meta_raw = state.data.get(_STATE_KEY)
        if not isinstance(meta_raw, dict):
            return result
        meta = dict(meta_raw)
        if str(meta.get("phase") or "") != "complete" or not isinstance(
            meta.get("final_verification"), dict
        ):
            return result

        try:
            root = resident.work_ledger.work_item_for_event(event.event_id)
            if root is None or root.parent_work_item_id is not None or not root.acceptance_criteria:
                raise RuntimeError("E2E-13 final verification lost its criterion-bound Root Work")
            verifier = _find_or_create_verifier(resident, root, meta)
            summary = _safe_summary(meta)
            if verifier.status != "completed":
                verifier = resident.work_ledger.complete_child_item(
                    verifier.work_item_id,
                    result=summary,
                )
            accepted = resident.work_ledger.accept_root_with_current_evidence(
                event.event_id,
                verifier_work_item_id=verifier.work_item_id,
                verification_summary=summary,
            )
            if accepted.status != "completed":
                raise RuntimeError("E2E-13 independent Root acceptance did not complete")
            meta["root_work_item_id"] = accepted.work_item_id
            meta["root_work_status"] = accepted.status
            meta["root_accepted_at"] = utc_now()
            state.data[_STATE_KEY] = meta
            resident.store.save_working_state(state)
            return result
        except Exception as exc:
            state.stage = "terminal_failure"
            state.next_action = None
            state.blocked_by = "fresh application verification could not be bound to Root Work truth"
            meta["root_acceptance_error"] = f"{type(exc).__name__}: {exc}"[:2000]
            state.data[_STATE_KEY] = meta
            resident.store.save_working_state(state)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BODY,
                success=False,
                response="",
                model_invocations=0,
                reason=(
                    "E2E-13 side effects were not replayed, but the verified final application state "
                    "could not pass the existing Root Work independent-acceptance gate: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)

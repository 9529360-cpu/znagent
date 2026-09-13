from __future__ import annotations

"""Bind E2E-13 fresh application evidence into existing Root Work truth.

The cleanup behavior owns task execution. This composition layer also owns the
restart seam for E2E-13's replay-sensitive ValuePattern mutation: if the shared
side-effect journal says a replacement already crossed durable dispatch ownership,
current reality must reconcile that old attempt before the behavior may consider
ordinary source drift or form a new replacement action.
"""

import json

from .automation_text_content import text_sha256
from .current_app_text_cleanup_behavior import _STATE_KEY, _terminal
from .current_app_text_cleanup_goal import CurrentAppTextCleanupGoal
from .models import ExecutionPath, ResidentRunResult, utc_now

_INSTALL_MARKER = "_e2e13_current_app_text_cleanup_completion_installed"
_EXECUTION_TITLE = "E2E-13 bounded desktop execution"
_EXECUTION_OBJECTIVE = (
    "Perform the bounded current-app deterministic cleanup and one Save using fresh desktop authority"
)
_EXECUTION_CRITERION = (
    "bounded current-app cleanup mutation and single Save reached fresh final application verification"
)
_VERIFIER_TITLE = "E2E-13 saved result verifier"
_VERIFIER_OBJECTIVE = (
    "Independently verify the fresh same-process result window matches the Resident-owned "
    "deterministic cleanup result"
)
_VERIFIER_CRITERION = (
    "independent_python_verification:e2e13 fresh same-process new-window UIA readback hash "
    "equals deterministic cleanup result"
)


def _safe_summary(meta: dict, *, evidence_kind: str) -> str:
    transform = dict(meta.get("transform") or {})
    final = dict(meta.get("final_verification") or {})
    payload = {
        "e2e13_evidence": evidence_kind,
        "version": 1,
        "source_sha256": str(transform.get("source_sha256") or ""),
        "source_chars": int(transform.get("source_chars") or 0),
        "source_line_count": int(transform.get("source_line_count") or 0),
        "result_sha256": str(transform.get("result_sha256") or ""),
        "result_chars": int(transform.get("result_chars") or 0),
        "result_line_count": int(transform.get("result_line_count") or 0),
        "removed_blank_line_count": int(transform.get("removed_blank_line_count") or 0),
        "removed_duplicate_line_count": int(transform.get("removed_duplicate_line_count") or 0),
        "save_dispatch_count": int(meta.get("save_dispatch_count") or 0),
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


def _find_or_create_child(
    resident,
    root,
    meta: dict,
    *,
    meta_key: str,
    title: str,
    objective: str,
    criterion: str,
):
    child_id = str(meta.get(meta_key) or "").strip()
    items = resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
    if child_id:
        found = next((item for item in items if item.work_item_id == child_id), None)
        if found is not None:
            return found

    current = [
        item
        for item in items
        if item.parent_work_item_id == root.work_item_id
        and item.plan_version == root.plan_version
        and item.title == title
        and item.objective == objective
        and list(item.acceptance_criteria) == [criterion]
    ]
    if len(current) > 1:
        raise RuntimeError(f"E2E-13 found ambiguous current-plan WorkItems for {title!r}")
    if current:
        child = current[0]
    else:
        child = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=objective,
            acceptance_criteria=[criterion],
            title=title,
        )
    meta[meta_key] = child.work_item_id
    meta[f"{meta_key}_bound_at"] = utc_now()
    return child


def _recover_replacement_dispatch_ownership(resident, event, state):
    """Reconcile an interrupted E2E-13 SetValue from fresh reality only.

    Returns ``(handled, result)``. When ``handled`` is true the normal cleanup
    behavior must not execute in this pulse. This is intentionally asymmetric:
    exact expected-result reality may prove the old effect, while every mismatch
    holds/fails closed and never grants authority for a new replacement signature.
    """

    if str(getattr(state, "stage", "") or "") != "e2e13_replace":
        return False, None
    raw_meta = state.data.get(_STATE_KEY)
    if not isinstance(raw_meta, dict) or str(raw_meta.get("phase") or "") != "replace":
        return False, None

    attempts_reader = getattr(resident.body, "value_replacement_attempts", None)
    if not callable(attempts_reader):
        return False, None
    try:
        attempts = list(attempts_reader(event.event_id))
    except Exception as exc:
        return True, _terminal(
            resident,
            event,
            state,
            "could not inspect durable E2E-13 replacement ownership after restart: "
            f"{type(exc).__name__}: {exc}",
        )
    if not attempts:
        return False, None
    if len(attempts) != 1:
        return True, _terminal(
            resident,
            event,
            state,
            "multiple durable E2E-13 replacement attempts exist for one event; refusing any replay",
        )

    attempt = dict(attempts[0])
    attempt_id = str(attempt.get("attempt_id") or "").strip()
    status_before = str(attempt.get("status") or "").strip().lower()
    meta = dict(raw_meta)
    expected = dict(meta.get("transform") or {})
    result_chars = int(expected.get("result_chars") or 0)
    result_sha = str(expected.get("result_sha256") or "").strip().lower()
    if not attempt_id or status_before not in {"started", "observed", "verified_effect"}:
        return True, _terminal(
            resident,
            event,
            state,
            "durable E2E-13 replacement ownership is malformed; refusing any replay",
        )
    if result_chars <= 0 or len(result_sha) != 64:
        return True, _terminal(
            resident,
            event,
            state,
            "stale E2E-13 state lacks bounded expected-result evidence for crash recovery",
        )

    try:
        goal = CurrentAppTextCleanupGoal(**dict(meta.get("goal") or {}))
        foreground = resident.foreground_window.probe()
        if (
            int(foreground.process_id) != int(meta.get("process_id") or 0)
            or str(foreground.process_name or "").strip().lower()
            != str(meta.get("process_name") or "").strip().lower()
            or int(foreground.window_handle or 0)
            != int(meta.get("source_window_handle") or 0)
        ):
            raise RuntimeError(
                "foreground process/window no longer matches the interrupted replacement authority"
            )
        edit = resident.named_automation_control.find_unique_edit(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name),
            name=goal.field_name,
        )
        fresh = resident.current_app_text_content.read_exact(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name),
            window_handle=int(foreground.window_handle),
            name=goal.field_name,
            runtime_id=tuple(edit.runtime_id),
            allow_read_only=False,
        )
    except Exception as exc:
        return True, _terminal(
            resident,
            event,
            state,
            "unresolved E2E-13 replacement can only be reconciled from fresh exact app reality; "
            f"{type(exc).__name__}: {exc}",
        )

    fresh_hash = text_sha256(fresh.text)
    if len(fresh.text) != result_chars or fresh_hash != result_sha:
        return True, _terminal(
            resident,
            event,
            state,
            "unresolved E2E-13 replacement does not match the old expected result in fresh reality; "
            "holding uncertainty and refusing a new SetValue signature",
        )

    if status_before in {"started", "observed"}:
        if not resident.body.resolve_uncertain_attempt(
            attempt_id,
            event_id=event.event_id,
            status="verified_effect",
        ):
            return True, _terminal(
                resident,
                event,
                state,
                "durable E2E-13 replacement attempt could not be resolved from verified effect",
            )

    meta["replacement_uncertainty_resolved"] = "verified_effect"
    meta["replacement_recovery"] = {
        "attempt_id": attempt_id,
        "status_before": status_before,
        "status_after": "verified_effect",
        "semantic_target_name": goal.field_name,
        "process_id": int(foreground.process_id),
        "process_name": str(foreground.process_name or "").strip().lower(),
        "window_handle": int(foreground.window_handle),
        "runtime_id": list(edit.runtime_id),
        "chars": len(fresh.text),
        "sha256": fresh_hash,
        "read_identity_stable": bool(fresh.audit.get("read_identity_stable")),
        "additional_replacement_dispatches": 0,
        "recovered_at": utc_now(),
    }
    meta["phase"] = "verify_replacement"
    meta["replacement_verified_at"] = utc_now()
    state.data[_STATE_KEY] = meta
    state.stage = "e2e13_verify_replacement"
    state.next_action = "freshly reread the exact edit after crash recovery before save"
    state.blocked_by = None
    resident.store.save_working_state(state)
    return True, None


def install_current_app_text_cleanup_completion(resident) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        handled, recovery_result = _recover_replacement_dispatch_ownership(
            resident,
            event,
            state,
        )
        if handled:
            return recovery_result

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

            execution = _find_or_create_child(
                resident,
                root,
                meta,
                meta_key="execution_work_item_id",
                title=_EXECUTION_TITLE,
                objective=_EXECUTION_OBJECTIVE,
                criterion=_EXECUTION_CRITERION,
            )
            if execution.status != "completed":
                execution = resident.work_ledger.complete_child_item(
                    execution.work_item_id,
                    result=_safe_summary(meta, evidence_kind="bounded_execution"),
                )

            verifier = _find_or_create_child(
                resident,
                root,
                meta,
                meta_key="verifier_work_item_id",
                title=_VERIFIER_TITLE,
                objective=_VERIFIER_OBJECTIVE,
                criterion=_VERIFIER_CRITERION,
            )
            summary = _safe_summary(meta, evidence_kind="independent_final_readback")
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

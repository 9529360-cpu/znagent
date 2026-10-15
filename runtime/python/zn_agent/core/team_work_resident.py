from __future__ import annotations

"""Team execution layer: the resident itself is the specialist executor.

Chain position: ``BroadGoalCodingResidentRuntime`` (Veteran intercept) ->
``TeamWorkResidentRuntime`` -> ``BroadGoalRecoverableCodingResidentRuntime``.
Same pattern as the Veteran owner: intercept ``_deliberation_step`` for
events the owner handles, run one durable driver step per pulse, then fall
through to the normal cognition loop.

Per-pulse flow for a team event::

    deliberation intercept -> TeamWorkOwner.advance (runner.step: dispatch /
    verify / complete) -> cognition with the live specialist's context ->
    integration executes ONE bounded step (write_file / run_python) against
    the runner's child WorkItem -> Body verifies the postcondition ->
    evidence recorded on the WorkerRun -> specialist claims via prose ->
    runner verifies (fresh observation) -> item completes -> next item

Nothing here is a second control plane: plan items, WorkerRuns, evidence,
verification and completion all live in the existing Work ledger. The
runner never completes an item on a claim alone -- verification with
fresh observation is the gate, and a failed verification stalls the item
until the coordinator escalates to the user.

Two feedback loops keep a live specialist from spinning: a rejected
structured proposal records its reason and the next cognition call
carries it (so the model can fix the real mistake), and a run that goes
``_MAX_NO_EVIDENCE_PULSES`` consecutive pulses without new Body-verified
evidence escalates instead of burning pulses with zero progress.

CP-3 adds a third gate: a completion claim must be a structured final
report adjudicated against the plan item's ``expected_output``
(``completion_verdict``). A non-verified verdict feeds its reason +
actionable fix + missing items back to the next cognition call; a
blown retry budget escalates instead of re-asking.
"""

import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .action import NativeActionIntent
from .broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from .cognition import CognitiveIncrement
from .models import ExecutionPath, utc_now
from .plan_mode import (
    PLAN_GATE_STATE_KEY,
    parse_plan_proposal,
    plan_file_rel_path,
    plan_gate,
    plan_mode_enabled,
    plan_pending,
    render_plan_markdown,
    request_plan,
)
from .sensitive_handover import (
    detect_sensitive_step,
    pending_handover,
    request_handover,
)
from .structured_proposal import (
    looks_like_structured_payload,
    parse_exact_json_payload,
)
from .team_disband import execute_disband, handles_disband
from .team_work_owner import (
    EVIDENCE_KEY,
    TEAM_CLAIM_STATE_KEY,
    TEAM_COMPLETE_STATE_KEY,
    TEAM_ID_STATE_KEY,
    TeamWorkOwner,
    verified_evidence,
)
from .team_termination import record_team_tool_call


class TeamWorkResidentRuntime(BroadGoalCodingResidentRuntime):
    """Drive project-team events through the resident's own cognition loop."""

    _TEAM_STEP_KEY = "team_specialist_step"
    _TEAM_SOURCE = "resident_team_specialist_choice"
    _TEAM_LIVE_CONTEXT_KEY = "team_live_context"
    # Durable rejection feedback: the latest rejected proposal for the live
    # run, fed into the next cognition call so the model learns why its
    # proposal was refused instead of repeating it blind.
    _TEAM_REJECTION_KEY = "team_proposal_rejection"
    # Durable zero-evidence-progress counter for the live run. Cognition
    # calls keep arriving even when nothing verifiable is produced, so a
    # wall-clock stall timeout alone never fires: count consecutive pulses
    # with no new verified evidence and escalate at the threshold.
    _TEAM_NO_PROGRESS_KEY = "team_no_evidence_progress"
    _MAX_NO_EVIDENCE_PULSES = 8
    # P2: a specialist that hits a missing design/scope gap reports it
    # instead of inventing scope. LG-2: the gap is an INTERRUPT, not a
    # terminal failure -- the integration step persists the pending
    # decision (team shared memory + AF-2 checkpoint), the next
    # deliberation blocks the event alive until resume_interrupt()
    # supplies the decision value, and the interrupted node then
    # re-runs with that value.
    _TEAM_GAP_KEY = "team_specialist_gap"
    # LG-2: the consumed resume value, carried exactly once into the
    # interrupted node's next cognition call.
    _TEAM_RESUME_KEY = "team_interrupt_resume"
    # Rewrite-loop convergence: byte-identical content rewritten twice,
    # or the same (objective, path) four times, means the specialist is
    # circling without converging -- escalate instead of spinning.
    _MAX_IDENTICAL_CONTENT_REWRITES = 2
    _MAX_SAME_OBJECTIVE_STEPS = 4

    # -- disband: DisbandPlan executed for real (P3-8) ---------------------

    def _handle_disband(self, event, state):
        """Execute the disband and complete with the cleanup checklist.

        Deterministic local completion (CAPABILITY checkpoint, zero model
        calls): deletion is never a model decision. The checklist is the
        event's final response, so the owner sees it in the thread.
        """
        payload = event.payload if isinstance(event.payload, dict) else {}
        team_id = str(
            (payload.get("disband_request") or {}).get("team_id") or ""
        ).strip()
        thread_id = str(payload.get("work_thread_id") or "").strip()
        root = self.work_ledger.work_item_for_event(event.event_id)
        try:
            report = execute_disband(
                team_id=team_id,
                ledger=self.work_ledger,
                memory=self.memory,
                thread_id=thread_id,
                current_event_id=event.event_id,
                current_work_item_id=(
                    root.work_item_id if root is not None else None
                ),
                current_message_id=(
                    str(payload.get("work_message_id") or "").strip() or None
                ),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            reason = f"解散失败，未完成清理：{type(exc).__name__}: {exc}"
            state.data["local_failure"] = reason[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(event, state, reason=reason)
        completion = {
            "execution_path": ExecutionPath.CAPABILITY.value,
            "success": True,
            "response": report.checklist_text(),
            "model_invocations": 0,
            "capability_name": "team_disband",
            "reason": f"团队 {team_id} 已解散，清理清单已交付",
        }
        state.stage = "resident_completion"
        state.next_action = "交付团队解散清理清单"
        state.data["resident_completion"] = completion
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return self._resident_completion_result(event, completion)

    # -- deliberation: one durable driver step per pulse -------------------

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        # P3-8 disband: the user's disband instruction is the confirmation.
        # Runs before the team branch (a disband event carries
        # disband_request, not team_request, so TeamWorkOwner.handles is
        # False for it) and completes deterministically -- no cognition,
        # no model involvement in deletion.
        if handles_disband(event):
            return self._handle_disband(event, state)

        if (
            not TeamWorkOwner.handles(event)
            or bool(state.data.get(TEAM_COMPLETE_STATE_KEY))
        ):
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        # v1 specialist execution is workspace-bound (write_file / run_python
        # both resolve inside the attached workspace). Without one, fail
        # closed with a clear reason instead of stalling for 30 minutes.
        if not str(event.payload.get("workspace_path") or "").strip():
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "团队需要一个已附加的工作区文件夹才能让专员写文件/跑脚本；"
                    "请附加工作区后重新说一次组团队。"
                ),
            )

        owner = TeamWorkOwner(ledger=self.work_ledger, memory=self.memory)
        # P3-8 sensitive handover: while a handover is pending, the event
        # stays blocked -- no cognition, no dispatch, no claim. The owner
        # resolves it (team_handover_done RPC / "做完了" message); the next
        # pulse sees it resolved and the driver continues.
        thread_id = str(event.payload.get("work_thread_id") or "").strip()
        team = owner.resolve_team(event=event, state=state, thread_id=thread_id)
        # LG-2: a specialist-reported design/scope gap is an INTERRUPT,
        # not a terminal failure. The pending decision lives in team
        # shared memory (durable across crash/restart) and in the AF-2
        # checkpoint; the event stays alive + blocked until
        # resume_interrupt() supplies the decision value. The interrupt
        # must not be answered with another cognition call, or the
        # specialist will invent the missing scope.
        interrupt = owner.pending_interrupt(team_id=team.team_id)
        if interrupt is not None and str(interrupt.get("status") or "") == "resumed":
            # Command(resume) landed: consume exactly once and carry
            # the value into this pulse's cognition call, so the
            # interrupted node re-runs with the decision.
            owner.clear_interrupt(team_id=team.team_id)
            consumed_id = str(interrupt.get("interrupt_id") or "")
            gap_mirror = state.data.get(self._TEAM_GAP_KEY)
            state.data.pop(self._TEAM_GAP_KEY, None)
            if (
                isinstance(gap_mirror, dict)
                and str(gap_mirror.get("missing") or "").strip()
                and str(gap_mirror.get("interrupt_id") or "")
                not in ("", consumed_id)
            ):
                # A newer gap arrived while the old one was pending:
                # re-record it and stay blocked instead of losing it.
                self._record_gap_interrupt(
                    owner, team_id=team.team_id, gap=gap_mirror
                )
                state.data[self._TEAM_GAP_KEY] = dict(gap_mirror)
                return self._block_on_interrupt(
                    event,
                    state,
                    missing=str(gap_mirror.get("missing") or ""),
                )
            state.data[self._TEAM_RESUME_KEY] = {
                "interrupt_id": consumed_id,
                "kind": str(interrupt.get("kind") or "gap"),
                "resume_value": str(interrupt.get("resume_value") or "")[:4000],
            }
        elif interrupt is not None:
            # Still waiting on the user's decision: mirror the pending
            # decision into working state and block the event alive.
            state.data[self._TEAM_GAP_KEY] = {
                "interrupt_id": str(interrupt.get("interrupt_id") or ""),
                "run_id": str(interrupt.get("run_id") or ""),
                "work_item_id": str(interrupt.get("work_item_id") or ""),
                "kind": str(interrupt.get("kind") or "gap"),
                "missing": str(interrupt.get("missing") or "")[:600],
                "needed": str(interrupt.get("needed") or "")[:600],
                "impact": str(interrupt.get("impact") or "")[:600],
            }
            return self._block_on_interrupt(
                event,
                state,
                missing=str(interrupt.get("missing") or ""),
            )
        else:
            # No shared-memory record: a working-state gap left behind
            # is still an interrupt, never a terminal failure --
            # re-record it and block.
            gap = state.data.get(self._TEAM_GAP_KEY)
            if isinstance(gap, dict) and str(gap.get("missing") or "").strip():
                self._record_gap_interrupt(owner, team_id=team.team_id, gap=gap)
                return self._block_on_interrupt(
                    event,
                    state,
                    missing=str(gap.get("missing") or ""),
                )
        # CUR-2 Plan Mode: a pending plan blocks dispatch (never a work
        # step before approval); a rejected plan fails the team closed.
        # This mirrors the handover branch -- the event stays alive while
        # waiting, and resumes on the next pulse after approval lands.
        gate = plan_gate(state.data) if isinstance(state.data, dict) else None
        if gate is not None and gate.get("status") == "rejected":
            state.data.pop(PLAN_GATE_STATE_KEY, None)
            reason = (
                "计划被拒绝，团队已停止："
                f"{str(gate.get('reject_reason') or '计划被拒绝')[:600]}"
            )
            state.data["local_failure"] = reason[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(event, state, reason=reason)
        if plan_pending(state.data if isinstance(state.data, dict) else {}):
            state.blocked_by = "user_presence_required"
            state.stage = "native_deliberation"
            state.next_action = (
                "等待主人审批计划："
                f"{str(gate.get('title') or '')[:200]}"
                f"（已写入 {str(gate.get('plan_file') or '')}，可编辑后批准）"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        pending = pending_handover(self.memory, team.team_id)
        if pending is not None:
            state.blocked_by = "user_presence_required"
            state.stage = "native_deliberation"
            state.next_action = (
                f"等待主人亲自完成敏感步骤：{pending.detail}，完成后点“做完了”"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        if state.blocked_by == "user_presence_required":
            state.blocked_by = None
        try:
            step = owner.advance(
                event=event,
                state=state,
                root_work_item_id=root.work_item_id,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            reason = f"团队驱动失败，已停止：{type(exc).__name__}: {exc}"
            state.data["local_failure"] = reason[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        if step.stop_reason:
            # Hard termination (CP-1): the runner stopped the team before
            # dispatching anything this pulse. Fail closed with the
            # structured STOP_REASON instead of looping or asking cognition
            # with no live specialist.
            reason = (
                f"团队已停止（STOP_REASON={step.stop_reason}）。"
                f"触发：{step.stop_trigger}。"
                "不再派活，等待用户拍板。"
            )
            state.data["local_failure"] = reason[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(event, state, reason=reason)
        # CP-3: the verdict retry budget is blown -- fail closed with the
        # escalation instead of re-asking cognition for the same claim.
        if step.verdict_escalation:
            state.data["local_failure"] = step.verdict_escalation[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(
                event, state, reason=step.verdict_escalation
            )
        # CP-3: a non-verified verdict becomes rejection feedback for the
        # next cognition call (same channel as rejected proposals).
        if step.verdict_feedback is not None:
            feedback = step.verdict_feedback
            state.data[self._TEAM_REJECTION_KEY] = {
                "run_id": str(feedback.get("run_id") or ""),
                "reason": (
                    f"完成裁决 {feedback.get('verdict') or ''}："
                    f"{feedback.get('reason') or ''} "
                    f"可执行修改：{feedback.get('actionable_fix') or ''} "
                    "缺失项："
                    + "、".join(feedback.get("missing_items") or [])
                ),
                "proposal_excerpt": "、".join(feedback.get("missing_items") or []),
            }

        if step.team_complete:
            state.data[TEAM_COMPLETE_STATE_KEY] = True
            state.data.pop("local_failure", None)
            state.next_action = "团队全部任务完成，核对 Root 验收"
            state.data.pop(self._TEAM_LIVE_CONTEXT_KEY, None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            # Normal loop completes the Root from here.
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        if step.escalations and not step.live_run_id:
            # Blocked/stalled with nothing executable: fail closed with the
            # escalation surfaced. The team state stays durable (spec +
            # plan map in team memory), so re-asking resumes from truth.
            # This mirrors how blocked Broad Work fails closed.
            reason = "团队需要用户拍板：" + "; ".join(
                e.reason for e in step.escalations
            )[:1200]
            state.data["local_failure"] = reason[:3000]
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._checkpoint_terminal_failure(event, state, reason=reason)
        if step.live_run_id:
            # Feed the latest rejection for THIS run into the next cognition
            # call (live context). Stale rejections from an earlier run never
            # leak into a new specialist's question.
            rejection = state.data.get(self._TEAM_REJECTION_KEY)
            if (
                isinstance(rejection, dict)
                and str(rejection.get("run_id") or "") == step.live_run_id
                and step.live_context is not None
            ):
                step.live_context["rejection_feedback"] = {
                    "reason": str(rejection.get("reason") or "")[:600],
                    "proposal_excerpt": str(rejection.get("proposal_excerpt") or "")[
                        :600
                    ],
                }
            # Zero-evidence-progress escalation: N consecutive pulses with
            # no new Body-verified evidence escalate instead of letting
            # "a fresh cognition call every pulse, zero progress" spin
            # until the wall-clock stall timeout.
            no_progress = self._count_no_evidence_pulse(
                event, state, run_id=step.live_run_id
            )
            if no_progress is not None:
                state.data["local_failure"] = no_progress[:3000]
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return self._checkpoint_terminal_failure(
                    event, state, reason=no_progress
                )
            # Rewrite-loop convergence: fresh verified evidence every
            # pulse can still mean zero progress (same objective / same
            # content rewritten). Escalate instead of letting the run
            # circle until the pulse cap.
            rewrite_loop = self._check_rewrite_loop(run_id=step.live_run_id)
            if rewrite_loop is not None:
                state.data["local_failure"] = rewrite_loop[:3000]
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return self._checkpoint_terminal_failure(
                    event, state, reason=rewrite_loop
                )
            state.next_action = (
                f"专员 {step.live_specialist_name or 'specialist'} 执行下一步"
            )
            # LG-2: exactly-once delivery of the resume value into the
            # interrupted node's re-run (popped here, so a later pulse
            # never repeats a decision already delivered).
            if step.live_context is not None:
                resume = state.data.pop(self._TEAM_RESUME_KEY, None)
                if isinstance(resume, dict) and str(
                    resume.get("resume_value") or ""
                ).strip():
                    step.live_context["resume_value"] = str(
                        resume["resume_value"]
                    )[:4000]
                    step.live_context["resumed_interrupt_id"] = str(
                        resume.get("interrupt_id") or ""
                    )
            state.data.pop(self._TEAM_LIVE_CONTEXT_KEY, None)
            if step.live_context is not None:
                state.data[self._TEAM_LIVE_CONTEXT_KEY] = dict(step.live_context)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            # Continue to cognition: the live specialist's step is produced
            # by the normal cognition loop.
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        # Transition state (verify/complete pending, next dispatch not yet
        # due): loop deliberation without cognition. Cognition here would
        # ask the model with no live specialist, and generic prose would
        # complete the event before the runner finishes the transition.
        state.next_action = "团队驱动推进中，等待验收/完成确认"
        state.data.pop(self._TEAM_LIVE_CONTEXT_KEY, None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _record_gap_interrupt(self, owner, *, team_id: str, gap: dict) -> dict | None:
        """Best-effort: persist one gap as the team's pending interrupt.

        A failure here must not kill the pulse -- the working-state gap
        mirror still blocks the team, and the next deliberation
        re-records it. Returns the record, or None when not recorded.
        """
        try:
            return owner.record_interrupt(
                team_id=team_id,
                run_id=str(gap.get("run_id") or ""),
                work_item_id=str(gap.get("work_item_id") or ""),
                kind=str(gap.get("kind") or "gap"),
                missing=str(gap.get("missing") or ""),
                needed=str(gap.get("needed") or ""),
                impact=str(gap.get("impact") or ""),
            )
        except (OSError, RuntimeError, ValueError):
            return None

    def _block_on_interrupt(self, event, state, *, missing: str):
        """Block the event alive on a pending decision (LG-2 interrupt)."""
        state.blocked_by = "user_presence_required"
        state.stage = "native_deliberation"
        state.next_action = (
            "等待主人拍板缺口："
            f"{str(missing or '')[:200]}（恢复后继续）"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _count_no_evidence_pulse(self, event, state, *, run_id: str) -> str | None:
        """Count one pulse with no new verified evidence for the live run.

        Returns an escalation reason once the run has gone
        ``_MAX_NO_EVIDENCE_PULSES`` consecutive pulses without producing new
        Body-verified evidence; otherwise None. Evidence growth resets the
        counter; a new run starts it over.
        """
        run = self.work_ledger.worker_run(run_id)
        if run is None:
            return None
        evidence_count = len(verified_evidence(run))
        progress = state.data.get(self._TEAM_NO_PROGRESS_KEY)
        if not isinstance(progress, dict) or str(
            progress.get("run_id") or ""
        ) != run_id:
            state.data[self._TEAM_NO_PROGRESS_KEY] = {
                "run_id": run_id,
                "evidence_count": evidence_count,
                "pulses": 0,
            }
            return None
        try:
            previous_count = int(progress.get("evidence_count") or 0)
        except (TypeError, ValueError):
            previous_count = 0
        if evidence_count > previous_count:
            state.data[self._TEAM_NO_PROGRESS_KEY] = {
                "run_id": run_id,
                "evidence_count": evidence_count,
                "pulses": 0,
            }
            return None
        try:
            pulses = int(progress.get("pulses") or 0) + 1
        except (TypeError, ValueError):
            pulses = 1
        state.data[self._TEAM_NO_PROGRESS_KEY] = {
            "run_id": run_id,
            "evidence_count": evidence_count,
            "pulses": pulses,
        }
        if pulses < self._MAX_NO_EVIDENCE_PULSES:
            return None
        rejection = state.data.get(self._TEAM_REJECTION_KEY)
        reason = (
            f"团队专员连续 {self._MAX_NO_EVIDENCE_PULSES} 个 pulse "
            "没有产生可验证进展，已停止等待用户拍板。"
        )
        if isinstance(rejection, dict) and str(
            rejection.get("run_id") or ""
        ) == run_id:
            detail = str(rejection.get("reason") or "").strip()
            if detail:
                reason += f"最近一次提案被拒原因：{detail[:600]}"
        return reason

    def _check_rewrite_loop(self, *, run_id: str) -> str | None:
        """Escalate when a run rewrites without converging.

        The no-evidence counter cannot see this failure: every rewrite
        produces fresh verified evidence, so the run looks busy while
        making zero progress. Two rules over the run's verified evidence:
        - identical rewrite: the same (objective, path, content hash)
          twice means byte-identical content was written twice -- never
          progress.
        - same-objective loop: the same (objective, path) four times
          with any content means the specialist is circling without
          converging.
        Returns an escalation reason, else None.
        """
        run = self.work_ledger.worker_run(run_id)
        if run is None:
            return None
        identical: dict[tuple[str, str, str], int] = {}
        same_objective: dict[tuple[str, str], int] = {}
        for entry in verified_evidence(run):
            objective = str(entry.get("objective") or "")
            path = str(entry.get("relative_path") or "")
            key = (objective, path)
            same_objective[key] = same_objective.get(key, 0) + 1
            content_hash = str(entry.get("content_hash") or "")
            if content_hash:
                identical_key = (objective, path, content_hash)
                identical[identical_key] = identical.get(identical_key, 0) + 1
                if identical[identical_key] >= self._MAX_IDENTICAL_CONTENT_REWRITES:
                    return (
                        f"团队专员重复提交相同内容（目标“{objective[:120]}”，"
                        f"文件 {path or '（未记录）'}，"
                        f"已 {identical[identical_key]} 次），"
                        "未收敛，已停止等待用户拍板。"
                    )
            if same_objective[key] >= self._MAX_SAME_OBJECTIVE_STEPS:
                return (
                    f"团队专员同一目标重复执行 {same_objective[key]} 次（目标"
                    f"“{objective[:120]}”，文件 {path or '（未记录）'}），"
                    "未收敛，已停止等待用户拍板。"
                )
        return None

    # -- cognition: scope the question to the live specialist ----------------

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(
            event,
            impasse,
            required,
            deliberation,
        )
        if not TeamWorkOwner.handles(event):
            return request
        state = self.store.get_working_state()
        context = state.data.get(self._TEAM_LIVE_CONTEXT_KEY)
        if not isinstance(context, dict) or not context.get("run_id"):
            return request
        evidence = context.get("evidence") or []
        rejection = context.get("rejection_feedback")
        rejection_text = ""
        if isinstance(rejection, dict):
            reason = str(rejection.get("reason") or "").strip()
            excerpt = str(rejection.get("proposal_excerpt") or "").strip()
            if reason or excerpt:
                rejection_text = (
                    "Your last proposal was REJECTED and NOT executed. "
                    f"Rejection reason: {reason or '结构化校验未通过'}. "
                    "Do not repeat it: fix the reason and propose again. "
                    f"Rejected proposal (excerpt): {excerpt[:600]} "
                )
        prior_items = context.get("prior_items")
        prior_text = ""
        if isinstance(prior_items, list) and prior_items:
            prior_text = (
                "前面已完成项（结论与产物，可引用，不要重复做，不要自行发明"
                "与之矛盾的范围）:"
                f" {json.dumps(prior_items, ensure_ascii=False)} "
            )
        # LG-2: the resume value for the interrupted node -- the user's
        # decision that unblocks this re-run.
        resume_value = context.get("resume_value")
        resume_text = ""
        if isinstance(resume_value, str) and resume_value.strip():
            resume_text = (
                "用户已拍板（恢复值）："
                f"{resume_value.strip()[:4000]} "
                "按这个决定继续你的事项，不要重新上报同一缺口，"
                "不要从头重做已完成步骤。 "
            )
        # CUR-2 Plan Mode: when enabled, a multi-file / design-decision
        # item plans first -- no files are written before approval.
        plan_text = ""
        if plan_mode_enabled(event):
            plan_text = (
                "Plan Mode 已开启：如果你的事项涉及多个文件或需要设计抉择，"
                "不要先写文件。只回复这一个 JSON 对象（不要其他文字）："
                '{"plan_proposal":{"title":"...","goal":"...","files":'
                '["relative/path",...],"steps":["...",...],"decisions":'
                '[{"question":"...","options":["...","..."],'
                '"recommendation":"..."}],"risks":["...",...],'
                '"acceptance":["...",...]}}。计划会写成可审阅、可编辑的'
                "计划文件，等用户改完批准后才执行。未经批准不要执行计划"
                "中的任何步骤，也不要重新规划一个已提交待审批的计划。"
            )
        approved_text = ""
        approved_plan = context.get("approved_plan")
        if isinstance(approved_plan, str) and approved_plan.strip():
            approved_text = (
                "已批准的计划（用户改完批准的版本，按它执行，不要重新"
                f"规划，不要偏离）：{approved_plan[:6000]} "
            )
        request.question = (
            "You are the "
            f"{context.get('specialist_name') or 'specialist'} specialist on one "
            "durable ZN project team. ZN owns the Work lifecycle, tools, "
            "permissions, execution, evidence and completion. Work on exactly "
            "ONE smallest useful step for your assigned item. Return ONLY one "
            "JSON object with this shape: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"write_file",'
            '"path":"relative/path","content":"..."},"acceptance":{"kind":"text_equals",'
            '"path":"relative/path","expected_text":"..."}}} OR '
            '{"zn_work_step":{"objective":"...","action":{"kind":"run_python",'
            '"path":"relative/script.py","args":[]},"acceptance":{"kind":"command",'
            '"expected_exit_code":0,"output_contains":["..."]}}}. '
            "The path must be relative to the attached workspace. "
            "The workspace starts EMPTY -- no subdirectories exist yet. "
            "Prefer a path at the workspace root (for example \"notes.md\"). "
            "If you use a subdirectory, its parent directory must already exist. "
            "Do not emit "
            "shell commands, executable paths, background-process controls, or "
            "tool calls. "
            "If you wrote test files, you MUST run them with run_python and "
            "pass before claiming any test-coverage acceptance item: a claim "
            "that cites only written-but-never-run tests will be sent back. "
            "If the design / scope information your item needs is missing -- "
            "for example your brief or objective refers to a design doc, "
            "an interface contract, or a scope definition that is in neither "
            "your brief nor the completed items below -- do NOT invent the "
            "missing scope, interface, or feature set. Reply with ONLY this "
            "JSON object (no other text): "
            '{"gap_report":{"missing":"what information is missing",'
            '"needed":"what is needed to continue",'
            '"impact":"what breaks without it"}}. '
            "The team stops and waits for the user to decide on a reported gap. "
            f"{plan_text}"
            f"{approved_text}"
            "If your item's acceptance criteria are NOT all "
            "satisfied yet, do NOT claim completion: do another work step. "
            "Only when EVERY criterion is satisfied by the verified evidence "
            "below, reply with ONLY this JSON object (no other text): "
            '{"completion_report":{"conclusion":"...","evidence":'
            '[{"criterion":"<exact acceptance criterion>",'
            '"evidence_ref":"<relative_path or objective of one verified '
            'evidence entry below>"}],'
            '"files":["<workspace-relative path>"],"unfinished":[],'
            '"standing_dod":{"no_regression":{"status":"satisfied|'
            'not_applicable","detail":"...","evidence_ref":"..."},'
            '"runtime_verified":{...},"docs":{...},"rollback":{...},'
            '"approval":{...}}}. '
            "Cite EVERY acceptance criterion once, with an evidence_ref that "
            "matches one verified evidence entry below. "
            "standing_dod must attest all five standing Definition-of-Done "
            "items: no_regression, runtime_verified, docs, rollback, "
            "approval -- each with status satisfied|not_applicable and a "
            "concrete detail; no_regression and runtime_verified must cite "
            "a real verified evidence entry (a test run / a runtime run) "
            "when satisfied; a missing or unattested item sends the "
            "report back. Put anything "
            "uncertain or not yet done in \"unfinished\" and do NOT claim "
            "completion for it -- never present a guess as a verified fact. "
            "A report with a missing section, a criterion without evidence, "
            "or a non-empty \"unfinished\" list will be sent back for rework; "
            "repeated identical rejections escalate to the user. "
            f"{rejection_text}"
            f"{resume_text}"
            f"Your brief: {context.get('specialist_prompt') or ''} "
            f"Your item: {context.get('objective') or ''}. "
            f"Acceptance criteria: {json.dumps(context.get('acceptance_criteria') or [], ensure_ascii=False)}. "
            f"{prior_text}"
            f"Verified evidence so far: {json.dumps(evidence, ensure_ascii=False)}."
        )
        request.context = {
            **dict(request.context or {}),
            "team_live_run_id": context.get("run_id"),
            "team_live_work_item_id": context.get("work_item_id"),
            "team_specialist": context.get("specialist_name"),
        }
        return request

    # -- integration: bind one cognition step to the runner's child ---------

    def _cognition_integration_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("cognitive_increment")
        context = state.data.get(self._TEAM_LIVE_CONTEXT_KEY)
        if (
            not TeamWorkOwner.handles(event)
            or not isinstance(context, dict)
            or not context.get("run_id")
            or not isinstance(raw, dict)
        ):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None:
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        increment = CognitiveIncrement.from_dict(raw)

        # P3-8 sensitive handover: a specialist step touching a password,
        # a verification code, or a payment confirmation is never executed
        # and never recorded as a claim. Record the handover, block the
        # event, and wait for the owner to do it by hand.
        sensitive = detect_sensitive_step(increment.content)
        if sensitive is not None:
            team_id = str(state.data.get(TEAM_ID_STATE_KEY) or "").strip()
            if team_id:
                request_handover(
                    memory=self.memory,
                    ledger=self.work_ledger,
                    team_id=team_id,
                    thread_id=str(event.payload.get("work_thread_id") or ""),
                    kind=sensitive.kind,
                )
                state.blocked_by = "user_presence_required"
            else:
                # Deliberation never ran, so no team id to hang the
                # handover on: refuse without executing, and feed the
                # refusal back so the next cognition call sees it.
                state.data[self._TEAM_REJECTION_KEY] = {
                    "run_id": str(context.get("run_id") or ""),
                    "reason": "敏感步骤已拦截，需主人亲自完成（未找到团队记录，无法挂起交接）",
                    "proposal_excerpt": "",
                }
            state.stage = "native_deliberation"
            state.next_action = "敏感步骤已拦截，等待主人亲自完成"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        # P2: a specialist gap report is not a work step and must never be
        # executed. LG-2: persist it as the team's pending interrupt
        # (shared memory + AF-2 checkpoint) and block; the next
        # deliberation waits for the user's resume value instead of
        # inventing the scope.
        gap_shape = parse_exact_json_payload(increment.content)
        if isinstance(gap_shape, dict) and "gap_report" in gap_shape:
            gap_value = gap_shape.get("gap_report")
            if isinstance(gap_value, dict) and str(
                gap_value.get("missing") or ""
            ).strip():
                interrupt_id = ""
                checkpoint_error = ""
                team_id = str(state.data.get(TEAM_ID_STATE_KEY) or "").strip()
                if team_id:
                    interrupt_owner = TeamWorkOwner(
                        ledger=self.work_ledger, memory=self.memory
                    )
                    record = self._record_gap_interrupt(
                        interrupt_owner,
                        team_id=team_id,
                        gap={
                            "run_id": str(context.get("run_id") or ""),
                            "work_item_id": str(
                                context.get("work_item_id") or ""
                            ),
                            "kind": "gap",
                            "missing": str(gap_value.get("missing") or ""),
                            "needed": str(gap_value.get("needed") or ""),
                            "impact": str(gap_value.get("impact") or ""),
                        },
                    )
                    if record is not None:
                        interrupt_id = str(record.get("interrupt_id") or "")
                    # Best-effort checkpoint carrying the pending
                    # decision. A failure here must not kill the pulse
                    # (shared memory + working state already hold the
                    # truth), but it is recorded on the gap mirror
                    # instead of swallowed, so it stays visible.
                    try:
                        root_item = self.work_ledger.work_item_for_event(
                            event.event_id
                        )
                        thread_id = str(
                            event.payload.get("work_thread_id") or ""
                        ).strip()
                        team = interrupt_owner.resolve_team(
                            event=event, state=state, thread_id=thread_id
                        )
                        if root_item is not None:
                            saved = interrupt_owner.save_interrupt_checkpoint(
                                team=team,
                                root_work_item_id=root_item.work_item_id,
                            )
                            if saved is None:
                                # DSH-3: save failures now raise
                                # CheckpointSaveError (caught below with
                                # the real cause), so None here means
                                # only "no checkpoint storage wired".
                                checkpoint_error = (
                                    "interrupt checkpoint not saved "
                                    "(no checkpoint storage wired)"
                                )
                    except (
                        AttributeError,
                        KeyError,
                        LookupError,
                        OSError,
                        RuntimeError,
                        ValueError,
                    ) as exc:
                        checkpoint_error = (
                            f"{type(exc).__name__}: {exc}"[:200]
                        )
                state.data[self._TEAM_GAP_KEY] = {
                    "interrupt_id": interrupt_id,
                    "run_id": str(context.get("run_id") or ""),
                    "work_item_id": str(context.get("work_item_id") or ""),
                    "kind": "gap",
                    "missing": str(gap_value.get("missing") or "")[:600],
                    "needed": str(gap_value.get("needed") or "")[:600],
                    "impact": str(gap_value.get("impact") or "")[:600],
                    "checkpoint_error": checkpoint_error,
                }
                state.stage = "native_deliberation"
                state.next_action = (
                    "专员上报缺口，停止等待用户拍板："
                    f"{str(gap_value.get('missing') or '')[:200]}"
                )
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            # Malformed gap report: same rejection channel as a rejected
            # structured proposal, so the next cognition call sees why.
            state.data[self._TEAM_REJECTION_KEY] = {
                "run_id": str(context.get("run_id") or ""),
                "reason": (
                    "gap_report 格式错误：需为 JSON 对象且含非空 missing 字段，"
                    "例如 {\"gap_report\": {\"missing\": \"...\", "
                    "\"needed\": \"...\", \"impact\": \"...\"}}"
                ),
                "proposal_excerpt": str(increment.content or "")[:600],
            }
            state.stage = "native_deliberation"
            state.next_action = "专员缺口报告格式错误：按拒因重提"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        # CUR-2 Plan Mode: a plan proposal is not a work step and must
        # never be executed. Render it as a reviewable, editable plan
        # file; the team blocks until the user approves the plan.
        # Exact-shape routing only -- prose merely mentioning
        # "plan_proposal" must not misfire this branch.
        if plan_mode_enabled(event):
            plan_shape = parse_exact_json_payload(increment.content)
            if isinstance(plan_shape, dict) and "plan_proposal" in plan_shape:
                proposal, plan_err = parse_plan_proposal(increment.content)
                if proposal is None:
                    state.data[self._TEAM_REJECTION_KEY] = {
                        "run_id": str(context.get("run_id") or ""),
                        "reason": f"plan_proposal 格式错误：{plan_err}",
                        "proposal_excerpt": str(increment.content or "")[:600],
                    }
                    state.stage = "native_deliberation"
                    state.next_action = "专员计划格式错误：按拒因重提"
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                    return None
                gate, replaced = request_plan(
                    state.data,
                    work_item_id=str(context.get("work_item_id") or ""),
                    run_id=str(context.get("run_id") or ""),
                    proposal=proposal,
                    plan_file=plan_file_rel_path(
                        str(context.get("work_item_id") or "")
                    ),
                )
                if not replaced:
                    state.data[self._TEAM_REJECTION_KEY] = {
                        "run_id": str(context.get("run_id") or ""),
                        "reason": (
                            "已有待审批计划，不要重新规划："
                            f"{str(gate.get('title') or '')[:200]}"
                        ),
                        "proposal_excerpt": str(increment.content or "")[:600],
                    }
                    state.stage = "native_deliberation"
                    state.next_action = "已有待审批计划：等用户审批，不要重提"
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                    return None
                workspace_path = str(
                    event.payload.get("workspace_path") or ""
                ).strip()
                if not workspace_path:
                    # No file was written: drop the gate so the state
                    # stays consistent (no pending plan without a file).
                    state.data.pop(PLAN_GATE_STATE_KEY, None)
                    state.data[self._TEAM_REJECTION_KEY] = {
                        "run_id": str(context.get("run_id") or ""),
                        "reason": "无已附加工作区，计划文件无处可写",
                        "proposal_excerpt": str(increment.content or "")[:600],
                    }
                    state.stage = "native_deliberation"
                    state.next_action = "无工作区：计划文件无处可写"
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                    return None
                try:
                    plan_path = (
                        Path(workspace_path)
                        / str(gate.get("plan_file") or "")
                    )
                    plan_path.parent.mkdir(parents=True, exist_ok=True)
                    plan_path.write_text(
                        render_plan_markdown(
                            proposal,
                            work_item_id=str(
                                context.get("work_item_id") or ""
                            ),
                            specialist_name=str(
                                context.get("specialist_name") or "specialist"
                            ),
                        ),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    # No file was written: drop the gate so the state
                    # stays consistent (no pending plan without a file).
                    state.data.pop(PLAN_GATE_STATE_KEY, None)
                    state.data[self._TEAM_REJECTION_KEY] = {
                        "run_id": str(context.get("run_id") or ""),
                        "reason": (
                            "计划文件写入失败："
                            f"{type(exc).__name__}: {exc}"
                        ),
                        "proposal_excerpt": str(increment.content or "")[:600],
                    }
                    state.stage = "native_deliberation"
                    state.next_action = "计划文件写入失败：按拒因重提"
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                    return None
                state.stage = "native_deliberation"
                state.next_action = (
                    "专员已提交计划，等待用户审批："
                    f"{proposal.title[:200]}"
                    f"（已写入 {gate.get('plan_file')}，可编辑后批准）"
                )
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None

        # Route the proposal to the parser matching its declared action
        # kind, so the rejection reason (fed back to the next cognition
        # call) describes the proposal the model actually sent -- not a
        # kind mismatch from the other parser.
        raw_shape = parse_exact_json_payload(increment.content)
        declared_kind = ""
        if isinstance(raw_shape, dict):
            step_shape = raw_shape.get("zn_work_step")
            if isinstance(step_shape, dict):
                action_shape = step_shape.get("action")
                if isinstance(action_shape, dict):
                    declared_kind = str(action_shape.get("kind") or "").strip()
        reasons: list[str] = []
        proposal = None
        parsed_python = None
        if declared_kind == "run_python":
            parsed_python = self._parse_run_python_step(
                event, root, increment.content, reasons=reasons
            )
        else:
            proposal = self._parse_write_file_step(
                event,
                root,
                increment.content,
                allow_missing_parent=True,
                reasons=reasons,
            )

        if proposal is not None:
            return self._begin_team_step(
                event,
                state,
                increment=increment,
                context=context,
                intent=NativeActionIntent(
                    intent_id=f"team-step-{_identity(event, increment)[:12]}",
                    event_id=event.event_id,
                    kind="write_text",
                    args={
                        "path": proposal["absolute_path"],
                        "content": proposal["content"],
                        "append": False,
                        # The parser already boundary-checked the path; a
                        # missing parent is created here instead of
                        # rejecting the proposal (the workspace starts
                        # empty, so subdirectory proposals used to die on
                        # a parent that did not exist yet).
                        "create_parents": True,
                    },
                    expected_outcome={
                        "kind": "text_equals",
                        "path": proposal["absolute_path"],
                        "expected_text": proposal["content"],
                    },
                    reason=(
                        "ZN validated one bounded specialist cognition proposal "
                        "against the attached workspace and chose the concrete "
                        "Body movement itself"
                    ),
                    source=self._TEAM_SOURCE,
                ),
                step_detail={
                    "relative_path": proposal["relative_path"],
                    "objective": proposal["objective"],
                    "action_kind": "write_file",
                },
            )

        if parsed_python is not None:
            command = shlex.join(
                [sys.executable, parsed_python["absolute_path"], *parsed_python["args"]]
            )
            return self._begin_team_step(
                event,
                state,
                increment=increment,
                context=context,
                intent=NativeActionIntent(
                    intent_id=f"team-step-{_identity(event, increment)[:12]}",
                    event_id=event.event_id,
                    kind="command",
                    args={
                        "command": command,
                        "workdir": parsed_python["workspace"],
                        "timeout": parsed_python["timeout"],
                        "max_output_chars": 50_000,
                    },
                    expected_outcome={
                        "kind": "command",
                        "command": command,
                        "workdir": parsed_python["workspace"],
                        "expected_exit_code": parsed_python["expected_exit_code"],
                        "output_contains": parsed_python["output_contains"],
                        "timeout": parsed_python["timeout"],
                        "max_output_chars": 50_000,
                    },
                    reason=(
                        "ZN bound one specialist-proposed Python script to the "
                        "attached workspace, selected its own interpreter, and "
                        "chose the Terminal movement itself"
                    ),
                    source=self._TEAM_SOURCE,
                ),
                step_detail={
                    "relative_path": parsed_python["relative_path"],
                    "objective": parsed_python["objective"],
                    "action_kind": "run_python",
                },
            )

        # A rejected structured proposal must NOT fall through to the prose
        # claim branch below: its text routinely contains "完成" (in the
        # objective or content), and the old fall-through recorded those
        # rejections as completion claims. Record the rejection reason so
        # the next cognition call sees it, and re-ask from that feedback.
        if looks_like_structured_payload(
            increment.content, top_level_key="zn_work_step"
        ):
            reason = reasons[0] if reasons else "提案未通过结构化校验"
            state.data[self._TEAM_REJECTION_KEY] = {
                "run_id": str(context.get("run_id") or ""),
                "reason": reason,
                "proposal_excerpt": str(increment.content or "")[:600],
            }
            state.stage = "native_deliberation"
            state.next_action = f"专员提案被拒：{reason}；按拒因重提"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        # Prose: the specialist claims the item is done. Record the claim and
        # keep the event alive -- the generic prose path would complete the
        # event with the model answer, but a team claim is only a claim:
        # the owner applies it next pulse (only with verified evidence),
        # the runner verifies, and the loop continues to the next item.
        # A completion signal is required: confused prose ("I'm stuck")
        # must not complete an item. Without a signal, no claim is
        # recorded and the next pulse re-asks cognition; the stall
        # timeout eventually escalates to the user.
        summary = str(increment.content or "").strip()
        completion_signals = (
            "完成",
            "搞定了",
            "done",
            "complete",
            "finished",
            "ready",
            "验收",
        )
        claimed = summary and any(
            signal in summary.lower() for signal in completion_signals
        )
        if claimed:
            self._accept_borrowed_increment(event, state, increment)
            # Structured completion reports carry one evidence entry per
            # criterion; keep headroom so a long report is not truncated
            # mid-JSON (a truncated report adjudicates as malformed).
            state.data[TEAM_CLAIM_STATE_KEY] = {
                "run_id": str(context.get("run_id") or ""),
                "summary": summary[:8000],
            }
        state.stage = "native_deliberation"
        state.next_action = (
            "apply specialist completion claim to the team runner"
            if claimed
            else "specialist has not claimed completion; re-ask from evidence"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _begin_team_step(
        self,
        event,
        state,
        *,
        increment,
        context,
        intent,
        step_detail,
    ):
        self._accept_borrowed_increment(event, state, increment)
        # Content hash for the rewrite-loop detector: the evidence entry
        # records what was verified, so a byte-identical rewrite is
        # visible to the next pulse's convergence check.
        content_hash = None
        raw_content = None
        if intent.kind == "write_text":
            raw_content = intent.args.get("content")
        elif intent.kind == "command":
            raw_content = intent.args.get("command")
        if isinstance(raw_content, str) and raw_content:
            content_hash = hashlib.sha256(
                raw_content.encode("utf-8", errors="replace")
            ).hexdigest()[:16]
        state.data[self._TEAM_STEP_KEY] = {
            "run_id": str(context.get("run_id") or ""),
            "work_item_id": str(context.get("work_item_id") or ""),
            "objective": str(step_detail.get("objective") or ""),
            "relative_path": str(step_detail.get("relative_path") or ""),
            "action_kind": str(step_detail.get("action_kind") or ""),
            "increment_id": increment.increment_id,
            "content_hash": content_hash,
        }
        self._begin_native_action_cycle(event, state, intent)
        state.next_action = "execute one ZN-owned team specialist step through the Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    # -- evidence: Body-verified steps land on the WorkerRun -----------------

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        team_step = state.data.get(self._TEAM_STEP_KEY)
        if not isinstance(team_step, dict):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )
        result = super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )
        # Mirror BroadGoalWork: a verified specialist step is not terminal
        # Root completion. Always record the evidence and keep the event
        # alive (None) -- returning super()'s result would finalize the
        # event after the first verified step.
        return self._record_team_evidence(event, state, result=result)

    def _resume_native_completion(self, event, state):
        team_step = state.data.get(self._TEAM_STEP_KEY)
        if not isinstance(team_step, dict):
            return super()._resume_native_completion(event, state)
        result = super()._resume_native_completion(event, state)
        if result is None or not result.success:
            return result
        return self._record_team_evidence(event, state, result=result)

    def _record_team_evidence(self, event, state, *, result):
        team_step = state.data.get(self._TEAM_STEP_KEY)
        if not isinstance(team_step, dict):
            return result
        run_id = str(team_step.get("run_id") or "").strip()
        run = self.work_ledger.worker_run(run_id) if run_id else None
        if run is not None and run.state in {"queued", "running"}:
            evidence = verified_evidence(run)
            entry: dict[str, Any] = {
                "kind": "verified_body_step",
                "objective": str(team_step.get("objective") or "")[:600],
                "relative_path": str(team_step.get("relative_path") or "")[:600],
                "action_kind": str(team_step.get("action_kind") or ""),
                "result": str(getattr(result, "response", "") or "")[:4000],
                "verified": True,
                "recorded_at": utc_now(),
                "artifact_refs": [],
            }
            if team_step.get("content_hash"):
                entry["content_hash"] = str(team_step["content_hash"])
            evidence.append(entry)
            try:
                self.work_ledger.update_worker_run_metrics(
                    run_id, metrics={EVIDENCE_KEY: evidence[-12:]}
                )
                # CP-1 tool cap: one durable increment per executed
                # specialist tool step. Counter loss must not kill the
                # event -- see the except below.
                team_id = str(state.data.get(TEAM_ID_STATE_KEY) or "").strip()
                if team_id:
                    record_team_tool_call(self.memory, team_id)
            except (OSError, RuntimeError, ValueError):
                # Evidence checkpoint loss must not kill the event: the
                # runner's verifier will fail closed (no evidence -> no pass)
                # and the coordinator escalates. Keep the durable step key
                # cleared below so the next pulse re-asks cognition.
                pass
        state.data.pop(self._TEAM_STEP_KEY, None)
        state.data.pop("native_completion", None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        # Verified progress supersedes the last rejection and resets the
        # zero-evidence-progress counter: the specialist is moving again.
        state.data.pop(self._TEAM_REJECTION_KEY, None)
        state.data.pop(self._TEAM_NO_PROGRESS_KEY, None)
        state.stage = "native_deliberation"
        state.next_action = "choose the next bounded team specialist step from fresh evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    # -- verification contract for team command intents ----------------------

    def _verification_contract(self, event, intent, *, result=None):
        raw = intent.expected_outcome
        if (
            intent.source != self._TEAM_SOURCE
            or intent.kind != "command"
            or not isinstance(raw, dict)
        ):
            return super()._verification_contract(event, intent, result=result)
        if str(raw.get("kind") or "").strip().lower() != "command":
            return super()._verification_contract(event, intent, result=result)
        command = str(raw.get("command") or "").strip()
        intent_command = str(intent.args.get("command") or "").strip()
        workdir = str(raw.get("workdir") or "").strip() or None
        intent_workdir = str(intent.args.get("workdir") or "").strip() or None
        if not command or command != intent_command or workdir != intent_workdir:
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "team command verification must exactly match the current ZN-owned movement",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        try:
            expected_exit = int(raw.get("expected_exit_code", 0))
            timeout = max(0.05, min(120.0, float(raw.get("timeout", 20.0))))
            max_output = max(128, min(100_000, int(raw.get("max_output_chars", 50_000))))
        except (TypeError, ValueError):
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "team command verification has invalid numeric limits",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        raw_output = raw.get("output_contains") or []
        if not isinstance(raw_output, list):
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "team command verification output_contains must be a list",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        output_contains = [str(item) for item in raw_output if str(item)]
        return {
            "kind": "command",
            "command": command,
            "workdir": workdir,
            "expected_exit_code": expected_exit,
            "output_contains": output_contains,
            "timeout": timeout,
            "max_output_chars": max_output,
            "intent_id": intent.intent_id,
            "action_signature": self._intent_signature(intent),
        }


def _identity(event: Any, increment: Any) -> str:
    """Deterministic identity for one specialist step (crash-safe replay)."""
    return hashlib.sha256(
        f"{event.event_id}\0{increment.increment_id}".encode("utf-8", errors="replace")
    ).hexdigest()[:16]


__all__ = ["TeamWorkResidentRuntime"]

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
"""

import hashlib
import json
import shlex
import sys
from typing import Any

from .action import NativeActionIntent
from .broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from .cognition import CognitiveIncrement
from .models import utc_now
from .structured_proposal import (
    looks_like_structured_payload,
    parse_exact_json_payload,
)
from .team_work_owner import (
    EVIDENCE_KEY,
    TEAM_CLAIM_STATE_KEY,
    TEAM_COMPLETE_STATE_KEY,
    TeamWorkOwner,
    verified_evidence,
)


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
            state.next_action = (
                f"专员 {step.live_specialist_name or 'specialist'} 执行下一步"
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
            "tool calls. If your item's acceptance criteria are ALREADY fully "
            "satisfied by the verified evidence below, reply with ONLY a short "
            "completion summary in plain text (no JSON) quoting which criteria "
            "are met. Do not claim completion without verified evidence. "
            f"{rejection_text}"
            f"Your brief: {context.get('specialist_prompt') or ''} "
            f"Your item: {context.get('objective') or ''}. "
            f"Acceptance criteria: {json.dumps(context.get('acceptance_criteria') or [], ensure_ascii=False)}. "
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
            state.data[TEAM_CLAIM_STATE_KEY] = {
                "run_id": str(context.get("run_id") or ""),
                "summary": summary[:2000],
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
        state.data[self._TEAM_STEP_KEY] = {
            "run_id": str(context.get("run_id") or ""),
            "work_item_id": str(context.get("work_item_id") or ""),
            "objective": str(step_detail.get("objective") or ""),
            "relative_path": str(step_detail.get("relative_path") or ""),
            "action_kind": str(step_detail.get("action_kind") or ""),
            "increment_id": increment.increment_id,
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
            evidence.append(
                {
                    "kind": "verified_body_step",
                    "objective": str(team_step.get("objective") or "")[:600],
                    "relative_path": str(team_step.get("relative_path") or "")[:600],
                    "action_kind": str(team_step.get("action_kind") or ""),
                    "result": str(getattr(result, "response", "") or "")[:4000],
                    "verified": True,
                    "recorded_at": utc_now(),
                    "artifact_refs": [],
                }
            )
            try:
                self.work_ledger.update_worker_run_metrics(
                    run_id, metrics={EVIDENCE_KEY: evidence[-12:]}
                )
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

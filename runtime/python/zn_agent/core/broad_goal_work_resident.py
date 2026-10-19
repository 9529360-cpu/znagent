from __future__ import annotations

"""Rolling broad-Work execution on top of the existing Resident/Work/Body stack.

This is intentionally not a planner, scheduler, worker runtime, or second task
engine. A criterion-bound durable Work item may ask an external cognitive
resource for exactly one proposed next step. ZN validates that proposal,
materializes it as an existing child WorkItem, executes it through the existing
NativeActionIntent/Body lifecycle, freshly verifies the postcondition, and only
then accepts that child. The Root Work remains live for the next roll.
"""

import hashlib
import json
from pathlib import Path

from .action import NativeActionIntent
from .cognition import CognitiveIncrement
from .evidence_bound_work import EvidenceBoundSteerableWorkLedger
from .models import ExecutionPath, ResidentRunResult, utc_now
from .plan_verify_reroute import STRATEGY_LEDGER_KEY, StrategyLedger
from .user_browser_extension_resident import UserBrowserExtensionResidentRuntime
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .team_runner import FanIn, FanOut, SwitchCase, WorkflowRoute
from .work import title_for_work_task


def describe_rolling_route() -> WorkflowRoute:
    """Describe the rolling Broad Work step routing (AF-2 vocabulary).

    One cognition proposal switches on validity (valid -> accept, invalid
    -> prose fallback); an accepted proposal fans out to two durable
    effects (child WorkItem materialization + Body action cycle); the Body
    result switches on verification (verified -> roll forward, failed ->
    investigation); every branch joins back into the next pulse.
    """
    route = WorkflowRoute(
        name="broad_goal_rolling",
        edges=(
            SwitchCase(
                on="proposal_valid",
                cases=(
                    ("valid", "accept_proposal"),
                    ("invalid", "prose_fallback"),
                ),
                default="prose_fallback",
            ),
            FanOut(
                from_step="accept_proposal",
                to_steps=("materialize_child_item", "begin_body_action"),
            ),
            SwitchCase(
                on="verification",
                cases=(
                    ("verified", "roll_forward"),
                    ("failed", "investigation"),
                ),
                default="investigation",
            ),
            FanIn(
                from_steps=("roll_forward", "investigation", "prose_fallback"),
                to_step="next_pulse",
                require_all=False,
            ),
        ),
    )
    route.validate()
    return route


class BroadGoalWorkResidentRuntime(UserBrowserExtensionResidentRuntime):
    """Add a bounded rolling-decomposition bridge over durable Work."""

    _ROLLING_STEP_KEY = "broad_goal_rolling_step"
    _ROLLING_HISTORY_KEY = "broad_goal_rolling_history"
    _MAX_STEP_CONTENT = 200_000

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # Same SQLite truth and same WorkItem schema. This helper does not own a
        # scheduler or event loop; the Resident event remains the execution owner.
        self.work_ledger = EvidenceBoundSteerableWorkLedger(self)

    def _criterion_bound_root(self, event) -> WorkItem | None:
        thread_id = str(event.payload.get("work_thread_id") or "").strip()
        item_id = str(event.payload.get("work_item_id") or "").strip()
        if not thread_id or not item_id or not event.payload.get("workspace_path"):
            return None
        item = self.work_ledger.work_item_for_event(event.event_id)
        if item is None or item.work_item_id != item_id:
            return None
        if item.parent_work_item_id is not None or not item.acceptance_criteria:
            return None
        if item.plan_version != self.work_ledger.plan_version(thread_id):
            return None
        return item

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(
            event,
            impasse,
            required,
            deliberation,
        )
        root = self._criterion_bound_root(event)
        if root is None:
            return request

        completed = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
        ]
        history = [
            {
                "objective": item.objective[:300],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:500],
            }
            for item in completed[-6:]
        ]
        state = self.store.get_working_state()
        local_failure = str(state.data.get("local_failure") or "").strip()

        request.question = (
            "You are a bounded cognitive resource assisting one durable ZN Work. "
            "ZN owns the Work lifecycle, tools, permissions, execution, evidence and completion. "
            "Propose exactly ONE smallest useful next workspace step; do not claim the Root Work is complete. "
            "Return ONLY one JSON object with this shape: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"write_file",'
            '"path":"relative/path","content":"..."},"acceptance":{"kind":"text_equals",'
            '"path":"relative/path","expected_text":"..."}}}. '
            "The path must be relative to the attached workspace. The acceptance path and text must exactly "
            "match the proposed write. Do not emit shell commands or tool calls in this V1 step. "
            f"Root objective: {root.objective}. "
            f"Root acceptance criteria: {json.dumps(root.acceptance_criteria, ensure_ascii=False)}. "
            f"Already accepted child evidence: {json.dumps(history, ensure_ascii=False)}. "
            f"Latest real execution failure, if any: {local_failure or 'none'}."
        )
        request.context = {
            **dict(request.context or {}),
            "work_thread_id": root.work_thread_id,
            "root_work_item_id": root.work_item_id,
            "plan_version": root.plan_version,
            "completed_child_count": len(completed),
            "rolling_step_contract": "write_file/text_equals-v1",
        }
        # M-3: the strategy ledger guides the next proposal (what already
        # failed, why the loop switched). Layers above this one overwrite
        # the question (coding) or replace it for non-step rounds (M-5
        # claim, autonomous intake); the coding layer re-appends this
        # same block after its overwrite so it survives to cognition.
        ledger_block = self._strategy_ledger_prompt_block(event, root)
        if ledger_block:
            request.question = (
                str(request.question or "") + "\n\n" + ledger_block
            )
        return request

    # -- M-3: generic plan -> verify -> reroute loop ----------------------
    # The strategy ledger lives in durable working state, scoped to the
    # current plan: steering / replan starts a fresh ledger for the new
    # plan instead of carrying stale "do not repeat" guidance forward.

    def _strategy_ledger(
        self,
        state,
        *,
        root: WorkItem | None = None,
        plan_version: int | None = None,
        root_work_item_id: str | None = None,
    ) -> StrategyLedger:
        if root is not None:
            plan_version = root.plan_version
            root_work_item_id = root.work_item_id
        return StrategyLedger.from_state(
            state.data.get(STRATEGY_LEDGER_KEY),
            plan_version=plan_version,
            root_work_item_id=root_work_item_id,
        )

    def _save_strategy_ledger(self, state, ledger: StrategyLedger) -> None:
        state.data[STRATEGY_LEDGER_KEY] = ledger.to_dict()

    def _strategy_ledger_prompt_block(self, event, root: WorkItem) -> str:
        return self._strategy_ledger(
            self.store.get_working_state(), root=root
        ).prompt_block()

    @staticmethod
    def _strategy_for_rolling_step(
        rolling: dict, child: WorkItem | None = None
    ) -> str:
        objective = str(rolling.get("objective") or "").strip()
        kind = str(rolling.get("action_kind") or "").strip()
        target = str(
            rolling.get("relative_path")
            or rolling.get("requested_relative_path")
            or ""
        ).strip()
        if not kind and child is not None:
            # Write-file rolling steps carry no action_kind; infer the
            # step kind from the child's acceptance-criterion prefix.
            for criterion in child.acceptance_criteria or []:
                text = str(criterion or "").strip()
                if text.startswith("text_equals:"):
                    kind = "write_file"
                    break
                if text.startswith("command_exit:"):
                    kind = "run_python"
                    break
                if text.startswith("independent_python_verification:"):
                    kind = "verify_python"
                    break
        label = f"{kind or 'step'}:{target}" if target else (kind or "step")
        return f"{label} :: {objective}" if objective else label

    def _record_strategy_failure(
        self,
        event,
        state,
        *,
        strategy: str,
        failure: str,
        child_work_item_id: str = "",
        root: WorkItem | None = None,
    ) -> str | None:
        """Record one failed attempt; return the blocking reason, if any.

        ``None`` means the loop continues: the next cognition round gets
        the ledger block (tried strategies + diagnosed missing resource
        + the resource bundle to switch to). A non-``None`` reason means
        the budget is exhausted and the caller must terminal-fail with it
        instead of asking cognition again.
        """
        ledger = self._strategy_ledger(state, root=root)
        _decision, blocked = ledger.record_failure(
            strategy,
            failure,
            child_work_item_id=child_work_item_id,
        )
        self._save_strategy_ledger(state, ledger)
        self.store.save_working_state(state)
        return blocked

    def _record_strategy_success(
        self,
        state,
        *,
        root: WorkItem | None = None,
        plan_version: int | None = None,
        root_work_item_id: str | None = None,
    ) -> None:
        """One verified child: the loop made progress, reset the streak.

        Callers save working state themselves after this (roll-forward
        paths already do); no extra save here.
        """
        ledger = self._strategy_ledger(
            state,
            root=root,
            plan_version=plan_version,
            root_work_item_id=root_work_item_id,
        )
        if ledger.consecutive_failures or ledger.last_signature:
            ledger.record_success()
            self._save_strategy_ledger(state, ledger)

    def _record_rolling_failure_if_any(self, event, state) -> str | None:
        """Record the rolling step's execution failure, if this is one.

        Every Body-step failure funnels into native_investigation with
        ``local_failure`` set: a failed action (non-zero exit, timeout,
        error), a failed postcondition verification, and the verifier's
        fresh-read failure. This is the single recording point for all
        three, so the loop does not need one hook per failure shape.

        Attribution is strict: the rolling child must be blocked and its
        blocker must carry this ``local_failure`` text. A proposal
        rejection reuses the investigation stage, but its
        ``local_failure`` is about the rejected proposal, not this
        child -- the child's blocker still carries the child's own
        execution failure, so a rejection is never mis-recorded as a
        strategy attempt. Team specialist steps never set the rolling
        key, and the M-5 completion-report round has no rolling step by
        the time it runs, so neither is recorded here (the M-5 verdict
        rejections keep the M-5 budget, not this one).

        Returns the blocking reason when the reroute budget is
        exhausted, else ``None``.
        """
        failure = str(state.data.get("local_failure") or "").strip()
        if not failure:
            return None
        root = self._criterion_bound_root(event)
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if root is None or not isinstance(rolling, dict):
            return None
        if str(rolling.get("root_work_item_id") or "") != root.work_item_id:
            return None
        child_id = str(rolling.get("work_item_id") or "").strip()
        if not child_id:
            return None
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(
                    root.work_thread_id
                )
                if item.work_item_id == child_id
            ),
            None,
        )
        if (
            child is None
            or child.status != "blocked"
            or failure not in str(child.blocker or "")
        ):
            return None
        return self._record_strategy_failure(
            event,
            state,
            strategy=self._strategy_for_rolling_step(rolling, child),
            failure=failure,
            child_work_item_id=child_id,
            root=root,
        )

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        # M-3: record the rolling step's failure before the base
        # investigation runs, so the next cognition round gets the
        # strategy-ledger block and the budget is enforced before
        # another attempt. When the budget is exhausted, terminal-fail
        # here instead of investigating further.
        blocked = self._record_rolling_failure_if_any(event, state)
        if blocked is not None:
            return self._checkpoint_terminal_failure(
                event, state, reason=blocked
            )
        return super()._investigation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _cognition_integration_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        increment = CognitiveIncrement.from_dict(raw)
        proposal = self._parse_write_file_step(event, root, increment.content)
        if proposal is None:
            # Ordinary prose cognition keeps the existing bounded-increment
            # behavior. In particular, model planning text still cannot satisfy
            # Work acceptance because the evidence-bound ledger owns that gate.
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        self._accept_borrowed_increment(event, state, increment)
        identity = hashlib.sha256(
            f"{event.event_id}\0{increment.increment_id}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        child = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[f'text_equals: {proposal["relative_path"]}'],
        )
        # Deterministic identity closes the crash window between child materialization
        # and the durable action checkpoint: replaying integration reuses this row.
        self.work_ledger._save_item(child)

        intent = NativeActionIntent(
            intent_id=f"broad-step-{identity[:12]}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": proposal["absolute_path"],
                "content": proposal["content"],
                "append": False,
                "create_parents": False,
            },
            expected_outcome={
                "kind": "text_equals",
                "path": proposal["absolute_path"],
                "expected_text": proposal["content"],
            },
            reason=(
                "ZN validated one bounded external cognition proposal against the attached "
                "workspace and chose the concrete Body movement itself"
            ),
            source="resident_broad_goal_choice",
        )
        state.data[self._ROLLING_STEP_KEY] = {
            "work_item_id": child.work_item_id,
            "root_work_item_id": root.work_item_id,
            "work_thread_id": root.work_thread_id,
            "plan_version": root.plan_version,
            "relative_path": proposal["relative_path"],
            "objective": proposal["objective"],
            "increment_id": increment.increment_id,
        }
        self._begin_native_action_cycle(event, state, intent)
        state.next_action = "execute one ZN-owned rolling Work step through the Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        # Reuse the complete mature Body accounting/recovery path first. We only
        # intercept the semantic level above it: this is a verified child step,
        # not yet terminal Root Work completion.
        result = super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )
        return self._roll_forward_verified_child(event, state, result=result)

    def _resume_native_completion(self, event, state):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return super()._resume_native_completion(event, state)

        # If the process died after the mature Body completion checkpoint but
        # before Root roll-forward, recovery must accept/reconcile the child and
        # continue the same Root instead of publishing a terminal Root outcome.
        result = super()._resume_native_completion(event, state)
        if result is None or not result.success:
            return result
        return self._roll_forward_verified_child(event, state, result=result)

    def _roll_forward_verified_child(self, event, state, *, result):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return result

        child_id = str(rolling.get("work_item_id") or "").strip()
        thread_id = str(rolling.get("work_thread_id") or "").strip()
        plan_version = int(rolling.get("plan_version") or 0)
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(thread_id)
                if item.work_item_id == child_id
            ),
            None,
        )
        current_version = self.work_ledger.plan_version(thread_id)
        if child is None:
            raise RuntimeError("verified rolling Body step lost its durable WorkItem")
        if plan_version != current_version or child.plan_version != current_version:
            child.status = "superseded"
            child.blocker = "verified child result belongs to a stale Work plan"
            child.updated_at = utc_now()
            self.work_ledger._save_item(child)
            return result

        if child.status != "completed":
            child.status = "completed"
            child.result = str(result.response or rolling.get("relative_path") or "")
            child.blocker = None
            child.completed_at = utc_now()
            child.updated_at = child.completed_at
            self.work_ledger._save_item(child)

        raw_history = state.data.get(self._ROLLING_HISTORY_KEY)
        history = list(raw_history) if isinstance(raw_history, list) else []
        if not any(
            isinstance(item, dict) and item.get("work_item_id") == child.work_item_id
            for item in history
        ):
            history.append(
                {
                    "work_item_id": child.work_item_id,
                    "objective": child.objective,
                    "acceptance_criteria": list(child.acceptance_criteria),
                    "result": child.result,
                    "completed_at": child.completed_at,
                }
            )
        state.data[self._ROLLING_HISTORY_KEY] = history[-12:]
        # M-3: a verified child is real progress -- reset the reroute
        # streak so failures spread across a long Work never exhaust
        # the budget. The ledger entries stay for audit.
        self._record_strategy_success(
            state,
            plan_version=plan_version,
            root_work_item_id=str(rolling.get("root_work_item_id") or ""),
        )
        state.data.pop(self._ROLLING_STEP_KEY, None)
        state.data.pop("native_completion", None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_deliberation"
        state.next_action = "choose the next bounded Work step from fresh evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _accept_borrowed_increment(self, event, state, increment: CognitiveIncrement) -> None:
        external = state.data.get("external_cognition_result")
        external_data = external if isinstance(external, dict) else {}
        invocations = max(0, int(external_data.get("model_invocations") or 0))
        accepted_run = ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=True,
            response=increment.content,
            model_invocations=invocations,
            reason=f"accepted bounded rolling Work proposal from {increment.source}",
        )
        self.life.resolve_impasse(
            event,
            accepted_run,
            resolution_source=increment.source,
        )
        self.investigator.resolve_from_external(
            event.event_id,
            increment.content or "external cognition proposed one bounded Work step",
        )
        domains = self.kernel.self_model.integrate_external_learning(
            event.task,
            self._required_capabilities(event),
            quality=increment.quality,
            confidence=increment.confidence,
        )
        state.data["cognition_integration"] = {
            "increment_id": increment.increment_id,
            "accepted": True,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.data["integrated_learning_domains"] = list(domains)

    def _parse_write_file_step(
        self,
        event,
        root: WorkItem,
        content: str,
        *,
        reasons: list[str] | None = None,
        allow_missing_parent: bool = False,
    ) -> dict[str, str] | None:
        """Validate one bounded write_file proposal.

        ``reasons`` (when given) collects why a proposal was rejected, so a
        caller can feed the rejection back to the next cognition call
        instead of leaving the model in a zero-feedback loop. The checks
        themselves are unchanged: ``reasons`` is diagnostic-only and never
        grants execution. ``allow_missing_parent`` relaxes only the
        parent-directory existence check -- the workspace boundary check
        still applies, and the caller must create the parent (Body
        ``create_parents``) before the write executes.
        """

        def _reject(reason: str) -> None:
            if reasons is not None:
                reasons.append(reason)

        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            _reject("提案必须是恰好一个 zn_work_step JSON 对象")
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            _reject("zn_work_step 必须是对象")
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not objective or len(objective) > 600:
            _reject("objective 为空或超过 600 字符")
            return None
        if not isinstance(action, dict) or not isinstance(acceptance, dict):
            _reject("action 和 acceptance 都必须是对象")
            return None
        if str(action.get("kind") or "").strip() != "write_file":
            _reject("write_file 提案的 action.kind 必须是 write_file")
            return None
        if str(acceptance.get("kind") or "").strip() != "text_equals":
            _reject("write_file 提案的 acceptance.kind 必须是 text_equals")
            return None

        relative_path = str(action.get("path") or "").strip()
        acceptance_path = str(acceptance.get("path") or "").strip()
        body = action.get("content")
        expected = acceptance.get("expected_text")
        if not relative_path or relative_path != acceptance_path:
            _reject("action.path 与 acceptance.path 必须相同且非空")
            return None
        if (
            not isinstance(body, str)
            or not isinstance(expected, str)
            or body != expected
        ):
            _reject("action.content 与 acceptance.expected_text 必须相同")
            return None
        if len(body) > self._MAX_STEP_CONTENT:
            _reject("文件内容超过单步上限")
            return None

        rel = Path(relative_path)
        if (
            rel.is_absolute()
            or not rel.parts
            or any(part in {"", ".", ".."} for part in rel.parts)
        ):
            _reject(
                "路径必须是工作区内的相对路径，不能是绝对路径或包含 . / .."
            )
            return None
        workspace = Path(str(event.payload.get("workspace_path") or "")).expanduser()
        try:
            root_path = workspace.resolve(strict=True)
            candidate = root_path.joinpath(*rel.parts)
            if allow_missing_parent:
                # Missing parents are created by the Body (create_parents);
                # resolve(strict=False) still resolves symlinks in the
                # existing prefix, so the boundary check stays real.
                parent = candidate.parent.resolve(strict=False)
            else:
                parent = candidate.parent.resolve(strict=True)
            parent.relative_to(root_path)
            if candidate.exists():
                candidate.resolve(strict=True).relative_to(root_path)
        except (OSError, RuntimeError, ValueError):
            _reject("路径不在工作区内，或工作区不存在")
            return None

        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            _reject("计划版本已变化，提案已过期")
            return None
        return {
            "objective": objective,
            "relative_path": rel.as_posix(),
            "absolute_path": str(candidate),
            "content": body,
        }

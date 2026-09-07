from __future__ import annotations

"""Autonomous Root acceptance formation for broad attached-workspace goals.

This layer does not add a scheduler, worker runtime, or store. When one active
Root Work has an attached workspace but no acceptance criteria yet, ZN borrows
one bounded cognition increment to define observable success criteria, persists
them once into the existing WorkItem, and only then enters the mature
research/write/run/verify loop. Delegated work is coordinated by one composed
Resident-internal component; cognition cannot materialize WorkerRuns directly.
"""

from .action_authority import (
    ActionAuthorityContext,
    bind_worker_authority_arg,
    install_worker_authority_gate,
)
from .broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from .cognition import CognitiveIncrement
from .delegated_work_coordinator import DelegatedWorkCoordinator
from .delegation_admission import BoundedDelegationPlanner
from .models import utc_now
from .route_policy_intake import infer_thread_route_policy, merge_route_policy
from .steerable_work import WorkItem
from .structured_proposal import (
    looks_like_structured_payload,
    normalize_exact_json_payload,
    parse_exact_json_payload,
)


class BroadGoalAutonomousResidentRuntime(BroadGoalCompletionResidentRuntime):
    """Let ZN form the Root contract from a broad goal before executing it."""

    _ROOT_ACCEPTANCE_MARKER = "Before any execution, define the Root acceptance contract."
    _MIN_ROOT_CRITERIA = 2
    _MAX_ROOT_CRITERIA = 8
    _MAX_CRITERION_CHARS = 500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the one existing Body object and its recovery-aware concrete type;
        # only its act admission boundary is decorated.
        install_worker_authority_gate(self.body, resident=self)

    def _delegated_work_coordinator(self) -> DelegatedWorkCoordinator:
        coordinator = getattr(self, "_delegated_work_coordinator_instance", None)
        if coordinator is None:
            coordinator = DelegatedWorkCoordinator(self)
            self._delegated_work_coordinator_instance = coordinator
        return coordinator

    def _bind_work_route_policy(self, event, request):
        """Persist Work privacy policy before any external cognition.

        Delegated Work re-checks the same policy before building a
        WorkerContextPack. Broad Root acceptance is itself an external cognition
        call, though, so user policy must already belong to the durable WorkThread
        before that first call. Natural-language restrictions, data classification,
        and an explicit valid route-policy object are therefore merged into the
        same WorkThread policy. ModelRouter remains the sole owner of provider
        eligibility and fail-closed validation.
        """

        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        thread_id = str(payload.get("work_thread_id") or "").strip()
        if not thread_id:
            return request

        thread = self.work_ledger.get_thread(thread_id)
        persisted: object = None
        if thread is not None:
            persisted = thread.metadata.get("route_policy")

        inferred = infer_thread_route_policy(str(getattr(event, "task", "") or ""))
        classification = payload.get("data_classification")
        explicit = payload.get("route_policy")

        durable_overlay: object = dict(inferred or {})
        if classification is not None:
            durable_overlay = merge_route_policy(
                durable_overlay,
                {"data_classification": classification},
            )
        if isinstance(explicit, dict):
            durable_overlay = merge_route_policy(durable_overlay, explicit)

        if durable_overlay:
            if thread is None:
                raise RuntimeError("Work route policy lost its durable WorkThread")
            durable = merge_route_policy(persisted, durable_overlay)
            metadata = dict(thread.metadata)
            metadata["route_policy"] = durable
            thread.metadata = metadata
            thread.updated_at = utc_now()
            self.work_ledger._save_thread(thread)
            persisted = durable

        if explicit is not None and not isinstance(explicit, dict):
            # Preserve malformed explicit policy for ModelRouter to reject rather
            # than widening access or persisting an unusable policy value.
            route_policy: object = explicit
        else:
            route_policy = persisted

        if route_policy:
            request.context = {
                **dict(request.context or {}),
                "route_policy": route_policy,
            }
        return request

    @staticmethod
    def _root_requests_delegated_worker_sequence(root: WorkItem) -> bool:
        """Admit only a bounded plan the current flat-worker substrate can honor."""

        return BoundedDelegationPlanner.decide(root).admitted

    def _prepare_delegated_worker_request(self, event, root, request, completed):
        """Active product composition boundary for WorkerRun coordination."""

        return self._delegated_work_coordinator().prepare_request(
            event,
            root,
            request,
            completed,
        )

    def _begin_native_action_cycle(self, event, state, intent):
        """Bind transient WorkerRun authority to the concrete persisted action."""

        pending = state.data.get(self._DELEGATED_PENDING_KEY)
        if isinstance(pending, dict):
            worker_run_id = str(pending.get("worker_run_id") or "").strip()
            work_item_id = str(pending.get("work_item_id") or "").strip()
            expected_action = str(pending.get("expected_action") or "").strip()
            worker = self.work_ledger.worker_run(worker_run_id) if worker_run_id else None
            item = (
                self.work_ledger._work_item_by_id(worker.work_item_id)
                if worker is not None
                else None
            )
            if worker is None or item is None or not work_item_id or not expected_action:
                raise PermissionError("delegated action lost its durable WorkerRun authority context")
            if item.work_item_id != work_item_id or worker.work_item_id != item.work_item_id:
                raise PermissionError("delegated action WorkItem does not match its WorkerRun")
            if item.plan_version != worker.plan_version:
                raise PermissionError("delegated action WorkItem plan does not match its WorkerRun")
            current_plan = int(self.work_ledger.plan_version(item.work_thread_id))
            if worker.plan_version != current_plan:
                raise PermissionError("delegated action belongs to a stale Work plan")
            command = str(intent.args.get("command") or "")
            context = ActionAuthorityContext(
                work_thread_id=item.work_thread_id,
                work_item_id=worker.work_item_id,
                worker_run_id=worker.worker_run_id,
                plan_version=worker.plan_version,
                executor_kind=worker.executor_kind,
                expected_action=expected_action,
                tool_scope=tuple(worker.tool_scope),
                authority_scope=tuple(worker.authority_scope),
                workspace_root=str(event.payload.get("workspace_path") or "").strip() or None,
                allowed_command_sha256=(
                    ActionAuthorityContext.command_digest(command) if command else None
                ),
            )
            intent.args = bind_worker_authority_arg(intent.args, context)
        return super()._begin_native_action_cycle(event, state, intent)

    def _autonomous_root_candidate(self, event) -> WorkItem | None:
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        thread_id = str(payload.get("work_thread_id") or "").strip()
        item_id = str(payload.get("work_item_id") or "").strip()
        if not thread_id or not item_id or not payload.get("workspace_path"):
            return None
        root = self.work_ledger.work_item_for_event(event.event_id)
        run = self.work_ledger.get_run(event.event_id)
        if root is None or run is None:
            return None
        if (
            root.work_item_id != item_id
            or root.work_thread_id != thread_id
            or root.parent_work_item_id is not None
            or root.acceptance_criteria
            or run.thread_id != thread_id
            or run.ledger_state != "active"
        ):
            return None
        current_version = self.work_ledger.plan_version(thread_id)
        if (
            root.plan_version != current_version
            or self.work_ledger._run_plan_version(event.event_id) != current_version
        ):
            return None
        return root

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage == "external_completion" and self._autonomous_root_candidate(event) is not None:
            run = self._resume_external_completion(event, state)
            if not run.success:
                return run
            return self._promote_external_completion(event, state, run)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _external_cognition_step(self, event, state):
        intake = self._autonomous_root_candidate(event)
        run = super()._external_cognition_step(event, state)
        if intake is None or run is None or not run.success:
            return run
        return self._promote_external_completion(event, state, run)

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(event, impasse, required, deliberation)
        request = self._bind_work_route_policy(event, request)
        root = self._autonomous_root_candidate(event)
        if root is None:
            return request

        request.question = (
            "You are a bounded cognitive resource assisting one durable ZN Root Work. "
            "ZN owns lifecycle, tools, permissions, execution, evidence, steering, and completion. "
            f"{self._ROOT_ACCEPTANCE_MARKER} "
            "Return ONLY one JSON object shaped exactly as "
            '{"zn_root_acceptance":{"criteria":["observable criterion", "observable criterion"]}}. '
            f"Provide {self._MIN_ROOT_CRITERIA}-{self._MAX_ROOT_CRITERIA} concise criteria. "
            "Each criterion must describe user-visible or independently observable success, not an implementation "
            "recipe, model/tool action, or claim that work is already done. Cover the requested runnable core "
            "behavior and any durability/restart behavior that the user actually asked for. Respect explicit "
            "scope exclusions and simplicity constraints. Do not provide source code, shell commands, URLs, or "
            "tool calls in this response. ZN will decide research and execution steps only after this contract is "
            f"durably accepted. Root objective: {root.objective}"
        )
        request.context = {
            **dict(request.context or {}),
            "work_thread_id": root.work_thread_id,
            "root_work_item_id": root.work_item_id,
            "plan_version": root.plan_version,
            "root_acceptance_contract": "autonomous-observable-root-criteria-v1",
        }
        return request

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        raw = state.data.get("cognitive_increment")
        if isinstance(raw, dict):
            increment = CognitiveIncrement.from_dict(raw)
            normalized = normalize_exact_json_payload(increment.content)
            parsed = parse_exact_json_payload(increment.content)
            if normalized is not None and parsed is not None:
                if normalized != increment.content.strip():
                    normalized_raw = dict(raw)
                    normalized_raw["content"] = normalized
                    state.data["cognitive_increment"] = normalized_raw
                    state.data["structured_proposal_normalization"] = {
                        "increment_id": increment.increment_id,
                        "envelope": "single_json_fence",
                    }
                    raw = normalized_raw
                    increment = CognitiveIncrement.from_dict(raw)
            elif self._looks_like_any_structured_proposal(increment.content):
                return self._reject_malformed_structured_proposal(event, state, increment)

        root = self._autonomous_root_candidate(event)
        raw = state.data.get("cognitive_increment")
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        increment = CognitiveIncrement.from_dict(raw)
        criteria = self._parse_root_acceptance(increment.content)
        if criteria is None:
            failure = (
                "ZN rejected broad-goal intake because cognition did not return a bounded, observable Root "
                "acceptance contract"
            )
            state.data["local_failure"] = failure
            state.data.pop("cognitive_increment", None)
            state.data.pop("external_cognition_result", None)
            state.data.pop("cognition_integration", None)
            state.data.pop("cognition_request", None)
            state.data.pop("impasse_id", None)
            state.stage = "native_investigation"
            state.next_action = "re-form the broad Root acceptance contract before any execution"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        self._accept_borrowed_increment(event, state, increment)
        accepted = self.work_ledger.initialize_root_acceptance(
            event.event_id,
            acceptance_criteria=criteria,
        )
        state.data["autonomous_root_acceptance"] = {
            "work_item_id": accepted.work_item_id,
            "plan_version": accepted.plan_version,
            "criteria": list(accepted.acceptance_criteria),
            "source": increment.source,
            "accepted_at": utc_now(),
        }
        state.data.pop("local_failure", None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_deliberation"
        state.next_action = "choose the first bounded Work step under the accepted Root contract"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    @staticmethod
    def _looks_like_any_structured_proposal(content: str) -> bool:
        return looks_like_structured_payload(content, top_level_key="zn_work_step") or (
            looks_like_structured_payload(content, top_level_key="zn_root_acceptance")
        )

    def _reject_malformed_structured_proposal(self, event, state, increment: CognitiveIncrement):
        failure = (
            "ZN rejected a structured cognition proposal because its exact JSON envelope was malformed, "
            "ambiguous, duplicated, or contained multiple proposal envelopes"
        )
        state.data["local_failure"] = failure
        state.data["structured_proposal_rejection"] = {
            "increment_id": increment.increment_id,
            "reason": failure,
        }
        rejection_hook = getattr(self, "_on_malformed_structured_proposal_rejection", None)
        if callable(rejection_hook):
            rejection_hook(event, state, increment, failure)
        investigation = self.investigator.current(event.event_id)
        if investigation is not None:
            evidence = list(investigation.evidence)
            if failure not in evidence:
                evidence.append(failure)
            investigation.status = "open"
            investigation.resolution = None
            investigation.unresolved = failure
            investigation.next_probe = None
            investigation.updated_at = utc_now()
            investigation.evidence = tuple(evidence[-64:])
            self.investigator._save(investigation)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_investigation"
        state.next_action = "repair the rejected bounded structured proposal"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _parse_root_acceptance(self, content: str) -> list[str] | None:
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_root_acceptance"}:
            return None
        contract = raw.get("zn_root_acceptance")
        if not isinstance(contract, dict) or set(contract) != {"criteria"}:
            return None
        raw_criteria = contract.get("criteria")
        if not isinstance(raw_criteria, list):
            return None
        if not self._MIN_ROOT_CRITERIA <= len(raw_criteria) <= self._MAX_ROOT_CRITERIA:
            return None

        criteria: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_criteria:
            if not isinstance(raw_item, str):
                return None
            item = " ".join(raw_item.strip().split())
            if not item or len(item) > self._MAX_CRITERION_CHARS:
                return None
            key = item.casefold()
            if key in seen:
                return None
            seen.add(key)
            criteria.append(item)
        return criteria

from __future__ import annotations

"""Active product resident ownership for compiled-capability crash recovery."""

from .focused_modern_text_resident import FocusedModernTextResidentRuntime
from .models import CapabilityResult, CognitionRequest, ExecutionPath, ResidentRunResult, utc_now
from .resident_accounting import ResidentAccountingJournal


class CapabilityRecoveryResidentRuntime(FocusedModernTextResidentRuntime):
    """Keep native and external completion inside one recoverable Work lifecycle.

    Compiled capabilities are opaque program code and may mutate the outside
    world. The active product therefore gives every capability execution a
    durable attempt boundary. Native memory/investigation completion and bounded
    external cognition also checkpoint their semantic result before cumulative
    accounting so restart cannot duplicate learning or provider work.
    """

    _CAPABILITY_EXECUTION_KEY = "capability_execution"
    _ACCOUNTING_VERSION = 1
    _RESIDENT_COMPLETION_ACCOUNTING_KEY = "resident_completion_accounting"
    _INVESTIGATION_COMPLETION_ACCOUNTING_KEY = "investigation_completion_accounting"
    _EXTERNAL_COMPLETION_KEY = "external_completion"
    _EXTERNAL_COMPLETION_ACCOUNTING_KEY = "external_completion_accounting"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.capabilities.bind_store(self.store)
        self.resident_accounting = ResidentAccountingJournal(self.store)

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage == "external_completion":
            return self._resume_external_completion(event, state)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _orient_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        # Capability execution owns a durable fact before normal orientation can
        # reconsider memory or matching. ``started`` means outside-world effect
        # may be uncertain; an ``observed`` result is sufficient to resume the
        # known success/failure without loading or executing the code again.
        raw_execution = state.data.get(self._CAPABILITY_EXECUTION_KEY)
        if isinstance(raw_execution, dict):
            status = str(raw_execution.get("status") or "").strip().lower()
            replay_safe = raw_execution.get("replay_safe") is True
            attempt_id = str(raw_execution.get("attempt_id") or "").strip()
            capability_name = str(raw_execution.get("capability_name") or "").strip()
            raw_result = raw_execution.get("result")
            if status == "observed" and attempt_id and capability_name:
                if not isinstance(raw_result, dict):
                    raise RuntimeError("observed capability result checkpoint is incomplete")
                if raw_result.get("success") is True:
                    return self._resume_observed_capability_success(
                        event,
                        state,
                        raw_execution,
                    )
                if raw_result.get("success") is False:
                    return self._resume_observed_capability_failure(
                        event,
                        state,
                        raw_execution,
                        thought=thought,
                    )
                raise RuntimeError("observed capability result checkpoint is malformed")
            if status == "started" and attempt_id and capability_name and not replay_safe:
                return self._begin_capability_recovery(
                    event,
                    state,
                    raw_execution,
                    thought=thought,
                )

        required = self._required_capabilities(event)
        memory_checked = bool(event.payload.get("allow_memory", True))
        state.data["memory_checked"] = memory_checked
        memory_match = self.memory.recall(event.task) if memory_checked else None
        if memory_match is not None:
            response = self._render_memory_value(memory_match.value)
            reason = f"recalled structured fact '{memory_match.key}'"
            domains = self.kernel.self_model.infer_domains(event.task, required)
            completion = {
                "execution_path": ExecutionPath.MEMORY.value,
                "success": True,
                "response": response,
                "model_invocations": 0,
                "reason": reason,
            }
            state.stage = "resident_completion"
            state.next_action = "publish terminal EventOutcome"
            state.data["resident_completion"] = completion
            state.data[self._RESIDENT_COMPLETION_ACCOUNTING_KEY] = {
                "version": self._ACCOUNTING_VERSION,
                "kind": "memory_success",
                "domains": list(domains),
                "quality": 1.0,
            }
            # Semantic result first. Accounting is derived from this durable fact
            # and can therefore be retried idempotently after any later crash.
            self.store.save_working_state(state)
            self._apply_resident_completion_accounting(event, state)
            return self._resident_completion_result(event, completion)

        resolved = self.capabilities.resolve(event)
        state.data["local_capability_checked"] = True
        if resolved is not None:
            capability, confidence = resolved
            state.stage = "native_capability"
            state.next_action = capability.name
            state.data["capability_match"] = confidence
            self.store.save_working_state(state)
            try:
                local_result = capability.execute(event, state)
            except Exception as exc:
                local_result = CapabilityResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )

            if (
                not local_result.success
                and isinstance(local_result.data, dict)
                and bool(local_result.data.get("side_effect_uncertain"))
            ):
                return self._begin_capability_recovery(
                    event,
                    state,
                    state.data.get(self._CAPABILITY_EXECUTION_KEY),
                    result=local_result,
                    thought=thought,
                )

            if local_result.success:
                return self._complete_observed_capability_success(
                    event,
                    state,
                    capability_name=capability.name,
                    local_result=local_result,
                    confidence=confidence,
                )

            return self._continue_after_observed_capability_failure(
                event,
                state,
                local_result=local_result,
                thought=thought,
            )

        return self._continue_to_native_investigation(event, state, thought=thought)

    def _resume_resident_completion(self, event, state):
        result = super()._resume_resident_completion(event, state)
        if result.success:
            self._apply_resident_completion_accounting(event, state)
        return result

    def _apply_resident_completion_accounting(self, event, state) -> None:
        raw = state.data.get(self._RESIDENT_COMPLETION_ACCOUNTING_KEY)
        # Checkpoints created before this accounting descriptor already ran the
        # old eager accounting path. Treat absence as already-accounted so an
        # upgrade cannot duplicate historical evidence.
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise RuntimeError("resident completion accounting checkpoint is malformed")
        if int(raw.get("version") or 0) != self._ACCOUNTING_VERSION:
            raise RuntimeError("resident completion accounting version is unsupported")
        if str(raw.get("kind") or "") != "memory_success":
            raise RuntimeError("resident completion accounting kind is unsupported")
        self.resident_accounting.record_memory_success(
            event_id=event.event_id,
            domains=tuple(raw.get("domains") or ()),
            quality=float(raw.get("quality", 1.0)),
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
        local_failure = str(state.data.get("local_failure") or "").strip() or None
        investigation = self.investigator.investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        state.data["native_investigation"] = self._investigation_data(investigation.state)
        self._merge_investigation_into_thought(thought, investigation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        if investigation.resolved:
            domains = self.kernel.self_model.infer_domains(
                event.task,
                self._required_capabilities(event),
            )
            completion = {
                "execution_path": ExecutionPath.INVESTIGATION.value,
                "success": True,
                "response": str(investigation.response or ""),
                "model_invocations": 0,
                "reason": "resolved from ZN's own body and environment evidence",
            }
            state.stage = "investigation_completion"
            state.next_action = "publish terminal EventOutcome"
            state.data["native_domains"] = list(domains)
            state.data["investigation_completion"] = completion
            state.data[self._INVESTIGATION_COMPLETION_ACCOUNTING_KEY] = {
                "version": self._ACCOUNTING_VERSION,
                "kind": "native_investigation_success",
                "domains": list(domains),
                "quality": 0.95,
            }
            self.store.save_working_state(state)
            self._apply_investigation_completion_accounting(event, state)
            return self._investigation_completion_result(event, completion)

        if investigation.can_continue:
            state.stage = "native_investigation"
            state.next_action = f"run native probe {investigation.state.next_probe}"
            self.store.save_working_state(state)
            return None

        state.stage = "native_deliberation"
        state.next_action = "integrate native evidence and identify remaining gap"
        self.store.save_working_state(state)
        return None

    def _resume_investigation_completion(self, event, state):
        result = super()._resume_investigation_completion(event, state)
        if result.success:
            self._apply_investigation_completion_accounting(event, state)
        return result

    def _apply_investigation_completion_accounting(self, event, state) -> None:
        raw = state.data.get(self._INVESTIGATION_COMPLETION_ACCOUNTING_KEY)
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise RuntimeError("investigation completion accounting checkpoint is malformed")
        if int(raw.get("version") or 0) != self._ACCOUNTING_VERSION:
            raise RuntimeError("investigation completion accounting version is unsupported")
        if str(raw.get("kind") or "") != "native_investigation_success":
            raise RuntimeError("investigation completion accounting kind is unsupported")
        self.resident_accounting.record_native_investigation_success(
            event_id=event.event_id,
            domains=tuple(raw.get("domains") or ()),
            quality=float(raw.get("quality", 0.95)),
        )

    def _external_cognition_step(self, event, state):
        raw = state.data.get("cognition_request")
        if not isinstance(raw, dict):
            raise RuntimeError("external cognition stage has no cognition request")
        request_id = str(raw.get("request_id") or "").strip()
        if not request_id:
            raise RuntimeError("external cognition request has no durable request id")
        required = tuple(raw.get("required_capabilities") or self._required_capabilities(event))
        cognition = CognitionRequest(
            request_id=request_id,
            impasse_id=str(raw.get("impasse_id") or state.data.get("impasse_id") or ""),
            event_id=event.event_id,
            question=str(raw.get("question") or event.task),
            required_capabilities=required,
            context=dict(raw.get("context") or {}),
            created_at=str(raw.get("created_at") or "") or utc_now(),
        )
        budget = state.data.get("cognitive_budget")
        max_calls = 1
        decision_reason = "native investigation exhausted its current probes"
        if isinstance(budget, dict):
            try:
                max_calls = max(1, int(budget.get("max_model_calls") or 1))
            except (TypeError, ValueError):
                max_calls = 1
            decision_reason = str(budget.get("reason") or decision_reason)

        goal_id = f"goal-{cognition.request_id}"
        kernel_result = self.kernel.run_goal(
            cognition.question,
            required_capabilities=cognition.required_capabilities,
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "impasse_id": cognition.impasse_id,
                "cognition_request": {
                    "request_id": cognition.request_id,
                    "context": cognition.context,
                },
            },
            max_attempts_override=max_calls,
            goal_id=goal_id,
        )
        invocations = sum(
            1
            for experience in kernel_result.experiences
            if experience.metrics.get("model_invoked", True) is not False
        )
        prompt_tokens, completion_tokens = self._sum_tokens(kernel_result)
        success = bool(kernel_result.assessment.success)
        reason = decision_reason
        if not success and kernel_result.worker_result.error:
            reason = kernel_result.worker_result.error
        domains = self.kernel.self_model.infer_domains(
            event.task,
            self._required_capabilities(event),
        )
        learning_sample = (
            max(0.0, min(1.0, float(kernel_result.assessment.quality)))
            * max(0.0, min(1.0, float(kernel_result.assessment.confidence)))
            if success
            else 0.0
        )
        completion = {
            "execution_path": ExecutionPath.MODEL.value,
            "success": success,
            "response": kernel_result.worker_result.response,
            "model_invocations": invocations,
            "reason": reason,
            "goal_id": kernel_result.goal.goal_id,
            "route_id": kernel_result.route.route_id,
        }
        state.current_goal_id = kernel_result.goal.goal_id
        state.stage = "external_completion"
        state.next_action = "publish terminal EventOutcome"
        state.data[self._EXTERNAL_COMPLETION_KEY] = completion
        state.data[self._EXTERNAL_COMPLETION_ACCOUNTING_KEY] = {
            "version": self._ACCOUNTING_VERSION,
            "kind": "external_completion",
            "domains": list(domains),
            "success": success,
            "learning_sample": learning_sample,
            "model_invocations": invocations,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "route_id": kernel_result.route.route_id,
        }
        # No resident metrics, learning or life resolution is allowed before this
        # recoverable semantic completion checkpoint is durable.
        self.store.save_working_state(state)
        run = self._external_completion_result(event, completion)
        run.kernel_result = kernel_result
        self._apply_external_completion(event, state, run)
        return run

    def _resume_external_completion(self, event, state):
        raw = state.data.get(self._EXTERNAL_COMPLETION_KEY)
        if not isinstance(raw, dict):
            raise RuntimeError("durable external completion checkpoint is incomplete")
        try:
            run = self._external_completion_result(event, raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("durable external completion checkpoint is malformed") from exc
        goal_id = str(raw.get("goal_id") or state.current_goal_id or "").strip()
        if goal_id:
            run.kernel_result = self.kernel.load_goal_result(goal_id)
        self._apply_external_completion(event, state, run)
        return run

    @staticmethod
    def _external_completion_result(event, raw) -> ResidentRunResult:
        if raw.get("success") not in {True, False}:
            raise ValueError("external completion checkpoint must record boolean success")
        execution_path = ExecutionPath(str(raw.get("execution_path") or ""))
        if execution_path is not ExecutionPath.MODEL:
            raise ValueError("external completion checkpoint must use model path")
        model_invocations = raw.get("model_invocations")
        if isinstance(model_invocations, bool) or int(model_invocations) < 0:
            raise ValueError("external completion checkpoint has invalid model invocation count")
        return ResidentRunResult(
            event=event,
            execution_path=execution_path,
            success=bool(raw.get("success")),
            response=raw.get("response"),
            model_invocations=int(model_invocations),
            reason=str(raw.get("reason") or ""),
        )

    def _apply_external_completion(self, event, state, run: ResidentRunResult) -> None:
        raw = state.data.get(self._EXTERNAL_COMPLETION_ACCOUNTING_KEY)
        if not isinstance(raw, dict):
            raise RuntimeError("external completion accounting checkpoint is incomplete")
        if int(raw.get("version") or 0) != self._ACCOUNTING_VERSION:
            raise RuntimeError("external completion accounting version is unsupported")
        if str(raw.get("kind") or "") != "external_completion":
            raise RuntimeError("external completion accounting kind is unsupported")
        success = raw.get("success")
        if success not in {True, False} or bool(success) != bool(run.success):
            raise RuntimeError("external completion accounting disagrees with semantic result")
        domains = self.resident_accounting.record_external_completion(
            event_id=event.event_id,
            domains=tuple(raw.get("domains") or ()),
            success=bool(success),
            learning_sample=float(raw.get("learning_sample", 0.0)),
            model_invocations=int(raw.get("model_invocations") or 0),
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
        )
        if run.success:
            route_id = str(raw.get("route_id") or "external").strip() or "external"
            self.life.resolve_impasse(
                event,
                run,
                resolution_source=f"external:{route_id}",
            )
            investigation = self.investigator.current(event.event_id)
            if investigation is not None and not str(investigation.status).startswith("resolved"):
                self.investigator.resolve_from_external(
                    event.event_id,
                    run.response or "external cognition resolved the remaining gap",
                )
            state.data["integrated_learning_domains"] = list(domains)
            self.store.save_working_state(state)
        else:
            self.life.mark_impasse_unresolved(event, run.reason)

    def _resume_observed_capability_success(
        self,
        event,
        state,
        execution,
    ):
        raw_result = execution.get("result")
        if not isinstance(raw_result, dict) or raw_result.get("success") is not True:
            raise RuntimeError("observed capability success checkpoint is malformed")
        local_result = CapabilityResult(
            success=True,
            response=str(raw_result.get("response") or ""),
            data=dict(raw_result.get("data") or {}),
            error=None,
            verification_passed=raw_result.get("verification_passed"),
        )
        capability_name = str(execution.get("capability_name") or "").strip()
        if not capability_name:
            raise RuntimeError("observed capability success has no capability name")
        try:
            confidence = float(state.data.get("capability_match", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        return self._complete_observed_capability_success(
            event,
            state,
            capability_name=capability_name,
            local_result=local_result,
            confidence=confidence,
        )

    def _resume_observed_capability_failure(
        self,
        event,
        state,
        execution,
        *,
        thought=None,
    ):
        raw_result = execution.get("result")
        if not isinstance(raw_result, dict) or raw_result.get("success") is not False:
            raise RuntimeError("observed capability failure checkpoint is malformed")
        local_result = CapabilityResult(
            success=False,
            response=str(raw_result.get("response") or ""),
            data=dict(raw_result.get("data") or {}),
            error=(
                str(raw_result.get("error"))
                if raw_result.get("error") is not None
                else None
            ),
            verification_passed=raw_result.get("verification_passed"),
        )
        return self._continue_after_observed_capability_failure(
            event,
            state,
            local_result=local_result,
            thought=thought,
        )

    def _complete_observed_capability_success(
        self,
        event,
        state,
        *,
        capability_name: str,
        local_result: CapabilityResult,
        confidence: float,
    ):
        required = self._required_capabilities(event)
        domains = self.resident_accounting.record_native_capability_success(
            event_id=event.event_id,
            task=event.task,
            required_capabilities=required,
            quality=max(0.5, min(1.0, float(confidence))),
        )
        completion = {
            "execution_path": ExecutionPath.CAPABILITY.value,
            "success": True,
            "response": local_result.response,
            "model_invocations": 0,
            "capability_name": capability_name,
            "reason": "resolved by compiled local capability",
        }
        state.stage = "resident_completion"
        state.next_action = "publish terminal EventOutcome"
        state.blocked_by = None
        state.data["native_domains"] = list(domains)
        state.data["resident_completion"] = completion
        self.store.save_working_state(state)
        return self._resident_completion_result(event, completion)

    def _continue_after_observed_capability_failure(
        self,
        event,
        state,
        *,
        local_result: CapabilityResult,
        thought=None,
    ):
        if (
            isinstance(local_result.data, dict)
            and bool(local_result.data.get("side_effect_uncertain"))
        ):
            raise RuntimeError(
                "uncertain capability effect cannot be converted into failure evidence"
            )
        required = self._required_capabilities(event)
        self.resident_accounting.record_native_capability_failure(
            event_id=event.event_id,
            task=event.task,
            required_capabilities=required,
        )
        state.data["local_failure"] = local_result.error or "local capability failed"
        return self._continue_to_native_investigation(event, state, thought=thought)

    def _continue_to_native_investigation(self, event, state, *, thought=None):
        state.stage = "native_investigation"
        state.next_action = "select the next native probe"
        state.blocked_by = None
        if thought is not None:
            action = "inspect concrete local state before declaring an impasse"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = f"{thought.reason}; orientation found no terminal native answer"
            self._persist_enriched_thought(thought)
        self.store.save_working_state(state)
        return None

    def _begin_capability_recovery(
        self,
        event,
        state,
        raw_execution,
        *,
        result=None,
        thought=None,
    ):
        execution = dict(raw_execution) if isinstance(raw_execution, dict) else {}
        result_data = result.data if result is not None and isinstance(result.data, dict) else {}
        attempt_id = str(
            execution.get("attempt_id")
            or result_data.get("side_effect_attempt_id")
            or ""
        ).strip()
        capability_name = str(execution.get("capability_name") or "").strip()
        recovery = {
            "status": "uncertain",
            "kind": "capability",
            "capability_name": capability_name,
            "attempt_id": attempt_id,
            "replay_blocked": True,
            "signature": str(
                result_data.get("side_effect_signature")
                or execution.get("signature_hash")
                or ""
            )[:16],
            "decision": "user_decision_required",
        }
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.data.pop("local_failure", None)
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "await explicit recovery or cancellation decision; do not replay the compiled capability"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            message = (
                "compiled capability execution crossed a durable non-replayable boundary; "
                "its outside-world effect is uncertain"
            )
            if message not in thought.unknown:
                thought.unknown = (*thought.unknown, message)
            thought.reason = (
                f"{thought.reason}; interrupted compiled code is recovery state rather than "
                "failure evidence, so replay remains blocked"
            )
            self._persist_enriched_thought(thought)
        return None

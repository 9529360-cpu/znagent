from __future__ import annotations

"""Active product resident ownership for compiled-capability crash recovery."""

from .focused_modern_text_resident import FocusedModernTextResidentRuntime
from .models import CapabilityResult, ExecutionPath


class CapabilityRecoveryResidentRuntime(FocusedModernTextResidentRuntime):
    """Keep compiled procedures inside the same non-replayable Work lifecycle.

    Compiled capabilities are opaque program code and may mutate the outside
    world. The active product therefore gives every capability execution a
    durable attempt boundary. Capabilities are non-replayable by default; only
    an explicit ``replay_safe`` contract permits retry after interruption.
    """

    _CAPABILITY_EXECUTION_KEY = "capability_execution"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.capabilities.bind_store(self.store)

    def _orient_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        # An interrupted non-replayable capability is outside-world uncertainty,
        # not evidence that the capability failed. Convert the durable ``started``
        # checkpoint into the same Work recovery state used by guarded Body
        # effects before resolve/execute can run again.
        raw_execution = state.data.get(self._CAPABILITY_EXECUTION_KEY)
        if isinstance(raw_execution, dict):
            status = str(raw_execution.get("status") or "").strip().lower()
            replay_safe = raw_execution.get("replay_safe") is True
            attempt_id = str(raw_execution.get("attempt_id") or "").strip()
            capability_name = str(raw_execution.get("capability_name") or "").strip()
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
            self.kernel.self_model.observe_knowledge_use(
                event.task,
                required,
                quality=1.0,
            )
            self.store.record_runtime_task(model_invocations=0)
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
            self.store.save_working_state(state)
            return self._resident_completion_result(event, completion)

        local_failure: str | None = None
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
                domains = self.kernel.self_model.observe_native_outcome(
                    event.task,
                    required,
                    success=True,
                    quality=max(0.5, min(1.0, float(confidence))),
                )
                completion = {
                    "execution_path": ExecutionPath.CAPABILITY.value,
                    "success": True,
                    "response": local_result.response,
                    "model_invocations": 0,
                    "capability_name": capability.name,
                    "reason": "resolved by compiled local capability",
                }
                state.stage = "resident_completion"
                state.next_action = "publish terminal EventOutcome"
                state.blocked_by = None
                state.data["native_domains"] = list(domains)
                state.data["resident_completion"] = completion
                self.store.record_runtime_task(model_invocations=0)
                self.store.save_working_state(state)
                return self._resident_completion_result(event, completion)

            self.kernel.self_model.observe_native_outcome(
                event.task,
                required,
                success=False,
            )
            local_failure = local_result.error or "local capability failed"
            state.data["local_failure"] = local_failure

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

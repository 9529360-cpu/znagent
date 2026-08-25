from __future__ import annotations

"""Bind pointer-click completion to one explicit, independently verified effect.

The lower pointer-click resident proves only that a target-local visual region
changed after one bounded click. This layer owns the event-level completion
boundary: that evidence may close only an event explicitly typed as an effect
probe whose whole completion scope is that same verified effect.
"""

from typing import Any

from .action import NativeActionIntent
from .models import ExecutionPath, ResidentRunResult
from .pointer_click_resident import VerifiedPointerClickResidentRuntime


class EffectScopedPointerClickResidentRuntime(VerifiedPointerClickResidentRuntime):
    """Active resident that never upgrades a local click effect into broad success."""

    _POINTER_CLICK_EVENT_KIND = "effect_probe"
    _POINTER_CLICK_COMPLETION_SCOPE_KIND = "verified_effect"

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        contract, error = super()._pointer_click_contract(event, intent)
        if error:
            return contract, error
        assert contract is not None

        event_kind = str(event.kind or "").strip().lower()
        if event_kind != self._POINTER_CLICK_EVENT_KIND:
            return None, (
                "pointer_click is currently permitted only for effect_probe events; "
                "visual_region_changed cannot prove a broader user task outcome"
            )

        completion_scope, scope_error = self._pointer_click_completion_scope(event)
        if scope_error:
            return None, scope_error
        assert completion_scope is not None
        return {**contract, "completion_scope": completion_scope}, None

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult | None:
        if intent.kind != "pointer_click":
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        completion_scope, scope_error = self._pointer_click_completion_scope(event)
        if scope_error or completion_scope is None:
            failure = (
                "pointer click completion scope became invalid after input; "
                "refusing to convert the verified local effect into event success: "
                + str(scope_error or "unknown completion-scope error")
            )
            state.data["local_failure"] = failure
            self._record_failed_action(
                event,
                state,
                intent,
                source="verification",
                failure=failure,
            )
            state.stage = "native_investigation"
            state.next_action = "investigate completion-scope drift without replaying pointer input"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        state.stage = "complete"
        state.next_action = None
        state.data["native_completion_scope"] = dict(completion_scope)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        self.store.record_runtime_task(model_invocations=0)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=response,
            model_invocations=0,
            reason=(
                "ZN completed this effect_probe only because its explicit completion_scope "
                "binds the whole event to the independently verified visual_region_changed "
                "effect; no broader user-task semantic or native ability was credited"
            ),
        )

    def _pointer_click_completion_scope(
        self,
        event,
    ) -> tuple[dict[str, str] | None, str | None]:
        raw = event.payload.get("completion_scope")
        if not isinstance(raw, dict):
            return None, (
                "effect_probe pointer_click requires an explicit completion_scope with "
                "kind=verified_effect and effect_kind=visual_region_changed"
            )

        unknown = sorted(
            str(key)
            for key in raw
            if key not in {"kind", "effect_kind"}
        )
        if unknown:
            return None, (
                "pointer_click completion_scope contains unsupported authority fields: "
                + ", ".join(unknown)
            )

        scope_kind = str(raw.get("kind") or "").strip().lower()
        effect_kind = str(raw.get("effect_kind") or "").strip().lower()
        if scope_kind != self._POINTER_CLICK_COMPLETION_SCOPE_KIND:
            return None, (
                "pointer_click completion_scope must use kind=verified_effect; broader "
                "semantic completion is not yet independently verifiable"
            )
        if effect_kind != self._POINTER_CLICK_POSTCONDITION_KIND:
            return None, (
                "pointer_click completion_scope must bind exactly to "
                "effect_kind=visual_region_changed"
            )

        return {
            "kind": self._POINTER_CLICK_COMPLETION_SCOPE_KIND,
            "effect_kind": self._POINTER_CLICK_POSTCONDITION_KIND,
        }, None

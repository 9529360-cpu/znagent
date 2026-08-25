from __future__ import annotations

"""Add one narrow, read-only verified UI-state completion scope to pointer clicks."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from .models import ExecutionPath, ResidentRunResult
from .pointer_click_completion_resident import EffectScopedPointerClickResidentRuntime
from .pointer_click_resident import VerifiedPointerClickResidentRuntime


class SemanticPointerClickResidentRuntime(EffectScopedPointerClickResidentRuntime):
    """Complete only a typed foreground-window state proven by fresh OS evidence."""

    _UI_EVENT_KIND = "ui_state_transition"
    _UI_SCOPE_KIND = "foreground_window_matches"
    _SEMANTIC_PRECONDITION_KEY = "native_pointer_click_semantic_precondition"
    _SEMANTIC_VERIFICATION_KEY = "native_pointer_click_semantic_verification"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.foreground_window = NativeForegroundWindowSense()

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw_scope = event.payload.get("completion_scope")
        scope_kind = (
            str(raw_scope.get("kind") or "").strip().lower()
            if isinstance(raw_scope, dict)
            else ""
        )
        if scope_kind != self._UI_SCOPE_KIND:
            return super()._pointer_click_contract(event, intent)

        contract, error = VerifiedPointerClickResidentRuntime._pointer_click_contract(
            self,
            event,
            intent,
        )
        if error:
            return contract, error
        assert contract is not None

        scope, scope_error = self._ui_completion_scope(event)
        if scope_error:
            return None, scope_error
        assert scope is not None
        event_kind = str(event.kind or "").strip().lower()
        if event_kind != self._UI_EVENT_KIND:
            return None, (
                "foreground_window_matches pointer_click completion is permitted only for "
                "ui_state_transition events"
            )
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, (
                "ui_state_transition pointer_click requires the resident-owned foreground "
                "window Sense before any pointer movement or input"
            )
        return {
            **contract,
            "completion_scope": scope,
            "completion_event_kind": event_kind,
        }, None

    def _pointer_click_action_step(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ):
        contract, error = self._pointer_click_contract(event, intent)
        if error:
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                error,
                thought=thought,
            )
        assert contract is not None
        scope = contract.get("completion_scope")
        prepared = state.data.get(self._POINTER_CLICK_PRECONDITION_KEY)
        semantic_preflight_due = not isinstance(prepared, dict)
        if (
            isinstance(scope, dict)
            and scope.get("kind") == self._UI_SCOPE_KIND
            and semantic_preflight_due
        ):
            observed, probe_error = self._probe_foreground_window()
            if observed is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh foreground-window preflight was unavailable: "
                    + str(probe_error or "unknown foreground-window error"),
                    thought=thought,
                )
            state.data[self._SEMANTIC_PRECONDITION_KEY] = asdict(observed)
            if self._foreground_window_matches(observed, scope):
                state.data[self._SEMANTIC_VERIFICATION_KEY] = self._verification(
                    observed,
                    scope,
                    verified=True,
                    before_input=True,
                )
                return self._complete_ui_scope(
                    event,
                    state,
                    scope,
                    response=self._response(observed),
                    reason=(
                        "ZN completed this ui_state_transition because fresh foreground-window "
                        "evidence already matched the exact structured completion scope; no "
                        "pointer input was sent"
                    ),
                )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)

        return super()._pointer_click_action_step(
            event,
            state,
            intent,
            thought=thought,
        )

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult | None:
        raw_scope = event.payload.get("completion_scope")
        if (
            intent.kind != "pointer_click"
            or not isinstance(raw_scope, dict)
            or str(raw_scope.get("kind") or "").strip().lower() != self._UI_SCOPE_KIND
        ):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        scope, scope_error = self._ui_completion_scope(event)
        if scope_error or scope is None:
            return self._fail_ui_completion(
                event,
                state,
                intent,
                str(scope_error or "unknown completion-scope error"),
            )
        admitted = state.data.get("native_verification")
        admitted_scope = admitted.get("completion_scope") if isinstance(admitted, dict) else None
        admitted_kind = (
            str(admitted.get("completion_event_kind") or "").strip().lower()
            if isinstance(admitted, dict)
            else ""
        )
        if (
            not isinstance(admitted_scope, dict)
            or dict(admitted_scope) != scope
            or admitted_kind != str(event.kind or "").strip().lower()
        ):
            return self._fail_ui_completion(
                event,
                state,
                intent,
                "the admitted event kind/completion_scope drifted after pointer input",
            )

        observed, probe_error = self._probe_foreground_window()
        verified = observed is not None and self._foreground_window_matches(observed, scope)
        state.data[self._SEMANTIC_VERIFICATION_KEY] = (
            self._verification(observed, scope, verified=verified, before_input=False)
            if observed is not None
            else {
                "verified": False,
                "kind": self._UI_SCOPE_KIND,
                "before_input": False,
                "error": str(probe_error or "foreground-window observation unavailable"),
            }
        )
        if observed is not None and verified:
            return self._complete_ui_scope(
                event,
                state,
                scope,
                response=self._response(observed),
                reason=(
                    "ZN completed this ui_state_transition only after the bounded click effect "
                    "was independently observed and a fresh foreground-window Sense exactly "
                    "matched the structured process/title completion scope; task prose was not "
                    "used as completion evidence"
                ),
            )

        detail = self._response(observed) if observed is not None else str(probe_error)
        return self._fail_ui_completion(
            event,
            state,
            intent,
            "fresh foreground-window evidence did not match the exact structured scope: " + detail,
        )

    def _complete_ui_scope(
        self,
        event,
        state,
        scope: dict[str, str],
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult:
        state.stage = "complete"
        state.next_action = None
        state.data["native_completion_scope"] = dict(scope)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        self.store.record_runtime_task(model_invocations=0)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=response,
            model_invocations=0,
            reason=reason,
        )

    def _fail_ui_completion(self, event, state, intent: NativeActionIntent, failure: str) -> None:
        message = "pointer click semantic completion failed: " + str(failure)
        state.data["local_failure"] = message
        self._record_failed_action(
            event,
            state,
            intent,
            source="verification",
            failure=message,
        )
        state.stage = "native_investigation"
        state.next_action = (
            "investigate the contradicted semantic UI state without replaying pointer input"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _ui_completion_scope(
        self,
        event,
    ) -> tuple[dict[str, str] | None, str | None]:
        raw = event.payload.get("completion_scope")
        if not isinstance(raw, dict) or str(raw.get("kind") or "").strip().lower() != self._UI_SCOPE_KIND:
            return None, "ui_state_transition requires completion_scope.kind=foreground_window_matches"
        unknown = sorted(
            str(key)
            for key in raw
            if key not in {"kind", "process_name", "title_equals"}
        )
        if unknown:
            return None, (
                "foreground_window_matches completion_scope contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        process_name = str(raw.get("process_name") or "").strip().lower()
        title = str(raw.get("title_equals") or "").strip()
        if not process_name or not title:
            return None, (
                "foreground_window_matches requires exact non-empty process_name and title_equals"
            )
        return {
            "kind": self._UI_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": title,
        }, None

    def _probe_foreground_window(
        self,
    ) -> tuple[ForegroundWindowObservation | None, str | None]:
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned foreground window Sense is unavailable"
        try:
            return sense.probe(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _foreground_window_matches(
        observed: ForegroundWindowObservation,
        scope: dict[str, str],
    ) -> bool:
        return bool(
            str(observed.process_name or "").strip().lower() == scope["process_name"]
            and str(observed.title or "").strip() == scope["title_equals"]
        )

    @staticmethod
    def _response(observed: ForegroundWindowObservation) -> str:
        return f"foreground window process={observed.process_name!s} title={observed.title!r}"

    def _verification(
        self,
        observed: ForegroundWindowObservation,
        scope: dict[str, str],
        *,
        verified: bool,
        before_input: bool,
    ) -> dict[str, Any]:
        return {
            "verified": bool(verified),
            "kind": self._UI_SCOPE_KIND,
            "before_input": bool(before_input),
            "expected_process_name": scope["process_name"],
            "expected_title": scope["title_equals"],
            "observed_process_id": int(observed.process_id),
            "observed_process_name": observed.process_name,
            "observed_title": observed.title,
            "observed_class_name": observed.class_name,
            "observation": asdict(observed),
        }

from __future__ import annotations

"""Zero-model Windows master-volume Reflex on the existing Resident/Action path."""

from typing import Any, Mapping

from .action import NativeActionIntent
from .action_execution import ActionRequest
from .models import ExecutionPath, ResidentRunResult, utc_now


_STATE_KEY = "windows_audio_reflex_v1"
_REVERIFY_STAGE = "windows_audio_reflex_reverify"
_INSTALL_MARKER = "_windows_audio_reflex_v1_installed"
_AUDIO_INTENTS = {
    "windows.audio.volume.read",
    "windows.audio.volume.set",
}


def _blocked(
    resident,
    event,
    state,
    *,
    code: str,
    detail: str,
    response: str | None = None,
) -> ResidentRunResult:
    reason = f"{code}: {detail}"[:4000]
    meta = dict(state.data.get(_STATE_KEY) or {})
    meta.update(
        {
            "status": "blocked",
            "blocker": {"code": code, "detail": str(detail)[:2000]},
            "updated_at": utc_now(),
            "model_invocations": 0,
        }
    )
    state.data[_STATE_KEY] = meta
    state.stage = "failed"
    state.next_action = None
    state.blocked_by = code
    resident.store.save_working_state(state)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=False,
        response=(response or detail)[:8000],
        model_invocations=0,
        reason=reason,
    )


def _audio_match(resident, event):
    resolution = resident.reflex_intents.resolve(event)
    if resolution.status == "ambiguous":
        direct = [
            candidate
            for candidate in resolution.candidates
            if candidate.intent_id in _AUDIO_INTENTS
        ]
        return resolution, None, bool(direct)
    match = resolution.match
    if (
        resolution.status != "matched"
        or match is None
        or match.intent_id not in _AUDIO_INTENTS
    ):
        return resolution, None, False
    descriptor = resident.reflex_intents.descriptor(match.intent_id)
    if descriptor is None or "direct_action" not in set(descriptor.tags):
        return resolution, None, False
    return resolution, match, False


def _intent(event, *, action_id: str, body_action_kind: str, args: Mapping[str, Any]):
    return NativeActionIntent(
        intent_id=f"audio-reflex-{event.event_id}",
        event_id=event.event_id,
        kind=body_action_kind,
        args=dict(args),
        expected_outcome={"kind": "action_fabric", "action_id": action_id},
        reason="deterministic resident audio reflex selected one existing Action Fabric action",
        source="resident_reflex",
    )


def _level(execution) -> float | None:
    for observation in reversed(tuple(execution.observations or ())):
        raw = observation.data.get("level_percent")
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _format_percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    rounded = round(float(value), 3)
    return f"{rounded:g}"


def _response(event, *, action_id: str, level: float | None) -> str:
    chinese = any("\u4e00" <= char <= "\u9fff" for char in str(event.task or ""))
    rendered = _format_percent(level)
    if action_id == "windows.audio.volume.read":
        return (
            f"当前系统音量为 {rendered}%。"
            if chinese
            else f"System volume is {rendered}%."
        )
    return (
        f"系统音量已调到 {rendered}%。"
        if chinese
        else f"System volume was set to {rendered}%."
    )


def _run_action(
    resident,
    event,
    state,
    *,
    intent_id: str,
    action_id: str,
    args: Mapping[str, Any],
    reverify: bool,
):
    action = resident.action_fabric.descriptor(action_id)
    if action is None or not action.body_action_kind:
        return _blocked(
            resident,
            event,
            state,
            code="audio_action_unavailable",
            detail=f"Action Fabric has no executable binding for {action_id}",
            response="当前系统音量能力不可用，ZN 没有把命令转交给模型猜测执行。",
        )

    intent = _intent(
        event,
        action_id=action_id,
        body_action_kind=action.body_action_kind,
        args=args,
    )
    meta = dict(state.data.get(_STATE_KEY) or {})
    meta.update(
        {
            "version": 1,
            "event_id": event.event_id,
            "intent_id": intent_id,
            "action_id": action_id,
            "args": dict(args),
            "status": "reverifying" if reverify else "executing",
            "model_invocations": 0,
            "updated_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = meta
    if action.effect_class != "read_only":
        state.data["native_action_intent"] = intent.to_dict()
    resident.store.save_working_state(state)

    execution = resident.action_executor.execute(
        ActionRequest(
            action_id,
            dict(args),
            event_id=event.event_id,
        )
    )
    meta["execution_id"] = execution.execution_id
    meta["execution_status"] = execution.status
    meta["verification_status"] = execution.verification.status
    meta["verification_reason"] = execution.verification.reason[:1200]
    meta["updated_at"] = utc_now()
    state.data[_STATE_KEY] = meta

    if execution.success:
        observed = _level(execution)
        meta["status"] = "verified"
        meta["observed_level_percent"] = observed
        state.data[_STATE_KEY] = meta
        return resident._complete_successful_body_action(
            event,
            state,
            intent,
            response=_response(event, action_id=action_id, level=observed),
            reason=(
                "deterministic resident audio reflex completed through the existing "
                "Action Fabric and Body with fresh Windows Core Audio verification; "
                "zero model invocations"
            ),
        )

    if execution.status == "uncertain" and action.effect_class != "read_only":
        if not reverify:
            meta["status"] = "reverify_pending"
            state.data[_STATE_KEY] = meta
            state.stage = _REVERIFY_STAGE
            state.next_action = (
                "re-observe the same Windows audio postcondition without replay"
            )
            state.blocked_by = None
            resident.store.save_working_state(state)
            return None

        body_result = execution.body_result
        if body_result is not None:
            meta["status"] = "side_effect_recovery"
            state.data[_STATE_KEY] = meta
            state.data["native_action_intent"] = intent.to_dict()
            resident.store.save_working_state(state)
            return resident._begin_side_effect_recovery(
                event,
                state,
                intent,
                body_result,
            )

    return _blocked(
        resident,
        event,
        state,
        code="audio_action_failed",
        detail=execution.error or execution.verification.reason or "audio action failed",
        response=(
            "系统音量命令没有通过当前机器状态验证，ZN 没有改用模型或盲目重试。"
        ),
    )


def install_windows_audio_reflex_behavior(resident) -> None:
    """Attach direct Windows audio Reflexes to the one Product Resident."""
    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_advance = resident._advance_event_step

    def advance_event_step(
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        stage = str(state.stage or "")
        if stage == "orient":
            resolution, match, direct_ambiguous = _audio_match(resident, event)
            if direct_ambiguous:
                return _blocked(
                    resident,
                    event,
                    state,
                    code="audio_reflex_ambiguous",
                    detail=resolution.reason or "multiple direct audio intents matched",
                    response="音量命令存在歧义，ZN 没有执行，也没有交给模型猜。",
                )
            if match is not None and match.action_id:
                return _run_action(
                    resident,
                    event,
                    state,
                    intent_id=match.intent_id,
                    action_id=match.action_id,
                    args=match.slots,
                    reverify=False,
                )

        if stage == _REVERIFY_STAGE:
            meta = state.data.get(_STATE_KEY)
            if not isinstance(meta, dict):
                return _blocked(
                    resident,
                    event,
                    state,
                    code="audio_reverify_state_missing",
                    detail="durable Windows audio re-verification state is missing",
                )
            intent_id = str(meta.get("intent_id") or "")
            action_id = str(meta.get("action_id") or "")
            args = meta.get("args")
            if intent_id not in _AUDIO_INTENTS or not action_id or not isinstance(args, dict):
                return _blocked(
                    resident,
                    event,
                    state,
                    code="audio_reverify_state_invalid",
                    detail="durable Windows audio re-verification state is malformed",
                )
            return _run_action(
                resident,
                event,
                state,
                intent_id=intent_id,
                action_id=action_id,
                args=args,
                reverify=True,
            )

        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)

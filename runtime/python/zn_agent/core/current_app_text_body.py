from __future__ import annotations

"""E2E-13 exact ValuePattern replacement on the existing product Body."""

from typing import Any

from .automation_text_content import NativeAutomationValueReplacementBody, text_sha256
from .body import BodyAction, BodyActionResult
from .machine_capability_body import MachineCapabilityBody
from .models import utc_now


class CurrentAppTextAwareBody(MachineCapabilityBody):
    """Add one bounded UIA replacement movement without adding a second Body.

    The raw replacement exists only in the live call. Durable action history is
    rewritten to length/hash metadata before it reaches the inherited recorder,
    while the inherited generic side-effect attempt journal stores only a
    signature hash. A replay-blocking started/observed attempt therefore never
    needs the application text to survive a restart.

    Inherit the current final product Body rather than an older browser-only
    layer so application launch/activation, browser form submit, named text,
    pointer/keyboard, file, and existing side-effect recovery remain one
    compatible Body surface.
    """

    _AUTOMATION_VALUE_REPLACE = "automation_value_replace"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._automation_value_replacement = NativeAutomationValueReplacementBody()

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._AUTOMATION_VALUE_REPLACE:
            return True
        return super()._requires_guard(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind == self._AUTOMATION_VALUE_REPLACE:
            safe_args = dict(action.args)
            raw = safe_args.pop("replacement_text", None)
            if raw is not None:
                text = str(raw)
                safe_args["replacement_text_redacted"] = True
                safe_args["replacement_chars"] = len(text)
                safe_args["replacement_sha256"] = text_sha256(text)
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind != self._AUTOMATION_VALUE_REPLACE:
            return super()._dispatch(action, started)

        result = self._automation_value_replacement.replace_exact(
            process_id=int(action.args.get("process_id") or 0),
            process_name=str(action.args.get("process_name") or ""),
            window_handle=int(action.args.get("window_handle") or 0),
            name=str(action.args.get("name") or ""),
            runtime_id=tuple(int(v) for v in action.args.get("runtime_id") or ()),
            source_chars=int(action.args.get("source_chars") or 0),
            source_sha256=str(action.args.get("source_sha256") or ""),
            replacement_text=str(action.args.get("replacement_text") or ""),
            result_chars=int(action.args.get("result_chars") or 0),
            result_sha256=str(action.args.get("result_sha256") or ""),
        )
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=bool(result.success),
            output="",
            data=result.audit,
            error=result.error,
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

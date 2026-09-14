from __future__ import annotations

"""Current final product Body extensions for exact UI text and local service state."""

from contextlib import closing
from dataclasses import asdict
from typing import Any

from . import side_effect_attempts
from .automation_text_content import NativeAutomationValueReplacementBody, text_sha256
from .body import BodyAction, BodyActionResult
from .local_service_diagnosis import LocalServiceDiagnoser, LocalServiceTarget
from .machine_capability_body import MachineCapabilityBody
from .models import utc_now


class CurrentAppTextAwareBody(MachineCapabilityBody):
    """Extend the one product Body without creating a second execution surface.

    The raw E2E-13 replacement exists only in the live call. Durable action
    history is rewritten to length/hash metadata before it reaches the inherited
    recorder, while the inherited generic side-effect attempt journal stores only
    a signature hash.

    E2E-21 adds only a read-only ``local_service_state`` movement here. Any repair
    remains an ordinary ``command`` movement, so the existing command authority,
    side-effect journal, replay rules, terminal isolation and audit path stay the
    single mutation boundary. A successful command therefore never makes service
    recovery true by itself; callers must observe ``local_service_state`` again.

    Local diagnostic details are richer in the live result than in durable Body
    history. Health URLs, log paths/roots/text and executable paths can contain
    user data, so the persisted row retains only bounded length/hash metadata for
    those fields. Log reads themselves require an explicit ``log_root`` and are
    revalidated inside that authority immediately before every read.
    """

    _AUTOMATION_VALUE_REPLACE = "automation_value_replace"
    _LOCAL_SERVICE_STATE = "local_service_state"
    _RECOVERY_VISIBLE_STATUSES = ("started", "observed", "verified_effect")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._automation_value_replacement = NativeAutomationValueReplacementBody()
        self._local_service_diagnoser = LocalServiceDiagnoser()

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._AUTOMATION_VALUE_REPLACE:
            return True
        return super()._requires_guard(kind, args)

    def value_replacement_attempts(
        self,
        event_id: str,
    ) -> list[dict[str, Any]]:
        """Return argument-free durable dispatch ownership for this E2E-13 mutation.

        Recovery deliberately queries by event + action kind rather than by the
        current action signature. Once one replacement has crossed the durable
        side-effect boundary, changed source evidence must not manufacture a new
        signature that can bypass that ownership after restart.

        ``verified_effect`` remains visible here because recovery may itself
        crash after resolving the attempt but before advancing WorkingState. On
        the next restart that durable machine evidence still forbids a new
        replacement dispatch.
        """

        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            return []
        with closing(self._connect()) as conn:
            rows = side_effect_attempts.event_attempts(
                conn,
                event_id=normalized_event,
                statuses=self._RECOVERY_VISIBLE_STATUSES,
                limit=32,
            )
        return [
            dict(row)
            for row in rows
            if str(row["kind"] or "").strip().lower() == self._AUTOMATION_VALUE_REPLACE
        ]

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        persisted_result = result
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
        elif action.kind == self._LOCAL_SERVICE_STATE:
            safe_args = dict(action.args)
            for key in ("health_url", "log_path", "log_root"):
                self._redact_mapping_value(safe_args, key)
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
            persisted_result = self._redacted_local_service_result(result)
        super()._record(action, persisted_result)

    @staticmethod
    def _redact_mapping_value(data: dict[str, Any], key: str) -> None:
        raw = data.pop(key, None)
        if raw in (None, ""):
            return
        value = str(raw)
        data[f"{key}_redacted"] = True
        data[f"{key}_chars"] = len(value)
        data[f"{key}_sha256"] = text_sha256(value)

    @classmethod
    def _redacted_local_service_result(cls, result: BodyActionResult) -> BodyActionResult:
        data = dict(result.data or {})

        target = dict(data.get("target") or {})
        for key in ("health_url", "log_path", "log_root"):
            cls._redact_mapping_value(target, key)
        data["target"] = target

        listeners = data.get("listeners")
        if isinstance(listeners, (list, tuple)):
            safe_listeners: list[dict[str, Any]] = []
            for row in listeners:
                if not isinstance(row, dict):
                    continue
                safe_row = dict(row)
                cls._redact_mapping_value(safe_row, "executable_path")
                safe_listeners.append(safe_row)
            data["listeners"] = safe_listeners

        health = data.get("health")
        if isinstance(health, dict):
            safe_health = dict(health)
            cls._redact_mapping_value(safe_health, "url")
            data["health"] = safe_health

        log = data.get("log")
        if isinstance(log, dict):
            safe_log = dict(log)
            cls._redact_mapping_value(safe_log, "path")
            cls._redact_mapping_value(safe_log, "tail")
            data["log"] = safe_log

        return BodyActionResult(
            action_id=result.action_id,
            kind=result.kind,
            success=result.success,
            output=result.output,
            data=data,
            error=result.error,
            event_id=result.event_id,
            started_at=result.started_at,
            completed_at=result.completed_at,
        )

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._LOCAL_SERVICE_STATE:
            target = LocalServiceTarget(
                port=int(action.args.get("port") or 0),
                host=str(action.args.get("host") or "127.0.0.1"),
                expected_process_name=(
                    str(action.args.get("expected_process_name") or "").strip() or None
                ),
                health_url=str(action.args.get("health_url") or "").strip() or None,
                log_path=str(action.args.get("log_path") or "").strip() or None,
                log_root=str(action.args.get("log_root") or "").strip() or None,
            )
            snapshot = self._local_service_diagnoser.inspect(
                target,
                health_timeout=max(
                    0.05,
                    min(10.0, float(action.args.get("health_timeout") or 2.0)),
                ),
            )
            data = asdict(snapshot)
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=snapshot.reason,
                data=data,
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

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

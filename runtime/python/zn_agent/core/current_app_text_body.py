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
    history. Health URLs and log text can contain credentials or user data, so the
    persisted row retains only bounded metadata and hashes for those fields.
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
            raw_url = safe_args.pop("health_url", None)
            if raw_url:
                url = str(raw_url)
                safe_args["health_url_redacted"] = True
                safe_args["health_url_chars"] = len(url)
                safe_args["health_url_sha256"] = text_sha256(url)
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
    def _redacted_local_service_result(result: BodyActionResult) -> BodyActionResult:
        data = dict(result.data or {})

        target = dict(data.get("target") or {})
        raw_target_url = target.pop("health_url", None)
        if raw_target_url:
            value = str(raw_target_url)
            target["health_url_redacted"] = True
            target["health_url_chars"] = len(value)
            target["health_url_sha256"] = text_sha256(value)
        data["target"] = target

        health = data.get("health")
        if isinstance(health, dict):
            safe_health = dict(health)
            raw_health_url = safe_health.pop("url", None)
            if raw_health_url:
                value = str(raw_health_url)
                safe_health["url_redacted"] = True
                safe_health["url_chars"] = len(value)
                safe_health["url_sha256"] = text_sha256(value)
            data["health"] = safe_health

        log = data.get("log")
        if isinstance(log, dict):
            safe_log = dict(log)
            raw_tail = str(safe_log.pop("tail", "") or "")
            safe_log["tail_redacted"] = True
            safe_log["tail_chars"] = len(raw_tail)
            safe_log["tail_sha256"] = text_sha256(raw_tail)
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

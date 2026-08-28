from __future__ import annotations

"""Windows staged exact-overwrite commit layered on #21 recovery semantics."""

import os
from typing import Any

from .action import NativeActionIntent
from .body import BodyActionResult
from .file_identity import compare_file_identities, observe_file_identity
from .models import utc_now
from .overwrite_recovery_resident import OverwriteAwareBody, OverwriteRecoveryResidentRuntime
from .staged_text_write import (
    StagedWriteCommitUncertainError,
    cleanup_overwrite_artifacts,
    write_text_staged_windows,
)


class _PrecommitChanged(RuntimeError):
    pass


class _PrecommitRejected(RuntimeError):
    def __init__(self, result: BodyActionResult) -> None:
        self.result = result
        super().__init__(result.error or "overwrite precommit rejected")


class _DispatchUncertain(RuntimeError):
    def __init__(self, result: BodyActionResult) -> None:
        self.result = result
        super().__init__(result.error or "overwrite dispatch uncertain")


class AtomicOverwriteAwareBody(OverwriteAwareBody):
    """Stage full Windows text beside its target before the final rename/replace."""

    @staticmethod
    def _overwrite(kind: str, args: dict[str, Any]) -> bool:
        return str(kind or "").strip().lower() in {"write_text", "write_file"} and not bool(
            args.get("append", False)
        )

    def _work(self, event_id: str | None, kind: str, args: dict[str, Any]):
        if self.resident is None or not str(event_id or "").strip():
            return None, None
        state = self.resident.store.get_working_state()
        raw = state.data.get("native_action_intent")
        if str(state.current_event_id or "") != str(event_id) or not isinstance(raw, dict):
            return None, state
        intent = NativeActionIntent.from_dict(raw)
        if not (
            self._overwrite(intent.kind, intent.args)
            and str(intent.kind).strip().lower() == str(kind).strip().lower()
            and dict(intent.args) == dict(args)
        ):
            return None, state
        return intent, state

    def _token(self, event_id: str | None, kind: str, args: dict[str, Any], fallback="") -> str:
        owner = str(event_id or "").strip() or str(fallback).strip() or "body"
        return f"{owner}\0{self._signature_hash(str(kind).strip().lower(), args)}"

    def cleanup_atomic_artifacts(self, *, event_id: str, kind: str, args: dict[str, Any]):
        return cleanup_overwrite_artifacts(
            self._path_arg(args), self._token(event_id, kind, args)
        )

    def _precommit(self, action) -> dict[str, object]:
        intent, state = self._work(action.event_id, action.kind, dict(action.args))
        if intent is None or state is None:
            return {"checked": False, "reason": "no_active_work_prestate"}
        raw = state.data.get(self.resident._OVERWRITE_PRESTATE_KEY)
        if not (
            isinstance(raw, dict)
            and str(raw.get("intent_id") or "") == intent.intent_id
            and str(raw.get("action_signature") or "") == self.resident._intent_signature(intent)
            and isinstance(raw.get("identity"), dict)
        ):
            raise _PrecommitChanged("matching durable overwrite pre-state identity is missing")
        comparison = compare_file_identities(
            raw["identity"], observe_file_identity(str(action.args.get("path") or ""))
        )
        if comparison.get("exact") is not True:
            raise _PrecommitChanged(
                "overwrite precommit identity changed after staging; refusing namespace replacement "
                f"({comparison.get('reason') or 'identity_unknown'})"
            )
        return {"checked": True, "exact": True, "reason": comparison.get("reason")}

    def _write_text(self, action, started: str) -> BodyActionResult:
        if os.name != "nt" or not self._overwrite(action.kind, action.args):
            return super()._write_text(action, started)
        path = self._path_arg(action.args)
        content = str(action.args.get("content") or "")
        encoding = str(action.args.get("encoding") or "utf-8")
        if bool(action.args.get("create_parents", True)):
            path.parent.mkdir(parents=True, exist_ok=True)
        precommit: dict[str, object] = {}
        try:
            staged = write_text_staged_windows(
                path,
                content,
                encoding=encoding,
                token=self._token(action.event_id, action.kind, dict(action.args), action.action_id),
                precommit_check=lambda: precommit.update(self._precommit(action)),
            )
        except StagedWriteCommitUncertainError as exc:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={
                    "path": str(path),
                    "side_effect_uncertain": True,
                    "replay_blocked": True,
                    "write_commit_uncertain": True,
                    "write_strategy": exc.strategy,
                    "staging_path": str(exc.staging_path),
                    "backup_path": str(exc.backup_path) if exc.backup_path else None,
                    "winerror": exc.error_code,
                },
                error=f"{type(exc).__name__}: {exc}",
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        except Exception as exc:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={
                    "path": str(path),
                    "atomic_commit_proven_absent": True,
                    "overwrite_precommit_rejected": isinstance(exc, _PrecommitChanged),
                },
                error=f"{type(exc).__name__}: {exc}",
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        return self._ok(
            action,
            started,
            output=str(path),
            data={
                "path": str(path),
                "written_chars": staged.written_chars,
                "append": False,
                "encoding": encoding,
                "write_strategy": staged.strategy,
                "cleanup_pending": list(staged.cleanup_pending),
                "precommit_identity": precommit,
            },
        )

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        result = super().act(kind, event_id=event_id, **args)
        data = result.data if isinstance(result.data, dict) else {}
        if not result.success and data.get("atomic_commit_proven_absent") is True:
            attempt_id = str(data.get("side_effect_attempt_id") or "").strip()
            if attempt_id and str(event_id or "").strip() and not self.resolve_uncertain_attempt(
                attempt_id,
                event_id=str(event_id),
                status="verified_absent",
                evidence_action_id=result.action_id,
            ):
                raise RuntimeError("could not close commit-proven-absent overwrite attempt")
        intent, _ = self._work(event_id, kind, dict(args))
        if intent is None or result.success:
            return result
        if data.get("overwrite_precommit_rejected") is True:
            raise _PrecommitRejected(result)
        if data.get("side_effect_uncertain") is True:
            raise _DispatchUncertain(result)
        return result


class AtomicOverwriteRecoveryResidentRuntime(OverwriteRecoveryResidentRuntime):
    """Keep #21 replay policy while strengthening Windows physical overwrite commit."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.body = AtomicOverwriteAwareBody(resident=self)

    @staticmethod
    def _result_data(result: BodyActionResult) -> dict[str, Any]:
        return {
            "action_id": result.action_id,
            "kind": result.kind,
            "success": result.success,
            "data": dict(result.data or {}),
            "output": result.output,
            "error": result.error,
            "event_id": result.event_id,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
        }

    def _cleanup(self, event, intent: NativeActionIntent) -> None:
        if os.name == "nt" and self._is_overwrite_intent(intent) and str(
            intent.args.get("path") or ""
        ).strip():
            self.body.cleanup_atomic_artifacts(
                event_id=event.event_id, kind=intent.kind, args=dict(intent.args)
            )

    def _native_action_step(self, event, state, *, readiness, thought=None):
        try:
            return super()._native_action_step(
                event, state, readiness=readiness, thought=thought
            )
        except (_PrecommitRejected, _DispatchUncertain) as exc:
            raw = state.data.get("native_action_intent")
            if not isinstance(raw, dict):
                raise RuntimeError("atomic overwrite exception has no active intent") from exc
            intent = NativeActionIntent.from_dict(raw)
            state.data["native_action_result"] = self._result_data(exc.result)
            if isinstance(exc, _DispatchUncertain):
                return self._begin_side_effect_recovery(
                    event, state, intent, exc.result, thought=thought
                )
            failure = exc.result.error or "overwrite precommit changed"
            state.data["local_failure"] = failure
            self._record_failed_action(
                event, state, intent, source="precondition", failure=failure
            )
            state.stage = "native_investigation"
            state.next_action = "refresh current file/repository evidence before another overwrite"
            state.blocked_by = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

    def _begin_side_effect_recovery(self, event, state, intent, result, *, thought=None):
        outcome = super()._begin_side_effect_recovery(
            event, state, intent, result, thought=thought
        )
        data = result.data if isinstance(result.data, dict) else {}
        recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        if data.get("write_commit_uncertain") is True and isinstance(recovery, dict):
            recovery.update(
                {
                    "write_commit_uncertain": True,
                    "write_strategy": str(data.get("write_strategy") or "")[:80],
                    "winerror": data.get("winerror"),
                    "staging_path": str(data.get("staging_path") or ""),
                    "backup_path": str(data.get("backup_path") or ""),
                }
            )
            self.store.save_working_state(state)
        return outcome

    def _complete_successful_body_action(self, event, state, intent, *, response, reason):
        result = super()._complete_successful_body_action(
            event, state, intent, response=response, reason=reason
        )
        if result is not None and result.success:
            self._cleanup(event, intent)
        return result

    def _resume_native_completion(self, event, state):
        result = super()._resume_native_completion(event, state)
        raw = state.data.get("native_action_intent")
        if result is not None and result.success and isinstance(raw, dict):
            self._cleanup(event, NativeActionIntent.from_dict(raw))
        return result

    def _side_effect_recovery_step(self, event, state, *, readiness, thought=None):
        result = super()._side_effect_recovery_step(
            event, state, readiness=readiness, thought=thought
        )
        raw = state.data.get("native_action_intent")
        if result is not None and result.success and isinstance(raw, dict):
            self._cleanup(event, NativeActionIntent.from_dict(raw))
        return result

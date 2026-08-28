from __future__ import annotations

"""Windows staged exact-overwrite commit layered on #21 recovery semantics."""

import os
from contextlib import closing
from typing import Any

from . import atomic_overwrite_protocols
from .action import NativeActionIntent
from .body import BodyActionResult
from .file_identity import compare_file_identities, observe_file_identity
from .models import utc_now
from .overwrite_recovery_resident import OverwriteAwareBody, OverwriteRecoveryResidentRuntime
from .staged_text_write import (
    StagedWriteCommitUncertainError,
    cleanup_overwrite_artifacts,
    overwrite_artifact_paths,
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

    def _init_schema(self) -> None:
        super()._init_schema()
        with closing(self._connect()) as conn:
            atomic_overwrite_protocols.ensure_schema(conn)
            conn.commit()

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

    def _signature(self, kind: str, args: dict[str, Any]) -> str:
        return self._signature_hash(str(kind).strip().lower(), args)

    def _token(self, event_id: str | None, kind: str, args: dict[str, Any], fallback="") -> str:
        owner = str(event_id or "").strip() or str(fallback).strip() or "body"
        return f"{owner}\0{self._signature(kind, args)}"

    def atomic_artifact_paths(self, *, event_id: str, kind: str, args: dict[str, Any]):
        return overwrite_artifact_paths(
            self._path_arg(args), self._token(event_id, kind, args)
        )

    def cleanup_atomic_artifacts(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
        include_staging: bool = True,
        include_backup: bool = True,
    ):
        return cleanup_overwrite_artifacts(
            self._path_arg(args),
            self._token(event_id, kind, args),
            include_staging=include_staging,
            include_backup=include_backup,
        )

    def prepare_atomic_protocol(
        self,
        *,
        event_id: str,
        intent: NativeActionIntent,
    ) -> dict[str, Any]:
        args = dict(intent.args)
        staging_path, backup_path = self.atomic_artifact_paths(
            event_id=event_id,
            kind=intent.kind,
            args=args,
        )
        signature = self._signature(intent.kind, args)
        with closing(self._connect()) as conn:
            protocol = atomic_overwrite_protocols.prepare_protocol(
                conn,
                event_id=event_id,
                signature_hash=signature,
                intent_id=intent.intent_id,
                staging_path=str(staging_path),
                backup_path=str(backup_path),
            )
            conn.commit()
        return protocol

    def atomic_protocol(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            return atomic_overwrite_protocols.protocol(
                conn,
                event_id=event_id,
                signature_hash=self._signature(kind, args),
            )

    def delete_atomic_protocol(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
        attempt_id: str | None = None,
    ) -> bool:
        with closing(self._connect()) as conn:
            deleted = atomic_overwrite_protocols.delete_protocol(
                conn,
                event_id=event_id,
                signature_hash=self._signature(kind, args),
                attempt_id=attempt_id,
            )
            conn.commit()
        return deleted

    def _active_started_attempt(self, event_id: str, kind: str, args: dict[str, Any]):
        return self._replay_blocking_attempt(
            event_id,
            self._signature(kind, args),
            include_observed=False,
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

    def _stage_ready(self, action, staging_path) -> None:
        intent, _ = self._work(action.event_id, action.kind, dict(action.args))
        if intent is None:
            return
        event_id = str(action.event_id or "")
        attempt = self._active_started_attempt(event_id, action.kind, dict(action.args))
        if attempt is None:
            raise RuntimeError("atomic stage has no matching durable side-effect attempt")
        stage_identity = observe_file_identity(staging_path)
        with closing(self._connect()) as conn:
            atomic_overwrite_protocols.record_stage_ready(
                conn,
                event_id=event_id,
                signature_hash=self._signature(action.kind, dict(action.args)),
                intent_id=intent.intent_id,
                attempt_id=str(attempt["attempt_id"]),
                staging_path=str(staging_path),
                stage_identity=stage_identity,
            )
            conn.commit()

    def _commit_started(self, action, strategy: str, staging_path, backup_path) -> None:
        intent, _ = self._work(action.event_id, action.kind, dict(action.args))
        if intent is None:
            return
        event_id = str(action.event_id or "")
        attempt = self._active_started_attempt(event_id, action.kind, dict(action.args))
        if attempt is None:
            raise RuntimeError("atomic commit has no matching durable side-effect attempt")
        with closing(self._connect()) as conn:
            atomic_overwrite_protocols.record_commit_started(
                conn,
                event_id=event_id,
                signature_hash=self._signature(action.kind, dict(action.args)),
                intent_id=intent.intent_id,
                attempt_id=str(attempt["attempt_id"]),
                staging_path=str(staging_path),
                backup_path=str(backup_path) if backup_path is not None else None,
                strategy=str(strategy),
            )
            conn.commit()

    def _discard_resolved_protocol_if_clean(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
        attempt_id: str,
    ) -> None:
        staging_path, backup_path = self.atomic_artifact_paths(
            event_id=event_id,
            kind=kind,
            args=args,
        )
        if os.path.lexists(str(staging_path)) or os.path.lexists(str(backup_path)):
            return
        self.delete_atomic_protocol(
            event_id=event_id,
            kind=kind,
            args=args,
            attempt_id=attempt_id,
        )

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
                after_stage=lambda staging_path: self._stage_ready(action, staging_path),
                precommit_check=lambda: precommit.update(self._precommit(action)),
                before_commit=lambda strategy, staging_path, backup_path: self._commit_started(
                    action, strategy, staging_path, backup_path
                ),
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
            normalized_event = str(event_id or "").strip()
            if attempt_id and normalized_event and not self.resolve_uncertain_attempt(
                attempt_id,
                event_id=normalized_event,
                status="verified_absent",
                evidence_action_id=result.action_id,
            ):
                raise RuntimeError("could not close commit-proven-absent overwrite attempt")
            if attempt_id and normalized_event:
                self._discard_resolved_protocol_if_clean(
                    event_id=normalized_event,
                    kind=kind,
                    args=dict(args),
                    attempt_id=attempt_id,
                )
        intent, _ = self._work(event_id, kind, dict(args))
        if intent is None or result.success:
            return result
        if data.get("overwrite_precommit_rejected") is True:
            raise _PrecommitRejected(result)
        if data.get("side_effect_uncertain") is True:
            raise _DispatchUncertain(result)
        return result


class AtomicOverwriteRecoveryResidentRuntime(OverwriteRecoveryResidentRuntime):
    """Keep #21 replay policy while adding durable staged-commit reconciliation."""

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

    def _cleanup(
        self,
        event,
        intent: NativeActionIntent,
        *,
        preserve_backup: bool = False,
    ) -> dict[str, object] | None:
        if os.name != "nt" or not self._is_overwrite_intent(intent) or not str(
            intent.args.get("path") or ""
        ).strip():
            return None
        protocol = self.body.atomic_protocol(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        cleanup = self.body.cleanup_atomic_artifacts(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
            include_staging=True,
            include_backup=not preserve_backup,
        )
        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        artifacts_gone = not os.path.lexists(str(staging_path)) and (
            preserve_backup or not os.path.lexists(str(backup_path))
        )
        if protocol is not None and artifacts_gone and not (
            preserve_backup and os.path.lexists(str(backup_path))
        ):
            self.body.delete_atomic_protocol(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
                attempt_id=str(protocol.get("attempt_id") or "") or None,
            )
        return cleanup

    def _native_action_step(self, event, state, *, readiness, thought=None):
        raw = state.data.get("native_action_intent")
        if os.name == "nt" and isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            if self._is_overwrite_intent(intent) and not self.body.overwrite_replay_blocked(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
            ):
                if not self._prepare_overwrite_prestate(
                    event,
                    state,
                    intent,
                    thought=thought,
                ):
                    return None
                self.body.prepare_atomic_protocol(event_id=event.event_id, intent=intent)
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
        protocol = self.body.atomic_protocol(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if isinstance(recovery, dict):
            if protocol is not None:
                recovery.update(
                    {
                        "atomic_protocol_version": protocol.get("version"),
                        "atomic_stage_ready": protocol.get("stage_ready") is True,
                        "atomic_namespace_commit_started": (
                            protocol.get("namespace_commit_started") is True
                        ),
                    }
                )
            if data.get("write_commit_uncertain") is True:
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

    def _reconcile_precommit_stage(self, event, state, intent: NativeActionIntent) -> bool:
        protocol = self.body.atomic_protocol(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if (
            not isinstance(protocol, dict)
            or int(protocol.get("version") or 0) != atomic_overwrite_protocols.PROTOCOL_VERSION
            or protocol.get("stage_ready") is not True
            or protocol.get("namespace_commit_started") is True
            or not isinstance(protocol.get("stage_identity"), dict)
        ):
            return False

        recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        attempt_id = str(recovery.get("attempt_id") or "") if isinstance(recovery, dict) else ""
        if not attempt_id or str(protocol.get("attempt_id") or "") != attempt_id:
            return False

        raw_prestate = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        prestate_identity = (
            raw_prestate.get("identity")
            if isinstance(raw_prestate, dict)
            and str(raw_prestate.get("intent_id") or "") == intent.intent_id
            and str(raw_prestate.get("action_signature") or "")
            == self._intent_signature(intent)
            else None
        )
        current_target = observe_file_identity(str(intent.args.get("path") or ""))
        target_comparison = compare_file_identities(
            prestate_identity if isinstance(prestate_identity, dict) else None,
            current_target,
        )
        current_stage = observe_file_identity(str(protocol.get("staging_path") or ""))
        stage_comparison = compare_file_identities(protocol["stage_identity"], current_stage)
        backup_path = str(protocol.get("backup_path") or "")
        backup_absent = bool(backup_path) and not os.path.lexists(backup_path)

        if isinstance(recovery, dict):
            recovery["atomic_precommit_reconciliation"] = {
                "target_exact_prestate": target_comparison.get("exact") is True,
                "target_reason": str(target_comparison.get("reason") or "identity_unknown")[:120],
                "stage_exact": stage_comparison.get("exact") is True,
                "stage_reason": str(stage_comparison.get("reason") or "identity_unknown")[:120],
                "backup_absent": backup_absent,
            }

        if not (
            target_comparison.get("exact") is True
            and stage_comparison.get("exact") is True
            and backup_absent
        ):
            self.store.save_working_state(state)
            return False

        if not self.body.resolve_uncertain_attempt(
            attempt_id,
            event_id=event.event_id,
            status="verified_absent",
        ):
            self.store.save_working_state(state)
            return False

        cleanup = self.body.cleanup_atomic_artifacts(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
            include_staging=True,
            include_backup=False,
        )
        staging_path, _ = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if cleanup.get("complete") is not True or os.path.lexists(str(staging_path)):
            if isinstance(recovery, dict):
                recovery["atomic_stage_cleanup"] = cleanup
            self.store.save_working_state(state)
            return False

        self.body.delete_atomic_protocol(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
            attempt_id=attempt_id,
        )
        state.data.pop(self._SIDE_EFFECT_RECOVERY_KEY, None)
        state.data.pop("native_action_result", None)
        state.data.pop("local_failure", None)
        state.stage = "native_action"
        state.next_action = "retry exact overwrite after durable proof namespace commit never started"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return True

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
        raw = state.data.get("native_action_intent")
        if os.name == "nt" and isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            if self._is_overwrite_intent(intent) and self._reconcile_precommit_stage(
                event, state, intent
            ):
                return None
        raw_recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        preserve_backup = bool(
            isinstance(raw_recovery, dict)
            and raw_recovery.get("write_commit_uncertain") is True
        )
        result = super()._side_effect_recovery_step(
            event, state, readiness=readiness, thought=thought
        )
        raw = state.data.get("native_action_intent")
        if result is not None and result.success and isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            cleanup = self._cleanup(event, intent, preserve_backup=preserve_backup)
            if preserve_backup:
                recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
                if isinstance(recovery, dict):
                    recovery["atomic_backup_preserved"] = True
                    recovery["atomic_cleanup"] = cleanup
                    self.store.save_working_state(state)
        return result

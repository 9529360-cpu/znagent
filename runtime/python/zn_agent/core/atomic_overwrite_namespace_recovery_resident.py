from __future__ import annotations

"""Commit-start namespace reconciliation and retained-artifact cleanup for Windows overwrite."""

import os
from pathlib import Path
from typing import Any

from . import atomic_overwrite_protocols
from .action import NativeActionIntent
from .atomic_overwrite_resident import AtomicOverwriteRecoveryResidentRuntime
from .file_identity import compare_file_identities, observe_file_identity
from .models import ExecutionPath, ResidentRunResult
from .overwrite_recovery_resident import OverwriteRecoveryResidentRuntime


class AtomicOverwriteNamespaceRecoveryResidentRuntime(AtomicOverwriteRecoveryResidentRuntime):
    """Own post-commit namespace truth without turning it into replay authority.

    #23 proves one narrow precommit state where the Windows namespace API never
    started. This layer owns the opposite side of that boundary: once
    ``namespace_commit_started`` is durable, current target/stage/backup reality
    may classify what is visible, but it never authorizes replay of the old
    overwrite attempt.

    Verified effects may leave deterministic staging/backup artifacts. Cleanup
    is checkpointed only after the requested target effect is independently
    verified, and delayed deletion is allowed only while the exact artifact
    identity still matches the checkpointed ZN-owned file.
    """

    _CLEANUP_DECISION = "cleanup_verified_atomic_overwrite_artifacts"
    _REPAIR_DECISION = "repair_retained_atomic_namespace_required"

    @staticmethod
    def _content_equivalent(
        expected: dict[str, Any] | None,
        current: dict[str, Any] | None,
    ) -> bool:
        """Compare bounded complete file contents while intentionally ignoring path metadata."""

        if not isinstance(expected, dict) or not isinstance(current, dict):
            return False
        for identity in (expected, current):
            if (
                identity.get("observable") is not True
                or identity.get("stable") is not True
                or identity.get("exists") is not True
                or str(identity.get("type") or "") != "file"
                or identity.get("digest_complete") is not True
                or not str(identity.get("content_sha256") or "")
            ):
                return False
        return bool(
            int(expected.get("size_bytes") or -1) == int(current.get("size_bytes") or -2)
            and str(expected.get("content_sha256") or "")
            == str(current.get("content_sha256") or "")
        )

    def _prestate_identity(self, state, intent: NativeActionIntent) -> dict[str, Any] | None:
        raw = state.data.get(self._OVERWRITE_PRESTATE_KEY)
        if not (
            isinstance(raw, dict)
            and str(raw.get("intent_id") or "") == intent.intent_id
            and str(raw.get("action_signature") or "") == self._intent_signature(intent)
            and isinstance(raw.get("identity"), dict)
        ):
            return None
        return dict(raw["identity"])

    def _matching_commit_protocol(self, event, state, intent: NativeActionIntent):
        recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        attempt_id = (
            str(recovery.get("attempt_id") or "").strip()
            if isinstance(recovery, dict)
            else ""
        )
        if not attempt_id:
            return None
        protocol = self.body.atomic_protocol(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if not isinstance(protocol, dict):
            return None
        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if not (
            int(protocol.get("version") or 0) == atomic_overwrite_protocols.PROTOCOL_VERSION
            and str(protocol.get("intent_id") or "") == intent.intent_id
            and str(protocol.get("attempt_id") or "") == attempt_id
            and protocol.get("stage_ready") is True
            and isinstance(protocol.get("stage_identity"), dict)
            and protocol.get("namespace_commit_started") is True
            and str(protocol.get("staging_path") or "") == str(staging_path)
            and str(protocol.get("backup_path") or "") == str(backup_path)
            and str(protocol.get("write_strategy") or "")
            in {"replace_file_with_backup", "move_new_no_replace"}
        ):
            return None
        return protocol

    def _commit_namespace_evidence(
        self,
        event,
        state,
        intent: NativeActionIntent,
        protocol: dict[str, Any],
    ) -> dict[str, Any]:
        target_path = str(intent.args.get("path") or "")
        staging_path = str(protocol.get("staging_path") or "")
        backup_path = str(protocol.get("backup_path") or "")
        target_identity = observe_file_identity(target_path)
        staging_identity = observe_file_identity(staging_path)
        backup_identity = observe_file_identity(backup_path)
        prestate_identity = self._prestate_identity(state, intent)

        stage_matches = self._content_equivalent(
            protocol.get("stage_identity") if isinstance(protocol.get("stage_identity"), dict) else None,
            staging_identity,
        )
        backup_matches = self._content_equivalent(prestate_identity, backup_identity)
        target_missing = bool(
            target_identity.get("observable") is True
            and target_identity.get("stable") is True
            and target_identity.get("exists") is False
        )
        classification = "commit_started_namespace_unresolved"
        if (
            str(protocol.get("write_strategy") or "") == "replace_file_with_backup"
            and target_missing
            and stage_matches
            and backup_matches
        ):
            # Microsoft documents WinError 1177 with a supplied backup as exactly
            # this split: replacement remains under its staging name and the
            # replaced file survives under the backup name. It proves the current
            # target does not contain the requested effect, but it does not grant
            # replay authority because the namespace API already started.
            classification = "replacefile_1177_split_retained"

        return {
            "classification": classification,
            "strategy": str(protocol.get("write_strategy") or ""),
            "target_missing": target_missing,
            "stage_matches_durable_payload": stage_matches,
            "backup_matches_durable_prestate": backup_matches,
            "target_identity": target_identity,
            "staging_identity": staging_identity,
            "backup_identity": backup_identity,
        }

    def _hold_documented_namespace_split(
        self,
        event,
        state,
        evidence: dict[str, Any],
    ) -> None:
        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        recovery.update(
            {
                "status": "namespace_contradiction",
                "decision": self._REPAIR_DECISION,
                "replay_blocked": True,
                "atomic_commit_namespace": evidence,
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "preserve the exact retained stage/backup and choose an explicit namespace repair; "
            "do not replay the old overwrite"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

    def _cleanup_authority(
        self,
        event,
        state,
        intent: NativeActionIntent,
        protocol: dict[str, Any],
    ) -> dict[str, Any]:
        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        staging_identity = observe_file_identity(staging_path)
        backup_identity = observe_file_identity(backup_path)
        prestate_identity = self._prestate_identity(state, intent)

        staging_exists = staging_identity.get("exists") is True
        backup_exists = backup_identity.get("exists") is True
        staging_owned = bool(
            not staging_exists
            or self._content_equivalent(
                protocol.get("stage_identity")
                if isinstance(protocol.get("stage_identity"), dict)
                else None,
                staging_identity,
            )
        )
        backup_owned = bool(
            not backup_exists or self._content_equivalent(prestate_identity, backup_identity)
        )
        return {
            "staging_path": str(staging_path),
            "backup_path": str(backup_path),
            "staging_identity": staging_identity,
            "backup_identity": backup_identity,
            "staging_owned": staging_owned,
            "backup_owned": backup_owned,
            "has_unowned_artifact": bool(
                (staging_exists and not staging_owned) or (backup_exists and not backup_owned)
            ),
        }

    def _complete_cleanup_state(self, event, state, recovery: dict[str, Any]) -> None:
        recovery.update(
            {
                "status": "verified_effect",
                "decision": "complete_without_replay",
                "replay_blocked": False,
                "atomic_cleanup_last": {"complete": True, "removed": [], "errors": []},
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "complete"
        state.next_action = None
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

    def _checkpoint_verified_effect_cleanup(
        self,
        event,
        state,
        intent: NativeActionIntent,
        result: ResidentRunResult,
    ):
        protocol = self._matching_commit_protocol(event, state, intent)
        if protocol is None:
            return result

        authority = self._cleanup_authority(event, state, intent, protocol)
        staging_exists = authority["staging_identity"].get("exists") is True
        backup_exists = authority["backup_identity"].get("exists") is True
        if not staging_exists and not backup_exists:
            self.body.delete_atomic_protocol(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
                attempt_id=str(protocol.get("attempt_id") or "") or None,
            )
            return result

        # Delayed deletion requires positive ownership evidence. Unknown or
        # externally changed deterministic paths are preserved rather than being
        # erased merely because the user task itself is already complete.
        if authority.get("has_unowned_artifact") is True:
            raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
            recovery = dict(raw) if isinstance(raw, dict) else {}
            recovery.update(
                {
                    "status": "verified_effect_cleanup_blocked",
                    "decision": "user_decision_required",
                    "replay_blocked": True,
                    "atomic_cleanup_authority_lost": True,
                }
            )
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "side_effect_recovery"
            state.blocked_by = "outside_world_effect_uncertain"
            state.next_action = (
                "preserve retained atomic-overwrite artifacts whose exact ownership changed; "
                "the overwrite remains verified and must not be replayed"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        recovery.update(
            {
                "status": "verified_effect_cleanup_pending",
                "decision": self._CLEANUP_DECISION,
                "replay_blocked": True,
                "atomic_cleanup_expected": {
                    "staging": authority["staging_identity"],
                    "backup": authority["backup_identity"],
                },
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "retry exact retained atomic-overwrite artifact cleanup after verified effect; "
            "never replay the overwrite"
        )
        self._sync_execution_context(event, state)
        # The cleanup authority is durable before any unlink. A crash after one
        # artifact disappears can therefore treat its absence as an idempotent
        # cleanup result rather than recreating or replaying anything.
        self.store.save_working_state(state)
        return self._retry_verified_effect_cleanup(
            event,
            state,
            intent,
            original_result=result,
        )

    def _retry_verified_effect_cleanup(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        original_result: ResidentRunResult | None = None,
    ):
        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        expected = recovery.get("atomic_cleanup_expected")
        if not isinstance(expected, dict):
            return None

        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        paths = {"staging": Path(staging_path), "backup": Path(backup_path)}
        current = {name: observe_file_identity(path) for name, path in paths.items()}
        remaining = [name for name, identity in current.items() if identity.get("exists") is True]

        protocol = self._matching_commit_protocol(event, state, intent)
        if remaining and protocol is None:
            recovery.update(
                {
                    "status": "verified_effect_cleanup_blocked",
                    "decision": "user_decision_required",
                    "replay_blocked": True,
                    "atomic_cleanup_authority_lost": True,
                }
            )
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "side_effect_recovery"
            state.blocked_by = "outside_world_effect_uncertain"
            state.next_action = (
                "preserve retained atomic-overwrite artifacts because their matching protocol "
                "is unavailable; the verified overwrite must not be replayed"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        drift: dict[str, Any] = {}
        errors: list[str] = []
        removed: list[str] = []
        for name, path in paths.items():
            identity = current[name]
            if identity.get("exists") is not True:
                continue
            expected_identity = expected.get(name)
            comparison = compare_file_identities(
                expected_identity if isinstance(expected_identity, dict) else None,
                identity,
            )
            if comparison.get("exact") is not True:
                drift[name] = {
                    "reason": str(comparison.get("reason") or "identity_unknown")[:120],
                    "current_identity": identity,
                }
                continue
            try:
                path.unlink()
            except OSError as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            after = observe_file_identity(path)
            if after.get("exists") is False:
                removed.append(str(path))
            else:
                errors.append(f"{name}: cleanup did not make the exact artifact absent")

        if drift:
            recovery.update(
                {
                    "status": "verified_effect_cleanup_blocked",
                    "decision": "user_decision_required",
                    "replay_blocked": True,
                    "atomic_cleanup_drift": drift,
                }
            )
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "side_effect_recovery"
            state.blocked_by = "outside_world_effect_uncertain"
            state.next_action = (
                "preserve retained atomic-overwrite artifacts that changed after cleanup authority "
                "was checkpointed; the verified overwrite must not be replayed"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if errors:
            recovery["atomic_cleanup_last"] = {
                "complete": False,
                "removed": removed,
                "errors": errors,
            }
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            state.stage = "side_effect_recovery"
            state.blocked_by = "outside_world_effect_uncertain"
            state.next_action = (
                "retry exact retained atomic-overwrite artifact cleanup after verified effect; "
                "never replay the overwrite"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        after = {name: observe_file_identity(path) for name, path in paths.items()}
        if any(identity.get("exists") is True for identity in after.values()):
            recovery["atomic_cleanup_last"] = {
                "complete": False,
                "removed": removed,
                "errors": ["an exact retained artifact remains after cleanup"],
            }
            state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
            self.store.save_working_state(state)
            return None

        if protocol is not None:
            self.body.delete_atomic_protocol(
                event_id=event.event_id,
                kind=intent.kind,
                args=dict(intent.args),
                attempt_id=str(protocol.get("attempt_id") or "") or None,
            )
        recovery["atomic_cleanup_last"] = {
            "complete": True,
            "removed": removed,
            "errors": [],
        }
        recovery.update(
            {
                "status": "verified_effect",
                "decision": "complete_without_replay",
                "replay_blocked": False,
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "complete"
        state.next_action = None
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return original_result or self._verified_effect_cleanup_result(event, intent)

    @staticmethod
    def _verified_effect_cleanup_result(event, intent: NativeActionIntent) -> ResidentRunResult:
        path = str(intent.args.get("path") or "")
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=path,
            model_invocations=0,
            reason=(
                "ZN had already independently verified the exact overwrite effect and then "
                "finished the bounded retained-artifact cleanup; the overwrite was not replayed"
            ),
        )

    def _side_effect_recovery_step(self, event, state, *, readiness, thought=None):
        raw_intent = state.data.get("native_action_intent")
        if os.name != "nt" or not isinstance(raw_intent, dict):
            return super()._side_effect_recovery_step(
                event, state, readiness=readiness, thought=thought
            )

        intent = NativeActionIntent.from_dict(raw_intent)
        if not self._is_overwrite_intent(intent):
            return super()._side_effect_recovery_step(
                event, state, readiness=readiness, thought=thought
            )

        raw_recovery = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw_recovery) if isinstance(raw_recovery, dict) else {}
        if str(recovery.get("decision") or "") == self._CLEANUP_DECISION:
            return self._retry_verified_effect_cleanup(event, state, intent)

        # Preserve #23's only automatic verified-absent reconciliation before
        # looking at any commit-start state.
        if self._reconcile_precommit_stage(event, state, intent):
            return None

        protocol = self._matching_commit_protocol(event, state, intent)
        if protocol is not None:
            evidence = self._commit_namespace_evidence(event, state, intent, protocol)
            if evidence.get("classification") == "replacefile_1177_split_retained":
                self._hold_documented_namespace_split(event, state, evidence)
                return None

        # Bypass AtomicOverwriteRecoveryResidentRuntime's old immediate artifact
        # cleanup. The generic overwrite owner still performs the exact read-only
        # target verification and attempt resolution; this layer then checkpoints
        # delayed cleanup authority before any retained artifact is removed.
        result = OverwriteRecoveryResidentRuntime._side_effect_recovery_step(
            self,
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if result is not None and result.success:
            return self._checkpoint_verified_effect_cleanup(event, state, intent, result)
        return result

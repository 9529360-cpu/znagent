from __future__ import annotations

"""Commit-start namespace reconciliation and retained-artifact cleanup for Windows overwrite."""

import os
from pathlib import Path
from typing import Any

from . import atomic_overwrite_protocols, staged_text_write
from .action import NativeActionIntent
from .atomic_overwrite_resident import (
    AtomicOverwriteAwareBody,
    AtomicOverwriteRecoveryResidentRuntime,
)
from .file_identity import compare_file_identities, observe_file_identity
from .models import ExecutionPath, ResidentRunResult
from .overwrite_recovery_resident import OverwriteRecoveryResidentRuntime


class AtomicOverwriteNamespaceAwareBody(AtomicOverwriteAwareBody):
    """Keep the retained-stage repair as a bounded physical Body movement."""

    def repair_retained_stage_to_missing_target(
        self,
        *,
        event_id: str,
        kind: str,
        args: dict[str, Any],
    ) -> None:
        target = self._path_arg(args)
        staging_path, _ = self.atomic_artifact_paths(
            event_id=event_id,
            kind=kind,
            args=args,
        )
        staged_text_write.repair_staged_to_missing_target_windows(staging_path, target)


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

    A proven ReplaceFileW 1177 split may enter a separate repair lifecycle. The
    repair owns its own durable checkpoint, revalidates the exact retained
    namespace before mutation, and asks Body to move the retained stage to the
    still-missing target with no-replace semantics. It is never a replay of the
    original overwrite attempt.
    """

    _CLEANUP_DECISION = "cleanup_verified_atomic_overwrite_artifacts"
    _REPAIR_DECISION = "repair_retained_atomic_namespace_required"
    _REPAIR_STARTED_DECISION = "repair_retained_atomic_namespace"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.body = AtomicOverwriteNamespaceAwareBody(resident=self)

    @staticmethod
    def _content_equivalent(
        expected: dict[str, Any] | None,
        current: dict[str, Any] | None,
    ) -> bool:
        """Compare bounded complete file contents while intentionally ignoring path metadata."""

        if not isinstance(expected, dict) or not isinstance(current, dict):
            return False
        for identity in (expected, current):
            size_bytes = identity.get("size_bytes")
            content_sha256 = identity.get("content_sha256")
            if (
                identity.get("observable") is not True
                or identity.get("stable") is not True
                or identity.get("exists") is not True
                or str(identity.get("type") or "") != "file"
                or identity.get("digest_complete") is not True
                or type(size_bytes) is not int
                or size_bytes < 0
                or not isinstance(content_sha256, str)
                or len(content_sha256) != 64
                or any(character not in "0123456789abcdef" for character in content_sha256)
            ):
                return False
        return bool(
            expected["size_bytes"] == current["size_bytes"]
            and expected["content_sha256"] == current["content_sha256"]
        )

    @staticmethod
    def _stable_missing(identity: dict[str, Any] | None) -> bool:
        return bool(
            isinstance(identity, dict)
            and identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is False
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
        target_missing = self._stable_missing(target_identity)
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
            "checkpoint a new retained-stage namespace repair; do not replay the old overwrite"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

    def _block_namespace_repair(
        self,
        event,
        state,
        recovery: dict[str, Any],
        *,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        recovery.update(
            {
                "status": "namespace_repair_blocked",
                "decision": "user_decision_required",
                "replay_blocked": True,
                "atomic_namespace_repair_blocked": str(reason)[:240],
            }
        )
        if isinstance(evidence, dict):
            recovery["atomic_namespace_repair_evidence"] = evidence
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "preserve retained stage/backup because exact namespace repair authority was lost; "
            "never replay the old overwrite"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

    def _checkpoint_namespace_repair(
        self,
        event,
        state,
        intent: NativeActionIntent,
    ) -> None:
        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        protocol = self._matching_commit_protocol(event, state, intent)
        if protocol is None:
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="matching commit-start protocol is unavailable",
            )
            return
        evidence = self._commit_namespace_evidence(event, state, intent, protocol)
        if evidence.get("classification") != "replacefile_1177_split_retained":
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="current namespace no longer proves the exact retained 1177 split",
                evidence=evidence,
            )
            return

        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        recovery.update(
            {
                "status": "namespace_repair_pending",
                "decision": self._REPAIR_STARTED_DECISION,
                "replay_blocked": True,
                "atomic_namespace_repair": {
                    "version": 1,
                    "protocol_version": int(protocol.get("version") or 0),
                    "attempt_id": str(protocol.get("attempt_id") or ""),
                    "intent_id": intent.intent_id,
                    "target_path": str(intent.args.get("path") or ""),
                    "staging_path": str(staging_path),
                    "backup_path": str(backup_path),
                    "expected_stage_identity": evidence["staging_identity"],
                    "expected_backup_identity": evidence["backup_identity"],
                },
            }
        )
        state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
        state.stage = "side_effect_recovery"
        state.blocked_by = "outside_world_effect_uncertain"
        state.next_action = (
            "revalidate the exact retained split and move only the retained stage to the "
            "still-missing target with no-replace semantics"
        )
        self._sync_execution_context(event, state)
        # Repair authority is durable before Body may cross the namespace boundary.
        self.store.save_working_state(state)

    def _matching_repair_checkpoint(
        self,
        event,
        state,
        intent: NativeActionIntent,
        protocol: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        repair = recovery.get("atomic_namespace_repair")
        if not isinstance(repair, dict):
            return None
        staging_path, backup_path = self.body.atomic_artifact_paths(
            event_id=event.event_id,
            kind=intent.kind,
            args=dict(intent.args),
        )
        if not (
            int(repair.get("version") or 0) == 1
            and int(repair.get("protocol_version") or 0)
            == int(protocol.get("version") or 0)
            and str(repair.get("attempt_id") or "")
            == str(protocol.get("attempt_id") or "")
            and str(repair.get("intent_id") or "") == intent.intent_id
            and str(repair.get("target_path") or "")
            == str(intent.args.get("path") or "")
            and str(repair.get("staging_path") or "") == str(staging_path)
            and str(repair.get("backup_path") or "") == str(backup_path)
            and isinstance(repair.get("expected_stage_identity"), dict)
            and isinstance(repair.get("expected_backup_identity"), dict)
        ):
            return None
        return dict(repair)

    def _finish_namespace_repair_effect(
        self,
        event,
        state,
        intent: NativeActionIntent,
        repair: dict[str, Any],
    ):
        attempt_id = str(repair.get("attempt_id") or "").strip()
        if not attempt_id or not self.body.resolve_uncertain_attempt(
            attempt_id,
            event_id=event.event_id,
            status="verified_effect",
        ):
            raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
            recovery = dict(raw) if isinstance(raw, dict) else {}
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="repaired target effect could not close the matching old attempt",
            )
            return None
        result = ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=str(intent.args.get("path") or ""),
            model_invocations=0,
            reason=(
                "ZN independently observed the exact retained stage at the target after a "
                "separate no-replace namespace repair; the stale overwrite was not replayed"
            ),
        )
        return self._checkpoint_verified_effect_cleanup(event, state, intent, result)

    def _reconcile_namespace_repair(
        self,
        event,
        state,
        intent: NativeActionIntent,
    ):
        raw = state.data.get(self._SIDE_EFFECT_RECOVERY_KEY)
        recovery = dict(raw) if isinstance(raw, dict) else {}
        protocol = self._matching_commit_protocol(event, state, intent)
        if protocol is None:
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="matching commit-start protocol disappeared during repair",
            )
            return None
        repair = self._matching_repair_checkpoint(event, state, intent, protocol)
        if repair is None:
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="durable namespace repair checkpoint does not match current protocol",
            )
            return None

        staging_path = Path(str(repair["staging_path"]))
        backup_path = Path(str(repair["backup_path"]))
        target_path = Path(str(repair["target_path"]))

        def observe() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            return (
                observe_file_identity(target_path),
                observe_file_identity(staging_path),
                observe_file_identity(backup_path),
            )

        target_identity, staging_identity, backup_identity = observe()
        stage_comparison = compare_file_identities(
            repair["expected_stage_identity"], staging_identity
        )
        backup_comparison = compare_file_identities(
            repair["expected_backup_identity"], backup_identity
        )
        target_matches_stage = self._content_equivalent(
            repair["expected_stage_identity"], target_identity
        )
        target_missing = self._stable_missing(target_identity)
        stage_missing = self._stable_missing(staging_identity)
        stage_exact = stage_comparison.get("exact") is True
        backup_exact = backup_comparison.get("exact") is True

        if target_matches_stage and stage_missing and backup_exact:
            return self._finish_namespace_repair_effect(
                event, state, intent, repair
            )

        if target_missing and stage_exact and backup_exact:
            try:
                self.body.repair_retained_stage_to_missing_target(
                    event_id=event.event_id,
                    kind=intent.kind,
                    args=dict(intent.args),
                )
            except OSError as exc:
                target_identity, staging_identity, backup_identity = observe()
                if (
                    self._content_equivalent(
                        repair["expected_stage_identity"], target_identity
                    )
                    and self._stable_missing(staging_identity)
                    and compare_file_identities(
                        repair["expected_backup_identity"], backup_identity
                    ).get("exact")
                    is True
                ):
                    return self._finish_namespace_repair_effect(
                        event, state, intent, repair
                    )
                if (
                    self._stable_missing(target_identity)
                    and compare_file_identities(
                        repair["expected_stage_identity"], staging_identity
                    ).get("exact")
                    is True
                    and compare_file_identities(
                        repair["expected_backup_identity"], backup_identity
                    ).get("exact")
                    is True
                ):
                    recovery["atomic_namespace_repair_last_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )[:240]
                    state.data[self._SIDE_EFFECT_RECOVERY_KEY] = recovery
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                    return None
                self._block_namespace_repair(
                    event,
                    state,
                    recovery,
                    reason="namespace changed while the no-replace repair was attempted",
                    evidence={
                        "target_identity": target_identity,
                        "staging_identity": staging_identity,
                        "backup_identity": backup_identity,
                    },
                )
                return None

            target_identity, staging_identity, backup_identity = observe()
            if (
                self._content_equivalent(
                    repair["expected_stage_identity"], target_identity
                )
                and self._stable_missing(staging_identity)
                and compare_file_identities(
                    repair["expected_backup_identity"], backup_identity
                ).get("exact")
                is True
            ):
                return self._finish_namespace_repair_effect(
                    event, state, intent, repair
                )
            self._block_namespace_repair(
                event,
                state,
                recovery,
                reason="no-replace repair returned without the exact repaired namespace",
                evidence={
                    "target_identity": target_identity,
                    "staging_identity": staging_identity,
                    "backup_identity": backup_identity,
                },
            )
            return None

        self._block_namespace_repair(
            event,
            state,
            recovery,
            reason="fresh target/stage/backup reality no longer matches durable repair authority",
            evidence={
                "target_identity": target_identity,
                "staging_identity": staging_identity,
                "backup_identity": backup_identity,
                "stage_exact": stage_exact,
                "backup_exact": backup_exact,
                "target_matches_stage": target_matches_stage,
            },
        )
        return None

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
        decision = str(recovery.get("decision") or "")
        if decision == self._CLEANUP_DECISION:
            return self._retry_verified_effect_cleanup(event, state, intent)
        if decision == self._REPAIR_STARTED_DECISION:
            return self._reconcile_namespace_repair(event, state, intent)
        if decision == self._REPAIR_DECISION:
            self._checkpoint_namespace_repair(event, state, intent)
            return None

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

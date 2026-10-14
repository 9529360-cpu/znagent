from __future__ import annotations

"""Workspace-scoped file actions for the generic agent loop (P0).

On Linux the generic action loop previously offered only the read-only
``windows.application.resolve`` action, so an agent asked to "write X to a
file" had no file action to propose and burned its bounded action budget.
These four actions close that gap: the agent can read, create, overwrite
and delete files, but only inside the ZN workspace (``your_files/`` and
``drafts/``), only through the workspace discipline, and destructive
actions (overwrite, delete) only through the existing approval cards.

Security shape, in one paragraph: the model proposes a workspace-relative
``path``; the approval scope/target are derived from the canonical
resolved path (never from model-supplied ``approval_*`` args), so an
``always_allow`` rule can only ever bless one concrete file; the Body
handler re-resolves the same path before any effect; delete moves the file
into workspace trash (recoverable, never a direct unlink); and the
verifier re-reads the file (or its trash entry) as independent evidence.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from .action_execution import ActionObservation, ActionVerification
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .workspace_file_discipline import (
    list_trash,
    resolve_agent_workspace_path,
)

WORKSPACE_FILE_READ = "workspace.file.read"
WORKSPACE_FILE_WRITE = "workspace.file.write"
WORKSPACE_FILE_OVERWRITE = "workspace.file.overwrite"
WORKSPACE_FILE_DELETE = "workspace.file.delete"

_WORKSPACE_FILE_ACTIONS = (
    WORKSPACE_FILE_READ,
    WORKSPACE_FILE_WRITE,
    WORKSPACE_FILE_OVERWRITE,
    WORKSPACE_FILE_DELETE,
)


def _availability_probe(
    workspace_root: Path,
    approval_available: bool,
):
    def probe(descriptor: ActionDescriptor) -> ActionAvailability:
        if not approval_available:
            # Fail closed: without an approval store there is no gate, so
            # the destructive actions must not be offered at all.
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="approval store is unavailable; workspace file actions need an approval gate",
                evidence={"source": "workspace_file_actions"},
            )
        resolved = Path(workspace_root).expanduser()
        if not resolved.is_absolute():
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="workspace root is not absolute",
                evidence={"source": "workspace_file_actions"},
            )
        resolved = resolved.resolve(strict=False)
        if not resolved.is_dir():
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="workspace root does not exist",
                evidence={
                    "source": "workspace_file_actions",
                    "workspace_root": str(resolved),
                },
            )
        if not os.access(resolved, os.W_OK):
            return ActionAvailability(
                descriptor.action_id,
                "unavailable",
                reason="workspace root is not writable",
                evidence={
                    "source": "workspace_file_actions",
                    "workspace_root": str(resolved),
                },
            )
        return ActionAvailability(
            descriptor.action_id,
            "available",
            reason="workspace root exists and is writable",
            evidence={
                "source": "workspace_file_actions",
                "workspace_root": str(resolved),
            },
        )

    return probe


def register_workspace_file_actions(
    registry: ActionFabricRegistry,
    *,
    workspace_root: str | Path,
    approval_available: bool = True,
) -> None:
    """Register the four workspace file actions into an Action Fabric registry."""

    root = Path(workspace_root).expanduser()
    probe = _availability_probe(root, approval_available)

    registry.register(
        ActionDescriptor(
            action_id=WORKSPACE_FILE_READ,
            provider="zn.workspace",
            description=(
                "Read one workspace file as text. Path must be workspace-relative "
                "under your_files/ (deliverables) or drafts/ (drafts). Never an "
                "absolute path, never '..', never hidden_files/ or trash."
            ),
            body_action_kind="workspace_file_read",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "number", "minimum": 1},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "chars": {"type": "integer"},
                    "returned_chars": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                    "sha256": {"type": "string"},
                },
            },
            effect_class="read_only",
            sensitivity="workspace_file_content",
            postconditions=("fresh workspace file text is returned",),
            verification=("the file readback itself is current workspace evidence",),
            reversibility="not_applicable",
            replay_semantics="read_only",
            tags=("workspace", "file", "read", "sense", "body"),
        ),
        availability_probe=probe,
    )
    registry.register(
        ActionDescriptor(
            action_id=WORKSPACE_FILE_WRITE,
            provider="zn.workspace",
            description=(
                "Create one new workspace file with the given text content. Path "
                "must be workspace-relative under your_files/ (deliverables) or "
                "drafts/ (drafts). Fails if the file already exists: use "
                "workspace.file.overwrite to replace an existing file, which "
                "requires user approval."
            ),
            body_action_kind="workspace_file_write",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "written_chars": {"type": "integer"},
                    "sha256": {"type": "string"},
                },
            },
            effect_class="potential_side_effect",
            required_authority=("body_action",),
            sensitivity="workspace_file_content",
            preconditions=("the target workspace file does not already exist",),
            postconditions=("one new workspace file exists with the requested content",),
            verification=("fresh file readback SHA-256 matches the requested content",),
            reversibility=(
                "delete the created file through workspace.file.delete (approval-gated)"
            ),
            replay_semantics="verify_before_replay",
            tags=("workspace", "file", "write", "body"),
        ),
        availability_probe=probe,
    )
    registry.register(
        ActionDescriptor(
            action_id=WORKSPACE_FILE_OVERWRITE,
            provider="zn.workspace",
            description=(
                "Replace the full content of one existing workspace file. Path "
                "must be workspace-relative under your_files/ or drafts/. The "
                "previous content is not retained, so this action requires user "
                "approval. Fails if the file does not exist: use "
                "workspace.file.write to create one."
            ),
            body_action_kind="workspace_file_overwrite",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "written_chars": {"type": "integer"},
                    "sha256": {"type": "string"},
                },
            },
            effect_class="irreversible_side_effect",
            required_authority=("body_action",),
            sensitivity="workspace_file_content",
            preconditions=("the target workspace file already exists",),
            postconditions=("the workspace file content equals the requested content",),
            verification=("fresh file readback SHA-256 matches the requested content",),
            reversibility="none: previous content is not retained; re-write to restore",
            replay_semantics="verify_before_replay",
            tags=(
                "workspace",
                "file",
                "overwrite",
                "body",
                "approval:production_change",
            ),
        ),
        availability_probe=probe,
    )
    registry.register(
        ActionDescriptor(
            action_id=WORKSPACE_FILE_DELETE,
            provider="zn.workspace",
            description=(
                "Delete one existing workspace file by moving it into workspace "
                "trash (recoverable). Path must be workspace-relative under "
                "your_files/ or drafts/. Requires user approval. Directories "
                "are refused."
            ),
            body_action_kind="workspace_file_delete",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string"},
                    "original_path": {"type": "string"},
                    "deleted_at": {"type": "string"},
                    "trash_path": {"type": "string"},
                },
            },
            effect_class="irreversible_side_effect",
            required_authority=("body_action",),
            sensitivity="workspace_file_deletion",
            preconditions=("the target workspace file exists and is a regular file",),
            postconditions=(
                "the file no longer exists at its workspace path",
                "a trash entry records the original path for restore",
            ),
            verification=(
                "fresh file-absence check plus trash entry with the same original path",
            ),
            reversibility="restore the trash entry to its original path",
            replay_semantics="verify_before_replay",
            tags=("workspace", "file", "delete", "body", "approval:delete"),
        ),
        availability_probe=probe,
    )


def _workspace_scope(root: Path):
    """Approval scope/target resolver: canonical workspace-relative path.

    Bound to one concrete file (``workspace:<rel-path>``), so an
    ``always_allow`` rule can only bless that one file. Model-supplied
    ``approval_scope`` / ``approval_target`` args are ignored here.
    """

    resolved_root = Path(root).expanduser().resolve(strict=False)

    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        target, _kind = resolve_agent_workspace_path(
            resolved_root, str(args.get("path") or "")
        )
        rel = target.relative_to(resolved_root).as_posix()
        scope = f"workspace:{rel}"
        return scope, scope, ""

    return resolver


def _overwrite_scope(root: Path):
    resolved_root = Path(root).expanduser().resolve(strict=False)

    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        target, _kind = resolve_agent_workspace_path(
            resolved_root, str(args.get("path") or "")
        )
        rel = target.relative_to(resolved_root).as_posix()
        scope = f"workspace:{rel}"
        preview = " ".join(str(args.get("content") or "").split())[:200]
        return scope, scope, preview

    return resolver


def _argument_binder(root: Path):
    root_text = str(Path(root).expanduser())

    def binder(args: Mapping[str, Any]) -> dict[str, Any]:
        bound = dict(args)
        bound["workspace_root"] = root_text
        return bound

    return binder


def _observe_file(root: Path, request: Any) -> ActionObservation:
    target, _kind = resolve_agent_workspace_path(
        root, str(request.args.get("path") or "")
    )
    if not target.is_file():
        return ActionObservation(
            request.action_id,
            "workspace_file_readback",
            data={"path": str(target), "exists": False},
        )
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return ActionObservation(
        request.action_id,
        "workspace_file_readback",
        data={
            "path": str(target),
            "exists": True,
            "size_bytes": int(target.stat().st_size),
            "sha256": digest,
        },
    )


def _verify_write(root: Path, request: Any, observation: ActionObservation, _result: Any) -> ActionVerification:
    data = dict(observation.data or {})
    target, _kind = resolve_agent_workspace_path(
        root, str(request.args.get("path") or "")
    )
    expected = hashlib.sha256(
        str(request.args.get("content") or "").encode("utf-8")
    ).hexdigest()
    verified = bool(
        data.get("exists") is True
        and data.get("path") == str(target)
        and data.get("sha256") == expected
    )
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh workspace file readback SHA-256 matches the requested content"
            if verified
            else "fresh workspace file readback does not match the requested content"
        ),
        evidence={
            "path": data.get("path"),
            "expected_sha256": expected,
            "observed_sha256": data.get("sha256"),
        },
        observed_at=observation.observed_at,
    )


def _observe_delete(root: Path, request: Any) -> ActionObservation:
    target, _kind = resolve_agent_workspace_path(
        root, str(request.args.get("path") or "")
    )
    entries = [
        entry.entry_id
        for entry in list_trash(root)
        if entry.original_path == str(target)
    ]
    return ActionObservation(
        request.action_id,
        "workspace_file_absence_and_trash_readback",
        data={
            "path": str(target),
            "exists": bool(target.exists()),
            "trash_entry_ids": entries,
        },
    )


def _verify_delete(
    request: Any, observation: ActionObservation, _result: Any
) -> ActionVerification:
    data = dict(observation.data or {})
    verified = bool(
        data.get("exists") is False and data.get("trash_entry_ids")
    )
    return ActionVerification(
        "verified" if verified else "failed",
        (
            "fresh readback proves the file is gone and a trash entry records it"
            if verified
            else "fresh readback does not prove deletion plus a trash entry"
        ),
        evidence={
            "path": data.get("path"),
            "exists": data.get("exists"),
            "trash_entry_ids": data.get("trash_entry_ids"),
        },
        observed_at=observation.observed_at,
    )


def register_workspace_file_verification(
    runtime: Any,
    *,
    workspace_root: str | Path,
) -> None:
    """Bind workspace root, approval scopes and verifiers into an execution runtime."""

    root = Path(workspace_root).expanduser()
    binder = _argument_binder(root)
    for action_id in _WORKSPACE_FILE_ACTIONS:
        runtime.register_argument_binder(action_id, binder)
    runtime.register_approval_scope(WORKSPACE_FILE_OVERWRITE, _overwrite_scope(root))
    runtime.register_approval_scope(WORKSPACE_FILE_DELETE, _workspace_scope(root))
    for action_id in (WORKSPACE_FILE_WRITE, WORKSPACE_FILE_OVERWRITE):
        runtime.register_verification(
            action_id,
            observe=lambda request, result, root=root: _observe_file(root, request),
            verify=lambda request, observation, result, root=root: _verify_write(
                root, request, observation, result
            ),
        )
    runtime.register_verification(
        WORKSPACE_FILE_DELETE,
        observe=lambda request, result, root=root: _observe_delete(root, request),
        verify=_verify_delete,
    )

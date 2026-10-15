from __future__ import annotations

"""Workspace checkpoints (CUR-3): snapshot / preview / restore, git-free.

A checkpoint is a local, on-disk snapshot of the user-visible workspace
state -- ``your_files/`` (deliverables) and ``drafts/`` -- taken before a
major change, so the change can be previewed and undone with one action.
Snapshots are plain file copies plus a JSON manifest; they are deliberately
NOT git commits, so they work in a workspace that is not a git checkout
and never touch git history.

This is a different object from the workflow ``Checkpoint`` in
``team_runner.py`` (AF-2: pulse-boundary resume state for a team run).
That checkpoint answers "where do I resume execution"; this one answers
"what did the workspace files look like before this change". The two
complement each other and share no storage.

Rules (decided, not negotiable in this module):

* Restore never destroys history. Every restore first takes an automatic
  backup snapshot of the current state (trigger ``pre_restore``), so the
  pre-restore state stays recoverable through that backup's id.
* Restore only restores the selected snapshot, and only within the
  snapshotted scope (``your_files/`` + ``drafts/``). Internal bookkeeping
  (``hidden_files/``) and trash (``.trash/``) are never snapshotted and
  never touched by a restore.
* There is no delete API for checkpoints. History is append-only.
* External side effects cannot be restored. A restore only puts files
  back; messages already sent, payments already made, or cloud state
  already synced stay as they are. Every restore result carries
  :data:`EXTERNAL_SIDE_EFFECTS_NOTICE` plus a verification checklist,
  and callers must surface it.
* Symlinks are refused, fail-closed: a snapshot never follows a link
  out of the workspace, and a restore never writes through a link.

Auto-snapshot triggers (explicit and testable):

* ``manual`` -- explicit ``checkpoint_create`` RPC / direct call.
* ``pre_restore`` -- automatic backup taken by :meth:`CheckpointStore.restore`
  before any file is touched.
* ``pre_undo`` -- automatic snapshot taken by the daemon before an
  approved-change undo (``approval_undo`` RPC).
* ``pre_write`` -- available to future destructive-write call sites
  through :meth:`CheckpointStore.ensure_pre_change_snapshot`; no
  call site wires it yet.

Dedup: creating a snapshot whose file contents hash-identically to the
newest existing snapshot returns that newest snapshot instead of writing
a duplicate. A no-change auto-snapshot therefore never spams history.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCOPE_DIRS = ("your_files", "drafts")
_CHECKPOINTS_DIRNAME = "checkpoints"
_MANIFEST_FILENAME = "manifest.json"
_FILES_DIRNAME = "files"
_TMP_PREFIX = ".tmp-"

TRIGGER_MANUAL = "manual"
TRIGGER_PRE_RESTORE = "pre_restore"
TRIGGER_PRE_UNDO = "pre_undo"
TRIGGER_PRE_WRITE = "pre_write"
_KNOWN_TRIGGERS = frozenset(
    (TRIGGER_MANUAL, TRIGGER_PRE_RESTORE, TRIGGER_PRE_UNDO, TRIGGER_PRE_WRITE)
)

_CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EXTERNAL_SIDE_EFFECTS_NOTICE = (
    "外部副作用未恢复，需核对：恢复只还原了工作区文件。已经发生的外部副作用"
    "（已发送的消息/邮件、已执行的外部操作、已同步的云端状态、已产生的扣费）"
    "无法通过恢复撤销。"
)

EXTERNAL_SIDE_EFFECTS_CHECKLIST = (
    "核对清单：1) 检查已发送的消息/邮件是否需要手动说明或撤回；"
    "2) 检查外部系统（云端文档、日历、账单、第三方服务）的状态是否与恢复后的文件一致；"
    "3) 如不一致，以外部系统为准，手动修正，不要再次恢复覆盖。"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_checkpoint_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def _validate_checkpoint_id(checkpoint_id: str) -> str:
    normalized = str(checkpoint_id or "").strip()
    if not normalized or not _CHECKPOINT_ID_RE.match(normalized):
        raise ValueError(f"invalid checkpoint id: {checkpoint_id!r}")
    if normalized in (".", "..") or "/" in normalized or "\\" in normalized:
        raise ValueError(f"invalid checkpoint id: {checkpoint_id!r}")
    return normalized


def _validate_relative_path(rel: str) -> str:
    normalized = str(rel or "").replace("\\", "/").strip()
    if not normalized:
        raise ValueError("checkpoint file path is empty")
    if normalized.startswith("/") or normalized in (".", ".."):
        raise ValueError(f"checkpoint file path escapes scope: {rel!r}")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"checkpoint file path escapes scope: {rel!r}")
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CheckpointFileEntry:
    """One snapshotted file: relative path within the workspace + digest."""

    path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class WorkspaceCheckpoint:
    """A snapshot of the workspace files at one moment."""

    checkpoint_id: str
    created_at: str
    trigger: str
    reason: str
    files: tuple[CheckpointFileEntry, ...] = ()
    total_bytes: int = 0
    reused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "trigger": self.trigger,
            "reason": self.reason,
            "files": [entry.to_dict() for entry in self.files],
            "total_bytes": self.total_bytes,
            "reused": self.reused,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "WorkspaceCheckpoint":
        if not isinstance(raw, dict):
            raise ValueError("checkpoint manifest must be an object")
        checkpoint_id = _validate_checkpoint_id(str(raw.get("checkpoint_id") or ""))
        files_raw = raw.get("files")
        if not isinstance(files_raw, list):
            raise ValueError("checkpoint manifest files must be a list")
        entries = []
        for item in files_raw:
            if not isinstance(item, dict):
                raise ValueError("checkpoint manifest file entry must be an object")
            entries.append(
                CheckpointFileEntry(
                    path=_validate_relative_path(str(item.get("path") or "")),
                    sha256=str(item.get("sha256") or ""),
                    size=int(item.get("size") or 0),
                )
            )
        return WorkspaceCheckpoint(
            checkpoint_id=checkpoint_id,
            created_at=str(raw.get("created_at") or ""),
            trigger=str(raw.get("trigger") or ""),
            reason=str(raw.get("reason") or ""),
            files=tuple(entries),
            total_bytes=int(raw.get("total_bytes") or 0),
            reused=False,
        )


class CheckpointStore:
    """Append-only local store for workspace checkpoints.

    Layout under ``<workspace_root>/hidden_files/checkpoints/``::

        <checkpoint_id>/manifest.json
        <checkpoint_id>/files/<relative path...>   (byte copies)

    The store root lives in ``hidden_files/`` (internal bookkeeping per
    the M12 workspace discipline), never in ``your_files/``.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        checkpoints_dir: str | Path | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser()
        if checkpoints_dir is not None:
            self.checkpoints_dir = Path(checkpoints_dir).expanduser()
        else:
            self.checkpoints_dir = (
                self.workspace_root / "hidden_files" / _CHECKPOINTS_DIRNAME
            )

    # -- creation -----------------------------------------------------

    def create(
        self,
        *,
        trigger: str = TRIGGER_MANUAL,
        reason: str = "",
    ) -> WorkspaceCheckpoint:
        """Snapshot the current workspace files.

        Returns the newest identical snapshot instead of writing a
        duplicate when nothing changed since the last snapshot.
        """
        if trigger not in _KNOWN_TRIGGERS:
            raise ValueError(f"unknown checkpoint trigger: {trigger!r}")
        entries = self._collect_current_entries()
        newest = self._newest()
        if newest is not None and self._same_content(newest, entries):
            return WorkspaceCheckpoint(
                checkpoint_id=newest.checkpoint_id,
                created_at=newest.created_at,
                trigger=newest.trigger,
                reason=newest.reason,
                files=newest.files,
                total_bytes=newest.total_bytes,
                reused=True,
            )
        checkpoint_id = _new_checkpoint_id()
        checkpoint = WorkspaceCheckpoint(
            checkpoint_id=checkpoint_id,
            created_at=_utc_now_iso(),
            trigger=trigger,
            reason=str(reason or "").strip(),
            files=tuple(entries),
            total_bytes=sum(entry.size for entry in entries),
            reused=False,
        )
        self._write_checkpoint(checkpoint)
        return checkpoint

    def ensure_pre_change_snapshot(
        self,
        *,
        trigger: str,
        reason: str = "",
    ) -> WorkspaceCheckpoint:
        """Auto-snapshot entry point for destructive-change call sites.

        Thin wrapper over :meth:`create` so trigger points share one
        dedup rule: a no-change call returns the newest identical
        snapshot instead of writing a duplicate.
        """
        return self.create(trigger=trigger, reason=reason)

    # -- reads ----------------------------------------------------------

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """List checkpoints, newest first (manifests only, no file bytes)."""
        checkpoints = self._read_all()
        checkpoints.sort(key=lambda item: item.created_at, reverse=True)
        bounded = max(1, min(200, int(limit or 50)))
        return [item.to_dict() for item in checkpoints[:bounded]]

    def get(self, checkpoint_id: str) -> WorkspaceCheckpoint:
        """Load one checkpoint manifest; raises ValueError when unknown."""
        normalized = _validate_checkpoint_id(checkpoint_id)
        manifest_path = self._checkpoint_dir(normalized) / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ValueError(f"unknown checkpoint: {normalized!r}")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"checkpoint manifest is corrupt: {normalized!r}") from exc
        return WorkspaceCheckpoint.from_dict(raw)

    def preview(self, checkpoint_id: str) -> dict[str, Any]:
        """Diff a checkpoint against the current workspace without touching disk.

        Returns the manifest plus per-file status, where the status
        describes what a restore of this checkpoint WILL DO:
        ``added`` (restore brings the file back), ``deleted`` (restore
        removes the file), ``modified`` (restore overwrites it),
        ``unchanged``. Also carries the external-side-effects notice:
        previewing a restore must show what restore cannot undo.
        """
        checkpoint = self.get(checkpoint_id)
        current = {entry.path: entry for entry in self._collect_current_entries()}
        snapshotted = {entry.path: entry for entry in checkpoint.files}
        diff: list[dict[str, Any]] = []
        for path in sorted(set(current) | set(snapshotted)):
            before = snapshotted.get(path)
            after = current.get(path)
            if before is None and after is not None:
                status = "deleted"
            elif before is not None and after is None:
                status = "added"
            elif before is not None and after is not None and before.sha256 != after.sha256:
                status = "modified"
            else:
                status = "unchanged"
            diff.append(
                {
                    "path": path,
                    "status": status,
                    "checkpoint_sha256": before.sha256 if before else None,
                    "current_sha256": after.sha256 if after else None,
                }
            )
        return {
            "checkpoint": checkpoint.to_dict(),
            "diff": diff,
            "external_side_effects_notice": EXTERNAL_SIDE_EFFECTS_NOTICE,
            "external_side_effects_checklist": EXTERNAL_SIDE_EFFECTS_CHECKLIST,
        }

    # -- restore --------------------------------------------------------

    def restore(
        self,
        checkpoint_id: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        """Restore the workspace files to exactly one selected snapshot.

        Steps, in order:

        1. Load and validate the target snapshot.
        2. Take an automatic ``pre_restore`` backup of the current state.
           This is unconditional: the pre-restore state stays recoverable
           through the returned ``backup_checkpoint_id``.
        3. Apply the snapshot within scope: files absent from the snapshot
           are removed, snapshot files are written back byte-for-byte and
           verified by sha256 after writing.
        4. Return the backup id plus the external-side-effects notice and
           verification checklist. Callers must surface them: restore
           cannot undo side effects that already happened outside the
           workspace.

        Raises ValueError for unknown ids, symlinks, or verification
        failures. On a mid-restore failure the backup snapshot still
        exists, so the pre-restore state can be restored again.
        """
        target = self.get(checkpoint_id)
        backup = self.ensure_pre_change_snapshot(
            trigger=TRIGGER_PRE_RESTORE,
            reason=f"pre-restore backup before restoring {target.checkpoint_id}"
            + (f": {reason}" if str(reason or "").strip() else ""),
        )
        snapshot_dir = self._checkpoint_dir(target.checkpoint_id) / _FILES_DIRNAME
        wanted = {entry.path: entry for entry in target.files}
        current = {entry.path: entry for entry in self._collect_current_entries()}
        # Remove in-scope files that the snapshot does not contain.
        for path in sorted(set(current) - set(wanted)):
            victim = self.workspace_root / path
            if victim.is_symlink() or not victim.is_file():
                raise ValueError(
                    f"restore refused: {path!r} is a symlink or not a regular file"
                )
            victim.unlink()
        # Write snapshot files back, verifying each one after writing.
        for path in sorted(wanted):
            entry = wanted[path]
            source = snapshot_dir / path
            if source.is_symlink() or not source.is_file():
                raise ValueError(
                    f"restore refused: snapshot file {path!r} is missing or a symlink"
                )
            destination = self.workspace_root / path
            if destination.is_symlink():
                raise ValueError(
                    f"restore refused: {path!r} is a symlink in the workspace"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if _sha256_file(destination) != entry.sha256:
                raise ValueError(
                    f"restore verification failed for {path!r}: sha256 mismatch"
                )
        self._prune_empty_scope_dirs()
        return {
            "restored_checkpoint_id": target.checkpoint_id,
            "backup_checkpoint_id": backup.checkpoint_id,
            "backup_reused": backup.reused,
            "restored_files": len(target.files),
            "external_side_effects_notice": EXTERNAL_SIDE_EFFECTS_NOTICE,
            "external_side_effects_checklist": EXTERNAL_SIDE_EFFECTS_CHECKLIST,
        }

    # -- internals ------------------------------------------------------

    def _checkpoint_dir(self, checkpoint_id: str) -> Path:
        return self.checkpoints_dir / _validate_checkpoint_id(checkpoint_id)

    def _collect_current_entries(self) -> list[CheckpointFileEntry]:
        """Hash every regular file under the snapshot scope, git-free."""
        entries: list[CheckpointFileEntry] = []
        for scope in _SCOPE_DIRS:
            scope_dir = self.workspace_root / scope
            if scope_dir.is_symlink():
                raise ValueError(
                    f"snapshot refused: scope {scope!r} is a symlink"
                )
            if not scope_dir.is_dir():
                continue
            for path in sorted(scope_dir.rglob("*")):
                if path.is_symlink():
                    raise ValueError(
                        f"snapshot refused: {path.relative_to(self.workspace_root)} "
                        "is a symlink; snapshots never follow links"
                    )
                if not path.is_file():
                    continue
                rel = path.relative_to(self.workspace_root).as_posix()
                entries.append(
                    CheckpointFileEntry(
                        path=_validate_relative_path(rel),
                        sha256=_sha256_file(path),
                        size=path.stat().st_size,
                    )
                )
        entries.sort(key=lambda entry: entry.path)
        return entries

    @staticmethod
    def _same_content(
        checkpoint: WorkspaceCheckpoint,
        entries: list[CheckpointFileEntry],
    ) -> bool:
        if len(checkpoint.files) != len(entries):
            return False
        return all(
            old.path == new.path
            and old.sha256 == new.sha256
            and old.size == new.size
            for old, new in zip(checkpoint.files, entries)
        )

    def _read_all(self) -> list[WorkspaceCheckpoint]:
        checkpoints: list[WorkspaceCheckpoint] = []
        if not self.checkpoints_dir.is_dir():
            return checkpoints
        for child in sorted(self.checkpoints_dir.iterdir()):
            if child.name.startswith(_TMP_PREFIX) or not child.is_dir():
                continue
            manifest_path = child / _MANIFEST_FILENAME
            if not manifest_path.is_file():
                continue
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                checkpoints.append(WorkspaceCheckpoint.from_dict(raw))
            except (ValueError, OSError, UnicodeDecodeError):
                continue
        return checkpoints

    def _newest(self) -> WorkspaceCheckpoint | None:
        checkpoints = self._read_all()
        if not checkpoints:
            return None
        checkpoints.sort(key=lambda item: item.created_at)
        return checkpoints[-1]

    def _write_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> None:
        """Write files + manifest to a temp dir, then rename into place."""
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.checkpoints_dir / (
            f"{_TMP_PREFIX}{checkpoint.checkpoint_id}-{secrets.token_hex(4)}"
        )
        tmp_dir.mkdir(parents=True, exist_ok=False)
        try:
            files_dir = tmp_dir / _FILES_DIRNAME
            for entry in checkpoint.files:
                source = self.workspace_root / entry.path
                destination = files_dir / entry.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if _sha256_file(destination) != entry.sha256:
                    raise ValueError(
                        f"snapshot verification failed for {entry.path!r}"
                    )
            manifest_path = tmp_dir / _MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_dir, self._checkpoint_dir(checkpoint.checkpoint_id))
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def _prune_empty_scope_dirs(self) -> None:
        """Remove empty directories left behind inside the snapshot scope."""
        for scope in _SCOPE_DIRS:
            scope_dir = self.workspace_root / scope
            if not scope_dir.is_dir():
                continue
            for path in sorted(scope_dir.rglob("*"), reverse=True):
                if path.is_dir() and not path.is_symlink():
                    try:
                        path.rmdir()
                    except OSError:
                        continue

from __future__ import annotations

"""Windows staged text replacement primitives for ZN-owned overwrite safety."""

import ctypes
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ERROR_UNABLE_TO_MOVE_REPLACEMENT_2 = 1177
_MOVEFILE_WRITE_THROUGH = 0x00000008
_FILE_ATTRIBUTE_READONLY = getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x00000001)
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x00000400,
)


@dataclass(frozen=True, slots=True)
class StagedTextWriteResult:
    written_chars: int
    strategy: str
    staging_path: str
    backup_path: str | None
    cleanup_pending: tuple[str, ...] = ()


class StagedWriteCommitUncertainError(RuntimeError):
    """A Windows replacement call changed namespace state before reporting failure."""

    def __init__(
        self,
        message: str,
        *,
        staging_path: Path,
        backup_path: Path | None,
        strategy: str,
        error_code: int,
    ) -> None:
        super().__init__(message)
        self.staging_path = Path(staging_path)
        self.backup_path = Path(backup_path) if backup_path is not None else None
        self.strategy = str(strategy)
        self.error_code = int(error_code)


def overwrite_artifact_paths(target: Path, token: str) -> tuple[Path, Path]:
    """Return privacy-bounded same-directory artifact names for one overwrite."""

    target = Path(target)
    digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:24]
    return (
        target.parent / f".zn-write-{digest}.tmp",
        target.parent / f".zn-backup-{digest}.tmp",
    )


def cleanup_overwrite_artifacts(
    target: Path,
    token: str,
    *,
    include_staging: bool = True,
    include_backup: bool = True,
) -> dict[str, object]:
    """Best-effort cleanup of exact deterministic artifacts owned by one write."""

    staging_path, backup_path = overwrite_artifact_paths(Path(target), token)
    artifacts: list[Path] = []
    if include_staging:
        artifacts.append(staging_path)
    if include_backup:
        artifacts.append(backup_path)

    removed: list[str] = []
    errors: list[str] = []
    for artifact in artifacts:
        if not os.path.lexists(str(artifact)):
            continue
        try:
            artifact.unlink()
        except OSError as exc:
            errors.append(f"{artifact.name}: {type(exc).__name__}: {exc}")
        else:
            removed.append(str(artifact))
    return {
        "removed": removed,
        "errors": errors,
        "complete": not errors,
    }


def _write_stage(path: Path, content: str, encoding: str) -> int:
    with path.open("x", encoding=encoding) as handle:
        written = handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return int(written)


def _validate_existing_windows_target(path: Path) -> None:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    if stat.S_ISLNK(int(info.st_mode)) or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(
            f"atomic overwrite refuses Windows reparse/symlink target: {path}"
        )
    if not stat.S_ISREG(int(info.st_mode)):
        raise OSError(f"atomic overwrite requires a regular file target: {path}")
    if attributes & _FILE_ATTRIBUTE_READONLY:
        raise PermissionError(f"atomic overwrite refuses read-only target: {path}")


def _replace_existing_windows(target: Path, staging: Path, backup: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    replace_file.restype = ctypes.c_int
    ctypes.set_last_error(0)
    succeeded = bool(
        replace_file(
            str(target),
            str(staging),
            str(backup),
            0,
            None,
            None,
        )
    )
    if succeeded:
        return

    error_code = int(ctypes.get_last_error())
    if error_code == _ERROR_UNABLE_TO_MOVE_REPLACEMENT_2:
        raise StagedWriteCommitUncertainError(
            (
                "ReplaceFileW moved the replaced file to ZN's backup name but could not "
                f"move the staged replacement into place (WinError {error_code})"
            ),
            staging_path=staging,
            backup_path=backup,
            strategy="replace_file_with_backup",
            error_code=error_code,
        )
    raise OSError(
        error_code,
        f"ReplaceFileW failed without moving the replaced file (WinError {error_code})",
        str(target),
    )


def _move_new_windows(staging: Path, target: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file.restype = ctypes.c_int
    ctypes.set_last_error(0)
    if move_file(str(staging), str(target), _MOVEFILE_WRITE_THROUGH):
        return
    error_code = int(ctypes.get_last_error())
    raise OSError(
        error_code,
        f"MoveFileExW no-replace commit failed (WinError {error_code})",
        str(target),
    )


def write_text_staged_windows(
    target: Path,
    content: str,
    *,
    encoding: str,
    token: str,
    after_stage: Callable[[Path], None] | None = None,
    precommit_check: Callable[[], None] | None = None,
    before_commit: Callable[[str, Path, Path | None], None] | None = None,
) -> StagedTextWriteResult:
    """Write complete text beside the target, then commit it as one Windows rename.

    Existing regular files use ReplaceFileW with a deterministic backup so the
    original DACL, creation time and other ReplaceFile metadata are preserved and
    the only documented namespace-mutating failure retains the original under a
    ZN-owned backup name. Missing targets use MoveFileExW without
    MOVEFILE_REPLACE_EXISTING, so a target that appears during the race is never
    silently clobbered.

    ``after_stage`` runs after the full stage has been flushed and fsynced.
    ``before_commit`` runs after staging/precondition checks and immediately
    before the Windows namespace API. A resident can persist exact restart
    evidence in those callbacks; both callbacks must finish before this function
    invokes ReplaceFileW/MoveFileExW.
    """

    if os.name != "nt":
        raise RuntimeError("Windows staged text replacement requires os.name == 'nt'")

    target = Path(target)
    staging_path, backup_path = overwrite_artifact_paths(target, token)
    for artifact in (staging_path, backup_path):
        if os.path.lexists(str(artifact)):
            raise FileExistsError(
                f"ZN overwrite artifact already exists and will not be replaced: {artifact}"
            )

    stage_started = False
    try:
        stage_started = True
        written = _write_stage(staging_path, content, encoding)
        if after_stage is not None:
            after_stage(staging_path)
        if precommit_check is not None:
            precommit_check()

        try:
            target_info = target.lstat()
        except FileNotFoundError:
            target_info = None

        if target_info is None:
            if before_commit is not None:
                before_commit("move_new_no_replace", staging_path, None)
            _move_new_windows(staging_path, target)
            return StagedTextWriteResult(
                written_chars=written,
                strategy="move_new_no_replace",
                staging_path=str(staging_path),
                backup_path=None,
            )

        _validate_existing_windows_target(target)
        if before_commit is not None:
            before_commit("replace_file_with_backup", staging_path, backup_path)
        _replace_existing_windows(target, staging_path, backup_path)

        cleanup_pending: list[str] = []
        if os.path.lexists(str(backup_path)):
            try:
                backup_path.unlink()
            except OSError:
                cleanup_pending.append(str(backup_path))
        return StagedTextWriteResult(
            written_chars=written,
            strategy="replace_file_with_backup",
            staging_path=str(staging_path),
            backup_path=str(backup_path),
            cleanup_pending=tuple(cleanup_pending),
        )
    except StagedWriteCommitUncertainError:
        # Preserve both deterministic artifacts. Recovery can inspect current
        # reality and must not destroy the only retained pre-replacement file.
        raise
    except Exception:
        # Precommit/checkpoint failures occur before namespace mutation. Microsoft
        # documents every ReplaceFileW failure except 1177 as keeping the original
        # names when a backup is supplied. Remove only ZN's exact stage; never
        # erase an unexpected backup as part of generic exception cleanup.
        cleanup_overwrite_artifacts(
            target,
            token,
            include_staging=True,
            include_backup=False,
        )
        raise
    except BaseException:
        # A killed process may bypass Python cleanup entirely. Once stage creation
        # may have begun, preserve deterministic artifacts for restart evidence.
        if not stage_started:
            cleanup_overwrite_artifacts(
                target,
                token,
                include_staging=True,
                include_backup=False,
            )
        raise

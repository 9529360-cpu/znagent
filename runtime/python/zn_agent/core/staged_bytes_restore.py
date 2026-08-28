from __future__ import annotations

"""Crash-inspectable exact-byte restore into a currently missing Windows path.

This module owns only the bounded filesystem movement. Durable Work ownership,
user approval, retained-byte validation, recovery classification and final
verification remain resident concerns.
"""

import ctypes
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_MOVEFILE_WRITE_THROUGH = 0x00000008


@dataclass(frozen=True, slots=True)
class StagedBytesRestoreResult:
    written_bytes: int
    staging_path: str
    target_path: str


def restore_staging_path(target: Path, token: str) -> Path:
    target = Path(target)
    digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:24]
    return target.parent / f".zn-restore-{digest}.tmp"


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
        f"MoveFileExW no-replace restore failed (WinError {error_code})",
        str(target),
    )


def restore_bytes_to_missing_target_windows(
    target: Path,
    content: bytes,
    *,
    token: str,
    after_stage: Callable[[Path], None] | None = None,
    before_commit: Callable[[Path], None] | None = None,
) -> StagedBytesRestoreResult:
    """Stage exact bytes beside a missing target, then move without replacement.

    The target must remain absent through the final resident precommit callback.
    ``MoveFileExW`` is deliberately invoked without a replace flag, so a target
    that appears after preflight wins the race instead of being overwritten.
    The deterministic stage is preserved after an uncertain/failed commit so
    restart recovery can classify current reality without replaying blindly.
    """

    if os.name != "nt":
        raise RuntimeError("exact-byte Work restore currently requires Windows")

    target = Path(target)
    payload = bytes(content)
    staging = restore_staging_path(target, token)
    if os.path.lexists(str(target)):
        raise FileExistsError(f"restore target is no longer missing: {target}")
    if os.path.lexists(str(staging)):
        raise FileExistsError(
            f"ZN restore staging artifact already exists and requires recovery: {staging}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    stage_ready = False
    try:
        with staging.open("xb") as handle:
            written = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        stage_ready = True
        if written != len(payload):
            raise OSError(
                f"short exact-byte restore stage write: {written} of {len(payload)} bytes"
            )
        if after_stage is not None:
            after_stage(staging)
        if os.path.lexists(str(target)):
            raise FileExistsError(f"restore target appeared before commit: {target}")
        if before_commit is not None:
            before_commit(staging)
        if os.path.lexists(str(target)):
            raise FileExistsError(f"restore target appeared at commit boundary: {target}")
        _move_new_windows(staging, target)
        return StagedBytesRestoreResult(
            written_bytes=written,
            staging_path=str(staging),
            target_path=str(target),
        )
    except Exception:
        # Before a durable stage exists, cleanup is safe. Once staged bytes exist,
        # preserve the exact artifact so resident recovery can determine whether
        # the no-replace namespace move started or completed.
        if not stage_ready and os.path.lexists(str(staging)):
            try:
                staging.unlink()
            except OSError:
                pass
        raise

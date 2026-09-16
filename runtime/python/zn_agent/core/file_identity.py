from __future__ import annotations

"""Privacy-bounded current-file identity for resident mutation recovery."""

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from .models import utc_now
from .path_context import canonical_host_path

IDENTITY_VERSION = 1
DEFAULT_MAX_HASH_BYTES = 8 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


def _canonical_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(os.path.abspath(str(path)))
    return canonical_host_path(path)


def _stat_fields(info: os.stat_result) -> dict[str, int]:
    return {
        "size_bytes": int(info.st_size),
        "mtime_ns": int(getattr(info, "st_mtime_ns", round(info.st_mtime * 1_000_000_000))),
        "ctime_ns": int(getattr(info, "st_ctime_ns", round(info.st_ctime * 1_000_000_000))),
        "device": int(getattr(info, "st_dev", 0) or 0),
        "inode": int(getattr(info, "st_ino", 0) or 0),
    }


def observe_file_identity(
    value: str | Path,
    *,
    max_hash_bytes: int = DEFAULT_MAX_HASH_BYTES,
) -> dict[str, Any]:
    """Observe content-free identity evidence without returning file contents.

    Regular files at or below ``max_hash_bytes`` receive a complete SHA-256 plus
    before/after stat agreement. Larger files remain observable but deliberately
    do not get an exact content identity. Symlinks are reported but are not
    treated as exact overwrite baselines because the existing write primitive
    follows the link target.
    """

    path = _canonical_path(value)
    observed_at = utc_now()
    cap = max(0, int(max_hash_bytes))
    try:
        before_lstat = path.lstat()
    except FileNotFoundError:
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": True,
            "stable": True,
            "exists": False,
            "type": "missing",
            "digest_complete": True,
            "content_sha256": None,
        }
    except OSError as exc:
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": False,
            "stable": False,
            "exists": None,
            "type": "unknown",
            "digest_complete": False,
            "content_sha256": None,
            "error_class": type(exc).__name__,
        }

    mode = int(before_lstat.st_mode)
    if stat.S_ISLNK(mode):
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": True,
            "stable": True,
            "exists": True,
            "type": "symlink",
            "digest_complete": False,
            "content_sha256": None,
            **_stat_fields(before_lstat),
        }
    if not stat.S_ISREG(mode):
        kind = "directory" if stat.S_ISDIR(mode) else "other"
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": True,
            "stable": True,
            "exists": True,
            "type": kind,
            "digest_complete": False,
            "content_sha256": None,
            **_stat_fields(before_lstat),
        }

    before = _stat_fields(before_lstat)
    if before["size_bytes"] > cap:
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": True,
            "stable": True,
            "exists": True,
            "type": "file",
            "digest_complete": False,
            "content_sha256": None,
            "max_hash_bytes": cap,
            **before,
        }

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        after_lstat = path.lstat()
    except (FileNotFoundError, OSError) as exc:
        return {
            "version": IDENTITY_VERSION,
            "path": str(path),
            "observed_at": observed_at,
            "observable": False,
            "stable": False,
            "exists": None,
            "type": "unknown",
            "digest_complete": False,
            "content_sha256": None,
            "error_class": type(exc).__name__,
        }

    after = _stat_fields(after_lstat)
    stable = (
        stat.S_ISREG(int(after_lstat.st_mode))
        and all(before[key] == after[key] for key in before)
    )
    return {
        "version": IDENTITY_VERSION,
        "path": str(path),
        "observed_at": observed_at,
        "observable": True,
        "stable": bool(stable),
        "exists": True,
        "type": "file",
        "digest_complete": bool(stable),
        "content_sha256": digest.hexdigest() if stable else None,
        "max_hash_bytes": cap,
        **after,
    }


def compare_file_identities(
    expected: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare exact observable identity; never grant mutation authority itself."""

    if not isinstance(expected, dict) or not isinstance(current, dict):
        return {"comparable": False, "exact": False, "reason": "identity_missing"}
    if expected.get("version") != IDENTITY_VERSION or current.get("version") != IDENTITY_VERSION:
        return {"comparable": False, "exact": False, "reason": "identity_version"}
    if str(expected.get("path") or "") != str(current.get("path") or ""):
        return {"comparable": False, "exact": False, "reason": "path_changed"}
    if not expected.get("observable") or not current.get("observable"):
        return {"comparable": False, "exact": False, "reason": "identity_unobservable"}
    if not expected.get("stable") or not current.get("stable"):
        return {"comparable": False, "exact": False, "reason": "identity_unstable"}
    if expected.get("exists") != current.get("exists"):
        return {"comparable": True, "exact": False, "reason": "existence_changed"}
    if str(expected.get("type") or "") != str(current.get("type") or ""):
        return {"comparable": True, "exact": False, "reason": "type_changed"}

    kind = str(expected.get("type") or "")
    if kind == "missing":
        return {"comparable": True, "exact": True, "reason": "same_missing_target"}
    if kind != "file":
        return {"comparable": False, "exact": False, "reason": "unsupported_file_type"}
    if not expected.get("digest_complete") or not current.get("digest_complete"):
        return {"comparable": False, "exact": False, "reason": "digest_incomplete"}

    keys = (
        "size_bytes",
        "mtime_ns",
        "ctime_ns",
        "device",
        "inode",
        "content_sha256",
    )
    exact = all(expected.get(key) == current.get(key) for key in keys)
    return {
        "comparable": True,
        "exact": bool(exact),
        "reason": "same_exact_file_identity" if exact else "file_identity_changed",
    }


def read_text_for_exact_file_identity(
    value: str | Path,
    expected: dict[str, Any] | None,
    *,
    max_bytes: int = DEFAULT_MAX_HASH_BYTES,
    encoding: str = "utf-8",
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Read text only from the exact already-observed regular file.

    The path is opened once, then the opened handle is checked against the
    caller's exact identity *before* any bytes are read. The same handle is
    checked again after reading, the bytes must match the expected digest, and
    the pathname must still resolve to that exact file before content is
    released to the caller. This closes the path-swap window between a normal
    pre-read identity check and a later path-based read.
    """

    if not isinstance(expected, dict):
        return None, None, "exact file identity is required"
    path = _canonical_path(value)
    if str(expected.get("path") or "") != str(path):
        return None, None, "exact file identity path does not match the requested source"
    if not (
        expected.get("version") == IDENTITY_VERSION
        and expected.get("observable") is True
        and expected.get("stable") is True
        and expected.get("exists") is True
        and expected.get("type") == "file"
        and expected.get("digest_complete") is True
        and str(expected.get("content_sha256") or "")
    ):
        return None, None, "exact file identity is not a stable readable regular-file baseline"

    cap = max(0, int(max_bytes))
    try:
        expected_size = int(expected.get("size_bytes"))
    except (TypeError, ValueError):
        return None, None, "exact file identity has no valid size"
    if expected_size > cap:
        return None, None, "exact file exceeds the bounded read limit"

    # Path stat and opened-handle fstat do not expose identical ctime semantics
    # on Windows 3.12+. Bind the opened object with portable object fields; the
    # expected content digest below remains the authoritative byte identity.
    handle_identity_keys = ("size_bytes", "mtime_ns", "device", "inode")
    try:
        with path.open("rb") as handle:
            before = _stat_fields(os.fstat(handle.fileno()))
            if any(expected.get(key) != before.get(key) for key in handle_identity_keys):
                return None, None, "opened file identity no longer matches the expected source"
            raw = handle.read(cap + 1)
            after = _stat_fields(os.fstat(handle.fileno()))
    except (FileNotFoundError, OSError) as exc:
        return None, None, f"exact source open/read failed: {type(exc).__name__}"

    if any(before.get(key) != after.get(key) for key in handle_identity_keys):
        return None, None, "opened file changed while it was being read"
    if len(raw) > cap or len(raw) != after["size_bytes"]:
        return None, None, "opened file exceeded or changed across the bounded read"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != str(expected.get("content_sha256") or ""):
        return None, None, "opened file content no longer matches the expected source"

    current = observe_file_identity(path, max_hash_bytes=cap)
    if compare_file_identities(expected, current).get("exact") is not True:
        return None, current, "source path identity changed while the exact file was being read"
    try:
        text = raw.decode(str(encoding or "utf-8"), errors="replace")
    except LookupError as exc:
        return None, current, f"unknown text encoding: {exc}"
    return text.replace("\r\n", "\n").replace("\r", "\n"), current, None

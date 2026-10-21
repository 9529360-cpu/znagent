"""Blueprint §6.5 export/migrate: versioned takeout of the memory facts table (Q15).

The user can take their own memory with them: :func:`export_facts_to_file`
serializes every fact row (key / value / aliases / sensitivity / expires_at /
timestamps) into a versioned JSON document, and
:func:`import_facts_from_file` restores it into another (or the same) store.

Design notes (fail closed):

- Only the ``facts`` table is exported. The credential store is never
  touched by this module, so credential material cannot leak through an
  export by construction.
- Export is an explicit takeout: unlike the ``memory_list`` RPC inventory
  (which deliberately omits values), the export file contains full fact
  values. The file itself is the user's responsibility.
- Import validates the whole payload *before* writing anything (two-pass),
  so a malformed file never leaves a half-imported store.
- Import conflicts default to ``skip``; an existing key is only replaced
  when ``overwrite=True`` is explicitly passed.
- Import writes go through :meth:`KernelStore.put_fact`, so the M15
  credential-isolation gate and the Q11 sensitivity / Q7 expiry validators
  apply exactly as on the normal ``remember`` path. ``created_at`` /
  ``updated_at`` become import time -- they describe this store's copy, not
  the original.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import utc_now
from .store import normalize_expires_at, normalize_sensitivity

MEMORY_EXPORT_VERSION = 1

_FACT_FIELDS = (
    "key",
    "value",
    "aliases",
    "created_at",
    "updated_at",
    "expires_at",
    "sensitivity",
)


def _reject_traversal(raw: str) -> None:
    """Reject literal ``..`` segments: no escaping the caller's directory."""
    if ".." in Path(raw).parts:
        raise ValueError(f"refusing path with '..' traversal: {raw!r}")


def _resolve_export_target(raw: str) -> Path:
    path_str = str(raw or "").strip()
    if not path_str:
        raise ValueError("memory_export requires a destination path")
    _reject_traversal(path_str)
    target = Path(path_str)
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(
            f"memory_export destination directory does not exist: {parent}"
        )
    if target.exists() and target.is_dir():
        raise ValueError(f"memory_export destination is a directory: {target}")
    return target


def _resolve_import_source(raw: str) -> Path:
    path_str = str(raw or "").strip()
    if not path_str:
        raise ValueError("memory_import requires a source path")
    _reject_traversal(path_str)
    source = Path(path_str)
    if not source.exists():
        raise ValueError(f"memory_import source file does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"memory_import source is not a file: {source}")
    return source


def export_facts(store: Any) -> dict[str, Any]:
    """Build the versioned export payload from the facts table (no I/O)."""
    entries = []
    for fact in store.list_facts():
        entries.append(
            {
                "key": fact.get("key"),
                "value": fact.get("value"),
                "aliases": list(fact.get("aliases") or ()),
                "created_at": fact.get("created_at"),
                "updated_at": fact.get("updated_at"),
                "expires_at": fact.get("expires_at"),
                "sensitivity": fact.get("sensitivity") or "normal",
            }
        )
    return {
        "version": MEMORY_EXPORT_VERSION,
        "exported_at": utc_now(),
        "fact_count": len(entries),
        "facts": entries,
    }


def export_facts_to_file(store: Any, path: str) -> dict[str, Any]:
    """Write the versioned facts export to *path*.

    Returns ``{"exported": n, "file": str, "version": 1}``.
    """
    target = _resolve_export_target(path)
    payload = export_facts(store)
    try:
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise ValueError(f"memory_export cannot write {target}: {exc}") from None
    return {
        "exported": payload["fact_count"],
        "file": str(target),
        "version": MEMORY_EXPORT_VERSION,
    }


def _validate_entry(entry: Any, index: int) -> dict[str, Any]:
    where = f"entry #{index}"
    if not isinstance(entry, dict):
        raise ValueError(f"invalid memory export {where}: must be an object")
    key = entry.get("key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError(
            f"invalid memory export {where}: 'key' must be a non-empty string"
        )
    key = key.strip()
    value = entry.get("value")
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        raise ValueError(
            f"invalid memory export entry {key!r}: 'value' is not JSON-serializable"
        ) from None
    aliases = entry.get("aliases") or []
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) for alias in aliases
    ):
        raise ValueError(
            f"invalid memory export entry {key!r}: 'aliases' must be a list of strings"
        )
    try:
        expires_at = normalize_expires_at(entry.get("expires_at"))
    except ValueError as exc:
        raise ValueError(
            f"invalid memory export entry {key!r}: expires_at: {exc}"
        ) from None
    try:
        sensitivity = normalize_sensitivity(entry.get("sensitivity"))
    except ValueError as exc:
        raise ValueError(
            f"invalid memory export entry {key!r}: sensitivity: {exc}"
        ) from None
    return {
        "key": key,
        "value": value,
        "aliases": aliases,
        "expires_at": expires_at,
        "sensitivity": sensitivity,
    }


def import_facts(
    store: Any, payload: Any, *, overwrite: bool = False
) -> dict[str, int]:
    """Restore facts from an export *payload* (already parsed JSON).

    Two-pass: every entry is validated before any write, so a malformed
    payload leaves the store untouched. Existing keys are skipped unless
    ``overwrite`` is true, in which case they are replaced and counted
    separately.
    """
    if not isinstance(payload, dict):
        raise ValueError("memory export must be a JSON object")
    version = payload.get("version")
    if version != MEMORY_EXPORT_VERSION:
        raise ValueError(
            f"unsupported memory export version: {version!r} "
            f"(expected {MEMORY_EXPORT_VERSION})"
        )
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise ValueError("memory export 'facts' must be a list")
    entries = [_validate_entry(entry, index) for index, entry in enumerate(facts)]

    existing_keys = {str(fact.get("key")) for fact in store.list_facts()}
    imported = skipped = overwritten = 0
    for entry in entries:
        if entry["key"] in existing_keys:
            if not overwrite:
                skipped += 1
                continue
            overwritten += 1
        else:
            imported += 1
        # M15 credential-isolation gate, Q11 tier validation and Q7 expiry
        # normalization all run inside put_fact -- import is a write path and
        # gets the same treatment as remember. A credential-shaped value
        # fails the whole import explicitly (no silent drop).
        store.put_fact(
            entry["key"],
            entry["value"],
            aliases=tuple(entry["aliases"]),
            expires_at=entry["expires_at"],
            sensitivity=entry["sensitivity"],
        )
    return {
        "imported": imported,
        "skipped": skipped,
        "overwritten": overwritten,
        "version": MEMORY_EXPORT_VERSION,
    }


def import_facts_from_file(
    store: Any, path: str, *, overwrite: bool = False
) -> dict[str, int]:
    """Read *path* and restore its facts into *store*."""
    source = _resolve_import_source(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"memory export file {source} is not valid UTF-8: {exc}"
        ) from None
    except OSError as exc:
        raise ValueError(
            f"memory export file {source} cannot be read: {exc}"
        ) from None
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"memory export file {source} is not valid JSON: {exc}"
        ) from None
    return import_facts(store, payload, overwrite=overwrite)

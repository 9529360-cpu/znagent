from __future__ import annotations

"""ZN workspace file discipline: deliverables / drafts / internal ledger.

Mechanism adapted from the Muse workspace-file-discipline pattern (M12:
deliverables, drafts and internal bookkeeping live in three separate places;
deletion is recoverable). No Muse code is copied; the mechanism is
re-implemented for ZN's own workspace layout.

Layout (under one workspace root, by default ``<ZN home>/workspace/``)::

    workspace/
      your_files/    Deliverables: final products for the user. The only
                     place user-visible finished files come from.
      drafts/        Drafts: intermediate / in-progress files. Never
                     presented to the user as finished work.
      hidden_files/  Internal ledger: internal state, logs, watermarks,
                     seen-lists, snapshots. The user must not see these.
      .trash/        Trash: the recoverable waystation for deletions.
                     Not a fourth content class; only the trash API reads it.

Discipline, enforced by code (not just documentation):

* A deliverable is written in ``your_files/`` from the first write. It is
  never built elsewhere and copied/moved in afterwards: a copy leaves two
  versions that drift, a move breaks references. A draft that turns out to
  be final is promoted with :func:`promote_draft_to_deliverable`, which
  MOVES (never copies) so no duplicate remains.
* Internal bookkeeping never lands in ``your_files/``. The write helpers
  (:func:`check_write`, :func:`write_text`, :func:`write_bytes`) reject a
  kind/location mismatch at write time.
* Deletion is a move into trash, never a direct unlink: :func:`trash_path`
  records the original path plus deletion time, :func:`list_trash` lists
  what can be restored, :func:`restore_path` puts it back.
* High-risk / bulk / irreversible operations require explicit
  ``confirm=True``: trashing a directory, permanently purging one trash
  entry (:func:`purge_trashed`), and emptying the trash
  (:func:`empty_trash`). Restoring over an existing target refuses by
  default; ``overwrite=True`` first trashes the current occupant, so a
  restore never silently destroys anything.
* Symlinks are refused by trash/restore: following a link could move a
  file that lives outside the workspace.

Trash is a resident-level operation. It is deliberately NOT admitted for
WorkerRun authority: ``WorkerActionAuthorityEnforcer`` denies Body kinds
outside its admitted sets, and trash kinds are not in them, so a WorkerRun
calling a trash Body action is rejected fail-closed.
"""

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .home import get_zn_home

FileKind = Literal["deliverable", "draft", "internal"]

_DELIVERABLES_DIRNAME = "your_files"
_DRAFTS_DIRNAME = "drafts"
_INTERNAL_DIRNAME = "hidden_files"
_TRASH_DIRNAME = ".trash"
_KIND_DIRS: dict[FileKind, str] = {
    "deliverable": _DELIVERABLES_DIRNAME,
    "draft": _DRAFTS_DIRNAME,
    "internal": _INTERNAL_DIRNAME,
}
_LAYOUT_DIRNAMES = frozenset(
    (_DELIVERABLES_DIRNAME, _DRAFTS_DIRNAME, _INTERNAL_DIRNAME, _TRASH_DIRNAME)
)
_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_ENTRY_NAME_CHARS = 64


class WorkspaceFileDisciplineError(ValueError):
    """A workspace file operation violates the deliverable/draft/ledger split."""


@dataclass(frozen=True, slots=True)
class TrashEntry:
    """One recoverable deletion: where it came from and when it was trashed."""

    entry_id: str
    original_path: str
    deleted_at: str
    kind: str  # "file" | "directory"
    size_bytes: int
    trash_path: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _resolve_root(root: str | Path) -> Path:
    resolved = Path(root).expanduser()
    if not resolved.is_absolute():
        raise WorkspaceFileDisciplineError(
            f"workspace root must be absolute: {root!r}"
        )
    return resolved.resolve(strict=False)


def _resolve_inside(path: str | Path, root: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(os.path.abspath(str(candidate)))
    return candidate.resolve(strict=False)


def _relative_to_root(target: Path, root: Path) -> tuple[str, ...]:
    try:
        return target.relative_to(root).parts
    except ValueError as exc:
        raise WorkspaceFileDisciplineError(
            f"path is outside the workspace root {root}: {target}"
        ) from exc


def resolve_agent_workspace_path(root: str | Path, raw_path: str | Path) -> tuple[Path, FileKind]:
    """Resolve one agent-supplied workspace path to (absolute path, kind).

    This is the single containment gate for agent file actions: the path
    must be workspace-relative (absolute paths are rejected outright),
    must resolve inside the workspace root after following symlinks, and
    must land in a deliverable (``your_files/``) or draft (``drafts/``)
    directory. Internal ledger paths (``hidden_files/``), trash paths,
    unclassified paths directly under the root, and the workspace root
    itself are all refused. Body handlers, approval scope resolvers and
    verifiers all go through this one function, so no caller can smuggle
    a different target past the gate.
    """

    raw = str(raw_path or "").strip()
    if not raw:
        raise WorkspaceFileDisciplineError("workspace path must not be empty")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise WorkspaceFileDisciplineError(
            "workspace path must be relative, not absolute: "
            f"{raw!r}"
        )
    if ".." in candidate.parts:
        raise WorkspaceFileDisciplineError(
            f"workspace path must not contain '..': {raw!r}"
        )
    resolved_root = _resolve_root(root)
    target = (resolved_root / candidate).resolve(strict=False)
    _relative_to_root(target, resolved_root)
    kind = classify_path(target, root=resolved_root)
    if kind not in ("deliverable", "draft"):
        raise WorkspaceFileDisciplineError(
            "agent file actions only operate on deliverables "
            f"(your_files/) and drafts (drafts/): {raw!r}"
        )
    return target, kind


def default_workspace_root(home: str | Path | None = None) -> Path:
    """Return ZN's workspace root: ``<ZN home>/workspace/`` by default."""
    base = Path(home).expanduser() if home is not None else get_zn_home()
    return base / "workspace"


def classify_path(path: str | Path, *, root: str | Path) -> str | None:
    """Classify a path: ``deliverable`` | ``draft`` | ``internal`` | ``trash``.

    Returns ``None`` for the workspace root itself, for paths directly under
    it (unclassified), and for paths outside the workspace.
    """

    resolved_root = _resolve_root(root)
    target = _resolve_inside(path, resolved_root)
    try:
        rel = target.relative_to(resolved_root).parts
    except ValueError:
        return None
    if not rel:
        return None
    first = rel[0]
    if first == _TRASH_DIRNAME:
        return "trash"
    if first == _DELIVERABLES_DIRNAME:
        return "deliverable"
    if first == _DRAFTS_DIRNAME:
        return "draft"
    if first == _INTERNAL_DIRNAME:
        return "internal"
    return None


def check_write(path: str | Path, kind: FileKind, *, root: str | Path) -> Path:
    """Validate that ``path`` may hold a ``kind`` file; return resolved path.

    Raises :class:`WorkspaceFileDisciplineError` when the kind is unknown,
    the path is outside the workspace, the path is in trash, the path is
    unclassified (directly under the workspace root), or the path's actual
    directory disagrees with the declared kind. In particular, internal
    ledger content can never be written into the deliverables directory.
    """

    if kind not in _KIND_DIRS:
        raise WorkspaceFileDisciplineError(f"unknown workspace file kind: {kind!r}")
    resolved_root = _resolve_root(root)
    target = _resolve_inside(path, resolved_root)
    _relative_to_root(target, resolved_root)
    actual = classify_path(target, root=resolved_root)
    if actual == "trash":
        raise WorkspaceFileDisciplineError(
            f"refusing to write into the trash area: {target}"
        )
    if actual is None:
        raise WorkspaceFileDisciplineError(
            "refusing unclassified write directly under the workspace root; "
            f"put {kind} files under {_KIND_DIRS[kind]}/: {target}"
        )
    if actual != kind:
        raise WorkspaceFileDisciplineError(
            f"refusing to write a {kind} file into the {actual} directory: {target}"
        )
    return target


def resolve_write_path(
    root: str | Path, kind: FileKind, relative: str | Path
) -> Path:
    """Safely join a relative name into ``kind``'s directory and check it.

    Absolute names and ``..`` traversal are rejected before any write.
    """

    if kind not in _KIND_DIRS:
        raise WorkspaceFileDisciplineError(f"unknown workspace file kind: {kind!r}")
    raw = str(relative or "").strip()
    if not raw:
        raise WorkspaceFileDisciplineError("workspace write needs a non-empty relative name")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceFileDisciplineError(
            f"workspace write name must be relative without '..': {relative!r}"
        )
    resolved_root = _resolve_root(root)
    target = resolved_root / _KIND_DIRS[kind] / candidate
    return check_write(target, kind, root=resolved_root)


def write_text(
    root: str | Path,
    kind: FileKind,
    relative: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    overwrite: bool = False,
) -> Path:
    """Write text into ``kind``'s directory, enforcing the three-way split."""
    if _has_final_symlink(_resolve_root(root) / _KIND_DIRS[kind] / Path(relative)):
        raise WorkspaceFileDisciplineError(
            f"refusing to write through a symlink: {relative!r}"
        )
    target = resolve_write_path(root, kind, relative)
    _write_checked(target, overwrite=overwrite)
    # newline="": text-mode writes translate "\n" -> os.linesep on Windows
    # (\r\n), but callers (SHA verifier, CUR-4 undo snapshot) compare raw
    # bytes against the requested text, so writes must be byte-faithful.
    target.write_text(content, encoding=encoding, newline="")
    return target


def write_bytes(
    root: str | Path,
    kind: FileKind,
    relative: str | Path,
    content: bytes,
    *,
    overwrite: bool = False,
) -> Path:
    """Write bytes into ``kind``'s directory, enforcing the three-way split."""
    if _has_final_symlink(_resolve_root(root) / _KIND_DIRS[kind] / Path(relative)):
        raise WorkspaceFileDisciplineError(
            f"refusing to write through a symlink: {relative!r}"
        )
    target = resolve_write_path(root, kind, relative)
    _write_checked(target, overwrite=overwrite)
    target.write_bytes(bytes(content))
    return target


def _has_final_symlink(path: str | Path) -> bool:
    # Check BEFORE resolve(): resolve() follows links, so checking the
    # resolved path would never see the link. The final component is the
    # one that decides where a write/trash actually lands.
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = Path(os.path.abspath(str(raw)))
    return os.path.islink(str(raw))


def _write_checked(target: Path, *, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(str(target)):
        if not overwrite:
            raise FileExistsError(
                f"workspace file already exists (pass overwrite=True to replace): {target}"
            )
        if target.is_dir():
            raise IsADirectoryError(f"workspace write target is a directory: {target}")


def promote_draft_to_deliverable(
    root: str | Path,
    draft_path: str | Path,
    deliverable_name: str | Path,
) -> Path:
    """Promote a draft to a deliverable by MOVE, never by copy.

    The draft must live under ``drafts/``; the destination is a relative
    name under ``your_files/`` and must not already exist. After promotion
    the draft is gone, so no duplicate can drift from the deliverable.
    Internal ledger files can never be promoted.
    """

    resolved_root = _resolve_root(root)
    source = _resolve_inside(draft_path, resolved_root)
    _relative_to_root(source, resolved_root)
    if classify_path(source, root=resolved_root) != "draft":
        raise WorkspaceFileDisciplineError(
            f"only drafts can be promoted to deliverables: {source}"
        )
    if not os.path.lexists(str(source)):
        raise FileNotFoundError(f"draft to promote does not exist: {source}")
    if _has_final_symlink(draft_path):
        raise WorkspaceFileDisciplineError(f"refusing to promote a symlink: {source}")
    dest = resolve_write_path(resolved_root, "deliverable", deliverable_name)
    if os.path.lexists(str(dest)):
        raise FileExistsError(f"deliverable already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    if os.path.lexists(str(source)) or not os.path.lexists(str(dest)):
        raise RuntimeError(f"draft promotion left an inconsistent state: {source} -> {dest}")
    return dest


def _trash_dir(root: Path) -> Path:
    return root / _TRASH_DIRNAME


def _entry_dir(root: Path, entry_id: str) -> Path:
    return _trash_dir(root) / entry_id


def _sanitize_entry_name(name: str) -> str:
    cleaned = _NAME_SANITIZE_RE.sub("_", str(name or "unnamed")).strip("._")
    return (cleaned or "unnamed")[:_MAX_ENTRY_NAME_CHARS]


def _new_entry_id(root: Path, deleted_at: str, original_name: str) -> str:
    stamp = re.sub(r"\D", "", deleted_at)[:20]
    base = _sanitize_entry_name(original_name)
    candidate = f"{stamp}-{base}"
    suffix = 0
    while os.path.lexists(str(_entry_dir(root, candidate))):
        suffix += 1
        candidate = f"{stamp}-{base}-{suffix}"
    return candidate


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            try:
                total += int(os.path.getsize(os.path.join(dirpath, filename)))
            except OSError:
                continue
    return total


def _refuse_symlinks_below(path: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        for name in (*dirnames, *filenames):
            if Path(dirpath, name).is_symlink():
                raise WorkspaceFileDisciplineError(
                    f"refusing to trash a tree containing a symlink: {Path(dirpath, name)}"
                )


def trash_path(path: str | Path, root: str | Path, *, confirm: bool = False) -> TrashEntry:
    """Delete by moving into trash. Returns the entry that can restore it.

    Single files need no confirmation (the deletion is recoverable).
    Directories are bulk deletions and require ``confirm=True``.
    """

    resolved_root = _resolve_root(root)
    target = _resolve_inside(path, resolved_root)
    rel = _relative_to_root(target, resolved_root)
    if not rel:
        raise WorkspaceFileDisciplineError("refusing to trash the workspace root itself")
    if len(rel) == 1 and rel[0] in _LAYOUT_DIRNAMES:
        raise WorkspaceFileDisciplineError(
            f"refusing to trash a workspace layout directory: {target}"
        )
    if rel[0] == _TRASH_DIRNAME:
        raise WorkspaceFileDisciplineError(f"path is already in trash: {target}")
    if not os.path.lexists(str(target)):
        raise FileNotFoundError(f"nothing to trash: {target}")
    if _has_final_symlink(path):
        raise WorkspaceFileDisciplineError(f"refusing to trash a symlink: {target}")
    is_dir = target.is_dir()
    if is_dir:
        if not confirm:
            raise WorkspaceFileDisciplineError(
                "trashing a directory is a bulk deletion and requires confirm=True: "
                f"{target}"
            )
        _refuse_symlinks_below(target)
    elif not target.is_file():
        raise WorkspaceFileDisciplineError(
            f"trash only accepts regular files and directories: {target}"
        )
    info = target.lstat()
    size = _dir_size_bytes(target) if is_dir else int(info.st_size)
    deleted_at = _utc_now_iso()
    trash = _trash_dir(resolved_root)
    trash.mkdir(parents=True, exist_ok=True)
    entry_id = _new_entry_id(resolved_root, deleted_at, target.name)
    entry_dir = _entry_dir(resolved_root, entry_id)
    entry_dir.mkdir(parents=True, exist_ok=False)
    meta = {
        "entry_id": entry_id,
        "original_path": str(target),
        "deleted_at": deleted_at,
        "kind": "directory" if is_dir else "file",
        "size_bytes": int(size),
    }
    try:
        (entry_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        shutil.move(str(target), str(entry_dir / "payload"))
    except Exception:
        shutil.rmtree(entry_dir, ignore_errors=True)
        raise
    return TrashEntry(
        entry_id=entry_id,
        original_path=str(target),
        deleted_at=deleted_at,
        kind=meta["kind"],
        size_bytes=int(size),
        trash_path=str(entry_dir / "payload"),
    )


def list_trash(root: str | Path) -> list[TrashEntry]:
    """List trashed entries oldest first. Malformed entries are skipped."""
    resolved_root = _resolve_root(root)
    trash = _trash_dir(resolved_root)
    if not trash.is_dir():
        return []
    entries: list[TrashEntry] = []
    for entry_dir in sorted(trash.iterdir(), key=lambda item: item.name):
        if not entry_dir.is_dir():
            continue
        meta_path = entry_dir / "meta.json"
        payload = entry_dir / "payload"
        if not meta_path.is_file() or not os.path.lexists(str(payload)):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            entry = TrashEntry(
                entry_id=str(meta["entry_id"]),
                original_path=str(meta["original_path"]),
                deleted_at=str(meta["deleted_at"]),
                kind=str(meta["kind"]),
                size_bytes=int(meta["size_bytes"]),
                trash_path=str(payload),
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if entry.entry_id != entry_dir.name:
            continue
        entries.append(entry)
    entries.sort(key=lambda item: (item.deleted_at, item.entry_id))
    return entries


def _load_entry(root: Path, entry_id: str) -> tuple[TrashEntry, Path, Path]:
    raw = str(entry_id or "").strip()
    if not raw or not _ENTRY_ID_RE.fullmatch(raw) or raw in {".", ".."}:
        raise WorkspaceFileDisciplineError(f"invalid trash entry id: {entry_id!r}")
    entry_dir = _entry_dir(root, raw)
    meta_path = entry_dir / "meta.json"
    payload = entry_dir / "payload"
    if not entry_dir.is_dir() or not meta_path.is_file():
        raise FileNotFoundError(f"trash entry does not exist: {raw}")
    if not os.path.lexists(str(payload)):
        raise FileNotFoundError(f"trash entry payload is missing: {raw}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        entry = TrashEntry(
            entry_id=str(meta["entry_id"]),
            original_path=str(meta["original_path"]),
            deleted_at=str(meta["deleted_at"]),
            kind=str(meta["kind"]),
            size_bytes=int(meta["size_bytes"]),
            trash_path=str(payload),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkspaceFileDisciplineError(f"trash entry metadata is unreadable: {raw}") from exc
    if entry.entry_id != raw:
        raise WorkspaceFileDisciplineError(f"trash entry id mismatch: {raw}")
    return entry, entry_dir, payload


def restore_path(
    entry_id: str, root: str | Path, *, overwrite: bool = False
) -> Path:
    """Restore one trash entry to its original path. Returns the restored path.

    The original parent directories are recreated when missing. When the
    original path is occupied and ``overwrite`` is False (default), the
    restore refuses. With ``overwrite=True`` the current occupant is
    itself trashed first, so nothing is ever silently destroyed.
    """

    resolved_root = _resolve_root(root)
    entry, entry_dir, payload = _load_entry(resolved_root, entry_id)
    target = _resolve_inside(entry.original_path, resolved_root)
    rel = _relative_to_root(target, resolved_root)
    if not rel:
        raise WorkspaceFileDisciplineError("refusing to restore onto the workspace root")
    if len(rel) == 1 and rel[0] in _LAYOUT_DIRNAMES:
        raise WorkspaceFileDisciplineError(
            f"refusing to restore onto a workspace layout directory: {target}"
        )
    if rel[0] == _TRASH_DIRNAME:
        raise WorkspaceFileDisciplineError(
            f"refusing to restore into the trash area: {target}"
        )
    if os.path.lexists(str(target)):
        if not overwrite:
            raise FileExistsError(
                "restore target already exists (pass overwrite=True to trash "
                f"the occupant and restore): {target}"
            )
        trash_path(target, resolved_root, confirm=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(payload), str(target))
    if not os.path.lexists(str(target)):
        raise RuntimeError(f"trash restore left an inconsistent state: {entry_id}")
    shutil.rmtree(entry_dir, ignore_errors=True)
    return target


def purge_trashed(entry_id: str, root: str | Path, *, confirm: bool = False) -> str:
    """Permanently delete one trash entry. Requires ``confirm=True``.

    This is the only permanent-delete path in the module: everything else
    is recoverable by design.
    """

    if not confirm:
        raise WorkspaceFileDisciplineError(
            "permanently purging a trash entry is irreversible and requires "
            f"confirm=True: {entry_id!r}"
        )
    resolved_root = _resolve_root(root)
    entry, entry_dir, payload = _load_entry(resolved_root, entry_id)
    if payload.is_symlink() or payload.is_file():
        payload.unlink()
    elif payload.is_dir():
        shutil.rmtree(payload)
    else:
        raise WorkspaceFileDisciplineError(
            f"refusing to purge a non-file non-directory payload: {entry_id!r}"
        )
    shutil.rmtree(entry_dir, ignore_errors=True)
    return entry.entry_id


def empty_trash(root: str | Path, *, confirm: bool = False) -> list[str]:
    """Permanently purge every trash entry. Requires ``confirm=True``."""
    if not confirm:
        raise WorkspaceFileDisciplineError(
            "emptying the trash is irreversible and requires confirm=True"
        )
    purged: list[str] = []
    for entry in list_trash(root):
        purged.append(purge_trashed(entry.entry_id, root, confirm=True))
    return purged


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """A workspace root bound to its three content dirs plus trash."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _resolve_root(self.root))

    @classmethod
    def default(cls, home: str | Path | None = None) -> "WorkspaceLayout":
        return cls(default_workspace_root(home))

    @property
    def deliverables_dir(self) -> Path:
        return self.root / _DELIVERABLES_DIRNAME

    @property
    def drafts_dir(self) -> Path:
        return self.root / _DRAFTS_DIRNAME

    @property
    def internal_dir(self) -> Path:
        return self.root / _INTERNAL_DIRNAME

    @property
    def trash_dir(self) -> Path:
        return self.root / _TRASH_DIRNAME

    def ensure(self) -> "WorkspaceLayout":
        for directory in (
            self.deliverables_dir,
            self.drafts_dir,
            self.internal_dir,
            self.trash_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def classify(self, path: str | Path) -> str | None:
        return classify_path(path, root=self.root)

    def check_write(self, path: str | Path, kind: FileKind) -> Path:
        return check_write(path, kind, root=self.root)

    def resolve_write_path(self, kind: FileKind, relative: str | Path) -> Path:
        return resolve_write_path(self.root, kind, relative)

    def write_text(
        self,
        kind: FileKind,
        relative: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = False,
    ) -> Path:
        return write_text(
            self.root, kind, relative, content, encoding=encoding, overwrite=overwrite
        )

    def write_bytes(
        self,
        kind: FileKind,
        relative: str | Path,
        content: bytes,
        *,
        overwrite: bool = False,
    ) -> Path:
        return write_bytes(self.root, kind, relative, content, overwrite=overwrite)

    def promote_draft(self, draft_path: str | Path, deliverable_name: str | Path) -> Path:
        return promote_draft_to_deliverable(self.root, draft_path, deliverable_name)

    def trash(self, path: str | Path, *, confirm: bool = False) -> TrashEntry:
        return trash_path(path, self.root, confirm=confirm)

    def list_trash(self) -> list[TrashEntry]:
        return list_trash(self.root)

    def restore(self, entry_id: str, *, overwrite: bool = False) -> Path:
        return restore_path(entry_id, self.root, overwrite=overwrite)

    def purge(self, entry_id: str, *, confirm: bool = False) -> str:
        return purge_trashed(entry_id, self.root, confirm=confirm)

    def empty_trash(self, *, confirm: bool = False) -> list[str]:
        return empty_trash(self.root, confirm=confirm)

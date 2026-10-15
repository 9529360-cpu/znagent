from __future__ import annotations

"""Diff-first review and one-click undo for approval cards (CUR-4).

Presentation layer + undo path only. This module never decides whether an
action may run: the gate in :mod:`approval_cards` keeps owning every
decision (deny sticky, allow_once, always_allow, post-approval
revalidation). What this module adds:

1. ``build_unified_diff`` -- a capped unified diff of one pending file
   change, shown on the approval card before anything lands.
2. ``capture_file_review`` -- at request time, read the file as it is now
   and produce the review payload the card stores: the diff plus a
   faithful snapshot of the previous content (the undo record). The
   snapshot is only captured when it round-trips exactly: strict UTF-8
   and within the cap. A binary file, an oversized file, or a missing
   file yields ``previous_captured=False`` plus a ``review_note`` that
   says why -- undo is then refused instead of restoring a corrupt or
   truncated snapshot.
3. ``undo_approved_change`` -- one-click undo for a consumed (allow_once,
   spent) approval: restore the captured snapshot. The current occupant,
   if any, is trashed first (recoverable), so undo itself never silently
   destroys anything. Undo runs at most once per request.

Undo honesty: undo restores *file state*. It cannot recall copies that
already left the file -- a file that was sent, published, or synced
elsewhere keeps its external copies. The workbench says so next to the
undo button.
"""

import difflib
from pathlib import Path
from typing import Any

from .approval_cards import (
    REVIEW_DIFF_MAX_CHARS,
    REVIEW_PREVIOUS_CONTENT_MAX_CHARS,
)
from .workspace_file_discipline import (
    WorkspaceFileDisciplineError,
    resolve_agent_workspace_path,
    trash_path,
    write_text as discipline_write_text,
)

# Label used in diffs for a file that did not exist before the change.
_MISSING_LABEL = "(file did not exist)"
_DELETED_LABEL = "(deleted)"

_WORKSPACE_SCOPE_PREFIX = "workspace:"


def build_unified_diff(
    old_text: str | None,
    new_text: str | None,
    *,
    path_label: str,
    max_chars: int = REVIEW_DIFF_MAX_CHARS,
) -> tuple[str, bool]:
    """Return (unified diff, truncated) for one file change.

    ``old_text=None`` means the file did not exist; ``new_text=None``
    means the change deletes the file. The diff is computed on text
    truncated to ``max_chars`` so a huge file cannot blow up the card;
    ``truncated`` reports that the diff was cut short.
    """
    old = "" if old_text is None else str(old_text)
    new = "" if new_text is None else str(new_text)
    truncated = len(old) > max_chars or len(new) > max_chars
    old_shown = old[:max_chars]
    new_shown = new[:max_chars]
    from_label = path_label if old_text is not None else _MISSING_LABEL
    to_label = path_label if new_text is not None else _DELETED_LABEL
    lines = list(
        difflib.unified_diff(
            old_shown.splitlines(keepends=True),
            new_shown.splitlines(keepends=True),
            fromfile=f"a/{from_label}",
            tofile=f"b/{to_label}",
        )
    )
    diff = "".join(lines)
    if not diff:
        diff = "(no changes: old and new content are identical)\n"
    if truncated:
        diff += "\n... (diff truncated: file is larger than the review cap)\n"
    return diff, truncated


def _decode_strict(raw: bytes) -> str | None:
    """Strict UTF-8 decode; None when the bytes are not valid UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def capture_file_review(
    *,
    old_bytes: bytes | None,
    new_text: str | None,
    path_label: str,
) -> dict[str, Any]:
    """Build the review payload for one pending file change.

    ``old_bytes`` is the file content as it is now (None when the file
    does not exist); ``new_text`` is the proposed content (None when the
    change deletes the file). Never raises for missing/binary/oversized
    input: those degrade to ``previous_captured=False`` with a note.
    """
    review_note = ""
    if old_bytes is None:
        old_text: str | None = None
        previous_content = ""
        previous_captured = False
        diff_text, truncated = build_unified_diff(
            None, new_text, path_label=path_label
        )
        return {
            "diff_text": diff_text,
            "previous_content": "",
            "previous_captured": False,
            "review_note": review_note,
        }
    if len(old_bytes) > REVIEW_PREVIOUS_CONTENT_MAX_CHARS:
        # Oversized: no faithful snapshot, but the card still shows a
        # truncated diff of the file's prefix (display only, never used
        # for undo).
        prefix = old_bytes[:REVIEW_DIFF_MAX_CHARS].decode("utf-8", errors="replace")
        diff_text, _truncated = build_unified_diff(
            prefix, new_text, path_label=path_label
        )
        # build_unified_diff cannot know the prefix was cut from a much
        # larger file, so the truncation note is added here.
        diff_text += "\n... (diff truncated: file is larger than the review cap)\n"
        return {
            "diff_text": diff_text,
            "previous_content": "",
            "previous_captured": False,
            "review_note": (
                "file is larger than the undo cap; no undo snapshot was "
                "saved; diff truncated"
            ),
        }
    old_text = _decode_strict(old_bytes)
    if old_text is None:
        return {
            "diff_text": "(binary file: content diff not shown)\n",
            "previous_content": "",
            "previous_captured": False,
            "review_note": "binary file: diff not shown, no undo snapshot was saved",
        }
    diff_text, truncated = build_unified_diff(old_text, new_text, path_label=path_label)
    if truncated:
        review_note = "diff truncated: file is larger than the review cap"
    return {
        "diff_text": diff_text,
        "previous_content": old_text,
        "previous_captured": True,
        "review_note": review_note,
    }


def undo_approved_change(
    store: Any,
    request_id: str,
    *,
    workspace_root: str | Path,
) -> dict[str, Any]:
    """Undo one consumed approval: restore the file to its pre-change state.

    Returns ``{"request_id", "path", "restored", "note"}``. Raises
    ``ValueError`` with a user-readable reason when undo is not possible
    (not consumed, already undone, no snapshot, non-workspace scope, or
    the target escapes the workspace). The current occupant, if any, is
    moved to trash before the snapshot is written back, so a failed undo
    still leaves the occupant recoverable in trash.
    """
    normalized_id = str(request_id or "").strip()
    if not normalized_id:
        raise ValueError("undo requires an approval request id")
    request = store.get_request(normalized_id)
    if request is None:
        raise ValueError(f"unknown approval request: {normalized_id}")
    if request.status != "consumed":
        raise ValueError(
            "only an applied (consumed) approval can be undone; "
            f"request {normalized_id} is {request.status}"
        )
    if request.undone:
        raise ValueError("this approved change was already undone")
    if not request.previous_captured:
        reason = (request.review_note or "").strip()
        raise ValueError(
            "this approved change has no undo snapshot"
            + (f": {reason}" if reason else "")
        )
    scope = str(request.scope or "")
    if not scope.startswith(_WORKSPACE_SCOPE_PREFIX):
        raise ValueError("only workspace file changes can be undone")
    rel = scope[len(_WORKSPACE_SCOPE_PREFIX):].strip()
    if not rel:
        raise ValueError("approval scope has no workspace file to undo")
    root = Path(workspace_root).expanduser()
    try:
        target, kind = resolve_agent_workspace_path(root, rel)
    except WorkspaceFileDisciplineError as exc:
        raise ValueError(f"undo target escapes the workspace: {exc}") from exc
    previous = str(request.previous_content or "")
    current: str | None = None
    if target.is_file():
        raw = target.read_bytes()
        decoded = _decode_strict(raw)
        if decoded is not None:
            current = decoded
    if current is not None and current == previous:
        store.mark_undone(normalized_id, note="already at the pre-change state")
        return {
            "request_id": normalized_id,
            "path": str(target),
            "restored": False,
            "note": "file was already at its pre-change state; nothing rewritten",
        }
    if target.exists() or target.is_symlink():
        # Recoverable first: the occupant goes to trash, never unlink.
        try:
            trash_path(target, root, confirm=True)
        except WorkspaceFileDisciplineError as exc:
            raise ValueError(f"undo refused: current file cannot be trashed: {exc}") from exc
    relative = Path(*target.relative_to(root.resolve(strict=False)).parts[1:])
    try:
        discipline_write_text(
            root, kind, relative, previous, encoding="utf-8", overwrite=True
        )
    except Exception as exc:
        raise ValueError(
            "undo failed after the current file was moved to trash; "
            f"recover it from trash: {exc}"
        ) from exc
    store.mark_undone(normalized_id)
    return {
        "request_id": normalized_id,
        "path": str(target),
        "restored": True,
        "note": "file restored to its pre-change state; the replaced version is in trash",
    }

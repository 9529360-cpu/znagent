from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .file_identity import compare_file_identities, observe_file_identity
from .path_context import canonical_host_path, resolved_within

if TYPE_CHECKING:
    from .models import AgentEvent

_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?\s*\.?\s*txt(?=[，,。；;\s]|$)", re.I
)
_REPLACE = re.compile(
    r"把\s*[\"“'‘]?(?P<old>[^\"”'’‘，,。；;\r\n]{1,128}?)[\"”'’]?\s*"
    r"改成\s*[\"“'‘]?(?P<new>[^\"”'’‘，,。；;\r\n]{1,128}?)[\"”'’]?"
    r"(?=\s*(?:，|,|。|；|;|保存|然后|再|并|$))"
)
MAX_ENTRIES = 64
MAX_CANDIDATES = 8
MAX_CHARS = 16_384
MAX_BYTES = 64 * 1024


def natural_workspace_text_edit_request(event: "AgentEvent") -> dict[str, str] | None:
    payload = event.payload or {}
    task = str(event.task or "").strip()
    if (
        str(event.kind or "").lower() != "desktop_user_event"
        or not str(payload.get("workspace_path") or "").strip()
        or payload.get("body_action")
        or payload.get("native_action")
        or "昨天" not in task
        or "保存" not in task
        or not any(x in task for x in ("读回来", "读回确认", "重新读", "确认"))
    ):
        return None
    hint, replacement = _HINT.search(task), _REPLACE.search(task)
    if hint is None or replacement is None:
        return None
    old, new = replacement.group("old").strip(), replacement.group("new").strip()
    name_hint = hint.group("v").strip()
    if not name_hint or not old or not new or old == new:
        return None
    return {
        "workspace_path": str(payload["workspace_path"]),
        "name_hint": name_hint,
        "old_text": old,
        "new_text": new,
    }


def observe_candidates(event: "AgentEvent", body: Any) -> tuple[dict[str, Any], list[str]]:
    req = natural_workspace_text_edit_request(event)
    if req is None:
        return _fail("not a bounded natural workspace edit")
    try:
        workspace = canonical_host_path(req["workspace_path"]).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        return _fail("the authorized workspace is unavailable")
    listing = body.act("list_directory", event_id=event.event_id, path=str(workspace), limit=MAX_ENTRIES + 1)
    if not listing.success:
        return _fail(f"bounded workspace enumeration failed: {listing.error or 'unknown error'}")
    entries = [dict(x) for x in (listing.data.get("entries") or ()) if isinstance(x, Mapping)]
    if len(entries) > MAX_ENTRIES:
        return _fail(
            "bounded workspace enumeration reached its top-level entry limit; ZN will not widen the search",
            listing_overflow=True,
        )
    matched = []
    hint = req["name_hint"].casefold()
    for item in entries:
        name, raw = str(item.get("name") or ""), str(item.get("path") or "")
        path = canonical_host_path(raw) if raw else None
        if (
            str(item.get("type") or "").lower() == "file"
            and path is not None
            and Path(name).suffix.casefold() == ".txt"
            and hint in Path(name).stem.casefold()
            and _direct_child(path, workspace)
        ):
            matched.append((name, str(path)))
    if len(matched) > MAX_CANDIDATES:
        return _fail("too many top-level filename candidates for bounded comparison")

    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    rows, unknown = [], False
    for name, path in matched:
        inspected = body.act("inspect_path", event_id=event.event_id, path=path)
        identity = observe_file_identity(path)
        day = _day(identity)
        unknown = unknown or day is None
        rows.append({
            "name": name,
            "path": path,
            "matches_yesterday": day == yesterday if day else None,
            "safe": bool(
                inspected.success
                and inspected.data.get("exists") is True
                and str(inspected.data.get("type") or "").lower() == "file"
                and _exact_file(identity, path)
                and int(identity.get("size_bytes") or 0) <= MAX_BYTES
            ),
            "identity": identity,
        })
    plausible = [x for x in rows if x["matches_yesterday"] is True]
    reason = None
    if unknown:
        reason = "a filename candidate could not be freshly dated, so it cannot be safely excluded"
    elif not matched:
        reason = "no top-level txt filename matches the requested name hint"
    elif not plausible:
        reason = "no filename candidate was freshly observed as modified yesterday"
    result = {
        "workspace_path": str(workspace),
        "expected_local_date": yesterday.isoformat(),
        "matching_name_count": len(matched),
        "yesterday_candidate_count": len(plausible),
        "complete": not unknown,
        "ready": bool(not unknown and plausible),
        "candidates": rows,
        "failure_reason": reason,
    }
    return result, [
        f"bounded top-level enumeration: entries={len(entries)} name_matches={len(matched)} yesterday_matches={len(plausible)}",
        *([reason] if reason else []),
    ]


def compare_candidates(event: "AgentEvent", body: Any, discovery: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    req = natural_workspace_text_edit_request(event)
    if req is None or discovery.get("ready") is not True:
        return _compare_fail(str(discovery.get("failure_reason") or "candidate set is not ready"))
    rows = []
    for item in discovery.get("candidates") or ():
        if not isinstance(item, Mapping) or item.get("matches_yesterday") is not True:
            continue
        path, initial = str(item.get("path") or ""), item.get("identity")
        pre = observe_file_identity(path)
        safe = bool(
            item.get("safe") is True
            and compare_file_identities(initial if isinstance(initial, dict) else None, pre).get("exact") is True
            and _exact_file(pre, path)
            and _direct_child(path, discovery["workspace_path"])
        )
        observed = body.act("read_text", event_id=event.event_id, path=path, max_chars=MAX_CHARS + 1) if safe else None
        post = observe_file_identity(path) if observed is not None else None
        text = str(observed.output) if observed is not None and observed.success else ""
        readable = bool(
            observed is not None and observed.success
            and not bool(observed.data.get("truncated"))
            and int(observed.data.get("chars") or len(text)) <= MAX_CHARS
            and compare_file_identities(pre, post).get("exact") is True
            and "\ufffd" not in text and "\x00" not in text
        )
        rows.append({
            "name": str(item.get("name") or ""),
            "path": path,
            "read_success": readable,
            "source_count": text.count(req["old_text"]) if readable else None,
            "identity": dict(post) if isinstance(post, Mapping) else None,
        })
    singles = [x for x in rows if x.get("source_count") == 1]
    repeated = [x for x in rows if isinstance(x.get("source_count"), int) and x["source_count"] > 1]
    if not rows or not all(x["read_success"] for x in rows):
        reason = "a plausible candidate could not be safely and fully read, so comparison is incomplete"
    elif repeated:
        reason = "a candidate contains the requested source text more than once, so the replacement position is ambiguous"
    elif len(singles) > 1:
        reason = "more than one yesterday-modified candidate still contains the requested source text after fresh comparison"
    elif not singles:
        reason = "none of the yesterday-modified filename candidates contains the requested source text"
    else:
        reason = None
    selected = None if reason else {
        "name": singles[0]["name"], "path": singles[0]["path"], "identity": singles[0]["identity"]
    }
    return {
        "complete": bool(rows) and all(x["read_success"] for x in rows),
        "candidates": rows,
        "selected": selected,
        "failure_reason": reason,
    }, [
        f"fresh candidate content comparison: candidates={len(rows)} exact_source_matches={len(singles)}",
        *([reason] if reason else []),
    ]


def read_target(event: "AgentEvent", body: Any, comparison: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
    req = natural_workspace_text_edit_request(event)
    selected = comparison.get("selected") if isinstance(comparison, Mapping) else None
    if req is None or not isinstance(selected, Mapping):
        reason = str(comparison.get("failure_reason") or "no exact target was bound")
        return {"complete": False, "failure_reason": reason}, None, [reason]
    path, baseline = str(selected.get("path") or ""), selected.get("identity")
    pre = observe_file_identity(path)
    if not (
        compare_file_identities(baseline if isinstance(baseline, dict) else None, pre).get("exact") is True
        and _exact_file(pre, path) and _direct_child(path, req["workspace_path"])
    ):
        reason = "the exact target changed after comparison, so stale evidence was rejected"
        return {"complete": False, "failure_reason": reason}, None, [reason]
    observed = body.act("read_text", event_id=event.event_id, path=path, max_chars=MAX_CHARS + 1)
    post = observe_file_identity(path)
    text = str(observed.output) if observed.success else ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if observed.success else None
    count = text.count(req["old_text"]) if observed.success else 0
    if not observed.success:
        reason = str(observed.error or "target read failed")
    elif bool(observed.data.get("truncated")) or int(observed.data.get("chars") or len(text)) > MAX_CHARS:
        reason = "the exact target exceeds the bounded complete-text observation limit"
    elif compare_file_identities(pre, post).get("exact") is not True or digest != post.get("content_sha256"):
        reason = "the exact target changed while it was being read"
    elif count != 1:
        reason = "the exact target no longer has one unambiguous replacement position"
    else:
        reason = None
    complete = reason is None
    result = {"complete": complete, "path": path, "identity": dict(post), "failure_reason": reason}
    preview = {"path": path, "preview": text, "chars": len(text), "truncated": False} if complete else None
    return result, preview, [f"fresh exact target read: complete={complete}", *([reason] if reason else [])]


def edit_intent(event: "AgentEvent", facts: Mapping[str, Any]):
    req = natural_workspace_text_edit_request(event)
    discovery, comparison, target = (
        facts.get("natural_file_candidates"), facts.get("natural_file_candidate_comparison"), facts.get("natural_file_target_read")
    )
    selected = comparison.get("selected") if isinstance(comparison, Mapping) else None
    if not (
        req and isinstance(discovery, Mapping) and discovery.get("complete") is True
        and isinstance(comparison, Mapping) and comparison.get("complete") is True
        and isinstance(selected, Mapping) and isinstance(target, Mapping) and target.get("complete") is True
    ):
        return None
    path, identity = str(selected.get("path") or ""), target.get("identity")
    previews = facts.get("file_previews") if isinstance(facts.get("file_previews"), list) else []
    preview = next((x for x in previews if isinstance(x, Mapping) and _same(x.get("path"), path)), None)
    if not (
        isinstance(identity, Mapping) and _exact_file(identity, path)
        and _day(identity) is not None and _day(identity).isoformat() == discovery.get("expected_local_date")
        and isinstance(preview, Mapping) and not preview.get("truncated")
    ):
        return None
    current = str(preview.get("preview") or "")
    if current.count(req["old_text"]) != 1 or hashlib.sha256(current.encode("utf-8")).hexdigest() != identity.get("content_sha256"):
        return None
    expected = current.replace(req["old_text"], req["new_text"], 1)
    from .action import NativeActionIntent
    return NativeActionIntent(
        intent_id=f"act-{uuid.uuid4().hex[:12]}", event_id=event.event_id, kind="write_text",
        args={"path": path, "content": expected, "append": False, "create_parents": False},
        expected_outcome={"kind": "text_equals", "path": path, "expected_text": expected, "precondition_file_identity": dict(identity)},
        reason="fresh bounded file evidence bound one exact target and one exact replacement", source="resident_choice",
    )


def failure_reason(event: "AgentEvent", facts: Mapping[str, Any]) -> str | None:
    if natural_workspace_text_edit_request(event) is None or edit_intent(event, facts) is not None:
        return None
    for key in ("natural_file_target_read", "natural_file_candidate_comparison", "natural_file_candidates"):
        value = facts.get(key)
        if isinstance(value, Mapping) and str(value.get("failure_reason") or "").strip():
            return str(value["failure_reason"])
    return "bounded workspace evidence could not establish one exact safe target; ZN stopped instead of guessing"


def _fail(reason: str, **extra: Any):
    return {**extra, "complete": False, "ready": False, "failure_reason": reason}, [reason]


def _compare_fail(reason: str):
    return {"complete": False, "selected": None, "failure_reason": reason}, [reason]


def _day(identity: Mapping[str, Any]):
    try:
        return datetime.fromtimestamp(int(identity["mtime_ns"]) / 1_000_000_000).astimezone().date()
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return None


def _exact_file(identity: Mapping[str, Any], path: Any) -> bool:
    return bool(identity.get("observable") is True and identity.get("stable") is True and identity.get("exists") is True and identity.get("type") == "file" and identity.get("digest_complete") is True and _same(identity.get("path"), path))


def _direct_child(path: Any, workspace: Any) -> bool:
    try:
        root = canonical_host_path(workspace).resolve(strict=True)
        lexical = canonical_host_path(path)
        resolved = resolved_within(root, lexical)
        return lexical.parent == root and resolved is not None and resolved.parent == root
    except (OSError, RuntimeError, ValueError):
        return False


def _same(left: Any, right: Any) -> bool:
    try:
        return canonical_host_path(str(left or "")) == canonical_host_path(str(right or ""))
    except (OSError, RuntimeError, ValueError):
        return False

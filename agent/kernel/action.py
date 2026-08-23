from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import AgentEvent, utc_now
from .path_context import resolve_context_path


@dataclass(slots=True)
class NativeActionIntent:
    """A concrete movement ZN has decided its Body should perform next.

    This is not a skill and it is not an external-model instruction. It is the
    bridge between Thought and Body: cognition chooses an action, the action is
    persisted in working state, Body performs it, and the observed result flows
    back into the next Situation.
    """

    intent_id: str
    event_id: str
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = "native cognition selected a concrete body action"
    source: str = "native_deliberation"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NativeActionIntent":
        data = dict(raw)
        data["args"] = dict(data.get("args") or {})
        return cls(**data)


def derive_native_action_intent(
    event: AgentEvent,
    *,
    facts: dict[str, Any] | None = None,
) -> NativeActionIntent | None:
    """Return the resident's current default structured action choice."""

    intents = derive_native_action_intents(event, facts=facts)
    return intents[0] if intents else None


def derive_native_action_intents(
    event: AgentEvent,
    *,
    facts: dict[str, Any] | None = None,
) -> tuple[NativeActionIntent, ...]:
    """Compile the current ZN-owned structured action choice set.

    Ordinary task heuristics intentionally preserve the historical single-action
    behavior. Multiple actions are returned only when the current event carries
    an explicit ``native_action_options`` choice set. This distinction matters:
    two action-shaped clauses in a task may be sequential obligations rather
    than alternatives, so procedural memory must never reinterpret them as a
    choice merely to gain influence.

    A valid explicit ``body_action`` / ``native_action`` remains exclusive. The
    alternatives API never invents arguments and learned procedural evidence is
    not consulted here.
    """

    payload = event.payload or {}
    observed = facts if isinstance(facts, dict) else {}
    explicit = payload.get("body_action") or payload.get("native_action")

    if explicit:
        kind, args = _explicit_action(explicit, payload)
        if kind:
            args = _contextualize_action_args(args, payload)
            return (
                NativeActionIntent(
                    intent_id=f"act-{uuid.uuid4().hex[:12]}",
                    event_id=event.event_id,
                    kind=kind,
                    args=args,
                    reason="the oriented event contains a concrete body action",
                    source="structured_event",
                ),
            )

    raw_options = payload.get("native_action_options")
    if isinstance(raw_options, list):
        options: list[NativeActionIntent] = []
        for raw in raw_options[:8]:
            kind, args = _explicit_action(raw, {})
            if not kind:
                continue
            args = _contextualize_action_args(args, payload)
            options.append(
                NativeActionIntent(
                    intent_id=f"act-{uuid.uuid4().hex[:12]}",
                    event_id=event.event_id,
                    kind=kind,
                    args=args,
                    reason="the current event contains a bounded structured native action choice",
                    source="structured_choice",
                )
            )
        if options:
            return tuple(options)

    default = _derive_heuristic_native_action_intent(
        event,
        payload=payload,
        observed=observed,
    )
    return (default,) if default is not None else ()


def _derive_heuristic_native_action_intent(
    event: AgentEvent,
    *,
    payload: dict[str, Any],
    observed: dict[str, Any],
) -> NativeActionIntent | None:
    """Historical single-choice native action formation."""

    task = event.task.lower()
    raw_path = (
        payload.get("path")
        or payload.get("file")
        or payload.get("target")
        or payload.get("directory")
    )
    path = (
        str(resolve_context_path(str(raw_path), payload))
        if raw_path is not None and str(raw_path).strip()
        else None
    )
    command = payload.get("command")
    has_content = "content" in payload or "text" in payload
    content = payload.get("content", payload.get("text", ""))

    if command is not None and any(
        token in task
        for token in (
            "run ", "execute ", "build ", "test ", "start ",
            "运行", "执行", "构建", "测试", "启动",
        )
    ):
        explicit_workdir = payload.get("workdir")
        observed_workdir = None
        git = observed.get("git") if isinstance(observed.get("git"), dict) else {}
        if not explicit_workdir and git.get("available") is not False and git.get("root"):
            observed_workdir = str(git["root"])
        workdir = explicit_workdir or observed_workdir
        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="command",
            args={
                "command": str(command),
                **({"workdir": str(workdir)} if workdir else {}),
                **(
                    {"timeout": int(payload["timeout"])}
                    if payload.get("timeout") is not None
                    else {}
                ),
            },
            reason=(
                "native investigation observed the repository root that anchors the requested command"
                if observed_workdir
                else "native orientation identified an explicit local command to execute"
            ),
            source="native_deliberation" if observed_workdir else "native_orientation",
        )

    if path and has_content and any(
        token in task
        for token in (
            "write ", "create ", "save ", "ensure ", "replace ", "append ",
            "写", "创建", "保存", "确保", "替换", "追加",
        )
    ):
        append = bool(payload.get("append", "append" in task or "追加" in task))
        path_fact = _matching_path_fact(observed, path)
        preview = _matching_file_preview(observed, path)
        if path_fact is not None and bool(path_fact.get("exists")):
            path_type = str(path_fact.get("type") or "").strip().lower()
            if path_type in {"directory", "other", "unavailable"}:
                return None

        if path_fact is not None and not bool(path_fact.get("exists")):
            reason = (
                "native investigation observed that the requested file target is missing, "
                "so the requested text state requires one write movement"
            )
        elif preview is not None and not append:
            observed_text = str(preview.get("preview") or "")
            if bool(preview.get("truncated")):
                reason = (
                    "native investigation observed the current file but not its complete "
                    "contents; the requested text state still implies a concrete write movement"
                )
            elif observed_text != str(content):
                reason = (
                    "native investigation observed that current file content differs from "
                    "the requested text state, so a write movement is needed"
                )
            else:
                reason = (
                    "native investigation confirmed the current file before the explicitly "
                    "requested write movement"
                )
        elif path_fact is not None:
            reason = (
                "native investigation confirmed a compatible file target and the requested "
                "text state implies a concrete filesystem movement"
            )
        else:
            reason = "native evidence and requested state imply a concrete filesystem movement"

        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": path,
                "content": str(content),
                "append": append,
                "create_parents": bool(payload.get("create_parents", True)),
            },
            reason=reason,
            source="native_deliberation",
        )

    if path and any(
        token in task
        for token in ("list directory", "list folder", "列出目录", "列出文件")
    ):
        path_fact = _matching_path_fact(observed, path)
        if path_fact is not None:
            if not bool(path_fact.get("exists")):
                return None
            if str(path_fact.get("type") or "").strip().lower() != "directory":
                return None
        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="list_directory",
            args={"path": path},
            reason=(
                "native investigation confirmed that the requested target is a directory"
                if path_fact is not None
                else "the requested state can be obtained directly through the filesystem body"
            ),
            source="native_deliberation",
        )

    return None


def _matching_path_fact(
    facts: dict[str, Any],
    path: Any,
) -> dict[str, Any] | None:
    target = _path_key(path)
    paths = facts.get("paths") if isinstance(facts.get("paths"), list) else []
    for item in paths:
        if not isinstance(item, dict):
            continue
        if _path_key(item.get("path")) == target:
            return item
    return None


def _matching_file_preview(
    facts: dict[str, Any],
    path: Any,
) -> dict[str, Any] | None:
    target = _path_key(path)
    previews = (
        facts.get("file_previews")
        if isinstance(facts.get("file_previews"), list)
        else []
    )
    for item in previews:
        if not isinstance(item, dict):
            continue
        if _path_key(item.get("path")) == target:
            return item
    return None


def _path_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser())
    except (OSError, RuntimeError, ValueError):
        return text


def _contextualize_action_args(
    args: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    contextualized = dict(args)
    raw_path = contextualized.get("path") or contextualized.get("target")
    if raw_path is not None and str(raw_path).strip():
        contextualized["path"] = str(resolve_context_path(str(raw_path), payload))
        contextualized.pop("target", None)
    if contextualized.get("workdir") is None and payload.get("workdir") is not None:
        contextualized["workdir"] = payload["workdir"]
    return contextualized


def _explicit_action(
    explicit: Any,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if isinstance(explicit, str):
        kind = explicit.strip().lower()
        args = dict(payload.get("body_args") or payload.get("native_action_args") or {})
    elif isinstance(explicit, dict):
        kind = str(explicit.get("kind") or explicit.get("action") or "").strip().lower()
        raw_args = explicit.get("args")
        if isinstance(raw_args, dict):
            args = dict(raw_args)
        else:
            args = {
                key: value
                for key, value in explicit.items()
                if key not in {"kind", "action", "reason", "source"}
            }
    else:
        return "", {}

    # Let structured top-level event data fill common body arguments without
    # forcing callers to duplicate the same values inside body_action.args.
    for key in (
        "path", "target", "content", "text", "command", "workdir", "timeout",
        "append", "create_parents", "pid", "background", "pty",
    ):
        if key in payload and key not in args:
            args[key] = payload[key]
    if "content" not in args and "text" in args:
        args["content"] = args["text"]
    return kind, args

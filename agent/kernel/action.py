from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import AgentEvent, utc_now


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
    """Compile a concrete local action from an already-oriented event.

    The first implementation deliberately uses information ZN already owns:
    structured event payload plus native investigation facts. It does not ask a
    model to turn prose into a command. As richer native cognition develops,
    additional action derivation can feed the same intent shape without
    changing the Thought -> Body -> Outcome loop.
    """

    payload = event.payload or {}
    facts = dict(facts or {})
    explicit = payload.get("body_action") or payload.get("native_action")

    if explicit:
        kind, args = _explicit_action(explicit, payload)
        if kind:
            return NativeActionIntent(
                intent_id=f"act-{uuid.uuid4().hex[:12]}",
                event_id=event.event_id,
                kind=kind,
                args=args,
                reason="the oriented event contains a concrete body action",
                source="structured_event",
            )

    task = event.task.lower()
    path = (
        payload.get("path")
        or payload.get("file")
        or payload.get("target")
        or payload.get("directory")
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
        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="command",
            args={
                "command": str(command),
                **({"workdir": str(payload["workdir"])} if payload.get("workdir") else {}),
                **({"timeout": int(payload["timeout"])} if payload.get("timeout") is not None else {}),
            },
            reason="native orientation identified an explicit local command to execute",
            source="native_orientation",
        )

    if path and has_content and any(
        token in task
        for token in (
            "write ", "create ", "save ", "ensure ", "replace ", "append ",
            "写", "创建", "保存", "确保", "替换", "追加",
        )
    ):
        # Native evidence can show that an ensure-style request is already
        # satisfied. In that case no body movement is necessary.
        previews = facts.get("file_previews") if isinstance(facts.get("file_previews"), list) else []
        if "ensure" in task or "确保" in task:
            for preview in previews:
                if str(preview.get("path") or "") == str(path):
                    if str(preview.get("preview") or "") == str(content):
                        return None

        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": str(path),
                "content": str(content),
                "append": bool(payload.get("append", "append" in task or "追加" in task)),
                "create_parents": bool(payload.get("create_parents", True)),
            },
            reason="native evidence and requested state imply a concrete filesystem movement",
            source="native_deliberation",
        )

    if path and any(
        token in task
        for token in ("list directory", "list folder", "列出目录", "列出文件")
    ):
        return NativeActionIntent(
            intent_id=f"act-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="list_directory",
            args={"path": str(path)},
            reason="the requested state can be obtained directly through the filesystem body",
            source="native_deliberation",
        )

    return None


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
    return kind, args

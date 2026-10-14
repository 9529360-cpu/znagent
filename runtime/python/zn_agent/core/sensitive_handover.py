from __future__ import annotations

"""P3-8: sensitive-step handover -- ZN stops, the owner does it by hand.

Sensitive steps are the three things ZN must never do on the owner's
behalf: entering a password, entering a verification code / passing a
captcha, confirming a payment. When a team specialist's next step
touches one, the resident:

1. does NOT execute the step, does NOT record a completion claim;
2. records a pending handover (durable, in team shared memory) and
   journals it, so it is visible in the thread and auditable;
3. blocks the event (``blocked_by=user_presence_required`` -- the
   workbench already renders this as "waiting_for_user") until the
   owner resolves it.

The owner resolves it by doing the step themselves and saying
"做完了" (``team_handover_done`` RPC, or a "做完了" message when the
event has already failed closed). Only an explicit owner action
resolves a handover -- the model can never resolve its own handover,
and a resolved handover never re-fires for the same step.

Card contract: :func:`SensitiveHandover.card` is the shape a workbench
card renders (P2-4 approval-card work owns rendering; this module owns
state + blocking). The record never stores secrets: ``detail`` is a
fixed per-kind label, never echoed model/user text -- a handover must
not become a place where a pasted password or code gets persisted.

Scope: wired into team specialist execution (the P3-8 surface). The
generic non-team path keeps its existing fail-closed password-control
refusals; generalizing the card to every Body action is P2-4's job.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from .models import utc_now
from .team_memory import team_shared_memory

HANDOVER_MEMORY_KEY = "sensitive_handover"

#: What the owner must do themselves, per kind. No secrets, no values.
WHAT_USER_DOES = {
    "password": "请你自己在原界面输入密码。ZN 不会代填、代传密码。",
    "verification_code": "请你自己输入收到的验证码 / 完成人机验证。ZN 不会代填验证码。",
    "payment_confirmation": "请你自己核对金额、收款方并确认支付。ZN 不会代确认支付。",
}

#: Fixed, secret-free labels for what ZN stopped on.
_DETAIL_LABEL = {
    "password": "专员下一步涉及输入密码，已停下",
    "verification_code": "专员下一步需要验证码 / 人机验证，已停下",
    "payment_confirmation": "专员下一步需要确认支付，已停下",
}

#: Verbs that turn a sensitive noun into an *action* ("写一份支付流程文档"
#: is writing ABOUT payment, not paying -- it must not hand over).
#: Single-character CJK verbs carry lookbehind guards so "主要" (main)
#: does not match "要" and "觉得" does not match "得"; short English
#: verbs are word-bounded so "target"/"together" do not match "get".
_ACTION_VERBS = (
    r"输入|填写|填入|提供|告诉|键入|输|需要|(?<![主需首重])要|(?<![觉])得|"
    r"获取|确认|完成|进行|发起|扫码|提交|核对|"
    r"\benter\b|\btype\b|\bfill\b|\bsubmit\b|\bprovide\b|\bgive\b|\btell\b|"
    r"\brequire\b|\bneed\b|\bget\b|\bconfirm\b|\bcomplete\b|\bmake\b|"
    r"\bverify\b|\bapprove\b"
)

#: Verb-anchored patterns: sensitive noun + action verb nearby. Used for
#: structured steps (objective/action, never file content) and prose.
_ANCHORED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("password", rf"(?:{_ACTION_VERBS}).{{0,12}}(?:密码|password|passwd)"),
    ("password", r"(?:密码|password|passwd).{0,12}(?:输入|填写|填入|验证|登录|登陆|支付|确认|重置|找回)"),
    ("password", r"登录密码|登陆密码|账号密码|账户密码|支付密码|login password|account password|user password"),
    (
        "verification_code",
        rf"(?:{_ACTION_VERBS}).{{0,12}}(?:验证码|verification code|\botp\b|captcha)",
    ),
    (
        "verification_code",
        r"(?:验证码|verification code|\botp\b|captcha).{0,12}(?:输入|填写|填入|验证|确认|告诉|发送|获取)",
    ),
    (
        "verification_code",
        r"短信验证码|图形验证码|手机验证码|短信验证|手机验证|两步验证|双因素|人机验证|"
        r"verification code|one-time code|one time code|\b2fa\b|\botp\b|captcha",
    ),
    (
        "payment_confirmation",
        rf"(?:{_ACTION_VERBS}).{{0,12}}(?:支付|付款|转账|付费|payment|checkout)",
    ),
    (
        "payment_confirmation",
        r"(?:支付|付款|转账|付费|payment).{0,12}(?:确认|密码|验证|扫码|完成)",
    ),
    (
        "payment_confirmation",
        r"确认支付|确认付款|扫码支付|支付密码|付款确认|confirm payment|payment confirmation|approve (?:the )?payment",
    ),
)

#: Bare nouns that hand over in *prose* only ("下一步是验证码" from a
#: specialist is a handover; "写一份验证码接入文档" as a structured
#: objective is not -- structured steps use the anchored patterns).
_PROSE_BARE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("password", r"密码"),
    ("verification_code", r"验证码|captcha|\botp\b"),
    ("payment_confirmation", r"确认支付|确认付款|扫码支付"),
)

#: "密码" followed by one of these is about cryptography / policy, not
#: credentials ("密码学", "密码算法", "密码策略", "密码强度").
_PASSWORD_BENIGN_FOLLOW = ("学", "算法", "策略", "强度")


@dataclass(frozen=True, slots=True)
class SensitiveStep:
    """One detected sensitive step: its kind, nothing else."""

    kind: str  # password | verification_code | payment_confirmation

    @property
    def detail(self) -> str:
        return _DETAIL_LABEL[self.kind]


def _probe_text(text: str) -> tuple[str, bool]:
    """Text to scan + whether it was a structured specialist step.

    For a structured ``zn_work_step`` proposal, only the objective and
    the action (kind/path/args) are scanned -- never the file ``content``:
    writing a document *about* passwords is not entering one. For a
    structured completion report, the conclusion + unfinished list are
    scanned (a claim that "the user must enter the password" is a
    handover signal). Anything else is prose: scan it all.
    """
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return str(text or ""), False
    if not isinstance(parsed, dict):
        return str(text or ""), False
    step = parsed.get("zn_work_step")
    if isinstance(step, dict):
        action = step.get("action")
        action_text = ""
        if isinstance(action, dict):
            action_text = " ".join(
                str(action.get(key) or "")
                for key in ("kind", "path")
            ) + " " + " ".join(
                str(arg) for arg in (action.get("args") or []) if arg is not None
            )
        return f"{step.get('objective') or ''} {action_text}", True
    report = parsed.get("completion_report")
    if isinstance(report, dict):
        unfinished = report.get("unfinished") or []
        return (
            f"{report.get('conclusion') or ''} "
            + " ".join(str(item) for item in unfinished if item is not None),
            True,
        )
    return str(text or ""), False


def detect_sensitive_step(text: str) -> SensitiveStep | None:
    """Detect a sensitive step in specialist cognition output.

    Returns None when the text is not a sensitive step. Never echoes
    input text into the result: the caller records only the kind.
    """
    if not text or not str(text).strip():
        return None
    probe, structured = _probe_text(str(text))
    for kind, pattern in _ANCHORED_PATTERNS:
        for match in re.finditer(pattern, probe, flags=re.IGNORECASE):
            if kind == "password":
                # "需要密码学知识" / "密码策略" is cryptography / policy,
                # not a credential -- skip benign occurrences.
                tail = probe[match.end():match.end() + 2]
                if any(tail.startswith(word) for word in _PASSWORD_BENIGN_FOLLOW):
                    continue
            return SensitiveStep(kind=kind)
    if not structured:
        for kind, pattern in _PROSE_BARE_PATTERNS:
            for match in re.finditer(pattern, probe, flags=re.IGNORECASE):
                if kind == "password":
                    # "密码学" / "密码算法" in prose is cryptography, not a
                    # credential -- skip benign occurrences, keep the rest.
                    tail = probe[match.end():match.end() + 2]
                    if any(
                        tail.startswith(word)
                        for word in _PASSWORD_BENIGN_FOLLOW
                    ):
                        continue
                return SensitiveStep(kind=kind)
    return None


# A "done" declaration: the owner finished the sensitive step by hand.
# The optional trailing "继续..." covers the natural "做完了，继续".
# Anything else trailing ("做完了就发我") does NOT match -- it is not a
# plain done declaration, so it must not silently resolve a handover.
_HANDOVER_DONE_RE = re.compile(
    r"^(?:我)?(?:已经|已)?(?:做完了|搞定了|弄好了|完成了|完成|done)[，。,；;！!、\s]*(?:继续.*)?$",
    flags=re.IGNORECASE,
)


def parse_handover_done(task: str) -> bool:
    """True when the message is a plain "done" declaration."""
    if not task or not str(task).strip():
        return False
    return bool(_HANDOVER_DONE_RE.match(str(task).strip()))


@dataclass(slots=True)
class SensitiveHandover:
    """One pending / resolved sensitive-step handover. Secret-free."""

    handover_id: str
    kind: str
    detail: str
    status: str  # pending | resolved
    requested_at: str
    resolved_at: str | None = None

    def what_user_does(self) -> str:
        return WHAT_USER_DOES.get(self.kind, "请你自己完成这一步，ZN 不代办。")

    def card(self) -> dict[str, Any]:
        """Render contract for the workbench card (P2-4 owns rendering)."""
        return {
            "handover_id": self.handover_id,
            "kind": self.kind,
            "title": "需要你亲自完成",
            "detail": self.detail,
            "what_user_does": self.what_user_does(),
            "status": self.status,
            "actions": ["做完了"] if self.status == "pending" else [],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "handover_id": self.handover_id,
            "kind": self.kind,
            "detail": self.detail,
            "status": self.status,
            "requested_at": self.requested_at,
            "resolved_at": self.resolved_at,
        }

    @staticmethod
    def from_dict(raw: Any) -> "SensitiveHandover | None":
        if not isinstance(raw, dict):
            return None
        handover_id = str(raw.get("handover_id") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if not handover_id or kind not in WHAT_USER_DOES:
            return None
        return SensitiveHandover(
            handover_id=handover_id,
            kind=kind,
            detail=str(raw.get("detail") or _DETAIL_LABEL.get(kind, ""))[:300],
            status=str(raw.get("status") or "pending"),
            requested_at=str(raw.get("requested_at") or ""),
            resolved_at=raw.get("resolved_at"),
        )


def pending_handover(memory: Any, team_id: str) -> SensitiveHandover | None:
    """The team's pending handover, if any. None when none / resolved."""
    if not team_id or not str(team_id).strip():
        return None
    shared = team_shared_memory(memory, str(team_id).strip())
    match = shared.recall(HANDOVER_MEMORY_KEY)
    if match is None:
        return None
    handover = SensitiveHandover.from_dict(match.value)
    if handover is None or handover.status != "pending":
        return None
    return handover


def request_handover(
    *,
    memory: Any,
    ledger: Any,
    team_id: str,
    thread_id: str,
    kind: str,
    detail: str | None = None,
) -> SensitiveHandover:
    """Record a pending handover (memory + journal). Idempotent per team.

    A second sensitive step while one is pending returns the existing
    record instead of stacking a second card: the owner resolves the
    first one, then the resident re-asks and the next step hands over
    on its own if it is still sensitive.
    """
    team_id = str(team_id or "").strip()
    thread_id = str(thread_id or "").strip()
    if not team_id or kind not in WHAT_USER_DOES:
        raise ValueError("request_handover requires a team_id and a known kind")
    existing = pending_handover(memory, team_id)
    if existing is not None:
        return existing
    handover = SensitiveHandover(
        handover_id=f"handover-{uuid.uuid4().hex[:12]}",
        kind=kind,
        detail=(str(detail or "")[:300] or _DETAIL_LABEL[kind]),
        status="pending",
        requested_at=utc_now(),
    )
    shared = team_shared_memory(memory, team_id)
    shared.remember(HANDOVER_MEMORY_KEY, handover.to_dict())
    if thread_id:
        ledger.append_message(
            thread_id,
            role=f"team:{team_id}:coordinator",
            text=(
                f"ZN 已停下，需要你亲自完成：{handover.detail}。"
                f"{handover.what_user_does()}完成后点“做完了”，ZN 再继续。"
            ),
            detail={
                "kind": "handover_pending",
                "team_id": team_id,
                "author": "coordinator",
                "handover_id": handover.handover_id,
                "sensitive_kind": kind,
            },
        )
    return handover


def resolve_handover(
    *,
    memory: Any,
    ledger: Any,
    team_id: str,
    thread_id: str,
) -> SensitiveHandover | None:
    """Resolve the team's pending handover. None when there was none.

    Only an explicit owner action calls this (``team_handover_done``
    RPC or a "做完了" message at ingress). The model can never resolve
    its own handover: no resident path calls this on cognition output.
    """
    team_id = str(team_id or "").strip()
    thread_id = str(thread_id or "").strip()
    pending = pending_handover(memory, team_id)
    if pending is None:
        return None
    resolved = SensitiveHandover(
        handover_id=pending.handover_id,
        kind=pending.kind,
        detail=pending.detail,
        status="resolved",
        requested_at=pending.requested_at,
        resolved_at=utc_now(),
    )
    shared = team_shared_memory(memory, team_id)
    shared.remember(HANDOVER_MEMORY_KEY, resolved.to_dict())
    if thread_id:
        ledger.append_message(
            thread_id,
            role=f"team:{team_id}:coordinator",
            text="敏感步骤已由主人亲自完成，ZN 继续。",
            detail={
                "kind": "handover_resolved",
                "team_id": team_id,
                "author": "coordinator",
                "handover_id": resolved.handover_id,
                "sensitive_kind": resolved.kind,
            },
        )
    return resolved


__all__ = [
    "HANDOVER_MEMORY_KEY",
    "SensitiveHandover",
    "SensitiveStep",
    "detect_sensitive_step",
    "parse_handover_done",
    "pending_handover",
    "request_handover",
    "resolve_handover",
]

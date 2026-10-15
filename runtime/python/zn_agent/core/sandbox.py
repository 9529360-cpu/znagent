from __future__ import annotations

"""Three-tier action sandbox (DSH-6) + one-shot escalation.

The sandbox answers "what can this call touch", while the W-1 permission
model (``permission_model.py``) answers "is this action allowed". The two
layers are complementary: a call must pass both.

Tiers:

- ``read_only`` -- reads only. Every write, command, and other
  side-effecting call is denied.
- ``workspace_write`` -- reads plus writes confined to the session
  workspace. A write whose target is outside ``workspace_root`` is denied.
  Raw commands are denied: a shell command is not provably confined to the
  workspace, so fail-closed applies. Other side-effecting calls (send,
  publish, purchase, ...) are denied.
- ``danger_full_access`` -- everything is allowed, but every call is
  audited. The tier is for explicitly user-approved dangerous work, not a
  default.

One-shot escalation: a call denied by the sandbox can be retried once
after the user approves it. The approval produces a single-use token bound
to the exact call fingerprint (kind + canonical args digest). Consuming
the token allows exactly one retry; a second identical call with the same
token is denied again. Denying the escalation executes nothing. The
escalation is never persisted and never widens later permissions: every
decision -- allow, deny, approve, reject, consume -- is appended to the
audit trail.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class SandboxTier(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    DANGER_FULL_ACCESS = "danger_full_access"


def parse_sandbox_tier(raw: str | SandboxTier) -> SandboxTier:
    if isinstance(raw, SandboxTier):
        return raw
    normalized = str(raw or "").strip().lower()
    for tier in SandboxTier:
        if tier.value == normalized:
            return tier
    raise ValueError(f"unsupported sandbox tier: {normalized or '<empty>'}")


class SandboxDeniedError(PermissionError):
    """Raised when the sandbox refuses a call (with its escalation id)."""


# Call categories. Unknown kinds are fail-closed: they count as
# side-effecting, so only danger_full_access allows them.
_READ_KINDS = {
    "inspect_path",
    "path",
    "read_text",
    "read_file",
    "list_directory",
    "list_dir",
    "git_state",
    "git",
    "git_diff",
}
_WRITE_KINDS = {
    "write_text",
    "write_file",
    "delete_file",
    "delete_path",
    "delete",
    "remove",
    "remove_path",
    "trash_path",
    "append_text",
    "append_file",
}
_COMMAND_KINDS = {"command", "terminal", "shell", "run_python"}


def classify_call(kind: str) -> str:
    """Classify a call kind as ``read`` / ``write`` / ``command`` / ``other``."""
    normalized = str(kind or "").strip().lower()
    if normalized in _READ_KINDS:
        return "read"
    if normalized in _WRITE_KINDS:
        return "write"
    if normalized in _COMMAND_KINDS:
        return "command"
    return "other"


def canonical_call_fingerprint(kind: str, args: dict[str, Any]) -> str:
    """Deterministic fingerprint of a call: kind + canonical args digest."""
    canonical = json.dumps(
        {"kind": str(kind or "").strip().lower(), "args": dict(args or {})},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True, slots=True)
class SandboxAuditEntry:
    """One audited sandbox event. JSON-serializable via :meth:`to_dict`."""

    event: str  # allow | deny | escalate_request | escalate_approve | escalate_deny | escalate_consume
    kind: str
    category: str
    tier: str
    reason: str
    escalation_id: str | None = None
    escalated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "kind": self.kind,
            "category": self.category,
            "tier": self.tier,
            "reason": self.reason,
            "escalation_id": self.escalation_id,
            "escalated": self.escalated,
        }


@dataclass(frozen=True, slots=True)
class SandboxDecision:
    """Result of a sandbox check."""

    allowed: bool
    reason: str
    kind: str = ""
    category: str = ""
    tier: str = ""
    escalated: bool = False
    escalation_id: str | None = None


@dataclass(frozen=True, slots=True)
class EscalationRequest:
    request_id: str
    kind: str
    fingerprint: str
    status: str  # pending | approved | denied | consumed
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OneShotToken:
    """Single-use escalation token, bound to one exact call fingerprint."""

    token_id: str
    request_id: str
    fingerprint: str
    consumed: bool = False


class OneShotEscalationManager:
    """Pending escalation requests + single-use tokens. In-memory only."""

    def __init__(self, *, audit: list[SandboxAuditEntry] | None = None) -> None:
        self._requests: dict[str, EscalationRequest] = {}
        self._tokens: dict[str, OneShotToken] = {}
        self._audit = audit if audit is not None else []

    @property
    def requests(self) -> dict[str, EscalationRequest]:
        return dict(self._requests)

    def request(
        self,
        kind: str,
        args: dict[str, Any],
        *,
        category: str = "",
        tier: str = "",
        reason: str = "",
    ) -> EscalationRequest:
        fingerprint = canonical_call_fingerprint(kind, args)
        req = EscalationRequest(
            request_id=f"esc-{uuid.uuid4().hex[:12]}",
            kind=str(kind or "").strip().lower(),
            fingerprint=fingerprint,
            status="pending",
            args=dict(args or {}),
        )
        self._requests[req.request_id] = req
        self._audit.append(
            SandboxAuditEntry(
                event="escalate_request",
                kind=req.kind,
                category=category,
                tier=tier,
                reason=reason or "sandbox denied call; escalation requested",
                escalation_id=req.request_id,
            )
        )
        return req

    def approve(self, request_id: str) -> OneShotToken:
        req = self._requests.get(str(request_id or ""))
        if req is None:
            raise ValueError(f"unknown escalation request: {request_id!r}")
        if req.status != "pending":
            raise ValueError(
                f"escalation request {request_id!r} is already {req.status}"
            )
        token = OneShotToken(
            token_id=f"tok-{uuid.uuid4().hex[:16]}",
            request_id=req.request_id,
            fingerprint=req.fingerprint,
        )
        self._requests[req.request_id] = EscalationRequest(
            request_id=req.request_id,
            kind=req.kind,
            fingerprint=req.fingerprint,
            status="approved",
            args=req.args,
        )
        self._tokens[token.token_id] = token
        self._audit.append(
            SandboxAuditEntry(
                event="escalate_approve",
                kind=req.kind,
                category="",
                tier="",
                reason="user approved one-shot escalation for this call only",
                escalation_id=req.request_id,
            )
        )
        return token

    def deny(self, request_id: str, *, reason: str = "") -> None:
        req = self._requests.get(str(request_id or ""))
        if req is None:
            raise ValueError(f"unknown escalation request: {request_id!r}")
        if req.status != "pending":
            raise ValueError(
                f"escalation request {request_id!r} is already {req.status}"
            )
        self._requests[req.request_id] = EscalationRequest(
            request_id=req.request_id,
            kind=req.kind,
            fingerprint=req.fingerprint,
            status="denied",
            args=req.args,
        )
        self._audit.append(
            SandboxAuditEntry(
                event="escalate_deny",
                kind=req.kind,
                category="",
                tier="",
                reason=reason or "user denied escalation; call not executed",
                escalation_id=req.request_id,
            )
        )

    def consume(self, token_id: str, kind: str, args: dict[str, Any]) -> bool:
        """Consume a token for one exact call. True only on the first match."""
        token = self._tokens.get(str(token_id or ""))
        if token is None or token.consumed:
            return False
        if canonical_call_fingerprint(kind, args) != token.fingerprint:
            return False
        self._tokens[token.token_id] = OneShotToken(
            token_id=token.token_id,
            request_id=token.request_id,
            fingerprint=token.fingerprint,
            consumed=True,
        )
        req = self._requests.get(token.request_id)
        if req is not None:
            self._requests[req.request_id] = EscalationRequest(
                request_id=req.request_id,
                kind=req.kind,
                fingerprint=req.fingerprint,
                status="consumed",
                args=req.args,
            )
        self._audit.append(
            SandboxAuditEntry(
                event="escalate_consume",
                kind=str(kind or "").strip().lower(),
                category="",
                tier="",
                reason="one-shot escalation token consumed for this call only",
                escalation_id=token.request_id,
                escalated=True,
            )
        )
        return True


@dataclass
class SandboxPolicy:
    """Tier + workspace root. Every check appends an audit entry."""

    tier: SandboxTier = SandboxTier.WORKSPACE_WRITE
    workspace_root: str | None = None
    audit: list[SandboxAuditEntry] = field(default_factory=list)
    audit_sink: Callable[[SandboxAuditEntry], None] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.tier, str):
            object.__setattr__(self, "tier", parse_sandbox_tier(self.tier))
        root = str(self.workspace_root or "").strip() or None
        object.__setattr__(self, "workspace_root", root)

    def _record(self, entry: SandboxAuditEntry) -> None:
        self.audit.append(entry)
        if self.audit_sink is not None:
            self.audit_sink(entry)

    def check(self, kind: str, args: dict[str, Any]) -> SandboxDecision:
        """Check a call against the tier. Pure enforcement, no escalation."""
        normalized_kind = str(kind or "").strip().lower()
        category = classify_call(normalized_kind)
        tier = self.tier
        if tier is SandboxTier.DANGER_FULL_ACCESS:
            decision = SandboxDecision(
                allowed=True,
                reason="danger_full_access allows the call (audited)",
                kind=normalized_kind,
                category=category,
                tier=tier.value,
            )
            self._record(
                SandboxAuditEntry(
                    event="allow",
                    kind=normalized_kind,
                    category=category,
                    tier=tier.value,
                    reason=decision.reason,
                )
            )
            return decision

        denied_reason: str | None = None
        if category == "read":
            denied_reason = None
        elif category == "write":
            if tier is SandboxTier.READ_ONLY:
                denied_reason = "read_only tier denies all writes"
            else:
                denied_reason = self._write_reason(args)
        elif category == "command":
            denied_reason = (
                "read_only tier denies commands"
                if tier is SandboxTier.READ_ONLY
                else "workspace_write tier denies raw commands (not provably workspace-confined)"
            )
        else:  # other / unknown kinds fail closed
            denied_reason = (
                f"{tier.value} tier denies side-effecting call kind {normalized_kind or '<empty>'}"
            )

        if denied_reason is None:
            decision = SandboxDecision(
                allowed=True,
                reason=f"{tier.value} allows {category} call",
                kind=normalized_kind,
                category=category,
                tier=tier.value,
            )
            self._record(
                SandboxAuditEntry(
                    event="allow",
                    kind=normalized_kind,
                    category=category,
                    tier=tier.value,
                    reason=decision.reason,
                )
            )
            return decision
        decision = SandboxDecision(
            allowed=False,
            reason=denied_reason,
            kind=normalized_kind,
            category=category,
            tier=tier.value,
        )
        self._record(
            SandboxAuditEntry(
                event="deny",
                kind=normalized_kind,
                category=category,
                tier=tier.value,
                reason=denied_reason,
            )
        )
        return decision

    def _write_reason(self, args: dict[str, Any]) -> str | None:
        """None when the write target is inside the workspace; else a reason."""
        if not self.workspace_root:
            return "workspace_write tier denies writes without a workspace root"
        target = self._write_target(args)
        if target is None:
            return "write without a target path cannot be proven workspace-confined"
        root = Path(self.workspace_root).expanduser().resolve(strict=False)
        resolved = Path(str(target)).expanduser().resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            return f"write target {str(target)!r} is outside the workspace"
        return None

    @staticmethod
    def _write_target(args: dict[str, Any]) -> str | None:
        for key in ("path", "target", "file", "workdir", "root"):
            value = (args or {}).get(key)
            if value is not None and str(value).strip():
                return str(value)
        return None


class SandboxGate:
    """Policy enforcement + one-shot escalation, sharing one audit trail."""

    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        *,
        escalation: OneShotEscalationManager | None = None,
    ) -> None:
        self.policy = policy if policy is not None else SandboxPolicy()
        # The escalation manager shares the policy's audit list so the full
        # allow/deny/approve/reject/consume trail lives in one place.
        self.escalation = escalation or OneShotEscalationManager(audit=self.policy.audit)

    def authorize(
        self,
        kind: str,
        args: dict[str, Any],
        escalation_token: str | None = None,
    ) -> SandboxDecision:
        """Authorize a call, optionally with a one-shot escalation token.

        Denied calls get a pending escalation request (``decision.escalation_id``)
        that the user can approve or deny. An approved token allows exactly
        one retry of the identical call; a second use is denied again.
        """
        decision = self.policy.check(kind, args)
        if decision.allowed:
            return decision
        if escalation_token:
            if self.escalation.consume(escalation_token, kind, args):
                return SandboxDecision(
                    allowed=True,
                    reason="one-shot escalation approved by the user; valid for this call only",
                    kind=decision.kind,
                    category=decision.category,
                    tier=decision.tier,
                    escalated=True,
                    escalation_id=decision.escalation_id,
                )
            self.policy._record(
                SandboxAuditEntry(
                    event="deny",
                    kind=decision.kind,
                    category=decision.category,
                    tier=decision.tier,
                    reason="escalation token invalid, consumed, or bound to a different call",
                    escalation_id=decision.escalation_id,
                )
            )
            return SandboxDecision(
                allowed=False,
                reason="escalation token invalid, consumed, or bound to a different call",
                kind=decision.kind,
                category=decision.category,
                tier=decision.tier,
                escalation_id=decision.escalation_id,
            )
        req = self.escalation.request(
            kind,
            args,
            category=decision.category,
            tier=decision.tier,
            reason=decision.reason,
        )
        return SandboxDecision(
            allowed=False,
            reason=decision.reason,
            kind=decision.kind,
            category=decision.category,
            tier=decision.tier,
            escalation_id=req.request_id,
        )

    def require(
        self,
        kind: str,
        args: dict[str, Any],
        escalation_token: str | None = None,
    ) -> SandboxDecision:
        """Like :meth:`authorize` but raises :class:`SandboxDeniedError` on denial."""
        decision = self.authorize(kind, args, escalation_token)
        if not decision.allowed:
            raise SandboxDeniedError(
                f"sandbox denied {decision.kind or '<empty>'} "
                f"({decision.reason}; escalation_id={decision.escalation_id})"
            )
        return decision

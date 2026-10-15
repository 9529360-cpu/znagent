from __future__ import annotations

"""Durable approval cards for sensitive actions (P2-4).

A sensitive action (send / publish / purchase / delete / production_change)
must not execute on ZN's say-so alone. The resident records one approval
request per proposed action, the workbench shows it as a card with the
action, target, scope and value, and the user decides:

- ``allow_once`` -- approve this one request only;
- ``always_allow`` -- approve this request and remember an auto-allow rule
  for the same action + scope;
- ``deny`` -- refuse; the action never executes.

Deny semantics (sticky, with one controlled override):

- Deny is sticky: once a (action kind, scope, target) triple is denied,
  the gate keeps blocking that triple. Deny outranks auto-allow rules --
  a rule created afterwards does NOT silently unblock a denied triple,
  because a rule is for future requests, not a retroactive override.
- Deny is terminal for its request: the denied record is never mutated
  back to pending or approved.
- The only way to re-ask a denied triple is an explicit user
  reconsideration: ``ApprovalCardStore.reconsider_denied`` (exposed to the
  workbench as daemon RPC ``approval_reconsider_denied``), which creates a
  fresh pending request for the same triple and writes an audited
  ``deny_overridden`` entry linking the denied request to the new one.
  There is no silent or agent-side path around a deny: the agent's
  execution path only ever goes through ``ApprovalGate.check``, which
  never reconsiders a deny on its own.
- A denied triple that is reconsidered and denied again needs another
  explicit reconsideration; each override is individually audited.

Rules are narrow by construction: a rule matches exactly one action kind and
one scope. Broad rules (``*``, ``browser``, ``everything`` ...) are rejected.
When an ``ask_first`` rule and an ``auto_allow`` rule both match,
``ask_first`` wins. Unattended sources (routines, specialists, other bots,
triggers) expire after 10 minutes; expired requests never execute, but the
user can still pick "always allow this kind" from an expired card, which
only creates the rule for future requests.

Every decision is appended to an immutable audit log, so approvals stay
auditable. This module owns the ledger; the workbench talks to it through
the resident RPC, and ``ActionExecutionRuntime`` consults ``ApprovalGate``
before dispatching actions whose descriptor opts in with an
``approval:<kind>`` tag.

Editable commands (W-1): when the user approves a command request they
may edit the command on the card. The edited command is stored on the
request as ``approved_command`` and the execution path runs the edited
version, never the original. The edited command is re-checked against
the permission policy denylist at decision time (when a policy is
supplied) and again when the gate consumes the approval (defense in
depth): a denylisted edit never executes, the approval is spent, and the
block is audited as ``edited_command_denied``.

Permission policy (W-1): an optional structured ``PermissionPolicy`` may
be attached to the gate. It is consulted after the sticky-deny check and
before the rule evaluation: denylist blocks, session auto-approve /
always_allow lets the action through without a card, ask / agent_decides
falls through to the existing rules.
"""

import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import utc_now
from .permission_model import PermissionPolicy, PermissionVerdict


APPROVAL_KINDS = ("send", "publish", "purchase", "delete", "production_change")

APPROVAL_SOURCES = (
    "user_chat",
    "resident",
    "routine",
    "specialist",
    "other_bot",
    "trigger",
    "mcp",
)

UNATTENDED_SOURCES = frozenset({"routine", "specialist", "other_bot", "trigger", "mcp"})

UNATTENDED_TTL_SECONDS = 600
ATTENDED_TTL_SECONDS = 86400

REQUEST_STATUSES = (
    "pending",
    "approved_once",
    "approved",
    "consumed",
    "denied",
    "expired",
)

DECISIONS = ("allow_once", "always_allow", "deny")

RULE_EFFECTS = ("ask_first", "auto_allow")

# Scopes that would let one rule bless a whole surface ("allow everything in
# the browser"). Rules must name one concrete scope.
_REJECTED_SCOPES = {
    "",
    "*",
    "all",
    "any",
    "everything",
    "browser",
    "browser.*",
    "browser:*",
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validate_approval_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized not in APPROVAL_KINDS:
        raise ValueError(f"unsupported approval kind: {normalized or '<empty>'}")
    return normalized


def validate_approval_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized not in APPROVAL_SOURCES:
        raise ValueError(f"unsupported approval source: {normalized or '<empty>'}")
    return normalized


def validate_approval_scope(scope: str) -> str:
    normalized = " ".join(str(scope or "").split())
    if not normalized:
        raise ValueError("approval scope must not be empty")
    if len(normalized) > 200:
        raise ValueError("approval scope is too long")
    if "*" in normalized:
        raise ValueError("approval scope must not contain a wildcard")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("approval scope contains control characters")
    if normalized.lower() in _REJECTED_SCOPES:
        raise ValueError(
            "approval scope is too broad: name one concrete scope, "
            "not a whole surface such as 'browser' or 'everything'"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: str
    action_kind: str
    target: str
    scope: str
    value_text: str = ""
    source: str = "resident"
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    expires_at: str = ""
    decided_at: str | None = None
    decision: str | None = None
    event_id: str | None = None
    # Command approved by the user after editing it on the card. Empty
    # means "run the original command"; the execution path runs this
    # version when set.
    approved_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ApprovalRequest":
        return cls(
            request_id=str(raw.get("request_id") or ""),
            action_kind=str(raw.get("action_kind") or ""),
            target=str(raw.get("target") or ""),
            scope=str(raw.get("scope") or ""),
            value_text=str(raw.get("value_text") or ""),
            source=str(raw.get("source") or "resident"),
            status=str(raw.get("status") or "pending"),
            created_at=str(raw.get("created_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
            decided_at=str(raw.get("decided_at") or "") or None,
            decision=str(raw.get("decision") or "") or None,
            event_id=str(raw.get("event_id") or "") or None,
            approved_command=str(raw.get("approved_command") or ""),
        )


@dataclass(frozen=True, slots=True)
class ApprovalRule:
    rule_id: str
    action_kind: str
    scope: str
    effect: str
    created_at: str = field(default_factory=utc_now)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ApprovalRule":
        return cls(
            rule_id=str(raw.get("rule_id") or ""),
            action_kind=str(raw.get("action_kind") or ""),
            scope=str(raw.get("scope") or ""),
            effect=str(raw.get("effect") or ""),
            created_at=str(raw.get("created_at") or ""),
            enabled=bool(raw.get("enabled", True)),
        )


@dataclass(frozen=True, slots=True)
class ApprovalAuditEntry:
    audit_id: str
    request_id: str | None
    decision: str
    action_kind: str
    scope: str
    rule_id: str | None = None
    note: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ApprovalGateOutcome:
    allowed: bool
    request_id: str | None = None
    reason: str = ""
    # Command the execution path must run when set: the user-edited
    # version approved on the card. None means "run the original".
    approved_command: str | None = None


# Approval kind -> permission-policy action type. "delete" maps to the
# policy's file_delete type; the rest share names.
_POLICY_ACTION_TYPE_BY_KIND = {
    "send": "send",
    "publish": "publish",
    "purchase": "purchase",
    "delete": "file_delete",
    "production_change": "production_change",
}


_REQUESTS_TABLE = "approval_requests"
_RULES_TABLE = "approval_rules"
_AUDIT_TABLE = "approval_audit"


class ApprovalCardStore:
    """SQLite-backed approval requests, rules and audit log."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {_REQUESTS_TABLE}(
                    request_id TEXT PRIMARY KEY,
                    action_kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    value_text TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    decision TEXT,
                    event_id TEXT,
                    approved_command TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_approval_requests_status
                    ON {_REQUESTS_TABLE}(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_approval_requests_triple
                    ON {_REQUESTS_TABLE}(action_kind, scope, target, created_at DESC);
                CREATE TABLE IF NOT EXISTS {_RULES_TABLE}(
                    rule_id TEXT PRIMARY KEY,
                    action_kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(action_kind, scope, effect)
                );
                CREATE INDEX IF NOT EXISTS idx_approval_rules_pair
                    ON {_RULES_TABLE}(action_kind, scope);
                CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE}(
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    decision TEXT NOT NULL,
                    action_kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    rule_id TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_approval_audit_created
                    ON {_AUDIT_TABLE}(created_at DESC);
                """
            )
            conn.commit()
            # Migration: databases created before W-1 lack approved_command.
            columns = {
                row[1]
                for row in conn.execute(
                    f"PRAGMA table_info({_REQUESTS_TABLE})"
                ).fetchall()
            }
            if "approved_command" not in columns:
                conn.execute(
                    f"ALTER TABLE {_REQUESTS_TABLE} "
                    "ADD COLUMN approved_command TEXT NOT NULL DEFAULT ''"
                )
                conn.commit()

    # -- requests -----------------------------------------------------------

    def request_approval(
        self,
        *,
        action_kind: str,
        target: str,
        scope: str,
        value_text: str = "",
        source: str = "resident",
        event_id: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        kind = validate_approval_kind(action_kind)
        normalized_source = validate_approval_source(source)
        normalized_scope = validate_approval_scope(scope)
        normalized_target = " ".join(str(target or "").split())
        if not normalized_target:
            raise ValueError("approval target must not be empty")
        if len(normalized_target) > 500:
            raise ValueError("approval target is too long")
        normalized_value = " ".join(str(value_text or "").split())[:1000]
        current = now or datetime.now(timezone.utc)
        self.expire_overdue(now=current)
        ttl = (
            UNATTENDED_TTL_SECONDS
            if normalized_source in UNATTENDED_SOURCES
            else ATTENDED_TTL_SECONDS
        )
        expires_at = (current + timedelta(seconds=ttl)).isoformat()
        created_at = current.isoformat()
        with closing(self._connect()) as conn:
            existing = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} "
                "WHERE action_kind = ? AND scope = ? AND target = ? "
                "AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (kind, normalized_scope, normalized_target),
            ).fetchone()
            if existing is not None:
                return ApprovalRequest.from_dict(dict(existing))
            request = ApprovalRequest(
                request_id=f"approval-{uuid.uuid4().hex[:16]}",
                action_kind=kind,
                target=normalized_target,
                scope=normalized_scope,
                value_text=normalized_value,
                source=normalized_source,
                status="pending",
                created_at=created_at,
                expires_at=expires_at,
                event_id=str(event_id or "").strip() or None,
            )
            conn.execute(
                f"INSERT INTO {_REQUESTS_TABLE} "
                "(request_id, action_kind, target, scope, value_text, source, "
                "status, created_at, expires_at, decided_at, decision, event_id, "
                "approved_command) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.request_id,
                    request.action_kind,
                    request.target,
                    request.scope,
                    request.value_text,
                    request.source,
                    request.status,
                    request.created_at,
                    request.expires_at,
                    request.decided_at,
                    request.decision,
                    request.event_id,
                    request.approved_command,
                ),
            )
            conn.commit()
            return request

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        normalized = str(request_id or "").strip()
        if not normalized:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} WHERE request_id = ?",
                (normalized,),
            ).fetchone()
        return ApprovalRequest.from_dict(dict(row)) if row is not None else None

    def pending_requests(self, *, limit: int = 100) -> list[ApprovalRequest]:
        self.expire_overdue()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [ApprovalRequest.from_dict(dict(row)) for row in rows]

    def expired_requests(self, *, limit: int = 100) -> list[ApprovalRequest]:
        self.expire_overdue()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} WHERE status = 'expired' "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [ApprovalRequest.from_dict(dict(row)) for row in rows]

    def denied_requests(self, *, limit: int = 100) -> list[ApprovalRequest]:
        self.expire_overdue()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} WHERE status = 'denied' "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [ApprovalRequest.from_dict(dict(row)) for row in rows]

    def latest_request_for(
        self, *, action_kind: str, scope: str, target: str
    ) -> ApprovalRequest | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT * FROM {_REQUESTS_TABLE} "
                "WHERE action_kind = ? AND scope = ? AND target = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (
                    validate_approval_kind(action_kind),
                    validate_approval_scope(scope),
                    " ".join(str(target or "").split()),
                ),
            ).fetchone()
        return ApprovalRequest.from_dict(dict(row)) if row is not None else None

    def expire_overdue(self, *, now: datetime | None = None) -> int:
        current = (now or datetime.now(timezone.utc)).isoformat()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE {_REQUESTS_TABLE} SET status = 'expired' "
                "WHERE status = 'pending' AND expires_at <= ?",
                (current,),
            )
            conn.commit()
            return cursor.rowcount

    # -- decisions ----------------------------------------------------------

    def decide(
        self,
        request_id: str,
        decision: str,
        *,
        now: datetime | None = None,
        edited_command: str | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> ApprovalRequest:
        """Decide a pending request.

        ``edited_command`` (W-1) is the user-edited command approved on
        the card. It is only valid with an approval decision; the edited
        command is stored as ``approved_command`` and the execution path
        runs it instead of the original. When a permission policy is
        supplied, a denylisted edit is rejected here; the gate re-checks
        it again when consuming the approval.
        """
        normalized = str(decision or "").strip().lower()
        if normalized not in DECISIONS:
            raise ValueError(f"unsupported approval decision: {normalized or '<empty>'}")
        normalized_edit: str | None = None
        if edited_command is not None:
            if normalized == "deny":
                raise ValueError("a denied command cannot be edited; the edit is discarded")
            normalized_edit = " ".join(str(edited_command or "").split())
            if not normalized_edit:
                raise ValueError("edited command must not be empty")
            if permission_policy is not None and permission_policy.denies(
                "terminal_command", normalized_edit
            ):
                raise ValueError("edited command is denied by the permission policy")
        current = now or datetime.now(timezone.utc)
        request = self.get_request(request_id)
        if request is None:
            raise ValueError(f"unknown approval request: {request_id}")
        if request.status == "expired":
            # An expired request never executes. "Always allow" from an
            # expired card only creates the rule for future requests.
            if normalized != "always_allow":
                raise ValueError("expired approval requests never execute; only always_allow is accepted")
            rule = self._ensure_rule(
                request.action_kind, request.scope, "auto_allow", conn=None
            )
            self._audit(
                request.request_id,
                "always_allow_from_expired",
                request.action_kind,
                request.scope,
                rule_id=rule.rule_id,
                note="expired request kept expired; rule created for future requests",
            )
            return request
        if request.status != "pending":
            raise ValueError(
                f"approval request {request.request_id} is already {request.status}"
            )
        if _parse_time(request.expires_at) is not None and _parse_time(request.expires_at) <= current:
            self.expire_overdue(now=current)
            raise ValueError("approval request expired before the decision")
        new_status = {
            "allow_once": "approved_once",
            "always_allow": "approved",
            "deny": "denied",
        }[normalized]
        rule_id: str | None = None
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE {_REQUESTS_TABLE} SET status = ?, decided_at = ?, "
                "decision = ?, approved_command = ? "
                "WHERE request_id = ? AND status = 'pending'",
                (
                    new_status,
                    current.isoformat(),
                    normalized,
                    normalized_edit or "",
                    request.request_id,
                ),
            )
            if conn.execute(
                f"SELECT status FROM {_REQUESTS_TABLE} WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()[0] != new_status:
                raise ValueError("approval request changed before the decision")
            if normalized == "always_allow":
                rule = self._ensure_rule(
                    request.action_kind, request.scope, "auto_allow", conn=conn
                )
                rule_id = rule.rule_id
            conn.commit()
        self._audit(
            request.request_id,
            normalized,
            request.action_kind,
            request.scope,
            rule_id=rule_id,
            note="command edited on approval" if normalized_edit else "",
        )
        updated = self.get_request(request.request_id)
        assert updated is not None
        return updated

    def reconsider_denied(
        self,
        request_id: str,
        *,
        note: str = "",
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Explicitly reconsider a denied request.

        Only the user may call this (via daemon RPC ``approval_reconsider_denied``;
        the agent's execution path never calls it). It creates a fresh pending
        request for the same triple and writes an audited ``deny_overridden``
        entry linking the denied request to the new one. The denied record
        itself is never mutated, so the deny decision stays in history.
        """
        denied = self.get_request(request_id)
        if denied is None:
            raise ValueError(f"unknown approval request: {request_id}")
        if denied.status != "denied":
            raise ValueError(
                "only denied approval requests can be reconsidered; "
                f"request {denied.request_id} is {denied.status}"
            )
        fresh = self.request_approval(
            action_kind=denied.action_kind,
            target=denied.target,
            scope=denied.scope,
            value_text=denied.value_text,
            source=denied.source,
            event_id=denied.event_id,
            now=now,
        )
        self._audit(
            denied.request_id,
            "deny_overridden",
            denied.action_kind,
            denied.scope,
            note=(
                f"denied request {denied.request_id} reconsidered; "
                f"new request {fresh.request_id}"
                + (f"; {note}" if str(note or '').strip() else "")
            ),
        )
        return fresh

    def consume(self, request_id: str) -> bool:
        """Consume one approved_once approval. Returns True only if consumed."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"UPDATE {_REQUESTS_TABLE} SET status = 'consumed' "
                "WHERE request_id = ? AND status = 'approved_once'",
                (str(request_id or "").strip(),),
            )
            conn.commit()
            return cursor.rowcount == 1

    # -- rules --------------------------------------------------------------

    def create_rule(
        self, *, action_kind: str, scope: str, effect: str
    ) -> ApprovalRule:
        kind = validate_approval_kind(action_kind)
        normalized_scope = validate_approval_scope(scope)
        normalized_effect = str(effect or "").strip().lower()
        if normalized_effect not in RULE_EFFECTS:
            raise ValueError(f"unsupported approval rule effect: {normalized_effect or '<empty>'}")
        return self._ensure_rule(kind, normalized_scope, normalized_effect, conn=None)

    def _ensure_rule(
        self,
        action_kind: str,
        scope: str,
        effect: str,
        *,
        conn: sqlite3.Connection | None,
    ) -> ApprovalRule:
        own = conn is None
        handle = conn if conn is not None else self._connect()
        try:
            existing = handle.execute(
                f"SELECT * FROM {_RULES_TABLE} "
                "WHERE action_kind = ? AND scope = ? AND effect = ?",
                (action_kind, scope, effect),
            ).fetchone()
            if existing is not None:
                rule = ApprovalRule.from_dict(dict(existing))
                if not rule.enabled:
                    handle.execute(
                        f"UPDATE {_RULES_TABLE} SET enabled = 1 WHERE rule_id = ?",
                        (rule.rule_id,),
                    )
                    if own:
                        handle.commit()
                    rule = ApprovalRule(**{**rule.to_dict(), "enabled": True})
                return rule
            rule = ApprovalRule(
                rule_id=f"rule-{uuid.uuid4().hex[:12]}",
                action_kind=action_kind,
                scope=scope,
                effect=effect,
            )
            handle.execute(
                f"INSERT INTO {_RULES_TABLE} "
                "(rule_id, action_kind, scope, effect, created_at, enabled) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    rule.rule_id,
                    rule.action_kind,
                    rule.scope,
                    rule.effect,
                    rule.created_at,
                ),
            )
            if own:
                handle.commit()
            return rule
        finally:
            if own:
                handle.close()

    def delete_rule(self, rule_id: str) -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"DELETE FROM {_RULES_TABLE} WHERE rule_id = ?",
                (str(rule_id or "").strip(),),
            )
            conn.commit()
            return cursor.rowcount == 1

    def list_rules(self) -> list[ApprovalRule]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_RULES_TABLE} ORDER BY created_at ASC"
            ).fetchall()
        return [ApprovalRule.from_dict(dict(row)) for row in rows]

    def evaluate(self, *, action_kind: str, scope: str) -> str:
        """Return ask_first / auto_allow. ask_first wins on conflict."""
        kind = validate_approval_kind(action_kind)
        normalized_scope = validate_approval_scope(scope)
        rules = [
            rule
            for rule in self.list_rules()
            if rule.enabled
            and rule.action_kind == kind
            and rule.scope == normalized_scope
        ]
        if any(rule.effect == "ask_first" for rule in rules):
            return "ask_first"
        if any(rule.effect == "auto_allow" for rule in rules):
            return "auto_allow"
        return "ask_first"

    # -- audit --------------------------------------------------------------

    def _audit(
        self,
        request_id: str | None,
        decision: str,
        action_kind: str,
        scope: str,
        *,
        rule_id: str | None = None,
        note: str = "",
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"INSERT INTO {_AUDIT_TABLE} "
                "(audit_id, request_id, decision, action_kind, scope, rule_id, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"audit-{uuid.uuid4().hex[:12]}",
                    request_id,
                    decision,
                    action_kind,
                    scope,
                    rule_id,
                    " ".join(str(note or "").split())[:500],
                    utc_now(),
                ),
            )
            conn.commit()

    def list_audit(self, *, limit: int = 50) -> list[ApprovalAuditEntry]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM {_AUDIT_TABLE} ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            ApprovalAuditEntry(
                audit_id=str(row["audit_id"]),
                request_id=str(row["request_id"] or "") or None,
                decision=str(row["decision"]),
                action_kind=str(row["action_kind"]),
                scope=str(row["scope"]),
                rule_id=str(row["rule_id"] or "") or None,
                note=str(row["note"] or ""),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]


class ApprovalGate:
    """Fail-closed gate consulted before a sensitive action executes."""

    def __init__(
        self,
        store: ApprovalCardStore,
        *,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = permission_policy

    def check(
        self,
        *,
        action_kind: str,
        target: str,
        scope: str,
        value_text: str = "",
        source: str = "resident",
        event_id: str | None = None,
        command: str | None = None,
        session_id: str | None = None,
        action_type: str | None = None,
    ) -> ApprovalGateOutcome:
        kind = validate_approval_kind(action_kind)
        normalized_scope = validate_approval_scope(scope)
        normalized_target = " ".join(str(target or "").split())
        if not normalized_target:
            raise ValueError("approval target must not be empty")
        self._store.expire_overdue()
        latest = self._store.latest_request_for(
            action_kind=kind, scope=normalized_scope, target=normalized_target
        )
        if latest is not None and latest.status == "denied":
            # Deny is sticky and outranks auto_allow rules for its triple:
            # a rule is for future requests, never a silent override of a
            # deny. Only an explicit reconsider_denied re-asks the triple.
            return ApprovalGateOutcome(
                False,
                request_id=latest.request_id,
                reason=(
                    "approval denied; action never executes — "
                    "reconsider explicitly to re-ask"
                ),
            )
        # Structured permission policy (W-1): consulted after the sticky
        # deny and before the rule evaluation. Denylist blocks outright;
        # a policy ALLOW (session grant / always_allow) skips the card;
        # ASK / AGENT_DECIDES falls through to the existing rules.
        if self._policy is not None:
            resolved_type = (
                action_type
                or _POLICY_ACTION_TYPE_BY_KIND.get(kind)
                or ("terminal_command" if command else None)
            )
            if resolved_type is not None:
                verdict = self._policy.evaluate(
                    resolved_type, command or "", session_id=session_id
                )
                if verdict is PermissionVerdict.DENY:
                    return ApprovalGateOutcome(
                        False,
                        reason="permission policy denied the action (denylist)",
                    )
                if verdict is PermissionVerdict.ALLOW:
                    return ApprovalGateOutcome(
                        True,
                        reason="permission policy allowed the action",
                    )
        if self._store.evaluate(action_kind=kind, scope=normalized_scope) == "auto_allow":
            return ApprovalGateOutcome(True, reason="auto_allow rule matched")
        if latest is not None and latest.status == "approved_once":
            approved_command = latest.approved_command.strip() or None
            if (
                approved_command is not None
                and self._policy is not None
                and self._policy.denies("terminal_command", approved_command)
            ):
                # Defense in depth: an edit that slipped past decide()
                # without a policy check never executes. The approval is
                # spent and the block is audited.
                self._store.consume(latest.request_id)
                self._store._audit(
                    latest.request_id,
                    "edited_command_denied",
                    kind,
                    normalized_scope,
                    note=(
                        "approved edited command denied by permission policy; "
                        "approval spent, action never executes"
                    ),
                )
                return ApprovalGateOutcome(
                    False,
                    request_id=latest.request_id,
                    reason="edited command denied by permission policy",
                )
            if self._store.consume(latest.request_id):
                return ApprovalGateOutcome(
                    True,
                    request_id=latest.request_id,
                    reason="approved_once consumed",
                    approved_command=approved_command,
                )
        if latest is not None and latest.status == "pending":
            return ApprovalGateOutcome(
                False,
                request_id=latest.request_id,
                reason="approval pending",
            )
        if latest is not None and latest.status == "expired":
            return ApprovalGateOutcome(
                False,
                request_id=latest.request_id,
                reason="approval expired; action never executes",
            )
        request = self._store.request_approval(
            action_kind=kind,
            target=normalized_target,
            scope=normalized_scope,
            value_text=value_text,
            source=source,
            event_id=event_id,
        )
        return ApprovalGateOutcome(
            False,
            request_id=request.request_id,
            reason="approval requested; action never executes without a decision",
        )


def approval_kind_for_tag(tags: tuple[str, ...] | list[str]) -> str | None:
    """Return the approval kind from an ``approval:<kind>`` descriptor tag."""
    for tag in tags or ():
        text = str(tag or "").strip().lower()
        if not text.startswith("approval:"):
            continue
        kind = text.split("approval:", 1)[1].strip()
        if kind in APPROVAL_KINDS:
            return kind
    return None

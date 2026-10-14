from __future__ import annotations

"""CP-4: failure classification + hard-stop rules for the orchestrator.

Sources (mechanism only, no copied code): Muse failure discipline
(classify -> reroute -> fallback; rejection / rate-limit hard-stop) and
AutoGen termination (composable stop conditions + a hard cap).

Four categories -- every classified failure lands in exactly one:

- ``retryable``: transient, safe to retry the same path with a bound
  (network / service blips). Attempts are consecutive-failure counted;
  any successful apply resets the count.
- ``reroute``: this path is unusable, try the next path in the reroute
  chain (overloaded provider, bad route, context overflow, malformed
  request). The chain is configuration (:func:`FailurePolicy.next_path`);
  callers that execute alternate paths consume it. The team runner
  records the tried path and escalates when attempts exhaust.
- ``hard_stop``: stop now, no retry, no reroute. Rate limit (429) stops
  the whole round; approval / authority / content-policy rejections must
  never be bypassed by retrying or switching paths.
- ``needs_user``: only the user can unblock (permanent auth failure,
  billing / quota). Stop, report the tried paths + blocking reason +
  what the user must do, and do not spin.

Hard rules enforced here and in ``TeamRunner``:

- Rate limit (429 / rate-limited) hard-stops the current round: no sleep
  retry, no reroute, no dispatching another task this round. Partial
  progress is reported.
- An approval rejection is recorded by action key; any later attempt to
  execute the same action raises :class:`ApprovalBypassBlocked`, which
  classifies as a round-level hard stop. Rejections are durable: the
  runner persists them in team shared memory because the owner rebuilds
  the runner every pulse.
- Permanent auth failure is never retried; the report carries a
  reconnect hint.
- The user is asked only after every path is blocked (attempts
  exhausted) or when only the user can unblock (auth / billing).

Provider evidence comes from :mod:`cognitive_failure` -- this module maps
its ``failure_class`` to a category instead of re-deriving HTTP semantics.
An exception with no recognizable failure evidence classifies as ``None``;
callers must re-raise it rather than swallow a possible programmer bug.
"""

from dataclasses import dataclass, field
from typing import Any

from .cognitive_failure import classify_cognitive_failure


#: Failure categories. See the module docstring.
CATEGORIES = ("retryable", "reroute", "hard_stop", "needs_user")

#: Scopes: "item" failures escalate one WorkItem and the round continues;
#: "round" failures stop the whole orchestrator round immediately.
SCOPES = ("item", "round")

#: Default bound on consecutive failures for one (item, failure kind)
#: before the item escalates as needs-user.
DEFAULT_MAX_ATTEMPTS_PER_ITEM = 2

#: Ordered alternative paths per task kind. The last entry is always
#: ``"ask_user"``: when it is the only path left, the caller escalates
#: instead of executing anything else.
DEFAULT_REROUTE_CHAINS: dict[str, tuple[str, ...]] = {
    "cognition": ("primary_route", "alternate_route", "reduced_scope", "ask_user"),
    "provider_call": ("primary_route", "alternate_route", "ask_user"),
    "tool_call": ("same_tool_retry", "alternate_tool", "ask_user"),
    "team_dispatch": ("same_specialist", "alternate_specialist", "ask_user"),
    "default": ("alternate_path", "reduced_scope", "ask_user"),
}


class ApprovalRejectedError(PermissionError):
    """An approval layer rejected an action. Never retry or reroute it."""


class ApprovalBypassBlocked(ApprovalRejectedError):
    """A previously rejected action was attempted again -- bypass blocked."""


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """One classified failure: what happened and what the orchestrator does."""

    category: str  # one of CATEGORIES
    kind: str  # stable failure kind, e.g. "rate_limit"
    scope: str  # "item" | "round"
    reason: str  # why, in one line
    user_action: str = ""  # what the user can do, "" when nothing is needed
    reconnect_hint: str = ""  # reconnect path for auth / billing failures


# cognitive failure_class -> (category, scope, reason, user_action, reconnect_hint)
_COGNITIVE_MAP: dict[str, tuple[str, str, str, str, str]] = {
    "rate_limit": (
        "hard_stop",
        "round",
        "限流（429/rate-limited）：本轮立即硬停，不睡眠重试、不换路、不另派任务",
        "无需操作；本轮已汇报部分进展，下一轮再试",
        "",
    ),
    "provider_overloaded": (
        "reroute",
        "item",
        "服务过载：换备选路径",
        "",
        "",
    ),
    "network_or_service": (
        "retryable",
        "item",
        "网络/服务瞬断：有界重试同一路径",
        "",
        "",
    ),
    "request_context_or_payload": (
        "reroute",
        "item",
        "上下文/载荷超限：换路（缩减上下文/拆分任务）",
        "",
        "",
    ),
    "request_or_input": (
        "reroute",
        "item",
        "请求格式无效：换路（修正请求后重试）",
        "",
        "",
    ),
    "request_or_content_policy": (
        "hard_stop",
        "item",
        "内容/政策拒绝：不得重试、不得换路绕过",
        "改写请求内容后重新下达",
        "",
    ),
    "billing_or_quota": (
        "needs_user",
        "round",
        "额度/账单不足：不重试",
        "充值或提高额度后继续",
        "检查账单/额度后继续",
    ),
    "authentication_or_authorization": (
        "needs_user",
        "round",
        "授权永久失效：不重试",
        "重新连接并更新凭证",
        "重新授权/重连",
    ),
    "configuration_or_route": (
        "reroute",
        "item",
        "模型/路由配置无效：换备选路由",
        "",
        "",
    ),
}


@dataclass(slots=True)
class FailurePolicy:
    """Orchestrator failure policy: classify, count, guard, report."""

    max_attempts_per_item: int = DEFAULT_MAX_ATTEMPTS_PER_ITEM
    reroute_chains: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_REROUTE_CHAINS)
    )
    _rejected: dict[str, str] = field(default_factory=dict, repr=False)
    _attempts: dict[tuple[str, str], int] = field(default_factory=dict, repr=False)

    # -- classification -------------------------------------------------

    def classify(self, error: BaseException) -> FailureClassification | None:
        """Classify ``error`` or return ``None`` when it carries no evidence.

        ``None`` is deliberate: an unrecognized exception is not a
        retryable failure, it is a possible programmer bug. Callers must
        re-raise it instead of swallowing it.
        """
        if isinstance(error, ApprovalRejectedError):
            return FailureClassification(
                category="hard_stop",
                kind="approval_rejected",
                scope="round",
                reason="审批被拒：不得换路绕过",
                user_action="修改方案后重新提交审批",
            )
        disposition = classify_cognitive_failure(error)
        if disposition is not None:
            mapped = _COGNITIVE_MAP.get(disposition.failure_class)
            if mapped is not None:
                category, scope, reason, user_action, hint = mapped
                return FailureClassification(
                    category=category,
                    kind=disposition.failure_class,
                    scope=scope,
                    reason=reason,
                    user_action=user_action,
                    reconnect_hint=hint,
                )
            # Forward-compat: a future cognitive class still gets a
            # bounded retryable disposition instead of crashing the round.
            return FailureClassification(
                category="retryable",
                kind=disposition.failure_class,
                scope="item",
                reason=f"未映射的认知失败（{disposition.failure_class}）：按有界可重试处理",
            )
        if isinstance(error, PermissionError):
            return FailureClassification(
                category="hard_stop",
                kind="authority_denied",
                scope="item",
                reason="权限/授权拒绝：不得换路绕过",
                user_action="确认该动作是否应被授权后再下达",
            )
        if isinstance(error, (TimeoutError, ConnectionError)):
            return FailureClassification(
                category="retryable",
                kind="network_or_service",
                scope="item",
                reason="网络/服务瞬断：有界重试同一路径",
            )
        return None

    # -- approval-rejection guard ----------------------------------------

    def record_approval_rejection(self, action_key: str, reason: str = "") -> None:
        """Record that the approval layer rejected ``action_key``."""
        key = str(action_key or "").strip()
        if not key:
            raise ValueError("action_key must not be empty")
        self._rejected[key] = str(reason or "").strip() or "审批被拒"

    def rejected_reason(self, action_key: str) -> str | None:
        """The recorded rejection reason, or ``None`` when not rejected."""
        return self._rejected.get(str(action_key or "").strip())

    def require_not_rejected(self, action_key: str) -> None:
        """Raise :class:`ApprovalBypassBlocked` if the action was rejected."""
        reason = self.rejected_reason(action_key)
        if reason is not None:
            raise ApprovalBypassBlocked(
                f"action {str(action_key).strip()!r} was rejected ({reason}); "
                "refusing to execute it through another path"
            )

    # -- bounded attempts -------------------------------------------------

    def record_attempt(self, work_item_id: str, kind: str) -> int:
        """Count one consecutive failure for (item, kind); return the count."""
        key = (str(work_item_id or "").strip(), str(kind or "").strip())
        count = self._attempts.get(key, 0) + 1
        self._attempts[key] = count
        return count

    def attempts_for(self, work_item_id: str, kind: str) -> int:
        return self._attempts.get(
            (str(work_item_id or "").strip(), str(kind or "").strip()), 0
        )

    def attempts_exhausted(self, work_item_id: str, kind: str) -> bool:
        return self.attempts_for(work_item_id, kind) >= max(
            1, int(self.max_attempts_per_item)
        )

    def note_success(self, work_item_id: str) -> bool:
        """Reset consecutive-failure counts for an item. True when cleared."""
        wid = str(work_item_id or "").strip()
        stale = [key for key in self._attempts if key[0] == wid]
        for key in stale:
            del self._attempts[key]
        return bool(stale)

    # -- reroute chain ----------------------------------------------------

    def next_path(self, task_kind: str, tried_paths: Any) -> str | None:
        """Next untried path for ``task_kind``, or ``None`` when exhausted.

        ``"ask_user"`` as the returned value means the caller must escalate
        to the user instead of executing anything else.
        """
        chain = self.reroute_chains.get(
            str(task_kind or "").strip(), self.reroute_chains.get("default", ())
        )
        tried = {str(path) for path in (tried_paths or ())}
        for path in chain:
            if path not in tried:
                return path
        return None

    # -- blocked report ----------------------------------------------------

    def build_blocked_report(
        self,
        *,
        tried_paths: Any = (),
        blocking_reason: str = "",
        user_action: str = "",
        partial_progress: Any = (),
        failure_kind: str = "",
        reconnect_hint: str = "",
    ) -> dict[str, Any]:
        """Final report shape: tried paths + blocking reason + user action."""
        return {
            "tried_paths": [str(path) for path in (tried_paths or ())],
            "blocking_reason": str(blocking_reason or "").strip(),
            "needs_user_to": str(user_action or "").strip(),
            "partial_progress": [str(item) for item in (partial_progress or ())],
            "failure_kind": str(failure_kind or "").strip(),
            "reconnect_hint": str(reconnect_hint or "").strip(),
        }

    # -- durable state (runner persists this in team shared memory) --------

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "rejected": dict(self._rejected),
            "attempts": {
                f"{wid}\x00{kind}": count
                for (wid, kind), count in self._attempts.items()
            },
        }

    def restore_state(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        rejected = raw.get("rejected")
        if isinstance(rejected, dict):
            for key, reason in rejected.items():
                if isinstance(key, str) and key.strip() and isinstance(reason, str):
                    self._rejected[key] = reason
        attempts = raw.get("attempts")
        if isinstance(attempts, dict):
            for key, count in attempts.items():
                if not isinstance(key, str) or "\x00" not in key:
                    continue
                wid, _, kind = key.partition("\x00")
                if wid.strip() and kind.strip() and isinstance(count, int):
                    self._attempts[(wid, kind)] = count


__all__ = [
    "ApprovalBypassBlocked",
    "ApprovalRejectedError",
    "CATEGORIES",
    "DEFAULT_MAX_ATTEMPTS_PER_ITEM",
    "DEFAULT_REROUTE_CHAINS",
    "FailureClassification",
    "FailurePolicy",
    "SCOPES",
]

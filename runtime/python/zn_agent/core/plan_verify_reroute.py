from __future__ import annotations

"""M-3: generic plan -> verify -> reroute loop for single (non-team) Work.

A Broad Work step used to be "preset flow -> target not found -> fail": the
only reroute rule in the codebase was the coding layer's bounded
``path_replanned`` (a missing ``.py`` path may be replaced by one unique
same-basename file). This module generalizes that into one loop every
single-Work step kind shares:

```text
attempt (one bounded step proposal)
-> independent verification (the existing Body postcondition)
-> on failure: diagnose the missing resource (ZN.md §1.10), switch
   strategy / resource bundle, record the attempt in the strategy ledger
-> bounded retries: an identical (strategy, failure) twice blocks at once;
   N consecutive failures without verified progress block as well
-> exhausted: explicit block with a tried-strategy report, never a
   fabricated result
```

Deliberate boundaries:

- This module owns the *step* loop only. It adds no completion judge:
  step verification is the existing Body postcondition, and Root
  completion is still decided solely by the M-5 CP-3 adjudicator
  (``completion_verdict.adjudicate_completion`` via
  ``accept_root_with_current_evidence``). A failed step never completes
  anything, and a passed step never accepts the Root.
- Team paths are untouched: the resident wiring records only failures
  that belong to a rolling single-Work step (see
  ``BroadGoalWorkResidentRuntime``), and the M-5 completion-report round
  keeps its own verdict retry budget.
- Diagnosis is deterministic keyword matching over resident-owned
  failure evidence, never a model call and never a guess: when no
  marker fits, the missing resource is ``understanding`` (re-derive the
  plan from fresh evidence) rather than an invented fact.
"""

import re
from dataclasses import dataclass, field
from typing import Any

#: Missing-resource kinds from ZN.md §1.10. Every verification failure is
#: diagnosed as exactly one of these before the next strategy is chosen.
MISSING_RESOURCES: tuple[str, ...] = (
    "understanding",
    "fact",
    "capability",
    "permission",
    "proof",
)

#: Consecutive failed attempts (no verified child in between) before the
#: loop blocks explicitly. Four attempts = the first try plus three
#: reroutes. An identical (strategy, failure) repeat blocks at once,
#: before this budget, mirroring the M-5 verdict rule (identical
#: rejection escalates at once; distinct rejections run out the budget).
MAX_CONSECUTIVE_FAILURES = 4

#: How many ledger entries the cognition prompt block carries. The full
#: ledger stays in durable state for audit; only the recent entries
#: guide the next proposal.
_PROMPT_LEDGER_ENTRIES = 3

#: Durable state key under ``WorkingState.data``. The ledger is plain
#: JSON-able data so it survives crash recovery like the rolling step.
STRATEGY_LEDGER_KEY = "plan_verify_reroute_ledger"

# -- deterministic diagnosis (ZN.md §1.10) --------------------------------
# Order matters: proof markers are checked before fact markers, because
# "missing expected output fragment" is a proof failure (the evidence did
# not prove the outcome), not a missing file. Bare "missing" is
# deliberately NOT a fact marker for the same reason.

_PERMISSION_MARKERS: tuple[str, ...] = (
    "permission",
    "denied",
    "unauthorized",
    "forbidden",
    "approval",
    "not allowed",
    "requires approval",
    "not permitted",
    "eacces",
    "eperm",
    "权限",
    "未授权",
    "审批被拒",
    "需要审批",
)

_PROOF_MARKERS: tuple[str, ...] = (
    "mismatch",
    "did not match",
    "did not satisfy",
    "expected",
    "observed",
    "verification failed",
    "not equal",
    "differs",
    "验证",
    "不匹配",
    "期望",
    "实际",
    "不一致",
    "未通过",
)

_FACT_MARKERS: tuple[str, ...] = (
    "not found",
    "no such file",
    "no such path",
    "does not exist",
    "unknown file",
    "unknown path",
    "unknown url",
    "unknown host",
    "not a file",
    "is a directory",
    "404",
    "不存在",
    "找不到",
    "未找到",
    "没有这个",
    "查无",
    "不是文件",
)

_CAPABILITY_MARKERS: tuple[str, ...] = (
    "unsupported",
    "not supported",
    "no tool",
    "no provider",
    "provider unavailable",
    "unavailable",
    "not available",
    "cannot execute",
    "cannot open",
    "no such tool",
    "不支持",
    "没有工具",
    "无法执行",
    "不可用",
    "没有可用的",
)

_UNDERSTANDING_MARKERS: tuple[str, ...] = (
    "invalid",
    "malformed",
    "ambiguous",
    "unclear",
    "parse",
    "syntax",
    "typeerror",
    "nameerror",
    "keyerror",
    "attributeerror",
    "valueerror",
    "无效",
    "格式错误",
    "歧义",
    "不清楚",
    "无法解析",
    "语法",
)

#: What to try next for each missing resource (ZN.md §1.10). This is the
#: "换资源包" half of a reroute: the next attempt must use a different
#: resource bundle, not the same failed strategy harder.
RESOURCE_BUNDLES: dict[str, str] = {
    "understanding": "缺理解/规划：换一种规划与推导方式，从新鲜证据重新推导下一步，不要重复同一假设。",
    "fact": "缺事实：先感知/核查真实世界（读文件、列目录、重新观测），不要猜路径或内容。",
    "capability": "缺能力：换工具/资源包，换一种能真正影响世界的动作种类。",
    "permission": "缺权限：申请最小必要权限或交接，不要重试被拒动作、不要绕过拒绝。",
    "proof": "缺证明：重新观测/查询/测试/比对，用新鲜证据确认结果，不要凭信心宣称完成。",
}

_DIGIT_RE = re.compile(r"\d+")
_SPACE_RE = re.compile(r"\s+")


def diagnose_missing_resource(failure: str) -> str:
    """Diagnose one verification failure as a ZN.md §1.10 missing resource.

    Deterministic keyword matching over the resident-owned failure
    evidence. Unknown failures fall back to ``understanding``: re-derive
    the plan from fresh evidence, never invent a fact.
    """
    text = str(failure or "").casefold()
    for marker in _PERMISSION_MARKERS:
        if marker in text:
            return "permission"
    for marker in _PROOF_MARKERS:
        if marker in text:
            return "proof"
    for marker in _FACT_MARKERS:
        if marker in text:
            return "fact"
    for marker in _CAPABILITY_MARKERS:
        if marker in text:
            return "capability"
    for marker in _UNDERSTANDING_MARKERS:
        if marker in text:
            return "understanding"
    return "understanding"


def failure_signature(strategy: str, failure: str) -> str:
    """Normalized identity of one (strategy, failure) pair.

    Digits are masked so the same failure with different line numbers,
    ports, or exit codes still counts as the same failure; the strategy
    stays in the signature so two different steps failing with similar
    text do not falsely count as a repeat.
    """
    normalized = _SPACE_RE.sub(
        " ", str(failure or "").strip().casefold()
    )
    normalized = _DIGIT_RE.sub("#", normalized)
    return f"{str(strategy or '').strip().casefold()} :: {normalized[:500]}"


@dataclass
class StrategyAttempt:
    """One ledger entry: what was tried, what the evidence said, why switch."""

    strategy: str
    failure: str
    missing_resource: str
    switch_reason: str
    attempt: int
    # Durable identity of the failed attempt, for de-duplicating a
    # re-entrant recording of the same attempt. Not rendered in prompts.
    child_work_item_id: str = ""


@dataclass
class StrategyLedger:
    """Append-only strategy ledger + bounded reroute budget for one Work.

    ``entries`` is the audit trail (what was tried, evidence, why switch).
    ``consecutive_failures`` counts failed attempts since the last
    verified child; a verified child resets it, so failures spread
    across a long Work with real progress never exhaust the budget.
    ``last_signature`` is the previous attempt's failure signature:
    the same signature twice in a row blocks at once.
    """

    entries: list[StrategyAttempt] = field(default_factory=list)
    consecutive_failures: int = 0
    last_signature: str | None = None
    blocked_reason: str | None = None
    # Monotonic attempt counter: entries are capped at 12 for prompt
    # size, so ``len(entries) + 1`` would repeat attempt numbers.
    total_attempts: int = 0
    # Scope: the ledger belongs to one plan of one Root. Steering /
    # replan starts a fresh ledger instead of carrying stale
    # "do not repeat" guidance into the new plan.
    plan_version: int | None = None
    root_work_item_id: str = ""

    # -- persistence ------------------------------------------------------

    @classmethod
    def from_state(
        cls,
        raw: Any,
        *,
        plan_version: int | None = None,
        root_work_item_id: str | None = None,
    ) -> "StrategyLedger":
        if not isinstance(raw, dict):
            return cls(
                plan_version=plan_version,
                root_work_item_id=str(root_work_item_id or ""),
            )
        stored_version = raw.get("plan_version")
        stored_root = str(raw.get("root_work_item_id") or "")
        if (
            plan_version is not None
            and isinstance(stored_version, int)
            and stored_version != plan_version
        ) or (
            root_work_item_id is not None
            and stored_root
            and stored_root != str(root_work_item_id)
        ):
            # The plan moved on: the old ledger's failures belong to a
            # superseded plan and must not constrain the new one.
            return cls(
                plan_version=plan_version,
                root_work_item_id=str(root_work_item_id or ""),
            )
        entries: list[StrategyAttempt] = []
        raw_entries = raw.get("entries")
        if isinstance(raw_entries, list):
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                strategy = str(item.get("strategy") or "").strip()
                if not strategy:
                    continue
                missing = str(item.get("missing_resource") or "").strip()
                entries.append(
                    StrategyAttempt(
                        strategy=strategy,
                        failure=str(item.get("failure") or "")[:1000],
                        missing_resource=(
                            missing if missing in MISSING_RESOURCES else "understanding"
                        ),
                        switch_reason=str(item.get("switch_reason") or "")[:1000],
                        attempt=int(item.get("attempt") or 0) or len(entries) + 1,
                        child_work_item_id=str(item.get("child_work_item_id") or ""),
                    )
                )
        blocked = raw.get("blocked_reason")
        return cls(
            entries=entries[-12:],
            consecutive_failures=max(0, int(raw.get("consecutive_failures") or 0)),
            total_attempts=max(
                0,
                int(raw.get("total_attempts") or 0),
                len(entries),
            ),
            last_signature=(
                str(raw.get("last_signature") or "").strip() or None
            ),
            blocked_reason=(
                str(blocked or "").strip() or None
                if isinstance(blocked, str)
                else None
            ),
            plan_version=(
                stored_version
                if isinstance(stored_version, int)
                else plan_version
            ),
            root_work_item_id=stored_root or str(root_work_item_id or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "root_work_item_id": self.root_work_item_id,
            "entries": [
                {
                    "strategy": entry.strategy,
                    "failure": entry.failure,
                    "missing_resource": entry.missing_resource,
                    "switch_reason": entry.switch_reason,
                    "attempt": entry.attempt,
                    "child_work_item_id": entry.child_work_item_id,
                }
                for entry in self.entries[-12:]
            ],
            "consecutive_failures": self.consecutive_failures,
            "last_signature": self.last_signature,
            "blocked_reason": self.blocked_reason,
            "total_attempts": self.total_attempts,
        }

    # -- loop -------------------------------------------------------------

    def record_failure(
        self,
        strategy: str,
        failure: str,
        *,
        child_work_item_id: str = "",
    ) -> tuple[str, str | None]:
        """Record one failed attempt; decide switch / blocked / duplicate.

        Returns ``(decision, blocked_reason)``. ``duplicate`` means this
        exact child already recorded this failure (a re-entrant call for
        the same attempt): nothing new is recorded and the loop continues.
        ``blocked`` carries the explicit blocking reason; the caller must
        terminal-fail with it instead of asking cognition again.
        """
        clean_strategy = str(strategy or "").strip() or "unknown step"
        clean_failure = str(failure or "").strip() or "verification failed"
        signature = failure_signature(clean_strategy, clean_failure)
        last = self.entries[-1] if self.entries else None
        if (
            last is not None
            and child_work_item_id
            and last.child_work_item_id == str(child_work_item_id)
            and failure_signature(last.strategy, last.failure) == signature
        ):
            return "duplicate", None
        if self.blocked_reason is not None:
            return "blocked", self.blocked_reason
        if self.last_signature is not None and signature == self.last_signature:
            self.blocked_reason = (
                "同一策略的同一验证失败连续出现 2 次，已显式阻塞，不再重试："
                f"策略 {clean_strategy}；失败证据 {clean_failure[:500]}；"
                "请按策略账本与阻塞原因处理，不要重复同一策略。"
            )
            return "blocked", self.blocked_reason
        self.consecutive_failures += 1
        self.total_attempts += 1
        missing = diagnose_missing_resource(clean_failure)
        entry = StrategyAttempt(
            strategy=clean_strategy,
            failure=clean_failure[:1000],
            missing_resource=missing,
            switch_reason=RESOURCE_BUNDLES[missing],
            attempt=self.total_attempts,
            child_work_item_id=str(child_work_item_id or ""),
        )
        self.entries.append(entry)
        self.entries = self.entries[-12:]
        self.last_signature = signature
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.blocked_reason = (
                f"连续 {self.consecutive_failures} 次尝试验证失败、中间无已验证进展，"
                "通用规划-验证-换路循环已耗尽，已显式阻塞，不再重试；"
                f"最后诊断缺 {missing}；"
                f"已尝试策略：{'; '.join(e.strategy for e in self.entries[-4:])}。"
            )
            return "blocked", self.blocked_reason
        return "switch", None

    def record_success(self) -> None:
        """One verified child: the loop made progress, reset the streak."""
        self.consecutive_failures = 0
        self.last_signature = None

    # -- presentation ------------------------------------------------------

    def prompt_block(self) -> str:
        """Cognition guidance from the ledger, or ``""`` when no attempts."""
        if not self.entries:
            return ""
        lines = [
            "[strategy-ledger 策略账本] ZN 已尝试的策略与验证结果（不要重复已失败策略）："
        ]
        for entry in self.entries[-_PROMPT_LEDGER_ENTRIES:]:
            lines.append(
                f"- 尝试 {entry.attempt}：{entry.strategy} → 验证失败"
                f"（缺{entry.missing_resource}）：{entry.failure[:300]}；"
                f"换路：{entry.switch_reason}"
            )
        last = self.entries[-1]
        lines.append(
            f"上次失败诊断：缺 {last.missing_resource}。"
            f"下一步必须换策略或换资源包：{RESOURCE_BUNDLES[last.missing_resource]}"
            "不要编造事实、路径或结果；若无可试的未尝试策略，如实说明阻塞原因。"
        )
        return "\n".join(lines)

    def blocked_report(self) -> dict[str, Any]:
        """Tried strategies + blocking reason, for the terminal failure."""
        return {
            "tried_strategies": [entry.strategy for entry in self.entries],
            "blocking_reason": self.blocked_reason or "",
            "missing_resource": (
                self.entries[-1].missing_resource if self.entries else ""
            ),
            "consecutive_failures": self.consecutive_failures,
            "attempts": len(self.entries),
        }


__all__ = [
    "MAX_CONSECUTIVE_FAILURES",
    "MISSING_RESOURCES",
    "RESOURCE_BUNDLES",
    "STRATEGY_LEDGER_KEY",
    "StrategyAttempt",
    "StrategyLedger",
    "diagnose_missing_resource",
    "failure_signature",
]

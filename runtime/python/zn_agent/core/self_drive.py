from __future__ import annotations

"""M-14: native goal-driven self-drive loop across pulses.

A durable goal given to ZN advances on its own -- take the next goal,
decompose one step, execute it through the ordinary Work/event pipeline,
verify, and continue on the next pulse -- until the goal verifies complete
or blocks explicitly. No external cron triggers it: the driver is consulted
once per resident pulse, exactly like the recurring-will and routine
behaviors (``install_recurring_will_behavior`` / ``install_routine_behavior``).

Reuse, not reinvention:

- Goal state machine: the existing ``NativeWill`` (``will.py``)
  intention lifecycle (active / engaged / paused / completed / blocked).
  The driver never invents a second state machine; it only sets
  ``next_task`` and lets the existing ``_advance_intention`` ->
  ``enqueue`` -> ``run_once`` -> ``observe_event_outcome`` loop execute it.
- Failure reroute: the M-3 ``StrategyLedger`` (``plan_verify_reroute.py``)
  per goal generation: switch strategy on failure, bounded retries,
  explicit block on exhaustion.
- Completion gate: the single CP-3 adjudicator
  (``completion_verdict.adjudicate_completion``); the driver re-reads
  evidence from its durable per-goal step history at decision time and
  owns the verdict retry budget, mirroring the M-5 single-Work gate.
- Team assembly: self-drive steps run as ordinary events through the
  product resident pipeline, where ``SelfTeamDriver`` (M-12) already
  decides parallel assembly. The driver does not duplicate that judgment.
- Goal control authority: the ``goal_control`` approval kind
  (``approval_cards.APPROVAL_KINDS``); scopes are concrete
  ``self-drive-goal:<intention_id>:<start|pause|resume|redirect>``.

Retired-direction guard rails (ZN.md section 9, AGENTS.md "已废弃：专用
自我维护系统"):

- This is an ordinary goal-execution loop under user authorization, not a
  dedicated self-upkeep lane: no extra runtime, no dedicated cognition /
  repair chain, no investigation/review/publication state machine, no
  upstream BUG report / transport / intake / reconcile control plane, no
  dedicated UI, IPC, or RPC surface (no new RPC methods are added), and no
  extra authority. A goal whose target is the ZN repository is
  executed through the same generic Work / File / Terminal / Git / Repo
  Test capabilities as any other project; authority always flows through
  approval cards and Body verification.
- Goal intake is explicit: user-submitted goals start immediately (user
  authority); resident-proposed goals require a user-approved
  ``goal_control`` start card, fail closed without an approval channel,
  and never re-ask after a deny (deny is sticky).
"""

import json
import re
import sqlite3
from collections import deque
from contextlib import closing
from typing import Any, Callable

from .completion_verdict import (
    MAX_VERDICT_ATTEMPTS,
    adjudicate_completion,
    record_verdict_attempt,
)
from .models import utc_now
from .plan_verify_reroute import StrategyLedger

#: Intention source marking goals owned by the self-drive loop.
SELF_DRIVE_SOURCE = "self_drive"

#: Approval kind for goal control actions (registered in APPROVAL_KINDS).
APPROVAL_KIND_GOAL_CONTROL = "goal_control"

#: Goal origins: who submitted the goal.
ORIGIN_USER = "user"
ORIGIN_RESIDENT = "resident"

#: Control actions that may need a user approval card.
_CONTROL_ACTIONS = ("start", "pause", "resume", "redirect")

#: Consecutive unusable cognition answers before the goal blocks explicitly.
_MAX_INVALID_COGNITION = 3

#: Bounded progress scan per goal per pulse.
_PROGRESS_SCAN_LIMIT = 64

#: Bounded durable step history per goal.
_STEP_HISTORY_LIMIT = 64

_GOALS_TABLE = "self_drive_goals"

# Progress entries written by NativeWill.engage / observe_event_outcome.
_EVENT_OUTCOME_RE = re.compile(r"^event (\S+) (succeeded|failed|cancelled):")
_ENGAGED_RE = re.compile(r"^engaged step via event (\S+):")


class _NoCognitionAvailable(RuntimeError):
    """Raised when a decision needs cognition but none is wired."""


def _control_scope(intention_id: str, action: str) -> str:
    return f"self-drive-goal:{intention_id}:{action}"


def _new_goal_data(
    *, origin: str, objective: str, acceptance: list[str]
) -> dict[str, Any]:
    return {
        "origin": origin,
        "objective": objective,
        "acceptance": list(acceptance),
        "generation": 1,
        "strategy_ledger": None,
        "verdict_tracking": None,
        "invalid_cognition_streak": 0,
        "last_step_event_id": None,
        "last_strategy": None,
        "step_history": [],
        "pending_control": None,
        "control_denied": {},
        "pending_redirect": None,
        "redirects": [],
        "blocked_reason": None,
    }


class SelfDriveDriver:
    """Advance self-drive goals one decision per pulse.

    The driver is deliberately thin: durable goal configuration lives in
    the ``self_drive_goals`` table, the goal lifecycle lives in
    ``NativeWill``, and execution lives in the ordinary event pipeline.
    """

    def __init__(
        self,
        *,
        will,
        store,
        kernel=None,
        approval_store=None,
        cognitive_invoke: Callable[[str, str], str] | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self._will = will
        self._store = store
        self._kernel = kernel
        self._approval_store = approval_store
        self._cognitive_invoke = cognitive_invoke
        self._notify = notify
        self._recent_errors: deque[str] = deque(maxlen=20)
        self._recent_notes: deque[str] = deque(maxlen=20)
        self._init_schema()

    def rewire(
        self,
        *,
        kernel=None,
        approval_store=None,
        cognitive_invoke: Callable[[str, str], str] | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        """Attach explicitly passed knobs to an installed driver.

        Used when the behavior is (re-)installed with wiring the original
        install did not have -- e.g. the product resident installs the
        driver at construction, and a later explicit install attaches the
        cognition/notify hooks. Only non-None knobs are applied.
        """
        if kernel is not None:
            self._kernel = kernel
        if approval_store is not None:
            self._approval_store = approval_store
        if cognitive_invoke is not None:
            self._cognitive_invoke = cognitive_invoke
        if notify is not None:
            self._notify = notify

    # -- durable goal table -------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_GOALS_TABLE} ("
                "intention_id TEXT PRIMARY KEY, "
                "data TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            conn.commit()

    def _load_goal(self, intention_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT data FROM {_GOALS_TABLE} WHERE intention_id=?",
                (str(intention_id),),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        return data if isinstance(data, dict) else None

    def _save_goal(self, intention_id: str, data: dict[str, Any]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                f"INSERT INTO {_GOALS_TABLE} (intention_id, data, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(intention_id) DO UPDATE SET "
                "data=excluded.data, updated_at=excluded.updated_at",
                (str(intention_id), json.dumps(data, ensure_ascii=False), utc_now()),
            )
            conn.commit()

    # -- intake --------------------------------------------------------

    def submit_goal(
        self,
        description: str,
        *,
        acceptance: list[str] | tuple[str, ...],
        origin: str = ORIGIN_USER,
        priority: int = 0,
    ):
        """Register a goal with the self-drive loop; returns the intention.

        ``acceptance`` is the goal's expected output: every item must be
        cited with real evidence before CP-3 lets the goal complete.
        User-submitted goals start immediately. Resident-proposed goals
        open a ``goal_control`` start card and wait for the user; without
        an approval channel they fail closed to blocked.
        """
        objective = str(description or "").strip()
        if not objective:
            raise ValueError("self-drive goal description must not be empty")
        criteria = [str(item).strip() for item in (acceptance or []) if str(item).strip()]
        if not criteria:
            raise ValueError("self-drive goal needs at least one acceptance criterion")
        if origin not in (ORIGIN_USER, ORIGIN_RESIDENT):
            raise ValueError(f"unknown goal origin: {origin!r}")

        intention = self._will.intend(
            objective,
            source=SELF_DRIVE_SOURCE,
            priority=int(priority),
        )
        goal = _new_goal_data(origin=origin, objective=objective, acceptance=criteria)
        if origin == ORIGIN_RESIDENT:
            try:
                opened = self._request_control(
                    intention.intention_id, "start", goal, objective
                )
            except Exception as exc:
                # The card itself failed to open: fail closed rather than
                # leaving an orphan active intention with no goal decision.
                self._record_error(
                    f"goal start card failed: {type(exc).__name__}: {exc}"
                )
                opened = False
                goal["blocked_reason"] = (
                    "ZN 自提目标需用户审批启动，但审批卡创建失败"
                    f"（{type(exc).__name__}），fail closed"
                )
            if not opened:
                if not goal.get("blocked_reason"):
                    goal["blocked_reason"] = (
                        "ZN 自提目标需用户审批启动，但无审批通道，fail closed"
                    )
                self._will.block(intention.intention_id, reason=goal["blocked_reason"])
                self._note(
                    f"自驱目标 {intention.intention_id} 未启动："
                    f"{goal['blocked_reason'][:120]}，已显式阻塞"
                )
        self._prune_terminal_goals()
        self._save_goal(intention.intention_id, goal)
        return intention

    def get_goal(self, intention_id: str) -> dict[str, Any] | None:
        """Read-only view of one goal's durable driver state."""
        goal = self._load_goal(intention_id)
        return dict(goal) if goal else None

    def _prune_terminal_goals(self, keep: int = 100) -> None:
        """Drop driver rows for terminal (completed/blocked) goals beyond keep.

        Active goals are never pruned: only goals whose Will intention has
        left the active set lose their driver row, so a long-running loop
        cannot grow the table without bound. Kept terminal goals stay
        visible via ``list_goals``.
        """
        rows: list[tuple[str, str]] = []
        with closing(self._connect()) as conn:
            rows = [
                (row["intention_id"], row["data"])
                for row in conn.execute(
                    f"SELECT intention_id, data FROM {_GOALS_TABLE} "
                    "ORDER BY updated_at DESC"
                ).fetchall()
            ]
        terminal: list[str] = []
        for intention_id, _data in rows:
            intention = self._will.get(intention_id)
            status = intention.status if intention else None
            if status in ("completed", "blocked"):
                terminal.append(intention_id)
            elif status is None:
                # The Will row is gone (e.g. store reset): the driver row is
                # orphaned bookkeeping, safe to drop.
                terminal.append(intention_id)
        drop = terminal[max(0, int(keep)):]
        if not drop:
            return
        with closing(self._connect()) as conn:
            conn.executemany(
                f"DELETE FROM {_GOALS_TABLE} WHERE intention_id=?",
                [(intention_id,) for intention_id in drop],
            )
            conn.commit()

    def list_goals(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read-only list of self-drive goals with their Will status."""
        items: list[dict[str, Any]] = []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT intention_id, data FROM {_GOALS_TABLE} "
                "ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        for row in rows:
            intention = self._will.get(row["intention_id"])
            data = json.loads(row["data"])
            items.append(
                {
                    "intention_id": row["intention_id"],
                    "status": intention.status if intention else "unknown",
                    "objective": data.get("objective"),
                    "origin": data.get("origin"),
                    "generation": data.get("generation"),
                    "blocked_reason": data.get("blocked_reason"),
                    "steps": len(data.get("step_history") or []),
                }
            )
        return items

    def status(self) -> dict[str, Any]:
        """Driver health snapshot (no new RPC; surfaced via resident status)."""
        return {
            "goals": self.list_goals(),
            "recent_errors": list(self._recent_errors),
            "recent_notes": list(self._recent_notes),
        }

    # -- per-pulse ------------------------------------------------------

    def drive(self) -> dict[str, int]:
        """Advance every self-drive goal by at most one decision.

        Called once per resident pulse by the install wrapper. May raise;
        the install wrapper (``_drive_quietly``) converts any unexpected
        error into a recorded note so the pulse loop never breaks.
        """
        summary = {
            "goals_checked": 0,
            "steps_proposed": 0,
            "completions": 0,
            "blocks": 0,
            "controls_polled": 0,
        }
        for intention in self._will.active(limit=200):
            if intention.source != SELF_DRIVE_SOURCE:
                continue
            if intention.status != "active":
                continue
            summary["goals_checked"] += 1
            self._drive_goal(intention, summary)
        return summary

    def _drive_goal(self, intention, summary: dict[str, int]) -> None:
        goal_id = intention.intention_id
        goal = self._load_goal(goal_id)
        if goal is None:
            return
        if goal.get("blocked_reason"):
            if intention.status != "blocked":
                self._will.block(goal_id, reason=goal["blocked_reason"])
                summary["blocks"] += 1
            return
        self._poll_control(intention, goal, summary)
        goal = self._load_goal(goal_id)
        if goal is None or goal.get("blocked_reason"):
            return
        pending = goal.get("pending_control") or {}
        if pending.get("action") == "start":
            # Resident-proposed goal still waiting for the user's start
            # approval: nothing advances until the card is decided.
            return
        intention = self._will.get(goal_id)
        if intention is None or intention.status != "active":
            return
        if intention.related_event_id or intention.next_task:
            # A step is already in flight or queued for the event pipeline.
            return
        self._apply_pending_redirect(intention, goal)
        if not self._observe_last_step(intention, goal, summary):
            return
        self._decide_next(intention, goal, summary)

    # -- step outcome observation ----------------------------------------

    def _latest_step_outcome(self, intention) -> tuple[str, str] | None:
        """Newest (event_id, label) outcome recorded in Will progress."""
        progress = intention.progress or ()
        for entry in reversed(progress[-_PROGRESS_SCAN_LIMIT:]):
            match = _EVENT_OUTCOME_RE.match(str(entry or ""))
            if match:
                return match.group(1), match.group(2)
        return None

    def _ledger(self, goal: dict[str, Any], goal_id: str) -> StrategyLedger:
        return StrategyLedger.from_state(
            goal.get("strategy_ledger"),
            plan_version=goal.get("generation"),
            root_work_item_id=goal_id,
        )

    def _observe_last_step(self, intention, goal: dict[str, Any], summary) -> bool:
        """Fold the finished step's outcome into history + strategy ledger.

        Returns False when the goal was blocked as a result.
        """
        latest = self._latest_step_outcome(intention)
        if latest is None:
            return True
        event_id, label = latest
        if event_id == goal.get("last_step_event_id"):
            return True
        outcome = self._store.get_event_outcome(event_id)
        if outcome is not None:
            success = bool(outcome.success)
            text = (
                outcome.response
                or outcome.reason
                or ("step succeeded" if success else "step failed")
            )
        else:
            success = label == "succeeded"
            text = f"event {event_id} {label} (no stored outcome)"
        task = intention.current_step or ""
        history = goal.get("step_history") or []
        history.append(
            {
                "event_id": event_id,
                "task": task,
                "strategy": goal.get("last_strategy"),
                "success": success,
                "outcome": str(text)[:1000],
                "at": utc_now(),
            }
        )
        goal["step_history"] = history[-_STEP_HISTORY_LIMIT:]
        goal["last_step_event_id"] = event_id

        ledger = self._ledger(goal, intention.intention_id)
        if success:
            ledger.record_success()
        else:
            strategy = str(goal.get("last_strategy") or task or "unknown step")
            decision, blocked_reason = ledger.record_failure(
                strategy, str(text), child_work_item_id=event_id
            )
            if decision == "blocked":
                goal["strategy_ledger"] = ledger.to_dict()
                self._save_goal(intention.intention_id, goal)
                self._block_goal(
                    intention,
                    goal,
                    blocked_reason or "策略循环已耗尽",
                    summary,
                )
                return False
        goal["strategy_ledger"] = ledger.to_dict()
        self._save_goal(intention.intention_id, goal)
        return True

    # -- cognition --------------------------------------------------------

    def _invoke(self, question: str) -> str:
        invoke = self._cognitive_invoke
        if invoke is None:
            invoke = self._kernel_invoke()
        if invoke is None:
            raise _NoCognitionAvailable(
                "self-drive decision needs cognition but none is wired"
            )
        return invoke(question, "")

    def _kernel_invoke(self) -> Callable[[str, str], str] | None:
        kernel = self._kernel
        if kernel is None:
            return None

        def invoke(question: str, context: str) -> str:
            result = kernel.run_goal(
                question,
                required_capabilities=("language_understanding",),
                metadata={"purpose": "self_drive_decision"},
                max_attempts_override=1,
            )
            worker_result = getattr(result, "worker_result", None)
            if worker_result is None or not getattr(worker_result, "success", False):
                raise RuntimeError("self-drive cognition worker failed")
            return str(getattr(worker_result, "response", "") or "")

        return invoke

    def _decision_question(self, intention, goal: dict[str, Any]) -> str:
        ledger = self._ledger(goal, intention.intention_id)
        history = goal.get("step_history") or []
        lines = [
            "你是 ZN 的自驱目标推进器。没有外部 cron 触发你：你靠每 pulse 一次的决策推进目标，"
            "一次只做一步，做完就停，下一 pulse 再继续。",
            f"目标：{goal.get('objective')}",
            "验收标准（全部满足、有真实证据引用，才能判完成）：",
        ]
        for item in goal.get("acceptance") or []:
            lines.append(f"- {item}")
        lines.append(f"当前代次：{goal.get('generation')}")
        if history:
            lines.append("已完成步骤（来自 Work 账本，可引用为证据）：")
            for step in history[-8:]:
                mark = "成功" if step.get("success") else "失败"
                lines.append(
                    f"- [{mark}] {step.get('task')}: {step.get('outcome')}"
                )
        progress = intention.progress or ()
        if progress:
            lines.append("最近进展：")
            for entry in progress[-8:]:
                lines.append(f"- {entry}")
        outcome_text = intention.last_outcome or "无（这是第一步）"
        lines.append(f"上一步结果：{outcome_text}")
        avoid = ledger.prompt_block()
        if avoid:
            lines.append("已试策略（不要重复这些策略/失败模式）：")
            lines.append(avoid)
        lines.append(
            "只返回 JSON，不要其他文字。二选一：\n"
            '1. 下一步：{"decision": "next_step", "task": "<具体可执行的一步>", '
            '"strategy": "<策略标签，可选>"}\n'
            '2. 已完成并给出终报：{"decision": "done", "completion_report": '
            '"<JSON 字符串，顶层含 completion_report 键：conclusion / evidence / '
            'files / unfinished / standing_dod（no_regression、runtime_verified、'
            'docs、rollback、approval 五项逐项填写）>"}\n'
            "规则：一次只做一步；上一步失败就换策略；不确定就继续推进，"
            "绝不谎报完成。evidence_ref 必须引用上面“已完成步骤”里的真实任务或结果原文。"
        )
        return "\n".join(lines)

    def _parse_decision(self, raw: str) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        decision = str(data.get("decision") or "").strip()
        if decision == "next_step":
            task = str(data.get("task") or "").strip()
            if not task:
                return None
            strategy = str(data.get("strategy") or "").strip() or task[:120]
            return {"decision": "next_step", "task": task, "strategy": strategy}
        if decision == "done":
            report = data.get("completion_report")
            if isinstance(report, dict):
                report_text = json.dumps(report, ensure_ascii=False)
            else:
                report_text = str(report or "").strip()
            if not report_text:
                return None
            try:
                parsed = json.loads(report_text)
            except (ValueError, TypeError):
                return None
            if not isinstance(parsed, dict) or "completion_report" not in parsed:
                return None
            return {"decision": "done", "completion_report": report_text}
        return None

    def _decide_next(self, intention, goal: dict[str, Any], summary) -> None:
        goal_id = intention.intention_id
        try:
            raw = self._invoke(self._decision_question(intention, goal))
        except _NoCognitionAvailable:
            # No cognition wired: the goal simply waits for the next pulse.
            return
        except Exception as exc:
            self._record_error(f"cognition invoke failed: {type(exc).__name__}: {exc}")
            return
        parsed = self._parse_decision(raw)
        if parsed is None:
            streak = int(goal.get("invalid_cognition_streak") or 0) + 1
            goal["invalid_cognition_streak"] = streak
            self._save_goal(goal_id, goal)
            if streak >= _MAX_INVALID_COGNITION:
                self._block_goal(
                    intention,
                    goal,
                    f"认知连续 {streak} 次返回不可用的决策，已显式阻塞",
                    summary,
                )
            return
        goal["invalid_cognition_streak"] = 0
        if parsed["decision"] == "next_step":
            goal["last_strategy"] = parsed["strategy"]
            self._save_goal(goal_id, goal)
            self._will.set_next_step(
                goal_id,
                parsed["task"],
                payload={
                    "self_drive_goal_id": goal_id,
                    "self_drive_strategy": parsed["strategy"],
                    "self_drive_generation": goal.get("generation"),
                },
            )
            summary["steps_proposed"] += 1
            return
        self._verify_completion(intention, goal, parsed["completion_report"], summary)

    # -- CP-3 completion gate ---------------------------------------------

    def _evidence_entries(self, goal: dict[str, Any]) -> list[dict[str, Any]]:
        """Re-read evidence from the durable step history at decision time."""
        entries: list[dict[str, Any]] = []
        for step in goal.get("step_history") or []:
            if not step.get("success"):
                continue
            entries.append(
                {
                    "relative_path": "",
                    "objective": str(step.get("task") or ""),
                    "result": str(step.get("outcome") or ""),
                }
            )
        return entries

    def _verify_completion(
        self, intention, goal: dict[str, Any], report_text: str, summary
    ) -> None:
        goal_id = intention.intention_id
        evidence = self._evidence_entries(goal)
        verdict = adjudicate_completion(
            expected_output=list(goal.get("acceptance") or []),
            evidence=evidence,
            summary=report_text,
            require_standing_dod=True,
        )
        if verdict.verdict == "verified":
            self._save_goal(goal_id, goal)
            self._will.complete(
                goal_id,
                summary=f"自驱目标完成（CP-3 verified）：{goal.get('objective')}",
            )
            summary["completions"] += 1
            self._note(f"自驱目标已完成：{goal.get('objective')}")
            return
        tracking, escalate, reason = record_verdict_attempt(
            goal.get("verdict_tracking"), run_id=goal_id, verdict=verdict
        )
        goal["verdict_tracking"] = tracking
        self._save_goal(goal_id, goal)
        if escalate:
            self._block_goal(
                intention,
                goal,
                f"完成裁决未通过且已升级：{reason}",
                summary,
            )
            return
        # Bounded retry: the next step is to address the missing items.
        goal["last_strategy"] = "verdict-retry"
        self._save_goal(goal_id, goal)
        self._will.set_next_step(
            goal_id,
            f"补齐完成裁决缺失项后重新验证：{verdict.feedback_text()}"[:1000],
            payload={
                "self_drive_goal_id": goal_id,
                "self_drive_strategy": "verdict-retry",
                "self_drive_generation": goal.get("generation"),
            },
        )
        summary["steps_proposed"] += 1

    # -- explicit block ----------------------------------------------------

    def _block_goal(self, intention, goal: dict[str, Any], reason: str, summary) -> None:
        goal_id = intention.intention_id
        goal["blocked_reason"] = str(reason)[:1000]
        goal["pending_control"] = None
        self._save_goal(goal_id, goal)
        self._will.block(goal_id, reason=goal["blocked_reason"])
        summary["blocks"] += 1
        self._note(f"自驱目标已显式阻塞：{goal.get('objective')} —— {reason}")

    # -- goal control: pause / resume / redirect -----------------------------

    def pause_goal(
        self, intention_id: str, *, by: str = ORIGIN_USER, reason: str | None = None
    ) -> str:
        """Pause a goal. User pauses directly; resident pauses via card."""
        intention = self._will.get(intention_id)
        if intention is None or intention.source != SELF_DRIVE_SOURCE:
            raise ValueError(f"unknown self-drive goal: {intention_id}")
        if by == ORIGIN_USER:
            self._clear_pending_control(intention_id, "pause")
            self._will.pause(intention_id, reason=reason)
            return "paused"
        return self._resident_control(intention_id, "pause", {}, reason)

    def resume_goal(self, intention_id: str, *, by: str = ORIGIN_USER) -> str:
        """Resume a paused goal. User resumes directly; resident via card."""
        intention = self._will.get(intention_id)
        if intention is None or intention.source != SELF_DRIVE_SOURCE:
            raise ValueError(f"unknown self-drive goal: {intention_id}")
        if by == ORIGIN_USER:
            self._clear_pending_control(intention_id, "resume")
            self._will.resume(intention_id)
            return "resumed"
        return self._resident_control(intention_id, "resume", {}, None)

    def redirect_goal(
        self,
        intention_id: str,
        *,
        new_objective: str,
        new_acceptance: list[str] | tuple[str, ...] | None = None,
        by: str = ORIGIN_USER,
        reason: str | None = None,
    ) -> str:
        """Change a goal's objective mid-flight.

        A redirect bumps the generation: the strategy ledger and verdict
        retry budget restart under the new objective, and a not-yet-engaged
        pending step is dropped so it never runs under the new objective.
        A step already engaged finishes first; the redirect applies right
        after its outcome lands.
        """
        objective = str(new_objective or "").strip()
        if not objective:
            raise ValueError("redirect needs a non-empty new objective")
        criteria = None
        if new_acceptance is not None:
            criteria = [
                str(item).strip() for item in new_acceptance if str(item).strip()
            ]
            if not criteria:
                raise ValueError("redirect acceptance must not be empty")
        intention = self._will.get(intention_id)
        if intention is None or intention.source != SELF_DRIVE_SOURCE:
            raise ValueError(f"unknown self-drive goal: {intention_id}")
        payload: dict[str, Any] = {"new_objective": objective}
        if criteria is not None:
            payload["new_acceptance"] = criteria
        if reason:
            payload["reason"] = str(reason)[:500]
        if by == ORIGIN_USER:
            self._clear_pending_control(intention_id, "redirect")
            return self._stage_redirect(intention_id, payload)
        return self._resident_control(intention_id, "redirect", payload, reason)

    def _stage_redirect(self, intention_id: str, payload: dict[str, Any]) -> str:
        intention = self._will.get(intention_id)
        goal = self._load_goal(intention_id)
        if intention is None or goal is None:
            raise ValueError(f"unknown self-drive goal: {intention_id}")
        if intention.related_event_id:
            goal["pending_redirect"] = dict(payload)
            self._save_goal(intention_id, goal)
            return "deferred"
        self._apply_redirect(intention, goal, payload)
        return "redirected"

    def _apply_pending_redirect(self, intention, goal: dict[str, Any]) -> None:
        pending = goal.get("pending_redirect")
        if not pending:
            return
        if intention.related_event_id:
            return
        goal["pending_redirect"] = None
        self._apply_redirect(intention, goal, pending)

    def _apply_redirect(
        self, intention, goal: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        goal_id = intention.intention_id
        old_objective = goal.get("objective")
        goal["objective"] = payload["new_objective"]
        if payload.get("new_acceptance") is not None:
            goal["acceptance"] = list(payload["new_acceptance"])
        goal["generation"] = int(goal.get("generation") or 1) + 1
        goal["strategy_ledger"] = None
        goal["verdict_tracking"] = None
        goal["invalid_cognition_streak"] = 0
        goal["pending_redirect"] = None
        redirects = goal.get("redirects") or []
        redirects.append(
            {
                "at": utc_now(),
                "from": old_objective,
                "to": payload["new_objective"],
                "reason": payload.get("reason"),
            }
        )
        goal["redirects"] = redirects[-16:]
        self._save_goal(goal_id, goal)
        self._will.clear_next_step(goal_id)
        self._note(
            f"自驱目标已改向（第 {goal['generation']} 代）：{payload['new_objective']}"
        )

    # -- approval envelope ---------------------------------------------------

    def _request_control(
        self,
        intention_id: str,
        action: str,
        goal: dict[str, Any],
        objective: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Open a goal_control card; False when no approval channel exists."""
        if action not in _CONTROL_ACTIONS:
            raise ValueError(f"unknown goal control action: {action!r}")
        store = self._approval_store
        if store is None:
            return False
        requester = getattr(store, "request_approval", None)
        if not callable(requester):
            return False
        if (goal.get("control_denied") or {}).get(action):
            # Deny is sticky: never silently re-ask the same control action.
            return False
        scope = _control_scope(intention_id, action)
        value = json.dumps(
            {
                "action": action,
                "objective": objective,
                "acceptance": goal.get("acceptance"),
                "payload": payload or {},
            },
            ensure_ascii=False,
        )[:1000]
        request = requester(
            action_kind=APPROVAL_KIND_GOAL_CONTROL,
            target=f"自驱目标控制：{action}（{objective[:120]}）",
            scope=scope,
            value_text=value,
            source="resident",
        )
        goal["pending_control"] = {
            "action": action,
            "card_id": request.request_id,
            "payload": payload or {},
        }
        return True

    def _resident_control(
        self,
        intention_id: str,
        action: str,
        payload: dict[str, Any],
        reason: str | None,
    ) -> str:
        goal = self._load_goal(intention_id)
        if goal is None:
            raise ValueError(f"unknown self-drive goal: {intention_id}")
        objective = goal.get("objective") or ""
        channel_ok = self._approval_store is not None
        opened = False
        if channel_ok:
            try:
                opened = self._request_control(
                    intention_id, action, goal, objective, payload
                )
            except Exception as exc:
                # A broken channel is the same as no channel: fail closed
                # rather than raising into the cognition loop.
                self._record_error(
                    f"goal_control card failed ({action}): "
                    f"{type(exc).__name__}: {exc}"
                )
                channel_ok = False
        self._save_goal(intention_id, goal)
        if opened:
            return "pending"
        if not channel_ok:
            # Fail closed in the safe direction: pause/redirect apply at
            # once rather than running uncontrolled; start/resume stay put.
            if action == "pause":
                self._will.pause(
                    intention_id, reason=reason or "无审批通道，fail closed 暂停"
                )
                return "paused-fail-closed"
            if action == "redirect":
                self._stage_redirect(intention_id, {**payload, "reason": reason})
                return "redirected-fail-closed"
            return "blocked-no-approval-channel"
        # Sticky deny: never silently re-ask the same control action.
        return "denied-sticky"

    def _clear_pending_control(self, intention_id: str, action: str) -> None:
        goal = self._load_goal(intention_id)
        if goal is None:
            return
        pending = goal.get("pending_control") or {}
        if pending.get("action") == action:
            goal["pending_control"] = None
            self._save_goal(intention_id, goal)

    def _poll_control(self, intention, goal: dict[str, Any], summary) -> None:
        pending = goal.get("pending_control") or {}
        action = pending.get("action")
        card_id = pending.get("card_id")
        if not action or not card_id:
            return
        summary["controls_polled"] += 1
        store = self._approval_store
        getter = getattr(store, "get_request", None) if store else None
        if not callable(getter):
            return
        try:
            request = getter(card_id)
        except Exception as exc:
            self._record_error(
                f"poll goal_control card failed: {type(exc).__name__}: {exc}"
            )
            return
        if request is None:
            return
        status = str(getattr(request, "status", "") or "")
        if status == "pending":
            return
        goal["pending_control"] = None
        if status in ("approved", "approved_once"):
            self._save_goal(intention.intention_id, goal)
            self._apply_approved_control(intention, action, pending.get("payload") or {})
            return
        # denied / expired: sticky, never re-ask.
        denied = goal.get("control_denied") or {}
        denied[action] = True
        goal["control_denied"] = denied
        if action == "start":
            self._save_goal(intention.intention_id, goal)
            self._block_goal(
                intention,
                goal,
                f"目标启动被用户拒绝（{status}），不再询问",
                summary,
            )
        else:
            self._save_goal(intention.intention_id, goal)
            self._note(f"自驱目标控制 {action} 被用户拒绝（{status}），保持现状")

    def _apply_approved_control(
        self, intention, action: str, payload: dict[str, Any]
    ) -> None:
        goal_id = intention.intention_id
        if action == "start":
            self._note(f"自驱目标启动已获批：{goal_id}")
        elif action == "pause":
            self._will.pause(goal_id, reason="用户批准暂停")
        elif action == "resume":
            self._will.resume(goal_id)
        elif action == "redirect":
            self._stage_redirect(goal_id, payload)

    # -- notes / errors -------------------------------------------------------

    def _note(self, text: str) -> None:
        self._recent_notes.append(f"{utc_now()} {text}")
        notify = self._notify
        if callable(notify):
            try:
                notify(text)
            except Exception as exc:
                self._record_error(
                    f"notify failed: {type(exc).__name__}: {exc}"
                )

    def _record_error(self, text: str) -> None:
        self._recent_errors.append(f"{utc_now()} {text}")

    def note_driver_error(self, text: str) -> None:
        """Record an unexpected driver error without breaking the pulse."""
        self._record_error(text)


_INSTALL_MARKER = "_zn_self_drive_installed"


def _drive_quietly(driver: SelfDriveDriver) -> bool:
    """Run one drive pass; an unexpected error is recorded, never raised."""
    try:
        driver.drive()
    except Exception as exc:
        driver.note_driver_error(
            f"drive failed: {type(exc).__name__}: {exc}"
        )
        return False
    return True


def install_self_drive_behavior(
    resident,
    *,
    kernel=None,
    approval_store=None,
    cognitive_invoke: Callable[[str, str], str] | None = None,
    notify: Callable[[str], None] | None = None,
) -> SelfDriveDriver | None:
    """Attach the native goal-driven self-drive loop to a resident.

    Mirrors ``install_recurring_will_behavior``: the driver's ``drive()``
    runs once per ``resident.pulse()`` before the original pulse, and any
    unexpected driver error is recorded instead of breaking the life loop.
    The driver is exposed as ``resident.self_drive`` for goal intake and
    pause/resume/redirect control (chat/cognition path, not a new RPC).
    Re-installing only re-wires explicitly passed knobs on the existing
    driver; the pulse wrapper is installed exactly once.
    """
    if getattr(resident, _INSTALL_MARKER, False):
        driver = getattr(resident, "self_drive", None)
        if driver is not None:
            driver.rewire(
                kernel=kernel,
                approval_store=approval_store,
                cognitive_invoke=cognitive_invoke,
                notify=notify,
            )
        return driver
    if not hasattr(resident, "will"):
        raise ValueError("self-drive behavior requires the existing NativeWill")
    if not hasattr(resident, "store"):
        raise ValueError("self-drive behavior requires the kernel store")

    driver = SelfDriveDriver(
        will=resident.will,
        store=resident.store,
        kernel=kernel if kernel is not None else getattr(resident, "kernel", None),
        approval_store=approval_store,
        cognitive_invoke=cognitive_invoke,
        notify=notify,
    )
    original_pulse = resident.pulse

    def pulse():
        _drive_quietly(driver)
        return original_pulse()

    resident.pulse = pulse
    resident.self_drive = driver
    setattr(resident, _INSTALL_MARKER, True)
    return driver

from __future__ import annotations

"""Background self-improvement loop for ZN (Muse pattern M5, reimplemented).

Source of the mechanism: Muse pattern M5 ("background self-improvement
loop"): background runs that do memory upkeep (newer claims supersede older
ones, the full trail is kept), skill review (audit existing skills against
recent work), and review of recent work (what worked, what ruptured). This
module reimplements that *mechanism* in ZN-owned code; it copies no Muse
code and no Muse content.

ZN port: only the mechanically verifiable parts, no "self-evolution":

- Memory tidy: AUDIT ONLY. Detects alias collisions and duplicate-value
  facts that the existing ``StructuredMemory`` supersession /
  consolidation mechanism (``memory.py``) could merge. It never deletes or
  rewrites a fact here: history is kept, and a merge is applied only
  through the existing ``memory.py`` paths with human confirmation.
- Skill audit: REPORT ONLY. Detects duplicate / conflicting / expired /
  deprecated skill bundles. It never edits or deletes a skill; the report
  carries recommendations for a human to act on.
- Retrospective: summarizes recent *finished* routine runs
  (succeeded / failed / failure reason) into review entries. Routine runs
  are the source because they are the only recent-task records with a
  structured success / failure / reason triple; work threads carry no
  outcome field, so they are deliberately not used here.

The loop itself is registered as one ordinary routine through the existing
``RoutineManager`` (P1-2 scheduling infra): the trigger organ owns "when",
the run history below owns "what happened". A scheduled occurrence hands
the task text to Will through the normal routine path; :func:`trigger_self_improvement`
is the deterministic manual execution of the same three steps, and it
records its run in :class:`SelfImprovementHistory`.
"""

import json
import re
import sqlite3
import unicodedata
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .models import utc_now
from .routine_request import DEFAULT_OWNER
from .skills import MAX_SKILL_BODY_CHARS, SkillStore

SELF_IMPROVEMENT_TASK = "自改进：整理记忆、审计 Skill、复盘最近任务"
SELF_IMPROVEMENT_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly
SELF_IMPROVEMENT_TIMEZONE = "UTC"
SELF_IMPROVEMENT_INPUT_SOURCE = "ZN 记忆事实、Skill  bundle、最近例行任务运行记录"
SELF_IMPROVEMENT_EXPECTED_RESULT = (
    "产出一份自改进报告：记忆审计发现、Skill 审计发现、最近任务复盘条目；"
    "只读，不删改记忆与 Skill"
)
SELF_IMPROVEMENT_APPROVAL_BOUNDARY = (
    "只读审计与汇总，不发送、不发布、不删除、不购买、不改写记忆与 Skill；"
    "任何合并/删除/修改需人工确认后另行执行"
)
SELF_IMPROVEMENT_MISSING_DATA_POLICY = "skip"
SELF_IMPROVEMENT_AUTO_PAUSE_AFTER_DAYS = 14

MAX_REVIEW_ENTRIES = 50
MAX_RUN_HISTORY = 100

_DEPRECATED_MARKERS = ("deprecated", "已废弃", "已过期", "expired", "do not use")


def self_improvement_draft() -> dict:
    """The six-confirmation draft for the self-improvement routine."""
    return {
        "text": SELF_IMPROVEMENT_TASK,
        "task": SELF_IMPROVEMENT_TASK,
        "owner": DEFAULT_OWNER,
        "schedule_kind": "interval",
        "interval_seconds": SELF_IMPROVEMENT_INTERVAL_SECONDS,
        "cron_expression": None,
        "timezone": SELF_IMPROVEMENT_TIMEZONE,
        "input_source": SELF_IMPROVEMENT_INPUT_SOURCE,
        "expected_result": SELF_IMPROVEMENT_EXPECTED_RESULT,
        "approval_boundary": SELF_IMPROVEMENT_APPROVAL_BOUNDARY,
        "missing_data_policy": SELF_IMPROVEMENT_MISSING_DATA_POLICY,
        "auto_pause_after_days": SELF_IMPROVEMENT_AUTO_PAUSE_AFTER_DAYS,
        "missing": [],
    }


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _value_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _skill_field(skill: Any, name: str, default: Any = "") -> Any:
    if isinstance(skill, dict):
        return skill.get(name, default)
    return getattr(skill, name, default)


# -- memory audit (read-only) --------------------------------------------


def audit_memory_facts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect merge candidates among stored memory facts. Never mutates.

    ``facts`` are ``store.list_facts()`` rows (``key`` / ``value`` /
    ``aliases``). Findings:

    - ``alias_collisions``: one normalized alias claimed by two or more
      keys — the exact ambiguity ``StructuredMemory.consolidate()`` resolves.
    - ``duplicate_values``: the same normalized value stored under two or
      more keys.
    - ``empty_facts``: keys whose value is blank / empty.
    """
    alias_claims: dict[str, list[str]] = {}
    value_claims: dict[str, list[str]] = {}
    empty: list[str] = []
    for fact in facts:
        key = str(fact.get("key") or "").strip()
        if not key:
            continue
        value = fact.get("value")
        if value is None or (isinstance(value, str) and not value.strip()) or (
            isinstance(value, (list, dict)) and not value
        ):
            empty.append(key)
        aliases = fact.get("aliases") or ()
        seen: set[str] = set()
        for alias in (key, *aliases):
            normalized = _normalize(str(alias or ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            alias_claims.setdefault(normalized, []).append(key)
        value_claims.setdefault(_normalize(_value_text(value)), []).append(key)
    collisions = [
        {"alias": alias, "keys": sorted(set(keys))}
        for alias, keys in sorted(alias_claims.items())
        if len(set(keys)) >= 2
    ]
    duplicates = [
        {"keys": sorted(set(keys))}
        for value, keys in sorted(value_claims.items())
        if value and len(set(keys)) >= 2
    ]
    return {
        "fact_count": len(facts),
        "alias_collisions": collisions,
        "duplicate_values": duplicates,
        "empty_facts": sorted(empty),
        "finding_count": len(collisions) + len(duplicates) + len(empty),
    }


# -- skill audit (read-only) ----------------------------------------------


def audit_skills(skills: list[Any]) -> dict[str, Any]:
    """Audit skill bundles. Never edits or deletes a skill.

    ``skills`` are :class:`Skill` objects or dicts with ``name`` /
    ``description`` / ``version`` / ``path`` / ``body`` / ``meta``.
    Findings: duplicate names, conflicting descriptions under one name,
    near-duplicate descriptions under different names, expired/deprecated
    skills, and bodies at the truncation limit.
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_description: dict[str, list[str]] = {}
    expired: list[dict[str, Any]] = []
    at_limit: list[str] = []
    for skill in skills:
        name = str(_skill_field(skill, "name") or "").strip()
        description = str(_skill_field(skill, "description") or "").strip()
        body = str(_skill_field(skill, "body") or "")
        meta = _skill_field(skill, "meta", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        path = _skill_field(skill, "path", "")
        entry = {
            "name": name,
            "description": description,
            "version": str(_skill_field(skill, "version") or ""),
            "path": str(path),
        }
        if name:
            by_name.setdefault(_normalize(name), []).append(entry)
        if description:
            by_description.setdefault(_normalize(description), []).append(name or "?")
        reason = _expiry_reason(meta, body)
        if reason:
            expired.append({"name": name, "path": str(path), "reason": reason})
        if len(body) >= MAX_SKILL_BODY_CHARS:
            at_limit.append(name)
    duplicates = [
        {"name": name, "entries": entries}
        for name, entries in sorted(by_name.items())
        if len(entries) >= 2
    ]
    conflicts = [
        {
            "name": name,
            "descriptions": sorted({entry["description"] for entry in entries}),
        }
        for name, entries in sorted(by_name.items())
        if len({entry["description"] for entry in entries}) >= 2
    ]
    near_duplicates = [
        {"description": description, "names": sorted(set(names))}
        for description, names in sorted(by_description.items())
        if len(set(names)) >= 2
    ]
    recommendations: list[str] = []
    for item in duplicates:
        recommendations.append(
            f"Skill 重名 {item['name']}：保留一份，删除或重命名其余，人工确认后执行"
        )
    for item in conflicts:
        recommendations.append(
            f"Skill 冲突 {item['name']}：同一名字有不同描述，先定哪份为准再改"
        )
    for item in near_duplicates:
        recommendations.append(
            f"Skill 描述重复（{', '.join(item['names'])}）：考虑合并为一个 Skill"
        )
    for item in expired:
        recommendations.append(
            f"Skill 过期/废弃 {item['name']}（{item['reason']}）：人工确认后归档或删除"
        )
    for name in at_limit:
        recommendations.append(
            f"Skill 正文已达截断上限 {name}：检查正文是否被截断，拆分或精简"
        )
    return {
        "skill_count": len(skills),
        "duplicates": duplicates,
        "conflicts": conflicts,
        "near_duplicates": near_duplicates,
        "expired": expired,
        "at_size_limit": sorted(set(at_limit)),
        "recommendations": recommendations,
        "finding_count": (
            len(duplicates)
            + len(conflicts)
            + len(near_duplicates)
            + len(expired)
            + len(set(at_limit))
        ),
    }


def _expiry_reason(meta: dict[str, Any], body: str) -> str | None:
    status = str(meta.get("status") or meta.get("state") or "").strip().lower()
    if status in {"deprecated", "expired", "archived", "retired"}:
        return f"status={status}"
    for field in ("expires", "expires_at", "expiry"):
        raw = str(meta.get(field) or "").strip()
        if not raw:
            continue
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return f"{field} 无法解析：{raw}"
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment < datetime.now(timezone.utc):
            return f"{field} 已过：{raw}"
        return None
    lowered = body.lower()
    for marker in _DEPRECATED_MARKERS:
        if marker in lowered or marker in body:
            return f"正文含标记：{marker}"
    return None


# -- retrospective (read-only) --------------------------------------------


def summarize_recent_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recent finished tasks into review entries.

    ``tasks`` are normalized records with ``task`` / ``title``, ``status``
    (``succeeded`` / ``failed`` / anything else) and optional
    ``failure_reason`` / ``summary``. Running tasks are not finished work
    and are counted separately as ``in_flight`` by the collector.
    """
    succeeded = failed = other = 0
    failure_reasons: dict[str, int] = {}
    entries: list[dict[str, Any]] = []
    for item in tasks:
        title = str(item.get("task") or item.get("title") or "").strip() or "(未命名任务)"
        status = str(item.get("status") or "").strip().lower()
        if status in {"succeeded", "success", "completed", "complete"}:
            succeeded += 1
        elif status in {"failed", "failure", "error"}:
            failed += 1
            reason = str(item.get("failure_reason") or item.get("summary") or "未给原因").strip()
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            if len(entries) < MAX_REVIEW_ENTRIES:
                entries.append({"kind": "failure", "task": title, "reason": reason})
        else:
            other += 1
    total = succeeded + failed + other
    summary_entry = {
        "kind": "summary",
        "task": f"最近 {total} 个已完成任务：成功 {succeeded}，失败 {failed}，其他 {other}",
        "reason": (
            "失败原因最多的是："
            + (
                "; ".join(
                    f"{reason}×{count}"
                    for reason, count in sorted(
                        failure_reasons.items(), key=lambda kv: (-kv[1], kv[0])
                    )[:3]
                )
                or "无"
            )
        ),
    }
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "other": other,
        "failure_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                failure_reasons.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "entries": [summary_entry, *entries],
    }


def collect_recent_routine_runs(
    routine_manager: Any,
    *,
    per_routine: int = 20,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Collect finished routine runs as retrospective input.

    Returns ``(tasks, in_flight)``. Runs still ``running`` are not finished
    work: they are counted, not summarized.
    """
    tasks: list[dict[str, Any]] = []
    in_flight = 0
    try:
        routines = routine_manager.list_routines(limit=100)
    except Exception:
        return [], 0
    for routine in routines:
        routine_id = str(routine.get("routine_id") or "")
        title = str(routine.get("title") or routine.get("task") or "").strip()
        try:
            runs = routine_manager.runs(routine_id, limit=max(1, int(per_routine)))
        except Exception:
            continue
        for run in runs:
            status = str(run.get("status") or "").strip().lower()
            if status == "running":
                in_flight += 1
                continue
            tasks.append(
                {
                    "task": title or str(run.get("routine_id") or ""),
                    "status": status,
                    "failure_reason": run.get("failure_reason"),
                    "summary": run.get("summary"),
                    "routine_id": routine_id,
                    "run_id": str(run.get("run_id") or ""),
                    "started_at": str(run.get("started_at") or ""),
                }
            )
    tasks.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return tasks[: max(1, int(limit))], in_flight


# -- orchestration (read-only) ---------------------------------------------


def run_self_improvement(
    *,
    memory_facts: list[dict[str, Any]] | None = None,
    skills: list[Any] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the three mechanical steps and return the report. No mutation."""
    memory_report = audit_memory_facts(list(memory_facts or []))
    skill_report = audit_skills(list(skills or []))
    review = summarize_recent_tasks(list(tasks or []))
    return {
        "generated_at": utc_now(),
        "source": "zn_self_improvement_loop (Muse pattern M5, reimplemented)",
        "memory": memory_report,
        "skills": skill_report,
        "review": review,
        "total_findings": (
            memory_report["finding_count"]
            + skill_report["finding_count"]
            + review["failed"]
        ),
        "note": "本报告只读：未删除、未改写任何记忆事实与 Skill；建议需人工确认后另行执行。",
    }


# -- run history ------------------------------------------------------------


@dataclass(slots=True)
class SelfImprovementRun:
    run_id: str
    routine_id: str | None
    started_at: str
    finished_at: str | None = None
    status: str = "running"  # running | succeeded | failed
    failure_reason: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SelfImprovementHistory:
    """Durable run history for the self-improvement loop.

    One row per execution, kept in the same kernel SQLite file as the
    routine run history. Mirrors the ``RoutineManager`` storage pattern.
    """

    def __init__(self, store: Any):
        self.store = store
        self._init_schema()

    def record(self, report: dict[str, Any], *, routine_id: str | None = None) -> dict:
        run_id = f"si-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        summary = json.dumps(report, ensure_ascii=False, default=str)[:20000]
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO self_improvement_runs(
                    run_id,routine_id,started_at,finished_at,status,
                    failure_reason,summary
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (run_id, routine_id, now, now, "succeeded", None, summary),
            )
            conn.execute(
                """
                DELETE FROM self_improvement_runs WHERE run_id NOT IN (
                    SELECT run_id FROM self_improvement_runs
                    ORDER BY started_at DESC, run_id DESC LIMIT ?
                )
                """,
                (MAX_RUN_HISTORY,),
            )
            conn.commit()
        row = self.get(run_id)
        if row is None:
            raise RuntimeError("self-improvement run did not persist")
        return row

    def record_failure(self, reason: str, *, routine_id: str | None = None) -> dict:
        run_id = f"si-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO self_improvement_runs(
                    run_id,routine_id,started_at,finished_at,status,
                    failure_reason,summary
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (run_id, routine_id, now, now, "failed", str(reason)[:2000], None),
            )
            conn.commit()
        row = self.get(run_id)
        if row is None:
            raise RuntimeError("self-improvement run did not persist")
        return row

    def get(self, run_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM self_improvement_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def recent(self, *, limit: int = 20) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM self_improvement_runs "
                "ORDER BY started_at DESC, run_id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS self_improvement_runs(
                    run_id TEXT PRIMARY KEY,
                    routine_id TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    failure_reason TEXT,
                    summary TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_self_improvement_runs_recent
                    ON self_improvement_runs(started_at DESC);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return SelfImprovementRun(
            run_id=str(row["run_id"]),
            routine_id=str(row["routine_id"]) if row["routine_id"] else None,
            started_at=str(row["started_at"] or ""),
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
            status=str(row["status"]),
            failure_reason=(
                str(row["failure_reason"]) if row["failure_reason"] else None
            ),
            summary=str(row["summary"]) if row["summary"] else None,
        ).to_dict()


# -- registration + manual trigger ------------------------------------------


def ensure_self_improvement_routine(routine_manager: Any) -> dict:
    """Register the self-improvement routine once (idempotent).

    Uses the existing ``RoutineManager.confirm`` path, so the trigger organ
    owns the cadence and the routine shows up in the normal routine list,
    run history, pause/resume/edit/delete flows. A second call returns the
    existing routine instead of creating a duplicate.
    """
    for routine in routine_manager.list_routines(limit=500):
        if str(routine.get("task") or "") == SELF_IMPROVEMENT_TASK:
            return routine
    return routine_manager.confirm(self_improvement_draft())


def trigger_self_improvement(
    resident: Any,
    *,
    skill_store: SkillStore | None = None,
    history: SelfImprovementHistory | None = None,
) -> dict:
    """Manually execute the three steps once and record the run.

    Gathers live inputs from the resident (memory facts, skill bundles,
    recent routine runs), runs the read-only report, and appends one run
    row. On failure a failed run row is recorded and the error re-raised.
    """
    routine_id: str | None = None
    try:
        routines = getattr(resident, "routines", None)
        if routines is not None:
            for routine in routines.list_routines(limit=500):
                if str(routine.get("task") or "") == SELF_IMPROVEMENT_TASK:
                    routine_id = str(routine.get("routine_id") or "") or None
                    break
        facts = list(resident.store.list_facts())
        store = skill_store if skill_store is not None else SkillStore()
        skills = store.discover()
        tasks, in_flight = (
            collect_recent_routine_runs(routines) if routines is not None else ([], 0)
        )
        report = run_self_improvement(
            memory_facts=facts, skills=skills, tasks=tasks,
        )
        report["in_flight_routine_runs"] = in_flight
        report["routine_id"] = routine_id
        recorder = history if history is not None else SelfImprovementHistory(resident.store)
        row = recorder.record(report, routine_id=routine_id)
        return {"report": report, "run": row}
    except Exception as exc:
        try:
            recorder = history if history is not None else SelfImprovementHistory(resident.store)
            recorder.record_failure(str(exc), routine_id=routine_id)
        except Exception:
            pass
        raise


__all__ = [
    "SELF_IMPROVEMENT_APPROVAL_BOUNDARY",
    "SELF_IMPROVEMENT_AUTO_PAUSE_AFTER_DAYS",
    "SELF_IMPROVEMENT_EXPECTED_RESULT",
    "SELF_IMPROVEMENT_INPUT_SOURCE",
    "SELF_IMPROVEMENT_INTERVAL_SECONDS",
    "SELF_IMPROVEMENT_MISSING_DATA_POLICY",
    "SELF_IMPROVEMENT_TASK",
    "SELF_IMPROVEMENT_TIMEZONE",
    "SelfImprovementHistory",
    "SelfImprovementRun",
    "audit_memory_facts",
    "audit_skills",
    "collect_recent_routine_runs",
    "ensure_self_improvement_routine",
    "run_self_improvement",
    "self_improvement_draft",
    "summarize_recent_tasks",
    "trigger_self_improvement",
]

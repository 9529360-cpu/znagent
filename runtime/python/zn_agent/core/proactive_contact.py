from __future__ import annotations

"""S1(b): 有节制的主动联系。

ZN 主动发起的问候 / 关心（例如"今天有 X 安排，要我帮你准备吗"）。
候选来源复用 P1-1 建议栏的确定性规则：到期的例行任务、记忆中的用户
事项（routine: 事实）、建议栏里的其他内容——不做任何模型调用。

节制规则（全部有测试锁定）：
1. 全局开关：环境变量 ``ZN_PROACTIVE_CONTACT``（0 关闭 / 1 开启），
   默认开启。理由：S1 整条线的目标就是让 ZN 像路遥一样"有灵魂"——
   会主动联系；防打扰靠的是下面的节制层（频率上限、夜间免打扰、
   拒绝后抑制），而不是把开关默认关掉让整条线变成死代码。仓库惯例
   上同类常驻能力（建议栏 P1-1、recurring will）也都是默认开启、
   开关只做逃生舱。
2. 每日上限：``ZN_PROACTIVE_CONTACT_MAX_PER_DAY``，默认每天最多 2 次
   （按用户本地日期计）。
3. 夜间免打扰：用户本地时间 22:00–07:00 不主动联系；
   ``ZN_PROACTIVE_CONTACT_QUIET_START`` / ``_QUIET_END`` 可配。
4. 拒绝 / 忽略后抑制：复用建议栏"拒绝后 7 天不重复推"语义——建议栏
   里被 dismiss 的 key 不会成为候选；一次主动联系被用户拒绝或忽略
   后，同一 key 同样抑制 7 天（``SUPPRESSION_TTL`` 与
   ``suggestions._DISMISSAL_TTL`` 用测试锁定为同一值）。

人格层：
- 问候语经 ``persona.render_persona`` 绑定人格指纹：同一人格文件 +
  同一触发条件 → 逐字节相同的问候；人格文件一改，指纹即变，漂移可
  追踪（测试锁定）。
- 口吻遵循 SOUL.md：中文、短、对用户用"你"、不说客服腔、不亲昵。

安全边界（#498 护栏语义不动）：
- ``maybe_contact`` 只做只读查询 + 自身记账表写入（抑制表 / 发送日志，
  与建议栏的 dismissal 表同类）；不创建 Work 线程、不产生事件、
  不触审批、不执行任何动作。
- 返回的 ``ProactiveContact`` 只有展示字段；点击它的动作是只读路由
  （``action="open_suggestion"``：走现有 Work / 建议栏路径），任何真
  实副作用仍走审批卡。

纯 stdlib + persona 模块；建议引擎由调用方注入。
"""

import logging
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .persona import load_zn_persona, persona_fingerprint, render_persona

_LOG = logging.getLogger(__name__)

#: 全局开关环境变量：0 关闭，其他/未设置开启。
ENABLED_ENV = "ZN_PROACTIVE_CONTACT"
#: 每日上限环境变量。
MAX_PER_DAY_ENV = "ZN_PROACTIVE_CONTACT_MAX_PER_DAY"
#: 夜间免打扰起止（小时，0-23）环境变量。
QUIET_START_ENV = "ZN_PROACTIVE_CONTACT_QUIET_START"
QUIET_END_ENV = "ZN_PROACTIVE_CONTACT_QUIET_END"

_DEFAULT_MAX_PER_DAY = 2
_DEFAULT_QUIET_START = 22
_DEFAULT_QUIET_END = 7

#: 拒绝 / 忽略后抑制时长：与建议栏 7 天语义一致（测试锁定相等）。
SUPPRESSION_TTL = timedelta(days=7)

#: 用户反馈的合法取值。
_FEEDBACK_VALUES = ("accepted", "dismissed", "ignored")

#: 问候语模板：按建议 kind 定。SOUL.md 口吻——中文、短、"你"、无客服腔。
#: 模板本身是常量（漂移锁定测试覆盖）；人格变化只改变指纹，不改变措辞。
_GREETINGS = {
    "recurring_due": "提醒你一下：「{task}」到点了，要我现在开始吗？",
    "recurring_upcoming": "「{task}」快到点了，要我帮你准备吗？",
    "failed_work": "上次「{task}」没跑完，要我继续吗？",
    "interrupted_work": "你刚才提到「{task}」，我还没回你——现在继续？",
    "autonomy_gated": "有个到点的事项「{task}」之前被我拦下了，要看看吗？",
    "routine": "「{task}」——今天要安排吗？",
}
_FALLBACK_GREETING = "有个事项想跟你确认：「{task}」，要我处理吗？"

_MAX_TASK_CHARS = 80


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _LOG.warning("invalid %s=%r; using default %d", name, raw, default)
        return default


@dataclass(frozen=True, slots=True)
class ProactiveContactConfig:
    """节制规则配置：环境变量 > 默认值。"""

    enabled: bool = True
    max_per_day: int = _DEFAULT_MAX_PER_DAY
    quiet_start: int = _DEFAULT_QUIET_START  # 夜间免打扰开始（小时）
    quiet_end: int = _DEFAULT_QUIET_END  # 夜间免打扰结束（小时）

    @classmethod
    def from_env(cls) -> "ProactiveContactConfig":
        return cls(
            enabled=_env_flag(ENABLED_ENV, True),
            max_per_day=max(0, _env_int(MAX_PER_DAY_ENV, _DEFAULT_MAX_PER_DAY)),
            quiet_start=_env_int(QUIET_START_ENV, _DEFAULT_QUIET_START) % 24,
            quiet_end=_env_int(QUIET_END_ENV, _DEFAULT_QUIET_END) % 24,
        )


@dataclass(frozen=True, slots=True)
class ProactiveContact:
    """一次主动联系：纯展示内容，无任何执行能力。"""

    key: str
    kind: str
    title: str
    task: str
    message: str
    source: dict[str, Any] = field(default_factory=dict)
    persona_fingerprint: str = ""
    prompt_context: str = ""
    sent_at: str = ""
    #: 只读路由：点击后走现有建议栏 / Work 路径，不执行动作。
    action: str = "open_suggestion"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "task": self.task,
            "message": self.message,
            "source": dict(self.source),
            "persona_fingerprint": self.persona_fingerprint,
            "prompt_context": self.prompt_context,
            "sent_at": self.sent_at,
            "action": self.action,
        }


def compose_greeting(kind: str, task: str) -> str:
    """按 kind 套用问候模板（确定性，见 _GREETINGS）。"""
    short = str(task or "").strip()
    if len(short) > _MAX_TASK_CHARS:
        short = short[:_MAX_TASK_CHARS] + "…"
    template = _GREETINGS.get(str(kind or ""), _FALLBACK_GREETING)
    return template.format(task=short)


class ProactiveContactEngine:
    """有节制的主动联系引擎。

    ``suggestion_engine`` 复用 P1-1 建议栏（含其 7 天 dismissal 语义）；
    ``persona_dir`` 传给 ``load_zn_persona``（None 时按默认顺序解析，
    每次联系都重读文件，人格文件即事实源）。
    """

    def __init__(
        self,
        resident,
        suggestion_engine,
        config: ProactiveContactConfig | None = None,
        persona_dir: str | Path | None = None,
    ):
        self.resident = resident
        self.suggestion_engine = suggestion_engine
        self.config = config or ProactiveContactConfig.from_env()
        self.persona_dir = persona_dir
        self.store = resident.store
        self._lock = threading.RLock()
        self._schema_ready = False

    # -- 主入口 --------------------------------------------------------

    def maybe_contact(self, *, now: datetime | None = None) -> ProactiveContact | None:
        """评估是否应主动联系一次。

        返回 None 表示"本次不打扰"（开关关 / 夜间 / 超频 / 无候选 /
        被抑制）；返回 ProactiveContact 表示可以展示给用户。
        除自身记账表外不写任何状态、不产生任何副作用。
        """
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if not self.config.enabled:
            return None
        local = self._local_time(current)
        if self._in_quiet_hours(local):
            return None
        self._ensure_schema()
        self._prune_expired(current)
        if self._sent_today(local) >= self.config.max_per_day:
            return None
        suppressed = self._suppressed_keys(current)
        candidate = self._pick_candidate(suppressed)
        if candidate is None:
            return None
        return self._build_contact(candidate, current, local)

    def note_feedback(
        self,
        key: str,
        feedback: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """记录用户对一次主动联系的反馈。

        dismissed / ignored → 该 key 抑制 7 天；
        accepted → 解除抑制（用户接了话，不再拦）。
        """
        normalized = str(key or "").strip()
        if not normalized:
            raise ValueError("proactive_contact_feedback requires a key")
        kind = str(feedback or "").strip().lower()
        if kind not in _FEEDBACK_VALUES:
            raise ValueError(
                f"feedback must be one of {', '.join(_FEEDBACK_VALUES)}"
            )
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        self._ensure_schema()
        with self._lock, closing(self._connect()) as conn:
            if kind == "accepted":
                conn.execute(
                    "DELETE FROM resident_proactive_contact_suppressions "
                    "WHERE suggestion_key=?",
                    (normalized,),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO resident_proactive_contact_suppressions(
                        suggestion_key,suppressed_at,expires_at
                    ) VALUES(?,?,?)
                    ON CONFLICT(suggestion_key) DO UPDATE SET
                        suppressed_at=excluded.suppressed_at,
                        expires_at=excluded.expires_at
                    """,
                    (
                        normalized,
                        current.isoformat(),
                        (current + SUPPRESSION_TTL).isoformat(),
                    ),
                )
            conn.commit()
        return {
            "key": normalized,
            "feedback": kind,
            "suppressed": kind != "accepted",
            "suppressed_until": (
                (current + SUPPRESSION_TTL).isoformat()
                if kind != "accepted"
                else None
            ),
        }

    # -- 候选与渲染 ----------------------------------------------------

    def _pick_candidate(
        self, suppressed: set[str]
    ) -> dict[str, Any] | None:
        try:
            items = self.suggestion_engine.list_suggestions()
        except Exception:
            _LOG.debug("suggestion engine unreadable; no proactive contact", exc_info=True)
            return None
        for item in items:
            if str(item.get("key") or "") not in suppressed:
                return item
        return None

    def _build_contact(
        self,
        candidate: dict[str, Any],
        current: datetime,
        local: datetime,
    ) -> ProactiveContact:
        persona = load_zn_persona(self.persona_dir)
        kind = str(candidate.get("kind") or "")
        task = str(candidate.get("task") or candidate.get("title") or "")
        contact = ProactiveContact(
            key=str(candidate.get("key") or ""),
            kind=kind,
            title=str(candidate.get("title") or task),
            task=task,
            message=compose_greeting(kind, task),
            source=dict(candidate.get("source") or {}),
            persona_fingerprint=persona_fingerprint(persona),
            prompt_context=render_persona(persona),
            sent_at=current.isoformat(),
        )
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_proactive_contact_log(
                    suggestion_key,kind,sent_at,day
                ) VALUES(?,?,?,?)
                """,
                (contact.key, contact.kind, contact.sent_at, local.date().isoformat()),
            )
            conn.commit()
        return contact

    # -- 节制规则 --------------------------------------------------------

    @staticmethod
    def _local_time(current: datetime) -> datetime:
        """用户本地时间：调用方传入的 now 若带 tzinfo 则以其时区为准，
        否则用系统本地时区（ZN 住在用户电脑上）。"""
        if current.tzinfo is not None:
            return current.astimezone(current.tzinfo)
        return current.astimezone()

    def _in_quiet_hours(self, local: datetime) -> bool:
        start, end = self.config.quiet_start, self.config.quiet_end
        if start == end:
            return False
        hour = local.hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _sent_today(self, local: datetime) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM resident_proactive_contact_log WHERE day=?",
                (local.date().isoformat(),),
            ).fetchone()
        return int(row["n"]) if row else 0

    def _suppressed_keys(self, current: datetime) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT suggestion_key FROM resident_proactive_contact_suppressions "
                "WHERE expires_at > ?",
                (current.isoformat(),),
            ).fetchall()
        return {str(row["suggestion_key"]) for row in rows}

    def _prune_expired(self, current: datetime) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM resident_proactive_contact_suppressions "
                "WHERE expires_at <= ?",
                (current.isoformat(),),
            )
            conn.commit()

    # -- schema ----------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._lock:
            if self._schema_ready:
                return
            self._init_schema()
            self._schema_ready = True

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_proactive_contact_suppressions(
                    suggestion_key TEXT PRIMARY KEY,
                    suppressed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proactive_contact_suppressions_expiry
                    ON resident_proactive_contact_suppressions(expires_at);
                CREATE TABLE IF NOT EXISTS resident_proactive_contact_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    suggestion_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    day TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proactive_contact_log_day
                    ON resident_proactive_contact_log(day);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

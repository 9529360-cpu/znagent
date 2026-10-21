from __future__ import annotations

"""S1(c): 每日日记。

ZN 每日把当日工作与互动写成简短日记，经既有记忆写入路径
（``StructuredMemory.remember``——与 daemon ``remember`` RPC 同一
入口：CM-3 隐私 choke 自动生效、可 ``forget``、可 supersession）
落盘进记忆；次日或显式查询（``recall("日记")`` / ``diary_get`` /
``diary_list``）可回顾。

触发与节制（不建后台线程、不新增无审批的自主写入路径）：
- 触发点是 daemon ``diary_write`` RPC，由既有例行 / 自驱循环
  （recurring will / routine 收尾）在每天调用一次；引擎本身
  不起线程、不轮询、不常驻。
- 全局开关 ``ZN_DIARY``（0 关闭，默认开启；理由见下）。
- 每日只写一次（按用户本地日期）：稳定 key
  ``zn-diary:YYYY-MM-DD``，P1-1 建议栏式去重；同日重复调用
  直接返回已存在的条目，不重写、不产生新版本。
- Q12 自主权包络：domain ``diary.daily``；只有 ``observe_only``
  拦下写入（唯一表示"绝不自主产出"的层级），其他层级（含 fail
  closed 的 ``require_approval``）都写——日记是写进 ZN 自己记忆的
  可逆记录，不是 #498 审批卡管辖的外部副作用。

开关默认开启的理由（抄 S1(b) ``ZN_PROACTIVE_CONTACT`` 模式）：
S1 整条线的目标就是让 ZN 像路遥一样"有灵魂"——会写日记；
防写滥用靠的是节制层（每日一次、稳定 key 去重、自主权包络、
显式触发点），而不是把开关默认关掉让整条线变成死代码。仓库惯例
上同类常驻能力（建议栏 P1-1、recurring will、S1(b) 主动联系）
也都是默认开启、开关只做逃生舱。

人格层：
- 日记正文由确定性模板 + 当日素材拼成：同一人格 + 同一素材 +
  同一日期 → 逐字节相同的正文（漂移锁定测试覆盖）。
- 条目绑定 ``persona_fingerprint``：人格文件一改指纹即变，可追踪。
- 口吻遵循 SOUL.md：中文、短、不说客服腔、不亲昵。

安全边界（#498 护栏语义不动）：
- ``maybe_write`` 只做：读工作台账（只读）、经既有 remember
  路径写一条记忆；不创建 Work 线程、不产生事件、不触审批、
  不执行任何动作。
- memory key 里不用任何路径分隔符（Windows 兼容：
  ``zn-diary:`` + ISO 日期，无反斜杠无正斜杠）。

纯 stdlib + persona / autonomy_policy 模块；素材收集由调用方注入
（daemon 传工作台账收集器，测试直接传素材）。
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .autonomy_policy import AutonomyPolicyStore, may_materialize_next_task
from .persona import load_zn_persona, persona_fingerprint

_LOG = logging.getLogger(__name__)

# 全局开关环境变量：0 关闭，其他 / 未设置开启。
ENABLED_ENV = "ZN_DIARY"

# Q12 自主权包络里的日记域。
AUTONOMY_DOMAIN = "diary.daily"

# 记忆 key 前缀 + ISO 日期（无路径分隔符，Windows 安全）。
DIARY_KEY_PREFIX = "zn-diary:"
# 显式查询别名：recall("日记") / recall("diary") 可命中。
DIARY_ALIASES = ("zn-diary", "diary", "日记")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 素材 kind。
KIND_WORK_DONE = "work_done"
KIND_WORK_ACTIVE = "work_active"
KIND_INTERACTION = "interaction"
KIND_NOTE = "note"

_MAX_ITEMS = 10
_MAX_TEXT_CHARS = 80

# 正文模板：常量，漂移锁定测试覆盖；改动模板必须同步更新测试常量。
_HEADER = "【ZN 日记 · {date}】"
_SECTION_WORK = "今天的工作："
_SECTION_INTERACTION = "互动："
_LINE_WORK_DONE = "- 「{text}」做完了"
_LINE_WORK_ACTIVE = "- 「{text}」还在进行"
_LINE_BULLET = "- {text}"
_EMPTY_DAY = "今天没什么大事，平静的一天。"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


@dataclass(frozen=True, slots=True)
class DiaryConfig:
    """日记开关配置：环境变量 > 默认值。"""

    enabled: bool = True

    @classmethod
    def from_env(cls) -> "DiaryConfig":
        return cls(enabled=_env_flag(ENABLED_ENV, True))


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    """一条已落盘（或已存在）的日记：纯展示内容，无执行能力。"""

    date: str
    key: str
    text: str
    item_count: int
    persona_fingerprint: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "key": self.key,
            "text": self.text,
            "item_count": self.item_count,
            "persona_fingerprint": self.persona_fingerprint,
            "created_at": self.created_at,
        }


def _shorten(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) > _MAX_TEXT_CHARS:
        cleaned = cleaned[:_MAX_TEXT_CHARS] + "…"
    return cleaned


def compose_diary(items: Any, date_str: str) -> str:
    """按模板把当日素材拼成日记正文（确定性）。

    ``items``: 每项 ``{"kind": ..., "text": ...}``；未知 kind 按备注处理。
    同一素材 + 同一日期 → 逐字节相同的正文。
    """
    normalized: list[dict[str, str]] = []
    for raw in items or ():
        if not isinstance(raw, dict):
            continue
        text = _shorten(raw.get("text"))
        if not text:
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in (KIND_WORK_DONE, KIND_WORK_ACTIVE, KIND_INTERACTION, KIND_NOTE):
            kind = KIND_NOTE
        normalized.append({"kind": kind, "text": text})
        if len(normalized) >= _MAX_ITEMS:
            break

    lines = [_HEADER.format(date=date_str)]
    work = [it for it in normalized if it["kind"] in (KIND_WORK_DONE, KIND_WORK_ACTIVE)]
    interactions = [it for it in normalized if it["kind"] == KIND_INTERACTION]
    notes = [it for it in normalized if it["kind"] == KIND_NOTE]
    if work:
        lines.append(_SECTION_WORK)
        for it in work:
            template = _LINE_WORK_DONE if it["kind"] == KIND_WORK_DONE else _LINE_WORK_ACTIVE
            lines.append(template.format(text=it["text"]))
    if interactions:
        lines.append(_SECTION_INTERACTION)
        lines.extend(_LINE_BULLET.format(text=it["text"]) for it in interactions)
    for it in notes:
        lines.append(_LINE_BULLET.format(text=it["text"]))
    if not normalized:
        lines.append(_EMPTY_DAY)
    return "\n".join(lines)


class DiaryEngine:
    """每日日记引擎。

    ``day_items``: 素材收集器 ``(local_date_str) -> list[dict]``，由调用方
    注入（daemon 传工作台账收集器）；``persona_dir`` 传给
    ``load_zn_persona``（None 时按默认顺序解析）。
    引擎本身无状态：是否已写当天日记以记忆为准，重启后语义不变。
    """

    def __init__(
        self,
        resident,
        config: DiaryConfig | None = None,
        persona_dir: str | Path | None = None,
        day_items: Callable[[str], list[dict[str, Any]]] | None = None,
    ):
        self.resident = resident
        self.config = config or DiaryConfig.from_env()
        self.persona_dir = persona_dir
        self.day_items = day_items
        self._autonomy_store: AutonomyPolicyStore | None = None

    def maybe_write(
        self,
        *,
        now: datetime | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> DiaryEntry | None:
        """评估并写入当日日记（每天最多一次）。

        返回 None 表示"本次不写"（开关关 / 自主权包络拦下）。
        即使当天无素材也会写一条"平静的一天"（日记的语义就是每天
        一条）；同日重复调用返回已存在的条目，不重写。
        除既有 remember 记忆写入外无任何副作用。
        """
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if not self.config.enabled:
            return None
        local = self._local_time(current)
        date_str = local.date().isoformat()
        if not self._autonomy_allows():
            return None
        existing = self._existing_entry(date_str)
        if existing is not None:
            return existing
        collected = list(items) if items is not None else self._collect(date_str)
        persona = load_zn_persona(self.persona_dir)
        text = compose_diary(collected, date_str)
        key = DIARY_KEY_PREFIX + date_str
        # 既有记忆写入路径（与 daemon remember RPC 同一入口）：
        # CM-3 隐私 choke 在 remember 内部生效，可 forget、可回溯。
        self.resident.memory.remember(key, text, aliases=DIARY_ALIASES)
        return DiaryEntry(
            date=date_str,
            key=key,
            text=text,
            item_count=self._bullet_count(text),
            persona_fingerprint=persona_fingerprint(persona),
            created_at=current.isoformat(),
        )

    def get_entry(self, date_str: str) -> DiaryEntry | None:
        """按日期取一条日记（显式回顾）。日期须为 YYYY-MM-DD。"""
        normalized = str(date_str or "").strip()
        if not _DATE_RE.match(normalized):
            raise ValueError("diary date must be YYYY-MM-DD")
        return self._existing_entry(normalized)

    def list_entries(self, limit: int = 30) -> list[DiaryEntry]:
        """列出日记（按日期倒序，只读）。"""
        bounded = max(1, min(100, int(limit)))
        entries: list[DiaryEntry] = []
        try:
            facts = self.resident.memory.store.list_facts()
        except Exception:
            _LOG.debug("memory facts unreadable; diary list empty", exc_info=True)
            return []
        for fact in facts:
            key = str(fact.get("key") or "")
            if not key.startswith(DIARY_KEY_PREFIX):
                continue
            date_str = key[len(DIARY_KEY_PREFIX):]
            if not _DATE_RE.match(date_str):
                continue
            entries.append(self._entry_from(key, fact.get("value"), date_str))
        entries.sort(key=lambda entry: entry.date, reverse=True)
        return entries[:bounded]

    def _collect(self, date_str: str) -> list[dict[str, Any]]:
        if self.day_items is None:
            return []
        try:
            collected = self.day_items(date_str)
        except Exception:
            _LOG.debug("day-items collector failed; writing empty diary", exc_info=True)
            return []
        return list(collected or [])

    def _existing_entry(self, date_str: str) -> DiaryEntry | None:
        try:
            match = self.resident.memory.recall(DIARY_KEY_PREFIX + date_str)
        except Exception:
            _LOG.debug("memory recall failed; treating diary as unwritten", exc_info=True)
            return None
        if match is None:
            return None
        return self._entry_from(match.key, match.value, date_str)

    def _entry_from(self, key: str, value: Any, date_str: str) -> DiaryEntry:
        text = str(value) if value is not None else ""
        persona = load_zn_persona(self.persona_dir)
        return DiaryEntry(
            date=date_str,
            key=key,
            text=text,
            item_count=self._bullet_count(text),
            persona_fingerprint=persona_fingerprint(persona),
            created_at="",
        )

    @staticmethod
    def _bullet_count(text: str) -> int:
        return sum(1 for line in text.splitlines() if line.startswith("- "))

    @staticmethod
    def _local_time(current: datetime) -> datetime:
        """用户本地时间：调用方传入的 now 若带 tzinfo 则以其时区为准，
        否则用系统本地时区（ZN 住在用户电脑上）。"""
        if current.tzinfo is not None:
            return current.astimezone(current.tzinfo)
        return current.astimezone()

    def _autonomy_allows(self) -> bool:
        """Q12 自主权包络在日记域上的应用。

        只有 ``observe_only`` 拦下写入（唯一表示"绝不自主产出"的层级）；
        其他层级（含 fail closed 的 ``require_approval``）都允许——日记
        是写进 ZN 自己记忆的可逆记录（既有 remember 路径、CM-3 choke、
        可 forget），不是 #498 审批卡管辖的外部副作用。层级比较语义
        复用 ``autonomy_policy.may_materialize_next_task``。
        包络存储本身不可用时 fail closed：不写。
        """
        try:
            if self._autonomy_store is None:
                self._autonomy_store = AutonomyPolicyStore(self.resident)
            level = self._autonomy_store.get_level(AUTONOMY_DOMAIN)
        except Exception:
            _LOG.warning(
                "autonomy policy unreadable; diary write blocked (fail closed)",
                exc_info=True,
            )
            return False
        return may_materialize_next_task(level)

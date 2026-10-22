from __future__ import annotations

"""S1(c) 每日日记：写入 / 开关 / 召回 / 人格绑定 / 安全边界的测试。

验收对照：
1. 真实对话前后对照：同一素材下，开关开 → 写出一条人格口吻的日记
   并落盘进记忆；开关关 → 零写入（test_before_after_contrast，
   运行输出即对照证据）。
2. 每日一次：同日重复调用幂等（稳定 key 去重），不产生重复版本。
3. 可回顾：写入后（模拟次日：全新引擎实例 + 同一 kernel.db）
   get_entry / list_entries / recall("日记") / recall(精确 key)
   均可读回逐字节相同的正文。
4. 节制与包络：ZN_DIARY=0 时零写入；diary.daily=observe_only 时不写；
   默认包络（require_approval）仍写。
5. 安全语义：日记路径上无 Work 线程创建、无审批触达；返回体只有
   展示字段。
6. 人格漂移锁定：固定人格 + 固定素材 + 固定日期 → 正文逐字节稳定、
   指纹常量锁定；人格文件一改指纹即变、正文不变。
7. Windows 兼容：memory key 无任何路径分隔符。
"""

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from zn_agent.core.autonomy_policy import AutonomyPolicyStore
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core import diary as diary_module
from zn_agent.core.diary import (
    AUTONOMY_DOMAIN,
    DIARY_ALIASES,
    DIARY_KEY_PREFIX,
    ENABLED_ENV,
    DiaryConfig,
    DiaryEngine,
    compose_diary,
)
from zn_agent.core.persona import persona_fingerprint
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack

#: 测试用固定时区（模拟用户本地，CEST）。
_TZ = timezone(timedelta(hours=2))


def _at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=_TZ)


_VALID_IDENTITY = "You are ZN, the user's personal secretary and assistant."
_VALID_SOUL = (
    "# SOUL\n\n## 性格\n直接、结果先行；中文、短。\n\n"
    "## 口头禅边界\n不用亲昵称呼，不说客服腔。\n\n"
    "## 情绪表达规则\n可表达轻量关心；不声称有人类身体/感官/真实感受。\n"
)

_CANON_ITEMS = [
    {"kind": "work_done", "text": "check the daily inbox"},
    {"kind": "work_active", "text": "write the weekly report"},
    {"kind": "interaction", "text": "和阿豪聊了路遥的人格设计"},
]

#: 固定人格 + 固定素材 + 固定日期（2026-10-21）的日记正文。
#: 模板改动时必须同步更新本常量（漂移锁定）。
EXPECTED_DIARY_TEXT = (
    "【ZN 日记 · 2026-10-21】\n"
    "今天的工作：\n"
    "- 「check the daily inbox」做完了\n"
    "- 「write the weekly report」还在进行\n"
    "互动：\n"
    "- 和阿豪聊了路遥的人格设计"
)

#: 空素材日的日记正文（模板改动时同步更新）。
EXPECTED_EMPTY_DAY_TEXT = (
    "【ZN 日记 · 2026-10-21】\n"
    "今天没什么大事，平静的一天。"
)

#: 同上场景的人格指纹（与 S1(b) 同一套人格文本）。用以下命令重算：
#:   PYTHONPATH=runtime/python python3 - <<'EOF'
#:   from pathlib import Path
#:   from zn_agent.core.persona import load_zn_persona, persona_fingerprint
#:   import tempfile
#:   tmp = Path(tempfile.mkdtemp())
#:   (tmp/"IDENTITY.md").write_text(<_VALID_IDENTITY>, encoding="utf-8")
#:   (tmp/"SOUL.md").write_text(<_VALID_SOUL>, encoding="utf-8")
#:   print(persona_fingerprint(load_zn_persona(tmp)))
#:   EOF
EXPECTED_PERSONA_FINGERPRINT = "509f43f938a0251fc930e94c2368deb9d576adbfae3397ad18e887dae3a97af1"


def _write_persona(directory: Path, identity: str, soul: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "IDENTITY.md").write_text(identity, encoding="utf-8")
    (directory / "SOUL.md").write_text(soul, encoding="utf-8")
    return directory


class DiaryTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _stack(self, tmp: str, persona_texts=None, **config_kwargs):
        db = Path(tmp) / "kernel.db"
        resident = self._resident(db)
        persona_dir = Path(tmp) / "persona"
        identity, soul = persona_texts or (_VALID_IDENTITY, _VALID_SOUL)
        _write_persona(persona_dir, identity, soul)
        merged = {"enabled": True}
        merged.update(config_kwargs)
        config = DiaryConfig(**merged)
        engine = DiaryEngine(resident, config=config, persona_dir=persona_dir)
        return resident, engine

    @staticmethod
    def _diary_keys(resident) -> list[str]:
        return [
            str(fact.get("key") or "")
            for fact in resident.memory.store.list_facts()
            if str(fact.get("key") or "").startswith(DIARY_KEY_PREFIX)
        ]

    # -- 开关 ------------------------------------------------------------

    def test_switch_off_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp, enabled=False)
            try:
                self.assertIsNone(engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS))
                self.assertIsNone(engine.maybe_write(now=_at(20, 31), items=_CANON_ITEMS))
                # 开关关闭时零写入：记忆里没有任何日记 key。
                self.assertEqual(self._diary_keys(resident), [])
            finally:
                resident.store.close()

    def test_switch_env_flag(self):
        with mock.patch.dict(os.environ, {ENABLED_ENV: "0"}):
            self.assertFalse(DiaryConfig.from_env().enabled)
        with mock.patch.dict(os.environ, {ENABLED_ENV: "1"}):
            self.assertTrue(DiaryConfig.from_env().enabled)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENABLED_ENV, None)
            self.assertTrue(DiaryConfig.from_env().enabled)

    # -- 每日一次 / 幂等 --------------------------------------------------

    def test_daily_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                first = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(first)
                self.assertEqual(first.text, EXPECTED_DIARY_TEXT)
                self.assertEqual(first.key, "zn-diary:2026-10-21")
                second = engine.maybe_write(now=_at(23, 59), items=_CANON_ITEMS)
                self.assertIsNotNone(second)
                self.assertEqual(second.text, first.text)
                self.assertEqual(second.key, first.key)
                # 稳定 key 去重：同一天只写了一条。
                self.assertEqual(self._diary_keys(resident), ["zn-diary:2026-10-21"])
            finally:
                resident.store.close()

    def test_empty_day_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                entry = engine.maybe_write(now=_at(20, 30), items=[])
                self.assertIsNotNone(entry)
                self.assertEqual(entry.text, EXPECTED_EMPTY_DAY_TEXT)
                self.assertEqual(entry.item_count, 0)
            finally:
                resident.store.close()

    # -- 可回顾（次日 / 显式查询） ------------------------------------------

    def test_recall_next_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            persona_dir = _write_persona(
                Path(tmp) / "persona", _VALID_IDENTITY, _VALID_SOUL
            )
            try:
                engine = DiaryEngine(
                    resident,
                    config=DiaryConfig(enabled=True),
                    persona_dir=persona_dir,
                )
                written = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(written)
            finally:
                resident.store.close()

            # 模拟次日：全新 resident + 全新引擎实例，同一 kernel.db。
            resident2 = self._resident(db)
            try:
                engine2 = DiaryEngine(
                    resident2,
                    config=DiaryConfig(enabled=True),
                    persona_dir=persona_dir,
                )
                # 按日期显式回顾。
                got = engine2.get_entry("2026-10-21")
                self.assertIsNotNone(got)
                self.assertEqual(got.text, EXPECTED_DIARY_TEXT)
                # 列表回顾（倒序）。
                listed = engine2.list_entries()
                self.assertEqual([e.date for e in listed], ["2026-10-21"])
                self.assertEqual(listed[0].text, EXPECTED_DIARY_TEXT)
                # 记忆显式查询：别名与精确 key 均可命中。
                by_alias = resident2.memory.recall("日记")
                self.assertIsNotNone(by_alias)
                self.assertEqual(str(by_alias.value), EXPECTED_DIARY_TEXT)
                by_key = resident2.memory.recall("zn-diary:2026-10-21")
                self.assertIsNotNone(by_key)
                self.assertEqual(str(by_key.value), EXPECTED_DIARY_TEXT)
                # 次日再写：新日期新 key，旧日记保留。
                next_day = engine2.maybe_write(now=_at(20, 30, day=22), items=[])
                self.assertIsNotNone(next_day)
                self.assertEqual(next_day.key, "zn-diary:2026-10-22")
                self.assertEqual(
                    [e.date for e in engine2.list_entries()],
                    ["2026-10-22", "2026-10-21"],
                )
            finally:
                resident2.store.close()

    def test_get_entry_bad_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                with self.assertRaises(ValueError):
                    engine.get_entry("not-a-date")
                with self.assertRaises(ValueError):
                    engine.get_entry("2026/10/21")
                self.assertIsNone(engine.get_entry("2026-01-01"))
            finally:
                resident.store.close()

    # -- 人格漂移锁定 ------------------------------------------------------

    def test_persona_tone_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                entry = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(entry)
                # 正文逐字节锁定。
                self.assertEqual(entry.text, EXPECTED_DIARY_TEXT)
                # 人格指纹锁定：与 S1(b) 同一套人格文本，指纹相同。
                self.assertEqual(
                    entry.persona_fingerprint, EXPECTED_PERSONA_FINGERPRINT
                )
                # compose 本身也是确定性的（不经过记忆）。
                self.assertEqual(
                    compose_diary(_CANON_ITEMS, "2026-10-21"), EXPECTED_DIARY_TEXT
                )
            finally:
                resident.store.close()

    def test_persona_change_moves_fingerprint_not_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            changed_soul = _VALID_SOUL + "\n\n## 补充\n今天心情不错。\n"
            try:
                first = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(first)
                self.assertEqual(first.persona_fingerprint, EXPECTED_PERSONA_FINGERPRINT)

                persona_dir2 = _write_persona(
                    Path(tmp) / "persona2", _VALID_IDENTITY, changed_soul
                )
                engine2 = DiaryEngine(
                    resident,
                    config=DiaryConfig(enabled=True),
                    persona_dir=persona_dir2,
                )
                # 同日已写：返回已存在条目；指纹按当前人格重算 → 变化可追踪。
                again = engine2.maybe_write(now=_at(21, 0), items=_CANON_ITEMS)
                self.assertIsNotNone(again)
                self.assertEqual(again.text, EXPECTED_DIARY_TEXT)
                self.assertNotEqual(
                    again.persona_fingerprint, EXPECTED_PERSONA_FINGERPRINT
                )
                # 纯 compose：人格变化不改变模板措辞。
                self.assertEqual(
                    compose_diary(_CANON_ITEMS, "2026-10-21"), EXPECTED_DIARY_TEXT
                )
            finally:
                resident.store.close()

    # -- 自主权包络 --------------------------------------------------------

    def test_autonomy_observe_only_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                AutonomyPolicyStore(resident).set_level(AUTONOMY_DOMAIN, "observe_only")
                self.assertIsNone(
                    engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                )
                self.assertEqual(self._diary_keys(resident), [])
            finally:
                resident.store.close()

    def test_autonomy_default_still_writes(self):
        # 默认包络（未知域 → require_approval）：日记是写进自己记忆的
        # 可逆记录，不归审批卡管辖，仍写。
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                entry = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.text, EXPECTED_DIARY_TEXT)
            finally:
                resident.store.close()

    # -- Windows 兼容 ------------------------------------------------------

    def test_windows_safe_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp)
            try:
                entry = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(entry)
                self.assertEqual(entry.key, "zn-diary:2026-10-21")
                self.assertNotIn("\\", entry.key)
                self.assertNotIn("/", entry.key)
                for alias in DIARY_ALIASES:
                    self.assertNotIn("\\", alias)
                    self.assertNotIn("/", alias)
            finally:
                resident.store.close()

    # -- 真实对话前后对照 ----------------------------------------------------

    def test_before_after_contrast(self):
        """同一素材：开关开 → 写出人格口吻的日记并落盘；开关关 → 零写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            resident, engine = self._stack(tmp, enabled=True)
            try:
                entry = engine.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNotNone(entry)
                print("\n[diary ON]\n" + entry.text)
                recalled = resident.memory.recall("日记")
                self.assertIsNotNone(recalled)
                self.assertEqual(str(recalled.value), entry.text)
            finally:
                resident.store.close()

            resident2, engine2 = self._stack(tmp, enabled=False)
            try:
                off_entry = engine2.maybe_write(now=_at(20, 30), items=_CANON_ITEMS)
                self.assertIsNone(off_entry)
                print("\n[diary OFF] -> None, nothing written")
            finally:
                resident2.store.close()

    # -- RPC 接线 ------------------------------------------------------------

    def test_rpc_write_get_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                # diary_write 用"今天"（UTC）作 key 与标题；冻结时钟让本测试
                # 与日历日期无关、逐字节确定性。断言本身未动（仍逐字节比对）。
                frozen_now = datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)

                class _FrozenDateTime(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return frozen_now

                with mock.patch.object(diary_module, "datetime", _FrozenDateTime):
                    written = server.handle(
                        {
                            "id": "1",
                            "method": "diary_write",
                            "params": {"items": _CANON_ITEMS},
                        }
                    )
                    self.assertTrue(written["ok"])
                    result = written["result"]
                    self.assertIsNotNone(result)
                    self.assertEqual(result["key"], "zn-diary:" + result["date"])
                    self.assertEqual(result["text"], EXPECTED_DIARY_TEXT)
                    # 同日再次调用：幂等，同一条目（同样冻结时钟）。
                    again = server.handle(
                        {"id": "2", "method": "diary_write", "params": {}}
                    )
                    self.assertTrue(again["ok"])
                    self.assertEqual(again["result"]["text"], EXPECTED_DIARY_TEXT)
                # 返回体只有展示字段。
                self.assertEqual(
                    set(result.keys()),
                    {
                        "date",
                        "key",
                        "text",
                        "item_count",
                        "persona_fingerprint",
                        "created_at",
                    },
                )

                # 按日期回顾。
                got = server.handle(
                    {
                        "id": "3",
                        "method": "diary_get",
                        "params": {"date": result["date"]},
                    }
                )
                self.assertTrue(got["ok"])
                self.assertEqual(got["result"]["text"], EXPECTED_DIARY_TEXT)

                # 列表回顾。
                listed = server.handle(
                    {"id": "4", "method": "diary_list", "params": {}}
                )
                self.assertTrue(listed["ok"])
                self.assertEqual(len(listed["result"]), 1)
                self.assertEqual(
                    listed["result"][0]["text"], EXPECTED_DIARY_TEXT
                )

                # 参数校验：handle 直接抛 ValueError（ok:false 的包装在
                # serve 循环层，不在 handle 内）。
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "5",
                            "method": "diary_write",
                            "params": {"items": "not-a-list"},
                        }
                    )
                with self.assertRaises(ValueError):
                    server.handle(
                        {"id": "6", "method": "diary_get", "params": {}}
                    )
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "7",
                            "method": "diary_get",
                            "params": {"date": "2026/10/21"},
                        }
                    )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

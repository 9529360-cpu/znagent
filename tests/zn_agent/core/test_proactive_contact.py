from __future__ import annotations

"""S1(b) 有节制的主动联系：节制规则 / 人格绑定 / 安全边界的测试。

验收对照：
1. 真实对话前后对照：同一场景（到期的例行任务）下，开关开 →
   输出一句人格口吻的问候；开关关 → 零输出（test_before_after_contrast，
   运行输出即对照证据）。
2. 节制规则锁定：超频抑制、夜间免打扰、拒绝/忽略后 7 天抑制、开关
   关闭后零主动联系（含零记账写入）。
3. 安全语义：主动联系路径上无 Work 线程、无事件、无审批触达；
   返回体只有展示字段，动作为只读路由。
4. 人格漂移锁定：固定人格 + 固定触发 → 问候逐字节稳定、指纹常量锁定；
   人格文件一改指纹即变。
"""

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.persona import load_zn_persona, persona_fingerprint
from zn_agent.core.proactive_contact import (
    MAX_PER_DAY_ENV,
    QUIET_END_ENV,
    QUIET_START_ENV,
    ENABLED_ENV,
    ProactiveContactConfig,
    ProactiveContactEngine,
    SUPPRESSION_TTL,
    compose_greeting,
)
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.suggestions import SuggestionEngine
from zn_agent.core.suggestions import _DISMISSAL_TTL
from zn_agent.core.work import ResidentWorkLedger

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

#: 固定人格 + 固定触发（recurring_due / "check the daily inbox"）的问候。
#: 模板改动时必须同步更新本常量（漂移锁定）。
EXPECTED_GREETING = "提醒你一下：「check the daily inbox」到点了，要我现在开始吗？"

#: 同上场景的人格指纹。用以下命令重算：
#:   PYTHONPATH=runtime/python python - <<'EOF'
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


class ProactiveContactTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _stack(self, tmp: str, persona_texts=None, **config_kwargs):
        db = Path(tmp) / "kernel.db"
        resident = self._resident(db)
        ledger = ResidentWorkLedger(resident)
        suggestions = SuggestionEngine(resident, ledger)
        persona_dir = Path(tmp) / "persona"
        identity, soul = persona_texts or (_VALID_IDENTITY, _VALID_SOUL)
        _write_persona(persona_dir, identity, soul)
        merged = {"enabled": True}
        merged.update(config_kwargs)
        config = ProactiveContactConfig(**merged)
        engine = ProactiveContactEngine(
            resident, suggestions, config=config, persona_dir=persona_dir
        )
        return resident, ledger, suggestions, engine

    def _due_recurring(self, resident, task="check the daily inbox"):
        now = datetime.now(timezone.utc)
        resident.schedule_recurring_intention(
            "daily check",
            task=task,
            interval_seconds=3600,
            source="user",
            first_due_at=now - timedelta(minutes=5),
        )

    # -- 开关 ------------------------------------------------------------

    def test_switch_off_yields_zero_contact_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(
                tmp, enabled=False, max_per_day=5
            )
            self._due_recurring(resident)
            self.assertIsNone(engine.maybe_contact(now=_at(9, 30)))
            self.assertIsNone(engine.maybe_contact(now=_at(9, 31)))
            # 开关关闭时连记账表都不写：suppressions / log 保持不存在。
            with engine._connect() as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertNotIn("resident_proactive_contact_suppressions", tables)
            self.assertNotIn("resident_proactive_contact_log", tables)
            resident.store.close()

    def test_env_switch_off_disables(self):
        with mock.patch.dict(os.environ, {ENABLED_ENV: "0"}):
            self.assertFalse(ProactiveContactConfig.from_env().enabled)
        with mock.patch.dict(os.environ, {ENABLED_ENV: "1"}):
            self.assertTrue(ProactiveContactConfig.from_env().enabled)
        with mock.patch.dict(
            os.environ,
            {MAX_PER_DAY_ENV: "5", QUIET_START_ENV: "23", QUIET_END_ENV: "6"},
        ):
            config = ProactiveContactConfig.from_env()
            self.assertEqual(config.max_per_day, 5)
            self.assertEqual(config.quiet_start, 23)
            self.assertEqual(config.quiet_end, 6)
        # 默认值：开 / 每天 2 次 / 22:00–07:00 免打扰。
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in (ENABLED_ENV, MAX_PER_DAY_ENV, QUIET_START_ENV, QUIET_END_ENV):
                os.environ.pop(key, None)
            config = ProactiveContactConfig.from_env()
            self.assertTrue(config.enabled)
            self.assertEqual(config.max_per_day, 2)
            self.assertEqual((config.quiet_start, config.quiet_end), (22, 7))

    # -- 频率上限 ----------------------------------------------------------

    def test_rate_cap_suppresses_beyond_daily_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=1)
            self._due_recurring(resident, task="first thing")
            resident.memory.remember("routine:stretch", "stand up and stretch")
            first = engine.maybe_contact(now=_at(9, 30))
            self.assertIsNotNone(first)
            # 同一天第二次：即使还有候选也不打扰。
            self.assertIsNone(engine.maybe_contact(now=_at(10, 30)))
            resident.store.close()

    def test_daily_cap_resets_next_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=1)
            self._due_recurring(resident)
            self.assertIsNotNone(engine.maybe_contact(now=_at(9, 30, day=21)))
            self.assertIsNone(engine.maybe_contact(now=_at(18, 0, day=21)))
            # 第二天额度恢复。
            self.assertIsNotNone(engine.maybe_contact(now=_at(9, 30, day=22)))
            resident.store.close()

    # -- 夜间免打扰 ----------------------------------------------------------

    def test_quiet_hours_suppress_at_night(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            self.assertIsNone(engine.maybe_contact(now=_at(23, 30)))
            self.assertIsNone(engine.maybe_contact(now=_at(3, 0)))
            self.assertIsNone(engine.maybe_contact(now=_at(6, 59)))
            # 白天正常联系。
            contact = engine.maybe_contact(now=_at(9, 0))
            self.assertIsNotNone(contact)
            assert contact is not None
            self.assertEqual(contact.kind, "recurring_due")
            resident.store.close()

    # -- 拒绝 / 忽略后抑制 ----------------------------------------------------

    def test_suppression_ttl_matches_suggestions_dismissal_semantics(self):
        # "复用 P1-1 拒绝后 7 天不重复推语义" 的锁定：两处 TTL 必须相等。
        self.assertEqual(SUPPRESSION_TTL, _DISMISSAL_TTL)
        self.assertEqual(SUPPRESSION_TTL, timedelta(days=7))

    def test_dismissed_suggestion_never_becomes_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, suggestions, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            key = suggestions.list_suggestions()[0]["key"]
            suggestions.dismiss(key)
            # 建议栏里拒绝过的 key，不会变成主动联系。
            self.assertIsNone(engine.maybe_contact(now=_at(9, 30)))
            resident.store.close()

    def test_ignored_contact_suppressed_for_seven_days_then_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            base = _at(9, 30)
            contact = engine.maybe_contact(now=base)
            self.assertIsNotNone(contact)
            assert contact is not None
            engine.note_feedback(contact.key, "ignored", now=base)
            # 忽略后 7 天内不再推同一 key。
            self.assertIsNone(engine.maybe_contact(now=base + timedelta(days=6)))
            # 7 天窗口过后可再次联系。
            later = engine.maybe_contact(now=base + timedelta(days=8))
            self.assertIsNotNone(later)
            assert later is not None
            self.assertEqual(later.key, contact.key)
            resident.store.close()

    def test_rejected_feedback_suppresses_and_accepted_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            base = _at(9, 30)
            contact = engine.maybe_contact(now=base)
            assert contact is not None
            dismissed = engine.note_feedback(contact.key, "dismissed", now=base)
            self.assertTrue(dismissed["suppressed"])
            self.assertIsNone(engine.maybe_contact(now=base + timedelta(hours=1)))
            # 用户后来接了话 → 解除抑制。
            cleared = engine.note_feedback(contact.key, "accepted", now=base)
            self.assertFalse(cleared["suppressed"])
            self.assertIsNotNone(
                engine.maybe_contact(now=base + timedelta(hours=2))
            )
            resident.store.close()

    def test_invalid_feedback_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _resident, _ledger, _sug, engine = self._stack(tmp)
            with self.assertRaises(ValueError):
                engine.note_feedback("sug-abc", "maybe-later")
            with self.assertRaises(ValueError):
                engine.note_feedback("", "ignored")
            _resident.store.close()

    # -- 安全边界：无副作用 ----------------------------------------------------

    def test_contact_path_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            threads_before = len(ledger.list_snapshots(thread_limit=24))
            events_before = len(resident.store.list_events(limit=1000))
            contact = engine.maybe_contact(now=_at(9, 30))
            self.assertIsNotNone(contact)
            assert contact is not None
            # 不创建 Work 线程、不产生事件。
            self.assertEqual(len(ledger.list_snapshots(thread_limit=24)), threads_before)
            self.assertEqual(len(resident.store.list_events(limit=1000)), events_before)
            # 返回体只有展示字段：无可调用对象，动作为只读路由。
            payload = contact.to_dict()
            for value in payload.values():
                self.assertFalse(callable(value), f"callable leaked: {value!r}")
            self.assertEqual(payload["action"], "open_suggestion")
            self.assertNotIn("execute", payload)
            self.assertNotIn("approval", payload)
            resident.store.close()

    # -- 人格绑定 / 漂移锁定 --------------------------------------------------

    def test_greeting_is_deterministic_and_persona_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            contact = engine.maybe_contact(now=_at(9, 30))
            assert contact is not None
            # 问候语逐字节锁定（模板常量）。
            self.assertEqual(contact.message, EXPECTED_GREETING)
            # 人格指纹锁定：随船/固定人格文件渲染的指纹。
            self.assertEqual(
                contact.persona_fingerprint, EXPECTED_PERSONA_FINGERPRINT
            )
            # 同一状态再次评估 → 同一问候。
            resident2 = self._resident(Path(tmp) / "kernel.db")
            ledger2 = ResidentWorkLedger(resident2)
            engine2 = ProactiveContactEngine(
                resident2,
                SuggestionEngine(resident2, ledger2),
                config=ProactiveContactConfig(enabled=True, max_per_day=5),
                persona_dir=Path(tmp) / "persona",
            )
            again = engine2.maybe_contact(now=_at(9, 30, day=22))
            assert again is not None
            self.assertEqual(again.message, contact.message)
            self.assertEqual(again.persona_fingerprint, contact.persona_fingerprint)
            resident.store.close()
            resident2.store.close()

    def test_persona_change_shifts_fingerprint_not_greeting(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, _sug, engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            before = engine.maybe_contact(now=_at(9, 30))
            assert before is not None
            # 改 SOUL.md 措辞（仍满足三节要求）：指纹变，问候模板不变。
            altered_soul = _VALID_SOUL.replace("直接、结果先行", "温和、结果先行")
            _write_persona(Path(tmp) / "persona", _VALID_IDENTITY, altered_soul)
            after = engine.maybe_contact(now=_at(9, 30, day=22))
            assert after is not None
            self.assertNotEqual(after.persona_fingerprint, before.persona_fingerprint)
            self.assertEqual(after.message, before.message)
            self.assertEqual(
                after.persona_fingerprint,
                persona_fingerprint(load_zn_persona(Path(tmp) / "persona")),
            )
            resident.store.close()

    def test_greeting_templates_cover_all_kinds(self):
        cases = {
            "recurring_due": "提醒你一下：「做功课」到点了，要我现在开始吗？",
            "recurring_upcoming": "「做功课」快到点了，要我帮你准备吗？",
            "failed_work": "上次「做功课」没跑完，要我继续吗？",
            "interrupted_work": "你刚才提到「做功课」，我还没回你——现在继续？",
            "autonomy_gated": "有个到点的事项「做功课」之前被我拦下了，要看看吗？",
            "routine": "「做功课」——今天要安排吗？",
        }
        for kind, expected in cases.items():
            self.assertEqual(compose_greeting(kind, "做功课"), expected)
        # 未知 kind 走兜底模板，不抛异常。
        self.assertIn("做功课", compose_greeting("mystery", "做功课"))

    # -- 真实对话前后对照 ------------------------------------------------------

    def test_before_after_contrast(self):
        """同一场景：开主动联系 vs 关主动联系的输出对照（证据）。"""
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, suggestions, _engine = self._stack(tmp, max_per_day=5)
            self._due_recurring(resident)
            persona_dir = Path(tmp) / "persona"

            on_engine = ProactiveContactEngine(
                resident,
                suggestions,
                config=ProactiveContactConfig(enabled=True, max_per_day=5),
                persona_dir=persona_dir,
            )
            off_engine = ProactiveContactEngine(
                resident,
                suggestions,
                config=ProactiveContactConfig(enabled=False, max_per_day=5),
                persona_dir=persona_dir,
            )
            on_contact = on_engine.maybe_contact(now=_at(9, 30))
            off_contact = off_engine.maybe_contact(now=_at(9, 30))

            print("\n[对照] 开关 ON  时输出：", on_contact.message if on_contact else None)
            print("[对照] 开关 OFF 时输出：", off_contact)
            self.assertIsNotNone(on_contact)
            assert on_contact is not None
            self.assertEqual(on_contact.message, EXPECTED_GREETING)
            self.assertIsNone(off_contact)
            resident.store.close()

    # -- RPC 接线 --------------------------------------------------------------

    def test_rpc_check_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                # 测试确定性：关掉夜间免打扰（真实 now 可能落在夜间）。
                server.proactive_contact.config = ProactiveContactConfig(
                    enabled=True, max_per_day=5, quiet_start=0, quiet_end=0
                )
                resident.schedule_recurring_intention(
                    "daily check",
                    task="check the daily inbox",
                    interval_seconds=3600,
                    source="user",
                    first_due_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                )
                checked = server.handle(
                    {"id": "1", "method": "proactive_contact_check", "params": {}}
                )
                self.assertTrue(checked["ok"])
                self.assertIsNotNone(checked["result"])
                self.assertEqual(checked["result"]["kind"], "recurring_due")
                self.assertEqual(checked["result"]["action"], "open_suggestion")
                key = checked["result"]["key"]

                feedback = server.handle(
                    {
                        "id": "2",
                        "method": "proactive_contact_feedback",
                        "params": {"key": key, "feedback": "ignored"},
                    }
                )
                self.assertTrue(feedback["ok"])
                self.assertTrue(feedback["result"]["suppressed"])

                checked_again = server.handle(
                    {"id": "3", "method": "proactive_contact_check", "params": {}}
                )
                self.assertTrue(checked_again["ok"])
                self.assertIsNone(checked_again["result"])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

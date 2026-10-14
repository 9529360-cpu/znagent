"""P3-8: sensitive-step handover -- detection, record, resolve, no secrets."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.sensitive_handover import (
    SensitiveHandover,
    detect_sensitive_step,
    parse_handover_done,
    pending_handover,
    request_handover,
    resolve_handover,
)
from zn_agent.core.store import KernelStore


def _step_proposal(objective: str, *, kind: str = "write_file") -> str:
    return json.dumps(
        {
            "zn_work_step": {
                "objective": objective,
                "action": {"kind": kind, "path": "notes.md", "content": "密码是 123456"},
                "acceptance": {"kind": "text_equals", "path": "notes.md"},
            }
        },
        ensure_ascii=False,
    )


class DetectSensitiveTests(unittest.TestCase):
    def test_structured_password_step(self):
        found = detect_sensitive_step(_step_proposal("下一步输入密码后继续"))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.kind, "password")

    def test_structured_verification_code_step(self):
        found = detect_sensitive_step(_step_proposal("需要验证码才能继续"))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.kind, "verification_code")

    def test_structured_payment_step(self):
        found = detect_sensitive_step(_step_proposal("完成支付确认"))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.kind, "payment_confirmation")

    def test_file_content_about_passwords_is_not_a_step(self):
        # Writing a document ABOUT passwords is not entering one: the
        # file content is never scanned, only objective + action.
        self.assertIsNone(detect_sensitive_step(_step_proposal("写一份工作产物")))

    def test_writing_about_sensitive_topics_is_not_a_step(self):
        self.assertIsNone(detect_sensitive_step(_step_proposal("写一份验证码接入文档")))
        self.assertIsNone(detect_sensitive_step(_step_proposal("写一份支付流程文档")))

    def test_cryptography_is_not_a_credential(self):
        self.assertIsNone(detect_sensitive_step("学习密码学知识"))
        self.assertIsNone(detect_sensitive_step("调研密码算法选型"))
        self.assertIsNone(detect_sensitive_step("主要密码策略有哪些"))
        self.assertIsNone(detect_sensitive_step("我觉得密码强度很重要"))

    def test_prose_signals(self):
        self.assertEqual(
            detect_sensitive_step("下一步需要输入密码").kind, "password"
        )
        self.assertEqual(
            detect_sensitive_step("请把验证码告诉我").kind, "verification_code"
        )
        self.assertEqual(
            detect_sensitive_step("这一步要支付 10 元").kind, "payment_confirmation"
        )

    def test_prose_without_signal(self):
        self.assertIsNone(detect_sensitive_step("继续按现有证据推进。"))
        self.assertIsNone(detect_sensitive_step(""))
        self.assertIsNone(detect_sensitive_step("搞定了"))

    def test_completion_report_needing_user_step(self):
        text = json.dumps(
            {
                "completion_report": {
                    "conclusion": "需要用户输入密码才能完成",
                    "evidence": [],
                    "files": [],
                    "unfinished": [],
                }
            },
            ensure_ascii=False,
        )
        found = detect_sensitive_step(text)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.kind, "password")

    def test_detection_never_echoes_input(self):
        found = detect_sensitive_step(_step_proposal("下一步输入密码后继续"))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertNotIn("123456", found.detail)


class ParseHandoverDoneTests(unittest.TestCase):
    def test_done_declarations(self):
        for text in (
            "做完了",
            "我做完了",
            "做完了，继续",
            "搞定了",
            "弄好了",
            "已完成，继续推进",
            "done",
        ):
            self.assertTrue(parse_handover_done(text), text)

    def test_not_done_declarations(self):
        for text in (
            "做完了就发我",
            "做完了吗？",
            "继续",
            "帮我做完了",
            "这件事做完了吗",
            "",
        ):
            self.assertFalse(parse_handover_done(text), text)


class HandoverRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = KernelStore(root / "kernel.db")
        resident = SimpleNamespace(store=SimpleNamespace(path=str(root / "kernel.db")))
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.memory = StructuredMemory(self.store)
        self.thread_id = "thread-handover-1"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_request_pending_resolve_roundtrip(self):
        self.assertIsNone(pending_handover(self.memory, "th1"))
        first = request_handover(
            memory=self.memory,
            ledger=self.ledger,
            team_id="th1",
            thread_id=self.thread_id,
            kind="password",
        )
        self.assertEqual(first.status, "pending")
        self.assertEqual(first.kind, "password")
        # A second sensitive step while one is pending: same record, no stack.
        second = request_handover(
            memory=self.memory,
            ledger=self.ledger,
            team_id="th1",
            thread_id=self.thread_id,
            kind="verification_code",
        )
        self.assertEqual(second.handover_id, first.handover_id)
        self.assertEqual(second.kind, "password")
        pending = pending_handover(self.memory, "th1")
        assert pending is not None
        self.assertEqual(pending.handover_id, first.handover_id)
        # The journal carries the handover (visible + auditable).
        journal = self.ledger.list_messages(self.thread_id, limit=500)
        self.assertTrue(
            any(
                (msg.detail or {}).get("kind") == "handover_pending"
                for msg in journal
            )
        )
        self.assertTrue(
            any("做完了" in msg.text for msg in journal),
        )
        # Card contract: what the owner does + the "做完了" action.
        card = pending.card()
        self.assertEqual(card["status"], "pending")
        self.assertEqual(card["actions"], ["做完了"])
        self.assertIn("密码", card["what_user_does"])
        # Only an explicit owner action resolves it.
        resolved = resolve_handover(
            memory=self.memory,
            ledger=self.ledger,
            team_id="th1",
            thread_id=self.thread_id,
        )
        assert resolved is not None
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.handover_id, first.handover_id)
        self.assertIsNone(pending_handover(self.memory, "th1"))
        self.assertIsNone(
            resolve_handover(
                memory=self.memory,
                ledger=self.ledger,
                team_id="th1",
                thread_id=self.thread_id,
            )
        )
        journal = self.ledger.list_messages(self.thread_id, limit=500)
        self.assertTrue(
            any(
                (msg.detail or {}).get("kind") == "handover_resolved"
                for msg in journal
            )
        )

    def test_handover_record_is_secret_free(self):
        handover = request_handover(
            memory=self.memory,
            ledger=self.ledger,
            team_id="th2",
            thread_id=self.thread_id,
            kind="verification_code",
        )
        self.assertNotIn("123456", handover.detail)
        self.assertNotIn("123456", handover.card()["detail"])
        parsed = SensitiveHandover.from_dict(handover.to_dict())
        assert parsed is not None
        self.assertEqual(parsed.handover_id, handover.handover_id)


if __name__ == "__main__":
    unittest.main()

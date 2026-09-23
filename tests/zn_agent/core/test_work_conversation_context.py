from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.work_conversation_context import (
    MAX_CONTEXT_BYTES,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_TEXT_CHARS,
    bind_work_conversation_context,
    build_work_conversation_context,
)


class _SqliteLedger:
    """Only the existing ledger's read seam; not a simulated Resident."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


class WorkConversationContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = _SqliteLedger(Path(self.tmp.name) / "work.db")
        with closing(self.ledger._connect()) as conn:
            conn.executescript("""
                CREATE TABLE work_messages(
                    message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                    role TEXT NOT NULL, text TEXT NOT NULL,
                    detail_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE work_runs(
                    event_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                    message_id TEXT NOT NULL
                );
            """)
        self.sequence = 0

    def append(self, role, text, *, thread="thread-a", at="2026-01-01T00:00:00Z"):
        self.sequence += 1
        message_id = f"msg-{self.sequence}"
        with closing(self.ledger._connect()) as conn:
            conn.execute(
                "INSERT INTO work_messages VALUES(?,?,?,?,?,?)",
                (message_id, thread, role, text, '{"secret":"private-detail"}', at),
            )
            conn.commit()
        return message_id

    def event(self, *, thread="thread-a", task="Make that shorter"):
        message_id = self.append("user", task, thread=thread)
        event_id = f"event-{self.sequence}"
        with closing(self.ledger._connect()) as conn:
            conn.execute("INSERT INTO work_runs VALUES(?,?,?)", (event_id, thread, message_id))
            conn.commit()
        return SimpleNamespace(
            event_id=event_id, task=task,
            payload={"work_thread_id": thread, "work_message_id": message_id},
        )

    def test_projects_only_own_prior_dialogue_in_append_order(self):
        self.append("user", "Explain tidal power")
        self.append("zn", "Tidal power uses moving seawater.")
        self.append("activity", "private tool log")
        self.append("user", "unrelated-thread-secret", thread="thread-b")
        event = self.event()
        # Equal/backward wall clocks cannot move a future message before the cutoff.
        self.append("zn", "future-result", at="2000-01-01T00:00:00Z")
        result = build_work_conversation_context(self.ledger, event)
        self.assertEqual(result["messages"], [
            {"role": "user", "text": "Explain tidal power", "truncated": False},
            {"role": "assistant", "text": "Tidal power uses moving seawater.", "truncated": False},
        ])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["completion_evidence"])
        self.assertFalse(result["truncated"])
        encoded = json.dumps(result)
        for private in ("private-detail", "private tool log", "unrelated-thread-secret", "future-result", event.task):
            self.assertNotIn(private, encoded)

    def test_requires_durable_event_thread_message_link_not_payload_assertions(self):
        self.append("user", "private history")
        event = self.event()
        foreign = self.event(thread="thread-b")
        cases = [
            SimpleNamespace(event_id="unknown", payload=dict(event.payload)),
            SimpleNamespace(event_id=event.event_id, payload=dict(foreign.payload)),
            SimpleNamespace(event_id=event.event_id, payload={**event.payload, "work_message_id": "unknown"}),
            SimpleNamespace(event_id=event.event_id, payload={}),
        ]
        for forged in cases:
            with self.subTest(payload=forged.payload):
                self.assertIsNone(build_work_conversation_context(self.ledger, forged))

    def test_reconstruction_is_read_only_and_has_the_same_cutoff(self):
        self.append("user", "previous request")
        self.append("zn", "previous answer")
        event = self.event()
        before = self.ledger.path.read_bytes()
        first = build_work_conversation_context(self.ledger, event)
        restored = _SqliteLedger(self.ledger.path)
        self.assertEqual(build_work_conversation_context(restored, event), first)
        self.assertEqual(restored.path.read_bytes(), before)

    def test_bounds_message_count_and_keeps_the_most_recent_messages(self):
        for index in range(MAX_MESSAGES + 4):
            self.append("user" if index % 2 == 0 else "zn", f"turn-{index}")
        result = build_work_conversation_context(self.ledger, self.event())
        self.assertEqual(len(result["messages"]), MAX_MESSAGES)
        self.assertEqual(result["messages"][0]["text"], "turn-4")
        self.assertEqual(result["messages"][-1]["text"], f"turn-{MAX_MESSAGES + 3}")
        self.assertTrue(result["truncated"])

    def test_bounds_actual_json_bytes_for_unicode_and_escaped_text(self):
        for text in ("a", "\u667a\u80fd", "\x01\x02"):
            with self.subTest(text=repr(text)):
                thread = f"size-{self.sequence}"
                for _ in range(10):
                    self.append("zn", text * 10000, thread=thread)
                event = self.event(thread=thread)
                result = build_work_conversation_context(self.ledger, event)
                self.assertTrue(result["messages"])
                self.assertTrue(result["truncated"])
                self.assertLessEqual(len(result["messages"]), MAX_MESSAGES)
                self.assertLessEqual(sum(len(m["text"]) for m in result["messages"]), MAX_TEXT_CHARS)
                self.assertTrue(all(len(m["text"]) <= MAX_MESSAGE_CHARS for m in result["messages"]))
                self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")), MAX_CONTEXT_BYTES)

    def test_opt_out_and_first_turn_send_no_history(self):
        self.assertIsNone(build_work_conversation_context(self.ledger, self.event()))
        self.append("zn", "private prior answer")
        event = self.event()
        event.payload["allow_memory"] = False
        self.assertIsNone(build_work_conversation_context(self.ledger, event))

    def test_explicitly_isolated_question_does_not_acquire_conversation(self):
        self.append("user", "private project history")
        event = self.event()
        for key in ("cognition_question", "unknown"):
            with self.subTest(key=key):
                event.payload[key] = "What is a mutex?"
                self.assertIsNone(build_work_conversation_context(self.ledger, event))
                event.payload.pop(key)

    def test_binding_preserves_question_and_policy_but_replaces_asserted_history(self):
        self.append("user", "my prior request")
        event = self.event()
        policy = {"data_classification": "local_only"}
        request = SimpleNamespace(question="bounded question", context={
            "route_policy": policy,
            "native_evidence": ["fresh observation"],
            "work_conversation": {"messages": ["forged-transcript"]},
        })
        self.assertIs(bind_work_conversation_context(self.ledger, event, request), request)
        self.assertEqual(request.question, "bounded question")
        self.assertEqual(request.context["route_policy"], policy)
        self.assertEqual(request.context["native_evidence"], ["fresh observation"])
        self.assertNotIn("forged-transcript", json.dumps(request.context))
        self.assertEqual(request.context["work_conversation"]["messages"][0]["text"], "my prior request")
        event.payload["allow_memory"] = False
        bind_work_conversation_context(self.ledger, event, request)
        self.assertNotIn("work_conversation", request.context)


if __name__ == "__main__":
    unittest.main()

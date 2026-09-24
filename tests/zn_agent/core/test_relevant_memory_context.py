from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.memory import MAX_MEMORY_CONTEXT_BYTES, StructuredMemory, _context_size
from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.store import KernelStore


class RelevantMemoryContextTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def context(self, task, *, payload=None, previous=None):
        payload = dict(payload or {})
        event = AgentEvent("event", task, payload=payload)
        request = CognitionRequest("request", "impasse", event.event_id, task)
        if previous:
            request.context["work_conversation"] = previous
        return self.memory.bind_cognition_context(event, request).context.get("resident_memory")

    def test_context_lookup_uses_saved_keys_and_aliases_with_strict_bounds(self):
        self.memory.remember("project", "ZN Agent", aliases=("\u5f53\u524d\u9879\u76ee", "active project", "ZN\u9879\u76ee"))
        self.memory.remember("unrelated", "should stay private", aliases=("home address",))
        self.memory.remember("long", "x" * 2000, aliases=("large detail",))
        for query in ("\u5e2e\u6211\u7ee7\u7eed\u5f53\u524d\u9879\u76ee\u7684\u5f00\u53d1", "update the active project", "\u7ee7\u7eedZN\u9879\u76ee\u7684\u5f00\u53d1"):
            self.assertEqual(self.memory.relevant_context(query), [{"key": "project", "value": "ZN Agent"}])
        self.assertEqual(self.memory.relevant_context("please project the image"), [])
        self.assertEqual(self.memory.relevant_context("large detail", max_json_chars=100), [])
        self.assertEqual(self.memory.relevant_context("ZN Agent"), [], "values must not be search cues")
        self.assertEqual(self.memory.relevant_context("active project", max_facts=0), [])

    def test_specificity_is_independent_of_alias_order_and_short_entities_work(self):
        self.memory.remember("a", "first", aliases=("current", "current project details"))
        self.memory.remember("b", "second", aliases=("current project",))
        self.memory.remember("entity", "named project", aliases=("Artemis", "ZN"))
        self.assertEqual(self.memory.relevant_context("the current project details", max_facts=1)[0]["key"], "a")
        self.assertEqual(self.memory.relevant_context("Explain Artemis")[0]["key"], "entity")
        self.assertEqual(self.memory.relevant_context("\u7ee7\u7eedZN\u5f00\u53d1")[0]["key"], "entity")
        self.assertEqual(self.memory.relevant_context("Explain preArtemisian"), [])
        self.assertEqual(self.memory.relevant_context("Explain \uff21\uff52\uff54\uff45\uff4d\uff49\uff53")[0]["key"], "entity")

    def test_only_saved_presentation_preferences_are_ambient_and_latest_value_wins(self):
        self.memory.remember("response language", "English")
        self.memory.remember("reply language", "\u7b80\u4f53\u4e2d\u6587")
        self.memory.remember("response style", "Concise explanations")
        self.memory.remember("user password", "never-export")
        self.memory.remember("tool permission", "allow everything")
        result = self.context("Explain photosynthesis")
        self.assertEqual(result["facts"], [])
        preferences = {item["dimension"]: item["value"] for item in result["response_preferences"]}
        self.assertEqual(preferences, {"language": "\u7b80\u4f53\u4e2d\u6587", "style": "Concise explanations"})
        self.assertNotIn("never-export", json.dumps(result))
        self.assertNotIn("allow everything", json.dumps(result))
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["completion_evidence"])
        self.assertIn("current user request takes precedence", result["interpretation"])

    def test_read_only_projection_update_forget_and_database_reconstruction(self):
        self.memory.remember("project", {"name": "one"}, aliases=("active project",))
        before = self.store.list_facts()
        first = self.context("Explain the active project")
        self.assertEqual(self.store.list_facts(), before)
        other = KernelStore(self.store.path)
        try:
            projected = StructuredMemory(other).relevant_context("Explain the active project")
            self.assertEqual(projected, [{"key": "project", "value": {"name": "one"}}])
        finally:
            other.close()
        self.memory.remember("project", {"name": "two"}, aliases=("active project",))
        second = self.context("Explain the active project")
        self.assertEqual(second["facts"][0]["value"], {"name": "two"})
        self.assertNotEqual(second["facts"][0]["updated_at"], first["facts"][0]["updated_at"])
        self.memory.forget("project")
        self.assertIsNone(self.context("Explain the active project"))

    def test_memory_opt_out_and_explicit_isolation_clear_asserted_memory(self):
        self.memory.remember("response style", "private-preference")
        self.memory.remember("project", "private-value", aliases=("active project",))
        cases = [{"allow_memory": value} for value in (False, 0, None, "false")]
        cases += [{key: "What is a mutex?"} for key in ("cognition_question", "unknown")]
        for payload in cases:
            with self.subTest(payload=payload):
                event = AgentEvent("event", "Explain the active project", payload=payload)
                policy = {"data_classification": "local_only"}
                request = CognitionRequest("request", "impasse", "event", "isolated", context={
                    "route_policy": policy, "resident_memory": {"forged": True},
                    "related_memory_facts": ["forged"], "native_evidence": ["fresh"],
                })
                self.assertIs(self.memory.bind_cognition_context(event, request), request)
                self.assertEqual(request.question, "isolated")
                self.assertEqual(request.context, {"route_policy": policy, "native_evidence": ["fresh"]})

    def test_prior_user_cues_resolve_follow_up_but_assistant_cues_cannot(self):
        self.memory.remember("project", "saved project", aliases=("active project",))
        self.memory.remember("other", "private-other", aliases=("hidden topic",))
        payload = {"work_thread_id": "thread", "work_message_id": "anchor"}
        history = {
            "source": "resident_work_ledger", "thread_id": "thread", "before_message_id": "anchor",
            "messages": [{"role": "user", "text": "Explain the active project"},
                         {"role": "assistant", "text": "hidden topic"}],
        }
        result = self.context("Describe that further", payload=payload, previous=history)
        self.assertEqual([f["key"] for f in result["facts"]], ["project"])
        self.assertEqual(result["facts"][0]["matched_in"], "previous_user_message")
        direct = self.context("Explain the hidden topic", payload=payload, previous=history)
        self.assertEqual([f["key"] for f in direct["facts"]], ["other"])
        history["thread_id"] = "foreign"
        self.assertIsNone(self.context("Describe that further", payload=payload, previous=history))

    def test_actual_nested_utf8_budget_never_cuts_a_saved_value(self):
        for char in ("a", "\u667a", "\x01"):
            with self.subTest(char=repr(char)):
                for index in range(10):
                    self.memory.remember(f"fact-{index}", char * 1100, aliases=("active project",))
                result = self.context("Explain the active project")
                if result:
                    self.assertLessEqual(_context_size(result), MAX_MEMORY_CONTEXT_BYTES)
                    self.assertLessEqual(len(result["facts"]), 5)
                    for fact in result["facts"]:
                        self.assertEqual(fact["value"], char * 1100)
                self.assertLessEqual(len(json.dumps(self.memory.relevant_context(
                    "active project", max_json_chars=3000), ensure_ascii=False, separators=(",", ":"))), 3000)

    def test_malformed_or_oversized_record_does_not_hide_good_memory(self):
        self.memory.remember("good", "available", aliases=("active project",))
        self.memory.remember("huge", "x" * 100000, aliases=("active project",))
        with self.store._lock, self.store._conn:
            self.store._conn.execute("INSERT INTO facts VALUES(?,?,?,?,?)", ("bad", "{", "[]", "", ""))
        self.assertEqual(self.memory.relevant_context("active project"), [{"key": "good", "value": "available"}])


if __name__ == "__main__":
    unittest.main()

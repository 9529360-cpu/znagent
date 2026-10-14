from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.completion_summary import (
    build_completion_summary,
    continuation_requested,
    list_completion_summaries,
    list_pitfalls,
    recall_completion_summaries,
    save_completion_summary,
)
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore


def _artifact(artifact_id="artifact-1", name="report.md", path="/work/report.md"):
    return SimpleNamespace(
        artifact_id=artifact_id, name=name, path=path, content="x"
    )


class BuildSummaryTests(unittest.TestCase):
    def test_decision_without_fresh_evidence_is_dropped(self):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title="Write report",
            task="Write the weekly report",
            event_id="evt-1",
            success=True,
            response="We decided to use offline-first storage.",
            reason="",
            artifacts=[_artifact()],
            decisions=[
                {"text": "Use offline-first", "evidence_ref": "memory:old-fact"},
                {"text": "Ship report.md", "evidence_ref": "artifact-1"},
            ],
        )
        refs = [d["evidence_ref"] for d in summary["key_decisions"]]
        self.assertIn("artifact-1", refs)
        self.assertNotIn("memory:old-fact", refs)
        self.assertEqual(summary["dropped_decisions"], 2)  # 1 explicit + 1 auto (no artifact cite)

    def test_decision_citing_artifact_by_name_is_kept(self):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title="Write report",
            task="Write the weekly report",
            event_id="evt-1",
            success=True,
            response="We decided to adopt the layout in report.md.",
            reason="",
            artifacts=[_artifact()],
        )
        self.assertEqual(len(summary["key_decisions"]), 1)
        self.assertEqual(summary["key_decisions"][0]["evidence_ref"], "artifact-1")

    def test_credentials_never_survive_redaction(self):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title="Deploy",
            task="Deploy with password=hunter2",
            event_id="evt-1",
            success=False,
            response="Deploy failed, password=hunter2 and token sk-abcdefghijklmnop failed.",
            reason="authorization=sk-abcdefghijklmnop denied",
            artifacts=[],
        )
        encoded = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("sk-abcdefghijklmnop", encoded)
        self.assertTrue(summary["pitfalls"])
        self.assertTrue(summary["open_items"])

    def test_failed_run_records_open_item_and_pitfall(self):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title="Fix bug",
            task="Fix the login bug",
            event_id="evt-1",
            success=False,
            response="Login still fails. TODO: retry after the service is back.",
            reason="service unreachable",
            artifacts=[],
        )
        self.assertFalse(summary["success"])
        self.assertTrue(summary["pitfalls"])
        self.assertTrue(any("未完成" in item for item in summary["open_items"]))

    def test_summary_has_all_five_sections(self):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title="T",
            task="Do T",
            event_id="evt-1",
            success=True,
            response="Done.",
            reason="",
            artifacts=[_artifact()],
        )
        for key in ("goal", "key_decisions", "deliverables", "pitfalls", "open_items"):
            self.assertIn(key, summary)
        self.assertEqual(summary["deliverables"][0]["name"], "report.md")
        self.assertEqual(summary["memory_category"], "project_summary")


class StoreSummaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def _save(self, event_id, *, task="Task", success=True, response="Done."):
        summary = build_completion_summary(
            thread_id="t1",
            thread_title=task,
            task=task,
            event_id=event_id,
            success=success,
            response=response,
            reason="" if success else "service unreachable",
            artifacts=[],
        )
        return save_completion_summary(self.memory, summary)

    def test_save_and_list_and_recall_continuation(self):
        self._save("evt-1", task="Write the Artemis report")
        self._save("evt-2", task="Fix login bug")
        summaries = list_completion_summaries(self.memory, limit=10)
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["event_id"], "evt-2")  # newest first
        recalled = recall_completion_summaries(self.memory, "继续昨天那个", limit=2)
        self.assertEqual(len(recalled), 2)
        self.assertEqual(recalled[0]["event_id"], "evt-2")

    def test_unrelated_query_does_not_recall_summaries(self):
        self._save("evt-1", task="Write the Artemis report")
        self.assertEqual(
            recall_completion_summaries(self.memory, "What's the weather?"), []
        )

    def test_pitfalls_saved_as_separate_category(self):
        self._save("evt-1", success=False, response="Deploy failed badly.")
        pitfalls = list_pitfalls(self.memory, limit=10)
        self.assertEqual(len(pitfalls), 1)
        self.assertEqual(pitfalls[0]["memory_category"], "pitfall")
        self.assertEqual(pitfalls[0]["source_event_id"], "evt-1")

    def test_summaries_survive_reopen(self):
        self._save("evt-1", task="Write the Artemis report")
        self.store.close()
        reopened = KernelStore(self.root / "memory.db")
        self.addCleanup(reopened.close)
        memory = StructuredMemory(reopened)
        summaries = list_completion_summaries(memory, limit=10)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["goal"], "Write the Artemis report")

    def test_retention_prunes_oldest(self):
        for index in range(55):
            self._save(f"evt-{index:03d}", task=f"Task {index}")
        summaries = list_completion_summaries(self.memory, limit=100)
        self.assertEqual(len(summaries), 50)
        self.assertNotIn("evt-000", [s["event_id"] for s in summaries])

    def test_continuation_cues(self):
        self.assertTrue(continuation_requested("继续昨天那个"))
        self.assertTrue(continuation_requested("continue where we left off"))
        self.assertFalse(continuation_requested("Explain the active project approach"))


class CompletionSummaryProductTests(unittest.TestCase):
    """Full product path: Work finalize -> summary in memory -> after a
    restart, '继续昨天那个' restores it in cognition context."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "kernel.db"
        self.requests = []
        self.boot()
        self.addCleanup(lambda: self.resident.store.close())

    def boot(self):
        from zn_agent.core.cognitive_resource import (
            CognitiveResourceWorkerFactory,
            OpenAICompatibleCognitiveResource,
        )
        from zn_agent.core.daemon import ResidentRpcServer
        from zn_agent.core.models import ModelRoute
        from zn_agent.core.provider_bridge import build_resident_runtime

        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.resident.kernel.reconfigure_resources(
            routes=[ModelRoute("memory-local", "custom", "test-resource", {
                "general": 1.0, "reasoning": 1.0, "language_understanding": 1.0,
            }, metadata={"local": True, "base_url": "http://127.0.0.1:1/v1"})],
            worker_factory=CognitiveResourceWorkerFactory(lambda route: OpenAICompatibleCognitiveResource(
                route, client_builder=lambda **_: _ProductWireClient(self.requests),
            )), resource_status={"available": True}, max_attempts=1,
        )
        self.rpc = ResidentRpcServer(self.resident)

    def call(self, method, **params):
        response = self.rpc.handle({"id": method, "method": method, "params": params})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def start(self, task, *, thread="conversation"):
        result = self.call("work_start", thread_id=thread, task=task, payload={})
        progress = result["progress"]
        return progress["event_id"], progress["thread_id"]

    def finish(self, started, *, thread=None):
        event_id, actual_thread = started
        thread = thread or actual_thread
        for _ in range(80):
            result = self.call("work_progress", thread_id=thread, event_id=event_id)
            if result["progress"]["finalized"]:
                return result["thread"]
            self.resident.live_once()
        self.fail("Product Work did not finish")

    def last_context(self):
        self.assertTrue(self.requests)
        system = next(m["content"] for m in self.requests[-1]["messages"] if m["role"] == "system")
        return json.loads(system.split("BOUNDED CONTEXT:\n", 1)[1])["bounded_context"]

    def test_work_finalize_writes_summary_and_resume_restores_it_after_restart(self):
        self.finish(self.start("Write the Artemis status note"))
        summaries = list_completion_summaries(self.resident.memory, limit=10)
        self.assertEqual(len(summaries), 1)
        self.assertIn("Artemis status note", summaries[0]["goal"])

        self.resident.store.close()
        self.boot()

        # "刚才那个继续…" is the product's latest-Work continuation: it
        # starts a fresh follow-up event carrying work_continuation, and
        # the follow-up's cognition must restore the previous run's summary.
        self.finish(self.start("刚才那个继续，再处理下一步", thread="resume"))
        context = self.last_context()
        restored = context.get("resident_memory", {}).get("completion_summaries") or []
        self.assertTrue(restored, context.get("resident_memory", {}).keys())
        self.assertIn("Artemis status note", json.dumps(restored, ensure_ascii=False))

    def test_unrelated_task_does_not_inject_summaries(self):
        self.finish(self.start("Write the Artemis status note"))
        self.finish(self.start("Explain an unrelated topic", thread="other"))
        context = self.last_context()
        self.assertNotIn(
            "completion_summaries", context.get("resident_memory", {})
        )


class _ProductWireClient:
    """Capture the actual adapter request, without a live model or paid API."""

    def __init__(self, requests):
        self.requests = requests
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Controlled provider response."), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
        )

    def close(self):
        pass


if __name__ == "__main__":
    unittest.main()

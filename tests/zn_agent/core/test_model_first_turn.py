from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import Goal
from zn_agent.core.provider_bridge import build_resident_runtime


class ModelFirstTurnTests(unittest.TestCase):
    def _server(self, root: str):
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(root) / "kernel.db",
        )
        return resident, ResidentRpcServer(resident=resident)

    @staticmethod
    def _ok(response: str):
        return SimpleNamespace(
            worker_result=SimpleNamespace(
                success=True,
                response=response,
                error=None,
            )
        )

    def test_plain_turn_reaches_model_without_creating_durable_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            calls: list[tuple[str, dict]] = []

            def fake_run_goal(task, **kwargs):
                calls.append((task, kwargs))
                return self._ok("The project is ready.")

            resident.kernel.run_goal = fake_run_goal
            try:
                response = server.handle(
                    {
                        "id": "turn-1",
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "conversation",
                            "text": "How is the project?",
                        },
                    }
                )
                result = response["result"]
                self.assertEqual(result["mode"], "reply")
                self.assertEqual(result["reply"], "The project is ready.")
                self.assertIsNone(result["thread"]["active_run"])
                self.assertEqual(
                    [(m["role"], m["text"]) for m in result["thread"]["messages"]],
                    [
                        ("user", "How is the project?"),
                        ("zn", "The project is ready."),
                    ],
                )
                self.assertEqual(calls[0][0], "How is the project?")
                self.assertTrue(calls[0][1]["metadata"]["model_first_turn"])
                self.assertIsNone(
                    server.work_control.ledger._active_run_for_thread("conversation")
                )
            finally:
                resident.store.close()

    def test_model_can_promote_turn_into_existing_durable_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)

            resident.kernel.run_goal = lambda task, **kwargs: self._ok(
                '{"zn_work":{"objective":"Inspect the repository and run the relevant tests",'
                '"ack":"I will inspect it and run the relevant tests."}}'
            )
            try:
                response = server.handle(
                    {
                        "id": "turn-2",
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "conversation",
                            "text": "Check the project and fix what is broken.",
                        },
                    }
                )
                result = response["result"]
                self.assertEqual(result["mode"], "work")
                self.assertFalse(result["steering"])
                active = result["thread"]["active_run"]
                self.assertIsNotNone(active)
                self.assertEqual(
                    result["reply"],
                    "I will inspect it and run the relevant tests.",
                )
                root = server.work_control.ledger.work_item_for_event(
                    active["event_id"]
                )
                self.assertIsNotNone(root)
                self.assertEqual(
                    root.objective,
                    "Inspect the repository and run the relevant tests",
                )
                messages = result["thread"]["messages"]
                self.assertEqual(messages[0]["text"], "Check the project and fix what is broken.")
                self.assertEqual(messages[1]["detail"], {"model_first_handoff": True})
            finally:
                resident.store.close()

    def test_malformed_work_handoff_fails_closed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            resident.kernel.run_goal = lambda task, **kwargs: self._ok(
                '{"zn_work":{"objective":"do it"},"extra":true}'
            )
            try:
                with self.assertRaisesRegex(RuntimeError, "unsupported top-level fields"):
                    server.handle(
                        {
                            "method": "turn_submit",
                            "params": {
                                "thread_id": "conversation",
                                "text": "Do it.",
                            },
                        }
                    )
                self.assertIsNone(
                    server.work_control.ledger._active_run_for_thread("conversation")
                )
                thread = server.work_control.ledger.get_thread("conversation")
                self.assertIsNotNone(thread)
                self.assertEqual(
                    server.work_control.ledger.list_messages("conversation"),
                    [],
                )
            finally:
                resident.store.close()

    def test_route_policy_is_bound_before_the_model_first_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            captured: dict = {}

            def fake_run_goal(task, **kwargs):
                captured.update(kwargs)
                return self._ok("Understood.")

            resident.kernel.run_goal = fake_run_goal
            try:
                server.handle(
                    {
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "private-thread",
                            "text": "Only use GPT for this conversation.",
                        },
                    }
                )
                self.assertEqual(
                    captured["metadata"]["route_policy"]["allowed_providers"],
                    ["openai"],
                )
                thread = server.work_control.ledger.get_thread("private-thread")
                self.assertEqual(
                    thread.metadata["route_policy"]["allowed_providers"],
                    ["openai"],
                )
            finally:
                resident.store.close()


    def test_saved_memory_and_prior_user_turn_reach_model_first_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            contexts: list[dict] = []

            def fake_run_goal(task, **kwargs):
                contexts.append(kwargs["metadata"]["cognition_request"]["context"])
                return self._ok("Noted.")

            resident.kernel.run_goal = fake_run_goal
            try:
                server.handle(
                    {
                        "method": "remember",
                        "params": {
                            "key": "project",
                            "value": {"name": "Artemis", "decision": "offline first"},
                            "aliases": ["active project"],
                        },
                    }
                )
                server.handle(
                    {
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "memory-thread",
                            "text": "Explain the active project approach.",
                        },
                    }
                )
                server.handle(
                    {
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "memory-thread",
                            "text": "Describe that approach further.",
                        },
                    }
                )
                self.assertEqual(
                    contexts[0]["resident_memory"]["facts"][0]["value"]["name"],
                    "Artemis",
                )
                self.assertEqual(
                    contexts[1]["resident_memory"]["facts"][0]["value"]["decision"],
                    "offline first",
                )
                self.assertEqual(
                    contexts[1]["resident_memory"]["facts"][0]["matched_in"],
                    "previous_user_message",
                )
                self.assertEqual(
                    contexts[1]["conversation"][0]["text"],
                    "Explain the active project approach.",
                )
            finally:
                resident.store.close()

    def test_active_work_turn_keeps_local_steering_boundary_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                started = server.handle(
                    {
                        "method": "work_start",
                        "params": {
                            "thread_id": "active-thread",
                            "task": "Inspect Notepad.",
                        },
                    }
                )["result"]
                calls = 0

                def should_not_run_model(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    raise AssertionError("active Work steering must not wait on the model")

                resident.kernel.run_goal = should_not_run_model
                steered = server.handle(
                    {
                        "method": "turn_submit",
                        "params": {
                            "thread_id": "active-thread",
                            "text": "Switch to Calculator instead.",
                        },
                    }
                )["result"]
                self.assertEqual(calls, 0)
                self.assertEqual(steered["mode"], "work")
                self.assertTrue(steered["steering"])
                self.assertNotEqual(
                    steered["progress"]["event_id"],
                    started["progress"]["event_id"],
                )
            finally:
                resident.store.close()

    def test_model_first_worker_context_makes_model_the_turn_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, _server = self._server(tmp)
            try:
                goal = Goal(
                    goal_id="turn-prompt",
                    task="What should we do?",
                    metadata={
                        "model_first_turn": True,
                        "cognition_request": {"context": {"conversation": []}},
                    },
                )
                context = resident.kernel._build_worker_context(
                    goal,
                    resident.kernel.router.routes[0],
                    1,
                    [],
                )
                self.assertIn("primary conversational model", context)
                self.assertIn('"zn_work"', context)
                self.assertIn("TURN CONTEXT", context)
                self.assertNotIn("temporarily consulted by ZN", context)
            finally:
                resident.store.close()

if __name__ == "__main__":
    unittest.main()

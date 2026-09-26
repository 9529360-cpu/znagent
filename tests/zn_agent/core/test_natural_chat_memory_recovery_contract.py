from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.channel import ChannelDelivery, ChannelEvent, channel_work_thread_id
from zn_agent.core.channel_runtime import ResidentChannelSupervisor
from zn_agent.core.config import load_zn_config
from zn_agent.core.continuity import ContinuitySnapshotService, compare_continuity_snapshots
from zn_agent.core.credentials import CredentialStoreStatus
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.event_ingress import stable_external_event_id
from zn_agent.core.models import EventStatus, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.provider_settings import ProviderSettingsService


class _MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def status(self) -> CredentialStoreStatus:
        return CredentialStoreStatus(
            available=True,
            backend="contract-memory",
            error=None,
        )

    def get(self, reference: str) -> str | None:
        return self.values.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)


class _CapturingWorker:
    def __init__(self, capture, route) -> None:
        self.capture = capture
        self.route = route

    def run(self, goal, kernel_context: str) -> WorkerResult:
        self.capture.append(
            {
                "provider": self.route.provider,
                "model": self.route.model,
                "task": goal.task,
                "context": kernel_context,
            }
        )
        return WorkerResult(
            success=True,
            response=(
                f"自然回复（{self.route.provider}/{self.route.model}）："
                f"我已结合当前对话和已确认偏好回答。"
            ),
            metrics={"model_invoked": True},
        )


class _CapturingWorkerFactory:
    def __init__(self, capture) -> None:
        self.capture = capture

    def create(self, route):
        return _CapturingWorker(self.capture, route)


class _FailingWorker:
    def run(self, goal, kernel_context: str) -> WorkerResult:
        return WorkerResult(
            success=False,
            error="TimeoutError: synthetic provider timeout with private diagnostic",
            metrics={"model_invoked": True},
        )


class _FailingWorkerFactory:
    def create(self, route):
        return _FailingWorker()


class _TelegramAdapter:
    name = "telegram"

    def __init__(self) -> None:
        self.sent = []

    def poll(self, *, timeout=0.0):
        return []

    def send(self, message):
        self.sent.append(message)
        return ChannelDelivery(
            ok=True,
            channel="telegram",
            conversation_id=message.conversation_id,
            message_ids=(f"sent-{len(self.sent)}",),
        )

    def close(self):
        pass


class NaturalChatMemoryRecoveryContractTests(unittest.TestCase):
    def _configure_capture(self, resident, capture) -> None:
        routes = list(resident.kernel.router.routes)
        self.assertTrue(routes, "configured provider did not create a route")
        resident.kernel.reconfigure_resources(
            routes=routes,
            worker_factory=_CapturingWorkerFactory(capture),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    @staticmethod
    def _drive(resident, event_id: str, *, limit: int = 256):
        for _ in range(limit):
            completed = resident.result_for(event_id)
            if completed is not None:
                return completed
            resident.live_once()
        raise AssertionError(f"Resident did not complete {event_id}")

    @staticmethod
    def _bounded_context(kernel_context: str) -> dict:
        marker = "BOUNDED CONTEXT:\n"
        if marker not in kernel_context:
            raise AssertionError("worker context has no bounded context")
        return json.loads(kernel_context.split(marker, 1)[1])

    @staticmethod
    def _event(
        *,
        update_id: int,
        text: str,
        message_id: str,
        chat_id: str = "telegram-chat-42",
        topic_id: str | None = None,
    ) -> ChannelEvent:
        return ChannelEvent(
            channel="telegram",
            conversation_id=chat_id,
            sender_id="telegram-user-7",
            text=text,
            message_id=message_id,
            thread_id=topic_id,
            metadata={
                "update_id": update_id,
                "update_type": "message",
                "chat_type": "private",
                "chat_title": "Long lived chat",
            },
        )

    def test_three_turn_cross_surface_memory_restart_and_provider_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            config_path = root / "config.yaml"
            credentials = _MemoryCredentialStore()
            capture = []

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=db,
                credential_store=credentials,
            )
            settings = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            configured = settings.update(
                {
                    "provider": "openai",
                    "model": "gpt-e2e-a",
                    "api_key": "synthetic-e2e-key-a",
                }
            )
            self.assertTrue(configured["cognition_available"])
            self.assertEqual(configured["provider"], "openai")
            self.assertEqual(configured["model"], "gpt-e2e-a")
            self._configure_capture(resident, capture)

            identity_created_at = resident.identity.created_at
            telegram = _TelegramAdapter()
            channels = ResidentChannelSupervisor(
                resident,
                [telegram],
                reply_failures=True,
            )
            first = self._event(
                update_id=101,
                message_id="tg-101",
                text="请记住，以后回答请简洁一些。然后告诉我你已经准备好了。",
            )
            thread_id = channel_work_thread_id(
                first.channel, first.conversation_id, first.thread_id
            )
            enqueued, duplicates = channels._ingest_events([first])
            self.assertEqual((enqueued, duplicates), (1, 0))
            event_id = stable_external_event_id(
                "channel", channels.ledger.source_key(first)
            )
            first_result = self._drive(resident, event_id)
            self.assertTrue(first_result.success)
            self.assertEqual(channels._deliver_ready("telegram", telegram), 1)
            self.assertEqual(len(telegram.sent), 1)
            self.assertIn("自然回复", telegram.sent[0].text)

            preference = resident.memory.recall("response verbosity")
            self.assertIsNotNone(preference)
            self.assertEqual(preference.value, "concise")
            before_repeat = next(
                item for item in resident.store.list_facts()
                if item["key"] == "response verbosity"
            )

            enqueued, duplicates = channels._ingest_events([first])
            self.assertEqual((enqueued, duplicates), (0, 1))
            self.assertEqual(channels._deliver_ready("telegram", telegram), 0)
            self.assertEqual(len(telegram.sent), 1, "duplicate Telegram update re-replied")
            after_repeat = next(
                item for item in resident.store.list_facts()
                if item["key"] == "response verbosity"
            )
            self.assertEqual(
                before_repeat["updated_at"],
                after_repeat["updated_at"],
                "duplicate Telegram update rewrote durable memory",
            )

            rpc = ResidentRpcServer(
                resident=resident,
                provider_settings=settings,
            )
            provider_view = rpc.handle(
                {"id": "provider", "method": "provider_settings", "params": {}}
            )["result"]
            self.assertTrue(provider_view["cognition_available"])
            self.assertEqual(provider_view["provider"], "openai")
            self.assertEqual(provider_view["model"], "gpt-e2e-a")
            desktop_view = rpc.handle(
                {"id": "get", "method": "work_get", "params": {"thread_id": thread_id}}
            )
            self.assertTrue(desktop_view["ok"])
            self.assertEqual(desktop_view["result"]["id"], thread_id)
            self.assertTrue(
                any(
                    item["role"] == "zn" and "自然回复" in item["text"]
                    for item in desktop_view["result"]["messages"]
                )
            )

            second = rpc.handle(
                {
                    "id": "desktop-turn",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": "第二轮：那你以后会怎样回答我？",
                    },
                }
            )["result"]
            second_event = second["progress"]["event_id"]
            self.assertTrue(self._drive(resident, second_event).success)
            second_progress = rpc.handle(
                {
                    "id": "desktop-progress",
                    "method": "work_progress",
                    "params": {
                        "thread_id": thread_id,
                        "event_id": second_event,
                    },
                }
            )["result"]
            self.assertTrue(second_progress["progress"]["finalized"])
            self.assertEqual(second_progress["thread"]["id"], thread_id)

            second_state = self._bounded_context(capture[-1]["context"])
            second_context = second_state["bounded_context"]
            conversation = second_context["work_conversation"]
            self.assertEqual(conversation["thread_id"], thread_id)
            self.assertTrue(
                any("请记住" in item["text"] for item in conversation["messages"])
            )
            memory = second_context["resident_memory"]
            self.assertTrue(
                any(
                    item["dimension"] == "verbosity" and item["value"] == "concise"
                    for item in memory["response_preferences"]
                )
            )

            before_restart = ContinuitySnapshotService(
                resident,
                work=resident.work_ledger,
                provider_settings=settings,
            ).snapshot()
            resident.store.close()

            resident = build_resident_runtime(
                config=load_zn_config(config_path),
                store_path=db,
                credential_store=credentials,
            )
            settings = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            self.assertEqual(resident.identity.created_at, identity_created_at)
            self.assertEqual(
                resident.memory.recall("response verbosity").value,
                "concise",
            )
            switched = settings.update(
                {
                    "provider": "anthropic",
                    "model": "claude-e2e-b",
                    "api_key": "synthetic-e2e-key-b",
                }
            )
            self.assertTrue(switched["cognition_available"])
            self.assertEqual(switched["provider"], "anthropic")
            self.assertEqual(switched["model"], "claude-e2e-b")
            self._configure_capture(resident, capture)

            rpc = ResidentRpcServer(
                resident=resident,
                provider_settings=settings,
            )
            provider_view = rpc.handle(
                {"id": "provider-after", "method": "provider_settings", "params": {}}
            )["result"]
            self.assertTrue(provider_view["cognition_available"])
            self.assertEqual(provider_view["provider"], "anthropic")
            self.assertEqual(provider_view["model"], "claude-e2e-b")
            restored = rpc.handle(
                {"id": "restored", "method": "work_get", "params": {"thread_id": thread_id}}
            )["result"]
            self.assertEqual(restored["id"], thread_id)
            self.assertTrue(any("第二轮" in item["text"] for item in restored["messages"]))

            telegram_after_restart = _TelegramAdapter()
            channels = ResidentChannelSupervisor(
                resident,
                [telegram_after_restart],
                reply_failures=True,
            )
            third = self._event(
                update_id=102,
                message_id="tg-102",
                text="第三轮：继续刚才的话。我们约定的回答偏好是什么？",
            )
            enqueued, duplicates = channels._ingest_events([third])
            self.assertEqual((enqueued, duplicates), (1, 0))
            third_event = stable_external_event_id(
                "channel", channels.ledger.source_key(third)
            )
            third_result = self._drive(resident, third_event)
            self.assertTrue(third_result.success)
            self.assertEqual(
                channels._deliver_ready("telegram", telegram_after_restart),
                1,
            )
            self.assertIn(
                "anthropic/claude-e2e-b",
                telegram_after_restart.sent[0].text,
            )

            third_state = self._bounded_context(capture[-1]["context"])
            third_context = third_state["bounded_context"]
            self.assertEqual(
                third_context["work_conversation"]["thread_id"],
                thread_id,
            )
            self.assertTrue(
                any(
                    item["dimension"] == "verbosity" and item["value"] == "concise"
                    for item in third_context["resident_memory"]["response_preferences"]
                )
            )
            self.assertEqual(capture[-1]["provider"], "anthropic")
            self.assertEqual(capture[-1]["model"], "claude-e2e-b")

            after_restart = ContinuitySnapshotService(
                resident,
                work=resident.work_ledger,
                provider_settings=settings,
            ).snapshot()
            continuity = compare_continuity_snapshots(
                before_restart,
                after_restart,
            )
            self.assertTrue(continuity["compatible"], continuity)
            self.assertTrue(
                any(
                    item["kind"] == "provider_reference_changed"
                    for item in continuity["warnings"]
                )
            )
            final_view = rpc.handle(
                {"id": "final", "method": "work_get", "params": {"thread_id": thread_id}}
            )["result"]
            self.assertEqual(
                sum(item["role"] == "user" for item in final_view["messages"]),
                3,
            )
            self.assertEqual(
                sum(item["role"] == "zn" for item in final_view["messages"]),
                3,
            )
            resident.store.close()

    def test_group_channel_cannot_rewrite_global_response_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                channels = ResidentChannelSupervisor(
                    resident,
                    [_TelegramAdapter()],
                    reply_failures=True,
                )
                event = ChannelEvent(
                    channel="telegram",
                    conversation_id="telegram-group-42",
                    sender_id="group-member-9",
                    text="请记住，以后回答请详细一点。",
                    message_id="group-301",
                    metadata={
                        "update_id": 301,
                        "update_type": "message",
                        "chat_type": "group",
                        "chat_title": "Shared room",
                    },
                )
                enqueued, duplicates = channels._ingest_events([event])
                self.assertEqual((enqueued, duplicates), (1, 0))
                self.assertIsNone(resident.memory.recall("response verbosity"))
                thread_id = channel_work_thread_id(
                    event.channel, event.conversation_id, event.thread_id
                )
                messages = resident.work_ledger.list_messages(thread_id)
                self.assertEqual(
                    [item.text for item in messages if item.role == "user"],
                    [event.text],
                )
            finally:
                resident.store.close()

    def test_configured_provider_failure_is_not_published_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = _MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            settings = ProviderSettingsService(
                resident,
                config_path=root / "config.yaml",
                credential_store=credentials,
                environ={},
            )
            snapshot = settings.update(
                {
                    "provider": "openai",
                    "model": "gpt-e2e-failing",
                    "api_key": "synthetic-e2e-failure-key",
                }
            )
            self.assertTrue(snapshot["cognition_available"])
            resident.kernel.reconfigure_resources(
                routes=list(resident.kernel.router.routes),
                worker_factory=_FailingWorkerFactory(),
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )

            telegram = _TelegramAdapter()
            channels = ResidentChannelSupervisor(
                resident,
                [telegram],
                reply_failures=True,
            )
            event = self._event(
                update_id=151,
                message_id="tg-151",
                text="请解释这个需要模型完成的问题。",
                chat_id="telegram-provider-failure",
            )
            thread_id = channel_work_thread_id(
                event.channel, event.conversation_id, event.thread_id
            )
            channels._ingest_events([event])
            event_id = stable_external_event_id(
                "channel", channels.ledger.source_key(event)
            )
            run = self._drive(resident, event_id)
            self.assertFalse(run.success)
            self.assertEqual(channels._deliver_ready("telegram", telegram), 1)
            self.assertEqual(len(telegram.sent), 1)
            self.assertIn(
                "could not complete this request with the configured cognitive resource",
                telegram.sent[0].text,
            )
            self.assertNotIn("private diagnostic", telegram.sent[0].text)

            view = ResidentRpcServer(
                resident=resident,
                provider_settings=settings,
            ).handle(
                {"id": "failed", "method": "work_get", "params": {"thread_id": thread_id}}
            )["result"]
            self.assertIsNone(view["active_run"])
            self.assertTrue(
                any(
                    item["role"] == "zn" and item["detail"].get("failed") is True
                    for item in view["messages"]
                )
            )
            resident.store.close()

    def test_unconfigured_model_returns_clear_channel_failure_and_keeps_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            config_path = root / "config.yaml"
            settings = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=_MemoryCredentialStore(),
                environ={},
            )
            snapshot = settings.snapshot()
            self.assertFalse(snapshot["cognition_available"])
            self.assertEqual(snapshot["model"], "")
            provider_view = ResidentRpcServer(
                resident=resident,
                provider_settings=settings,
            ).handle(
                {"id": "provider-unconfigured", "method": "provider_settings", "params": {}}
            )["result"]
            self.assertFalse(provider_view["cognition_available"])
            self.assertEqual(provider_view["model"], "")

            telegram = _TelegramAdapter()
            channels = ResidentChannelSupervisor(
                resident,
                [telegram],
                reply_failures=True,
            )
            event = self._event(
                update_id=201,
                message_id="tg-201",
                text="请解释一个需要模型推理的问题。",
                chat_id="telegram-unconfigured",
            )
            thread_id = channel_work_thread_id(
                event.channel, event.conversation_id, event.thread_id
            )
            enqueued, duplicates = channels._ingest_events([event])
            self.assertEqual((enqueued, duplicates), (1, 0))
            event_id = stable_external_event_id(
                "channel", channels.ledger.source_key(event)
            )
            run = self._drive(resident, event_id)
            self.assertFalse(run.success)
            self.assertEqual(channels._deliver_ready("telegram", telegram), 1)
            self.assertEqual(len(telegram.sent), 1)
            self.assertIn("no cognitive model is configured or available", telegram.sent[0].text)

            rpc = ResidentRpcServer(
                resident=resident,
                provider_settings=settings,
            )
            view = rpc.handle(
                {"id": "work", "method": "work_get", "params": {"thread_id": thread_id}}
            )["result"]
            self.assertIsNone(view["active_run"])
            self.assertTrue(
                any(
                    item["role"] == "zn" and "No System 2 model is configured" in item["text"]
                    for item in view["messages"]
                )
            )
            persisted = resident.store.get_event(event_id)
            self.assertIn(persisted.status, {EventStatus.COMPLETED, EventStatus.FAILED})

            enqueued, duplicates = channels._ingest_events([event])
            self.assertEqual((enqueued, duplicates), (0, 1))
            self.assertEqual(channels._deliver_ready("telegram", telegram), 0)
            self.assertEqual(len(telegram.sent), 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

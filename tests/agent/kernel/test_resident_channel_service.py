from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.kernel.channel import ChannelDelivery, ChannelEvent
from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.resident_server import ResidentSocketService


class _ResidentChannelAdapter:
    name = "test-channel"

    def __init__(self):
        self._first = True
        self._closed_event = threading.Event()
        self.delivered = threading.Event()
        self.sent = []
        self.closed = False

    def poll(self, *, timeout=0.0):
        if self._first:
            self._first = False
            return [
                ChannelEvent(
                    channel=self.name,
                    conversation_id="conversation-1",
                    sender_id="person-1",
                    text="resident channel work",
                    message_id="incoming-1",
                    metadata={"update_id": 17},
                )
            ]
        self._closed_event.wait(min(max(0.0, float(timeout)), 0.05))
        return []

    def send(self, message):
        self.sent.append(message)
        self.delivered.set()
        return ChannelDelivery(
            ok=True,
            channel=self.name,
            conversation_id=message.conversation_id,
            message_ids=("outgoing-1",),
        )

    def close(self):
        self.closed = True
        self._closed_event.set()


class ResidentChannelSocketServiceTests(unittest.TestCase):
    @staticmethod
    def _request(endpoint: dict, method: str) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": f"test-{method}-{time.time_ns()}",
                            "method": method,
                            "params": {},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            raw = client.makefile("rb").readline()
            return json.loads(raw.decode("utf-8"))

    def test_channel_runs_with_resident_even_without_ui_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            calls = []
            outcome = SimpleNamespace(
                success=True,
                response="resident channel reply",
                reason="",
            )

            def enqueue(task, **kwargs):
                calls.append((task, kwargs))
                return SimpleNamespace(event_id="evt-channel-service-test")

            def result_for(event_id):
                if event_id == "evt-channel-service-test":
                    return outcome
                return None

            resident.enqueue = enqueue
            resident.result_for = result_for
            adapter = _ResidentChannelAdapter()
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            service = ResidentSocketService(
                rpc,
                endpoint_path=endpoint_path,
                channel_adapters=[adapter],
                channel_poll_timeout=0.05,
            )
            thread = threading.Thread(
                target=service.serve_forever,
                name="test-resident-channel-service",
                daemon=True,
            )
            thread.start()

            deadline = time.monotonic() + 5.0
            endpoint = None
            while time.monotonic() < deadline:
                if endpoint_path.exists():
                    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                    break
                time.sleep(0.02)
            self.assertIsNotNone(endpoint)
            self.assertEqual(endpoint["channels"], ["test-channel"])

            self.assertTrue(adapter.delivered.wait(2.0))
            self.assertEqual([item[0] for item in calls], ["resident channel work"])
            self.assertEqual(calls[0][1]["kind"], "channel_message")
            self.assertEqual(
                calls[0][1]["payload"]["channel"],
                "test-channel",
            )
            self.assertEqual(
                calls[0][1]["payload"]["channel_source_key"],
                "test-channel:update:17",
            )
            self.assertEqual(adapter.sent[0].text, "resident channel reply")
            route = service.channels.ledger.route_for_event("evt-channel-service-test")
            self.assertIsNotNone(route)
            self.assertEqual(route.status, "delivered")

            shutdown = self._request(endpoint, "shutdown")
            self.assertTrue(shutdown["ok"])
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(adapter.closed)
            self.assertFalse(endpoint_path.exists())


if __name__ == "__main__":
    unittest.main()

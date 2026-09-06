from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zn_agent.core.channel import ChannelDelivery, ChannelEvent
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import EventOutcome, ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService


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
    def _auth_secret(endpoint: dict) -> str:
        auth = endpoint.get("authentication")
        if not isinstance(auth, dict) or auth.get("scheme") != "session-secret-v1":
            raise AssertionError("resident endpoint does not contain the expected auth scheme")
        secret = auth.get("secret")
        if not isinstance(secret, str) or len(secret) < 32:
            raise AssertionError("resident endpoint auth secret is missing or too short")
        return secret

    @classmethod
    def _request(cls, endpoint: dict, method: str) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            stream = client.makefile("rb")
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": f"test-auth-{time.time_ns()}",
                            "method": "authenticate",
                            "params": {"secret": cls._auth_secret(endpoint)},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            raw_auth = stream.readline()
            if not raw_auth:
                raise AssertionError("resident endpoint closed before auth response")
            auth_response = json.loads(raw_auth.decode("utf-8"))
            if not auth_response.get("ok"):
                return auth_response

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
            raw = stream.readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_channel_runs_with_resident_even_without_ui_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            # This test isolates channel lifecycle from cognition. The channel
            # must enqueue a durable percept, then later deliver a durable
            # outcome produced by the resident life loop rather than driving
            # cognition itself through submit().
            resident.live_once = lambda: None

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

            source_key = "test-channel:update:17"
            route = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                route = service.channels.ledger.route_for_source(source_key)
                if route is not None:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(route)
            assert route is not None

            event = resident.store.get_event(route.event_id)
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event.task, "resident channel work")
            self.assertEqual(event.kind, "channel_message")
            self.assertEqual(event.payload["channel"], "test-channel")
            self.assertEqual(event.payload["channel_source_key"], source_key)

            resident.store.finish_event(route.event_id, success=True)
            resident.store.save_event_outcome(
                EventOutcome(
                    event_id=route.event_id,
                    success=True,
                    execution_path=ExecutionPath.CAPABILITY,
                    response="resident channel reply",
                )
            )

            self.assertTrue(adapter.delivered.wait(2.0))
            self.assertEqual(adapter.sent[0].text, "resident channel reply")

            delivered_route = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                delivered_route = service.channels.ledger.route_for_event(route.event_id)
                if delivered_route is not None and delivered_route.status == "delivered":
                    break
                time.sleep(0.01)
            self.assertIsNotNone(delivered_route)
            assert delivered_route is not None
            self.assertEqual(delivered_route.status, "delivered")

            shutdown = self._request(endpoint, "shutdown")
            self.assertTrue(shutdown["ok"])
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(adapter.closed)
            self.assertFalse(endpoint_path.exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core import messaging_connector
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.credentials import CredentialStoreStatus
from zn_agent.core.messaging_connector import (
    CHANNEL_ID,
    LIST_ACTION_ID,
    READ_ACTION_ID,
    SEND_ACTION_ID,
    ChatMessage,
    ChatThread,
    MessagingAccountConfig,
    MessagingError,
    SendReceipt,
    WhatsAppCloudChannel,
    attach_messaging_tools,
    list_threads,
    read_thread,
    register_messaging_runtime,
    send_text,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"


class _FakeCredentialStore:
    def __init__(self, secrets: dict[str, str] | None = None):
        self._secrets = dict(secrets or {})

    def status(self):
        return CredentialStoreStatus(available=True, backend="fake")

    def get(self, reference: str):
        return self._secrets.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self._secrets[reference] = secret

    def delete(self, reference: str) -> None:
        self._secrets.pop(reference, None)


class _FakeChannel:
    """In-memory messaging channel: threads, messages, and sends."""

    def __init__(self):
        self.threads: dict[str, list[ChatMessage]] = {}
        self.peers: dict[str, str] = {}
        self.sends: list[dict] = []
        self._next_id = 0
        self.fail_list: Exception | None = None

    def add_thread(self, thread_id: str, peer: str, messages: list[ChatMessage]) -> None:
        self.threads[thread_id] = list(messages)
        self.peers[thread_id] = peer

    def list_threads(self, *, limit: int) -> list[ChatThread]:
        if self.fail_list is not None:
            raise self.fail_list
        ordered = list(self.threads)[:limit]
        result = []
        for thread_id in ordered:
            messages = self.threads[thread_id]
            last = messages[-1] if messages else None
            result.append(
                ChatThread(
                    thread_id=thread_id,
                    peer=self.peers.get(thread_id, ""),
                    last_message_preview=(
                        last.text[:50] if last is not None else ""
                    ),
                    last_message_at=last.sent_at if last is not None else None,
                    unread_count=sum(
                        1 for item in messages if item.direction == "in"
                    ),
                )
            )
        return result

    def read_thread(self, thread_id: str, *, limit: int) -> list[ChatMessage]:
        messages = self.threads.get(thread_id)
        if messages is None:
            raise MessagingError(f"no such thread {thread_id!r}")
        return list(reversed(messages[-limit:]))

    def send_text(self, *, recipient: str, text: str) -> SendReceipt:
        self._next_id += 1
        provider_id = f"wamid.fake{self._next_id:06d}"
        record = {"recipient": recipient, "text": text, "id": provider_id}
        self.sends.append(record)
        thread_id = f"thread-{recipient}"
        message = ChatMessage(
            message_id=f"local-{self._next_id}",
            thread_id=thread_id,
            direction="out",
            sender="me",
            text=text,
            sent_at=datetime.now(timezone.utc),
            provider_message_id=provider_id,
        )
        self.threads.setdefault(thread_id, []).append(message)
        self.peers.setdefault(thread_id, recipient)
        return SendReceipt(
            provider_message_id=provider_id,
            recipient=recipient,
            accepted=True,
            provider_response=json.dumps({"messages": [{"id": provider_id}]}),
        )


class _FakeHttpTransport:
    def __init__(self):
        self.calls: list[dict] = []
        self.status = 200
        self.body = json.dumps(
            {"messages": [{"id": "wamid.test123"}]}
        ).encode("utf-8")
        self.failure: Exception | None = None

    def post(self, *, url, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.status, self.body


def _message(
    *,
    message_id: str = "m1",
    thread_id: str = "t1",
    direction: str = "in",
    sender: str = "+491511111111",
    text: str = "Hello there",
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        thread_id=thread_id,
        direction=direction,
        sender=sender,
        text=text,
        sent_at=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        provider_message_id=f"wamid.{message_id}",
    )


def _config(**overrides) -> MessagingAccountConfig:
    values = {
        "phone_number_id": "123456789012345",
        "credential_ref": "provider:whatsapp",
    }
    values.update(overrides)
    return MessagingAccountConfig(**values)


def _store_with_secret() -> _FakeCredentialStore:
    return _FakeCredentialStore({"provider:whatsapp": "tok3n"})


class MessagingConfigTests(unittest.TestCase):
    def test_valid_config_normalizes(self):
        config = _config(credential_ref=" provider:whatsapp ")
        self.assertEqual(config.channel, "whatsapp")
        self.assertEqual(config.credential_ref, "provider:whatsapp")
        self.assertEqual(config.api_version, "v21.0")

    def test_bad_channel_rejected(self):
        with self.assertRaises(MessagingError):
            _config(channel="telegram")

    def test_bad_phone_number_id_rejected(self):
        with self.assertRaises(MessagingError):
            _config(phone_number_id="not-a-number")

    def test_bad_base_url_rejected(self):
        with self.assertRaises(MessagingError):
            _config(api_base_url="http://insecure.example.com")

    def test_bad_api_version_rejected(self):
        with self.assertRaises(MessagingError):
            _config(api_version="v2")

    def test_bad_credential_ref_rejected(self):
        with self.assertRaises(ValueError):
            _config(credential_ref="not a ref")

    def test_timeout_bounds(self):
        with self.assertRaises(MessagingError):
            _config(timeout_seconds=0.5)
        with self.assertRaises(MessagingError):
            _config(timeout_seconds=500.0)


class WhatsAppDriverTests(unittest.TestCase):
    def _driver(self, http, **overrides):
        config = _config(**overrides)
        return (
            WhatsAppCloudChannel(
                config, _store_with_secret(), http_transport=http
            ),
            config,
        )

    def test_send_builds_cloud_api_request(self):
        http = _FakeHttpTransport()
        driver, config = self._driver(http)
        receipt = driver.send_text(recipient="+4915112345678", text="Hi")
        self.assertEqual(receipt.provider_message_id, "wamid.test123")
        self.assertTrue(receipt.accepted)
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(
            call["url"],
            "https://graph.facebook.com/v21.0/123456789012345/messages",
        )
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok3n")
        self.assertEqual(call["payload"]["messaging_product"], "whatsapp")
        self.assertEqual(call["payload"]["to"], "+4915112345678")
        self.assertEqual(call["payload"]["text"]["body"], "Hi")
        self.assertFalse(call["payload"]["text"]["preview_url"])

    def test_send_rejects_bad_recipient_before_http(self):
        http = _FakeHttpTransport()
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="not-a-phone", text="Hi")
        self.assertIn("phone number", str(ctx.exception))
        self.assertEqual(http.calls, [])

    def test_send_rejects_empty_text_before_http(self):
        http = _FakeHttpTransport()
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError):
            driver.send_text(recipient="+4915112345678", text="   ")
        self.assertEqual(http.calls, [])

    def test_provider_error_payload_is_explicit(self):
        http = _FakeHttpTransport()
        http.status = 400
        http.body = json.dumps(
            {
                "error": {
                    "message": "Unsupported post request.",
                    "code": 100,
                    "error_data": {"details": "bad phone number id"},
                }
            }
        ).encode("utf-8")
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="+4915112345678", text="Hi")
        reason = str(ctx.exception)
        self.assertIn("400", reason)
        self.assertIn("bad phone number id", reason)

    def test_success_without_message_id_is_unconfirmed(self):
        http = _FakeHttpTransport()
        http.body = json.dumps({"messages": []}).encode("utf-8")
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="+4915112345678", text="Hi")
        self.assertIn("no message id", str(ctx.exception))

    def test_unreadable_success_body_is_unconfirmed(self):
        http = _FakeHttpTransport()
        http.body = b"not json at all"
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="+4915112345678", text="Hi")
        self.assertIn("unreadable", str(ctx.exception))

    def test_transport_failure_is_explicit(self):
        http = _FakeHttpTransport()
        http.failure = OSError("connection reset")
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="+4915112345678", text="Hi")
        self.assertIn("OSError", str(ctx.exception))

    def test_reads_name_the_webhook_step(self):
        http = _FakeHttpTransport()
        driver, _ = self._driver(http)
        with self.assertRaises(MessagingError) as ctx:
            driver.list_threads(limit=5)
        self.assertIn("webhook", str(ctx.exception))
        with self.assertRaises(MessagingError) as ctx:
            driver.read_thread("t1", limit=5)
        self.assertIn("webhook", str(ctx.exception))

    def test_send_without_config_token_is_explicit(self):
        http = _FakeHttpTransport()
        driver = WhatsAppCloudChannel(
            _config(), _FakeCredentialStore(), http_transport=http
        )
        with self.assertRaises(MessagingError) as ctx:
            driver.send_text(recipient="+4915112345678", text="Hi")
        self.assertIn("未配置", str(ctx.exception))
        self.assertEqual(http.calls, [])


class MessagingCoreTests(unittest.TestCase):
    def setUp(self):
        self.channel = _FakeChannel()
        self.channel.add_thread(
            "t1", "+491511111111", [_message(), _message(message_id="m2", text="Second")]
        )
        self.config = _config()
        self.store = _store_with_secret()

    def test_list_threads_newest_limited(self):
        threads = list_threads(
            self.channel, self.config, self.store, limit=10
        )
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].thread_id, "t1")
        self.assertEqual(threads[0].peer, "+491511111111")
        self.assertEqual(threads[0].unread_count, 2)

    def test_read_thread_newest_first(self):
        messages = read_thread(
            self.channel, self.config, self.store, thread_id="t1", limit=10
        )
        self.assertEqual([item.message_id for item in messages], ["m2", "m1"])

    def test_read_unknown_thread_is_explicit(self):
        with self.assertRaises(MessagingError):
            read_thread(
                self.channel, self.config, self.store, thread_id="nope"
            )

    def test_not_configured_without_config(self):
        with self.assertRaises(MessagingError) as ctx:
            list_threads(self.channel, None, self.store)
        self.assertIn("未配置", str(ctx.exception))

    def test_not_configured_without_store(self):
        # The shipped WhatsApp driver resolves the token at send time;
        # with no credential store the send reports "not configured".
        driver = WhatsAppCloudChannel(
            self.config, None, http_transport=_FakeHttpTransport()
        )
        with self.assertRaises(MessagingError) as ctx:
            send_text(
                driver, self.config, None, to="+4915112345678", text="Hi"
            )
        self.assertIn("未配置", str(ctx.exception))

    def test_fake_channel_reads_do_not_need_token(self):
        # The injected fake channel proves the read path without any
        # credential; only the real driver resolves the token.
        threads = list_threads(self.channel, self.config, _FakeCredentialStore())
        self.assertEqual(len(threads), 1)

    def test_send_needs_token_even_on_fake_channel(self):
        with self.assertRaises(MessagingError) as ctx:
            send_text(
                WhatsAppCloudChannel(
                    self.config, _FakeCredentialStore(), _FakeHttpTransport()
                ),
                self.config,
                _FakeCredentialStore(),
                to="+4915112345678",
                text="Hi",
            )
        self.assertIn("未配置", str(ctx.exception))

    def test_send_validates_before_touching_channel(self):
        channel = _FakeChannel()
        with self.assertRaises(MessagingError):
            send_text(
                channel, self.config, self.store, to="bad", text="Hi"
            )
        with self.assertRaises(MessagingError):
            send_text(
                channel,
                self.config,
                self.store,
                to="+4915112345678",
                text="x" * 4001,
            )
        self.assertEqual(channel.sends, [])

    def test_channel_failure_is_explicit(self):
        channel = _FakeChannel()
        channel.fail_list = RuntimeError("boom")
        with self.assertRaises(MessagingError) as ctx:
            list_threads(channel, self.config, self.store)
        self.assertIn("RuntimeError", str(ctx.exception))

    def test_whatsapp_driver_read_unavailable_surfaces(self):
        http = _FakeHttpTransport()
        driver = WhatsAppCloudChannel(
            self.config, self.store, http_transport=http
        )
        with self.assertRaises(MessagingError) as ctx:
            list_threads(driver, self.config, self.store)
        self.assertIn("webhook", str(ctx.exception))


class MessagingAttachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(self.root / "kernel.db"))
        self.channel = _FakeChannel()
        self.config = _config()
        self.store = _store_with_secret()
        self.attachment = attach_messaging_tools(
            self.fabric,
            self.body,
            config=self.config,
            channel=self.channel,
            credential_store=self.store,
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_all_three_actions_registered_with_effect_classes(self):
        descriptors = {
            item.action_id: item
            for item in (
                self.fabric.descriptor(LIST_ACTION_ID),
                self.fabric.descriptor(READ_ACTION_ID),
                self.fabric.descriptor(SEND_ACTION_ID),
            )
        }
        self.assertEqual(descriptors[LIST_ACTION_ID].effect_class, "read_only")
        self.assertEqual(descriptors[READ_ACTION_ID].effect_class, "read_only")
        self.assertEqual(
            descriptors[SEND_ACTION_ID].effect_class, "irreversible_side_effect"
        )
        send_tags = self.fabric.descriptor(SEND_ACTION_ID).tags
        self.assertIn("approval:send", send_tags)
        self.assertEqual(
            set(self.attachment.action_ids),
            {LIST_ACTION_ID, READ_ACTION_ID, SEND_ACTION_ID},
        )

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (LIST_ACTION_ID, READ_ACTION_ID, SEND_ACTION_ID):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_unconfigured_probe_reports_unavailable(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "probe.db"))
        try:
            handle = attach_messaging_tools(fabric, body, config=None)
            try:
                for action_id in (LIST_ACTION_ID, READ_ACTION_ID, SEND_ACTION_ID):
                    availability = fabric.availability(action_id)
                    self.assertEqual(availability.state, "unavailable")
                    self.assertIn("no messaging account", availability.reason)
            finally:
                handle.detach()
        finally:
            body.store.close()


class MessagingApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(self.root / "kernel.db"))
        self.channel = _FakeChannel()
        self.config = _config()
        self.store = _store_with_secret()
        self.attachment = attach_messaging_tools(
            self.fabric,
            self.body,
            config=self.config,
            channel=self.channel,
            credential_store=self.store,
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        store = ApprovalCardStore(str(self.root / "approvals.db"))
        runtime = ActionExecutionRuntime(
            self.fabric, self.body, approval_gate=ApprovalGate(store)
        )
        register_messaging_runtime(
            runtime,
            config=self.config,
            channel=self.channel,
            credential_store=self.store,
        )
        return runtime, store

    def _send_request(self, event_id: str, **overrides) -> ActionRequest:
        args = {"to": "+4915112345678", "text": "Dinner at 7?"}
        args.update(overrides)
        return ActionRequest(SEND_ACTION_ID, args, event_id=event_id)

    def test_send_denied_never_reaches_channel(self):
        runtime, store = self._runtime()
        execution = runtime.execute(self._send_request("evt-msg-deny-1"))
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        self.assertEqual(self.channel.sends, [])
        store.decide(store.pending_requests()[0].request_id, "deny")
        retry = runtime.execute(self._send_request("evt-msg-deny-2"))
        self.assertFalse(retry.success)
        self.assertIn("approval_required", retry.error or "")
        self.assertEqual(self.channel.sends, [])

    def test_send_approved_goes_through_and_verifies(self):
        runtime, store = self._runtime()
        first = runtime.execute(self._send_request("evt-msg-ok-1"))
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(self._send_request("evt-msg-ok-1"))
        self.assertTrue(second.success, second.error)
        self.assertEqual(len(self.channel.sends), 1)
        self.assertTrue(second.verification.verified)
        self.assertIn("message id", second.verification.reason.lower())

    def test_send_replay_refused(self):
        runtime, store = self._runtime()
        runtime.execute(self._send_request("evt-msg-replay-1"))
        # always_allow installs an auto-allow rule, so later dispatches
        # pass the gate and reach the replay guard.
        store.decide(store.pending_requests()[0].request_id, "always_allow")
        first = runtime.execute(self._send_request("evt-msg-replay-1"))
        self.assertTrue(first.success, first.error)
        # No new approval card is needed: the replay guard refuses the
        # redispatch before the channel is touched again.
        second = runtime.execute(self._send_request("evt-msg-replay-1"))
        self.assertFalse(second.success)
        self.assertIn("replay refused", second.error or "")
        self.assertEqual(len(self.channel.sends), 1)

    def test_send_validates_inputs_after_approval(self):
        runtime, store = self._runtime()
        first = runtime.execute(self._send_request("evt-msg-bad-1", text="   "))
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(self._send_request("evt-msg-bad-1", text="   "))
        self.assertFalse(second.success)
        self.assertIn("must not be empty", second.error or "")
        self.assertEqual(self.channel.sends, [])

    def test_read_actions_run_ungated(self):
        self.channel.add_thread(
            "t9", "+491519999999", [_message(thread_id="t9", text="Ping")]
        )
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(LIST_ACTION_ID, {"limit": 5}, event_id="evt-list-1")
        )
        self.assertTrue(execution.success, execution.error)
        report = json.loads(execution.body_result.output)
        self.assertEqual(report["thread_count"], 1)
        self.assertEqual(report["threads"][0]["peer"], "+491519999999")


class MessagingSkillTests(unittest.TestCase):
    def test_repo_messaging_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        messaging = [
            item for item in report.tier1 if item.skill_name == "messaging"
        ]
        self.assertEqual(len(messaging), 1, report.to_dict())
        self.assertTrue(messaging[0].passed, messaging[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()

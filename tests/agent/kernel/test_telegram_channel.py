from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.channel import ChannelMessage, ChannelOutboundMedia
from agent.kernel.outbound_media import (
    OutboundMediaAuthorizationError,
    OutboundMediaPathPolicy,
)
from agent.kernel.telegram_channel import (
    TelegramBotApiChannel,
    TelegramChannelError,
    split_utf16_message,
    utf16_len,
)


class _Response:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _message_update(update_id=1, chat_id=4, text="hello ZN"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 2,
            "text": text,
            "from": {"id": 3},
            "chat": {"id": chat_id, "type": "private"},
        },
    }


class TelegramChannelTests(unittest.TestCase):
    def test_utf16_limit_counts_non_bmp_as_two_units(self):
        self.assertEqual(utf16_len("a😀b"), 4)
        chunks = split_utf16_message("😀" * 30, 32)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(utf16_len(chunk) <= 32 for chunk in chunks))

    def test_poll_normalizes_message_thread_and_advances_offset(self):
        client = _Client(
            [
                _Response(
                    {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 40,
                                "message": {
                                    "message_id": 9,
                                    "message_thread_id": 7,
                                    "text": "hello ZN",
                                    "from": {"id": 12},
                                    "chat": {
                                        "id": -100,
                                        "type": "supergroup",
                                        "title": "room",
                                    },
                                },
                            }
                        ],
                    }
                )
            ]
        )
        adapter = TelegramBotApiChannel("token", allow_all=True, client=client)
        events = adapter.poll(timeout=10)
        self.assertEqual(events[0].conversation_id, "-100")
        self.assertEqual(events[0].sender_id, "12")
        self.assertEqual(events[0].message_id, "9")
        self.assertEqual(events[0].thread_id, "7")
        self.assertEqual(adapter.offset, 41)
        self.assertEqual(client.calls[0][1]["json"]["timeout"], 10)

    def test_default_inbound_authorization_is_deny_all(self):
        client = _Client([_Response({"ok": True, "result": [_message_update()]})])
        adapter = TelegramBotApiChannel("token", client=client)
        self.assertFalse(adapter.inbound_authorized)
        self.assertEqual(adapter.poll(), [])
        self.assertEqual(adapter.offset, 2)

    def test_allowed_chat_ids_filter_without_starting_another_agent(self):
        client = _Client(
            [
                _Response(
                    {
                        "ok": True,
                        "result": [
                            _message_update(
                                update_id=1,
                                chat_id=4,
                                text="ignored",
                            ),
                            _message_update(
                                update_id=2,
                                chat_id=5,
                                text="accepted",
                            ),
                        ],
                    }
                )
            ]
        )
        adapter = TelegramBotApiChannel("token", allowed_chat_ids=[5], client=client)
        events = adapter.poll()
        self.assertTrue(adapter.inbound_authorized)
        self.assertEqual([event.text for event in events], ["accepted"])
        self.assertEqual(adapter.offset, 3)

    def test_send_preserves_thread_reply_and_splits_long_text(self):
        long_text = "😀" * 3000
        chunks = split_utf16_message(long_text)
        responses = [
            _Response({"ok": True, "result": {"message_id": index + 100}})
            for index in range(len(chunks))
        ]
        client = _Client(responses)
        adapter = TelegramBotApiChannel("token", client=client)
        delivery = adapter.send(
            ChannelMessage(
                channel="telegram",
                conversation_id="77",
                text=long_text,
                thread_id="8",
                reply_to_message_id="9",
            )
        )
        self.assertTrue(delivery.ok)
        self.assertGreater(len(client.calls), 1)
        first = client.calls[0][1]["json"]
        self.assertEqual(first["message_thread_id"], 8)
        self.assertEqual(first["reply_parameters"], {"message_id": 9})
        for _url, call in client.calls:
            self.assertLessEqual(utf16_len(call["json"]["text"]), 4096)

    def test_send_authorizes_then_uploads_resident_nominated_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outbound"
            root.mkdir()
            artifact = root / "result.txt"
            artifact.write_text("verified resident artifact", encoding="utf-8")
            client = _Client(
                [
                    _Response({"ok": True, "result": {"message_id": 100}}),
                    _Response({"ok": True, "result": {"message_id": 101}}),
                ]
            )
            adapter = TelegramBotApiChannel(
                "token",
                client=client,
                outbound_media_policy=OutboundMediaPathPolicy([root]),
            )

            delivery = adapter.send(
                ChannelMessage(
                    channel="telegram",
                    conversation_id="77",
                    text="completed",
                    thread_id="8",
                    reply_to_message_id="9",
                    attachments=(
                        ChannelOutboundMedia(
                            nomination_id="media-1",
                            local_path=str(artifact.resolve()),
                            file_name="answer.txt",
                            mime_type="text/plain",
                        ),
                    ),
                )
            )

            self.assertEqual(delivery.message_ids, ("100", "101"))
            self.assertEqual(delivery.metadata, {"chunks": 1, "attachments": 1})
            self.assertIn("sendMessage", client.calls[0][0])
            upload_url, upload = client.calls[1]
            self.assertIn("sendDocument", upload_url)
            self.assertNotIn("json", upload)
            self.assertEqual(upload["data"]["chat_id"], "77")
            self.assertEqual(upload["data"]["message_thread_id"], 8)
            self.assertEqual(upload["files"]["document"][0], "answer.txt")
            self.assertEqual(upload["files"]["document"][2], "text/plain")

    def test_attachment_only_delivery_replies_on_document_without_empty_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outbound"
            root.mkdir()
            artifact = root / "result.bin"
            artifact.write_bytes(b"result")
            client = _Client([_Response({"ok": True, "result": {"message_id": 101}})])
            adapter = TelegramBotApiChannel(
                "token",
                client=client,
                outbound_media_policy=OutboundMediaPathPolicy([root]),
            )

            delivery = adapter.send(
                ChannelMessage(
                    channel="telegram",
                    conversation_id="77",
                    text="",
                    reply_to_message_id="9",
                    attachments=(
                        ChannelOutboundMedia(
                            nomination_id="media-1",
                            local_path=str(artifact.resolve()),
                        ),
                    ),
                )
            )

            self.assertEqual(len(client.calls), 1)
            self.assertIn("sendDocument", client.calls[0][0])
            self.assertEqual(
                client.calls[0][1]["data"]["reply_parameters"],
                '{"message_id":9}',
            )
            self.assertEqual(delivery.metadata, {"chunks": 0, "attachments": 1})

    def test_unauthorized_outbound_path_is_rejected_before_network_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outbound"
            root.mkdir()
            outside = Path(tmp) / "private.txt"
            outside.write_text("secret", encoding="utf-8")
            client = _Client([])
            adapter = TelegramBotApiChannel(
                "token",
                client=client,
                outbound_media_policy=OutboundMediaPathPolicy([root]),
            )

            with self.assertRaises(OutboundMediaAuthorizationError):
                adapter.send(
                    ChannelMessage(
                        channel="telegram",
                        conversation_id="77",
                        text="do not leak",
                        attachments=(
                            ChannelOutboundMedia(
                                nomination_id="media-1",
                                local_path=str(outside.resolve()),
                            ),
                        ),
                    )
                )

            self.assertEqual(client.calls, [])

    def test_transport_error_never_echoes_bot_token(self):
        class BrokenClient:
            def post(self, url, **kwargs):
                raise RuntimeError(f"failed URL {url}")

        token = "12345:super-secret"
        adapter = TelegramBotApiChannel(token, client=BrokenClient())
        with self.assertRaises(TelegramChannelError) as caught:
            adapter.poll()
        self.assertNotIn(token, str(caught.exception))
        self.assertIn("<redacted-token>", str(caught.exception))

    def test_from_zn_config_uses_explicit_zn_channel_authorization(self):
        adapter = TelegramBotApiChannel.from_zn_config(
            {"channels": {"telegram": {"allowed_chat_ids": [1, 2]}}},
            environ={"TELEGRAM_BOT_TOKEN": "env-token"},
            client=_Client([]),
        )
        self.assertEqual(adapter.token, "env-token")
        self.assertEqual(adapter.allowed_chat_ids, {"1", "2"})
        self.assertFalse(adapter.allow_all)
        self.assertTrue(adapter.inbound_authorized)

        open_adapter = TelegramBotApiChannel.from_zn_config(
            {"channels": {"telegram": {"allow_all": True}}},
            environ={"TELEGRAM_BOT_TOKEN": "env-token"},
            client=_Client([]),
        )
        self.assertTrue(open_adapter.allow_all)
        self.assertTrue(open_adapter.inbound_authorized)

    @patch("agent.kernel.telegram_channel.build_telegram_http_client")
    def test_from_zn_config_routes_network_options_into_zn_transport(self, build_client):
        built = _Client([])
        build_client.return_value = built
        adapter = TelegramBotApiChannel.from_zn_config(
            {
                "channels": {
                    "telegram": {
                        "allow_all": True,
                        "network": {
                            "fallback_ips": ["149.154.167.220"],
                            "discover_fallback_ips": True,
                            "proxy_url": "http://proxy.example:8080",
                        },
                    }
                }
            },
            environ={"TELEGRAM_BOT_TOKEN": "env-token"},
        )

        self.assertIs(adapter._client, built)
        build_client.assert_called_once_with(
            base_url="https://api.telegram.org",
            fallback_ips=("149.154.167.220",),
            discover=True,
            proxy_url="http://proxy.example:8080",
            environ={"TELEGRAM_BOT_TOKEN": "env-token"},
            timeout=35.0,
        )


if __name__ == "__main__":
    unittest.main()

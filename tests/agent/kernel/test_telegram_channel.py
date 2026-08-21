from __future__ import annotations

import unittest

from agent.kernel.channel import ChannelMessage
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
                                    "chat": {"id": -100, "type": "supergroup", "title": "room"},
                                },
                            }
                        ],
                    }
                )
            ]
        )
        adapter = TelegramBotApiChannel("token", client=client)
        events = adapter.poll(timeout=10)
        self.assertEqual(events[0].conversation_id, "-100")
        self.assertEqual(events[0].sender_id, "12")
        self.assertEqual(events[0].message_id, "9")
        self.assertEqual(events[0].thread_id, "7")
        self.assertEqual(adapter.offset, 41)
        self.assertEqual(client.calls[0][1]["json"]["timeout"], 10)

    def test_allowed_chat_ids_filter_without_starting_another_agent(self):
        client = _Client(
            [
                _Response(
                    {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 1,
                                "message": {
                                    "message_id": 2,
                                    "text": "ignored",
                                    "from": {"id": 3},
                                    "chat": {"id": 4, "type": "private"},
                                },
                            }
                        ],
                    }
                )
            ]
        )
        adapter = TelegramBotApiChannel("token", allowed_chat_ids=[5], client=client)
        self.assertEqual(adapter.poll(), [])
        self.assertEqual(adapter.offset, 2)

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

    def test_from_zn_config_uses_zn_channel_config(self):
        adapter = TelegramBotApiChannel.from_zn_config(
            {"channels": {"telegram": {"allowed_chat_ids": [1, 2]}}},
            environ={"TELEGRAM_BOT_TOKEN": "env-token"},
            client=_Client([]),
        )
        self.assertEqual(adapter.token, "env-token")
        self.assertEqual(adapter.allowed_chat_ids, {"1", "2"})


if __name__ == "__main__":
    unittest.main()

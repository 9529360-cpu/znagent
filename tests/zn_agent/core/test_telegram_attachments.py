from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.channel import ResidentChannelService
from zn_agent.core.telegram_channel import (
    DEFAULT_TELEGRAM_ATTACHMENT_MAX_BYTES,
    LOCAL_TELEGRAM_ATTACHMENT_MAX_BYTES,
    TelegramBotApiChannel,
)


class _Response:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload


class _StreamResponse:
    def __init__(self, chunks, *, status_code=200, headers=None, text=""):
        self.chunks = list(chunks)
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_bytes(self):
        yield from self.chunks


class _Client:
    def __init__(self, posts, streams=()):
        self.posts = list(posts)
        self.streams = list(streams)
        self.post_calls = []
        self.stream_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.posts.pop(0)

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        return self.streams.pop(0)


def _document_update(*, file_size=4, caption=""):
    message = {
        "message_id": 7,
        "from": {"id": 12},
        "chat": {"id": 55, "type": "private"},
        "document": {
            "file_id": "remote-file-id",
            "file_unique_id": "unique-doc",
            "file_name": "notes.txt",
            "mime_type": "text/plain",
            "file_size": file_size,
        },
    }
    if caption:
        message["caption"] = caption
    return {"update_id": 90, "message": message}


class TelegramAttachmentTests(unittest.TestCase):
    def test_attachment_only_message_downloads_to_zn_cache_and_becomes_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _Client(
                [
                    _Response({"ok": True, "result": [_document_update()]}),
                    _Response(
                        {
                            "ok": True,
                            "result": {
                                "file_path": "documents/file_7.txt",
                                "file_size": 4,
                            },
                        }
                    ),
                ],
                [
                    _StreamResponse(
                        [b"test"],
                        headers={"content-length": "4"},
                    )
                ],
            )
            adapter = TelegramBotApiChannel(
                "token",
                allow_all=True,
                client=client,
                attachment_root=tmp,
            )

            events = adapter.poll()

            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertIn("Received channel attachment", event.text)
            self.assertEqual(len(event.attachments), 1)
            attachment = event.attachments[0]
            self.assertEqual(attachment.kind, "document")
            self.assertEqual(attachment.mime_type, "text/plain")
            self.assertEqual(attachment.size_bytes, 4)
            self.assertIsNone(attachment.error)
            self.assertTrue(attachment.local_path)
            cached = Path(attachment.local_path or "")
            self.assertEqual(cached.parent.resolve(), Path(tmp).resolve())
            self.assertEqual(cached.read_bytes(), b"test")
            self.assertEqual(len(client.stream_calls), 1)
            self.assertNotIn("token", cached.name)

    def test_caption_remains_primary_text_while_attachment_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _Client(
                [
                    _Response(
                        {
                            "ok": True,
                            "result": [_document_update(caption="please inspect")],
                        }
                    ),
                    _Response(
                        {
                            "ok": True,
                            "result": {"file_path": "documents/file.txt"},
                        }
                    ),
                ],
                [_StreamResponse([b"test"])],
            )
            adapter = TelegramBotApiChannel(
                "token",
                allow_all=True,
                client=client,
                attachment_root=tmp,
            )
            event = adapter.poll()[0]
            self.assertEqual(event.text, "please inspect")
            self.assertEqual(len(event.attachments), 1)

    def test_declared_oversize_attachment_never_calls_get_file_or_download(self):
        client = _Client(
            [
                _Response(
                    {
                        "ok": True,
                        "result": [
                            _document_update(
                                file_size=DEFAULT_TELEGRAM_ATTACHMENT_MAX_BYTES + 1
                            )
                        ],
                    }
                )
            ]
        )
        adapter = TelegramBotApiChannel("token", allow_all=True, client=client)

        event = adapter.poll()[0]

        self.assertEqual(len(client.post_calls), 1)
        self.assertEqual(client.stream_calls, [])
        self.assertIn("exceeds ZN limit", event.attachments[0].error or "")
        self.assertIn("unavailable", event.text)

    def test_streaming_limit_removes_partial_file_and_preserves_failure_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _Client(
                [
                    _Response({"ok": True, "result": [_document_update(file_size=2)]}),
                    _Response(
                        {
                            "ok": True,
                            "result": {"file_path": "documents/file.txt"},
                        }
                    ),
                ],
                [_StreamResponse([b"1234", b"5678"])],
            )
            adapter = TelegramBotApiChannel(
                "token",
                allow_all=True,
                client=client,
                attachment_root=tmp,
                max_attachment_bytes=5,
            )

            event = adapter.poll()[0]

            self.assertIn("exceeds ZN limit while downloading", event.attachments[0].error or "")
            self.assertIsNone(event.attachments[0].local_path)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_custom_bot_api_keeps_mature_two_gigabyte_default(self):
        adapter = TelegramBotApiChannel(
            "token",
            base_url="http://localhost:8081",
            allow_all=True,
            client=_Client([]),
        )
        self.assertEqual(adapter.max_attachment_bytes, LOCAL_TELEGRAM_ATTACHMENT_MAX_BYTES)

    def test_attachment_payload_reaches_same_resident_submit(self):
        class _Resident:
            def __init__(self):
                self.calls = []

            def submit(self, task, **kwargs):
                self.calls.append((task, kwargs))
                return SimpleNamespace(success=True, response="seen", reason="")

        class _Adapter:
            name = "telegram"

            def __init__(self, event):
                self.event = event
                self.sent = []

            def poll(self, *, timeout=0.0):
                return [self.event]

            def send(self, message):
                self.sent.append(message)
                return SimpleNamespace(ok=True)

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            client = _Client(
                [
                    _Response({"ok": True, "result": [_document_update()]}),
                    _Response(
                        {
                            "ok": True,
                            "result": {"file_path": "documents/file.txt"},
                        }
                    ),
                ],
                [_StreamResponse([b"test"])],
            )
            telegram = TelegramBotApiChannel(
                "token",
                allow_all=True,
                client=client,
                attachment_root=tmp,
            )
            event = telegram.poll()[0]
            resident = _Resident()
            adapter = _Adapter(event)

            ResidentChannelService(resident, adapter).run_once()

            payload = resident.calls[0][1]["payload"]
            self.assertEqual(payload["attachments"][0]["kind"], "document")
            self.assertEqual(payload["attachments"][0]["remote_id"], "remote-file-id")
            self.assertTrue(payload["attachments"][0]["local_path"])
            self.assertEqual(adapter.sent[0].text, "seen")


if __name__ == "__main__":
    unittest.main()

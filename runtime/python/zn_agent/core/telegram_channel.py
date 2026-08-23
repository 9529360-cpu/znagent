from __future__ import annotations

"""ZN-owned Telegram Bot API channel.

This is source extraction from the mature Telegram implementation. The current
slice keeps UTF-16 message limits, thread/reply routing, long-poll offsets,
explicit inbound authorization, ZN-owned network fallback/proxy handling,
bounded inbound attachment caching, and policy-authorized outbound documents
while leaving old gateway/AIAgent/session ownership behind.
"""

import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .channel import ChannelAttachment, ChannelDelivery, ChannelEvent, ChannelMessage
from .home import get_zn_home
from .outbound_media import OutboundMediaPathPolicy
from .telegram_network import build_telegram_http_client, parse_fallback_ip_env


DEFAULT_TELEGRAM_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
LOCAL_TELEGRAM_ATTACHMENT_MAX_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_TELEGRAM_BASE_URL = "https://api.telegram.org"


class TelegramChannelError(RuntimeError):
    pass


def utf16_len(value: str) -> int:
    return len(str(value or "").encode("utf-16-le")) // 2


def _prefix_within_utf16_limit(value: str, limit: int) -> str:
    text = str(value or "")
    if utf16_len(text) <= limit:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if utf16_len(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def split_utf16_message(value: str, limit: int = 4096) -> list[str]:
    text = str(value or "")
    if not text:
        return [""]
    cap = max(32, int(limit))
    chunks: list[str] = []
    remaining = text
    while utf16_len(remaining) > cap:
        prefix = _prefix_within_utf16_limit(remaining, cap)
        if not prefix:
            break
        floor = max(1, int(len(prefix) * 0.55))
        cut = -1
        for delimiter in ("\n\n", "\n", " "):
            candidate = prefix.rfind(delimiter, floor)
            if candidate > cut:
                cut = candidate + len(delimiter)
        if cut <= 0:
            cut = len(prefix)
        chunk = remaining[:cut].rstrip()
        if not chunk:
            chunk = remaining[: len(prefix)]
            cut = len(prefix)
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining or not chunks:
        chunks.append(remaining)
    return chunks


def _safe_error(error: object, token: str) -> str:
    text = str(error or "")
    if token:
        text = text.replace(token, "<redacted-token>")
    return text[:1500]


def _configured_fallback_ips(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return parse_fallback_ip_env(raw)
    if isinstance(raw, Iterable) and not isinstance(raw, (bytes, bytearray, Mapping)):
        return parse_fallback_ip_env(",".join(str(item) for item in raw))
    raise ValueError(
        "ZN channels.telegram.network.fallback_ips must be a list or comma-separated string"
    )


def _safe_filename(value: str | None, *, fallback: str) -> str:
    raw = Path(str(value or "")).name.strip() or fallback
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw).strip(" .")
    return (raw or fallback)[:180]


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


class TelegramBotApiChannel:
    name = "telegram"
    MAX_MESSAGE_LENGTH = 4096

    def __init__(
        self,
        token: str,
        *,
        base_url: str = _DEFAULT_TELEGRAM_BASE_URL,
        allowed_chat_ids: Iterable[str | int] | None = None,
        allow_all: bool = False,
        client: Any | None = None,
        request_timeout: float = 35.0,
        fallback_ips: Iterable[str] = (),
        discover_fallback_ips: bool = False,
        proxy_url: str | None = None,
        environ: Mapping[str, str] | None = None,
        attachment_root: str | Path | None = None,
        max_attachment_bytes: int | None = None,
        outbound_media_policy: OutboundMediaPathPolicy | None = None,
    ):
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("Telegram bot token must not be empty")
        self.base_url = str(base_url or _DEFAULT_TELEGRAM_BASE_URL).rstrip("/")
        self.allowed_chat_ids = (
            {str(item) for item in allowed_chat_ids}
            if allowed_chat_ids is not None
            else None
        )
        self.allow_all = bool(allow_all)
        self.request_timeout = max(1.0, float(request_timeout))
        self.fallback_ips = tuple(str(item) for item in fallback_ips)
        self.discover_fallback_ips = bool(discover_fallback_ips)
        self.proxy_url = str(proxy_url or "").strip() or None
        self.attachment_root = Path(
            attachment_root
            if attachment_root is not None
            else get_zn_home() / "channels" / "telegram" / "attachments"
        ).expanduser()
        if max_attachment_bytes is None:
            self.max_attachment_bytes = (
                DEFAULT_TELEGRAM_ATTACHMENT_MAX_BYTES
                if self.base_url == _DEFAULT_TELEGRAM_BASE_URL
                else LOCAL_TELEGRAM_ATTACHMENT_MAX_BYTES
            )
        else:
            self.max_attachment_bytes = max(1, int(max_attachment_bytes))
        self.outbound_media_policy = outbound_media_policy or OutboundMediaPathPolicy.for_zn_home(
            max_bytes=self.max_attachment_bytes
        )
        self._client = client or build_telegram_http_client(
            base_url=self.base_url,
            fallback_ips=self.fallback_ips,
            discover=self.discover_fallback_ips,
            proxy_url=self.proxy_url,
            environ=environ,
            timeout=self.request_timeout,
        )
        self._owns_client = client is None
        self._offset = 0

    @classmethod
    def from_zn_config(
        cls,
        config: Mapping[str, Any],
        *,
        environ: Mapping[str, str] | None = None,
        client: Any | None = None,
    ) -> "TelegramBotApiChannel":
        env = environ if environ is not None else os.environ
        channels = config.get("channels") or {}
        if not isinstance(channels, Mapping):
            raise ValueError("ZN channels config must be a mapping")
        telegram = channels.get("telegram") or {}
        if not isinstance(telegram, Mapping):
            raise ValueError("ZN channels.telegram config must be a mapping")
        network = telegram.get("network") or {}
        if not isinstance(network, Mapping):
            raise ValueError("ZN channels.telegram.network config must be a mapping")

        token = str(telegram.get("token") or env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        allowed = telegram.get("allowed_chat_ids")
        if isinstance(allowed, (str, int)):
            allowed = [allowed]
        fallback_ips = _configured_fallback_ips(
            network.get("fallback_ips", telegram.get("fallback_ips"))
        )
        discover = bool(
            network.get(
                "discover_fallback_ips",
                telegram.get("discover_fallback_ips", False),
            )
        )
        proxy_url = str(
            network.get("proxy_url")
            or network.get("proxy")
            or telegram.get("proxy_url")
            or telegram.get("proxy")
            or env.get("TELEGRAM_PROXY")
            or ""
        ).strip() or None
        attachment_root = telegram.get("attachment_root")
        max_attachment_bytes = telegram.get("max_attachment_bytes")

        return cls(
            token,
            base_url=str(telegram.get("base_url") or _DEFAULT_TELEGRAM_BASE_URL),
            allowed_chat_ids=allowed if isinstance(allowed, list) else None,
            allow_all=bool(telegram.get("allow_all", False)),
            client=client,
            request_timeout=float(telegram.get("request_timeout") or 35.0),
            fallback_ips=fallback_ips,
            discover_fallback_ips=discover,
            proxy_url=proxy_url,
            environ=env,
            attachment_root=(str(attachment_root) if attachment_root else None),
            max_attachment_bytes=(
                int(max_attachment_bytes)
                if max_attachment_bytes is not None
                else None
            ),
        )

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def inbound_authorized(self) -> bool:
        return self.allow_all or bool(self.allowed_chat_ids)

    def poll(self, *, timeout: float = 0.0) -> list[ChannelEvent]:
        poll_timeout = max(0, min(50, int(timeout)))
        payload: dict[str, Any] = {
            "timeout": poll_timeout,
            "allowed_updates": [
                "message",
                "edited_message",
                "channel_post",
                "edited_channel_post",
            ],
        }
        if self._offset > 0:
            payload["offset"] = self._offset
        raw = self._api(
            "getUpdates",
            payload,
            timeout=max(self.request_timeout, poll_timeout + 10),
        )
        updates = raw.get("result") or []
        if not isinstance(updates, list):
            raise TelegramChannelError("Telegram getUpdates returned invalid result")

        events: list[ChannelEvent] = []
        max_update_id = self._offset - 1
        for update in updates:
            if not isinstance(update, dict):
                continue
            try:
                update_id = int(update.get("update_id"))
            except (TypeError, ValueError):
                update_id = -1
            max_update_id = max(max_update_id, update_id)
            event = self._event_from_update(update)
            if event is not None:
                events.append(event)
        if max_update_id >= 0:
            self._offset = max(self._offset, max_update_id + 1)
        return events

    def send(self, message: ChannelMessage) -> ChannelDelivery:
        if message.channel and message.channel != self.name:
            raise ValueError(f"Telegram adapter cannot send channel {message.channel!r}")
        chat_id = str(message.conversation_id or "").strip()
        if not chat_id:
            raise ValueError("Telegram conversation_id must not be empty")
        text = str(message.text or "")
        chunks = split_utf16_message(text, self.MAX_MESSAGE_LENGTH) if text else []
        authorized_media = tuple(
            (item, self.outbound_media_policy.authorize(item.local_path))
            for item in message.attachments
        )
        sent_ids: list[str] = []
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "link_preview_options": {"is_disabled": True},
            }
            if message.thread_id:
                payload["message_thread_id"] = (
                    int(message.thread_id)
                    if str(message.thread_id).isdigit()
                    else message.thread_id
                )
            if index == 0 and message.reply_to_message_id:
                reply_id: Any = message.reply_to_message_id
                if str(reply_id).isdigit():
                    reply_id = int(str(reply_id))
                payload["reply_parameters"] = {"message_id": reply_id}
            raw = self._api("sendMessage", payload)
            result = raw.get("result") or {}
            if isinstance(result, dict) and result.get("message_id") is not None:
                sent_ids.append(str(result["message_id"]))

        for index, (item, authorized) in enumerate(authorized_media):
            data: dict[str, Any] = {"chat_id": chat_id}
            if message.thread_id:
                data["message_thread_id"] = (
                    int(message.thread_id)
                    if str(message.thread_id).isdigit()
                    else message.thread_id
                )
            if not chunks and index == 0 and message.reply_to_message_id:
                reply_id: Any = message.reply_to_message_id
                if str(reply_id).isdigit():
                    reply_id = int(str(reply_id))
                data["reply_parameters"] = json.dumps(
                    {"message_id": reply_id}, separators=(",", ":")
                )
            file_name = _safe_filename(
                item.file_name,
                fallback=authorized.path.name,
            )
            mime_type = str(item.mime_type or "").strip() or "application/octet-stream"
            with authorized.path.open("rb") as handle:
                raw = self._api_upload(
                    "sendDocument",
                    data,
                    files={"document": (file_name, handle, mime_type)},
                )
            result = raw.get("result") or {}
            if isinstance(result, dict) and result.get("message_id") is not None:
                sent_ids.append(str(result["message_id"]))

        return ChannelDelivery(
            ok=True,
            channel=self.name,
            conversation_id=chat_id,
            message_ids=tuple(sent_ids),
            metadata={"chunks": len(chunks), "attachments": len(authorized_media)},
        )

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def _event_from_update(self, update: dict[str, Any]) -> ChannelEvent | None:
        update_type = ""
        message: dict[str, Any] | None = None
        for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
            value = update.get(key)
            if isinstance(value, dict):
                update_type = key
                message = value
                break
        if message is None:
            return None

        chat = message.get("chat") or {}
        if not isinstance(chat, dict) or chat.get("id") is None:
            return None
        chat_id = str(chat["id"])
        if not self.allow_all:
            if self.allowed_chat_ids is None or chat_id not in self.allowed_chat_ids:
                return None

        sender = message.get("from") or message.get("sender_chat") or {}
        sender_id = str(sender.get("id") or chat_id) if isinstance(sender, dict) else chat_id
        attachments = self._attachments_from_message(message)
        text = str(message.get("text") or message.get("caption") or "").strip()
        if not text and attachments:
            text = self._attachment_event_text(attachments)
        if not text:
            return None

        metadata: dict[str, Any] = {
            "update_id": update.get("update_id"),
            "update_type": update_type,
            "chat_type": chat.get("type"),
            "chat_title": chat.get("title") or chat.get("username") or "",
        }
        if attachments:
            metadata["media_types"] = list(dict.fromkeys(item.kind for item in attachments))
        reply = message.get("reply_to_message")
        if isinstance(reply, dict) and reply.get("message_id") is not None:
            metadata["reply_to_message_id"] = str(reply["message_id"])

        thread_id = message.get("message_thread_id")
        return ChannelEvent(
            channel=self.name,
            conversation_id=chat_id,
            sender_id=sender_id,
            text=text,
            message_id=(
                str(message["message_id"])
                if message.get("message_id") is not None
                else None
            ),
            thread_id=str(thread_id) if thread_id is not None else None,
            attachments=attachments,
            metadata=metadata,
        )

    def _attachments_from_message(
        self,
        message: Mapping[str, Any],
    ) -> tuple[ChannelAttachment, ...]:
        specs: list[tuple[str, Mapping[str, Any], str | None, str | None]] = []
        photos = message.get("photo")
        if isinstance(photos, list):
            candidates = [item for item in photos if isinstance(item, Mapping)]
            if candidates:
                photo = max(
                    candidates,
                    key=lambda item: (
                        _int_or_none(item.get("file_size")) or 0,
                        (_int_or_none(item.get("width")) or 0)
                        * (_int_or_none(item.get("height")) or 0),
                    ),
                )
                unique = str(photo.get("file_unique_id") or uuid.uuid4().hex[:12])
                specs.append(("image", photo, f"photo-{unique}.jpg", "image/jpeg"))

        for key, kind in (
            ("document", "document"),
            ("audio", "audio"),
            ("voice", "voice"),
            ("video", "video"),
            ("video_note", "video"),
            ("animation", "animation"),
            ("sticker", "sticker"),
        ):
            raw = message.get(key)
            if not isinstance(raw, Mapping):
                continue
            file_name = str(raw.get("file_name") or "").strip() or None
            mime_type = str(raw.get("mime_type") or "").strip() or None
            specs.append((kind, raw, file_name, mime_type))

        return tuple(
            self._download_attachment(kind, raw, file_name=file_name, mime_type=mime_type)
            for kind, raw, file_name, mime_type in specs
        )

    def _download_attachment(
        self,
        kind: str,
        raw: Mapping[str, Any],
        *,
        file_name: str | None,
        mime_type: str | None,
    ) -> ChannelAttachment:
        remote_id = str(raw.get("file_id") or "").strip()
        unique_id = str(raw.get("file_unique_id") or uuid.uuid4().hex[:12]).strip()
        attachment_id = f"telegram-{unique_id[:80]}"
        declared_size = _int_or_none(raw.get("file_size"))
        metadata = {
            key: raw[key]
            for key in ("width", "height", "duration", "performer", "title")
            if raw.get(key) is not None
        }
        if not remote_id:
            return ChannelAttachment(
                attachment_id=attachment_id,
                kind=kind,
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=declared_size,
                error="Telegram attachment has no file_id",
                metadata=metadata,
            )
        if declared_size is not None and declared_size > self.max_attachment_bytes:
            return ChannelAttachment(
                attachment_id=attachment_id,
                kind=kind,
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=declared_size,
                remote_id=remote_id,
                error=(
                    f"Telegram attachment exceeds ZN limit: {declared_size} > "
                    f"{self.max_attachment_bytes} bytes"
                ),
                metadata=metadata,
            )

        try:
            file_response = self._api("getFile", {"file_id": remote_id})
            file_info = file_response.get("result") or {}
            if not isinstance(file_info, Mapping):
                raise TelegramChannelError("Telegram getFile returned invalid result")
            file_path = str(file_info.get("file_path") or "").strip()
            if not file_path:
                raise TelegramChannelError("Telegram getFile returned no file_path")
            resolved_size = _int_or_none(file_info.get("file_size")) or declared_size
            if resolved_size is not None and resolved_size > self.max_attachment_bytes:
                raise TelegramChannelError(
                    f"attachment exceeds ZN limit: {resolved_size} > "
                    f"{self.max_attachment_bytes} bytes"
                )
            local_path, actual_size = self._download_file_bytes(
                attachment_id,
                file_path,
                file_name=file_name,
                mime_type=mime_type,
            )
            return ChannelAttachment(
                attachment_id=attachment_id,
                kind=kind,
                file_name=Path(local_path).name,
                mime_type=mime_type,
                size_bytes=actual_size,
                local_path=local_path,
                remote_id=remote_id,
                metadata=metadata,
            )
        except Exception as exc:
            return ChannelAttachment(
                attachment_id=attachment_id,
                kind=kind,
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=declared_size,
                remote_id=remote_id,
                error=_safe_error(exc, self.token),
                metadata=metadata,
            )

    def _download_file_bytes(
        self,
        attachment_id: str,
        remote_path: str,
        *,
        file_name: str | None,
        mime_type: str | None,
    ) -> tuple[str, int]:
        fallback_ext = Path(remote_path).suffix
        if not fallback_ext and mime_type:
            fallback_ext = mimetypes.guess_extension(mime_type) or ""
        fallback_name = f"attachment{fallback_ext or '.bin'}"
        safe_name = _safe_filename(file_name, fallback=fallback_name)
        local_name = _safe_filename(
            f"{attachment_id}-{safe_name}",
            fallback=f"{attachment_id}.bin",
        )
        self.attachment_root.mkdir(parents=True, exist_ok=True)
        final_path = self.attachment_root / local_name
        temporary = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.part")
        url = f"{self.base_url}/file/bot{self.token}/{remote_path.lstrip('/')}"
        total = 0
        try:
            with self._client.stream(
                "GET",
                url,
                timeout=self.request_timeout,
            ) as response:
                status = int(getattr(response, "status_code", 0) or 0)
                if status < 200 or status >= 300:
                    detail = str(getattr(response, "text", "") or "").strip()
                    raise TelegramChannelError(
                        f"Telegram file download failed: {detail or f'HTTP {status}'}"
                    )
                content_length = _int_or_none(
                    getattr(response, "headers", {}).get("content-length")
                )
                if content_length is not None and content_length > self.max_attachment_bytes:
                    raise TelegramChannelError(
                        f"attachment exceeds ZN limit: {content_length} > "
                        f"{self.max_attachment_bytes} bytes"
                    )
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > self.max_attachment_bytes:
                            raise TelegramChannelError(
                                f"attachment exceeds ZN limit while downloading: {total} > "
                                f"{self.max_attachment_bytes} bytes"
                            )
                        handle.write(chunk)
            os.replace(temporary, final_path)
            return str(final_path.resolve()), total
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _attachment_event_text(attachments: tuple[ChannelAttachment, ...]) -> str:
        descriptions: list[str] = []
        for item in attachments:
            label = item.file_name or item.kind
            if item.error:
                descriptions.append(f"{item.kind} {label} (unavailable: {item.error})")
            elif item.local_path:
                descriptions.append(f"{item.kind} {label} ({item.local_path})")
            else:
                descriptions.append(f"{item.kind} {label}")
        return "Received channel attachment(s): " + "; ".join(descriptions)

    def _api(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/bot{self.token}/{method}"
        try:
            response = self._client.post(
                url,
                json=payload,
                timeout=float(timeout or self.request_timeout),
            )
        except Exception as exc:
            raise TelegramChannelError(
                f"Telegram {method} request failed: {_safe_error(exc, self.token)}"
            ) from exc

        status = int(getattr(response, "status_code", 0) or 0)
        try:
            data = response.json()
        except Exception as exc:
            raise TelegramChannelError(
                f"Telegram {method} returned invalid JSON (HTTP {status})"
            ) from exc
        if not isinstance(data, dict):
            raise TelegramChannelError(f"Telegram {method} returned invalid response")
        if status < 200 or status >= 300 or data.get("ok") is not True:
            detail = (
                data.get("description")
                or getattr(response, "text", "")
                or f"HTTP {status}"
            )
            raise TelegramChannelError(
                f"Telegram {method} failed: {_safe_error(detail, self.token)}"
            )
        return data

    def _api_upload(
        self,
        method: str,
        data: dict[str, Any],
        *,
        files: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.base_url}/bot{self.token}/{method}"
        try:
            response = self._client.post(
                url,
                data=data,
                files=files,
                timeout=self.request_timeout,
            )
        except Exception as exc:
            raise TelegramChannelError(
                f"Telegram {method} request failed: {_safe_error(exc, self.token)}"
            ) from exc

        status = int(getattr(response, "status_code", 0) or 0)
        try:
            payload = response.json()
        except Exception as exc:
            raise TelegramChannelError(
                f"Telegram {method} returned invalid JSON (HTTP {status})"
            ) from exc
        if not isinstance(payload, dict):
            raise TelegramChannelError(f"Telegram {method} returned invalid response")
        if status < 200 or status >= 300 or payload.get("ok") is not True:
            detail = (
                payload.get("description")
                or getattr(response, "text", "")
                or f"HTTP {status}"
            )
            raise TelegramChannelError(
                f"Telegram {method} failed: {_safe_error(detail, self.token)}"
            )
        return payload

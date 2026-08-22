from __future__ import annotations

"""ZN-owned communication channel contracts.

A channel is an I/O organ of the same resident ZN. It is not an agent runtime,
conversation owner or identity container. Platform adapters translate transport
specific events into ChannelEvent and translate ChannelMessage back to the
platform; resident cognition and continuity remain in the kernel.
"""

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, TYPE_CHECKING

from .models import utc_now

if TYPE_CHECKING:
    from .resident import ZNResidentRuntime


@dataclass(frozen=True, slots=True)
class ChannelAttachment:
    """One normalized file/media percept arriving through any channel.

    ``local_path`` points only to a ZN-owned cached copy created by the adapter;
    platform download URLs and credentials are deliberately not exposed to the
    resident. ``error`` preserves per-attachment failure evidence without
    dropping the surrounding message event.
    """

    attachment_id: str
    kind: str
    file_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    local_path: str | None = None
    remote_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChannelEvent:
    channel: str
    conversation_id: str
    sender_id: str
    text: str
    message_id: str | None = None
    thread_id: str | None = None
    event_id: str = field(default_factory=lambda: f"channel-{uuid.uuid4().hex[:12]}")
    metadata: dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=utc_now)
    # Appended rather than inserted so the original positional constructor
    # signature stays compatible during source migration.
    attachments: tuple[ChannelAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    channel: str
    conversation_id: str
    text: str
    thread_id: str | None = None
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Same compatibility rule as ChannelEvent: append new fields.
    attachments: tuple[ChannelAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelDelivery:
    ok: bool
    channel: str
    conversation_id: str
    message_ids: tuple[str, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    name: str

    def poll(self, *, timeout: float = 0.0) -> list[ChannelEvent]: ...

    def send(self, message: ChannelMessage) -> ChannelDelivery: ...

    def close(self) -> None: ...


class ResidentChannelService:
    """Bridge channel events into one existing resident and route replies out."""

    def __init__(
        self,
        resident: ZNResidentRuntime,
        adapter: ChannelAdapter,
        *,
        reply_failures: bool = False,
    ):
        self.resident = resident
        self.adapter = adapter
        self.reply_failures = bool(reply_failures)

    def run_once(self, *, timeout: float = 0.0) -> list[ChannelDelivery]:
        deliveries: list[ChannelDelivery] = []
        for event in self.adapter.poll(timeout=max(0.0, float(timeout))):
            result = self.resident.submit(
                event.text,
                kind="channel_message",
                payload={
                    "channel": event.channel,
                    "conversation_id": event.conversation_id,
                    "sender_id": event.sender_id,
                    "message_id": event.message_id,
                    "thread_id": event.thread_id,
                    "channel_event_id": event.event_id,
                    "attachments": [asdict(item) for item in event.attachments],
                    "channel_metadata": dict(event.metadata),
                },
            )
            response = str(result.response or "").strip()
            if not response and self.reply_failures and not result.success:
                response = str(result.reason or "ZN could not complete this request.").strip()
            if not response:
                continue
            deliveries.append(
                self.adapter.send(
                    ChannelMessage(
                        channel=event.channel,
                        conversation_id=event.conversation_id,
                        text=response,
                        thread_id=event.thread_id,
                        reply_to_message_id=event.message_id,
                    )
                )
            )
        return deliveries

    def close(self) -> None:
        self.adapter.close()

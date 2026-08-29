from __future__ import annotations

"""Resident-owned lifecycle for communication adapters.

Channels are sensory/motor organs of one ZN resident. They poll external reality,
enqueue percepts into the resident's durable event queue, and later deliver the
resident's durable outcomes. Channel threads never drive cognition themselves.
"""

import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .channel import ChannelAdapter, ChannelEvent, ChannelMessage
from .channel_delivery import ChannelDeliveryLedger, ChannelMediaNomination
from .config import load_zn_config
from .event_ingress import enqueue_event_once, stable_external_event_id
from .health_observation import ResidentHealthJournal
from .models import utc_now


@dataclass(slots=True)
class ChannelLoopState:
    channel: str
    running: bool = False
    polls: int = 0
    enqueued: int = 0
    deliveries: int = 0
    duplicate_percepts: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    pending_deliveries: int = 0
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None


class ResidentChannelSupervisor:
    """Run each channel independently while preserving one resident identity.

    Inbound adapters only enqueue durable percepts. The resident's own life loop
    decides when and how to process those events. Completed outcomes are read
    from the same durable store and routed outward, so UI disconnects or channel
    reconnects do not become alternate cognition owners.

    A supervisor owns one adapter lifecycle. ``stop()`` closes those adapters;
    restarting therefore requires constructing a fresh supervisor with fresh
    adapter resources instead of reusing a closed transport or duplicating a
    worker that is still unwinding.
    """

    def __init__(
        self,
        resident,
        adapters: Iterable[ChannelAdapter] = (),
        *,
        poll_timeout: float = 10.0,
        min_backoff: float = 0.5,
        max_backoff: float = 30.0,
        reply_failures: bool = False,
    ):
        self.resident = resident
        self.poll_timeout = max(0.0, float(poll_timeout))
        self.min_backoff = max(0.05, float(min_backoff))
        self.max_backoff = max(self.min_backoff, float(max_backoff))
        self.reply_failures = bool(reply_failures)
        self.ledger = ChannelDeliveryLedger(self.resident.store.path)
        self.health = ResidentHealthJournal(self.resident.store)
        self._adapters: dict[str, ChannelAdapter] = {}
        self._states: dict[str, ChannelLoopState] = {}
        for adapter in adapters:
            name = str(getattr(adapter, "name", "") or "").strip().lower()
            if not name:
                raise ValueError("channel adapter name must not be empty")
            if name in self._adapters:
                raise ValueError(f"duplicate channel adapter: {name}")
            self._adapters[name] = adapter
            self._states[name] = ChannelLoopState(channel=name)
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._stopped = False

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def start(self) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError(
                    "channel supervisor cannot restart after stop; "
                    "create a fresh supervisor with fresh adapters"
                )
            if self._threads:
                return
            self._stop.clear()
            for name, adapter in self._adapters.items():
                self._restore_adapter_checkpoint(name, adapter)
                thread = threading.Thread(
                    target=self._run_channel,
                    args=(name, adapter),
                    name=f"zn-channel-{name}",
                    daemon=True,
                )
                self._threads[name] = thread
                thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        self._stop.set()
        for adapter in self._adapters.values():
            try:
                adapter.close()
            except Exception:
                continue
        with self._lock:
            threads = list(self._threads.items())
        join_timeout = max(1.0, min(10.0, self.poll_timeout + 2.0))
        for _, thread in threads:
            if thread.is_alive():
                thread.join(timeout=join_timeout)
        with self._lock:
            # A provider that ignores close()/poll timeout may leave its daemon
            # thread alive. Keep that thread owned and visible rather than
            # claiming shutdown completed while it can still touch resident
            # state during process teardown.
            alive = {
                name: thread
                for name, thread in self._threads.items()
                if thread.is_alive()
            }
            self._threads = alive
            for name, state in self._states.items():
                thread = alive.get(name)
                state.running = bool(thread and thread.is_alive())
                if state.running:
                    state.total_failures += 1
                    state.consecutive_failures += 1
                    state.last_error_at = utc_now()
                    state.last_error = (
                        "channel worker did not stop before shutdown timeout; "
                        "worker remains owned until process teardown"
                    )

    def status(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            snapshots: list[dict[str, Any]] = []
            for name in sorted(self._states):
                state = self._states[name]
                counts = self.ledger.counts(name)
                state.pending_deliveries = int(counts.get("pending", 0))
                snapshots.append(asdict(state))
            return tuple(snapshots)

    def nominate_outbound_media(
        self,
        event_id: str,
        local_path: str,
        *,
        kind: str = "document",
        file_name: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMediaNomination:
        """Record explicit resident egress intent without interpreting text.

        The event must already belong to a durable channel route. Authorization
        remains the adapter's responsibility immediately before file access.
        """

        event = self.resident.store.get_event(str(event_id or "").strip())
        if event is None or event.kind != "channel_message":
            raise ValueError("outbound media nomination requires a resident channel event")
        return self.ledger.nominate_media(
            event.event_id,
            local_path,
            kind=kind,
            file_name=file_name,
            mime_type=mime_type,
            metadata=metadata,
        )

    def _run_channel(self, name: str, adapter: ChannelAdapter) -> None:
        backoff = self.min_backoff
        with self._lock:
            self._states[name].running = True
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    delivered_before = self._deliver_ready(name, adapter)
                    # stop() may arrive while an outbound provider send is
                    # blocked. Do not start another poll after delivery returns;
                    # teardown has already revoked further channel work.
                    if self._stop.is_set():
                        break
                    events = adapter.poll(timeout=self.poll_timeout)
                    # A stop can arrive while a long poll is blocked. Once the
                    # poll returns, do not enqueue, checkpoint or deliver anything
                    # else: resident teardown may already be closing durable state.
                    if self._stop.is_set():
                        break
                    enqueued, duplicates = self._ingest_events(events)
                    # Persist transport cursor only after every percept returned by
                    # this poll has a durable route. A crash before here replays
                    # the update; deterministic event ids make that replay
                    # idempotent even if the event reached the queue first.
                    self._save_adapter_checkpoint(name, adapter)
                    delivered_after = self._deliver_ready(name, adapter)
                    delivered = delivered_before + delivered_after
                except Exception as exc:
                    with self._lock:
                        state = self._states[name]
                        state.total_failures += 1
                        state.consecutive_failures += 1
                        state.last_error_at = utc_now()
                        state.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    try:
                        self.health.record_failure(f"channel:{name}", exc)
                    except Exception:
                        # Health evidence must never become a second failure mode
                        # that kills or stalls the communication organ itself.
                        pass
                    if self._stop.wait(backoff):
                        break
                    backoff = min(self.max_backoff, backoff * 2.0)
                    continue

                with self._lock:
                    state = self._states[name]
                    state.polls += 1
                    state.enqueued += enqueued
                    state.duplicate_percepts += duplicates
                    state.deliveries += delivered
                    state.consecutive_failures = 0
                    state.last_success_at = utc_now()
                    state.last_error = None
                    state.pending_deliveries = self.ledger.counts(name).get("pending", 0)
                try:
                    self.health.record_success(f"channel:{name}")
                except Exception:
                    pass
                backoff = self.min_backoff

                elapsed = time.monotonic() - started
                if not events and not delivered and elapsed < 0.05:
                    self._stop.wait(0.05 - elapsed)
        finally:
            with self._lock:
                self._states[name].running = False

    def _ingest_events(self, events: Iterable[ChannelEvent]) -> tuple[int, int]:
        enqueued = 0
        duplicates = 0
        for event in events:
            source_key = self.ledger.source_key(event)
            existing_route = self.ledger.route_for_source(source_key)
            if existing_route is not None:
                duplicates += 1
                continue

            payload = {
                "channel": event.channel,
                "conversation_id": event.conversation_id,
                "sender_id": event.sender_id,
                "message_id": event.message_id,
                "thread_id": event.thread_id,
                "channel_event_id": event.event_id,
                "channel_source_key": source_key,
                "attachments": [asdict(item) for item in event.attachments],
                "channel_metadata": dict(event.metadata),
            }
            event_id = stable_external_event_id("channel", source_key)
            ingress = enqueue_event_once(
                self.resident,
                event_id=event_id,
                task=event.text,
                kind="channel_message",
                payload=payload,
            )
            remembered = self.ledger.remember(event, ingress.event.event_id)
            if ingress.created and remembered.event_id == ingress.event.event_id:
                enqueued += 1
            else:
                # Recovery case: the same deterministic resident event already
                # existed (for example a crash after enqueue but before route
                # insert), or another worker already recorded the source route.
                duplicates += 1
        return enqueued, duplicates

    def _deliver_ready(self, name: str, adapter: ChannelAdapter) -> int:
        delivered = 0
        for route in self.ledger.pending(name):
            result = self.resident.result_for(route.event_id)
            if result is None:
                continue
            response = str(result.response or "").strip()
            if not response and self.reply_failures and not result.success:
                response = str(result.reason or "ZN could not complete this request.").strip()
            attachments = self.ledger.media_for_event(route.event_id)
            if not response and not attachments:
                self.ledger.mark_delivered(route.event_id)
                continue
            try:
                delivery = adapter.send(
                    ChannelMessage(
                        channel=route.channel,
                        conversation_id=route.conversation_id,
                        text=response,
                        thread_id=route.thread_id,
                        reply_to_message_id=route.reply_to_message_id,
                        attachments=attachments,
                    )
                )
                if not delivery.ok:
                    raise RuntimeError(delivery.error or "channel delivery failed")
            except Exception as exc:
                self.ledger.mark_delivery_failure(route.event_id, exc)
                raise
            self.ledger.mark_delivered(route.event_id)
            delivered += 1
        return delivered

    def _restore_adapter_checkpoint(self, name: str, adapter: ChannelAdapter) -> None:
        restore = getattr(adapter, "restore_checkpoint", None)
        if not callable(restore):
            return
        checkpoint = self.ledger.load_checkpoint(name)
        if checkpoint is not None:
            restore(checkpoint)

    def _save_adapter_checkpoint(self, name: str, adapter: ChannelAdapter) -> None:
        snapshot = getattr(adapter, "checkpoint", None)
        if not callable(snapshot):
            return
        checkpoint = snapshot()
        if not isinstance(checkpoint, Mapping):
            raise TypeError(f"channel {name} checkpoint must be a mapping")
        payload = dict(checkpoint)
        if self.ledger.load_checkpoint(name) != payload:
            self.ledger.save_checkpoint(name, payload)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def build_zn_channel_adapters(
    config: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[ChannelAdapter, ...]:
    """Build explicitly enabled ZN channels without old gateway config."""
    cfg = config if config is not None else load_zn_config()
    env = environ if environ is not None else os.environ
    channels = cfg.get("channels") or {}
    if not isinstance(channels, Mapping):
        raise ValueError("ZN channels config must be a mapping")

    adapters: list[ChannelAdapter] = []
    telegram = channels.get("telegram") or {}
    if telegram and not isinstance(telegram, Mapping):
        raise ValueError("ZN channels.telegram config must be a mapping")
    if isinstance(telegram, Mapping) and _truthy(telegram.get("enabled", False)):
        from .telegram_resident_channel import ResidentTelegramBotApiChannel

        adapters.append(
            ResidentTelegramBotApiChannel.from_zn_config(
                cfg,
                environ=env,
            )
        )
    return tuple(adapters)

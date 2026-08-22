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
from .channel_delivery import ChannelDeliveryLedger
from .config import load_zn_config
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

    Inbound adapters only enqueue. The resident's own life loop decides when and
    how to process those events. Completed outcomes are read back from the same
    durable store and routed out through the adapter, so UI disconnects or
    channel reconnects do not become alternate cognition owners.
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

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def start(self) -> None:
        with self._lock:
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
        self._stop.set()
        # Closing transports first wakes blocking long-polls. No channel thread
        # can be stuck inside resident cognition because cognition is never run
        # from these threads.
        for adapter in self._adapters.values():
            try:
                adapter.close()
            except Exception:
                continue
        with self._lock:
            threads = list(self._threads.values())
        join_timeout = max(1.0, min(10.0, self.poll_timeout + 2.0))
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=join_timeout)
        with self._lock:
            self._threads.clear()
            for state in self._states.values():
                state.running = False

    def status(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            snapshots: list[dict[str, Any]] = []
            for name in sorted(self._states):
                state = self._states[name]
                counts = self.ledger.counts(name)
                state.pending_deliveries = int(counts.get("pending", 0))
                snapshots.append(asdict(state))
            return tuple(snapshots)

    def _run_channel(self, name: str, adapter: ChannelAdapter) -> None:
        backoff = self.min_backoff
        with self._lock:
            self._states[name].running = True
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    delivered_before = self._deliver_ready(name, adapter)
                    events = adapter.poll(timeout=self.poll_timeout)
                    enqueued, duplicates = self._ingest_events(events)
                    # Persist transport cursor only after every percept returned by
                    # this poll has reached the durable routing ledger. A crash
                    # before this point may replay an update, which the ledger
                    # deduplicates; a crash after it cannot skip an unqueued event.
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
                backoff = self.min_backoff

                # A healthy long-poll blocks. Protect the resident from a
                # misconfigured adapter that returns immediately with no work.
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
            if self.ledger.route_for_source(source_key) is not None:
                duplicates += 1
                continue
            resident_event = self.resident.enqueue(
                event.text,
                kind="channel_message",
                payload={
                    "channel": event.channel,
                    "conversation_id": event.conversation_id,
                    "sender_id": event.sender_id,
                    "message_id": event.message_id,
                    "thread_id": event.thread_id,
                    "channel_event_id": event.event_id,
                    "channel_source_key": source_key,
                    "attachments": [asdict(item) for item in event.attachments],
                    "channel_metadata": dict(event.metadata),
                },
            )
            remembered = self.ledger.remember(event, resident_event.event_id)
            if remembered.event_id == resident_event.event_id:
                enqueued += 1
            else:
                # Only a concurrent/crash-window duplicate can reach this path;
                # keep routing to the already durable source record.
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
            if not response:
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

from __future__ import annotations

"""Resident-owned lifecycle for communication adapters.

Channels are sensory/motor organs of one ZN resident. This module owns their
threads, reconnect cadence, failure isolation and config-driven activation so a
Telegram/Discord/etc. adapter never becomes a second agent runtime.
"""

import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .channel import ChannelAdapter, ResidentChannelService
from .config import load_zn_config
from .models import utc_now


@dataclass(slots=True)
class ChannelLoopState:
    channel: str
    running: bool = False
    polls: int = 0
    deliveries: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None


class ResidentChannelSupervisor:
    """Run each channel independently while preserving one resident identity."""

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
        self._services: dict[str, ResidentChannelService] = {}
        self._states: dict[str, ChannelLoopState] = {}
        for adapter in adapters:
            name = str(getattr(adapter, "name", "") or "").strip().lower()
            if not name:
                raise ValueError("channel adapter name must not be empty")
            if name in self._services:
                raise ValueError(f"duplicate channel adapter: {name}")
            self._services[name] = ResidentChannelService(
                resident,
                adapter,
                reply_failures=self.reply_failures,
            )
            self._states[name] = ChannelLoopState(channel=name)
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(self._services)

    def start(self) -> None:
        with self._lock:
            if self._threads:
                return
            self._stop.clear()
            for name, service in self._services.items():
                thread = threading.Thread(
                    target=self._run_channel,
                    args=(name, service),
                    name=f"zn-channel-{name}",
                    daemon=True,
                )
                self._threads[name] = thread
                thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Closing the transport first gives a blocking long-poll a chance to
        # wake immediately instead of making resident shutdown wait for its full
        # server timeout.
        for service in self._services.values():
            try:
                service.close()
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
            return tuple(asdict(self._states[name]) for name in sorted(self._states))

    def _run_channel(self, name: str, service: ResidentChannelService) -> None:
        backoff = self.min_backoff
        with self._lock:
            self._states[name].running = True
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    deliveries = service.run_once(timeout=self.poll_timeout)
                except Exception as exc:
                    with self._lock:
                        state = self._states[name]
                        state.polls += 1
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
                    state.deliveries += len(deliveries)
                    state.consecutive_failures = 0
                    state.last_success_at = utc_now()
                    state.last_error = None
                backoff = self.min_backoff

                # A healthy long-poll blocks. Protect the resident from a
                # misconfigured adapter that returns immediately with no work.
                elapsed = time.monotonic() - started
                if not deliveries and elapsed < 0.05:
                    self._stop.wait(0.05 - elapsed)
        finally:
            with self._lock:
                self._states[name].running = False


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
        from .telegram_channel import TelegramBotApiChannel

        adapters.append(
            TelegramBotApiChannel.from_zn_config(
                cfg,
                environ=env,
            )
        )
    return tuple(adapters)

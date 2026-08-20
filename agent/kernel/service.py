from __future__ import annotations

import os
import socket
import threading
import time
import uuid

from .resident import ZNResidentRuntime


class ResidentAlreadyRunning(RuntimeError):
    pass


class ResidentService:
    """Single-instance service wrapper for a long-lived ZN resident runtime."""

    def __init__(
        self,
        resident: ZNResidentRuntime,
        *,
        heartbeat_interval: float = 5.0,
        lease_timeout: float = 30.0,
        instance_id: str | None = None,
    ):
        self.resident = resident
        self.store = resident.store
        self.heartbeat_interval = max(0.5, float(heartbeat_interval))
        self.lease_timeout = max(self.heartbeat_interval * 2.0, float(lease_timeout))
        self.instance_id = instance_id or f"resident-{uuid.uuid4().hex[:12]}"
        self._acquired = False

    def acquire(self) -> None:
        if self._acquired:
            return
        acquired = self.store.claim_resident_lease(
            instance_id=self.instance_id,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            stale_after_seconds=self.lease_timeout,
        )
        if not acquired:
            lease = self.store.get_resident_lease() or {}
            raise ResidentAlreadyRunning(
                "another ZN resident runtime holds the active lease "
                f"(pid={lease.get('pid')}, host={lease.get('hostname')})"
            )
        self._acquired = True

    def heartbeat(self) -> None:
        if not self._acquired:
            raise RuntimeError("resident lease is not acquired")
        if not self.store.heartbeat_resident_lease(self.instance_id):
            self._acquired = False
            raise RuntimeError("resident lease was lost")

    def release(self) -> None:
        if self._acquired:
            self.store.release_resident_lease(self.instance_id)
            self._acquired = False

    def run_forever(
        self,
        *,
        poll_interval: float = 0.5,
        stop_event: threading.Event | None = None,
    ) -> None:
        stopper = stop_event or threading.Event()
        poll = max(0.05, float(poll_interval))
        self.acquire()
        next_heartbeat = time.monotonic()
        try:
            while not stopper.is_set():
                now = time.monotonic()
                if now >= next_heartbeat:
                    self.heartbeat()
                    next_heartbeat = now + self.heartbeat_interval
                result = self.resident.run_once()
                if result is None:
                    stopper.wait(min(poll, max(0.05, next_heartbeat - time.monotonic())))
        finally:
            self.release()

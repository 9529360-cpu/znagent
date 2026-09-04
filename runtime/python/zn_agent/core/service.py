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

    def _browser_extension_resource(self):
        return getattr(self.resident, "user_browser_extension", None)

    def _close_browser_extension_resource(self) -> None:
        close_extension = getattr(self._browser_extension_resource(), "close", None)
        if callable(close_extension):
            close_extension()

    def acquire(self) -> None:
        if self._acquired:
            return
        hostname = socket.gethostname()
        lease = self.store.get_resident_lease()
        if (
            lease
            and str(lease.get("instance_id") or "") != self.instance_id
            and str(lease.get("hostname") or "") == hostname
            and not self._local_pid_alive(lease.get("pid"))
        ):
            # A resident that died abruptly cannot release its SQLite lease.
            # Same-host dead PID evidence is stronger than waiting for the
            # heartbeat timeout, so a new body can resume the durable self now.
            self.store.release_resident_lease(str(lease.get("instance_id") or ""))

        acquired = self.store.claim_resident_lease(
            instance_id=self.instance_id,
            pid=os.getpid(),
            hostname=hostname,
            stale_after_seconds=self.lease_timeout,
        )
        if not acquired:
            lease = self.store.get_resident_lease() or {}
            raise ResidentAlreadyRunning(
                "another ZN resident runtime holds the active lease "
                f"(pid={lease.get('pid')}, host={lease.get('hostname')})"
            )
        self._acquired = True
        start_extension = getattr(self._browser_extension_resource(), "start", None)
        if callable(start_extension):
            try:
                start_extension()
            except Exception:
                self.store.release_resident_lease(self.instance_id)
                self._acquired = False
                raise

    def heartbeat(self) -> None:
        if not self._acquired:
            raise RuntimeError("resident lease is not acquired")
        if not self.store.heartbeat_resident_lease(self.instance_id):
            # Browser-tab authority may only exist while this process owns the
            # canonical Resident lease. Drop it before surfacing lease loss.
            self._close_browser_extension_resource()
            self._acquired = False
            raise RuntimeError("resident lease was lost")

    def release(self) -> None:
        # Always close browser authorization first. This is intentionally not
        # conditional on ``_acquired`` because heartbeat loss may already have
        # cleared the flag.
        self._close_browser_extension_resource()
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
        self.resident.pulse()
        next_heartbeat = time.monotonic()
        try:
            while not stopper.is_set():
                now = time.monotonic()
                if now >= next_heartbeat:
                    self.heartbeat()
                    self.resident.pulse()
                    next_heartbeat = now + self.heartbeat_interval
                result = self.resident.run_once()
                if result is None:
                    stopper.wait(min(poll, max(0.05, next_heartbeat - time.monotonic())))
        finally:
            self.release()

    @staticmethod
    def _local_pid_alive(value: object) -> bool:
        try:
            pid = int(value)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            import psutil

            return bool(psutil.pid_exists(pid))
        except Exception:
            # If the process table cannot be inspected, preserve the lease and
            # fall back to its normal heartbeat timeout instead of guessing.
            return True

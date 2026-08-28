from __future__ import annotations

"""Resident-owned RPC control surface for the managed browser.

Playwright's synchronous API is thread-affine. Resident TCP clients may reconnect
or coexist, so request-handler threads are not a valid browser owner. This module
serializes every managed-browser provider call onto one resident-owned thread.
"""

import queue
import threading
from concurrent.futures import Future
from dataclasses import asdict
from enum import Enum
from typing import Any, Callable, TypeVar

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from .daemon import ResidentRpcServer

_T = TypeVar("_T")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class _BrowserOwner:
    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[Callable[[], Any], Future[Any]] | None] = queue.Queue()
        self._ready = threading.Event()
        self._thread_id: int | None = None
        self._closed = False
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="zn-managed-browser", daemon=True)
        self._thread.start()
        self._ready.wait()

    def call(self, operation: Callable[[], _T]) -> _T:
        if threading.get_ident() == self._thread_id:
            return operation()
        with self._state_lock:
            if self._closed:
                raise RuntimeError("resident managed-browser owner is closed")
            future: Future[_T] = Future()
            self._queue.put((operation, future))
        return future.result()

    def close(self, operation: Callable[[], Any]) -> None:
        with self._state_lock:
            if self._closed:
                return
        failure: BaseException | None = None
        try:
            self.call(operation)
        except BaseException as exc:
            failure = exc
        with self._state_lock:
            if not self._closed:
                self._closed = True
                self._queue.put(None)
        if threading.get_ident() != self._thread_id:
            self._thread.join(timeout=10.0)
        if failure is not None:
            raise failure

    def _run(self) -> None:
        self._thread_id = threading.get_ident()
        self._ready.set()
        while True:
            command = self._queue.get()
            if command is None:
                return
            operation, future = command
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(operation())
            except BaseException as exc:
                future.set_exception(exc)


class _ResidentManagedBrowser:
    """Resident-facing browser facade that preserves provider thread ownership."""

    def __init__(self, browser: Any, owner: _BrowserOwner) -> None:
        self._browser = browser
        self._owner = owner
        self.name = getattr(browser, "name", "managed-browser")
        self.plane = getattr(browser, "plane", None)

    def open_session(self, *, permission=None, headless=True):
        return self._owner.call(
            lambda: self._browser.open_session(permission=permission, headless=headless)
        )

    def close_session(self, session_id: str) -> None:
        self._owner.call(lambda: self._browser.close_session(session_id))

    def observe(self, session_id: str, *, page_id: str = ""):
        return self._owner.call(lambda: self._browser.observe(session_id, page_id=page_id))

    def observe_target(self, session_id: str, query, *, page_id: str = ""):
        return self._owner.call(
            lambda: self._browser.observe_target(session_id, query, page_id=page_id)
        )

    def act(self, action, authority):
        return self._owner.call(lambda: self._browser.act(action, authority))

    def close(self) -> None:
        self._owner.close(self._browser.close)


class BrowserResidentRpcServer(ResidentRpcServer):
    """Extend the normal resident RPC face with bounded managed browsing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser_permissions: dict[str, BrowserPermissionContext] = {}
        self._browser_permissions_lock = threading.Lock()
        self._browser_owner = _BrowserOwner()
        browser = getattr(self.resident, "managed_browser", None)
        if browser is not None:
            self.resident.managed_browser = _ResidentManagedBrowser(browser, self._browser_owner)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = str(request.get("method") or "").strip()
        if not method.startswith("browser_"):
            return super().handle(request)

        request_id = request.get("id")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        browser = getattr(self.resident, "managed_browser", None)
        if browser is None:
            raise ValueError("resident has no managed browser")

        if method == "browser_open":
            permission = self._permission_from_params(params.get("permission"))
            session = browser.open_session(
                permission=permission,
                headless=bool(params.get("headless", True)),
            )
            with self._browser_permissions_lock:
                self._browser_permissions[session.session_id] = permission
            result = _jsonable(asdict(session))
        elif method == "browser_observe":
            session_id = self._session_id(params, method)
            self._require_known_session(session_id)
            observation = browser.observe(
                session_id,
                page_id=str(params.get("page_id") or "").strip(),
            )
            result = _jsonable(asdict(observation))
        elif method == "browser_navigate":
            session_id = self._session_id(params, method)
            permission = self._require_known_session(session_id)
            url = str(params.get("url") or "").strip()
            if not url:
                raise ValueError("browser_navigate requires url")
            page_id = str(params.get("page_id") or "").strip()
            expected_url = str(params.get("url_equals") or "").strip()

            def navigate() -> Any:
                observation = browser.observe(session_id, page_id=page_id)
                action = BrowserAction.create(
                    session_id=session_id,
                    kind=BrowserActionKind.NAVIGATE,
                    page_id=page_id or observation.page_id,
                    args={"url": url},
                    expected={"url_equals": expected_url} if expected_url else {},
                )
                authority = BrowserActionAuthority.from_observation(
                    action,
                    observation,
                    permission,
                )
                return browser.act(action, authority)

            evidence = self._browser_owner.call(navigate)
            result = _jsonable(asdict(evidence))
        elif method == "browser_close":
            session_id = self._session_id(params, method)
            self._require_known_session(session_id)
            browser.close_session(session_id)
            with self._browser_permissions_lock:
                self._browser_permissions.pop(session_id, None)
            result = {"closed": True, "session_id": session_id}
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _session_id(params: dict[str, Any], method: str) -> str:
        session_id = str(params.get("session_id") or "").strip()
        if not session_id:
            raise ValueError(f"{method} requires session_id")
        return session_id

    def _require_known_session(self, session_id: str) -> BrowserPermissionContext:
        with self._browser_permissions_lock:
            permission = self._browser_permissions.get(session_id)
        if permission is None:
            raise ValueError("unknown resident managed-browser session")
        return permission

    @staticmethod
    def _permission_from_params(raw: Any) -> BrowserPermissionContext:
        if raw is None:
            return BrowserPermissionContext()
        if not isinstance(raw, dict):
            raise ValueError("browser_open permission must be an object")
        allowed_origins = raw.get("allowed_origins") or []
        if not isinstance(allowed_origins, list):
            raise ValueError("browser allowed_origins must be a list")
        return BrowserPermissionContext(
            allow_navigation=bool(raw.get("allow_navigation", False)),
            allow_page_interaction=bool(raw.get("allow_page_interaction", False)),
            allow_text_entry=bool(raw.get("allow_text_entry", False)),
            allow_downloads=bool(raw.get("allow_downloads", False)),
            allow_uploads=bool(raw.get("allow_uploads", False)),
            allow_clipboard=bool(raw.get("allow_clipboard", False)),
            allow_sensitive_fields=bool(raw.get("allow_sensitive_fields", False)),
            allow_private_network=bool(raw.get("allow_private_network", False)),
            allowed_origins=tuple(str(item) for item in allowed_origins),
        )

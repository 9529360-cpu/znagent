from __future__ import annotations

"""Loopback transport between the Resident and the explicitly authorized ZN tab.

The relay owns tab authorization plus a deliberately tiny command vocabulary.
It is not a generic CDP proxy. A command is delivered to the extension at most
once; if a dispatched mutation loses its result, the caller receives an uncertain
outcome and ZN's existing Body non-replay discipline decides what happens next.
"""

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .models import utc_now


ZN_BROWSER_EXTENSION_ID = "likpiakgiamipheeekdgekdahafjinnh"
ZN_BROWSER_EXTENSION_ORIGIN = f"chrome-extension://{ZN_BROWSER_EXTENSION_ID}"
ZN_BROWSER_EXTENSION_HEADER = "X-ZN-Browser-Extension-Id"

_ALLOWED_COMMANDS = frozenset(
    {
        "observe_page",
        "observe_named_textbox",
        "type_named_textbox",
    }
)
_MAX_COMMAND_PAYLOAD_BYTES = 8 * 1024
_MAX_RESULT_PAYLOAD_BYTES = 16 * 1024


@dataclass(slots=True, frozen=True)
class AuthorizedUserBrowserTab:
    tab_id: int
    url: str
    title: str
    attached_at: str


@dataclass(slots=True)
class _PendingCommand:
    command_id: str
    tab_id: int
    kind: str
    payload: dict[str, Any]
    created_at: str
    dispatched: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None
    completed: threading.Event = field(default_factory=threading.Event)


class UserBrowserExtensionRelayError(RuntimeError):
    pass


class UserBrowserExtensionOutcomeUncertain(UserBrowserExtensionRelayError):
    pass


class ResidentUserBrowserExtensionRelay:
    """Keep one user-authorized browser tab and one bounded in-flight command."""

    protocol_version = 1

    def __init__(self, *, host: str = "127.0.0.1", port: int = 19991):
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("user-browser extension relay must bind loopback only")
        self.host = host
        self.port = int(port)
        if not 0 <= self.port <= 65535:
            raise ValueError("user-browser extension relay port is invalid")
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._authorized: AuthorizedUserBrowserTab | None = None
        self._pending: _PendingCommand | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                return self.status()
            relay = self

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    self._write(404, {"ok": False, "error": "not_found"})

                def do_POST(self) -> None:  # noqa: N802
                    try:
                        self._require_extension_request()
                        body = self._json_body()
                        if self.path == "/v1/attach":
                            result = relay.authorize(
                                tab_id=body.get("tab_id"),
                                url=body.get("url"),
                                title=body.get("title"),
                            )
                        elif self.path == "/v1/detach":
                            result = relay.revoke(tab_id=body.get("tab_id"))
                        elif self.path == "/v1/command/next":
                            result = {
                                "command": relay.next_command(
                                    tab_id=body.get("tab_id"), timeout=20.0
                                )
                            }
                        elif self.path == "/v1/command/result":
                            result = relay.complete_command(
                                tab_id=body.get("tab_id"),
                                command_id=body.get("command_id"),
                                result=body.get("result"),
                                error=body.get("error"),
                            )
                        else:
                            self._write(404, {"ok": False, "error": "not_found"})
                            return
                    except (ValueError, UserBrowserExtensionRelayError) as exc:
                        self._write(400, {"ok": False, "error": str(exc)})
                        return
                    self._write(200, {"ok": True, **result})

                def _require_extension_request(self) -> None:
                    extension_id = str(
                        self.headers.get(ZN_BROWSER_EXTENSION_HEADER) or ""
                    ).strip()
                    if extension_id != ZN_BROWSER_EXTENSION_ID:
                        raise UserBrowserExtensionRelayError(
                            "browser relay request requires the installed ZN extension identity"
                        )
                    origin = str(self.headers.get("Origin") or "").strip()
                    if origin and origin != ZN_BROWSER_EXTENSION_ORIGIN:
                        raise UserBrowserExtensionRelayError(
                            "browser relay request origin does not match the ZN extension"
                        )

                def _json_body(self) -> dict[str, Any]:
                    try:
                        length = int(self.headers.get("Content-Length") or "0")
                    except ValueError as exc:
                        raise ValueError("invalid content length") from exc
                    if length <= 0 or length > _MAX_RESULT_PAYLOAD_BYTES:
                        raise ValueError("browser extension relay body is outside the bounded size")
                    try:
                        value = json.loads(self.rfile.read(length).decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError("browser extension relay body must be UTF-8 JSON") from exc
                    if not isinstance(value, dict):
                        raise ValueError("browser extension relay body must be an object")
                    if int(value.get("protocol_version") or 0) != relay.protocol_version:
                        raise ValueError("browser extension relay protocol version mismatch")
                    return value

                def _write(self, status: int, value: dict[str, Any]) -> None:
                    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, format: str, *args: Any) -> None:
                    return None

            server = ThreadingHTTPServer((self.host, self.port), Handler)
            server.daemon_threads = True
            self.port = int(server.server_address[1])
            self._server = server
            self._thread = threading.Thread(
                target=server.serve_forever,
                name="zn-user-browser-extension-relay",
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def close(self) -> None:
        with self._condition:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._authorized = None
            self._fail_pending_locked("browser extension relay closed")
            self._condition.notify_all()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def authorize(self, *, tab_id: Any, url: Any, title: Any) -> dict[str, Any]:
        normalized_tab_id = self._tab_id(tab_id, label="authorized")
        normalized_url = str(url or "").strip()
        if not self._safe_page_url(normalized_url):
            raise ValueError("authorized browser tab must be an HTTP(S) page")
        normalized_title = str(title or "").strip()
        if len(normalized_title) > 512:
            raise ValueError("authorized browser tab title is too long")
        tab = AuthorizedUserBrowserTab(
            tab_id=normalized_tab_id,
            url=normalized_url,
            title=normalized_title,
            attached_at=utc_now(),
        )
        with self._condition:
            current = self._authorized
            if current is not None and current.tab_id != tab.tab_id:
                raise UserBrowserExtensionRelayError(
                    "another user browser tab is already authorized; revoke it first"
                )
            self._authorized = tab
            self._condition.notify_all()
        return self.status()

    def revoke(self, *, tab_id: Any = None) -> dict[str, Any]:
        with self._condition:
            current = self._authorized
            if current is not None and tab_id not in (None, ""):
                expected = self._tab_id(tab_id, label="revoked")
                if expected != current.tab_id:
                    raise UserBrowserExtensionRelayError(
                        "refusing to revoke a different authorized browser tab"
                    )
            self._authorized = None
            self._fail_pending_locked("browser tab authorization was revoked")
            self._condition.notify_all()
        return self.status()

    def request(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in _ALLOWED_COMMANDS:
            raise ValueError("unsupported browser extension command")
        normalized_payload = dict(payload or {})
        encoded = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > _MAX_COMMAND_PAYLOAD_BYTES:
            raise ValueError("browser extension command payload is too large")
        wait = max(0.1, min(60.0, float(timeout)))

        with self._condition:
            tab = self._authorized
            if tab is None:
                raise UserBrowserExtensionRelayError("no user browser tab is authorized")
            if self._pending is not None:
                raise UserBrowserExtensionRelayError(
                    "another browser extension command is already in flight"
                )
            pending = _PendingCommand(
                command_id=f"zn-browser-{uuid.uuid4().hex[:16]}",
                tab_id=tab.tab_id,
                kind=normalized_kind,
                payload=normalized_payload,
                created_at=utc_now(),
            )
            self._pending = pending
            self._condition.notify_all()

        completed = pending.completed.wait(wait)
        with self._condition:
            if self._pending is pending:
                self._pending = None
                self._condition.notify_all()
            if not completed:
                if pending.dispatched:
                    raise UserBrowserExtensionOutcomeUncertain(
                        "browser extension command was dispatched but no result arrived; outcome is uncertain"
                    )
                raise UserBrowserExtensionRelayError(
                    "browser extension did not collect the command before the bounded timeout"
                )
            if pending.error:
                raise UserBrowserExtensionRelayError(pending.error)
            if not isinstance(pending.result, dict):
                raise UserBrowserExtensionRelayError(
                    "browser extension returned no structured command result"
                )
            return dict(pending.result)

    def next_command(self, *, tab_id: Any, timeout: float = 20.0) -> dict[str, Any] | None:
        expected_tab = self._tab_id(tab_id, label="polling")
        deadline = time.monotonic() + max(0.0, min(25.0, float(timeout)))
        with self._condition:
            while True:
                self._require_authorized_tab_locked(expected_tab)
                pending = self._pending
                if (
                    pending is not None
                    and pending.tab_id == expected_tab
                    and not pending.dispatched
                ):
                    pending.dispatched = True
                    return {
                        "command_id": pending.command_id,
                        "kind": pending.kind,
                        "payload": dict(pending.payload),
                        "created_at": pending.created_at,
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 1.0))

    def complete_command(
        self,
        *,
        tab_id: Any,
        command_id: Any,
        result: Any = None,
        error: Any = None,
    ) -> dict[str, Any]:
        expected_tab = self._tab_id(tab_id, label="result")
        expected_command = str(command_id or "").strip()
        if not expected_command:
            raise ValueError("browser extension result requires command_id")
        normalized_error = str(error or "").strip()
        if result is not None and not isinstance(result, dict):
            raise ValueError("browser extension command result must be an object")
        if result is not None:
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(encoded) > _MAX_RESULT_PAYLOAD_BYTES:
                raise ValueError("browser extension command result is too large")
        with self._condition:
            self._require_authorized_tab_locked(expected_tab)
            pending = self._pending
            if pending is None or pending.command_id != expected_command:
                raise UserBrowserExtensionRelayError(
                    "browser extension result does not match the current command"
                )
            if pending.tab_id != expected_tab or not pending.dispatched:
                raise UserBrowserExtensionRelayError(
                    "browser extension result lacks matching dispatched authority"
                )
            if pending.completed.is_set():
                raise UserBrowserExtensionRelayError(
                    "browser extension command result was already completed"
                )
            pending.result = dict(result or {}) if not normalized_error else None
            pending.error = normalized_error or None
            pending.completed.set()
            self._condition.notify_all()
        return {"accepted": True}

    def authorized_tab(self) -> AuthorizedUserBrowserTab | None:
        with self._lock:
            return self._authorized

    def status(self) -> dict[str, Any]:
        with self._lock:
            tab = self._authorized
            listening = self._server is not None
            pending = self._pending
        return {
            "available": listening,
            "authorized": tab is not None,
            "protocol_version": self.protocol_version,
            "endpoint": f"http://{self.host}:{self.port}",
            "extension_id": ZN_BROWSER_EXTENSION_ID,
            "tab": asdict(tab) if tab is not None else None,
            "command_in_flight": pending is not None,
            "command_dispatched": bool(pending and pending.dispatched),
        }

    def _require_authorized_tab_locked(self, tab_id: int) -> AuthorizedUserBrowserTab:
        current = self._authorized
        if current is None:
            raise UserBrowserExtensionRelayError("no user browser tab is authorized")
        if current.tab_id != tab_id:
            raise UserBrowserExtensionRelayError(
                "browser extension request belongs to a different tab"
            )
        return current

    def _fail_pending_locked(self, reason: str) -> None:
        pending = self._pending
        if pending is None or pending.completed.is_set():
            return
        pending.error = str(reason)
        pending.completed.set()

    @staticmethod
    def _tab_id(value: Any, *, label: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} browser tab id must be an integer") from exc
        if normalized <= 0:
            raise ValueError(f"{label} browser tab id must be positive")
        return normalized

    @staticmethod
    def _safe_page_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)

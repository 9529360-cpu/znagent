from __future__ import annotations

"""Loopback-only authorization and command relay for the ZN browser extension.

The user explicitly authorizes one current HTTP(S) tab through the installed ZN
extension. Resident may then issue only bounded, short-lived commands to that exact
tab. Command payloads/results live in memory only; revocation or Resident shutdown
withdraws the surface and wakes blocked callers without replaying work.
"""

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .models import utc_now


ZN_BROWSER_EXTENSION_ID = "likpiakgiamipheeekdgekdahafjinnh"
ZN_BROWSER_EXTENSION_ORIGIN = f"chrome-extension://{ZN_BROWSER_EXTENSION_ID}"
ZN_BROWSER_EXTENSION_HEADER = "X-ZN-Browser-Extension-Id"

_ALLOWED_COMMAND_KINDS = frozenset(
    {
        "probe_current_tab",
        "observe_named_textbox",
        "type_named_textbox",
        "observe_named_button",
        "click_named_button_to_url",
    }
)
_MAX_RELAY_BODY = 64 * 1024
_MAX_COMMAND_WAIT_SECONDS = 20.0


@dataclass(slots=True, frozen=True)
class AuthorizedUserBrowserTab:
    tab_id: int
    url: str
    title: str
    attached_at: str


@dataclass(slots=True, frozen=True)
class UserBrowserExtensionCommand:
    command_id: str
    tab_id: int
    kind: str
    args: dict[str, Any]
    issued_at: str


class UserBrowserExtensionRelayError(RuntimeError):
    pass


class UserBrowserExtensionCommandUncertainError(UserBrowserExtensionRelayError):
    """The extension received a command but Resident never got its final result.

    This is intentionally distinct from a pre-dispatch transport failure. Callers
    must assume a side effect may already have happened and re-sense before any
    further movement instead of replaying the command.
    """


class ResidentUserBrowserExtensionRelay:
    """Keep one explicitly user-authorized browser tab on loopback only."""

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
        self._pending: list[UserBrowserExtensionCommand] = []
        self._inflight: dict[str, UserBrowserExtensionCommand] = {}
        self._results: dict[str, dict[str, Any]] = {}
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
                                    tab_id=body.get("tab_id"),
                                    wait_seconds=body.get("wait_seconds"),
                                )
                            }
                        elif self.path == "/v1/command/result":
                            result = relay.complete_command(
                                tab_id=body.get("tab_id"),
                                command_id=body.get("command_id"),
                                success=body.get("success"),
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
                            "browser tab authorization requires the installed ZN extension identity"
                        )
                    origin = str(self.headers.get("Origin") or "").strip()
                    if origin and origin != ZN_BROWSER_EXTENSION_ORIGIN:
                        raise UserBrowserExtensionRelayError(
                            "browser tab authorization origin does not match the ZN extension"
                        )

                def _json_body(self) -> dict[str, Any]:
                    try:
                        length = int(self.headers.get("Content-Length") or "0")
                    except ValueError as exc:
                        raise ValueError("invalid content length") from exc
                    if length <= 0 or length > _MAX_RELAY_BODY:
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
            self._pending.clear()
            # Keep inflight command identities until their blocked Resident callers
            # wake. Those callers must be told that delivery happened and the final
            # side-effect state is therefore uncertain rather than safe to replay.
            self._results.clear()
            self._condition.notify_all()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def authorize(self, *, tab_id: Any, url: Any, title: Any) -> dict[str, Any]:
        try:
            normalized_tab_id = int(tab_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("authorized browser tab id must be an integer") from exc
        if normalized_tab_id <= 0:
            raise ValueError("authorized browser tab id must be positive")
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
                try:
                    expected = int(tab_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("revoked browser tab id must be an integer") from exc
                if expected != current.tab_id:
                    raise UserBrowserExtensionRelayError(
                        "refusing to revoke a different authorized browser tab"
                    )
            self._authorized = None
            self._pending.clear()
            # Do not erase inflight identities here. A command already delivered to
            # the extension may have crossed the side-effect boundary before the
            # user's revocation arrived; the waiting caller must re-sense, not replay.
            self._results.clear()
            self._condition.notify_all()
        return self.status()

    def request_command(
        self,
        kind: str,
        *,
        args: dict[str, Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        normalized_kind = str(kind or "").strip()
        if normalized_kind not in _ALLOWED_COMMAND_KINDS:
            raise ValueError("unsupported user-browser extension command kind")
        normalized_args = dict(args or {})
        self._validate_json_payload(normalized_args, "browser extension command args")
        timeout = float(timeout_seconds)
        if timeout <= 0 or timeout > 30.0:
            raise ValueError("browser extension command timeout is outside the bounded range")

        with self._condition:
            current = self._authorized
            if current is None:
                raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
            command = UserBrowserExtensionCommand(
                command_id=f"browser-extension-command-{uuid.uuid4().hex[:12]}",
                tab_id=current.tab_id,
                kind=normalized_kind,
                args=normalized_args,
                issued_at=utc_now(),
            )
            self._pending.append(command)
            self._condition.notify_all()
            deadline = time.monotonic() + timeout
            while True:
                result = self._results.pop(command.command_id, None)
                if result is not None:
                    return result
                current = self._authorized
                if current is None or current.tab_id != command.tab_id:
                    delivered = command.command_id in self._inflight
                    self._drop_command_locked(command.command_id)
                    if delivered:
                        raise UserBrowserExtensionCommandUncertainError(
                            "user browser authority changed after command delivery; side effect may have occurred"
                        )
                    raise UserBrowserExtensionRelayError(
                        "user browser authorization was revoked before command delivery"
                    )
                if self._server is None:
                    delivered = command.command_id in self._inflight
                    self._drop_command_locked(command.command_id)
                    if delivered:
                        raise UserBrowserExtensionCommandUncertainError(
                            "browser extension relay stopped after command delivery; side effect may have occurred"
                        )
                    raise UserBrowserExtensionRelayError(
                        "browser extension relay stopped before command delivery"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    delivered = command.command_id in self._inflight
                    self._drop_command_locked(command.command_id)
                    if delivered:
                        raise UserBrowserExtensionCommandUncertainError(
                            "browser extension command result was lost after delivery; side effect may have occurred"
                        )
                    raise UserBrowserExtensionRelayError(
                        "browser extension command was not delivered before timeout"
                    )
                self._condition.wait(timeout=remaining)

    def next_command(self, *, tab_id: Any, wait_seconds: Any = None) -> dict[str, Any] | None:
        normalized_tab_id = self._require_current_tab_id(tab_id)
        wait = _MAX_COMMAND_WAIT_SECONDS if wait_seconds in (None, "") else float(wait_seconds)
        if wait < 0 or wait > _MAX_COMMAND_WAIT_SECONDS:
            raise ValueError("browser extension command wait is outside the bounded range")
        deadline = time.monotonic() + wait
        with self._condition:
            while True:
                self._require_current_tab_id_locked(normalized_tab_id)
                for index, command in enumerate(self._pending):
                    if command.tab_id != normalized_tab_id:
                        continue
                    self._pending.pop(index)
                    self._inflight[command.command_id] = command
                    return asdict(command)
                if self._server is None or wait == 0:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)

    def complete_command(
        self,
        *,
        tab_id: Any,
        command_id: Any,
        success: Any,
        result: Any = None,
        error: Any = None,
    ) -> dict[str, Any]:
        normalized_tab_id = self._require_current_tab_id(tab_id)
        normalized_command_id = str(command_id or "").strip()
        if not normalized_command_id:
            raise ValueError("browser extension command result requires command_id")
        if not isinstance(success, bool):
            raise ValueError("browser extension command success must be boolean")
        normalized_result = result if result is not None else {}
        if not isinstance(normalized_result, dict):
            raise ValueError("browser extension command result must be an object")
        self._validate_json_payload(normalized_result, "browser extension command result")
        normalized_error = str(error or "").strip() or None
        if normalized_error is not None and len(normalized_error) > 512:
            raise ValueError("browser extension command error is too long")

        with self._condition:
            self._require_current_tab_id_locked(normalized_tab_id)
            command = self._inflight.pop(normalized_command_id, None)
            if command is None or command.tab_id != normalized_tab_id:
                raise UserBrowserExtensionRelayError(
                    "browser extension command result does not match one inflight command"
                )
            self._results[normalized_command_id] = {
                "command_id": normalized_command_id,
                "tab_id": normalized_tab_id,
                "kind": command.kind,
                "success": success,
                "result": normalized_result,
                "error": normalized_error,
                "completed_at": utc_now(),
            }
            self._condition.notify_all()
        return {"accepted": True, "command_id": normalized_command_id}

    def authorized_tab(self) -> AuthorizedUserBrowserTab | None:
        with self._lock:
            return self._authorized

    def status(self) -> dict[str, Any]:
        with self._lock:
            tab = self._authorized
            listening = self._server is not None
            pending_count = len(self._pending)
            inflight_count = len(self._inflight)
        return {
            "available": listening,
            "authorized": tab is not None,
            "protocol_version": self.protocol_version,
            "endpoint": f"http://{self.host}:{self.port}",
            "extension_id": ZN_BROWSER_EXTENSION_ID,
            "tab": asdict(tab) if tab is not None else None,
            "pending_commands": pending_count,
            "inflight_commands": inflight_count,
        }

    def _require_current_tab_id(self, value: Any) -> int:
        try:
            tab_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("browser extension command tab id must be an integer") from exc
        with self._lock:
            self._require_current_tab_id_locked(tab_id)
        return tab_id

    def _require_current_tab_id_locked(self, tab_id: int) -> None:
        current = self._authorized
        if current is None or current.tab_id != tab_id:
            raise UserBrowserExtensionRelayError(
                "browser extension command must use the currently authorized tab"
            )

    def _drop_command_locked(self, command_id: str) -> None:
        self._pending = [item for item in self._pending if item.command_id != command_id]
        self._inflight.pop(command_id, None)
        self._results.pop(command_id, None)

    @staticmethod
    def _validate_json_payload(value: dict[str, Any], label: str) -> None:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be JSON-safe") from exc
        if len(encoded) > _MAX_RELAY_BODY:
            raise ValueError(f"{label} is outside the bounded size")

    @staticmethod
    def _safe_page_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)

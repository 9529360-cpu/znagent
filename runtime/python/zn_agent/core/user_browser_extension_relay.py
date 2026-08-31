from __future__ import annotations

"""Loopback-only authorization relay for the ZN browser extension.

This first slice owns only user authorization state. The extension attaches the
current tab through ``chrome.debugger`` after a toolbar click and reports bounded
tab identity here. No DOM, cookies, storage, credentials, or page content cross
this relay yet.
"""

import json
import threading
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .models import utc_now


ZN_BROWSER_EXTENSION_ID = "likpiakgiamipheeekdgekdahafjinnh"
ZN_BROWSER_EXTENSION_ORIGIN = f"chrome-extension://{ZN_BROWSER_EXTENSION_ID}"


@dataclass(slots=True, frozen=True)
class AuthorizedUserBrowserTab:
    tab_id: int
    url: str
    title: str
    attached_at: str


class UserBrowserExtensionRelayError(RuntimeError):
    pass


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
        self._authorized: AuthorizedUserBrowserTab | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                return self.status()
            relay = self

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    # Browser tab identity is available through Resident status,
                    # not through an unauthenticated HTTP read surface.
                    self._write(404, {"ok": False, "error": "not_found"})

                def do_POST(self) -> None:  # noqa: N802
                    try:
                        self._require_extension_origin()
                        body = self._json_body()
                        if self.path == "/v1/attach":
                            result = relay.authorize(
                                tab_id=body.get("tab_id"),
                                url=body.get("url"),
                                title=body.get("title"),
                            )
                        elif self.path == "/v1/detach":
                            result = relay.revoke(tab_id=body.get("tab_id"))
                        else:
                            self._write(404, {"ok": False, "error": "not_found"})
                            return
                    except (ValueError, UserBrowserExtensionRelayError) as exc:
                        self._write(400, {"ok": False, "error": str(exc)})
                        return
                    self._write(200, {"ok": True, **result})

                def _require_extension_origin(self) -> None:
                    origin = str(self.headers.get("Origin") or "").strip()
                    if origin != ZN_BROWSER_EXTENSION_ORIGIN:
                        raise UserBrowserExtensionRelayError(
                            "browser tab authorization requires the installed ZN extension origin"
                        )

                def _json_body(self) -> dict[str, Any]:
                    try:
                        length = int(self.headers.get("Content-Length") or "0")
                    except ValueError as exc:
                        raise ValueError("invalid content length") from exc
                    if length <= 0 or length > 16 * 1024:
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
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._authorized = None
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
        with self._lock:
            current = self._authorized
            if current is not None and current.tab_id != tab.tab_id:
                raise UserBrowserExtensionRelayError(
                    "another user browser tab is already authorized; revoke it first"
                )
            self._authorized = tab
        return self.status()

    def revoke(self, *, tab_id: Any = None) -> dict[str, Any]:
        with self._lock:
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
        return self.status()

    def authorized_tab(self) -> AuthorizedUserBrowserTab | None:
        with self._lock:
            return self._authorized

    def status(self) -> dict[str, Any]:
        with self._lock:
            tab = self._authorized
            listening = self._server is not None
        return {
            "available": listening,
            "authorized": tab is not None,
            "protocol_version": self.protocol_version,
            "endpoint": f"http://{self.host}:{self.port}",
            "extension_id": ZN_BROWSER_EXTENSION_ID,
            "tab": asdict(tab) if tab is not None else None,
        }

    @staticmethod
    def _safe_page_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)

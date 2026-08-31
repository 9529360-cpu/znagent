from __future__ import annotations

"""Minimal maintainer-side HTTP adapter for bounded ZN defect reports.

The service intentionally owns no repository or release authority. It accepts only
privacy-bounded report envelopes into the existing SQLite intake and exposes the
explicit presence query required by uncertain-dispatch reconciliation.

TLS is expected to terminate at the deployment boundary. The process binds to
loopback by default so an operator must explicitly choose wider network exposure.
"""

import argparse
import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .upstream_bug_report_intake import MaintainerBugReportIntake

_MAX_BODY_BYTES = 4096
_MIN_TOKEN_LENGTH = 32
_REPORT_PATH = "/reports"
_TOKEN_ENV = "ZN_MAINTAINER_REPORT_TOKEN"
_DB_ENV = "ZN_MAINTAINER_REPORT_DB"


def _validated_token(value: str) -> str:
    token = str(value or "").strip()
    if len(token) < _MIN_TOKEN_LENGTH:
        raise ValueError(f"maintainer report bearer token must be at least {_MIN_TOKEN_LENGTH} characters")
    return token


class MaintainerReportHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        intake: MaintainerBugReportIntake,
        bearer_token: str,
    ) -> None:
        self.intake = intake
        self.bearer_token = _validated_token(bearer_token)
        super().__init__(server_address, MaintainerReportRequestHandler)


class MaintainerReportRequestHandler(BaseHTTPRequestHandler):
    server: MaintainerReportHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "ZNMaintainerIntake"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, _format: str, *args: Any) -> None:
        # Report envelopes are privacy-bounded, but access logs still do not need
        # request paths, report keys, auth metadata, or client-controlled text.
        return

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        # Never fall back to BaseHTTPRequestHandler's implementation-detail HTML.
        del message, explain
        try:
            status = HTTPStatus(code)
        except ValueError:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._json(status, {"error": "request_rejected"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            self._unauthorized()
            return
        if urlsplit(self.path).path != _REPORT_PATH:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json_required"})
            return
        raw_length = str(self.headers.get("Content-Length") or "").strip()
        try:
            length = int(raw_length)
        except ValueError:
            length = -1
        if length <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if length > _MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "report_too_large"})
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "incomplete_body"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("report body must be an object")
            report_key = str(payload.get("report_key") or "").strip().lower()
            if not self._transport_keys_match(report_key, require_idempotency=True):
                raise ValueError("report transport identity does not match payload")
            result = self.server.intake.accept(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_report"})
            return
        except RuntimeError:
            # A report-key collision with different evidence is a protocol conflict,
            # never permission to overwrite the existing durable record.
            self._json(HTTPStatus.CONFLICT, {"error": "report_conflict"})
            return
        self._json(HTTPStatus.OK, result)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if not self._authorized():
            self._unauthorized()
            return
        path = urlsplit(self.path).path
        prefix = f"{_REPORT_PATH}/"
        if not path.startswith(prefix):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        report_key = unquote(path[len(prefix) :]).strip().lower()
        if not report_key or "/" in report_key:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._transport_keys_match(report_key, require_idempotency=False):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_report_key"})
            return
        try:
            result = self.server.intake.reconciliation(report_key)
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_report_key"})
            return
        self._json(HTTPStatus.OK, result)

    def _authorized(self) -> bool:
        header = str(self.headers.get("Authorization") or "")
        scheme, separator, supplied = header.partition(" ")
        if separator != " " or scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(supplied.strip(), self.server.bearer_token)

    def _transport_keys_match(self, report_key: str, *, require_idempotency: bool) -> bool:
        transport_key = str(self.headers.get("X-ZN-Report-Key") or "").strip().lower()
        if not report_key or not hmac.compare_digest(transport_key, report_key):
            return False
        if not require_idempotency:
            return True
        idempotency_key = str(self.headers.get("Idempotency-Key") or "").strip().lower()
        return hmac.compare_digest(idempotency_key, report_key)

    def _unauthorized(self) -> None:
        self._respond(
            HTTPStatus.UNAUTHORIZED,
            b'{"error":"unauthorized"}',
            authenticate=True,
        )

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._respond(status, body)

    def _respond(self, status: HTTPStatus, body: bytes, *, authenticate: bool = False) -> None:
        # Close after every bounded exchange. In particular, a rejected oversized
        # body is deliberately not consumed and therefore must not be reused as a
        # subsequent request on the same connection.
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if authenticate:
            self.send_header("WWW-Authenticate", 'Bearer realm="zn-maintainer-reports"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def build_server(
    *,
    database_path: str | Path,
    bearer_token: str,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> MaintainerReportHTTPServer:
    token = _validated_token(bearer_token)
    return MaintainerReportHTTPServer(
        (str(host), int(port)),
        intake=MaintainerBugReportIntake(database_path),
        bearer_token=token,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve bounded ZN maintainer defect-report intake")
    parser.add_argument(
        "--database",
        default=os.environ.get(_DB_ENV, ""),
        help=f"SQLite intake path (or {_DB_ENV})",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)

    database = str(args.database or "").strip()
    if not database:
        parser.error(f"--database or {_DB_ENV} is required")
    token = str(os.environ.get(_TOKEN_ENV) or "").strip()
    try:
        token = _validated_token(token)
    except ValueError as exc:
        parser.error(str(exc))

    server = build_server(
        database_path=database,
        bearer_token=token,
        host=str(args.host),
        port=int(args.port),
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

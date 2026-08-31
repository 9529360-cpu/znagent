from __future__ import annotations

"""Operator-controlled transport for privacy-safe upstream ZN defect reports.

This module deliberately does not know about GitHub, source repositories, release
credentials, updater authority, or maintainer identities. It only moves the
already-bounded report envelope to one explicitly configured HTTPS endpoint.

Dispatch is at-most-once unless independent reconciliation proves the report is
absent at the receiver. A lost response therefore remains outcome_uncertain and
is never blindly replayed.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx

from .upstream_bug_report import ResidentUpstreamBugReportOutbox

_ACK_SCHEMA = "zn-upstream-bug-report-ack-v1"


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _HttpClient(Protocol):
    def post(self, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str]) -> _HttpResponse: ...

    def get(self, url: str, *, headers: Mapping[str, str]) -> _HttpResponse: ...


class UpstreamBugReportTransportError(RuntimeError):
    pass


@dataclass(slots=True)
class UpstreamBugReportTransport:
    endpoint: str
    timeout_seconds: float = 10.0
    http_client: _HttpClient | None = None

    def __post_init__(self) -> None:
        self.endpoint = self._validated_endpoint(self.endpoint)
        self.timeout_seconds = max(1.0, min(60.0, float(self.timeout_seconds)))

    def dispatch(
        self,
        outbox: ResidentUpstreamBugReportOutbox,
        report_key: str,
    ) -> dict[str, Any]:
        payload = outbox.reserve_dispatch(report_key)
        key = str(payload["report_key"])
        try:
            response = self._client().post(
                self.endpoint,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Idempotency-Key": key,
                    "X-ZN-Report-Key": key,
                },
            )
            self._require_accepted_ack(response, key)
        except BaseException as exc:
            # Reservation was already durably committed. Even connect/timeout
            # failures are conservative uncertainty because the client cannot
            # prove whether the receiver observed the request.
            outbox.mark_outcome_uncertain(key, exc)
            if isinstance(exc, UpstreamBugReportTransportError):
                raise
            raise UpstreamBugReportTransportError(
                f"upstream bug report dispatch outcome is uncertain: {type(exc).__name__}"
            ) from exc
        return outbox.mark_delivered(key)

    def reconcile(
        self,
        outbox: ResidentUpstreamBugReportOutbox,
        report_key: str,
    ) -> dict[str, Any]:
        key = outbox.require_reconciliation(report_key)
        url = f"{self.endpoint.rstrip('/')}/{key}"
        try:
            response = self._client().get(
                url,
                headers={"Accept": "application/json", "X-ZN-Report-Key": key},
            )
        except BaseException as exc:
            raise UpstreamBugReportTransportError(
                f"upstream bug report reconciliation failed: {type(exc).__name__}"
            ) from exc

        if int(response.status_code) == 404:
            return outbox.mark_reconciled_absent(key)
        self._require_accepted_ack(response, key)
        return outbox.mark_reconciled_delivered(key)

    def _client(self) -> _HttpClient:
        if self.http_client is not None:
            return self.http_client
        return httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=True,
        )

    @staticmethod
    def _require_accepted_ack(response: _HttpResponse, report_key: str) -> None:
        status = int(response.status_code)
        if status < 200 or status >= 300:
            raise UpstreamBugReportTransportError(
                f"upstream bug report receiver returned HTTP {status}"
            )
        try:
            data = response.json()
        except Exception as exc:
            raise UpstreamBugReportTransportError(
                "upstream bug report receiver acknowledgement is not JSON"
            ) from exc
        if not isinstance(data, Mapping):
            raise UpstreamBugReportTransportError(
                "upstream bug report receiver acknowledgement is invalid"
            )
        if (
            str(data.get("schema") or "") != _ACK_SCHEMA
            or str(data.get("report_key") or "").lower() != report_key
            or data.get("accepted") is not True
        ):
            raise UpstreamBugReportTransportError(
                "upstream bug report receiver acknowledgement does not match dispatch"
            )

    @staticmethod
    def _validated_endpoint(value: str) -> str:
        endpoint = str(value or "").strip()
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() != "https":
            raise ValueError("upstream bug report endpoint must use HTTPS")
        if not parsed.hostname:
            raise ValueError("upstream bug report endpoint must include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("upstream bug report endpoint must not embed credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("upstream bug report endpoint must not include query or fragment")
        return endpoint.rstrip("/")

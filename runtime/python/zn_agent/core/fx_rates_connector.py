from __future__ import annotations

"""Frankfurter FX rates connector (R7): ZN's key-free currency tool.

Currency exchange rates and conversion become ZN tools through the
EXISTING M-8 OpenAPI REST adapter
(:mod:`zn_agent.core.openapi_rest_adapter`) — this module adds no new
mechanism, only trusted host configuration (the OpenAPI document below),
one attach helper, and a thin lookup/conversion layer that walks the
normal capability path (``ActionExecutionRuntime`` + ``ActionRequest``)
exactly the way a Work does.

The Frankfurter API serves ECB reference rates; no key is required.
Host note (verified live 2026-10-20): the old host
``api.frankfurter.app`` now 301-redirects to the canonical
``api.frankfurter.dev/v1`` used below; ``exchangerate.host`` now
requires an access key and is therefore out. ECB rates publish only on
trading days, so a "latest" query on a weekend serves Friday's rates,
and a historical query for a non-trading day silently serves the
previous trading day's rates — the returned ``rate_date`` is always
reported as the API returned it, and any mismatch is flagged explicitly.

Both services are read-only GETs, so every registered tool is
``read_only``; there are no write operations to approve.

api.frankfurter.dev sits behind Cloudflare, which rejects the default
Python-urllib agent, so every request goes through
:class:`FrankfurterPolicyHttpClient`: an identifying ``User-Agent``
plus polite request spacing, neither bypassable by the caller.

Failure honesty: a malformed currency code, an unknown currency, a
non-2xx response, a transport failure, or a malformed payload all raise
:class:`FxRatesError` with the concrete reason. Nothing here invents a
rate. Rates are informational reference data only; the skill layer says
so and gives no investment advice.
"""

import copy
import datetime
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .action_execution import ActionExecutionRuntime, ActionRequest
from .action_fabric import ActionFabricRegistry
from .body import NativeBody
from .models import utc_now
from .openapi_rest_adapter import (
    OpenApiRestAttachment,
    RestHttpClient,
    RestHttpResponse,
    UrllibRestHttpClient,
    attach_openapi_rest_tools,
)

__all__ = [
    "FRANKFURTER_PROVIDER_ID",
    "FRANKFURTER_SPEC",
    "FX_RATES_ACTION_ID",
    "FX_HISTORICAL_ACTION_ID",
    "FX_USER_AGENT",
    "SOURCE_LABEL",
    "FrankfurterPolicyHttpClient",
    "FxRatesAttachment",
    "FxRatesError",
    "attach_fx_rates_tools",
    "convert_currency",
    "lookup_fx_rates",
]

FRANKFURTER_PROVIDER_ID = "frankfurter_fx"
FX_RATES_ACTION_ID = f"rest.{FRANKFURTER_PROVIDER_ID}.get_latest_rates"
FX_HISTORICAL_ACTION_ID = f"rest.{FRANKFURTER_PROVIDER_ID}.get_historical_rates"

#: Frankfurter serves ECB reference rates, no key required.
SOURCE_LABEL = "Frankfurter (api.frankfurter.dev, ECB reference rates)"

#: Three-letter ISO 4217 shape; unknown-but-shaped codes surface the
#: API's own 404 honestly instead of being guessed at here.
_CURRENCY_RE = re.compile(r"[A-Z]{3}")

FRANKFURTER_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Frankfurter FX rates API", "version": "1.0.0"},
    "servers": [{"url": "https://api.frankfurter.dev/v1"}],
    "paths": {
        "/latest": {
            "get": {
                "operationId": "get_latest_rates",
                "summary": (
                    "Fetch the latest ECB reference exchange rates from "
                    "Frankfurter for a base currency"
                ),
                "parameters": [
                    {
                        "name": "base",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Base currency code, e.g. USD or EUR"
                            ),
                        },
                    },
                    {
                        "name": "symbols",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Comma-separated target currency codes, "
                                "e.g. EUR,CNY,JPY; omit for all ~30 "
                                "ECB currencies"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Latest rates with base, rate date and "
                            "currency->rate mapping"
                        )
                    }
                },
            }
        },
        "/{date}": {
            "get": {
                "operationId": "get_historical_rates",
                "summary": (
                    "Fetch ECB reference exchange rates from Frankfurter "
                    "for one past date"
                ),
                "parameters": [
                    {
                        "name": "date",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Rate date in YYYY-MM-DD form. ECB "
                                "publishes on trading days only; a "
                                "non-trading day serves the previous "
                                "trading day's rates."
                            ),
                        },
                    },
                    {
                        "name": "base",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Base currency code, e.g. USD or EUR"
                            ),
                        },
                    },
                    {
                        "name": "symbols",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Comma-separated target currency codes, "
                                "e.g. EUR,CNY,JPY; omit for all ~30 "
                                "ECB currencies"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Rates for the date with base, rate date "
                            "and currency->rate mapping"
                        )
                    }
                },
            }
        },
    },
}


class FxRatesError(RuntimeError):
    """One explicit FX lookup failure; the message IS the reason."""


#: Identifying agent string: api.frankfurter.dev sits behind Cloudflare,
#: which 403s the default Python-urllib agent (verified live 2026-10-20),
#: so every request carries this instead.
FX_USER_AGENT = "ZN-Agent-FX/0.1"

#: Default spacing between requests: Frankfurter is a free shared
#: resource and this connector is a guest on it.
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 1.0


class FrankfurterPolicyHttpClient:
    """``RestHttpClient`` wrapper enforcing the Frankfurter guest policy.

    Two policy rules live here so no caller can forget them:

    - every request carries the connector's identifying
      ``User-Agent`` (any caller-supplied agent is replaced; the
      default urllib agent is rejected by the host's CDN);
    - successive requests are spaced by at least
      ``min_interval_seconds``. The clock and sleeper are injectable so
      tests can prove the spacing without waiting.

    Requests are serialized through a lock: the Frankfurter service is a
    shared public resource and this connector is a guest on it.
    """

    def __init__(
        self,
        inner: RestHttpClient,
        *,
        user_agent: str = FX_USER_AGENT,
        min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not str(user_agent or "").strip():
            raise ValueError(
                "Frankfurter policy client needs an identifying User-Agent"
            )
        if float(min_interval_seconds) < 0:
            raise ValueError("min request interval must not be negative")
        self._inner = inner
        self._user_agent = str(user_agent)
        self._min_interval = float(min_interval_seconds)
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_at: float | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> RestHttpResponse:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                wait = self._min_interval - (now - self._last_request_at)
                if wait > 0:
                    self._sleeper(wait)
                    now = self._clock()
            self._last_request_at = now
            merged_headers = dict(headers)
            merged_headers["User-Agent"] = self._user_agent
            return self._inner.request(
                method,
                url,
                params=params,
                headers=merged_headers,
                json_body=json_body,
                timeout_seconds=timeout_seconds,
            )


@dataclass(slots=True)
class FxRatesAttachment:
    """The Frankfurter attachment; detach removes every tool at once."""

    attachment: OpenApiRestAttachment
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.attachment.detach()


def attach_fx_rates_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 15.0,
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    user_agent: str = FX_USER_AGENT,
) -> FxRatesAttachment:
    """Attach the Frankfurter FX rate tools to a Body/Fabric.

    Both operations are read-only, so no write approvals exist. Every
    request — real urllib transport by default — passes through
    :class:`FrankfurterPolicyHttpClient`, so the guest policy
    (identifying User-Agent + rate spacing) cannot be bypassed by a
    caller.
    """
    policy_client = FrankfurterPolicyHttpClient(
        http_client or UrllibRestHttpClient(),
        user_agent=user_agent,
        min_interval_seconds=min_request_interval_seconds,
    )
    attachment = attach_openapi_rest_tools(
        fabric=fabric,
        body=body,
        spec=copy.deepcopy(FRANKFURTER_SPEC),
        provider_id=FRANKFURTER_PROVIDER_ID,
        http_client=policy_client,
        timeout_seconds=timeout_seconds,
    )
    return FxRatesAttachment(attachment=attachment)


def _currency_code(value: Any, *, role: str) -> str:
    code = str(value or "").strip().upper()
    if not _CURRENCY_RE.fullmatch(code):
        raise FxRatesError(
            f"invalid {role} currency code {str(value)!r}: "
            "expected a 3-letter ISO 4217 code such as USD or EUR"
        )
    return code


def _rate_date(value: Any, *, stage: str) -> str:
    text = str(value or "").strip()
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        raise FxRatesError(
            f"FX {stage} returned a malformed rate date {value!r}"
        ) from None
    return text


def _number(value: Any, *, field: str, stage: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FxRatesError(
            f"FX {stage} returned a non-numeric {field}: {value!r}"
        )
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0:
        raise FxRatesError(
            f"FX {stage} returned an unusable {field}: {value!r}"
        )
    return rate


def _execute_json(
    runtime: ActionExecutionRuntime,
    action_id: str,
    args: Mapping[str, Any],
    *,
    event_id: str,
    stage: str,
) -> dict[str, Any]:
    outcome = runtime.execute(
        ActionRequest(action_id, dict(args), event_id=event_id)
    )
    if not outcome.success or outcome.body_result is None:
        reason = outcome.error or "no result returned"
        raise FxRatesError(f"FX {stage} failed: {reason}")
    try:
        payload = json.loads(outcome.body_result.output or "")
    except ValueError as exc:
        raise FxRatesError(
            f"FX {stage} returned a malformed payload"
        ) from exc
    if not isinstance(payload, dict):
        raise FxRatesError(f"FX {stage} returned a malformed payload")
    return payload


def _validate_date(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError:
        raise FxRatesError(
            f"invalid date {str(value)!r}: expected YYYY-MM-DD"
        ) from None
    if parsed > datetime.date.today():
        raise FxRatesError(
            f"invalid date {text}: historical rates need a past or "
            "today's date"
        )
    return text


def lookup_fx_rates(
    runtime: ActionExecutionRuntime,
    base_currency: str,
    *,
    symbols: list[str] | None = None,
    date: str | None = None,
    event_id: str,
) -> dict[str, Any]:
    """Fetch ECB reference rates for one base currency.

    Without ``date`` this queries /latest; with ``date`` (YYYY-MM-DD)
    the historical path. The returned ``rate_date`` is always the date
    the API actually served (ECB publishes trading days only): when it
    differs from today or from the requested date, the answer flags it
    explicitly instead of letting stale data pass as current.
    """
    base = _currency_code(base_currency, role="base")
    wanted: list[str] | None = None
    if symbols is not None:
        wanted = [_currency_code(code, role="target") for code in symbols]
        if base in wanted:
            wanted = [code for code in wanted if code != base]
    requested_date: str | None = None
    if date is not None:
        requested_date = _validate_date(date)
    retrieved_at = utc_now()

    if requested_date is None:
        action_id = FX_RATES_ACTION_ID
        args: dict[str, Any] = {"base": base}
        stage = "latest rates"
    else:
        action_id = FX_HISTORICAL_ACTION_ID
        args = {"date": requested_date, "base": base}
        stage = "historical rates"
    if wanted:
        args["symbols"] = ",".join(wanted)

    payload = _execute_json(
        runtime, action_id, args, event_id=event_id, stage=stage
    )
    rates = payload.get("rates")
    if not isinstance(rates, Mapping) or not rates:
        raise FxRatesError(f"FX {stage} returned no rates")
    normalized: dict[str, float] = {}
    for code, value in rates.items():
        normalized[_currency_code(code, role="returned")] = _number(
            value, field=f"rate for {code}", stage=stage
        )
    served_date = _rate_date(payload.get("date"), stage=stage)
    served_base = _currency_code(payload.get("base"), role="returned base")
    if served_base != base:
        raise FxRatesError(
            f"FX {stage} served base {served_base} for requested base {base}"
        )

    missing: list[str] = []
    if wanted:
        missing = [code for code in wanted if code not in normalized]
    today = datetime.date.today().isoformat()
    return {
        "base_currency": base,
        "requested_symbols": wanted,
        "missing_symbols": missing,
        "rates": normalized,
        "requested_date": requested_date,
        "rate_date": served_date,
        "rate_is_not_current_day": requested_date is None
        and served_date != today,
        "date_was_adjusted": requested_date is not None
        and served_date != requested_date,
        "source": SOURCE_LABEL,
        "retrieved_at": retrieved_at,
        "note": (
            "ECB reference rates via Frankfurter; informational only, "
            "not investment advice"
        ),
    }


def convert_currency(
    runtime: ActionExecutionRuntime,
    amount: float,
    from_currency: str,
    to_currency: str,
    *,
    date: str | None = None,
    event_id: str,
) -> dict[str, Any]:
    """Convert one amount between two currencies at ECB reference rates.

    Same-currency conversion is answered locally as 1:1 without a
    network call, and says so explicitly.
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise FxRatesError(
            f"invalid amount {amount!r}: expected a number"
        )
    quantity = float(amount)
    if not math.isfinite(quantity):
        raise FxRatesError(f"invalid amount {amount!r}: not finite")
    if quantity < 0:
        raise FxRatesError(f"invalid amount {amount!r}: must be >= 0")

    source = _currency_code(from_currency, role="source")
    target = _currency_code(to_currency, role="target")
    if source == target:
        return {
            "from_currency": source,
            "to_currency": target,
            "amount": quantity,
            "converted_amount": quantity,
            "rate": 1.0,
            "requested_date": None if date is None else _validate_date(date),
            "rate_date": None,
            "local_only": True,
            "source": SOURCE_LABEL,
            "retrieved_at": utc_now(),
            "note": (
                "same currency: 1:1, answered locally without a rate "
                "query; informational only, not investment advice"
            ),
        }

    answer = lookup_fx_rates(
        runtime,
        source,
        symbols=[target],
        date=date,
        event_id=event_id,
    )
    rate = answer["rates"].get(target)
    if rate is None:
        raise FxRatesError(
            f"no {target} rate in {source} rates "
            f"(rate date {answer['rate_date']})"
        )
    return {
        "from_currency": source,
        "to_currency": target,
        "amount": quantity,
        "converted_amount": quantity * rate,
        "rate": rate,
        "requested_date": answer["requested_date"],
        "rate_date": answer["rate_date"],
        "rate_is_not_current_day": answer["rate_is_not_current_day"],
        "date_was_adjusted": answer["date_was_adjusted"],
        "missing_symbols": answer["missing_symbols"],
        "local_only": False,
        "source": answer["source"],
        "retrieved_at": answer["retrieved_at"],
        "note": (
            "ECB reference rates via Frankfurter; informational only, "
            "not investment advice"
        ),
    }

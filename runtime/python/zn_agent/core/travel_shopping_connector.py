from __future__ import annotations

"""Travel & shopping query connectors (R12): ZN's key-free lookup tools.

Flight movements, product price observations, and a local offer
comparison engine become ZN tools through the EXISTING M-8 OpenAPI REST
adapter (:mod:`zn_agent.core.openapi_rest_adapter`) — this module adds
no new mechanism, only trusted host configuration (the two OpenAPI
documents below), one attach helper per provider, and thin lookup /
comparison layers that walk the normal capability path
(``ActionExecutionRuntime`` + ``ActionRequest``) exactly the way a Work
does.

Provider selection (verified live 2026-10-21 before landing; the full
rationale lives in ``docs/ZN-IMPLEMENTATION-STATUS.md`` under R12):

- **Flights — OpenSky Network** (``https://opensky-network.org/api``),
  no key required for anonymous use. Serves ADS-B *observed* departures
  and arrivals per airport (ICAO code + unix time window). This is
  availability/schedule information, NOT ticket prices: OpenSky has no
  fares, and every keyed fare source (Duffel, Amadeus, Skyscanner) needs
  an account key, so fares stay a documented placeholder until a keyed
  provider is wired at deployment time. OpenSky's data use is granted
  for non-profit research/education; commercial use needs their written
  licence — ZN is the user's private assistant, not a commercial
  product, and the skill states this boundary.
- **Product prices — Open Prices** (``https://prices.openfoodfacts.org``,
  the OpenFoodFacts price observatory), no key required. Serves
  crowdsourced price observations, each backed by a receipt/proof
  photo. Coverage is strongest for groceries and everyday goods in the
  OFF ecosystem. Currency and observation date live on the *proof*
  record; a price whose currency cannot be resolved is reported as
  ``currency_unknown`` and is never ranked — it cannot be compared
  honestly without a currency.
- **Hotels — no key-free source exists.** Amadeus Self-Service (incl.
  Hotel Search) was decommissioned 2026-07-17, Booking.com Demand API
  is contracted-partners only, and Google Hotels has no public API.
  Per the R12 rule ("an unstable source gets documented, not wired"),
  hotels are documented as a keyed-provider placeholder only. There is
  no hotel tool in this module and no hotel data is fabricated.

All three providers are read-only GETs, so every registered tool is
``read_only``. **There are no purchase, booking, or payment actions
anywhere in this module — by design, not by omission.** Buying stays a
separate future item that must go through approval.

Failure honesty: a malformed airport/product code, a non-2xx response,
a transport failure, or a malformed payload all raise
:class:`TravelShoppingError` with the concrete reason. Nothing here
invents a flight, a price, or a ranking.

Freshness honesty: every answer carries ``retrieved_at`` (when ZN
fetched it) and the source's own date (flight observation window,
proof/receipt date). :func:`compare_offers` labels every offer
``fresh`` / ``aging`` / ``stale`` / ``expired`` and refuses to crown a
winner across mixed currencies or from currency-unknown quotes. Stale
data is never passed off as current.
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
    "OPENPRICES_PROVIDER_ID",
    "OPENPRICES_SPEC",
    "OPENPRICES_USER_AGENT",
    "OPENSKY_PROVIDER_ID",
    "OPENSKY_SPEC",
    "OPENSKY_USER_AGENT",
    "PRICES_ACTION_ID",
    "ARRIVALS_ACTION_ID",
    "DEPARTURES_ACTION_ID",
    "SOURCE_LABEL_FLIGHTS",
    "SOURCE_LABEL_PRICES",
    "GuestPolicyHttpClient",
    "OpenPricesAttachment",
    "OpenSkyAttachment",
    "TravelShoppingError",
    "attach_openprices_tools",
    "attach_opensky_tools",
    "compare_offers",
    "lookup_flight_movements",
    "lookup_product_prices",
    "quote_age_status",
]

#: Provider namespaces for the M-8 adapter (lowercase, stable).
OPENSKY_PROVIDER_ID = "opensky_flights"
OPENPRICES_PROVIDER_ID = "openprices_prices"

DEPARTURES_ACTION_ID = f"rest.{OPENSKY_PROVIDER_ID}.get_departures"
ARRIVALS_ACTION_ID = f"rest.{OPENSKY_PROVIDER_ID}.get_arrivals"
PRICES_ACTION_ID = f"rest.{OPENPRICES_PROVIDER_ID}.query_prices"

SOURCE_LABEL_FLIGHTS = (
    "OpenSky Network (opensky-network.org, ADS-B observed flight data)"
)
SOURCE_LABEL_PRICES = (
    "Open Prices (prices.openfoodfacts.org, crowdsourced receipt-backed "
    "price observations)"
)

#: Identifying agent strings: both hosts are free shared resources and
#: this connector is a guest on them.
OPENSKY_USER_AGENT = "ZN-Agent-Travel/0.1"
OPENPRICES_USER_AGENT = "ZN-Agent-Shopping/0.1"

#: Polite spacing between requests. OpenSky's anonymous quota is the
#: tighter of the two, so it gets the longer interval.
OPENSKY_MIN_REQUEST_INTERVAL_SECONDS = 5.0
OPENPRICES_MIN_REQUEST_INTERVAL_SECONDS = 1.0

_ICAO_RE = re.compile(r"[A-Z]{4}")
_BARCODE_RE = re.compile(r"[0-9]{4,20}")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")

#: OpenSky serves observed flights; keep the window sane.
_MAX_WINDOW_HOURS = 168  # 7 days

#: Offer freshness bands, in hours since retrieval.
_FRESH_HOURS = 24.0
_AGING_HOURS = 168.0  # 7 days


OPENSKY_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "OpenSky Network flight API", "version": "1.0.0"},
    "servers": [{"url": "https://opensky-network.org/api"}],
    "paths": {
        "/flights/departure": {
            "get": {
                "operationId": "get_departures",
                "summary": (
                    "Observed departures from one airport in a time "
                    "window (ADS-B). Schedule/availability information "
                    "only — no fares."
                ),
                "parameters": [
                    {
                        "name": "airport",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "ICAO airport code, e.g. EDDF, EGLL, "
                                "ZBAA"
                            ),
                        },
                    },
                    {
                        "name": "begin",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Window start as unix epoch seconds"
                            ),
                        },
                    },
                    {
                        "name": "end",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Window end as unix epoch seconds"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "List of observed departures (may be empty)"
                        )
                    }
                },
            }
        },
        "/flights/arrival": {
            "get": {
                "operationId": "get_arrivals",
                "summary": (
                    "Observed arrivals at one airport in a time window "
                    "(ADS-B). Schedule/availability information only — "
                    "no fares."
                ),
                "parameters": [
                    {
                        "name": "airport",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "ICAO airport code, e.g. EDDF, EGLL, "
                                "ZBAA"
                            ),
                        },
                    },
                    {
                        "name": "begin",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Window start as unix epoch seconds"
                            ),
                        },
                    },
                    {
                        "name": "end",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Window end as unix epoch seconds"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "List of observed arrivals (may be empty)"
                        )
                    }
                },
            }
        },
    },
}

#: NOTE: no trailing slash — prices.openfoodfacts.org 404s the
#: trailing-slash form (verified live 2026-10-21).
OPENPRICES_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Open Prices API", "version": "1.0.0"},
    "servers": [{"url": "https://prices.openfoodfacts.org"}],
    "paths": {
        "/api/v1/prices": {
            "get": {
                "operationId": "query_prices",
                "summary": (
                    "Crowdsourced price observations for one product "
                    "(by barcode/EAN), newest first. Each observation "
                    "is receipt/proof backed."
                ),
                "parameters": [
                    {
                        "name": "product_code",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Product barcode (EAN), e.g. "
                                "3017620422003"
                            ),
                        },
                    },
                    {
                        "name": "size",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Max observations to return (1-100, "
                                "default 3; keep it small — the runtime "
                                "caps tool output at ~12k chars)"
                            ),
                        },
                    },
                    {
                        "name": "order_by",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Sort order; use -date for newest "
                                "observations first"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Price observations with product, location "
                            "and proof detail (may be empty)"
                        )
                    }
                },
            }
        },
    },
}


class TravelShoppingError(RuntimeError):
    """One explicit travel/shopping lookup failure; the message IS the reason."""


class GuestPolicyHttpClient:
    """``RestHttpClient`` wrapper enforcing the guest policy of a provider.

    Two policy rules live here so no caller can forget them:

    - every request carries the connector's identifying ``User-Agent``
      (any caller-supplied agent is replaced);
    - successive requests are spaced by at least ``min_interval_seconds``.
      The clock and sleeper are injectable so tests can prove the
      spacing without waiting.

    Requests are serialized through a lock: both providers are free
    shared resources and this connector is a guest on them.

    ``empty_404_means_empty_list`` normalizes one documented provider
    quirk (OpenSky only, verified live 2026-10-21): the flight endpoints
    answer HTTP 404 with a JSON ``[]`` body when no flights match the
    requested window — the same path returns 200 with data when flights
    exist, so the 404 is "no results", not "not found". When enabled, a
    404 whose body parses as exactly ``[]`` is translated to a 200 with
    that body; any other 404 body still surfaces as an error. Off by
    default.
    """

    def __init__(
        self,
        inner: RestHttpClient,
        *,
        user_agent: str,
        min_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        empty_404_means_empty_list: bool = False,
    ) -> None:
        if not str(user_agent or "").strip():
            raise ValueError(
                "guest policy client needs an identifying User-Agent"
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
        self._empty_404_means_empty_list = bool(empty_404_means_empty_list)

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
            response = self._inner.request(
                method,
                url,
                params=params,
                headers=merged_headers,
                json_body=json_body,
                timeout_seconds=timeout_seconds,
            )
            if (
                self._empty_404_means_empty_list
                and response.status_code == 404
            ):
                try:
                    empty = json.loads(response.text)
                except ValueError:
                    empty = None
                if empty == []:
                    return RestHttpResponse(
                        200, dict(response.headers), response.body
                    )
            return response


@dataclass(slots=True)
class OpenSkyAttachment:
    """The OpenSky attachment; detach removes every tool at once."""

    attachment: OpenApiRestAttachment
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.attachment.detach()


@dataclass(slots=True)
class OpenPricesAttachment:
    """The Open Prices attachment; detach removes every tool at once."""

    attachment: OpenApiRestAttachment
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.attachment.detach()


def attach_opensky_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 20.0,
    min_request_interval_seconds: float = OPENSKY_MIN_REQUEST_INTERVAL_SECONDS,
    user_agent: str = OPENSKY_USER_AGENT,
) -> OpenSkyAttachment:
    """Attach the OpenSky flight-movement tools to a Body/Fabric.

    Both operations are read-only, so no write approvals exist. Every
    request — real urllib transport by default — passes through
    :class:`GuestPolicyHttpClient`, so the guest policy (identifying
    User-Agent + request spacing) cannot be bypassed by a caller.
    """
    policy_client = GuestPolicyHttpClient(
        http_client or UrllibRestHttpClient(),
        user_agent=user_agent,
        min_interval_seconds=min_request_interval_seconds,
        # OpenSky answers 404 + `[]` when a window has no flights
        # (verified live 2026-10-21); normalize that one quirk only.
        empty_404_means_empty_list=True,
    )
    attachment = attach_openapi_rest_tools(
        fabric=fabric,
        body=body,
        spec=copy.deepcopy(OPENSKY_SPEC),
        provider_id=OPENSKY_PROVIDER_ID,
        http_client=policy_client,
        timeout_seconds=timeout_seconds,
    )
    return OpenSkyAttachment(attachment=attachment)


def attach_openprices_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 15.0,
    min_request_interval_seconds: float = (
        OPENPRICES_MIN_REQUEST_INTERVAL_SECONDS
    ),
    user_agent: str = OPENPRICES_USER_AGENT,
) -> OpenPricesAttachment:
    """Attach the Open Prices product-price tools to a Body/Fabric.

    Read-only; no write approvals exist. Same guest-policy guarantees
    as :func:`attach_opensky_tools`.
    """
    policy_client = GuestPolicyHttpClient(
        http_client or UrllibRestHttpClient(),
        user_agent=user_agent,
        min_interval_seconds=min_request_interval_seconds,
    )
    attachment = attach_openapi_rest_tools(
        fabric=fabric,
        body=body,
        spec=copy.deepcopy(OPENPRICES_SPEC),
        provider_id=OPENPRICES_PROVIDER_ID,
        http_client=policy_client,
        timeout_seconds=timeout_seconds,
    )
    return OpenPricesAttachment(attachment=attachment)


def _icao_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not _ICAO_RE.fullmatch(code):
        raise TravelShoppingError(
            f"invalid airport code {str(value)!r}: expected a 4-letter "
            "ICAO code such as EDDF, EGLL or ZBAA"
        )
    return code


def _barcode(value: Any) -> str:
    code = str(value or "").strip()
    if not _BARCODE_RE.fullmatch(code):
        raise TravelShoppingError(
            f"invalid product code {str(value)!r}: expected the numeric "
            "barcode (EAN) printed on the product, e.g. 3017620422003"
        )
    return code


def _epoch(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TravelShoppingError(
            f"OpenSky returned a non-numeric {field}: {value!r}"
        )
    stamp = int(value)
    if stamp <= 0:
        raise TravelShoppingError(
            f"OpenSky returned an unusable {field}: {value!r}"
        )
    return stamp


def _price_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TravelShoppingError(
            f"Open Prices returned a non-numeric {field}: {value!r}"
        )
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        raise TravelShoppingError(
            f"Open Prices returned an unusable {field}: {value!r}"
        )
    return amount


def _currency_or_none(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if not _CURRENCY_RE.fullmatch(text):
        return None
    return text


def _iso_date_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    # Proof dates may carry a time component; keep the calendar date.
    day = text[:10]
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        return None
    return day


def _execute_json(
    runtime: ActionExecutionRuntime,
    action_id: str,
    args: Mapping[str, Any],
    *,
    event_id: str,
    stage: str,
) -> Any:
    outcome = runtime.execute(
        ActionRequest(action_id, dict(args), event_id=event_id)
    )
    if not outcome.success or outcome.body_result is None:
        reason = outcome.error or "no result returned"
        raise TravelShoppingError(f"{stage} failed: {reason}")
    data = outcome.body_result.data or {}
    if data.get("truncated"):
        # The M-8 adapter caps tool output at ~12k chars; a truncated
        # JSON body would parse as garbage, so say so explicitly and
        # tell the caller how to get a complete answer instead.
        raise TravelShoppingError(
            f"{stage} returned more data than the tool output limit "
            "allows; narrow the request (fewer hours, smaller size) "
            "and try again"
        )
    try:
        return json.loads(outcome.body_result.output or "")
    except ValueError as exc:
        raise TravelShoppingError(
            f"{stage} returned a malformed payload"
        ) from exc


def _window(*, hours_back: float) -> tuple[int, int]:
    if (
        isinstance(hours_back, bool)
        or not isinstance(hours_back, (int, float))
        or not math.isfinite(float(hours_back))
    ):
        raise TravelShoppingError(
            f"invalid hours_back {hours_back!r}: expected a number of hours"
        )
    hours = float(hours_back)
    if hours <= 0 or hours > _MAX_WINDOW_HOURS:
        raise TravelShoppingError(
            f"invalid hours_back {hours_back!r}: expected 0 < hours <= "
            f"{_MAX_WINDOW_HOURS}"
        )
    end = int(time.time())
    begin = end - int(hours * 3600)
    return begin, end


def _iso_from_epoch(stamp: int) -> str:
    return (
        datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def lookup_flight_movements(
    runtime: ActionExecutionRuntime,
    airport: str,
    *,
    direction: str = "departure",
    hours_back: float = 6.0,
    event_id: str,
) -> dict[str, Any]:
    """Observed flight movements for one airport (OpenSky, ADS-B).

    ``direction`` is ``"departure"`` or ``"arrival"``; the window covers
    the last ``hours_back`` hours (0 < hours <= 168). Returns the
    observed movements plus honesty metadata: airports are *estimated*
    from ADS-B tracks (``estDepartureAirport``), and an empty list is a
    real answer ("no observed movements in this window"), never an
    error. These are observed movements — schedule/availability
    information — not ticket prices; OpenSky has no fares. Very busy
    windows can exceed the adapter's ~12k char tool-output cap; that
    surfaces as an explicit "narrow the request" error, never as a
    silently cut list.
    """
    code = _icao_code(airport)
    side = str(direction or "").strip().lower()
    if side == "departure":
        action_id = DEPARTURES_ACTION_ID
    elif side == "arrival":
        action_id = ARRIVALS_ACTION_ID
    else:
        raise TravelShoppingError(
            f"invalid direction {direction!r}: expected 'departure' or "
            "'arrival'"
        )
    begin, end = _window(hours_back=hours_back)
    retrieved_at = utc_now()

    payload = _execute_json(
        runtime,
        action_id,
        {"airport": code, "begin": begin, "end": end},
        event_id=event_id,
        stage=f"OpenSky {side}s",
    )
    if not isinstance(payload, list):
        raise TravelShoppingError(
            f"OpenSky {side}s returned a malformed payload: expected a "
            "list of movements"
        )
    movements: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise TravelShoppingError(
                f"OpenSky {side}s returned a malformed movement at "
                f"index {index}"
            )
        first_seen = _epoch(item.get("firstSeen"), field="firstSeen")
        last_seen = _epoch(item.get("lastSeen"), field="lastSeen")
        movements.append(
            {
                "callsign": str(item.get("callsign") or "").strip() or None,
                "icao24": str(item.get("icao24") or "").strip() or None,
                "departure_airport": item.get("estDepartureAirport"),
                "arrival_airport": item.get("estArrivalAirport"),
                "first_seen": _iso_from_epoch(first_seen),
                "last_seen": _iso_from_epoch(last_seen),
            }
        )
    return {
        "airport": code,
        "direction": side,
        "window_begin": _iso_from_epoch(begin),
        "window_end": _iso_from_epoch(end),
        "movements": movements,
        "movement_count": len(movements),
        "source": SOURCE_LABEL_FLIGHTS,
        "retrieved_at": retrieved_at,
        "note": (
            "ADS-B observed movements in the window; airports are "
            "estimated from tracks (estDepartureAirport / "
            "estArrivalAirport). Availability/schedule information "
            "only — OpenSky carries no ticket prices."
        ),
    }


def _observation_date(item: Mapping[str, Any]) -> tuple[str | None, str]:
    """Resolve an observation's currency and date, with provenance."""
    currency = _currency_or_none(item.get("currency"))
    observed = _iso_date_or_none(item.get("date"))
    provenance = "price"
    if currency is None or observed is None:
        proof = item.get("proof")
        if isinstance(proof, Mapping):
            if currency is None:
                currency = _currency_or_none(proof.get("currency"))
                if currency is not None:
                    provenance = "proof"
            if observed is None:
                observed = _iso_date_or_none(proof.get("date"))
    return currency, observed or "unknown"


def lookup_product_prices(
    runtime: ActionExecutionRuntime,
    product_code: str,
    *,
    event_id: str,
    limit: int = 3,
) -> dict[str, Any]:
    """Crowdsourced price observations for one product (Open Prices).

    ``limit`` is clamped to 1..100; observations come back newest-first.
    The default is 3 because one observation embeds its full product,
    location and proof records (~3.3 KB) and the M-8 adapter caps tool
    output at ~12k chars — ask for more than fits and you get an
    explicit "narrow the request" error instead of a silently cut list.
    Each observation carries ``price``, ``currency`` (resolved from the
    price record, falling back to its receipt proof), ``observed_date``
    (proof/receipt date, or ``"unknown"``), the store name and the proof
    id backing it. An observation whose currency cannot be resolved is
    flagged ``currency_unknown`` and ``comparable: False`` — it is
    reported, never ranked, because a price without a currency cannot be
    compared honestly.
    """
    code = _barcode(product_code)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 100
    ):
        raise TravelShoppingError(
            f"invalid limit {limit!r}: expected an integer 1..100"
        )
    retrieved_at = utc_now()

    payload = _execute_json(
        runtime,
        PRICES_ACTION_ID,
        {"product_code": code, "size": limit, "order_by": "-date"},
        event_id=event_id,
        stage="Open Prices query",
    )
    if not isinstance(payload, Mapping):
        raise TravelShoppingError(
            "Open Prices returned a malformed payload: expected an object"
        )
    items = payload.get("items")
    if not isinstance(items, list):
        raise TravelShoppingError(
            "Open Prices returned a malformed payload: 'items' is not a list"
        )
    observations: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise TravelShoppingError(
                "Open Prices returned a malformed observation at index "
                f"{index}"
            )
        price = _price_number(item.get("price"), field="price")
        currency, observed_date = _observation_date(item)
        product = item.get("product")
        product_name = None
        if isinstance(product, Mapping):
            product_name = product.get("product_name") or None
        location = item.get("location")
        store_name = None
        if isinstance(location, Mapping):
            store_name = (
                location.get("osm_name")
                or location.get("osm_display_name")
                or None
            )
        proof = item.get("proof")
        proof_id = None
        if isinstance(proof, Mapping):
            proof_id = proof.get("id")
        observations.append(
            {
                "price": price,
                "currency": currency,
                "currency_unknown": currency is None,
                "observed_date": observed_date,
                "date_unknown": observed_date == "unknown",
                "discounted": bool(item.get("price_is_discounted")),
                "store": store_name,
                "product_name": product_name,
                "proof_id": proof_id,
                "comparable": currency is not None,
            }
        )
    return {
        "product_code": code,
        "observations": observations,
        "observation_count": len(observations),
        "total_matching": payload.get("total"),
        "source": SOURCE_LABEL_PRICES,
        "retrieved_at": retrieved_at,
        "note": (
            "Crowdsourced observations, each backed by a receipt/proof "
            "photo (proof_id). Currency/date come from the price record "
            "or its proof; observations without a resolvable currency "
            "are flagged and never ranked."
        ),
    }


def quote_age_status(
    retrieved_at: str | Mapping[str, Any] | None,
    *,
    now: datetime.datetime | None = None,
) -> str:
    """Classify a quote's freshness: ``fresh`` / ``aging`` / ``stale``.

    ``retrieved_at`` is an ISO-8601 timestamp (or a mapping carrying
    one under ``"retrieved_at"``). Unparseable or missing timestamps are
    ``"stale"`` — a quote that cannot prove its age is treated as old,
    never as fresh.
    """
    stamp: str | None = None
    if isinstance(retrieved_at, Mapping):
        stamp = retrieved_at.get("retrieved_at")
    elif isinstance(retrieved_at, str):
        stamp = retrieved_at
    if not stamp:
        return "stale"
    try:
        moment = datetime.datetime.fromisoformat(
            str(stamp).replace("Z", "+00:00")
        )
    except ValueError:
        return "stale"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    ref = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)
    age_hours = (ref - moment).total_seconds() / 3600.0
    if age_hours < 0:
        return "fresh"  # clock skew: do not punish the quote
    if age_hours <= _FRESH_HOURS:
        return "fresh"
    if age_hours <= _AGING_HOURS:
        return "aging"
    return "stale"


def _offer_amount(offer: Mapping[str, Any], index: int) -> float:
    amount = offer.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TravelShoppingError(
            f"offer {index} has a non-numeric amount: {amount!r}"
        )
    value = float(amount)
    if not math.isfinite(value) or value < 0:
        raise TravelShoppingError(
            f"offer {index} has an unusable amount: {amount!r}"
        )
    return value


def _offer_expiry(offer: Mapping[str, Any]) -> str | None:
    raw = offer.get("expires_at")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        moment = datetime.datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError:
        raise TravelShoppingError(
            f"offer has a malformed expires_at: {raw!r}"
        ) from None
    return moment.isoformat()


def compare_offers(
    offers: list[Mapping[str, Any]],
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Compare same-currency offers locally; no network involved.

    Each offer needs ``label``, ``amount`` (number >= 0), ``currency``
    (3-letter code) and ``retrieved_at`` (ISO-8601); ``source`` and
    ``expires_at`` are optional. Rules, in order:

    - an offer with an unparseable amount/currency is rejected loudly
      (a comparison built on a broken offer is worse than none);
    - expired offers (``expires_at`` in the past) are listed but marked
      ``expired`` and excluded from the ranking;
    - every ranked offer is labelled ``fresh`` / ``aging`` / ``stale``
      by :func:`quote_age_status`;
    - offers spanning more than one currency are NOT ranked — the
      result says so and points at the currency tools instead of
      guessing a conversion.

    The return value is the comparison table itself: ranked offers
    cheapest-first (or ``ranking: None`` with the reason), the cheapest
    offer when one exists, and the per-offer freshness/expiry labels.
    """
    if not isinstance(offers, list) or not offers:
        raise TravelShoppingError(
            "compare_offers needs a non-empty list of offers"
        )
    ref = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)

    normalized: list[dict[str, Any]] = []
    for index, offer in enumerate(offers):
        if not isinstance(offer, Mapping):
            raise TravelShoppingError(
                f"offer {index} is not an object: {offer!r}"
            )
        label = str(offer.get("label") or f"offer {index}").strip()
        amount = _offer_amount(offer, index)
        currency = _currency_or_none(offer.get("currency"))
        if currency is None:
            raise TravelShoppingError(
                f"offer {index} ({label}) has no usable currency: "
                f"{offer.get('currency')!r} — a price without a currency "
                "cannot be compared"
            )
        retrieved = offer.get("retrieved_at")
        expiry = _offer_expiry(offer)
        expired = False
        if expiry is not None:
            expired = (
                datetime.datetime.fromisoformat(expiry) <= ref
            )
        normalized.append(
            {
                "label": label,
                "amount": amount,
                "currency": currency,
                "source": offer.get("source"),
                "retrieved_at": retrieved,
                "age_status": quote_age_status(retrieved, now=ref),
                "expires_at": expiry,
                "expired": expired,
            }
        )

    currencies = {offer["currency"] for offer in normalized}
    rankable = [offer for offer in normalized if not offer["expired"]]
    ranking: list[dict[str, Any]] | None = None
    cheapest: dict[str, Any] | None = None
    ranking_note: str | None = None
    if len(currencies) > 1:
        ranking_note = (
            f"offers span {len(currencies)} currencies "
            f"({', '.join(sorted(currencies))}): not ranked. Convert to "
            "one currency first (see the currency skill), then compare "
            "again — ranking across currencies without conversion "
            "would be guessing."
        )
    elif rankable:
        ranking = sorted(rankable, key=lambda o: o["amount"])
        cheapest = ranking[0]
    else:
        ranking_note = "every offer is expired: nothing rankable remains"

    return {
        "offers": normalized,
        "currencies": sorted(currencies),
        "ranking": ranking,
        "cheapest": cheapest,
        "ranking_note": ranking_note,
        "compared_at": ref.isoformat(),
        "note": (
            "Local comparison only — no prices were fetched or changed "
            "here. Every offer keeps its source and retrieval time; "
            "expired offers are excluded from the ranking and stale "
            "ones are labelled, never silently treated as current."
        ),
    }

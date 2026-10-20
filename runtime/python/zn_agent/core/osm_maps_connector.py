from __future__ import annotations

"""OSM maps connector (R4): addresses, coordinates and nearby places.

Two key-free OpenStreetMap services become ZN tools through the
EXISTING M-8 OpenAPI REST adapter
(:mod:`zn_agent.core.openapi_rest_adapter`) — this module adds no new
mechanism, only trusted host configuration (the two OpenAPI documents
below), one attach helper, and thin lookups that walk the normal
capability path (``ActionExecutionRuntime`` + ``ActionRequest``) exactly
the way a Work does: geocode an address to coordinates, reverse-geocode
coordinates to an address, query Overpass for places near a point, and
estimate the straight-line distance between two addresses.

OSM usage policy compliance is part of the connector, not an option:
every request goes through :class:`OsmPolicyHttpClient`, which stamps
an identifying ``User-Agent`` (Nominatim refuses anonymous/default
agents) and enforces a minimum interval between requests (Nominatim's
published maximum is 1 request per second; the same conservative
interval is applied to Overpass fair use). The documents below are
trusted host configuration, never model-supplied. Both services are
read-only GETs, so every registered tool is ``read_only``.

Failure honesty: an address with no geocoding match, a non-2xx
response, a transport failure, an Overpass error remark, or a malformed
payload all raise :class:`MapsLookupError` with the concrete reason.
Distances are labelled straight-line (haversine) estimates — this
connector never presents them as road distances or travel times.
"""

import copy
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
    "GEOCODE_ACTION_ID",
    "NOMINATIM_PROVIDER_ID",
    "NOMINATIM_SPEC",
    "OSM_USER_AGENT",
    "OVERPASS_ACTION_ID",
    "OVERPASS_PROVIDER_ID",
    "OVERPASS_SPEC",
    "REVERSE_GEOCODE_ACTION_ID",
    "MapsLookupError",
    "OsmMapsAttachment",
    "OsmPolicyHttpClient",
    "attach_osm_maps_tools",
    "build_overpass_nearby_query",
    "estimate_distance",
    "find_nearby_places",
    "geocode_address",
    "haversine_km",
    "reverse_geocode",
]

NOMINATIM_PROVIDER_ID = "osm_nominatim"
OVERPASS_PROVIDER_ID = "osm_overpass"
GEOCODE_ACTION_ID = f"rest.{NOMINATIM_PROVIDER_ID}.geocode_address"
REVERSE_GEOCODE_ACTION_ID = f"rest.{NOMINATIM_PROVIDER_ID}.reverse_geocode"
OVERPASS_ACTION_ID = f"rest.{OVERPASS_PROVIDER_ID}.query_interpreter"

SOURCE_LABEL = (
    "OpenStreetMap (nominatim.openstreetmap.org + overpass-api.de)"
)

#: Nominatim's usage policy requires an HTTP User-Agent that identifies
#: the application; generic library defaults are blocked. This product
#: token names the application and its version, nothing more.
OSM_USER_AGENT = "ZN-Agent-Maps/0.1"

#: Nominatim's published absolute maximum is 1 request/second. The same
#: conservative floor is applied to Overpass (fair-use) requests.
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 1.0

_TAG_KEY_RE = re.compile(r"[A-Za-z0-9_:\-.]{1,64}\Z")

NOMINATIM_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Nominatim OpenStreetMap API", "version": "1.0.0"},
    "servers": [{"url": "https://nominatim.openstreetmap.org"}],
    "paths": {
        "/search": {
            "get": {
                "operationId": "geocode_address",
                "summary": (
                    "Resolve an address or place name to coordinates "
                    "with the Nominatim geocoding service"
                ),
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Free-form address or place name, e.g. "
                                "'Brandenburger Tor, Berlin'"
                            ),
                        },
                    },
                    {
                        "name": "format",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["jsonv2"],
                            "description": (
                                "Response format; this connector only "
                                "supports jsonv2"
                            ),
                        },
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Maximum candidate places to return (1-50)"
                            ),
                        },
                    },
                    {
                        "name": "addressdetails",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "enum": [0, 1],
                            "description": (
                                "1 to include the structured address "
                                "breakdown in each result"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Matching places with display_name, latitude "
                            "and longitude (strings) and, on request, a "
                            "structured address breakdown"
                        )
                    }
                },
            }
        },
        "/reverse": {
            "get": {
                "operationId": "reverse_geocode",
                "summary": (
                    "Resolve coordinates to the nearest address with "
                    "the Nominatim reverse geocoding service"
                ),
                "parameters": [
                    {
                        "name": "lat",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "number",
                            "description": "Latitude in decimal degrees",
                        },
                    },
                    {
                        "name": "lon",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "number",
                            "description": "Longitude in decimal degrees",
                        },
                    },
                    {
                        "name": "format",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["jsonv2"],
                            "description": (
                                "Response format; this connector only "
                                "supports jsonv2"
                            ),
                        },
                    },
                    {
                        "name": "zoom",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Detail level 0-18 (18 = building); "
                                "defaults to 18"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "The nearest address for the coordinates, "
                            "with display_name and address breakdown"
                        )
                    }
                },
            }
        },
    },
}

OVERPASS_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Overpass API", "version": "1.0.0"},
    "servers": [{"url": "https://overpass-api.de/api"}],
    "paths": {
        "/interpreter": {
            "get": {
                "operationId": "query_interpreter",
                "summary": (
                    "Run an Overpass QL query against OpenStreetMap "
                    "data and return matching elements as JSON"
                ),
                "parameters": [
                    {
                        "name": "data",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Overpass QL query text, e.g. an "
                                "[out:json] query selecting nodes/ways "
                                "by tag around a coordinate"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "JSON document with an elements list "
                            "(nodes carry lat/lon; ways and relations "
                            "carry a center when the query asks for it)"
                        )
                    }
                },
            }
        }
    },
}


class MapsLookupError(RuntimeError):
    """One explicit maps lookup failure; the message IS the reason."""


class OsmPolicyHttpClient:
    """``RestHttpClient`` wrapper enforcing the OSM usage policy.

    Two policy rules live here so no caller can forget them:

    - every request carries the connector's identifying
      ``User-Agent`` (any caller-supplied agent is replaced);
    - successive requests are spaced by at least
      ``min_interval_seconds`` (Nominatim's published maximum rate is
      1 request/second). The clock and sleeper are injectable so tests
      can prove the spacing without waiting.

    Requests are serialized through a lock: the OSM services are a
    shared public resource and this connector is a guest on them.
    """

    def __init__(
        self,
        inner: RestHttpClient,
        *,
        user_agent: str = OSM_USER_AGENT,
        min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not str(user_agent or "").strip():
            raise ValueError("OSM policy client needs an identifying User-Agent")
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
class OsmMapsAttachment:
    """Both OSM attachments; detach removes every tool at once."""

    nominatim: OpenApiRestAttachment
    overpass: OpenApiRestAttachment
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.nominatim.detach()
        self.overpass.detach()


def attach_osm_maps_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 20.0,
    min_request_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    user_agent: str = OSM_USER_AGENT,
) -> OsmMapsAttachment:
    """Attach the Nominatim + Overpass tools to a Body/Fabric.

    Both providers are read-only, so no write approvals exist. Every
    request — real urllib transport by default — passes through
    :class:`OsmPolicyHttpClient`, so the OSM usage policy (identifying
    User-Agent + rate limit) cannot be bypassed by a caller.
    """
    policy_client = OsmPolicyHttpClient(
        http_client or UrllibRestHttpClient(),
        user_agent=user_agent,
        min_interval_seconds=min_request_interval_seconds,
    )
    nominatim = attach_openapi_rest_tools(
        fabric=fabric,
        body=body,
        spec=copy.deepcopy(NOMINATIM_SPEC),
        provider_id=NOMINATIM_PROVIDER_ID,
        http_client=policy_client,
        timeout_seconds=timeout_seconds,
    )
    try:
        overpass = attach_openapi_rest_tools(
            fabric=fabric,
            body=body,
            spec=copy.deepcopy(OVERPASS_SPEC),
            provider_id=OVERPASS_PROVIDER_ID,
            http_client=policy_client,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        nominatim.detach()
        raise
    return OsmMapsAttachment(nominatim=nominatim, overpass=overpass)


def _execute_payload(
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
        raise MapsLookupError(f"maps {stage} failed: {reason}")
    try:
        return json.loads(outcome.body_result.output or "")
    except ValueError as exc:
        raise MapsLookupError(
            f"maps {stage} returned a malformed payload"
        ) from exc


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _validate_coordinates(latitude: Any, longitude: Any, stage: str) -> tuple[float, float]:
    lat = _number(latitude)
    lon = _number(longitude)
    if lat is None or not -90.0 <= lat <= 90.0:
        raise MapsLookupError(f"maps {stage} needs a latitude between -90 and 90")
    if lon is None or not -180.0 <= lon <= 180.0:
        raise MapsLookupError(f"maps {stage} needs a longitude between -180 and 180")
    return lat, lon


def _place_from_nominatim(entry: Mapping[str, Any], stage: str) -> dict[str, Any]:
    latitude = _number(entry.get("lat"))
    longitude = _number(entry.get("lon"))
    if latitude is None or longitude is None:
        raise MapsLookupError(f"maps {stage} returned a place without coordinates")
    address = entry.get("address")
    return {
        "display_name": str(entry.get("display_name") or ""),
        "latitude": latitude,
        "longitude": longitude,
        "category": str(entry.get("class") or ""),
        "type": str(entry.get("type") or ""),
        "address": dict(address) if isinstance(address, Mapping) else {},
    }


def geocode_address(
    runtime: ActionExecutionRuntime,
    query: str,
    *,
    limit: int = 1,
    event_id: str,
) -> list[dict[str, Any]]:
    """Resolve an address / place name to candidate places.

    Returns normalized places (display name, coordinates, category,
    structured address). Raises :class:`MapsLookupError` when Nominatim
    finds no match or the call fails — never invents coordinates.
    """
    text = str(query or "").strip()
    if not text:
        raise MapsLookupError("maps geocoding needs an address or place name")
    if not 1 <= int(limit) <= 50:
        raise MapsLookupError("maps geocoding limit must be between 1 and 50")
    payload = _execute_payload(
        runtime,
        GEOCODE_ACTION_ID,
        {
            "q": text,
            "format": "jsonv2",
            "limit": int(limit),
            "addressdetails": 1,
        },
        event_id=event_id,
        stage="geocoding",
    )
    if not isinstance(payload, list):
        raise MapsLookupError("maps geocoding returned a malformed payload")
    if not payload:
        raise MapsLookupError(
            f"place not found: {text!r} "
            "(Nominatim returned no match)"
        )
    places: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, Mapping):
            raise MapsLookupError("maps geocoding returned a malformed place")
        places.append(_place_from_nominatim(entry, "geocoding"))
    return places


def reverse_geocode(
    runtime: ActionExecutionRuntime,
    latitude: float,
    longitude: float,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Resolve coordinates to the nearest address Nominatim knows."""
    lat, lon = _validate_coordinates(latitude, longitude, "reverse geocoding")
    payload = _execute_payload(
        runtime,
        REVERSE_GEOCODE_ACTION_ID,
        {"lat": lat, "lon": lon, "format": "jsonv2"},
        event_id=event_id,
        stage="reverse geocoding",
    )
    if not isinstance(payload, Mapping):
        raise MapsLookupError("maps reverse geocoding returned a malformed payload")
    if payload.get("error"):
        raise MapsLookupError(
            f"maps reverse geocoding found no address near {lat}, {lon}: "
            f"{payload['error']}"
        )
    place = _place_from_nominatim(payload, "reverse geocoding")
    if not place["display_name"]:
        raise MapsLookupError(
            f"maps reverse geocoding found no address near {lat}, {lon}"
        )
    return place


def haversine_km(
    latitude1: float, longitude1: float, latitude2: float, longitude2: float
) -> float:
    """Great-circle distance in km between two coordinates."""
    radius_km = 6371.0088
    phi1 = math.radians(latitude1)
    phi2 = math.radians(latitude2)
    delta_phi = math.radians(latitude2 - latitude1)
    delta_lambda = math.radians(longitude2 - longitude1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def estimate_distance(
    runtime: ActionExecutionRuntime,
    origin_query: str,
    destination_query: str,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Geocode two addresses and estimate the distance between them.

    The distance is a straight-line (haversine) estimate between the
    geocoded coordinates — explicitly NOT a road distance.
    """
    origin = geocode_address(
        runtime, origin_query, limit=1, event_id=f"{event_id}:origin"
    )[0]
    destination = geocode_address(
        runtime, destination_query, limit=1, event_id=f"{event_id}:destination"
    )[0]
    distance = haversine_km(
        origin["latitude"],
        origin["longitude"],
        destination["latitude"],
        destination["longitude"],
    )
    return {
        "origin": origin,
        "destination": destination,
        "straight_line_distance_km": round(distance, 3),
        "method": (
            "straight-line (haversine) distance between geocoded "
            "coordinates; not a road distance or travel time"
        ),
        "source": SOURCE_LABEL,
        "retrieved_at": utc_now(),
    }


def _escape_ql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_overpass_nearby_query(
    *,
    latitude: float,
    longitude: float,
    tag_key: str,
    tag_value: str,
    radius_m: int = 1000,
    limit: int = 20,
) -> str:
    """Build the Overpass QL for places with one tag near a point.

    Nodes, ways and relations are all selected; ``out center`` gives
    ways/relations a usable coordinate. Tag key/value are validated /
    escaped so caller text cannot break out of the QL string.
    """
    lat, lon = _validate_coordinates(latitude, longitude, "nearby query")
    key = str(tag_key or "").strip()
    if not _TAG_KEY_RE.fullmatch(key):
        raise MapsLookupError(
            "maps nearby query needs a simple OSM tag key "
            "(letters, digits, '_', ':', '-', '.')"
        )
    value = str(tag_value or "").strip()
    if not value or len(value) > 256:
        raise MapsLookupError("maps nearby query needs a non-empty tag value")
    if not 1 <= int(radius_m) <= 50_000:
        raise MapsLookupError("maps nearby query radius must be 1-50000 metres")
    if not 1 <= int(limit) <= 100:
        raise MapsLookupError("maps nearby query limit must be between 1 and 100")
    selector = f'["{_escape_ql_string(key)}"="{_escape_ql_string(value)}"]'
    around = f"(around:{int(radius_m)},{lat:.6f},{lon:.6f})"
    return (
        "[out:json][timeout:25];"
        "("
        f"node{selector}{around};"
        f"way{selector}{around};"
        f"relation{selector}{around};"
        ");"
        f"out center {int(limit)};"
    )


def find_nearby_places(
    runtime: ActionExecutionRuntime,
    *,
    latitude: float,
    longitude: float,
    tag_key: str,
    tag_value: str,
    radius_m: int = 1000,
    limit: int = 20,
    event_id: str,
) -> dict[str, Any]:
    """Find OSM places with ``tag_key=tag_value`` near a point.

    Returns the query centre plus places sorted by straight-line
    distance from it. An empty result is a successful answer (the list
    is empty); transport/HTTP/Overpass errors raise
    :class:`MapsLookupError`.
    """
    lat, lon = _validate_coordinates(latitude, longitude, "nearby places")
    query = build_overpass_nearby_query(
        latitude=lat,
        longitude=lon,
        tag_key=tag_key,
        tag_value=tag_value,
        radius_m=radius_m,
        limit=limit,
    )
    payload = _execute_payload(
        runtime,
        OVERPASS_ACTION_ID,
        {"data": query},
        event_id=event_id,
        stage="nearby places",
    )
    if not isinstance(payload, Mapping):
        raise MapsLookupError("maps nearby places returned a malformed payload")
    remark = str(payload.get("remark") or "")
    if "error" in remark.lower():
        raise MapsLookupError(f"maps nearby places failed: Overpass reported: {remark}")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise MapsLookupError("maps nearby places returned a malformed payload")
    places: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        element_lat = _number(element.get("lat"))
        element_lon = _number(element.get("lon"))
        if element_lat is None or element_lon is None:
            center = element.get("center")
            if isinstance(center, Mapping):
                element_lat = _number(center.get("lat"))
                element_lon = _number(center.get("lon"))
        if element_lat is None or element_lon is None:
            continue
        tags = element.get("tags")
        tags = dict(tags) if isinstance(tags, Mapping) else {}
        places.append(
            {
                "name": str(tags.get("name") or ""),
                "latitude": element_lat,
                "longitude": element_lon,
                "distance_m": round(
                    haversine_km(lat, lon, element_lat, element_lon) * 1000
                ),
                "tags": {str(k): str(v) for k, v in tags.items()},
            }
        )
    places.sort(key=lambda place: place["distance_m"])
    return {
        "center": {"latitude": lat, "longitude": lon},
        "radius_m": int(radius_m),
        "tag": {"key": str(tag_key), "value": str(tag_value)},
        "places": places,
        "source": SOURCE_LABEL,
        "retrieved_at": utc_now(),
    }

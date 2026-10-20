from __future__ import annotations

"""Open-Meteo weather connector (R1): ZN's first real external connector.

Two key-free Open-Meteo services become ZN tools through the EXISTING
M-8 OpenAPI REST adapter (:mod:`zn_agent.core.openapi_rest_adapter`) —
this module adds no new mechanism, only trusted host configuration
(the two OpenAPI documents below), one attach helper, and one thin
chained lookup that walks the normal capability path
(``ActionExecutionRuntime`` + ``ActionRequest``) exactly the way a Work
does: geocode a place name to coordinates first, then fetch the
forecast for those coordinates.

The documents below are trusted host configuration, never
model-supplied. Both services are read-only GETs, so every registered
tool is ``read_only``; there are no write operations to approve.

Failure honesty: a place with no geocoding match, a non-2xx response,
a transport failure, or a malformed payload all raise
:class:`WeatherLookupError` with the concrete reason. Nothing here
invents coordinates or weather values.
"""

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .action_execution import ActionExecutionRuntime, ActionRequest
from .action_fabric import ActionFabricRegistry
from .body import NativeBody
from .models import utc_now
from .openapi_rest_adapter import (
    OpenApiRestAttachment,
    RestHttpClient,
    attach_openapi_rest_tools,
)

__all__ = [
    "FORECAST_ACTION_ID",
    "FORECAST_PROVIDER_ID",
    "FORECAST_SPEC",
    "GEOCODING_ACTION_ID",
    "GEOCODING_PROVIDER_ID",
    "GEOCODING_SPEC",
    "OpenMeteoAttachment",
    "WeatherLookupError",
    "attach_open_meteo_tools",
    "lookup_weather",
    "weather_condition_text",
]

GEOCODING_PROVIDER_ID = "open_meteo_geocoding"
FORECAST_PROVIDER_ID = "open_meteo_forecast"
GEOCODING_ACTION_ID = f"rest.{GEOCODING_PROVIDER_ID}.search_location"
FORECAST_ACTION_ID = f"rest.{FORECAST_PROVIDER_ID}.get_forecast"

SOURCE_LABEL = (
    "Open-Meteo (geocoding-api.open-meteo.com + api.open-meteo.com)"
)

_CURRENT_VARIABLES = (
    "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
)
_DAILY_VARIABLES = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_probability_max"
)

GEOCODING_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Open-Meteo Geocoding API", "version": "1.0.0"},
    "servers": [{"url": "https://geocoding-api.open-meteo.com/v1"}],
    "paths": {
        "/search": {
            "get": {
                "operationId": "search_location",
                "summary": (
                    "Resolve a place name to coordinates with the "
                    "Open-Meteo Geocoding API"
                ),
                "parameters": [
                    {
                        "name": "name",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Place name to resolve, e.g. Berlin"
                            ),
                        },
                    },
                    {
                        "name": "count",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "description": (
                                "Maximum candidate places to return"
                            ),
                        },
                    },
                    {
                        "name": "language",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Language code for returned place names, "
                                "e.g. en or zh"
                            ),
                        },
                    },
                    {
                        "name": "format",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["json"],
                            "description": (
                                "Response format; this connector only "
                                "supports json"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Matching places with name, country, "
                            "latitude, longitude and timezone"
                        )
                    }
                },
            }
        }
    },
}

FORECAST_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Open-Meteo Forecast API", "version": "1.0.0"},
    "servers": [{"url": "https://api.open-meteo.com/v1"}],
    "paths": {
        "/forecast": {
            "get": {
                "operationId": "get_forecast",
                "summary": (
                    "Fetch current weather and a daily forecast for "
                    "coordinates from the Open-Meteo Forecast API"
                ),
                "parameters": [
                    {
                        "name": "latitude",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "number",
                            "description": "Latitude in decimal degrees",
                        },
                    },
                    {
                        "name": "longitude",
                        "in": "query",
                        "required": True,
                        "schema": {
                            "type": "number",
                            "description": "Longitude in decimal degrees",
                        },
                    },
                    {
                        "name": "current",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Comma-separated current-weather variables, "
                                "e.g. temperature_2m,weather_code"
                            ),
                        },
                    },
                    {
                        "name": "daily",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Comma-separated daily variables, e.g. "
                                "temperature_2m_max,temperature_2m_min"
                            ),
                        },
                    },
                    {
                        "name": "forecast_days",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "description": "Number of forecast days (1-16)",
                        },
                    },
                    {
                        "name": "timezone",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "description": (
                                "Timezone name, or 'auto' to resolve from "
                                "the coordinates"
                            ),
                        },
                    },
                ],
                "responses": {
                    "200": {
                        "description": (
                            "Current weather and daily forecast for the "
                            "coordinates"
                        )
                    }
                },
            }
        }
    },
}

#: WMO weather codes as returned by Open-Meteo, spelled out so an answer
#: never has to guess what a bare number means.
_WMO_CONDITIONS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow fall",
    73: "moderate snow fall",
    75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def weather_condition_text(code: Any) -> str:
    """Spell out one WMO weather code; unknown codes stay explicit."""
    if isinstance(code, bool) or not isinstance(code, (int, float)):
        return "unknown condition"
    return _WMO_CONDITIONS.get(int(code), f"unknown condition (code {int(code)})")


class WeatherLookupError(RuntimeError):
    """One explicit weather lookup failure; the message IS the reason."""


@dataclass(slots=True)
class OpenMeteoAttachment:
    """Both Open-Meteo attachments; detach removes every tool at once."""

    geocoding: OpenApiRestAttachment
    forecast: OpenApiRestAttachment
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.geocoding.detach()
        self.forecast.detach()


def attach_open_meteo_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 15.0,
) -> OpenMeteoAttachment:
    """Attach the Open-Meteo geocoding + forecast tools to a Body/Fabric.

    Both providers are read-only, so no write approvals exist. The same
    ``http_client`` (real urllib transport by default) serves both.
    """
    geocoding = attach_openapi_rest_tools(
        fabric=fabric,
        body=body,
        spec=copy.deepcopy(GEOCODING_SPEC),
        provider_id=GEOCODING_PROVIDER_ID,
        http_client=http_client,
        timeout_seconds=timeout_seconds,
    )
    try:
        forecast = attach_openapi_rest_tools(
            fabric=fabric,
            body=body,
            spec=copy.deepcopy(FORECAST_SPEC),
            provider_id=FORECAST_PROVIDER_ID,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        geocoding.detach()
        raise
    return OpenMeteoAttachment(geocoding=geocoding, forecast=forecast)


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
        raise WeatherLookupError(f"weather {stage} failed: {reason}")
    try:
        payload = json.loads(outcome.body_result.output or "")
    except ValueError as exc:
        raise WeatherLookupError(
            f"weather {stage} returned a malformed payload"
        ) from exc
    if not isinstance(payload, dict):
        raise WeatherLookupError(
            f"weather {stage} returned a malformed payload"
        )
    return payload


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _daily_entries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    daily = payload.get("daily")
    if not isinstance(daily, Mapping):
        return []
    dates = daily.get("time") or []
    if not isinstance(dates, list):
        return []

    def column(name: str) -> list[Any]:
        values = daily.get(name)
        return values if isinstance(values, list) else []

    codes = column("weather_code")
    maxima = column("temperature_2m_max")
    minima = column("temperature_2m_min")
    rain = column("precipitation_probability_max")
    entries: list[dict[str, Any]] = []
    for index, date in enumerate(dates):
        code = codes[index] if index < len(codes) else None
        entries.append(
            {
                "date": str(date),
                "weather_code": code,
                "condition": weather_condition_text(code),
                "temperature_max_c": _number(
                    maxima[index] if index < len(maxima) else None
                ),
                "temperature_min_c": _number(
                    minima[index] if index < len(minima) else None
                ),
                "precipitation_probability_max_percent": _number(
                    rain[index] if index < len(rain) else None
                ),
            }
        )
    return entries


def lookup_weather(
    runtime: ActionExecutionRuntime,
    place_name: str,
    *,
    forecast_days: int = 3,
    language: str | None = None,
    event_id: str,
) -> dict[str, Any]:
    """Chain geocoding -> forecast through the normal capability path.

    Returns the structured answer (place, current conditions, daily
    forecast, source, retrieval time). Raises :class:`WeatherLookupError`
    for every failure: unknown place, failed call, malformed payload.
    """
    place_query = str(place_name or "").strip()
    if not place_query:
        raise WeatherLookupError("weather lookup needs a place name")
    if not 1 <= int(forecast_days) <= 16:
        raise WeatherLookupError("forecast_days must be between 1 and 16")
    retrieved_at = utc_now()

    geocoding_args: dict[str, Any] = {
        "name": place_query,
        "count": 1,
        "format": "json",
    }
    if language:
        geocoding_args["language"] = str(language)
    geo = _execute_json(
        runtime,
        GEOCODING_ACTION_ID,
        geocoding_args,
        event_id=f"{event_id}:geocoding",
        stage="geocoding",
    )
    results = geo.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherLookupError(
            f"place not found: {place_query!r} "
            "(Open-Meteo geocoding returned no match)"
        )
    place = results[0]
    if not isinstance(place, Mapping):
        raise WeatherLookupError("weather geocoding returned a malformed place")
    latitude = _number(place.get("latitude"))
    longitude = _number(place.get("longitude"))
    if latitude is None or longitude is None:
        raise WeatherLookupError(
            "weather geocoding returned a place without coordinates"
        )

    forecast = _execute_json(
        runtime,
        FORECAST_ACTION_ID,
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": _CURRENT_VARIABLES,
            "daily": _DAILY_VARIABLES,
            "forecast_days": int(forecast_days),
            "timezone": "auto",
        },
        event_id=f"{event_id}:forecast",
        stage="forecast",
    )
    current = forecast.get("current")
    if not isinstance(current, Mapping):
        raise WeatherLookupError(
            "weather forecast returned no current conditions"
        )
    current_code = current.get("weather_code")
    return {
        "place": {
            "name": str(place.get("name") or place_query),
            "country": str(place.get("country") or ""),
            "region": str(place.get("admin1") or ""),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": str(
                forecast.get("timezone") or place.get("timezone") or ""
            ),
        },
        "current": {
            "time": str(current.get("time") or ""),
            "temperature_c": _number(current.get("temperature_2m")),
            "humidity_percent": _number(current.get("relative_humidity_2m")),
            "wind_speed_kmh": _number(current.get("wind_speed_10m")),
            "weather_code": current_code,
            "condition": weather_condition_text(current_code),
        },
        "daily": _daily_entries(forecast),
        "source": SOURCE_LABEL,
        "retrieved_at": retrieved_at,
    }

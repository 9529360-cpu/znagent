from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.openapi_rest_adapter import (
    RestHttpResponse,
    parse_openapi_spec,
)
from zn_agent.core.open_meteo_connector import (
    FORECAST_ACTION_ID,
    FORECAST_SPEC,
    GEOCODING_ACTION_ID,
    GEOCODING_SPEC,
    WeatherLookupError,
    attach_open_meteo_tools,
    lookup_weather,
    weather_condition_text,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_BERLIN = {
    "name": "Berlin",
    "country": "Germany",
    "admin1": "Berlin",
    "latitude": 52.52437,
    "longitude": 13.41053,
    "timezone": "Europe/Berlin",
}

_FORECAST_PAYLOAD = {
    "latitude": 52.52,
    "longitude": 13.41,
    "timezone": "Europe/Berlin",
    "current": {
        "time": "2026-10-20T19:00",
        "temperature_2m": 18.5,
        "relative_humidity_2m": 55,
        "weather_code": 2,
        "wind_speed_10m": 12.3,
    },
    "daily": {
        "time": ["2026-10-20", "2026-10-21", "2026-10-22"],
        "weather_code": [2, 61, 3],
        "temperature_2m_max": [21.0, 17.5, 19.0],
        "temperature_2m_min": [11.0, 10.5, 12.0],
        "precipitation_probability_max": [10, 80, 20],
    },
}


class _FakeOpenMeteo:
    """Mock Open-Meteo services: records calls, answers fixed payloads."""

    def __init__(self):
        self.calls = []
        self.geocoding_status: int | None = None
        self.forecast_status: int | None = None
        self.transport_error: Exception | None = None

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append(
            {"method": method, "url": url, "params": dict(params)}
        )
        if self.transport_error is not None:
            raise self.transport_error
        if "geocoding-api" in url:
            if self.geocoding_status is not None:
                return RestHttpResponse(
                    self.geocoding_status, {}, b'{"error": "boom"}'
                )
            if params.get("name") == "Berlin":
                payload = {"results": [dict(_BERLIN)]}
            else:
                payload = {"generationtime_ms": 0.1}
            return RestHttpResponse(
                200, {}, json.dumps(payload).encode("utf-8")
            )
        if "api.open-meteo.com" in url:
            if self.forecast_status is not None:
                return RestHttpResponse(
                    self.forecast_status, {}, b'{"error": "boom"}'
                )
            return RestHttpResponse(
                200, {}, json.dumps(_FORECAST_PAYLOAD).encode("utf-8")
            )
        return RestHttpResponse(404, {}, b'{"error": "not found"}')


class OpenMeteoConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.client = _FakeOpenMeteo()
        self.attachment = attach_open_meteo_tools(
            self.fabric, self.body, http_client=self.client
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_specs_parse_into_read_only_operations(self):
        geocoding = parse_openapi_spec(GEOCODING_SPEC)
        forecast = parse_openapi_spec(FORECAST_SPEC)
        self.assertEqual(
            [op.operation_id for op in geocoding.operations],
            ["search_location"],
        )
        self.assertEqual(
            [op.operation_id for op in forecast.operations], ["get_forecast"]
        )
        self.assertTrue(all(op.is_read for op in geocoding.operations))
        self.assertTrue(all(op.is_read for op in forecast.operations))
        latitude = forecast.operations[0].input_schema["properties"]["latitude"]
        self.assertEqual(latitude["type"], "number")

    def test_attach_registers_read_only_tools(self):
        for action_id in (GEOCODING_ACTION_ID, FORECAST_ACTION_ID):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertIn("rest", descriptor.tags)

    def test_detach_removes_tools(self):
        self.attachment.detach()
        self.assertIsNone(self.fabric.descriptor(GEOCODING_ACTION_ID))
        self.assertIsNone(self.fabric.descriptor(FORECAST_ACTION_ID))

    def test_lookup_weather_chains_geocoding_then_forecast(self):
        answer = lookup_weather(
            self.runtime, "Berlin", forecast_days=3, event_id="evt-weather-1"
        )
        self.assertEqual(answer["place"]["name"], "Berlin")
        self.assertEqual(answer["place"]["country"], "Germany")
        self.assertEqual(answer["place"]["timezone"], "Europe/Berlin")
        self.assertEqual(answer["current"]["temperature_c"], 18.5)
        self.assertEqual(answer["current"]["humidity_percent"], 55.0)
        self.assertEqual(answer["current"]["condition"], "partly cloudy")
        self.assertEqual(len(answer["daily"]), 3)
        self.assertEqual(answer["daily"][1]["condition"], "slight rain")
        self.assertEqual(
            answer["daily"][1]["precipitation_probability_max_percent"], 80.0
        )
        self.assertIn("Open-Meteo", answer["source"])
        self.assertTrue(answer["retrieved_at"])
        # The forecast call must carry the geocoded coordinates.
        forecast_call = self.client.calls[-1]
        self.assertEqual(forecast_call["params"]["latitude"], 52.52437)
        self.assertEqual(forecast_call["params"]["longitude"], 13.41053)
        self.assertEqual(forecast_call["params"]["forecast_days"], 3)

    def test_lookup_weather_place_not_found_is_explicit(self):
        with self.assertRaises(WeatherLookupError) as caught:
            lookup_weather(
                self.runtime, "Nowhereville", event_id="evt-weather-2"
            )
        self.assertIn("place not found", str(caught.exception))
        self.assertIn("Nowhereville", str(caught.exception))

    def test_lookup_weather_http_error_is_explicit(self):
        self.client.forecast_status = 500
        with self.assertRaises(WeatherLookupError) as caught:
            lookup_weather(self.runtime, "Berlin", event_id="evt-weather-3")
        self.assertIn("forecast", str(caught.exception))
        self.assertIn("500", str(caught.exception))

    def test_lookup_weather_transport_failure_is_explicit(self):
        self.client.transport_error = ConnectionError("network down")
        with self.assertRaises(WeatherLookupError) as caught:
            lookup_weather(self.runtime, "Berlin", event_id="evt-weather-4")
        self.assertIn("geocoding", str(caught.exception))

    def test_lookup_weather_rejects_bad_inputs(self):
        with self.assertRaises(WeatherLookupError):
            lookup_weather(self.runtime, "  ", event_id="evt-weather-5")
        with self.assertRaises(WeatherLookupError):
            lookup_weather(
                self.runtime, "Berlin", forecast_days=99, event_id="evt-weather-6"
            )

    def test_weather_condition_text(self):
        self.assertEqual(weather_condition_text(0), "clear sky")
        self.assertEqual(weather_condition_text(95), "thunderstorm")
        self.assertIn("unknown", weather_condition_text(1234))
        self.assertIn("unknown", weather_condition_text(None))


class WeatherSkillEvalTests(unittest.TestCase):
    def test_repo_weather_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        weather = [
            item for item in report.tier1 if item.skill_name == "weather"
        ]
        self.assertEqual(len(weather), 1, report.to_dict())
        self.assertTrue(weather[0].passed, weather[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()

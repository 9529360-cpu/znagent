from __future__ import annotations

import json
import tempfile
import time
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
from zn_agent.core.osm_maps_connector import (
    GEOCODE_ACTION_ID,
    NOMINATIM_SPEC,
    OSM_USER_AGENT,
    OVERPASS_ACTION_ID,
    OVERPASS_SPEC,
    REVERSE_GEOCODE_ACTION_ID,
    MapsLookupError,
    OsmPolicyHttpClient,
    attach_osm_maps_tools,
    build_overpass_nearby_query,
    estimate_distance,
    find_nearby_places,
    geocode_address,
    haversine_km,
    reverse_geocode,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_BRANDENBURGER_TOR = {
    "place_id": 23590321,
    "lat": "52.516312",
    "lon": "13.377704",
    "display_name": (
        "Brandenburger Tor, Unter den Linden, Mitte, Berlin, "
        "10117, Deutschland"
    ),
    "class": "tourism",
    "type": "attraction",
    "address": {
        "road": "Unter den Linden",
        "city": "Berlin",
        "postcode": "10117",
        "country": "Deutschland",
    },
}

_BERLIN = {
    "place_id": 240109189,
    "lat": "52.520008",
    "lon": "13.404954",
    "display_name": "Berlin, Deutschland",
    "class": "place",
    "type": "city",
    "address": {"city": "Berlin", "country": "Deutschland"},
}

_MUNICH = {
    "place_id": 180210892,
    "lat": "48.137154",
    "lon": "11.576124",
    "display_name": "München, Bayern, Deutschland",
    "class": "place",
    "type": "city",
    "address": {"city": "München", "country": "Deutschland"},
}

_OVERPASS_CAFES = {
    "elements": [
        {
            "type": "node",
            "id": 3,
            "lat": 52.5170,
            "lon": 13.4050,
            "tags": {"name": "Cafe Far", "amenity": "cafe"},
        },
        {
            "type": "way",
            "id": 2,
            "center": {"lat": 52.5215, "lon": 13.4060},
            "tags": {"name": "Cafe Middle", "amenity": "cafe"},
        },
        {
            "type": "node",
            "id": 1,
            "lat": 52.5205,
            "lon": 13.4050,
            "tags": {"name": "Cafe Near", "amenity": "cafe"},
        },
    ]
}


class _FakeOsm:
    """Mock Nominatim + Overpass: records calls, answers fixed payloads."""

    def __init__(self):
        self.calls = []
        self.nominatim_status: int | None = None
        self.overpass_status: int | None = None
        self.transport_error: Exception | None = None

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "at": time.monotonic(),
            }
        )
        if self.transport_error is not None:
            raise self.transport_error
        if "nominatim" in url:
            if self.nominatim_status is not None:
                return RestHttpResponse(
                    self.nominatim_status, {}, b'{"error": "boom"}'
                )
            if "/search" in url:
                q = str(params.get("q") or "")
                if "Munich" in q or "München" in q:
                    payload = [dict(_MUNICH)]
                elif "Brandenburger" in q:
                    payload = [dict(_BRANDENBURGER_TOR)]
                elif "Berlin" in q:
                    payload = [dict(_BERLIN)]
                else:
                    payload = []
                return RestHttpResponse(
                    200, {}, json.dumps(payload).encode("utf-8")
                )
            if "/reverse" in url:
                lat = float(params.get("lat") or 0)
                if abs(lat - 52.516312) < 0.01:
                    payload = dict(_BRANDENBURGER_TOR)
                else:
                    payload = {"error": "Unable to geocode"}
                return RestHttpResponse(
                    200, {}, json.dumps(payload).encode("utf-8")
                )
        if "overpass" in url:
            if self.overpass_status is not None:
                return RestHttpResponse(
                    self.overpass_status, {}, b"overloaded"
                )
            data = str(params.get("data") or "")
            if "errorremark" in data:
                payload = {"remark": "runtime error: Query timed out"}
            elif '"cafe"' in data:
                payload = _OVERPASS_CAFES
            else:
                payload = {"elements": []}
            return RestHttpResponse(
                200, {}, json.dumps(payload).encode("utf-8")
            )
        return RestHttpResponse(404, {}, b'{"error": "not found"}')


class OsmPolicyHttpClientTests(unittest.TestCase):
    """OSM usage policy: identifying User-Agent + rate limiting."""

    def _inner(self):
        calls = []

        class _Inner:
            def request(self, method, url, *, params, headers, json_body, timeout_seconds):
                calls.append({"headers": dict(headers)})
                return RestHttpResponse(200, {}, b"{}")

        return _Inner(), calls

    def test_user_agent_is_stamped_and_overrides_caller(self):
        inner, calls = self._inner()
        client = OsmPolicyHttpClient(inner, min_interval_seconds=0)
        client.request(
            "GET",
            "https://nominatim.openstreetmap.org/search",
            params={},
            headers={"User-Agent": "curl/8.0"},
            json_body=None,
            timeout_seconds=5,
        )
        self.assertEqual(calls[0]["headers"]["User-Agent"], OSM_USER_AGENT)
        self.assertIn("ZN-Agent", OSM_USER_AGENT)

    def test_rate_limit_spaces_successive_requests(self):
        inner, _calls = self._inner()
        now = [100.0]
        sleeps = []

        def clock():
            return now[0]

        def sleeper(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        client = OsmPolicyHttpClient(
            inner, min_interval_seconds=1.0, clock=clock, sleeper=sleeper
        )

        def call():
            client.request(
                "GET",
                "https://nominatim.openstreetmap.org/search",
                params={},
                headers={},
                json_body=None,
                timeout_seconds=5,
            )

        call()  # first request: never waits
        self.assertEqual(sleeps, [])
        now[0] += 0.25
        call()  # 0.25s later: must wait the remaining 0.75s
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.75, places=6)
        now[0] += 5.0
        call()  # long gap: no waiting
        self.assertEqual(len(sleeps), 1)

    def test_policy_client_rejects_blank_user_agent(self):
        inner, _calls = self._inner()
        with self.assertRaises(ValueError):
            OsmPolicyHttpClient(inner, user_agent="  ")


class OsmMapsConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.client = _FakeOsm()
        self.attachment = attach_osm_maps_tools(
            self.fabric,
            self.body,
            http_client=self.client,
            min_request_interval_seconds=0,
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_specs_parse_into_read_only_operations(self):
        nominatim = parse_openapi_spec(NOMINATIM_SPEC)
        overpass = parse_openapi_spec(OVERPASS_SPEC)
        self.assertEqual(
            [op.operation_id for op in nominatim.operations],
            ["geocode_address", "reverse_geocode"],
        )
        self.assertEqual(
            [op.operation_id for op in overpass.operations],
            ["query_interpreter"],
        )
        self.assertTrue(all(op.is_read for op in nominatim.operations))
        self.assertTrue(all(op.is_read for op in overpass.operations))

    def test_attach_registers_read_only_tools(self):
        for action_id in (
            GEOCODE_ACTION_ID,
            REVERSE_GEOCODE_ACTION_ID,
            OVERPASS_ACTION_ID,
        ):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertIn("rest", descriptor.tags)

    def test_detach_removes_tools(self):
        self.attachment.detach()
        self.assertIsNone(self.fabric.descriptor(GEOCODE_ACTION_ID))
        self.assertIsNone(self.fabric.descriptor(REVERSE_GEOCODE_ACTION_ID))
        self.assertIsNone(self.fabric.descriptor(OVERPASS_ACTION_ID))

    def test_requests_carry_osm_user_agent(self):
        geocode_address(
            self.runtime, "Berlin", event_id="evt-maps-ua"
        )
        self.assertTrue(self.client.calls)
        for call in self.client.calls:
            self.assertEqual(
                call["headers"].get("User-Agent"), OSM_USER_AGENT
            )

    def test_attach_enforces_rate_limit_spacing(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel-rl.db")
        )
        client = _FakeOsm()
        attachment = attach_osm_maps_tools(
            fabric,
            body,
            http_client=client,
            min_request_interval_seconds=0.1,
        )
        try:
            runtime = ActionExecutionRuntime(fabric, body)
            geocode_address(runtime, "Berlin", event_id="evt-maps-rl-1")
            geocode_address(runtime, "Munich", event_id="evt-maps-rl-2")
        finally:
            attachment.detach()
            body.store.close()
        self.assertEqual(len(client.calls), 2)
        gap = client.calls[1]["at"] - client.calls[0]["at"]
        self.assertGreaterEqual(gap, 0.09)

    def test_geocode_address_normalizes_string_coordinates(self):
        places = geocode_address(
            self.runtime,
            "Brandenburger Tor, Berlin",
            event_id="evt-maps-1",
        )
        self.assertEqual(len(places), 1)
        place = places[0]
        self.assertIn("Brandenburger Tor", place["display_name"])
        self.assertEqual(place["latitude"], 52.516312)
        self.assertEqual(place["longitude"], 13.377704)
        self.assertEqual(place["address"]["city"], "Berlin")
        call = self.client.calls[-1]
        self.assertEqual(call["params"]["format"], "jsonv2")
        self.assertEqual(call["params"]["addressdetails"], 1)

    def test_geocode_address_not_found_is_explicit(self):
        with self.assertRaises(MapsLookupError) as caught:
            geocode_address(
                self.runtime, "Nowhereville", event_id="evt-maps-2"
            )
        self.assertIn("place not found", str(caught.exception))
        self.assertIn("Nowhereville", str(caught.exception))

    def test_geocode_address_rejects_blank_query(self):
        with self.assertRaises(MapsLookupError):
            geocode_address(self.runtime, "   ", event_id="evt-maps-3")

    def test_reverse_geocode_resolves_address(self):
        place = reverse_geocode(
            self.runtime, 52.516312, 13.377704, event_id="evt-maps-4"
        )
        self.assertIn("Brandenburger Tor", place["display_name"])
        self.assertEqual(place["latitude"], 52.516312)

    def test_reverse_geocode_no_address_is_explicit(self):
        with self.assertRaises(MapsLookupError) as caught:
            reverse_geocode(
                self.runtime, 0.0, 0.0, event_id="evt-maps-5"
            )
        self.assertIn("no address", str(caught.exception))

    def test_reverse_geocode_rejects_bad_coordinates(self):
        with self.assertRaises(MapsLookupError):
            reverse_geocode(
                self.runtime, 91.0, 0.0, event_id="evt-maps-6"
            )

    def test_find_nearby_places_sorts_by_distance_and_uses_centers(self):
        result = find_nearby_places(
            self.runtime,
            latitude=52.520008,
            longitude=13.404954,
            tag_key="amenity",
            tag_value="cafe",
            event_id="evt-maps-7",
        )
        names = [place["name"] for place in result["places"]]
        self.assertEqual(names, ["Cafe Near", "Cafe Middle", "Cafe Far"])
        distances = [place["distance_m"] for place in result["places"]]
        self.assertEqual(distances, sorted(distances))
        # The QL sent to Overpass must select all element kinds with
        # the tag around the centre and ask for centers.
        sent = self.client.calls[-1]["params"]["data"]
        self.assertIn('["amenity"="cafe"]', sent)
        self.assertIn("(around:1000,52.520008,13.404954)", sent)
        self.assertIn("out center 20;", sent)

    def test_find_nearby_places_empty_result_is_an_answer(self):
        result = find_nearby_places(
            self.runtime,
            latitude=52.520008,
            longitude=13.404954,
            tag_key="amenity",
            tag_value="pharmacy",
            event_id="evt-maps-8",
        )
        self.assertEqual(result["places"], [])

    def test_find_nearby_places_overpass_remark_error_is_explicit(self):
        with self.assertRaises(MapsLookupError) as caught:
            find_nearby_places(
                self.runtime,
                latitude=52.520008,
                longitude=13.404954,
                tag_key="amenity",
                tag_value="errorremark",
                event_id="evt-maps-9",
            )
        self.assertIn("Overpass reported", str(caught.exception))

    def test_http_429_is_explicit(self):
        self.client.nominatim_status = 429
        with self.assertRaises(MapsLookupError) as caught:
            geocode_address(self.runtime, "Berlin", event_id="evt-maps-10")
        self.assertIn("geocoding", str(caught.exception))
        self.assertIn("429", str(caught.exception))

    def test_transport_failure_is_explicit(self):
        self.client.transport_error = ConnectionError("network down")
        with self.assertRaises(MapsLookupError) as caught:
            geocode_address(self.runtime, "Berlin", event_id="evt-maps-11")
        self.assertIn("geocoding", str(caught.exception))

    def test_estimate_distance_between_two_addresses(self):
        result = estimate_distance(
            self.runtime, "Berlin", "Munich", event_id="evt-maps-12"
        )
        self.assertIn("Berlin", result["origin"]["display_name"])
        self.assertIn("München", result["destination"]["display_name"])
        # Berlin <-> Munich straight line is roughly 504 km.
        self.assertGreater(result["straight_line_distance_km"], 490)
        self.assertLess(result["straight_line_distance_km"], 520)
        self.assertIn("not a road distance", result["method"])
        self.assertIn("OpenStreetMap", result["source"])

    def test_haversine_km_known_pair(self):
        distance = haversine_km(52.520008, 13.404954, 48.137154, 11.576124)
        self.assertGreater(distance, 490)
        self.assertLess(distance, 520)
        self.assertEqual(haversine_km(52.52, 13.40, 52.52, 13.40), 0.0)

    def test_build_overpass_nearby_query_validation_and_escaping(self):
        query = build_overpass_nearby_query(
            latitude=52.52,
            longitude=13.40,
            tag_key="amenity",
            tag_value='ca"fe',
        )
        self.assertIn('["amenity"="ca\\"fe"]', query)
        with self.assertRaises(MapsLookupError):
            build_overpass_nearby_query(
                latitude=52.52,
                longitude=13.40,
                tag_key='amenity"="x',
                tag_value="cafe",
            )
        with self.assertRaises(MapsLookupError):
            build_overpass_nearby_query(
                latitude=52.52,
                longitude=13.40,
                tag_key="amenity",
                tag_value="cafe",
                radius_m=999_999,
            )


class MapsSkillEvalTests(unittest.TestCase):
    def test_repo_maps_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        maps = [
            item for item in report.tier1 if item.skill_name == "maps"
        ]
        self.assertEqual(len(maps), 1, report.to_dict())
        self.assertTrue(maps[0].passed, maps[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()

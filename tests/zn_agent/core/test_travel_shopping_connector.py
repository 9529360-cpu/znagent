from __future__ import annotations

import datetime
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
from zn_agent.core.travel_shopping_connector import (
    ARRIVALS_ACTION_ID,
    DEPARTURES_ACTION_ID,
    OPENPRICES_SPEC,
    OPENSKY_SPEC,
    OPENPRICES_USER_AGENT,
    OPENSKY_USER_AGENT,
    PRICES_ACTION_ID,
    GuestPolicyHttpClient,
    TravelShoppingError,
    attach_openprices_tools,
    attach_opensky_tools,
    compare_offers,
    lookup_flight_movements,
    lookup_product_prices,
    quote_age_status,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_NOW = datetime.datetime.now(tz=datetime.timezone.utc)

_DEPARTURES_PAYLOAD = [
    {
        "icao24": "4ba930",
        "firstSeen": 1792533792,
        "estDepartureAirport": "EGLL",
        "lastSeen": 1792545819,
        "estArrivalAirport": None,
        "callsign": "THY4RN  ",
        "departureAirportCandidatesCount": 120,
        "arrivalAirportCandidatesCount": 0,
    },
    {
        "icao24": "7380cb",
        "firstSeen": 1792533383,
        "estDepartureAirport": "EGLL",
        "lastSeen": 1792545797,
        "estArrivalAirport": "KJFK",
        "callsign": "ELY3",
        "departureAirportCandidatesCount": 98,
        "arrivalAirportCandidatesCount": 3,
    },
]

_ARRIVALS_PAYLOAD = [
    {
        "icao24": "abc123",
        "firstSeen": 1792530000,
        "estDepartureAirport": "KJFK",
        "lastSeen": 1792540000,
        "estArrivalAirport": "EDDF",
        "callsign": "DLH401",
        "departureAirportCandidatesCount": 5,
        "arrivalAirportCandidatesCount": 140,
    },
]

_PRICES_PAYLOAD = {
    "items": [
        {
            "id": 2207,
            "product_code": "3017620422003",
            "price": 3.21,
            "price_is_discounted": False,
            "currency": "EUR",
            "date": None,
            "product": {"product_name": "Nutella 400g"},
            "location": {"osm_name": "Carrefour Villeurbanne"},
            "proof": {
                "id": 9498,
                "currency": "EUR",
                "date": "2024-01-11",
            },
        },
        {
            # currency only resolvable from the proof record.
            "id": 3838,
            "product_code": "3017620422003",
            "price": 2.99,
            "price_is_discounted": True,
            "currency": None,
            "date": None,
            "product": {"product_name": "Nutella 400g"},
            "location": {"osm_name": "Carrefour Market"},
            "proof": {
                "id": 9048,
                "currency": "EUR",
                "date": "2024-01-29",
            },
        },
        {
            # currency unresolvable anywhere: reported, never ranked.
            "id": 4294,
            "product_code": "3017620422003",
            "price": 3.50,
            "price_is_discounted": False,
            "currency": None,
            "date": None,
            "product": {"product_name": "Nutella 400g"},
            "location": {"osm_name": "Mystery Store"},
            "proof": {"id": 9100, "currency": None, "date": None},
        },
    ],
    "total": 167,
}


class _FakeUpstream:
    """Mock upstream: records calls, answers fixed payloads per path."""

    def __init__(self):
        self.calls = []
        self.status: int | None = None
        self.transport_error: Exception | None = None
        self.malformed = False
        self.empty_flights = False
        # OpenSky quirk: 404 + `[]` body means "no flights in window".
        self.empty_404_flights = False
        # Adapter output-cap probe: enough movements to exceed the ~12k
        # char tool-output cap.
        self.huge_flights = False

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
            }
        )
        if self.transport_error is not None:
            raise self.transport_error
        if self.status is not None:
            return RestHttpResponse(self.status, {}, b'{"message": "boom"}')
        if self.malformed:
            return RestHttpResponse(200, {}, b"not-json{{{")
        if "opensky-network.org" in url:
            if self.empty_404_flights:
                return RestHttpResponse(404, {}, b"[]")
            if self.huge_flights:
                payload = [
                    dict(_DEPARTURES_PAYLOAD[0], callsign=f"HUGE{i:04d}")
                    for i in range(200)
                ]
            elif self.empty_flights:
                payload: object = []
            elif "/flights/arrival" in url:
                payload = _ARRIVALS_PAYLOAD
            else:
                payload = _DEPARTURES_PAYLOAD
        else:
            payload = _PRICES_PAYLOAD
        return RestHttpResponse(200, {}, json.dumps(payload).encode("utf-8"))


class _FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self):
        return self.now

    def sleeper(self, seconds: float):
        self.slept.append(seconds)
        self.now += seconds


class TravelShoppingConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.client = _FakeUpstream()
        self.sky = attach_opensky_tools(
            self.fabric,
            self.body,
            http_client=self.client,
            min_request_interval_seconds=0,
        )
        self.prices = attach_openprices_tools(
            self.fabric,
            self.body,
            http_client=self.client,
            min_request_interval_seconds=0,
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.sky.detach()
        self.prices.detach()
        self.body.store.close()
        self.tmp.cleanup()

    # ---- spec & attach ----

    def test_specs_parse_into_read_only_operations(self):
        sky = parse_openapi_spec(OPENSKY_SPEC)
        self.assertEqual(
            [op.operation_id for op in sky.operations],
            ["get_departures", "get_arrivals"],
        )
        self.assertTrue(all(op.is_read for op in sky.operations))
        prices = parse_openapi_spec(OPENPRICES_SPEC)
        self.assertEqual(
            [op.operation_id for op in prices.operations],
            ["query_prices"],
        )
        self.assertTrue(all(op.is_read for op in prices.operations))

    def test_attach_registers_read_only_tools(self):
        for action_id in (
            DEPARTURES_ACTION_ID,
            ARRIVALS_ACTION_ID,
            PRICES_ACTION_ID,
        ):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertIn("rest", descriptor.tags)

    def test_no_purchase_or_write_tools_exist(self):
        for action_id in (
            DEPARTURES_ACTION_ID,
            ARRIVALS_ACTION_ID,
            PRICES_ACTION_ID,
        ):
            descriptor = self.fabric.descriptor(action_id)
            self.assertNotIn("write", descriptor.effect_class)

    def test_detach_removes_tools(self):
        self.sky.detach()
        self.prices.detach()
        for action_id in (
            DEPARTURES_ACTION_ID,
            ARRIVALS_ACTION_ID,
            PRICES_ACTION_ID,
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    # ---- guest policy ----

    def test_guest_policy_injects_user_agent_and_spaces_requests(self):
        fake_clock = _FakeClock()
        inner = _FakeUpstream()
        policy = GuestPolicyHttpClient(
            inner,
            user_agent="Test-Agent/1.0",
            min_interval_seconds=5.0,
            clock=fake_clock.clock,
            sleeper=fake_clock.sleeper,
        )
        kwargs = {
            "params": {},
            "headers": {"User-Agent": "caller-agent"},
            "json_body": None,
            "timeout_seconds": 5.0,
        }
        policy.request("GET", "https://example.test/x", **kwargs)
        policy.request("GET", "https://example.test/x", **kwargs)
        self.assertEqual(len(fake_clock.slept), 1)
        self.assertAlmostEqual(fake_clock.slept[0], 5.0)
        for call in inner.calls:
            self.assertEqual(call["headers"]["User-Agent"], "Test-Agent/1.0")

    def test_guest_policy_rejects_empty_user_agent(self):
        with self.assertRaises(ValueError):
            GuestPolicyHttpClient(_FakeUpstream(), user_agent="  ",
                                 min_interval_seconds=1.0)

    def test_guest_policy_rejects_negative_interval(self):
        with self.assertRaises(ValueError):
            GuestPolicyHttpClient(_FakeUpstream(), user_agent="UA",
                                 min_interval_seconds=-1.0)

    def test_default_user_agents_are_identifying(self):
        self.assertTrue(OPENSKY_USER_AGENT.startswith("ZN-Agent-"))
        self.assertTrue(OPENPRICES_USER_AGENT.startswith("ZN-Agent-"))

    # ---- flights ----

    def test_lookup_departures(self):
        answer = lookup_flight_movements(
            self.runtime, "egll", direction="departure",
            hours_back=6, event_id="evt-r12-1",
        )
        self.assertEqual(answer["airport"], "EGLL")
        self.assertEqual(answer["direction"], "departure")
        self.assertEqual(answer["movement_count"], 2)
        first = answer["movements"][0]
        self.assertEqual(first["callsign"], "THY4RN")
        self.assertEqual(first["icao24"], "4ba930")
        self.assertEqual(first["departure_airport"], "EGLL")
        self.assertIsNone(first["arrival_airport"])
        self.assertTrue(first["first_seen"].endswith("Z"))
        self.assertTrue(first["last_seen"].endswith("Z"))
        self.assertIn("OpenSky", answer["source"])
        self.assertTrue(answer["retrieved_at"])
        self.assertIn("no ticket prices", answer["note"])
        call = self.client.calls[-1]
        self.assertIn("/flights/departure", call["url"])
        self.assertEqual(call["params"]["airport"], "EGLL")
        self.assertLess(call["params"]["begin"], call["params"]["end"])

    def test_lookup_arrivals(self):
        answer = lookup_flight_movements(
            self.runtime, "EDDF", direction="arrival",
            hours_back=2, event_id="evt-r12-2",
        )
        self.assertEqual(answer["direction"], "arrival")
        self.assertEqual(answer["movement_count"], 1)
        self.assertEqual(answer["movements"][0]["arrival_airport"], "EDDF")
        call = self.client.calls[-1]
        self.assertIn("/flights/arrival", call["url"])

    def test_empty_movements_are_a_real_answer(self):
        self.client.empty_flights = True
        answer = lookup_flight_movements(
            self.runtime, "EDDF", hours_back=1, event_id="evt-r12-3",
        )
        self.assertEqual(answer["movements"], [])
        self.assertEqual(answer["movement_count"], 0)

    def test_opensky_404_empty_list_means_no_movements(self):
        # Documented OpenSky quirk (verified live 2026-10-21): a window
        # with no observed flights answers 404 + `[]`, not 200.
        self.client.empty_404_flights = True
        answer = lookup_flight_movements(
            self.runtime, "EDDF", hours_back=1, event_id="evt-r12-3b",
        )
        self.assertEqual(answer["movements"], [])
        self.assertEqual(answer["movement_count"], 0)

    def test_guest_policy_404_normalization_only_for_empty_list(self):
        fake_clock = _FakeClock()

        def policy_for(inner, flag):
            return GuestPolicyHttpClient(
                inner,
                user_agent="Test-Agent/1.0",
                min_interval_seconds=0,
                clock=fake_clock.clock,
                sleeper=fake_clock.sleeper,
                empty_404_means_empty_list=flag,
            )

        kwargs = {
            "params": {},
            "headers": {},
            "json_body": None,
            "timeout_seconds": 5.0,
        }

        class _Fake404(_FakeUpstream):
            def __init__(self, body: bytes):
                super().__init__()
                self._body = body

            def request(self, method, url, **kw):
                return RestHttpResponse(404, {}, self._body)

        # 404 + `[]` -> normalized to 200 when the flag is on.
        resp = policy_for(_Fake404(b"[]"), True).request(
            "GET", "https://example.test/x", **kwargs
        )
        self.assertEqual(resp.status_code, 200)
        # flag off: 404 passes through untouched.
        resp = policy_for(_Fake404(b"[]"), False).request(
            "GET", "https://example.test/x", **kwargs
        )
        self.assertEqual(resp.status_code, 404)
        # 404 with any other body: never normalized, even with flag on.
        for body in (b'{"error": "nope"}', b"<html>no</html>", b"not-json"):
            resp = policy_for(_Fake404(body), True).request(
                "GET", "https://example.test/x", **kwargs
            )
            self.assertEqual(resp.status_code, 404, body)

    def test_truncated_response_is_an_explicit_error(self):
        # A window too busy to fit the adapter's ~12k char tool-output
        # cap must surface as "narrow the request", never as a silently
        # cut or half-parsed list.
        self.client.huge_flights = True
        with self.assertRaises(TravelShoppingError) as ctx:
            lookup_flight_movements(
                self.runtime, "KJFK", hours_back=6, event_id="evt-r12-16",
            )
        self.assertIn("narrow the request", str(ctx.exception))

    def test_invalid_airport_code_rejected(self):
        for bad in ("EDD", "EDDFX", "12DF", "", None):
            with self.assertRaises(TravelShoppingError, msg=repr(bad)):
                lookup_flight_movements(
                    self.runtime, bad, event_id="evt-r12-4",
                )

    def test_invalid_direction_rejected(self):
        with self.assertRaises(TravelShoppingError):
            lookup_flight_movements(
                self.runtime, "EDDF", direction="sideways",
                event_id="evt-r12-5",
            )

    def test_window_bounds_rejected(self):
        for bad in (0, -3, 169, float("nan")):
            with self.assertRaises(TravelShoppingError, msg=repr(bad)):
                lookup_flight_movements(
                    self.runtime, "EDDF", hours_back=bad,
                    event_id="evt-r12-6",
                )

    def test_flight_failures_are_honest(self):
        self.client.status = 429
        with self.assertRaises(TravelShoppingError):
            lookup_flight_movements(
                self.runtime, "EDDF", event_id="evt-r12-7",
            )
        self.client.status = None
        self.client.transport_error = ConnectionError("down")
        with self.assertRaises(TravelShoppingError):
            lookup_flight_movements(
                self.runtime, "EDDF", event_id="evt-r12-8",
            )
        self.client.transport_error = None
        self.client.malformed = True
        with self.assertRaises(TravelShoppingError):
            lookup_flight_movements(
                self.runtime, "EDDF", event_id="evt-r12-9",
            )

    # ---- product prices ----

    def test_lookup_product_prices(self):
        answer = lookup_product_prices(
            self.runtime, "3017620422003", event_id="evt-r12-10",
        )
        self.assertEqual(answer["product_code"], "3017620422003")
        self.assertEqual(answer["observation_count"], 3)
        self.assertEqual(answer["total_matching"], 167)
        first, second, third = answer["observations"]
        # currency straight from the price record
        self.assertEqual(first["price"], 3.21)
        self.assertEqual(first["currency"], "EUR")
        self.assertFalse(first["currency_unknown"])
        self.assertTrue(first["comparable"])
        self.assertEqual(first["observed_date"], "2024-01-11")
        self.assertEqual(first["store"], "Carrefour Villeurbanne")
        self.assertEqual(first["product_name"], "Nutella 400g")
        self.assertEqual(first["proof_id"], 9498)
        # currency resolved from the proof record
        self.assertEqual(second["currency"], "EUR")
        self.assertFalse(second["currency_unknown"])
        self.assertTrue(second["discounted"])
        self.assertEqual(second["observed_date"], "2024-01-29")
        # currency unresolvable anywhere: flagged, never comparable
        self.assertTrue(third["currency_unknown"])
        self.assertIsNone(third["currency"])
        self.assertFalse(third["comparable"])
        self.assertTrue(third["date_unknown"])
        self.assertIn("Open Prices", answer["source"])
        self.assertTrue(answer["retrieved_at"])
        call = self.client.calls[-1]
        self.assertIn("/api/v1/prices", call["url"])
        self.assertNotIn("/api/v1/prices/", call["url"])
        self.assertEqual(call["params"]["product_code"], "3017620422003")
        self.assertEqual(call["params"]["order_by"], "-date")

    def test_invalid_barcode_rejected(self):
        for bad in ("abc", "12", "3" * 21, "", None):
            with self.assertRaises(TravelShoppingError, msg=repr(bad)):
                lookup_product_prices(
                    self.runtime, bad, event_id="evt-r12-11",
                )

    def test_invalid_limit_rejected(self):
        for bad in (0, 101, -1, True):
            with self.assertRaises(TravelShoppingError, msg=repr(bad)):
                lookup_product_prices(
                    self.runtime, "3017620422003", limit=bad,
                    event_id="evt-r12-12",
                )

    def test_price_failures_are_honest(self):
        self.client.status = 500
        with self.assertRaises(TravelShoppingError):
            lookup_product_prices(
                self.runtime, "3017620422003", event_id="evt-r12-13",
            )
        self.client.status = None
        self.client.transport_error = TimeoutError("slow")
        with self.assertRaises(TravelShoppingError):
            lookup_product_prices(
                self.runtime, "3017620422003", event_id="evt-r12-14",
            )
        self.client.transport_error = None
        self.client.malformed = True
        with self.assertRaises(TravelShoppingError):
            lookup_product_prices(
                self.runtime, "3017620422003", event_id="evt-r12-15",
            )


def _offer(label, amount, currency, retrieved_at, **extra):
    offer = {
        "label": label,
        "amount": amount,
        "currency": currency,
        "retrieved_at": retrieved_at,
        "source": "test",
    }
    offer.update(extra)
    return offer


class CompareOffersTests(unittest.TestCase):
    def test_same_currency_ranks_cheapest_first(self):
        result = compare_offers(
            [
                _offer("A", 3.21, "EUR", _NOW.isoformat()),
                _offer("B", 2.99, "EUR", _NOW.isoformat()),
                _offer("C", 3.50, "eur", _NOW.isoformat()),
            ],
            now=_NOW,
        )
        self.assertEqual(result["currencies"], ["EUR"])
        self.assertEqual(
            [o["label"] for o in result["ranking"]], ["B", "A", "C"]
        )
        self.assertEqual(result["cheapest"]["label"], "B")
        self.assertIsNone(result["ranking_note"])
        self.assertEqual(
            [o["age_status"] for o in result["ranking"]],
            ["fresh", "fresh", "fresh"],
        )

    def test_mixed_currencies_are_not_ranked(self):
        result = compare_offers(
            [
                _offer("A", 3.21, "EUR", _NOW.isoformat()),
                _offer("B", 400, "JPY", _NOW.isoformat()),
            ],
            now=_NOW,
        )
        self.assertIsNone(result["ranking"])
        self.assertIsNone(result["cheapest"])
        self.assertEqual(result["currencies"], ["EUR", "JPY"])
        self.assertIn("not ranked", result["ranking_note"])
        self.assertIn("currency", result["ranking_note"])

    def test_expired_offers_listed_but_not_ranked(self):
        past = (_NOW - datetime.timedelta(hours=2)).isoformat()
        future = (_NOW + datetime.timedelta(hours=2)).isoformat()
        result = compare_offers(
            [
                _offer("old-cheap", 1.00, "EUR", _NOW.isoformat(),
                       expires_at=past),
                _offer("live", 2.00, "EUR", _NOW.isoformat(),
                       expires_at=future),
            ],
            now=_NOW,
        )
        by_label = {o["label"]: o for o in result["offers"]}
        self.assertTrue(by_label["old-cheap"]["expired"])
        self.assertFalse(by_label["live"]["expired"])
        self.assertEqual(
            [o["label"] for o in result["ranking"]], ["live"]
        )
        self.assertEqual(result["cheapest"]["label"], "live")

    def test_all_expired_means_no_ranking(self):
        past = (_NOW - datetime.timedelta(hours=1)).isoformat()
        result = compare_offers(
            [_offer("gone", 1.00, "EUR", _NOW.isoformat(),
                    expires_at=past)],
            now=_NOW,
        )
        self.assertIsNone(result["ranking"])
        self.assertIn("expired", result["ranking_note"])

    def test_age_status_bands(self):
        fresh = _NOW.isoformat()
        aging = (_NOW - datetime.timedelta(hours=30)).isoformat()
        stale = (_NOW - datetime.timedelta(days=10)).isoformat()
        result = compare_offers(
            [
                _offer("f", 1.0, "EUR", fresh),
                _offer("a", 2.0, "EUR", aging),
                _offer("s", 3.0, "EUR", stale),
            ],
            now=_NOW,
        )
        by_label = {o["label"]: o for o in result["offers"]}
        self.assertEqual(by_label["f"]["age_status"], "fresh")
        self.assertEqual(by_label["a"]["age_status"], "aging")
        self.assertEqual(by_label["s"]["age_status"], "stale")

    def test_broken_offers_rejected_loudly(self):
        with self.assertRaises(TravelShoppingError):
            compare_offers(
                [_offer("nocur", 1.0, "EURO", _NOW.isoformat())], now=_NOW
            )
        with self.assertRaises(TravelShoppingError):
            compare_offers(
                [_offer("nan", float("nan"), "EUR", _NOW.isoformat())],
                now=_NOW,
            )
        with self.assertRaises(TravelShoppingError):
            compare_offers(
                [_offer("neg", -1.0, "EUR", _NOW.isoformat())], now=_NOW
            )
        with self.assertRaises(TravelShoppingError):
            compare_offers([], now=_NOW)
        with self.assertRaises(TravelShoppingError):
            compare_offers(
                [_offer("badexp", 1.0, "EUR", _NOW.isoformat(),
                        expires_at="yesterday")],
                now=_NOW,
            )

    def test_unparseable_retrieved_at_is_stale_not_fresh(self):
        result = compare_offers(
            [_offer("mystery", 1.0, "EUR", "not-a-time")], now=_NOW
        )
        self.assertEqual(result["offers"][0]["age_status"], "stale")
        # missing timestamp entirely is also stale
        offer = _offer("mystery2", 1.0, "EUR", None)
        del offer["retrieved_at"]
        result = compare_offers([offer], now=_NOW)
        self.assertEqual(result["offers"][0]["age_status"], "stale")


class QuoteAgeStatusTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(quote_age_status(_NOW.isoformat(), now=_NOW), "fresh")
        hour_ago = _NOW - datetime.timedelta(hours=23)
        self.assertEqual(quote_age_status(hour_ago.isoformat(), now=_NOW), "fresh")
        two_days = _NOW - datetime.timedelta(days=2)
        self.assertEqual(quote_age_status(two_days.isoformat(), now=_NOW), "aging")
        old = _NOW - datetime.timedelta(days=30)
        self.assertEqual(quote_age_status(old.isoformat(), now=_NOW), "stale")

    def test_unparseable_or_missing_is_stale(self):
        self.assertEqual(quote_age_status("garbage", now=_NOW), "stale")
        self.assertEqual(quote_age_status(None, now=_NOW), "stale")
        self.assertEqual(quote_age_status({}, now=_NOW), "stale")

    def test_mapping_input(self):
        payload = {"retrieved_at": _NOW.isoformat()}
        self.assertEqual(quote_age_status(payload, now=_NOW), "fresh")


class TravelShoppingSkillEvalTests(unittest.TestCase):
    def test_repo_travel_shopping_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        travel = [
            item for item in report.tier1 if item.skill_name == "travel-shopping"
        ]
        self.assertEqual(len(travel), 1, report.to_dict())
        self.assertTrue(travel[0].passed, travel[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()

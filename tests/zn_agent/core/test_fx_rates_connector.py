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
from zn_agent.core.fx_rates_connector import (
    FRANKFURTER_SPEC,
    FX_HISTORICAL_ACTION_ID,
    FX_RATES_ACTION_ID,
    FX_USER_AGENT,
    FrankfurterPolicyHttpClient,
    FxRatesError,
    attach_fx_rates_tools,
    convert_currency,
    lookup_fx_rates,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

_TODAY = datetime.date.today().isoformat()

_LATEST_PAYLOAD = {
    "amount": 1.0,
    "base": "USD",
    "date": _TODAY,
    "rates": {"EUR": 0.89166, "CNY": 6.678, "JPY": 158.13},
}

_STALE_PAYLOAD = {
    "amount": 1.0,
    "base": "USD",
    "date": "2024-06-07",
    "rates": {"EUR": 0.92566},
}


class _FakeFrankfurter:
    """Mock Frankfurter: records calls, answers fixed payloads."""

    def __init__(self):
        self.calls = []
        self.latest_payload: dict | None = dict(_LATEST_PAYLOAD)
        self.status: int | None = None
        self.transport_error: Exception | None = None
        self.malformed = False

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
        if "/latest" in url:
            payload = self.latest_payload
        else:
            # Historical: a weekend request silently serves Friday's rates,
            # exactly like the real API.
            date = url.rstrip("/").rsplit("/", 1)[-1]
            if date == "2024-06-01":
                payload = {
                    "amount": 1.0,
                    "base": "USD",
                    "date": "2024-05-31",
                    "rates": {"EUR": 0.91852},
                }
            else:
                payload = {
                    "amount": 1.0,
                    "base": "USD",
                    "date": date,
                    "rates": {"EUR": 0.9},
                }
            if params.get("base") == "XXX":
                return RestHttpResponse(
                    404, {}, b'{"message": "not found"}'
                )
        if params.get("base") == "XXX" and "/latest" in url:
            return RestHttpResponse(404, {}, b'{"message": "not found"}')
        return RestHttpResponse(
            200, {}, json.dumps(payload).encode("utf-8")
        )


class FxRatesConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.client = _FakeFrankfurter()
        self.attachment = attach_fx_rates_tools(
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

    def test_spec_parses_into_read_only_operations(self):
        parsed = parse_openapi_spec(FRANKFURTER_SPEC)
        self.assertEqual(
            [op.operation_id for op in parsed.operations],
            ["get_latest_rates", "get_historical_rates"],
        )
        self.assertTrue(all(op.is_read for op in parsed.operations))
        historical = parsed.operations[1]
        self.assertEqual(historical.path_params, ("date",))
        self.assertIn("base", historical.query_params)
        self.assertTrue(
            historical.input_schema["required"]
            and "base" in historical.input_schema["required"]
        )

    def test_attach_registers_read_only_tools(self):
        for action_id in (FX_RATES_ACTION_ID, FX_HISTORICAL_ACTION_ID):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertIn("rest", descriptor.tags)

    def test_detach_removes_tools(self):
        self.attachment.detach()
        self.assertIsNone(self.fabric.descriptor(FX_RATES_ACTION_ID))
        self.assertIsNone(self.fabric.descriptor(FX_HISTORICAL_ACTION_ID))

    def test_lookup_latest_rates(self):
        answer = lookup_fx_rates(
            self.runtime, "usd", symbols=["EUR", "CNY"], event_id="evt-fx-1"
        )
        self.assertEqual(answer["base_currency"], "USD")
        self.assertAlmostEqual(answer["rates"]["EUR"], 0.89166)
        self.assertAlmostEqual(answer["rates"]["CNY"], 6.678)
        self.assertEqual(answer["rate_date"], _TODAY)
        self.assertFalse(answer["rate_is_not_current_day"])
        self.assertFalse(answer["date_was_adjusted"])
        self.assertEqual(answer["missing_symbols"], [])
        self.assertIn("Frankfurter", answer["source"])
        self.assertIn("ECB", answer["source"])
        self.assertTrue(answer["retrieved_at"])
        # symbols ride as one comma-joined query param.
        call = self.client.calls[-1]
        self.assertEqual(call["params"]["base"], "USD")
        self.assertEqual(call["params"]["symbols"], "EUR,CNY")

    def test_lookup_stale_latest_flags_it_explicitly(self):
        self.client.latest_payload = dict(_STALE_PAYLOAD)
        answer = lookup_fx_rates(
            self.runtime, "USD", symbols=["EUR"], event_id="evt-fx-2"
        )
        self.assertEqual(answer["rate_date"], "2024-06-07")
        self.assertTrue(answer["rate_is_not_current_day"])

    def test_lookup_historical_reports_adjusted_date(self):
        answer = lookup_fx_rates(
            self.runtime,
            "USD",
            symbols=["EUR"],
            date="2024-06-01",
            event_id="evt-fx-3",
        )
        self.assertEqual(answer["requested_date"], "2024-06-01")
        self.assertEqual(answer["rate_date"], "2024-05-31")
        self.assertTrue(answer["date_was_adjusted"])

    def test_lookup_missing_symbols_are_named(self):
        answer = lookup_fx_rates(
            self.runtime,
            "USD",
            symbols=["EUR", "XXX"],
            event_id="evt-fx-4",
        )
        self.assertEqual(answer["missing_symbols"], ["XXX"])
        self.assertIn("EUR", answer["rates"])

    def test_lookup_rejects_bad_inputs(self):
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(self.runtime, "US", event_id="evt-fx-5")
        self.assertIn("invalid base currency code", str(caught.exception))
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(
                self.runtime, "USD", symbols=["EURO"], event_id="evt-fx-6"
            )
        self.assertIn("invalid target currency code", str(caught.exception))
        with self.assertRaises(FxRatesError):
            lookup_fx_rates(
                self.runtime, "USD", date="2024-13-99", event_id="evt-fx-7"
            )
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(
                self.runtime, "USD", date="2999-01-01", event_id="evt-fx-8"
            )
        self.assertIn("past", str(caught.exception))

    def test_lookup_unknown_currency_surfaces_api_404(self):
        # Shaped-but-unknown codes reach the API; its 404 becomes explicit.
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(self.runtime, "XXX", event_id="evt-fx-9")
        self.assertIn("latest rates", str(caught.exception))
        self.assertIn("404", str(caught.exception))

    def test_lookup_http_error_is_explicit(self):
        self.client.status = 500
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(self.runtime, "USD", event_id="evt-fx-10")
        self.assertIn("latest rates", str(caught.exception))
        self.assertIn("500", str(caught.exception))

    def test_lookup_transport_failure_is_explicit(self):
        self.client.transport_error = ConnectionError("network down")
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(self.runtime, "USD", event_id="evt-fx-11")
        self.assertIn("latest rates", str(caught.exception))

    def test_lookup_malformed_payload_is_explicit(self):
        self.client.malformed = True
        with self.assertRaises(FxRatesError) as caught:
            lookup_fx_rates(self.runtime, "USD", event_id="evt-fx-12")
        self.assertIn("malformed payload", str(caught.exception))

    def test_convert_currency(self):
        result = convert_currency(
            self.runtime, 100, "USD", "EUR", event_id="evt-fx-20"
        )
        self.assertEqual(result["from_currency"], "USD")
        self.assertEqual(result["to_currency"], "EUR")
        self.assertAlmostEqual(result["rate"], 0.89166)
        self.assertAlmostEqual(result["converted_amount"], 89.166)
        self.assertEqual(result["rate_date"], _TODAY)
        self.assertIn("not investment advice", result["note"])

    def test_convert_same_currency_is_local_and_explicit(self):
        result = convert_currency(
            self.runtime, 100, "USD", "USD", event_id="evt-fx-21"
        )
        self.assertTrue(result["local_only"])
        self.assertEqual(result["converted_amount"], 100.0)
        self.assertEqual(result["rate"], 1.0)
        self.assertEqual(self.client.calls, [])

    def test_convert_rejects_bad_amounts(self):
        for bad in (True, float("nan"), float("inf"), -5):
            with self.assertRaises(FxRatesError) as caught:
                convert_currency(
                    self.runtime, bad, "USD", "EUR", event_id="evt-fx-22"
                )
            self.assertIn("invalid amount", str(caught.exception))

    def test_convert_missing_target_rate_is_explicit(self):
        with self.assertRaises(FxRatesError) as caught:
            convert_currency(
                self.runtime, 100, "USD", "XXX", event_id="evt-fx-23"
            )
        self.assertIn("no XXX rate", str(caught.exception))

    def test_every_request_carries_identifying_user_agent(self):
        lookup_fx_rates(self.runtime, "USD", event_id="evt-fx-30")
        for call in self.client.calls:
            self.assertEqual(call["headers"].get("User-Agent"), FX_USER_AGENT)

    def test_policy_client_rejects_bad_configuration(self):
        with self.assertRaises(ValueError):
            FrankfurterPolicyHttpClient(self.client, user_agent="  ")
        with self.assertRaises(ValueError):
            FrankfurterPolicyHttpClient(
                self.client, min_interval_seconds=-1
            )

    def test_policy_client_spaces_successive_requests(self):
        now = [1000.0]
        slept: list[float] = []
        policy = FrankfurterPolicyHttpClient(
            self.client,
            min_interval_seconds=1.0,
            clock=lambda: now[0],
            sleeper=slept.append,
        )
        kwargs = {
            "params": {},
            "headers": {},
            "json_body": None,
            "timeout_seconds": 5.0,
        }
        policy.request("GET", "https://x/latest", **kwargs)
        now[0] += 0.2
        policy.request("GET", "https://x/latest", **kwargs)
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 0.8)
        now[0] += 1.5
        policy.request("GET", "https://x/latest", **kwargs)
        self.assertEqual(len(slept), 1)


class CurrencySkillEvalTests(unittest.TestCase):
    def test_repo_currency_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        currency = [
            item for item in report.tier1 if item.skill_name == "currency"
        ]
        self.assertEqual(len(currency), 1, report.to_dict())
        self.assertTrue(currency[0].passed, currency[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()

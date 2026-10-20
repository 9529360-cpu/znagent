"""Tests for ``zn model check``: probing, secret scrubbing, CLI exit codes.

All provider interaction goes through a fake worker factory: no real
network request is ever made.
"""

from __future__ import annotations

import io
import json
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core import zn_cli
from zn_agent.core.model_check import (
    PROBE_MAX_TOKENS,
    ModelCheckReport,
    RouteCheckResult,
    check_model_routes,
    format_no_config_hint,
    scrub_secrets,
)
from zn_agent.core.models import ModelRoute

_SECRET = "sk-test-fake-secret-abcdef123456"


class _FakeResult:
    def __init__(self, success: bool, error: str | None = None) -> None:
        self.success = success
        self.error = error


class _FakeWorker:
    """Scripted stand-in for CognitiveResourceWorker."""

    def __init__(self, behavior: str) -> None:
        self.behavior = behavior
        self.seen_goals: list = []

    def run(self, goal, kernel_context):
        self.seen_goals.append(goal)
        if self.behavior == "ok":
            return _FakeResult(True)
        if self.behavior == "fail":
            return _FakeResult(
                False, error=f"401 Unauthorized: invalid api key {_SECRET}"
            )
        if self.behavior == "raise":
            raise ConnectionError(f"dial tcp: connection refused (key {_SECRET})")
        time.sleep(60.0)  # "hang": the probe timeout must abandon this
        return _FakeResult(True)


class _FakeFactory:
    def __init__(self, behaviors: dict[str, str]) -> None:
        self.behaviors = behaviors
        self.created_routes: dict[str, ModelRoute] = {}

    def create(self, route: ModelRoute):
        if self.behaviors.get(route.route_id) == "construct-fail":
            raise RuntimeError(f"missing api_key for route (secret was {_SECRET})")
        self.created_routes[route.route_id] = route
        return _FakeWorker(self.behaviors.get(route.route_id, "ok"))


def _route(
    route_id: str,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    with_secret: bool = True,
) -> ModelRoute:
    metadata: dict = {"base_url": "https://api.example.com/v1"}
    if with_secret:
        metadata["api_key"] = _SECRET
    return ModelRoute(
        route_id=route_id, provider=provider, model=model, metadata=metadata
    )


def _plan(routes, *, available: bool = True, error=None):
    return SimpleNamespace(
        available=available, error=error, routes=list(routes), worker_factory=None
    )


def _ok_report() -> ModelCheckReport:
    return ModelCheckReport(
        configured=True,
        config_error=None,
        results=(
            RouteCheckResult(
                route_id="default",
                provider="openai",
                model="gpt-4o-mini",
                reachable=True,
                latency_seconds=0.42,
                detail="ok",
            ),
        ),
    )


def _down_report() -> ModelCheckReport:
    return ModelCheckReport(
        configured=True,
        config_error=None,
        results=(
            RouteCheckResult(
                route_id="default",
                provider="openai",
                model="gpt-4o-mini",
                reachable=False,
                latency_seconds=1.5,
                detail="ConnectionError: dial tcp: connection refused",
            ),
        ),
    )


class ModelCheckProbeTests(unittest.TestCase):
    def test_reachable_route_reports_latency(self):
        report = check_model_routes(
            plan=_plan([_route("default")]),
            worker_factory=_FakeFactory({"default": "ok"}),
        )
        self.assertTrue(report.configured)
        self.assertEqual(len(report.results), 1)
        result = report.results[0]
        self.assertTrue(result.reachable)
        self.assertEqual(result.detail, "ok")
        self.assertIsNotNone(result.latency_seconds)
        self.assertGreaterEqual(result.latency_seconds, 0.0)

    def test_unreachable_route_reports_scrubbed_reason(self):
        report = check_model_routes(
            plan=_plan([_route("default")]),
            worker_factory=_FakeFactory({"default": "fail"}),
        )
        result = report.results[0]
        self.assertFalse(result.reachable)
        self.assertNotIn(_SECRET, result.detail)
        self.assertIn("401", result.detail)

    def test_worker_exception_is_unreachable_and_scrubbed(self):
        report = check_model_routes(
            plan=_plan([_route("default")]),
            worker_factory=_FakeFactory({"default": "raise"}),
        )
        result = report.results[0]
        self.assertFalse(result.reachable)
        self.assertNotIn(_SECRET, result.detail)
        self.assertIn("ConnectionError", result.detail)

    def test_hang_is_bounded_by_probe_timeout(self):
        started = time.monotonic()
        report = check_model_routes(
            plan=_plan([_route("default")]),
            worker_factory=_FakeFactory({"default": "hang"}),
            probe_timeout_seconds=0.3,
        )
        elapsed = time.monotonic() - started
        result = report.results[0]
        self.assertFalse(result.reachable)
        self.assertIn("timed out", result.detail)
        self.assertLess(elapsed, 10.0)

    def test_construct_failure_is_unreachable(self):
        report = check_model_routes(
            plan=_plan([_route("default")]),
            worker_factory=_FakeFactory({"default": "construct-fail"}),
        )
        result = report.results[0]
        self.assertFalse(result.reachable)
        self.assertNotIn(_SECRET, result.detail)
        self.assertIsNone(result.latency_seconds)

    def test_no_routes_configured(self):
        report = check_model_routes(
            plan=_plan([], available=False),
            worker_factory=_FakeFactory({}),
        )
        self.assertFalse(report.configured)
        self.assertFalse(report.any_reachable)
        self.assertEqual(report.results, ())

    def test_config_error_is_reported(self):
        report = check_model_routes(
            plan=_plan([], available=False, error="ValueError: bad routes"),
            worker_factory=_FakeFactory({}),
        )
        self.assertFalse(report.configured)
        self.assertIn("bad routes", report.config_error or "")

    def test_probe_forces_minimal_max_tokens(self):
        factory = _FakeFactory({"default": "ok", "backup": "ok"})
        check_model_routes(
            plan=_plan([_route("default"), _route("backup")]),
            worker_factory=factory,
        )
        for route_id, created in factory.created_routes.items():
            self.assertEqual(
                created.metadata.get("max_tokens"),
                PROBE_MAX_TOKENS,
                route_id,
            )

    def test_probe_does_not_mutate_plan_routes(self):
        original = _route("default")
        original.metadata["max_tokens"] = 64
        check_model_routes(
            plan=_plan([original]),
            worker_factory=_FakeFactory({"default": "ok"}),
        )
        self.assertEqual(original.metadata["max_tokens"], 64)

    def test_none_provider_routes_are_skipped(self):
        plan = _plan([_route("ghost", provider="none", with_secret=False)])
        report = check_model_routes(
            plan=plan, worker_factory=_FakeFactory({})
        )
        self.assertTrue(report.configured)
        self.assertEqual(report.results, ())

    def test_scrub_secrets_redacts_and_collapses(self):
        text = f"first line\nsecond {_SECRET} end"
        scrubbed = scrub_secrets(text, [_SECRET, "short"])
        self.assertNotIn(_SECRET, scrubbed)
        self.assertNotIn("\n", scrubbed)
        self.assertIn("***", scrubbed)

    def test_invalid_timeout_rejected(self):
        with self.assertRaises(ValueError):
            check_model_routes(
                plan=_plan([_route("default")]),
                worker_factory=_FakeFactory({}),
                probe_timeout_seconds=0,
            )


class ModelCheckCliTests(unittest.TestCase):
    def _run(self, argv, report):
        buf = io.StringIO()
        with mock.patch.object(
            zn_cli, "check_model_routes", return_value=report
        ), redirect_stdout(buf):
            code = zn_cli.run(argv)
        return code, buf.getvalue()

    def test_cli_exit_zero_when_reachable(self):
        code, out = self._run(["model", "check"], _ok_report())
        self.assertEqual(code, 0)
        self.assertIn("reachable", out)
        self.assertIn("default", out)

    def test_cli_exit_one_when_none_reachable(self):
        code, out = self._run(["model", "check"], _down_report())
        self.assertEqual(code, 1)
        self.assertIn("unreachable", out)

    def test_cli_exit_three_and_hint_when_unconfigured(self):
        report = ModelCheckReport(
            configured=False, config_error=None, results=()
        )
        code, out = self._run(["model", "check"], report)
        self.assertEqual(code, 3)
        self.assertIn("model:", out)
        self.assertIn("zn model check", out)

    def test_cli_json_output_has_no_secrets(self):
        buf = io.StringIO()
        with mock.patch.object(
            zn_cli, "check_model_routes", return_value=_down_report()
        ), redirect_stdout(buf):
            code = zn_cli.run(["model", "check", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["reachable_count"], 0)
        self.assertEqual(payload["route_count"], 1)
        self.assertTrue(payload["configured"])
        route = payload["routes"][0]
        self.assertFalse(route["reachable"])
        self.assertNotIn(_SECRET, buf.getvalue())

    def test_cli_rejects_non_positive_probe_timeout(self):
        with self.assertRaises(SystemExit) as ctx:
            zn_cli.run(["model", "check", "--probe-timeout", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_config_hint_is_actionable(self):
        hint = format_no_config_hint()
        self.assertIn("model:", hint)
        self.assertIn("zn model check", hint)


if __name__ == "__main__":
    unittest.main()

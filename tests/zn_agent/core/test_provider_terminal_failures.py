from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_failure import classify_cognitive_failure
from zn_agent.core.health_observation import ResidentHealthJournal
from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.router import ModelRouter
from zn_agent.core.store import KernelStore


class _ProviderError(RuntimeError):
    """Test double for a provider SDK error carrying an HTTP status."""

    def __init__(self, *, status: int | None = None, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status


def _error(*, status=None, message=""):
    return _ProviderError(status=status, message=message)


class TerminalClassificationTests(unittest.TestCase):
    def test_unauthorized_is_terminal(self):
        disposition = classify_cognitive_failure(_error(status=401, message="unauthorized"))
        self.assertIsNotNone(disposition)
        assert disposition is not None
        self.assertTrue(disposition.affects_route_health)
        self.assertTrue(disposition.terminal)
        self.assertEqual(disposition.failure_class, "authentication_or_authorization")

    def test_insufficient_quota_is_terminal(self):
        disposition = classify_cognitive_failure(
            _error(status=403, message="insufficient_quota")
        )
        self.assertIsNotNone(disposition)
        assert disposition is not None
        self.assertTrue(disposition.terminal)
        self.assertEqual(disposition.failure_class, "billing_or_quota")

    def test_rate_limit_is_transient(self):
        disposition = classify_cognitive_failure(_error(status=429, message="slow down"))
        self.assertIsNotNone(disposition)
        assert disposition is not None
        self.assertTrue(disposition.affects_route_health)
        self.assertFalse(disposition.terminal)

    def test_server_error_is_transient(self):
        disposition = classify_cognitive_failure(_error(status=500, message="boom"))
        self.assertIsNotNone(disposition)
        assert disposition is not None
        self.assertFalse(disposition.terminal)

    def test_bad_request_stays_request_scoped(self):
        disposition = classify_cognitive_failure(_error(status=400, message="bad"))
        self.assertIsNotNone(disposition)
        assert disposition is not None
        self.assertFalse(disposition.affects_route_health)
        self.assertFalse(disposition.terminal)


class TerminalJournalTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(tmp / "kernel.db")
        # Close the store before the TemporaryDirectory cleanup runs:
        # KernelStore holds an open sqlite connection, and on Windows the
        # temp dir cannot be removed while kernel.db is still open.
        self.addCleanup(self.store.close)
        self.journal = ResidentHealthJournal(self.store)

    def test_terminal_failure_marks_organ(self):
        snapshot = self.journal.record_failure(
            "route-a", _error(status=401), failure_class="authentication_or_authorization",
            terminal=True,
        )
        self.assertEqual(snapshot["terminal_failure_class"], "authentication_or_authorization")
        self.assertFalse(snapshot["healthy"])

    def test_success_clears_terminal_mark(self):
        self.journal.record_failure(
            "route-a", _error(status=401), failure_class="authentication_or_authorization",
            terminal=True,
        )
        snapshot = self.journal.record_success("route-a")
        assert snapshot is not None
        self.assertIsNone(snapshot["terminal_failure_class"])
        self.assertTrue(snapshot["healthy"])

    def test_recent_window_tracks_success_rate(self):
        for _ in range(4):
            self.journal.record_failure("route-b", _error(status=500))
        self.journal.record_success("route-b")
        snapshot = self.journal.get("route-b")
        assert snapshot is not None
        # 4 failures + 1 success = 5 samples, rate 0.2
        self.assertEqual(snapshot["recent_window_samples"], 5)
        self.assertAlmostEqual(snapshot["recent_success_rate"], 0.2)

    def test_window_is_bounded(self):
        for _ in range(15):
            self.journal.record_failure("route-c", _error(status=500))
        snapshot = self.journal.get("route-c")
        assert snapshot is not None
        self.assertEqual(snapshot["recent_window_samples"], 10)

    def test_rate_none_below_min_samples(self):
        self.journal.record_failure("route-d", _error(status=500))
        snapshot = self.journal.get("route-d")
        assert snapshot is not None
        self.assertIsNone(snapshot["recent_success_rate"])


class _SelfModel:
    def infer_domains(self, task, required_capabilities):
        return tuple(str(item).lower() for item in required_capabilities)

    def route_score(self, route_id, capability, prior):
        return float(prior)


class TerminalRouterTests(unittest.TestCase):
    def _router(self, snapshot):
        return ModelRouter(
            routes=[
                ModelRoute(
                    route_id="r1",
                    provider="p",
                    model="m",
                    capabilities={"general": 0.9},
                    reliability=0.9,
                    metadata={"health_failure_threshold": 3},
                )
            ],
            self_model=_SelfModel(),
            health_resolver=lambda route: snapshot,
        )

    def test_terminal_rejected_immediately(self):
        router = self._router(
            {
                "available": True,
                "healthy": False,
                "consecutive_failures": 1,
                "terminal_failure_class": "authentication_or_authorization",
                "recent_success_rate": None,
                "last_failure_at": "",
            }
        )
        goal = Goal(goal_id="g", task="task")
        with self.assertRaises(Exception):
            router.select(goal)

    def test_flapping_route_rejected_by_success_rate(self):
        router = self._router(
            {
                "available": True,
                "healthy": False,
                "consecutive_failures": 2,  # below threshold 3
                "terminal_failure_class": None,
                "recent_success_rate": 0.25,
                "last_failure_at": "",
            }
        )
        goal = Goal(goal_id="g", task="task")
        with self.assertRaises(Exception):
            router.select(goal)

    def test_healthy_rate_allows_despite_streak(self):
        router = self._router(
            {
                "available": True,
                "healthy": False,
                "consecutive_failures": 2,  # below threshold 3
                "terminal_failure_class": None,
                "recent_success_rate": 0.8,
                "last_failure_at": "",
            }
        )
        goal = Goal(goal_id="g", task="task")
        route = router.select(goal)
        self.assertEqual(route.route_id, "r1")


if __name__ == "__main__":
    unittest.main()

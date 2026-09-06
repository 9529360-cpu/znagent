from __future__ import annotations

import unittest

from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.router import ModelRouter, NoRouteAvailable


class _SelfModel:
    def infer_domains(self, task, required_capabilities):
        return tuple(str(item).lower() for item in required_capabilities)

    def route_score(self, route_id, capability, prior):
        return float(prior)


class ModelRouterHardEligibilityTests(unittest.TestCase):
    def _router(self, *routes: ModelRoute) -> ModelRouter:
        return ModelRouter(list(routes), _SelfModel())

    @staticmethod
    def _route(
        route_id: str,
        *,
        provider: str = "cloud-a",
        model: str = "model-a",
        capabilities=None,
        reliability: float = 0.9,
        metadata=None,
    ) -> ModelRoute:
        return ModelRoute(
            route_id=route_id,
            provider=provider,
            model=model,
            capabilities=capabilities or {"general": 1.0},
            reliability=reliability,
            cost_weight=0.0,
            latency_weight=0.0,
            metadata=dict(metadata or {}),
        )

    def test_missing_required_capability_is_removed_not_soft_penalized(self) -> None:
        forbidden_but_reliable = self._route(
            "no-coding",
            capabilities={"general": 1.0},
            reliability=1.0,
        )
        eligible = self._route(
            "coding",
            capabilities={"coding": 0.2},
            reliability=0.1,
        )
        goal = Goal(task="code", required_capabilities=("coding",))
        selected = self._router(forbidden_but_reliable, eligible).select(goal)
        self.assertEqual(selected.route_id, "coding")

    def test_no_capability_eligible_route_fails_closed(self) -> None:
        router = self._router(
            self._route("general-only", capabilities={"general": 1.0})
        )
        with self.assertRaisesRegex(NoRouteAvailable, "missing required capabilities: research"):
            router.select(Goal(task="research", required_capabilities=("research",)))

    def test_user_pins_and_denials_are_hard_filters(self) -> None:
        pinned = self._route(
            "pinned",
            provider="provider-b",
            model="model-b",
            reliability=0.1,
        )
        tempting = self._route(
            "tempting",
            provider="provider-a",
            model="model-a",
            reliability=1.0,
        )
        goal = Goal(
            task="general",
            metadata={"route_policy": {"pinned_provider": "provider-b", "pinned_model": "model-b"}},
        )
        self.assertEqual(self._router(tempting, pinned).select(goal).route_id, "pinned")

        denied = Goal(
            task="general",
            metadata={"route_policy": {"denied_providers": ["provider-a"], "denied_models": ["model-a"]}},
        )
        self.assertEqual(self._router(tempting, pinned).select(denied).route_id, "pinned")

    def test_unavailable_and_unhealthy_routes_do_not_enter_soft_score(self) -> None:
        unavailable = self._route("unavailable", reliability=1.0, metadata={"available": False})
        unhealthy = self._route("unhealthy", reliability=1.0, metadata={"health": "unhealthy"})
        healthy = self._route("healthy", reliability=0.1, metadata={"healthy": True})
        selected = self._router(unavailable, unhealthy, healthy).select(Goal(task="general"))
        self.assertEqual(selected.route_id, "healthy")

    def test_cloud_denied_worker_context_removes_cloud_route_before_scoring(self) -> None:
        cloud = self._route("cloud", reliability=1.0, metadata={"local": False})
        local = self._route("local", reliability=0.1, metadata={"local": True})
        goal = Goal(
            task="private delegated work",
            metadata={
                "cognition_request": {
                    "context": {
                        "worker_context_pack": {"data_classification": "cloud_denied"}
                    }
                }
            },
        )
        self.assertEqual(self._router(cloud, local).select(goal).route_id, "local")

    def test_local_only_without_explicit_local_route_fails_closed(self) -> None:
        cloud = self._route("cloud", metadata={})
        goal = Goal(task="local private work", metadata={"route_policy": {"local_only": True}})
        with self.assertRaisesRegex(NoRouteAvailable, "cloud/non-local route forbidden"):
            self._router(cloud).select(goal)

    def test_required_policy_and_authority_scopes_are_hard_gates(self) -> None:
        wrong = self._route(
            "wrong-policy",
            reliability=1.0,
            metadata={"policy_tags": ["public"], "authority_scopes": ["read"]},
        )
        allowed = self._route(
            "allowed-policy",
            reliability=0.1,
            metadata={
                "policy_tags": ["private", "enterprise"],
                "authority_scopes": ["read", "bounded_worker"],
            },
        )
        goal = Goal(
            task="policy bound",
            metadata={
                "route_policy": {
                    "required_policy_tags": ["private"],
                    "required_authority_scopes": ["bounded_worker"],
                }
            },
        )
        self.assertEqual(self._router(wrong, allowed).select(goal).route_id, "allowed-policy")

    def test_excluded_retry_route_is_removed_before_scoring(self) -> None:
        first = self._route("first", reliability=1.0)
        second = self._route("second", reliability=0.1)
        selected = self._router(first, second).select(Goal(task="retry"), excluded={"first"})
        self.assertEqual(selected.route_id, "second")


if __name__ == "__main__":
    unittest.main(verbosity=2)

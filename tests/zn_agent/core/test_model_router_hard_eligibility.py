from __future__ import annotations

import unittest

from zn_agent.core.models import Goal, ModelRoute
from zn_agent.core.provider_bridge import _current_model_spec, route_from_spec
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
    def _goal(task: str, *, required=("general",), metadata=None) -> Goal:
        return Goal(
            goal_id=f"goal-{task.replace(' ', '-')}",
            task=task,
            required_capabilities=tuple(required),
            metadata=dict(metadata or {}),
        )

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
        selected = self._router(forbidden_but_reliable, eligible).select(
            self._goal("code", required=("coding",))
        )
        self.assertEqual(selected.route_id, "coding")

    def test_no_capability_eligible_route_fails_closed(self) -> None:
        router = self._router(
            self._route("general-only", capabilities={"general": 1.0})
        )
        with self.assertRaisesRegex(NoRouteAvailable, "missing required capabilities: research"):
            router.select(self._goal("research", required=("research",)))

    def test_legacy_single_model_shortcut_explicitly_covers_existing_product_roles(self) -> None:
        spec = _current_model_spec({"model": "fixture-model"})
        self.assertIsNotNone(spec)
        assert spec is not None
        route = route_from_spec(spec)
        for required in (
            ("general",),
            ("research", "reasoning"),
            ("coding", "reasoning"),
            ("language_understanding",),
        ):
            with self.subTest(required=required):
                selected = self._router(route).select(
                    self._goal("legacy default", required=required)
                )
                self.assertEqual(selected.route_id, "default")

    def test_explicit_route_without_capability_contract_remains_fail_closed(self) -> None:
        route = route_from_spec({"id": "explicit", "provider": "fixture", "model": "model"})
        with self.assertRaisesRegex(NoRouteAvailable, "missing required capabilities: coding"):
            self._router(route).select(self._goal("explicit coding", required=("coding",)))

    def test_explicit_empty_capabilities_are_not_rewritten_to_general(self) -> None:
        route = route_from_spec(
            {
                "id": "explicit-empty",
                "provider": "fixture",
                "model": "model",
                "capabilities": {},
            }
        )
        self.assertEqual(route.capabilities, {})
        with self.assertRaisesRegex(NoRouteAvailable, "missing required capabilities: general"):
            self._router(route).select(self._goal("no declared capability"))

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
        goal = self._goal(
            "general",
            metadata={"route_policy": {"pinned_provider": "provider-b", "pinned_model": "model-b"}},
        )
        self.assertEqual(self._router(tempting, pinned).select(goal).route_id, "pinned")

        denied = self._goal(
            "general-denied",
            metadata={"route_policy": {"denied_providers": ["provider-a"], "denied_models": ["model-a"]}},
        )
        self.assertEqual(self._router(tempting, pinned).select(denied).route_id, "pinned")

    def test_malformed_user_policy_never_degrades_to_allow(self) -> None:
        route = self._route("otherwise-eligible")
        malformed_set = self._goal(
            "bad deny",
            metadata={"route_policy": {"denied_providers": {"provider-a": True}}},
        )
        with self.assertRaisesRegex(NoRouteAvailable, "denied_providers has invalid type"):
            self._router(route).select(malformed_set)

        malformed_member = self._goal(
            "bad deny member",
            metadata={"route_policy": {"denied_models": ["model-a", {"model": "model-b"}]}},
        )
        with self.assertRaisesRegex(NoRouteAvailable, "denied_models must contain only strings"):
            self._router(route).select(malformed_member)

        malformed_nested = self._goal(
            "bad nested policy",
            metadata={"cognition_request": {"context": {"route_policy": "allow everything"}}},
        )
        with self.assertRaisesRegex(NoRouteAvailable, "cognition route policy is malformed"):
            self._router(route).select(malformed_nested)

    def test_unknown_data_classification_fails_closed(self) -> None:
        route = self._route("otherwise-eligible")
        goal = self._goal(
            "unknown classification",
            metadata={"route_policy": {"data_classification": "mystery_policy"}},
        )
        with self.assertRaisesRegex(NoRouteAvailable, "data_classification is invalid"):
            self._router(route).select(goal)

    def test_unavailable_and_unhealthy_routes_do_not_enter_soft_score(self) -> None:
        unavailable = self._route("unavailable", reliability=1.0, metadata={"available": False})
        unhealthy = self._route("unhealthy", reliability=1.0, metadata={"health": "unhealthy"})
        healthy = self._route("healthy", reliability=0.1, metadata={"healthy": True})
        selected = self._router(unavailable, unhealthy, healthy).select(self._goal("general"))
        self.assertEqual(selected.route_id, "healthy")

    def test_dynamic_runtime_unavailability_is_a_hard_filter(self) -> None:
        local = self._route(
            "local-runtime-down",
            provider="ollama",
            reliability=1.0,
            metadata={"local": True},
        )
        fallback = self._route(
            "cloud-fallback",
            provider="cloud-a",
            reliability=0.1,
        )
        router = ModelRouter(
            [local, fallback],
            _SelfModel(),
            health_resolver=lambda route: (
                {"available": False, "runtime_observed": True}
                if route.route_id == "local-runtime-down"
                else None
            ),
        )

        selected = router.select(self._goal("general"))

        self.assertEqual(selected.route_id, "cloud-fallback")

    def test_zero_model_sentinel_preserves_local_resident_no_model_semantics(self) -> None:
        sentinel = ModelRoute(
            route_id="system2-unavailable",
            provider="none",
            model="none",
            capabilities={"general": 0.0},
            reliability=1.0,
            cost_weight=0.0,
            latency_weight=0.0,
            metadata={"model_available": False},
        )
        router = self._router(sentinel)
        self.assertIs(router.select(self._goal("needs cognition")), sentinel)
        with self.assertRaisesRegex(NoRouteAvailable, "zero-model sentinel already observed"):
            router.select(self._goal("needs cognition"), excluded={sentinel.route_id})

        # An ordinary unavailable route must never inherit sentinel behavior.
        real_unavailable = self._route(
            "system2-unavailable",
            provider="cloud-a",
            model="model-a",
            metadata={"model_available": False},
        )
        with self.assertRaisesRegex(NoRouteAvailable, "route unavailable"):
            self._router(real_unavailable).select(self._goal("real route"))

    def test_cloud_denied_worker_context_removes_cloud_route_before_scoring(self) -> None:
        cloud = self._route("cloud", reliability=1.0, metadata={"local": False})
        local = self._route("local", reliability=0.1, metadata={"local": True})
        goal = self._goal(
            "private delegated work",
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
        goal = self._goal("local private work", metadata={"route_policy": {"local_only": True}})
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
        goal = self._goal(
            "policy bound",
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
        selected = self._router(first, second).select(self._goal("retry"), excluded={"first"})
        self.assertEqual(selected.route_id, "second")


if __name__ == "__main__":
    unittest.main(verbosity=2)

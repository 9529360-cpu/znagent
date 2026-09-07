from __future__ import annotations

import json
import unittest

from zn_agent.core.credentials import CredentialStoreStatus
from zn_agent.core.provider_bridge import build_zn_cognitive_resource_plan


class _MemoryCredentials:
    def __init__(self, values: dict[str, str]):
        self.values = dict(values)

    def status(self) -> CredentialStoreStatus:
        return CredentialStoreStatus(available=True, backend="test-memory")

    def get(self, reference: str) -> str | None:
        return self.values.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)


class MultiRouteProviderPlanTests(unittest.TestCase):
    def test_two_provider_routes_materialize_distinct_secure_credentials_without_mutating_config(self) -> None:
        config = {
            "zn_kernel": {
                "max_attempts": 2,
                "routes": [
                    {
                        "id": "research-openai",
                        "provider": "openai",
                        "model": "gpt-test",
                        "credential_ref": "provider:openai",
                        "capabilities": {"research": 1.0, "reasoning": 1.0},
                    },
                    {
                        "id": "coding-anthropic",
                        "provider": "anthropic",
                        "model": "claude-test",
                        "credential_ref": "provider:anthropic",
                        "capabilities": {"coding": 1.0, "reasoning": 1.0},
                    },
                ],
            }
        }
        credentials = _MemoryCredentials(
            {
                "provider:openai": "openai-secret",
                "provider:anthropic": "anthropic-secret",
            }
        )

        original = json.dumps(config, sort_keys=True)
        plan = build_zn_cognitive_resource_plan(config, credential_store=credentials)

        self.assertTrue(plan.available, plan.error)
        self.assertEqual(len(plan.routes), 2)
        self.assertEqual(
            [(route.route_id, route.provider, route.model) for route in plan.routes],
            [
                ("research-openai", "openai", "gpt-test"),
                ("coding-anthropic", "anthropic", "claude-test"),
            ],
        )
        self.assertEqual(plan.routes[0].metadata.get("api_key"), "openai-secret")
        self.assertEqual(plan.routes[1].metadata.get("api_key"), "anthropic-secret")
        self.assertEqual(json.dumps(config, sort_keys=True), original)
        self.assertNotIn("openai-secret", original)
        self.assertNotIn("anthropic-secret", original)


if __name__ == "__main__":
    unittest.main(verbosity=2)

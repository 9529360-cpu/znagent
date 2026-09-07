from __future__ import annotations

import unittest

from zn_agent.core.route_policy_intake import merge_route_policy


class RoutePolicyMergeSemanticsTests(unittest.TestCase):
    def test_new_provider_only_allowlist_removes_stale_local_exception(self) -> None:
        merged = merge_route_policy(
            {"allowed_providers": ["openai"], "allow_local": True},
            {"allowed_providers": ["openai"]},
        )
        self.assertEqual(merged, {"allowed_providers": ["openai"]})

    def test_provider_and_local_allowlist_keeps_explicit_local_exception(self) -> None:
        merged = merge_route_policy(
            {"allowed_providers": ["anthropic"]},
            {"allowed_providers": ["openai"], "allow_local": True},
        )
        self.assertEqual(
            merged,
            {"allowed_providers": ["openai"], "allow_local": True},
        )

    def test_new_allowlist_preserves_independent_provider_denial(self) -> None:
        merged = merge_route_policy(
            {"denied_providers": ["anthropic"], "allow_local": True},
            {"allowed_providers": ["openai"]},
        )
        self.assertEqual(
            merged,
            {"denied_providers": ["anthropic"], "allowed_providers": ["openai"]},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

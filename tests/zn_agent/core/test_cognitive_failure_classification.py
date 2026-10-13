from __future__ import annotations

import unittest

from zn_agent.core.cognitive_failure import classify_cognitive_failure


class _ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class CognitiveFailureClassificationTests(unittest.TestCase):
    def test_context_overflow_is_request_scoped(self):
        observed = classify_cognitive_failure(
            _ProviderError(
                "maximum context length exceeded",
                status_code=400,
                code="context_length_exceeded",
            )
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "request_context_or_payload")
        self.assertFalse(observed.affects_route_health)

    def test_content_policy_beats_generic_forbidden_auth_classification(self):
        observed = classify_cognitive_failure(
            _ProviderError(
                "request blocked by content policy",
                status_code=403,
                code="content_filter",
            )
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "request_or_content_policy")
        self.assertFalse(observed.affects_route_health)

    def test_bad_request_is_not_provider_outage(self):
        observed = classify_cognitive_failure(
            _ProviderError("unsupported parameter: seed", status_code=400)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "request_or_input")
        self.assertFalse(observed.affects_route_health)

    def test_rate_limit_affects_route_health(self):
        observed = classify_cognitive_failure(
            _ProviderError("too many requests", status_code=429)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "rate_limit")
        self.assertTrue(observed.affects_route_health)

    def test_overload_affects_route_health(self):
        observed = classify_cognitive_failure(
            _ProviderError("service temporarily unavailable", status_code=503)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "provider_overloaded")
        self.assertTrue(observed.affects_route_health)

    def test_auth_affects_route_health(self):
        observed = classify_cognitive_failure(
            _ProviderError("invalid api key", status_code=401)
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "authentication_or_authorization")
        self.assertTrue(observed.affects_route_health)

    def test_builtin_connection_error_keeps_existing_route_health_meaning(self):
        observed = classify_cognitive_failure(
            ConnectionError("primary provider temporarily unavailable private-detail")
        )
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual(observed.failure_class, "network_or_service")
        self.assertTrue(observed.affects_route_health)


if __name__ == "__main__":
    unittest.main()

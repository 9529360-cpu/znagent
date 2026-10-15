from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import httpx

from zn_agent.core import proxy_env
from zn_agent.core import telegram_network as tnet
from zn_agent.core.anthropic_resource import AnthropicCognitiveResource
from zn_agent.core.cognitive_resource import OpenAICompatibleCognitiveResource
from zn_agent.core.gemini_resource import GeminiCognitiveResource
from zn_agent.core.models import ModelRoute

try:
    import anthropic  # noqa: F401
except ImportError:  # pragma: no cover - optional extra
    anthropic = None

try:
    import openai  # noqa: F401
except ImportError:  # pragma: no cover - pinned dependency, normally present
    openai = None

MALFORMED_NO_PROXY = {
    "bad port": {"NO_PROXY": "example.com:abc"},
    "colons": {"NO_PROXY": "::::"},
    "unclosed bracket": {"NO_PROXY": "http://[::1"},
    "wildcard bad port": {"NO_PROXY": "*.example.com:abc"},
    "over-long": {"NO_PROXY": "a" * 100000},
    # Bracketed IPv6 crashes httpx's NO_PROXY parser (bare ::1 is the valid form).
    "bracketed ipv6": {"NO_PROXY": "[::1]"},
}

MALFORMED_PROXY_URL = {
    "proxy bad scheme": {"HTTP_PROXY": "://bad"},
    "proxy bad port": {"HTTP_PROXY": "http://proxy.example.com:abc"},
    "proxy unclosed bracket": {"HTTPS_PROXY": "http://[::1"},
}

ALL_MALFORMED = {
    **MALFORMED_NO_PROXY,
    **MALFORMED_PROXY_URL,
    "all combined": {
        "NO_PROXY": "::::",
        "HTTP_PROXY": "garbage",
        "HTTPS_PROXY": "://bad",
        "ALL_PROXY": "http://[::1",
    },
}

VALID_PROXY_ENV = {
    "plain host": {"NO_PROXY": "example.com"},
    "host port": {"NO_PROXY": "example.com:8080"},
    "wildcard": {"NO_PROXY": "*.example.com"},
    "localhost": {"NO_PROXY": "localhost"},
    "ipv4": {"NO_PROXY": "192.168.0.1"},
    "ipv6": {"NO_PROXY": "::1"},
    "star": {"NO_PROXY": "*"},
    "empty items": {"NO_PROXY": ",,,"},
    "mixed": {"NO_PROXY": "example.com, localhost, *.example.com:8080"},
    "proxy url": {"HTTP_PROXY": "http://proxy.example.com:8080"},
    "schemeless proxy": {"HTTP_PROXY": "proxy.example.com:8080"},
    "socks proxy": {"ALL_PROXY": "socks5://proxy.example.com:1080"},
    "proxy auth": {"HTTPS_PROXY": "http://user:pass@proxy.example.com:8080"},
}


def _gemini_route(**overrides):
    values = {
        "route_id": "gemini",
        "provider": "gemini",
        "model": "google/gemini-3.1-pro",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key"},
    }
    values.update(overrides)
    return ModelRoute(**values)


def _openai_route(**overrides):
    values = {
        "route_id": "openai-compat",
        "provider": "openai",
        "model": "test-model",
        "capabilities": {"general": 0.9},
        "metadata": {
            "api_key": "test-key",
            "base_url": "http://127.0.0.1:1/v1",
        },
    }
    values.update(overrides)
    return ModelRoute(**values)


def _anthropic_route(**overrides):
    values = {
        "route_id": "anthropic",
        "provider": "anthropic",
        "model": "claude-test",
        "capabilities": {"general": 0.9},
        "metadata": {"api_key": "test-key"},
    }
    values.update(overrides)
    return ModelRoute(**values)


class _GenerateContentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib handler name
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "bounded Gemini answer"}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 4,
                "totalTokenCount": 7,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D102 - silence test server logs
        pass


class ProxyEnvDetectionTests(unittest.TestCase):
    def test_malformed_no_proxy_values_are_named(self):
        for _label, env in MALFORMED_NO_PROXY.items():
            with self.subTest(label=_label):
                bad = proxy_env.malformed_proxy_env_names(env)
                self.assertIn("NO_PROXY", bad)

    def test_malformed_proxy_url_values_are_named(self):
        for _label, env in MALFORMED_PROXY_URL.items():
            with self.subTest(label=_label):
                bad = proxy_env.malformed_proxy_env_names(env)
                key = next(iter(env))
                self.assertIn(key, bad)

    def test_lowercase_no_proxy_is_checked(self):
        bad = proxy_env.malformed_proxy_env_names({"no_proxy": "example.com:abc"})
        self.assertIn("no_proxy", bad)

    def test_valid_proxy_env_is_not_flagged(self):
        for _label, env in VALID_PROXY_ENV.items():
            with self.subTest(label=_label):
                self.assertEqual(proxy_env.malformed_proxy_env_names(env), [])

    def test_empty_env_is_not_flagged(self):
        self.assertEqual(proxy_env.malformed_proxy_env_names({}), [])

    def test_normalize_proxy_url(self):
        self.assertIsNone(proxy_env.normalize_proxy_url(None))
        self.assertIsNone(proxy_env.normalize_proxy_url(""))
        self.assertIsNone(proxy_env.normalize_proxy_url("://bad"))
        self.assertIsNone(proxy_env.normalize_proxy_url("http://proxy:abc"))
        self.assertEqual(
            proxy_env.normalize_proxy_url("http://proxy:8080"), "http://proxy:8080"
        )
        # Schemeless values get http://, matching httpx env semantics.
        self.assertEqual(
            proxy_env.normalize_proxy_url("proxy:8080"), "http://proxy:8080"
        )


class BuildClientToleranceTests(unittest.TestCase):
    def test_build_httpx_client_survives_every_malformed_shape(self):
        for _label, env in ALL_MALFORMED.items():
            with self.subTest(label=_label):
                with mock.patch.dict(os.environ, env, clear=True):
                    client = proxy_env.build_httpx_client()
                    self.addCleanup(client.close)
                    self.assertIsInstance(client, httpx.Client)

    def test_build_httpx_client_keeps_working_with_valid_env(self):
        for _label, env in VALID_PROXY_ENV.items():
            with self.subTest(label=_label):
                with mock.patch.dict(os.environ, env, clear=True):
                    client = proxy_env.build_httpx_client()
                    self.addCleanup(client.close)
                    self.assertIsInstance(client, httpx.Client)

    def test_build_httpx_client_still_raises_for_explicit_bad_proxy(self):
        # An explicitly passed malformed proxy is a caller bug, not env
        # tolerance: it must still surface instead of being silently dropped.
        with self.assertRaises(ValueError):
            proxy_env.build_httpx_client(proxy="://bad")

    def test_build_sdk_client_retries_with_direct_http_client(self):
        seen = []

        def flaky_builder(**kwargs):
            seen.append(kwargs)
            if "http_client" not in kwargs:
                raise ValueError("Unknown scheme for proxy URL")
            return ("built", kwargs["http_client"])

        with mock.patch.dict(os.environ, {"NO_PROXY": "::::"}, clear=True):
            result = proxy_env.build_sdk_client(flaky_builder, api_key="k")
        self.assertEqual(result[0], "built")
        self.assertIsInstance(result[1], httpx.Client)
        self.assertEqual(len(seen), 2)

    def test_build_sdk_client_reraises_when_env_is_clean(self):
        def always_bad(**kwargs):
            raise ValueError("not a proxy problem")

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                proxy_env.build_sdk_client(always_bad)


@unittest.skipIf(openai is None, "openai SDK not installed")
class OpenAIClientToleranceTests(unittest.TestCase):
    def test_openai_client_construction_survives_malformed_env(self):
        for _label, env in ALL_MALFORMED.items():
            with self.subTest(label=_label):
                with mock.patch.dict(os.environ, env, clear=True):
                    resource = OpenAICompatibleCognitiveResource(
                        _openai_route(),
                    )
                    client = resource._client()
                    self.addCleanup(client.close)
                    self.assertIsNotNone(client)


@unittest.skipIf(anthropic is None, "anthropic SDK not installed")
class AnthropicClientToleranceTests(unittest.TestCase):
    def test_anthropic_client_construction_survives_malformed_env(self):
        for _label, env in ALL_MALFORMED.items():
            with self.subTest(label=_label):
                with mock.patch.dict(os.environ, env, clear=True):
                    resource = AnthropicCognitiveResource(_anthropic_route())
                    client = resource._client()
                    self.addCleanup(client.close)
                    self.assertIsNotNone(client)


class GeminiToleranceTests(unittest.TestCase):
    def test_gemini_construction_survives_malformed_env(self):
        for _label, env in ALL_MALFORMED.items():
            with self.subTest(label=_label):
                with mock.patch.dict(os.environ, env, clear=True):
                    resource = GeminiCognitiveResource(_gemini_route())
                    self.addCleanup(resource.close)
                    self.assertIsNotNone(resource._client)

    def test_gemini_invoke_works_end_to_end_under_malformed_env(self):
        # Default-constructed client (proxy fallback) against a local server:
        # proves a cognition call still completes with malformed proxy env.
        server = ThreadingHTTPServer(("127.0.0.1", 0), _GenerateContentHandler)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        route = _gemini_route(
            metadata={
                "api_key": "test-key",
                "base_url": f"http://127.0.0.1:{port}",
            }
        )
        with mock.patch.dict(os.environ, {"NO_PROXY": "::::"}, clear=True):
            resource = GeminiCognitiveResource(route)
            self.addCleanup(resource.close)
            increment = resource.invoke(question="hello?", context="")
        self.assertEqual(increment.text, "bounded Gemini answer")


class TelegramProxyToleranceTests(unittest.TestCase):
    def test_no_proxy_entry_matching_never_crashes_on_malformed_entries(self):
        malformed = [
            "http://[::1",
            "::::",
            "example.com:abc",
            "*.example.com:abc",
            "a" * 100000,
            "http://host:99999999999",
            "",
            "   ",
            "host:",
            ":8080",
            "[::1",
            "1.2.3.4/33",
            ":::",
            "http://",
            "http://[::1]:abc",
        ]
        for entry in malformed:
            with self.subTest(entry=entry[:20]):
                self.assertFalse(tnet._no_proxy_entry_matches(entry, "example.com", 443))

    def test_proxy_bypassed_never_crashes_on_malformed_no_proxy(self):
        self.assertFalse(
            tnet._proxy_bypassed(
                ["example.com"],
                environ={"NO_PROXY": "::::,http://[::1"},
                port=443,
            )
        )

    def test_resolve_proxy_url_skips_malformed_candidates(self):
        self.assertEqual(
            tnet.resolve_proxy_url(
                environ={"HTTPS_PROXY": "://bad", "HTTP_PROXY": "http://ok:8080"},
                target_hosts=["api.telegram.org"],
            ),
            "http://ok:8080",
        )

    def test_resolve_proxy_url_normalizes_schemeless_candidate(self):
        self.assertEqual(
            tnet.resolve_proxy_url(
                environ={"HTTP_PROXY": "proxy:8080"},
                target_hosts=["api.telegram.org"],
            ),
            "http://proxy:8080",
        )

    def test_resolve_proxy_url_returns_none_when_all_candidates_malformed(self):
        self.assertIsNone(
            tnet.resolve_proxy_url(
                environ={"HTTP_PROXY": "http://proxy:abc"},
                target_hosts=["api.telegram.org"],
            )
        )

    def test_resolve_proxy_url_keeps_valid_candidate_unchanged(self):
        self.assertEqual(
            tnet.resolve_proxy_url(
                environ={"HTTPS_PROXY": "http://proxy:8080"},
                target_hosts=["api.telegram.org"],
            ),
            "http://proxy:8080",
        )


if __name__ == "__main__":
    unittest.main()

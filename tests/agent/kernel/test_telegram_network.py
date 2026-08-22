from __future__ import annotations

import unittest

import httpx

from agent.kernel import telegram_network as tnet


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, calls, behavior, **kwargs):
        self.calls = calls
        self.behavior = behavior
        self.kwargs = kwargs
        self.closed = False

    def handle_request(self, request):
        self.calls.append(
            {
                "url_host": request.url.host,
                "host_header": request.headers.get("host"),
                "sni_hostname": request.extensions.get("sni_hostname"),
            }
        )
        action = self.behavior.get(request.url.host, "ok")
        if action == "timeout":
            raise httpx.ConnectTimeout("timeout")
        if action == "connect_error":
            raise httpx.ConnectError("connect")
        if isinstance(action, Exception):
            raise action
        return httpx.Response(200, request=request, text="ok")

    def close(self):
        self.closed = True


def _factory(calls, behavior, seen=None):
    def factory(**kwargs):
        if seen is not None:
            seen.append(kwargs.copy())
        return _FakeTransport(calls, behavior, **kwargs)

    return factory


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class _DohClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, *args, **kwargs):
        return self.responses.pop(0)


class TelegramNetworkTests(unittest.TestCase):
    def test_parse_filters_internal_and_invalid_addresses(self):
        self.assertEqual(
            tnet.parse_fallback_ip_env(
                "149.154.167.220,bad,127.0.0.1,2001:db8::1"
            ),
            ["149.154.167.220"],
        )

    def test_rewrite_preserves_logical_host_and_tls_sni(self):
        request = httpx.Request(
            "POST",
            "https://api.telegram.org/botTOKEN/getMe",
        )
        rewritten = tnet._rewrite_request_for_ip(request, "149.154.167.220")
        self.assertEqual(rewritten.url.host, "149.154.167.220")
        self.assertEqual(rewritten.headers["host"], "api.telegram.org")
        self.assertEqual(rewritten.extensions["sni_hostname"], "api.telegram.org")

    def test_ipv4_first_becomes_sticky_and_recovers_when_stale(self):
        calls = []
        behavior = {
            "149.154.167.220": "ok",
            "149.154.166.110": "ok",
            "api.telegram.org": "ok",
        }
        transport = tnet.TelegramFallbackTransport(
            ["149.154.167.220", "149.154.166.110"],
            environ={},
            transport_factory=_factory(calls, behavior),
        )
        request = httpx.Request(
            "GET",
            "https://api.telegram.org/botTOKEN/getMe",
        )

        self.assertEqual(transport.handle_request(request).status_code, 200)
        self.assertEqual([item["url_host"] for item in calls], ["149.154.167.220"])
        self.assertEqual(transport._sticky_ip, "149.154.167.220")

        calls.clear()
        behavior["149.154.167.220"] = "timeout"
        self.assertEqual(transport.handle_request(request).status_code, 200)
        self.assertEqual(
            [item["url_host"] for item in calls],
            ["149.154.167.220", "149.154.166.110"],
        )
        self.assertEqual(transport._sticky_ip, "149.154.166.110")

    def test_hostname_is_last_resort_when_ipv4_paths_fail(self):
        calls = []
        behavior = {
            "149.154.167.220": "timeout",
            "api.telegram.org": "ok",
        }
        transport = tnet.TelegramFallbackTransport(
            ["149.154.167.220"],
            environ={},
            transport_factory=_factory(calls, behavior),
        )
        request = httpx.Request(
            "GET",
            "https://api.telegram.org/botTOKEN/getMe",
        )

        self.assertEqual(transport.handle_request(request).status_code, 200)
        self.assertEqual(
            [item["url_host"] for item in calls],
            ["149.154.167.220", "api.telegram.org"],
        )
        self.assertIsNone(transport._sticky_ip)

    def test_non_connect_error_does_not_blindly_fail_over(self):
        calls = []
        behavior = {
            "149.154.167.220": RuntimeError("bad protocol"),
            "api.telegram.org": "ok",
        }
        transport = tnet.TelegramFallbackTransport(
            ["149.154.167.220"],
            environ={},
            transport_factory=_factory(calls, behavior),
        )
        request = httpx.Request(
            "GET",
            "https://api.telegram.org/botTOKEN/getMe",
        )

        with self.assertRaises(RuntimeError):
            transport.handle_request(request)
        self.assertEqual([item["url_host"] for item in calls], ["149.154.167.220"])

    def test_proxy_and_no_proxy_are_resolved_inside_zn(self):
        self.assertEqual(
            tnet.resolve_proxy_url(
                environ={"HTTPS_PROXY": "http://proxy:8080"},
                target_hosts=["api.telegram.org"],
            ),
            "http://proxy:8080",
        )
        self.assertIsNone(
            tnet.resolve_proxy_url(
                environ={
                    "HTTPS_PROXY": "http://proxy:8080",
                    "NO_PROXY": "api.telegram.org,149.154.160.0/20",
                },
                target_hosts=["api.telegram.org", "149.154.167.220"],
            )
        )

    def test_proxy_reaches_primary_and_lazy_fallback_pools(self):
        calls = []
        seen = []
        transport = tnet.TelegramFallbackTransport(
            ["149.154.167.220"],
            environ={"HTTPS_PROXY": "http://proxy:8080"},
            transport_factory=_factory(
                calls,
                {"149.154.167.220": "ok"},
                seen,
            ),
        )
        request = httpx.Request(
            "GET",
            "https://api.telegram.org/botTOKEN/getMe",
        )
        transport.handle_request(request)

        self.assertGreaterEqual(len(seen), 2)
        self.assertTrue(
            all(item["proxy"] == "http://proxy:8080" for item in seen)
        )

    def test_doh_discovery_deduplicates_valid_a_records(self):
        client = _DohClient(
            [
                _Response(
                    {
                        "Answer": [
                            {"type": 1, "data": "149.154.167.220"},
                            {"type": 28, "data": "2001:db8::1"},
                        ]
                    }
                ),
                _Response(
                    {
                        "Answer": [
                            {"type": 1, "data": "149.154.167.220"},
                            {"type": 1, "data": "149.154.166.110"},
                        ]
                    }
                ),
            ]
        )
        self.assertEqual(
            tnet.discover_fallback_ips(client=client),
            ["149.154.167.220", "149.154.166.110"],
        )


if __name__ == "__main__":
    unittest.main()

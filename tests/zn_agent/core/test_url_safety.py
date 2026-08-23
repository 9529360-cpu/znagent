from __future__ import annotations

import socket
import unittest

from zn_agent.core.url_safety import (
    allow_private_urls,
    is_always_blocked_url,
    is_safe_url,
)


def _resolver_for(*addresses):
    def resolve(host, port, family, socktype):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socktype, 6, "", (address, 0))
            for address in addresses
        ]

    return resolve


class UrlSafetyTests(unittest.TestCase):
    def test_public_http_target_is_allowed(self):
        self.assertTrue(
            is_safe_url(
                "https://example.test/path",
                environ={},
                resolver=_resolver_for("93.184.216.34"),
            )
        )

    def test_private_loopback_cgnat_and_mapped_private_are_blocked(self):
        for address in (
            "127.0.0.1",
            "10.0.0.8",
            "100.64.1.2",
            "::ffff:10.1.2.3",
        ):
            with self.subTest(address=address):
                self.assertFalse(
                    is_safe_url(
                        "https://host.test",
                        environ={},
                        resolver=_resolver_for(address),
                    )
                )

    def test_metadata_floor_survives_private_network_opt_out(self):
        self.assertFalse(
            is_safe_url(
                "http://169.254.169.254/latest/meta-data",
                allow_private=True,
                environ={},
                resolver=_resolver_for("169.254.169.254"),
            )
        )
        self.assertTrue(
            is_always_blocked_url(
                "https://metadata.google.internal/computeMetadata/v1",
                resolver=_resolver_for("93.184.216.34"),
            )
        )

    def test_explicit_zn_private_network_opt_out_allows_normal_private_target(self):
        self.assertTrue(
            is_safe_url(
                "https://internal.test",
                allow_private=True,
                environ={},
                resolver=_resolver_for("10.0.0.5"),
            )
        )

    def test_dns_failure_is_fail_closed_except_proxy_side_resolution(self):
        def broken(*args, **kwargs):
            raise socket.gaierror("no dns")

        self.assertFalse(
            is_safe_url(
                "https://public.example",
                environ={},
                resolver=broken,
            )
        )
        self.assertTrue(
            is_safe_url(
                "https://public.example",
                environ={"HTTPS_PROXY": "http://proxy:8080"},
                resolver=broken,
            )
        )
        self.assertFalse(
            is_safe_url(
                "http://127.0.0.1",
                environ={"HTTPS_PROXY": "http://proxy:8080"},
                resolver=broken,
            )
        )

    def test_zn_config_and_env_control_private_network_opt_out(self):
        self.assertTrue(
            allow_private_urls(
                {"security": {"allow_private_urls": True}},
                environ={},
            )
        )
        self.assertFalse(
            allow_private_urls(
                {"security": {"allow_private_urls": True}},
                environ={"ZN_ALLOW_PRIVATE_URLS": "false"},
            )
        )
        self.assertTrue(
            allow_private_urls(
                {"security": {"allow_private_urls": False}},
                environ={"ZN_ALLOW_PRIVATE_URLS": "true"},
            )
        )


if __name__ == "__main__":
    unittest.main()

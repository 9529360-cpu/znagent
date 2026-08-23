from __future__ import annotations

"""ZN-owned URL/network safety primitives.

Source-extracted from the mature URL safety layer. These checks belong to ZN's
network body, not to an old tool registry: HTTP(S)-only inputs, cloud metadata
sentinels, private/loopback/link-local/CGNAT blocking, IPv4-mapped IPv6 handling,
proxy-aware DNS failure semantics, and an explicit ZN private-network opt-out.
"""

import ipaddress
import os
import socket
from collections.abc import Mapping
from typing import Callable
from urllib.parse import urlsplit

from .config import load_zn_config


_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})
_ALWAYS_BLOCKED_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("169.254.169.253"),
    ipaddress.ip_address("fd00:ec2::254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("::ffff:169.254.169.254"),
    ipaddress.ip_address("::ffff:169.254.170.2"),
    ipaddress.ip_address("::ffff:169.254.169.253"),
    ipaddress.ip_address("::ffff:100.100.100.200"),
})
_ALWAYS_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::ffff:169.254.0.0/112"),
)
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_PROXY_ENV_VARS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)

Resolver = Callable[..., list[tuple]]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def allow_private_urls(
    config: Mapping[str, object] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Resolve ZN's explicit private-network opt-out.

    ``ZN_ALLOW_PRIVATE_URLS`` has priority. Otherwise only ZN's own
    ``security.allow_private_urls`` is read; the old Hermes browser/config
    namespace is intentionally not consulted.
    """
    env = environ if environ is not None else os.environ
    raw = env.get("ZN_ALLOW_PRIVATE_URLS")
    if raw is not None and str(raw).strip():
        return _truthy(raw)
    cfg = config if config is not None else load_zn_config()
    security = cfg.get("security") if isinstance(cfg, Mapping) else None
    return bool(isinstance(security, Mapping) and _truthy(security.get("allow_private_urls")))


def _proxy_is_configured(environ: Mapping[str, str]) -> bool:
    return any(str(environ.get(name) or "").strip() for name in _PROXY_ENV_VARS)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        embedded = ip.ipv4_mapped
        return bool(
            embedded.is_private
            or embedded.is_loopback
            or embedded.is_link_local
            or embedded.is_reserved
            or embedded.is_multicast
            or embedded.is_unspecified
            or embedded in _CGNAT_NETWORK
        )
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in _CGNAT_NETWORK
    )


def _always_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip in _ALWAYS_BLOCKED_IPS or any(ip in network for network in _ALWAYS_BLOCKED_NETWORKS)


def _literal_ip(hostname: str):
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def is_safe_url(
    url: str,
    *,
    allow_private: bool | None = None,
    config: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> bool:
    """Fail closed for unsafe or unresolved direct HTTP(S) targets.

    When a proxy is explicitly configured, a non-literal hostname whose local
    DNS lookup fails may proceed so DNS can be delegated to the proxy. Metadata
    hostnames remain blocked before that exception and literal IPs never receive
    the proxy-DNS exemption.
    """
    env = environ if environ is not None else os.environ
    try:
        parsed = urlsplit(str(url or "").strip())
        scheme = str(parsed.scheme or "").lower()
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    if scheme not in {"http", "https"} or not hostname:
        return False
    if hostname in _BLOCKED_HOSTNAMES:
        return False

    literal = _literal_ip(hostname)
    if literal is not None and _always_blocked_ip(literal):
        return False

    permit_private = (
        bool(allow_private)
        if allow_private is not None
        else allow_private_urls(config, environ=env)
    )

    try:
        addresses = resolver(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return literal is None and _proxy_is_configured(env)
    except Exception:
        return False

    saw_address = False
    for _family, _type, _proto, _canonname, sockaddr in addresses:
        if not sockaddr:
            return False
        raw = str(sockaddr[0] or "").split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        saw_address = True
        if _always_blocked_ip(ip):
            return False
        if not permit_private and _is_blocked_ip(ip):
            return False
    return saw_address


def is_always_blocked_url(
    url: str,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> bool:
    """Check the non-negotiable cloud-metadata floor only."""
    try:
        parsed = urlsplit(str(url or "").strip())
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    if not hostname:
        return False
    if hostname in _BLOCKED_HOSTNAMES:
        return True
    literal = _literal_ip(hostname)
    if literal is not None:
        return _always_blocked_ip(literal)
    try:
        addresses = resolver(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except Exception:
        return False
    for _family, _type, _proto, _canonname, sockaddr in addresses:
        try:
            ip = ipaddress.ip_address(str(sockaddr[0] or "").split("%", 1)[0])
        except (ValueError, TypeError):
            continue
        if _always_blocked_ip(ip):
            return True
    return False

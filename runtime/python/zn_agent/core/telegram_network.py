from __future__ import annotations

"""ZN-owned Telegram network transport.

Source-extracted from the mature Telegram adapter's network layer. The useful
mechanisms live here independently of the old gateway: IPv4-first fallback for
blackholed dual-stack routes, Host/SNI preservation, sticky healthy paths,
failed-pool replacement, bounded pools, proxy/NO_PROXY handling, and optional
DNS-over-HTTPS discovery.
"""

import ipaddress
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterable, Mapping
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_HOST = "api.telegram.org"
SEED_FALLBACK_IPS = ("149.154.166.110", "149.154.167.220")
_DOH_TIMEOUT = 4.0
_DOH_PROVIDERS = (
    (
        "https://dns.google/resolve",
        {"name": TELEGRAM_API_HOST, "type": "A"},
        {},
    ),
    (
        "https://cloudflare-dns.com/dns-query",
        {"name": TELEGRAM_API_HOST, "type": "A"},
        {"Accept": "application/dns-json"},
    ),
)
_UNSET = object()


def _normalize_fallback_ips(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            logger.warning("Ignoring invalid Telegram fallback IP: %r", raw)
            continue
        if addr.version != 4:
            logger.warning("Ignoring non-IPv4 Telegram fallback IP: %s", raw)
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            logger.warning("Ignoring private/internal Telegram fallback IP: %s", raw)
            continue
        normalized.append(str(addr))
    return normalized


def parse_fallback_ip_env(value: str | None) -> list[str]:
    if not value:
        return []
    return _normalize_fallback_ips(part.strip() for part in str(value).split(","))


def _split_host_port(value: str) -> tuple[str, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", None
    if "://" in raw:
        parsed = urlsplit(raw)
        try:
            port = parsed.port
        except ValueError:
            port = None
        return (parsed.hostname or "").lower().rstrip("."), port
    if raw.startswith("[") and "]" in raw:
        host, _, rest = raw[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
        return host.lower().rstrip("."), port
    if raw.count(":") == 1:
        host, _, maybe_port = raw.rpartition(":")
        if maybe_port.isdigit():
            return host.lower().rstrip("."), int(maybe_port)
    return raw.lower().strip("[]").rstrip("."), None


def _no_proxy_entry_matches(entry: str, host: str, port: int | None = None) -> bool:
    token = str(entry or "").strip().lower()
    normalized_host = str(host or "").strip().lower().strip("[]").rstrip(".")
    if not token or not normalized_host:
        return False
    if token == "*":
        return True

    token_host, token_port = _split_host_port(token)
    if token_port is not None and token_port != port:
        return False
    if not token_host:
        return False

    try:
        network = ipaddress.ip_network(token_host, strict=False)
        try:
            return ipaddress.ip_address(normalized_host) in network
        except ValueError:
            return False
    except ValueError:
        pass

    token_host = token_host.lstrip(".")
    return normalized_host == token_host or normalized_host.endswith("." + token_host)


def _no_proxy_entries(environ: Mapping[str, str]) -> list[str]:
    entries: list[str] = []
    for key in ("NO_PROXY", "no_proxy"):
        raw = str(environ.get(key) or "")
        entries.extend(part.strip() for part in raw.split(",") if part.strip())
    return entries


def _proxy_bypassed(
    targets: Iterable[str],
    *,
    environ: Mapping[str, str],
    port: int = 443,
) -> bool:
    entries = _no_proxy_entries(environ)
    if not entries:
        return False
    normalized_targets = [
        str(target or "").strip()
        for target in targets
        if str(target or "").strip()
    ]
    if not normalized_targets:
        return False
    return any(
        _no_proxy_entry_matches(entry, target, port)
        for target in normalized_targets
        for entry in entries
    )


def _detect_macos_system_proxy() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        output = subprocess.check_output(
            ["scutil", "--proxy"],
            timeout=3,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    props: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if " : " not in line:
            continue
        key, _, value = line.partition(" : ")
        props[key.strip()] = value.strip()
    for enabled_key, host_key, port_key in (
        ("HTTPSEnable", "HTTPSProxy", "HTTPSPort"),
        ("HTTPEnable", "HTTPProxy", "HTTPPort"),
    ):
        if props.get(enabled_key) != "1":
            continue
        host = props.get(host_key)
        proxy_port = props.get(port_key)
        if host and proxy_port:
            return f"http://{host}:{proxy_port}"
    return None


def resolve_proxy_url(
    explicit: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    target_hosts: Iterable[str] = (),
) -> str | None:
    """Resolve Telegram proxy without importing the old gateway config layer."""
    env = environ if environ is not None else os.environ
    targets = tuple(target_hosts) or (TELEGRAM_API_HOST,)
    if _proxy_bypassed(targets, environ=env):
        return None

    candidates = (
        explicit,
        env.get("TELEGRAM_PROXY"),
        env.get("HTTPS_PROXY"),
        env.get("https_proxy"),
        env.get("ALL_PROXY"),
        env.get("all_proxy"),
        env.get("HTTP_PROXY"),
        env.get("http_proxy"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return _detect_macos_system_proxy()


def _response_json(response: Any) -> dict[str, Any]:
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def discover_fallback_ips(
    *,
    client: Any | None = None,
    timeout: float = _DOH_TIMEOUT,
) -> list[str]:
    """Discover current Telegram A records via bounded public DoH requests."""
    owns_client = client is None
    active = client or httpx.Client(timeout=max(0.5, float(timeout)), trust_env=False)
    discovered: list[str] = []
    try:
        for url, params, headers in _DOH_PROVIDERS:
            try:
                response = active.get(url, params=params, headers=headers, timeout=timeout)
                status = int(getattr(response, "status_code", 0) or 0)
                if status < 200 or status >= 300:
                    continue
                payload = _response_json(response)
            except Exception as exc:
                logger.debug("Telegram DoH query failed for %s: %s", url, exc)
                continue
            for answer in payload.get("Answer") or ():
                if not isinstance(answer, dict) or answer.get("type") != 1:
                    continue
                discovered.append(str(answer.get("data") or "").strip())
    finally:
        if owns_client:
            active.close()

    validated = _normalize_fallback_ips(discovered)
    if validated:
        return list(dict.fromkeys(validated))

    return list(SEED_FALLBACK_IPS)


def _rewrite_request_for_ip(request: httpx.Request, ip: str) -> httpx.Request:
    original_host = request.url.host or TELEGRAM_API_HOST
    url = request.url.copy_with(host=ip)
    headers = request.headers.copy()
    headers["host"] = original_host
    extensions = dict(request.extensions)
    extensions["sni_hostname"] = original_host
    return httpx.Request(
        method=request.method,
        url=url,
        headers=headers,
        stream=request.stream,
        extensions=extensions,
    )


def _is_retryable_connect_error(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError))


TransportFactory = Callable[..., httpx.BaseTransport]


class TelegramFallbackTransport(httpx.BaseTransport):
    """Try Telegram IPv4 literals first and retain the healthy path.

    The request URL may point at a literal address, but the logical Host header
    and TLS SNI remain ``api.telegram.org``. This avoids blackholed AAAA routes
    without weakening certificate verification.
    """

    _POOL_LIMITS = httpx.Limits(max_connections=8, max_keepalive_connections=4)

    def __init__(
        self,
        fallback_ips: Iterable[str],
        *,
        proxy_url: str | None = None,
        environ: Mapping[str, str] | None = None,
        limits: httpx.Limits | None = None,
        transport_factory: TransportFactory | None = None,
    ):
        self._fallback_ips = list(dict.fromkeys(_normalize_fallback_ips(fallback_ips)))
        self._environ = environ if environ is not None else os.environ
        targets = (TELEGRAM_API_HOST, *self._fallback_ips)
        proxy = resolve_proxy_url(
            proxy_url,
            environ=self._environ,
            target_hosts=targets,
        )
        self._transport_kwargs: dict[str, Any] = {
            "limits": limits or self._POOL_LIMITS,
            "trust_env": False,
        }
        if proxy:
            self._transport_kwargs["proxy"] = proxy
        self._factory: TransportFactory = transport_factory or httpx.HTTPTransport
        self._primary = self._factory(**self._transport_kwargs)
        self._fallbacks: dict[str, httpx.BaseTransport] = {}
        self._sticky_ip: object = _UNSET
        self._lock = threading.RLock()
        self._closed = False

    def _get_fallback(self, ip: str) -> httpx.BaseTransport:
        with self._lock:
            transport = self._fallbacks.get(ip)
            if transport is None:
                transport = self._factory(**self._transport_kwargs)
                self._fallbacks[ip] = transport
            return transport

    def _reset_primary(self, failed: httpx.BaseTransport) -> None:
        with self._lock:
            if self._closed or failed is not self._primary:
                return
            self._primary = self._factory(**self._transport_kwargs)
        try:
            failed.close()
        except Exception:
            logger.debug("Error closing failed Telegram primary transport", exc_info=True)

    def _reset_fallback(self, ip: str) -> None:
        with self._lock:
            failed = self._fallbacks.pop(ip, None)
        if failed is None:
            return
        try:
            failed.close()
        except Exception:
            logger.debug(
                "Error closing failed Telegram fallback transport %s",
                ip,
                exc_info=True,
            )

    def _attempt_order(self) -> list[str | None]:
        with self._lock:
            sticky = self._sticky_ip
        order: list[str | None] = []
        if sticky is not _UNSET:
            order.append(None if sticky is None else str(sticky))
        for ip in self._fallback_ips:
            if ip not in order:
                order.append(ip)
        if None not in order:
            order.append(None)
        return order

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != TELEGRAM_API_HOST or not self._fallback_ips:
            return self._primary.handle_request(request)

        last_error: Exception | None = None
        failed_paths = 0
        for ip in self._attempt_order():
            candidate = request if ip is None else _rewrite_request_for_ip(request, ip)
            transport = self._primary if ip is None else self._get_fallback(ip)
            try:
                response = transport.handle_request(candidate)
                with self._lock:
                    changed = self._sticky_ip is _UNSET or self._sticky_ip != ip
                    self._sticky_ip = ip
                if changed and ip is not None:
                    log = logger.warning if failed_paths else logger.info
                    log("Using sticky IPv4 Telegram API path %s", ip)
                return response
            except Exception as exc:
                if not _is_retryable_connect_error(exc):
                    raise
                last_error = exc
                failed_paths += 1
                with self._lock:
                    if self._sticky_ip is not _UNSET and self._sticky_ip == ip:
                        self._sticky_ip = _UNSET
                if ip is None:
                    self._reset_primary(transport)
                else:
                    self._reset_fallback(ip)

        if last_error is None:
            raise RuntimeError("Telegram fallback paths exhausted without an error")
        raise last_error

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            primary = self._primary
            fallbacks = list(self._fallbacks.values())
            self._fallbacks.clear()
        try:
            primary.close()
        finally:
            for transport in fallbacks:
                try:
                    transport.close()
                except Exception:
                    logger.debug(
                        "Error closing Telegram fallback transport",
                        exc_info=True,
                    )


def build_telegram_http_client(
    *,
    base_url: str = "https://api.telegram.org",
    fallback_ips: Iterable[str] = (),
    discover: bool = False,
    proxy_url: str | None = None,
    environ: Mapping[str, str] | None = None,
    timeout: float = 35.0,
) -> httpx.Client:
    """Build a bounded Telegram HTTP client owned entirely by ZN."""
    env = environ if environ is not None else os.environ
    parsed = urlsplit(str(base_url or "https://api.telegram.org"))
    host = (parsed.hostname or "").lower()

    configured = list(fallback_ips)
    configured.extend(parse_fallback_ip_env(env.get("TELEGRAM_FALLBACK_IPS")))
    if discover and host == TELEGRAM_API_HOST:
        configured.extend(discover_fallback_ips())
    if host == TELEGRAM_API_HOST:
        configured.extend(SEED_FALLBACK_IPS)
    normalized = list(dict.fromkeys(_normalize_fallback_ips(configured)))

    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    if host == TELEGRAM_API_HOST and normalized:
        transport: httpx.BaseTransport = TelegramFallbackTransport(
            normalized,
            proxy_url=proxy_url,
            environ=env,
            limits=limits,
        )
    else:
        proxy = resolve_proxy_url(
            proxy_url,
            environ=env,
            target_hosts=(host,) if host else (),
        )
        kwargs: dict[str, Any] = {"limits": limits, "trust_env": False}
        if proxy:
            kwargs["proxy"] = proxy
        transport = httpx.HTTPTransport(**kwargs)

    return httpx.Client(
        transport=transport,
        timeout=max(1.0, float(timeout)),
        trust_env=False,
    )

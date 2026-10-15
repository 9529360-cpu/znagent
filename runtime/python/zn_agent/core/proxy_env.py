from __future__ import annotations

"""Proxy-environment tolerance for cognition HTTP clients.

A malformed proxy variable (``NO_PROXY`` / ``no_proxy`` / ``HTTP_PROXY`` /
``HTTPS_PROXY`` / ``ALL_PROXY`` and their lowercase twins) must never take
cognition offline: httpx parses the proxy environment at client construction
and raises ``InvalidURL`` / ``ValueError`` on entries it cannot parse (bad
ports, unclosed IPv6 brackets, bad schemes, over-long values, ...). The
OpenAI and Anthropic SDKs build their httpx clients the same way, so they
crash identically.

Valid proxy settings keep their exact semantics: the normal construction
path (``trust_env=True``) runs first and is untouched. Only when construction
actually raises do we fall back to a direct connection (``trust_env=False``)
and warn with the offending variable *names* -- never values, because proxy
URLs can embed credentials.
"""

import ipaddress
import logging
import os
from collections.abc import Mapping
from typing import Any, Callable, TypeVar

import httpx

_LOG = logging.getLogger(__name__)

PROXY_URL_ENV_KEYS = (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)
NO_PROXY_ENV_KEYS = ("NO_PROXY", "no_proxy")
PROXY_ENV_KEYS = PROXY_URL_ENV_KEYS + NO_PROXY_ENV_KEYS

_T = TypeVar("_T")

# httpx.InvalidURL inherits directly from Exception, NOT from ValueError --
# every parse-failure catch below must name it explicitly.
_PROXY_PARSE_ERRORS = (httpx.InvalidURL, ValueError, AttributeError, TypeError)


def _is_valid_proxy_url(value: str) -> bool:
    """Mirror httpx env handling: schemeless values get ``http://`` prepended."""
    candidate = value if "://" in value else f"http://{value}"
    try:
        httpx.Proxy(candidate)
    except _PROXY_PARSE_ERRORS:
        return False
    return True


def _is_valid_no_proxy_entry(entry: str) -> bool:
    """Validate one NO_PROXY entry the way httpx turns it into a mount key."""
    token = entry.strip()
    if not token:
        return True
    if token == "*":
        return True
    try:
        if "://" in token:
            httpx.URL(token)
            return True
        try:
            addr = ipaddress.ip_address(token)
        except ValueError:
            addr = None
        if addr is not None:
            if isinstance(addr, ipaddress.IPv6Address):
                httpx.URL(f"all://[{token}]")
            else:
                httpx.URL(f"all://{token}")
            return True
        if token.lower() == "localhost":
            httpx.URL("all://localhost")
            return True
        httpx.URL(f"all://*{token}")
        return True
    except _PROXY_PARSE_ERRORS:
        return False


def malformed_proxy_env_names(
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Return the names of set proxy env vars whose values httpx cannot parse.

    Only names are ever returned -- never values, because proxy URLs can
    embed credentials. An empty list means "no malformed proxy env found",
    not "httpx will not crash" (system proxy config is out of scope here).
    """
    env = environ if environ is not None else os.environ
    bad: list[str] = []
    for key in PROXY_URL_ENV_KEYS:
        raw = str(env.get(key) or "").strip()
        if raw and not _is_valid_proxy_url(raw):
            bad.append(key)
    for key in NO_PROXY_ENV_KEYS:
        raw = str(env.get(key) or "").strip()
        if raw and not all(
            _is_valid_no_proxy_entry(part) for part in raw.split(",")
        ):
            bad.append(key)
    return bad


def _warn_fallback(exc: BaseException) -> None:
    bad = malformed_proxy_env_names()
    if bad:
        detail = f"malformed proxy environment in: {', '.join(bad)}"
    else:
        detail = "malformed proxy configuration (variable could not be attributed)"
    _LOG.warning(
        "Ignoring proxy environment and continuing without proxy "
        "(%s): %s",
        detail,
        type(exc).__name__,
    )


def build_httpx_client(**kwargs: Any) -> httpx.Client:
    """Build an httpx.Client that never dies on malformed proxy env vars.

    Normal path first (full proxy semantics). On a construction-time proxy
    parse failure, retry once with ``trust_env=False`` (direct connection).
    Any other failure still raises from the retry.
    """
    try:
        return httpx.Client(**kwargs)
    except _PROXY_PARSE_ERRORS as exc:
        _warn_fallback(exc)
        kwargs["trust_env"] = False
        return httpx.Client(**kwargs)


def build_sdk_client(builder: Callable[..., _T], **kwargs: Any) -> _T:
    """Build an OpenAI/Anthropic SDK client that never dies on malformed proxy env.

    Same contract as :func:`build_httpx_client`: normal SDK construction
    first; on a construction-time proxy parse failure, retry once with an
    explicit direct-connection ``http_client``.
    """
    try:
        return builder(**kwargs)
    except _PROXY_PARSE_ERRORS as exc:
        _warn_fallback(exc)
        kwargs["http_client"] = httpx.Client(trust_env=False)
        return builder(**kwargs)


def normalize_proxy_url(value: str | None) -> str | None:
    """Normalize one proxy URL for explicit ``proxy=`` use, or drop it.

    Explicit ``proxy=`` requires a scheme (httpx crashes on schemeless values
    there, unlike env values where it prepends ``http://``). Returns the
    value with ``http://`` prepended when it had no scheme, the value
    unchanged when it already parses, or ``None`` when it cannot parse.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        httpx.Proxy(candidate)
    except _PROXY_PARSE_ERRORS:
        return None
    return candidate

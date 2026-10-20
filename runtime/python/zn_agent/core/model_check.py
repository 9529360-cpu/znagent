"""Local model-channel self check backing ``zn model check``.

Reads the locally configured cognitive routes with the same resolution the
resident uses (:func:`zn_agent.core.provider_bridge.build_zn_cognitive_resource_plan`)
and runs one bounded minimal probe per route. This is a local command, not a
resident RPC: it is meant to run before/without a running resident, e.g. as
the first verification step after deploying ZN on a machine.

Security: route metadata may carry materialized secrets (api_key). Only
``route_id`` / ``provider`` / ``model`` plus a scrubbed one-line failure
reason are ever reported; known secret values are redacted from every
message before it is surfaced.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field, replace
from typing import Any

from .config import load_zn_config, zn_config_path
from .models import Goal, ModelRoute
from .provider_bridge import build_zn_cognitive_resource_plan

__all__ = [
    "DEFAULT_PROBE_TIMEOUT_SECONDS",
    "PROBE_MAX_TOKENS",
    "PROBE_QUESTION",
    "ModelCheckReport",
    "RouteCheckResult",
    "check_model_routes",
    "format_no_config_hint",
    "scrub_secrets",
]


PROBE_QUESTION = "Reply with exactly one word: ok"
PROBE_MAX_TOKENS = 1
DEFAULT_PROBE_TIMEOUT_SECONDS = 25.0

_REDACTED = "***"
_MIN_SECRET_LENGTH = 8


def _one_line(text: str, *, limit: int = 200) -> str:
    """Collapse text to one printable line for terminal output."""

    collapsed = " ".join(str(text or "").split())
    collapsed = "".join(char if char.isprintable() else " " for char in collapsed)
    if len(collapsed) > limit:
        collapsed = collapsed[: max(0, limit - 1)].rstrip() + "…"
    return collapsed


def scrub_secrets(text: str, secrets: list[str]) -> str:
    """Redact every known secret value from ``text``, then collapse to one line."""

    redacted = str(text or "")
    for secret in secrets:
        value = str(secret or "")
        if len(value) >= _MIN_SECRET_LENGTH and value in redacted:
            redacted = redacted.replace(value, _REDACTED)
    return _one_line(redacted)


def _probe_secrets(routes: list[ModelRoute]) -> list[str]:
    """Collect the secret values that must never appear in check output."""

    secrets: list[str] = []
    for route in routes:
        metadata = route.metadata if isinstance(route.metadata, dict) else {}
        for key in ("api_key", "apiKey", "token", "access_token"):
            value = metadata.get(key)
            if isinstance(value, str) and len(value) >= _MIN_SECRET_LENGTH:
                secrets.append(value)
    return secrets


@dataclass(frozen=True)
class RouteCheckResult:
    route_id: str
    provider: str
    model: str
    reachable: bool
    latency_seconds: float | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "model": self.model,
            "reachable": self.reachable,
            "latency_seconds": self.latency_seconds,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelCheckReport:
    configured: bool
    config_error: str | None
    results: tuple[RouteCheckResult, ...] = field(default_factory=tuple)

    @property
    def reachable_count(self) -> int:
        return sum(1 for result in self.results if result.reachable)

    @property
    def any_reachable(self) -> bool:
        return self.reachable_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "config_error": self.config_error,
            "reachable_count": self.reachable_count,
            "route_count": len(self.results),
            "routes": [result.to_dict() for result in self.results],
        }


def _check_one_route(
    route: ModelRoute,
    worker: Any,
    *,
    secrets: list[str],
    timeout_seconds: float,
    question: str,
) -> RouteCheckResult:
    """Run one bounded probe against a single already-constructed worker."""

    started = time.monotonic()
    try:
        result = worker.run(
            Goal(goal_id=f"zn-model-check-{route.route_id}", task=question),
            "",
        )
    except Exception as exc:  # probe must never crash the CLI
        return RouteCheckResult(
            route_id=route.route_id,
            provider=route.provider,
            model=route.model,
            reachable=False,
            latency_seconds=time.monotonic() - started,
            detail=scrub_secrets(f"{type(exc).__name__}: {exc}", secrets),
        )
    latency = time.monotonic() - started
    if result is not None and getattr(result, "success", False):
        return RouteCheckResult(
            route_id=route.route_id,
            provider=route.provider,
            model=route.model,
            reachable=True,
            latency_seconds=latency,
            detail="ok",
        )
    error = getattr(result, "error", None) or "provider returned an unsuccessful result"
    return RouteCheckResult(
        route_id=route.route_id,
        provider=route.provider,
        model=route.model,
        reachable=False,
        latency_seconds=latency,
        detail=scrub_secrets(str(error), secrets),
    )


def check_model_routes(
    *,
    plan: Any | None = None,
    worker_factory: Any | None = None,
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    max_tokens: int = PROBE_MAX_TOKENS,
    question: str = PROBE_QUESTION,
) -> ModelCheckReport:
    """Probe every configured cognitive route with a minimal bounded request.

    ``plan`` / ``worker_factory`` are injectable seams so tests can run without
    network access. Each route is probed with ``max_tokens`` forced small, so
    the check costs almost nothing, and each probe is bounded by
    ``probe_timeout_seconds`` of wall-clock time.
    """

    if probe_timeout_seconds <= 0:
        raise ValueError("probe_timeout_seconds must be positive")
    if plan is None:
        plan = build_zn_cognitive_resource_plan(load_zn_config())
    if not getattr(plan, "available", False):
        config_error = getattr(plan, "error", None)
        return ModelCheckReport(
            configured=False,
            config_error=_one_line(config_error) if config_error else None,
            results=(),
        )

    routes = [
        route
        for route in (getattr(plan, "routes", None) or [])
        if str(getattr(route, "provider", "") or "") != "none"
    ]
    secrets = _probe_secrets(routes)
    factory = worker_factory if worker_factory is not None else plan.worker_factory

    workers: list[tuple[ModelRoute, Any]] = []
    construct_failures: list[RouteCheckResult] = []
    for route in routes:
        # Probe on a copy with a minimal token budget: the check must not
        # spend real generation budget or mutate the resident's routes.
        probe_route = replace(
            route,
            metadata={**(route.metadata if isinstance(route.metadata, dict) else {}),
                      "max_tokens": max_tokens},
        )
        try:
            workers.append((route, factory.create(probe_route)))
        except Exception as exc:  # construction failure is a route failure
            construct_failures.append(
                RouteCheckResult(
                    route_id=route.route_id,
                    provider=route.provider,
                    model=route.model,
                    reachable=False,
                    latency_seconds=None,
                    detail=scrub_secrets(f"{type(exc).__name__}: {exc}", secrets),
                )
            )

    probed: list[RouteCheckResult] = []
    # Daemon threads, not a ThreadPoolExecutor: a hung provider probe must be
    # abandoned after the timeout instead of blocking CLI exit on shutdown.
    pending: list[tuple[ModelRoute, dict[str, RouteCheckResult], threading.Thread]] = []
    for route, worker in workers:
        holder: dict[str, RouteCheckResult] = {}

        def _probe(
            route: ModelRoute = route,
            worker: Any = worker,
            holder: dict[str, RouteCheckResult] = holder,
        ) -> None:
            try:
                holder["result"] = _check_one_route(
                    route,
                    worker,
                    secrets=secrets,
                    timeout_seconds=probe_timeout_seconds,
                    question=question,
                )
            except Exception as exc:  # probe must never crash the CLI
                holder["result"] = RouteCheckResult(
                    route_id=route.route_id,
                    provider=route.provider,
                    model=route.model,
                    reachable=False,
                    latency_seconds=None,
                    detail=scrub_secrets(f"{type(exc).__name__}: {exc}", secrets),
                )

        thread = threading.Thread(
            target=_probe, name=f"zn-model-check-{route.route_id}", daemon=True
        )
        pending.append((route, holder, thread))
        thread.start()
    for route, holder, thread in pending:
        thread.join(timeout=probe_timeout_seconds)
        result = holder.get("result")
        if result is None:
            probed.append(
                RouteCheckResult(
                    route_id=route.route_id,
                    provider=route.provider,
                    model=route.model,
                    reachable=False,
                    latency_seconds=None,
                    detail=f"probe timed out after {probe_timeout_seconds:g}s",
                )
            )
        else:
            probed.append(result)

    by_route_id = {result.route_id: result for result in probed}
    ordered = [by_route_id[route.route_id] for route, _ in workers]
    return ModelCheckReport(
        configured=True,
        config_error=None,
        results=tuple(construct_failures + ordered),
    )


def format_no_config_hint() -> str:
    """Actionable hint printed when no model routes are configured."""

    config_path = zn_config_path()
    return (
        "no model routes configured.\n"
        f"ZN config file: {config_path}\n"
        "Add a `model` section, for example:\n"
        "  model:\n"
        "    provider: openai        # anthropic, gemini, or another OpenAI-compatible provider\n"
        "    default: gpt-4o-mini\n"
        "    base_url: https://api.openai.com/v1\n"
        "Then make the credential available (provider env var such as\n"
        "OPENAI_API_KEY, or the OS keyring via the resident provider settings)\n"
        "and rerun `zn model check`."
    )

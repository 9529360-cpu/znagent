from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .home import get_zn_home
from .models import ModelRoute
from .runtime import ZNKernelRuntime
from .store import KernelStore
from .worker import LegacyAIAgentWorkerFactory, UnavailableModelWorkerFactory


RuntimeResolver = Callable[..., dict[str, Any]]


def route_from_spec(spec: dict[str, Any], index: int = 0) -> ModelRoute:
    provider = str(spec.get("provider") or "auto").strip() or "auto"
    model = str(spec.get("model") or "").strip()
    if not model:
        raise ValueError(f"zn_kernel.routes[{index}] is missing model")
    route_id = str(spec.get("id") or spec.get("route_id") or f"route-{index}").strip()
    capabilities = spec.get("capabilities") or {"general": 0.7}
    if not isinstance(capabilities, dict):
        raise ValueError(f"zn_kernel.routes[{index}].capabilities must be a mapping")
    normalized_caps = {
        str(name): max(0.0, min(1.0, float(score)))
        for name, score in capabilities.items()
    }
    return ModelRoute(
        route_id=route_id,
        provider=provider,
        model=model,
        capabilities=normalized_caps,
        reliability=max(0.0, min(1.0, float(spec.get("reliability", 0.8)))),
        cost_weight=max(0.0, min(1.0, float(spec.get("cost_weight", 0.5)))),
        latency_weight=max(0.0, min(1.0, float(spec.get("latency_weight", 0.5)))),
        metadata={
            key: spec[key]
            for key in ("base_url", "api_key", "api_mode")
            if spec.get(key) is not None
        },
    )


def resolve_model_routes(
    specs: Iterable[dict[str, Any]],
    *,
    resolver: RuntimeResolver,
) -> list[ModelRoute]:
    resolved_routes: list[ModelRoute] = []
    for index, spec in enumerate(specs):
        route = route_from_spec(spec, index)
        runtime = resolver(
            requested=route.provider,
            target_model=route.model,
            explicit_api_key=route.metadata.get("api_key"),
            explicit_base_url=route.metadata.get("base_url"),
        )
        route.provider = str(runtime.get("provider") or route.provider)
        route.model = str(runtime.get("model") or route.model)
        for key in (
            "api_key",
            "base_url",
            "api_mode",
            "requested_provider",
            "credential_pool",
        ):
            if runtime.get(key) is not None:
                route.metadata[key] = runtime[key]
        resolved_routes.append(route)
    return resolved_routes


def _current_model_spec(config: dict[str, Any]) -> dict[str, Any] | None:
    model_cfg = config.get("model") or {}
    if isinstance(model_cfg, str):
        model = model_cfg.strip()
        provider = "auto"
    elif isinstance(model_cfg, dict):
        raw_model = model_cfg.get("default") or model_cfg.get("model") or ""
        if isinstance(raw_model, dict):
            raw_model = raw_model.get("model") or raw_model.get("id") or ""
        model = str(raw_model or "").strip()
        provider = str(model_cfg.get("provider") or "auto").strip() or "auto"
    else:
        model = ""
        provider = "auto"
    if not model:
        return None
    return {
        "id": "default",
        "provider": provider,
        "model": model,
        "capabilities": {"general": 0.75},
        "reliability": 0.8,
        "cost_weight": 0.5,
        "latency_weight": 0.5,
    }


def build_runtime_from_existing_stack(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
    agent_kwargs: dict[str, Any] | None = None,
    agent_builder: Callable[..., Any] | None = None,
    runtime_resolver: RuntimeResolver | None = None,
) -> ZNKernelRuntime:
    """Create a ZN Kernel while reusing the mature provider/tool stack.

    A configured model is optional. Without one, the resident still boots and
    System 1 remains fully available; only tasks requiring System 2 fail with a
    precise "model unavailable" result.
    """
    if config is None:
        from hermes_cli.config import load_config

        config = load_config()

    kernel_cfg = config.get("zn_kernel") or {}
    if not isinstance(kernel_cfg, dict):
        raise ValueError("zn_kernel config must be a mapping")
    route_specs = kernel_cfg.get("routes") or []
    if not isinstance(route_specs, list):
        raise ValueError("zn_kernel.routes must be a list")

    model_available = True
    if not route_specs:
        current = _current_model_spec(config)
        if current is None:
            model_available = False
            route_specs = []
        else:
            route_specs = [current]

    if model_available:
        if runtime_resolver is None:
            from hermes_cli.runtime_provider import resolve_runtime_provider

            runtime_resolver = resolve_runtime_provider
        routes = resolve_model_routes(route_specs, resolver=runtime_resolver)
    else:
        routes = [
            ModelRoute(
                route_id="system2-unavailable",
                provider="none",
                model="none",
                capabilities={"general": 0.0},
                reliability=1.0,
                cost_weight=0.0,
                latency_weight=0.0,
                metadata={"model_available": False},
            )
        ]

    if store_path is None:
        store_path = get_zn_home() / "kernel" / "kernel.db"

    if model_available:
        worker_defaults = dict(agent_kwargs or {})
        worker_defaults.setdefault("quiet_mode", True)
        worker_defaults.setdefault("platform", "cli")
        factory = LegacyAIAgentWorkerFactory(
            agent_kwargs=worker_defaults,
            agent_builder=agent_builder,
        )
    else:
        factory = UnavailableModelWorkerFactory()

    return ZNKernelRuntime(
        store=KernelStore(store_path),
        routes=routes,
        worker_factory=factory,
        max_attempts=max(1, int(kernel_cfg.get("max_attempts", 2))),
    )


def build_resident_runtime_from_existing_stack(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
    agent_kwargs: dict[str, Any] | None = None,
    agent_builder: Callable[..., Any] | None = None,
    runtime_resolver: RuntimeResolver | None = None,
):
    """Build the resident ZN runtime while reusing mature provider/tool plumbing."""
    from .budget import CognitiveBudgetManager
    from .resident import ZNResidentRuntime

    effective_config = config
    if effective_config is None:
        from hermes_cli.config import load_config

        effective_config = load_config()

    kernel = build_runtime_from_existing_stack(
        config=effective_config,
        store_path=store_path,
        agent_kwargs=agent_kwargs,
        agent_builder=agent_builder,
        runtime_resolver=runtime_resolver,
    )
    resident_cfg = effective_config.get("zn_resident") or {}
    if not isinstance(resident_cfg, dict):
        raise ValueError("zn_resident config must be a mapping")
    budget = CognitiveBudgetManager(
        normal_model_calls=max(1, int(resident_cfg.get("normal_model_calls", 1))),
        high_risk_model_calls=max(1, int(resident_cfg.get("high_risk_model_calls", 2))),
        high_risk_threshold=max(
            0.0, min(1.0, float(resident_cfg.get("high_risk_threshold", 0.8)))
        ),
    )
    return ZNResidentRuntime(kernel=kernel, budget=budget)

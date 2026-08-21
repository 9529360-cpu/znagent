from __future__ import annotations

"""ZN runtime construction and temporary legacy compatibility seams.

The public function names are retained while callers migrate, but the default
resident path is now ZN-owned: ZN config + ZN route resolution + ZN cognitive
resources.  Legacy provider/AIAgent construction is used only when a caller
explicitly injects a legacy resolver/builder/agent kwargs.
"""

from pathlib import Path
from typing import Any, Callable, Iterable

from .cognitive_resource import (
    CognitiveResourceWorkerFactory,
    resolve_openai_compatible_route,
)
from .config import load_zn_config
from .home import get_zn_home
from .models import ModelRoute
from .runtime import ZNKernelRuntime
from .store import KernelStore
from .worker import LegacyAIAgentWorkerFactory, UnavailableModelWorkerFactory


RuntimeResolver = Callable[..., dict[str, Any]]


_ROUTE_METADATA_KEYS = (
    "base_url",
    "api_key",
    "api_mode",
    "temperature",
    "max_tokens",
    "top_p",
    "seed",
    "timeout",
    "extra_body",
)


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
            for key in _ROUTE_METADATA_KEYS
            if spec.get(key) is not None
        },
    )


def resolve_model_routes(
    specs: Iterable[dict[str, Any]],
    *,
    resolver: RuntimeResolver,
) -> list[ModelRoute]:
    """Temporary adapter for callers that explicitly request the old resolver."""
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


def resolve_zn_routes(specs: Iterable[dict[str, Any]]) -> list[ModelRoute]:
    """Resolve configured routes entirely inside ZN's resource layer."""
    return [
        resolve_openai_compatible_route(route_from_spec(spec, index))
        for index, spec in enumerate(specs)
    ]


def _current_model_spec(config: dict[str, Any]) -> dict[str, Any] | None:
    model_cfg = config.get("model") or {}
    if isinstance(model_cfg, str):
        model = model_cfg.strip()
        provider = "auto"
        metadata: dict[str, Any] = {}
    elif isinstance(model_cfg, dict):
        raw_model = model_cfg.get("default") or model_cfg.get("model") or ""
        nested: dict[str, Any] = {}
        if isinstance(raw_model, dict):
            nested = raw_model
            raw_model = raw_model.get("model") or raw_model.get("id") or ""
        model = str(raw_model or "").strip()
        provider = str(
            nested.get("provider") or model_cfg.get("provider") or "auto"
        ).strip() or "auto"
        metadata = {
            key: nested.get(key, model_cfg.get(key))
            for key in _ROUTE_METADATA_KEYS
            if nested.get(key, model_cfg.get(key)) is not None
        }
    else:
        model = ""
        provider = "auto"
        metadata = {}
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
        **metadata,
    }


def build_runtime_from_existing_stack(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
    agent_kwargs: dict[str, Any] | None = None,
    agent_builder: Callable[..., Any] | None = None,
    runtime_resolver: RuntimeResolver | None = None,
) -> ZNKernelRuntime:
    """Build ZN runtime; legacy plumbing is now explicit opt-in only.

    The compatibility name remains while call sites migrate.  With no injected
    legacy resolver/builder/agent kwargs this function loads ZN's own config,
    resolves OpenAI-compatible resources in ZN, and never imports hermes_cli or
    constructs run_agent.AIAgent.
    """
    if config is None:
        config = load_zn_config()

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

    legacy_requested = (
        runtime_resolver is not None
        or agent_builder is not None
        or agent_kwargs is not None
    )

    if model_available:
        if runtime_resolver is not None:
            routes = resolve_model_routes(route_specs, resolver=runtime_resolver)
        else:
            routes = resolve_zn_routes(route_specs)
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

    if not model_available:
        factory = UnavailableModelWorkerFactory()
    elif legacy_requested:
        worker_defaults = dict(agent_kwargs or {})
        worker_defaults.setdefault("quiet_mode", True)
        worker_defaults.setdefault("platform", "cli")
        factory = LegacyAIAgentWorkerFactory(
            agent_kwargs=worker_defaults,
            agent_builder=agent_builder,
        )
    else:
        factory = CognitiveResourceWorkerFactory()

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
    """Build the resident with ZN-owned resources by default."""
    from .budget import CognitiveBudgetManager
    from .world_closed_loop import WorldAwareTransferResidentRuntime

    effective_config = config if config is not None else load_zn_config()

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
    return WorldAwareTransferResidentRuntime(kernel=kernel, budget=budget)

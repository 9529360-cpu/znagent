from __future__ import annotations

"""ZN-owned resident runtime construction.

Runtime ownership ends here: ZN config selects ZN cognitive resources and the
resident is assembled without importing another product's CLI, provider
resolver, agent object, or session lifecycle.
"""

from pathlib import Path
from typing import Any, Iterable

from .cognitive_factory import (
    ZNCognitiveResourceWorkerFactory,
    resolve_zn_cognitive_route,
)
from .config import load_zn_config
from .home import get_zn_home
from .models import ModelRoute
from .runtime import ZNKernelRuntime
from .store import KernelStore
from .worker import UnavailableModelWorkerFactory


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
    "thinking",
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


def resolve_zn_routes(specs: Iterable[dict[str, Any]]) -> list[ModelRoute]:
    return [
        resolve_zn_cognitive_route(route_from_spec(spec, index))
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


def build_runtime(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
) -> ZNKernelRuntime:
    """Build the ZN kernel from only ZN-owned configuration and resources."""
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
        else:
            route_specs = [current]

    if model_available:
        routes = resolve_zn_routes(route_specs)
        factory = ZNCognitiveResourceWorkerFactory()
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
        factory = UnavailableModelWorkerFactory()

    if store_path is None:
        store_path = get_zn_home() / "kernel" / "kernel.db"

    return ZNKernelRuntime(
        store=KernelStore(store_path),
        routes=routes,
        worker_factory=factory,
        max_attempts=max(1, int(kernel_cfg.get("max_attempts", 2))),
    )


def build_resident_runtime(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
):
    """Build the resident organism around the ZN-owned kernel."""
    from .budget import CognitiveBudgetManager
    from .world_closed_loop import WorldAwareTransferResidentRuntime

    effective_config = config if config is not None else load_zn_config()
    kernel = build_runtime(config=effective_config, store_path=store_path)
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


# Transitional source-level aliases only. They preserve existing ZN callers
# while naming migration happens, but no longer expose or construct a legacy
# runtime path.
build_runtime_from_existing_stack = build_runtime
build_resident_runtime_from_existing_stack = build_resident_runtime

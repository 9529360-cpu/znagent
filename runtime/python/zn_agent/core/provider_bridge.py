from __future__ import annotations

"""ZN-owned resident runtime construction.

Runtime ownership ends here: ZN config selects ZN cognitive resources and the
resident is assembled without importing another product's CLI, provider
resolver, agent object, or session lifecycle.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .cognitive_factory import (
    ZNCognitiveResourceWorkerFactory,
    resolve_zn_cognitive_route,
)
from .config import load_zn_config
from .credentials import (
    CredentialStore,
    materialize_zn_credentials,
)
from .home import get_zn_home
from .models import ModelRoute
from .runtime import ZNKernelRuntime
from .store import KernelStore
from .worker import UnavailableModelWorkerFactory, WorkerFactory


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


@dataclass(slots=True)
class ZNCognitiveResourcePlan:
    routes: list[ModelRoute]
    worker_factory: WorkerFactory
    max_attempts: int
    available: bool
    error: str | None = None


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


def _unavailable_plan(*, max_attempts: int, error: str | None = None) -> ZNCognitiveResourcePlan:
    metadata: dict[str, Any] = {"model_available": False}
    if error:
        metadata["configuration_error"] = error
    return ZNCognitiveResourcePlan(
        routes=[
            ModelRoute(
                route_id="system2-unavailable",
                provider="none",
                model="none",
                capabilities={"general": 0.0},
                reliability=1.0,
                cost_weight=0.0,
                latency_weight=0.0,
                metadata=metadata,
            )
        ],
        worker_factory=UnavailableModelWorkerFactory(),
        max_attempts=max_attempts,
        available=False,
        error=error,
    )


def build_zn_cognitive_resource_plan(
    config: dict[str, Any],
    *,
    credential_store: CredentialStore | None = None,
) -> ZNCognitiveResourcePlan:
    """Resolve external cognition without making its failure a resident failure."""

    kernel_cfg = config.get("zn_kernel") or {}
    if not isinstance(kernel_cfg, dict):
        raise ValueError("zn_kernel config must be a mapping")
    route_specs = kernel_cfg.get("routes") or []
    if not isinstance(route_specs, list):
        raise ValueError("zn_kernel.routes must be a list")
    max_attempts = max(1, int(kernel_cfg.get("max_attempts", 2)))

    runtime_config = materialize_zn_credentials(config, store=credential_store)
    runtime_kernel_cfg = runtime_config.get("zn_kernel") or {}
    runtime_route_specs = runtime_kernel_cfg.get("routes") or [] if isinstance(runtime_kernel_cfg, dict) else []
    if not runtime_route_specs:
        current = _current_model_spec(runtime_config)
        if current is None:
            return _unavailable_plan(max_attempts=max_attempts)
        runtime_route_specs = [current]

    try:
        routes = resolve_zn_routes(runtime_route_specs)
    except (ValueError, RuntimeError) as exc:
        return _unavailable_plan(
            max_attempts=max_attempts,
            error=f"{type(exc).__name__}: {exc}",
        )

    return ZNCognitiveResourcePlan(
        routes=routes,
        worker_factory=ZNCognitiveResourceWorkerFactory(),
        max_attempts=max_attempts,
        available=True,
    )


def apply_zn_cognitive_config(
    runtime: ZNKernelRuntime,
    config: dict[str, Any],
    *,
    credential_store: CredentialStore | None = None,
) -> ZNCognitiveResourcePlan:
    """Hot-apply provider resources while preserving the same kernel identity/store."""

    plan = build_zn_cognitive_resource_plan(config, credential_store=credential_store)
    observer = getattr(runtime, "resource_health_observer", None)
    setter = getattr(plan.worker_factory, "set_health_observer", None)
    if observer is not None and callable(setter):
        try:
            setter(observer)
        except Exception:
            # Health observation is secondary. A replacement provider plan must
            # remain hot-applicable even if observer binding itself is broken.
            pass
    runtime.reconfigure_resources(
        routes=plan.routes,
        worker_factory=plan.worker_factory,
        max_attempts=plan.max_attempts,
        resource_status={"available": plan.available, "error": plan.error},
    )
    return plan


def build_runtime(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
    credential_store: CredentialStore | None = None,
) -> ZNKernelRuntime:
    """Build the ZN kernel from only ZN-owned configuration and resources."""
    if config is None:
        config = load_zn_config()

    plan = build_zn_cognitive_resource_plan(config, credential_store=credential_store)

    if store_path is None:
        store_path = get_zn_home() / "kernel" / "kernel.db"

    return ZNKernelRuntime(
        store=KernelStore(store_path),
        routes=plan.routes,
        worker_factory=plan.worker_factory,
        max_attempts=plan.max_attempts,
        resource_status={"available": plan.available, "error": plan.error},
    )


def build_resident_runtime(
    *,
    config: dict[str, Any] | None = None,
    store_path: str | Path | None = None,
    credential_store: CredentialStore | None = None,
):
    """Build the normal product Resident around the ZN-owned kernel."""
    from .budget import CognitiveBudgetManager
    from .natural_file_work_resident import NaturalFileWorkResidentRuntime

    effective_config = config if config is not None else load_zn_config()
    resident_cfg = effective_config.get("zn_resident") or {}
    if not isinstance(resident_cfg, dict):
        raise ValueError("zn_resident config must be a mapping")

    kernel = build_runtime(
        config=effective_config,
        store_path=store_path,
        credential_store=credential_store,
    )
    budget = CognitiveBudgetManager(
        normal_model_calls=max(1, int(resident_cfg.get("normal_model_calls", 1))),
        high_risk_model_calls=max(1, int(resident_cfg.get("high_risk_model_calls", 2))),
        high_risk_threshold=max(
            0.0, min(1.0, float(resident_cfg.get("high_risk_threshold", 0.8)))
        ),
    )

    return NaturalFileWorkResidentRuntime(
        kernel=kernel,
        budget=budget,
    )


build_runtime_from_existing_stack = build_runtime
build_resident_runtime_from_existing_stack = build_resident_runtime

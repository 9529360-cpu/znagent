from __future__ import annotations

"""Read-only discovery for local inference runtimes already supported by ZN."""

import ipaddress
import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .device_capability_graph import DeviceCapabilityGraph
from .models import ModelRoute, utc_now


ModelsProbe = Callable[[str, str], tuple[str, ...] | None]


def _is_loopback_base_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.casefold()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


_RUNTIME_SPECS = (
    ("ollama", "http://127.0.0.1:11434/v1", ("Ollama",), ("ollama.exe",)),
    (
        "lmstudio",
        "http://127.0.0.1:1234/v1",
        ("LM Studio",),
        ("lm studio.exe", "lmstudio.exe"),
    ),
    ("vllm", "http://127.0.0.1:8000/v1", (), ()),
)


@dataclass(frozen=True, slots=True)
class LocalInferenceRuntimeObservation:
    provider: str
    base_url: str
    endpoint_reachable: bool
    model_ids: tuple[str, ...]
    application_installed: bool
    process_running: bool
    reason: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class LocalInferenceHardwareObservation:
    ram_total_bytes: int
    ram_available_bytes: int
    gpu_names: tuple[str, ...]
    ac_status: str
    battery_saver: bool | None
    observed_at: str


@dataclass(frozen=True, slots=True)
class LocalInferenceSnapshot:
    runtimes: tuple[LocalInferenceRuntimeObservation, ...]
    hardware: LocalInferenceHardwareObservation
    observed_at: str

    @property
    def usable_providers(self) -> tuple[str, ...]:
        return tuple(
            runtime.provider
            for runtime in self.runtimes
            if runtime.endpoint_reachable and bool(runtime.model_ids)
        )


class LocalInferenceRuntimeDiscovery:
    """Observe loopback runtimes and machine capacity without invoking a model."""

    def __init__(
        self,
        device_capabilities: DeviceCapabilityGraph,
        *,
        models_probe: ModelsProbe | None = None,
    ) -> None:
        self.device_capabilities = device_capabilities
        self._models_probe = models_probe or _probe_openai_models

    def route_health(self, route: ModelRoute) -> dict[str, Any] | None:
        """Return fresh availability for configured loopback local-model routes."""

        provider = str(route.provider or "").strip().lower()
        spec = next(
            (item for item in _RUNTIME_SPECS if item[0] == provider),
            None,
        )
        if spec is None:
            return None
        configured_base = str(
            (route.metadata or {}).get("base_url") or spec[1]
        ).strip()
        if not _is_loopback_base_url(configured_base):
            return None

        try:
            models = self._models_probe(provider, configured_base)
        except Exception:
            models = None
        model_ids = tuple(models or ())
        endpoint_reachable = models is not None
        model = str(route.model or "").strip()
        model_present = bool(model and model in model_ids)
        available = bool(endpoint_reachable and model_present)
        return {
            "available": available,
            "queryable": available,
            "runtime_observed": True,
            "runtime_provider": provider,
            "runtime_endpoint_reachable": endpoint_reachable,
            "runtime_model_present": model_present,
            "runtime_model_count": len(model_ids),
            "observed_at": utc_now(),
        }

    def snapshot(self) -> LocalInferenceSnapshot:
        graph = self.device_capabilities
        applications = graph.installed_applications()
        processes = graph.running_processes()
        hardware = graph.hardware()
        companion = graph.companion_context()
        observed_at = utc_now()

        runtimes: list[LocalInferenceRuntimeObservation] = []
        for provider, base_url, app_names, process_names in _RUNTIME_SPECS:
            app_ids = {
                application.app_id
                for application in applications
                if application.canonical_name in app_names
            }
            installed = bool(app_ids)
            process_running = any(
                process.resolved_app_id in app_ids
                or process.process_name.casefold()
                in {name.casefold() for name in process_names}
                for process in processes
            )
            try:
                models = self._models_probe(provider, base_url)
            except Exception:
                models = None
            reachable = models is not None
            model_ids = tuple(models or ())
            if reachable and model_ids:
                reason = "local inference endpoint is reachable with models"
            elif reachable:
                reason = "local inference endpoint is reachable but exposes no model"
            elif process_running:
                reason = "runtime process is observed but its local API is unreachable"
            elif installed:
                reason = "runtime is installed but its local API is not running"
            else:
                reason = "runtime is not currently discoverable"
            runtimes.append(
                LocalInferenceRuntimeObservation(
                    provider=provider,
                    base_url=base_url,
                    endpoint_reachable=reachable,
                    model_ids=model_ids,
                    application_installed=installed,
                    process_running=process_running,
                    reason=reason,
                    observed_at=observed_at,
                )
            )
        return LocalInferenceSnapshot(
            runtimes=tuple(runtimes),
            hardware=LocalInferenceHardwareObservation(
                ram_total_bytes=int(hardware.ram_total_bytes),
                ram_available_bytes=int(hardware.ram_available_bytes),
                gpu_names=tuple(gpu.name for gpu in hardware.gpus if gpu.name),
                ac_status=str(companion.power.ac_status),
                battery_saver=companion.power.battery_saver,
                observed_at=observed_at,
            ),
            observed_at=observed_at,
        )


def _probe_openai_models(
    _provider: str,
    base_url: str,
    *,
    timeout_seconds: float = 0.35,
) -> tuple[str, ...] | None:
    """Return bounded model ids, or None when the loopback server is unavailable."""

    if not _is_loopback_base_url(base_url):
        return None
    endpoint = str(base_url).rstrip("/") + "/models"
    request = Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=max(0.05, float(timeout_seconds))) as response:
            raw = response.read(1024 * 1024 + 1)
    except Exception:
        return None
    if len(raw) > 1024 * 1024:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    model_ids: list[str] = []
    for item in rows[:128]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or len(model_id) > 256:
            continue
        model_ids.append(model_id)
    return tuple(dict.fromkeys(model_ids))

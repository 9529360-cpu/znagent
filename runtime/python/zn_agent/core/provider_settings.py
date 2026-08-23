from __future__ import annotations

"""Resident-owned provider settings and secure credential editing."""

import copy
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .config import load_zn_config, save_zn_config, zn_config_path
from .credentials import (
    CredentialStore,
    CredentialStoreUnavailable,
    KeyringCredentialStore,
    provider_credential_env_names,
    provider_credential_reference,
)
from .provider_bridge import apply_zn_cognitive_config


_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ProviderSettingsService:
    """Edit provider resources without transferring ownership to Electron.

    Non-secret settings persist in ZN config. UI-entered credentials go only to
    the resident secure store; RPC snapshots expose presence/source metadata but
    never return secret values. Updating resources hot-applies a new cognition
    plan to the existing kernel while preserving resident identity and memory.
    """

    def __init__(
        self,
        resident,
        *,
        config_path: str | Path | None = None,
        credential_store: CredentialStore | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.resident = resident
        self.config_path = Path(config_path).expanduser() if config_path is not None else zn_config_path()
        self.credentials = credential_store or KeyringCredentialStore()
        self.environ = environ if environ is not None else os.environ

    def snapshot(self) -> dict[str, Any]:
        config = load_zn_config(self.config_path)
        return self._snapshot_from_config(config)

    def update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        config = load_zn_config(self.config_path)
        if self._has_advanced_routes(config):
            raise ValueError(
                "provider editor cannot replace advanced zn_kernel.routes; edit those routes explicitly"
            )

        existing_model = config.get("model")
        if isinstance(existing_model, dict) and isinstance(existing_model.get("default"), dict):
            raise ValueError(
                "provider editor cannot replace nested advanced model configuration"
            )
        model_cfg = dict(existing_model) if isinstance(existing_model, dict) else {}
        previous_provider = str(model_cfg.get("provider") or "auto").strip().lower() or "auto"
        previous_reference = str(model_cfg.get("credential_ref") or "").strip()

        provider = str(params.get("provider") or previous_provider or "auto").strip().lower()
        if not _PROVIDER_RE.fullmatch(provider):
            raise ValueError("provider must contain only letters, numbers, dot, underscore or dash")
        model = str(params.get("model") or model_cfg.get("default") or model_cfg.get("model") or "").strip()
        if not model:
            raise ValueError("model is required")

        base_url = str(params.get("base_url") or params.get("baseUrl") or "").strip()
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("base URL must be an http(s) URL with a hostname")

        api_key_value = params.get("api_key") if "api_key" in params else params.get("apiKey")
        api_key = str(api_key_value or "").strip() if api_key_value is not None else ""
        clear_credential = bool(params.get("clear_credential") or params.get("clearCredential"))
        if api_key and clear_credential:
            raise ValueError("cannot set and clear a provider credential in the same update")

        provider_changed = provider != previous_provider
        model_cfg["provider"] = provider
        model_cfg["default"] = model
        model_cfg.pop("model", None)
        if base_url:
            model_cfg["base_url"] = base_url
        else:
            model_cfg.pop("base_url", None)

        if provider_changed:
            # Never silently apply the old provider's key to a different provider.
            model_cfg.pop("credential_ref", None)
            model_cfg.pop("api_key", None)

        if clear_credential:
            reference = previous_reference if not provider_changed else ""
            if reference:
                self.credentials.delete(reference)
            model_cfg.pop("credential_ref", None)
            model_cfg.pop("api_key", None)
        elif api_key:
            reference = provider_credential_reference(provider)
            self.credentials.set(reference, api_key)
            model_cfg["credential_ref"] = reference
            # UI-written provider config never persists the raw secret.
            model_cfg.pop("api_key", None)
        elif not provider_changed and previous_reference:
            model_cfg["credential_ref"] = previous_reference

        updated = copy.deepcopy(config)
        updated["model"] = model_cfg
        save_zn_config(updated, self.config_path)
        apply_zn_cognitive_config(
            self.resident.kernel,
            updated,
            credential_store=self.credentials,
        )
        return self._snapshot_from_config(updated)

    def _snapshot_from_config(self, config: dict[str, Any]) -> dict[str, Any]:
        advanced_routes = self._has_advanced_routes(config)
        model_cfg = config.get("model")
        nested_advanced = isinstance(model_cfg, dict) and isinstance(model_cfg.get("default"), dict)
        editable = not advanced_routes and not nested_advanced

        provider = "auto"
        model = ""
        base_url = ""
        credential_reference = ""
        inline_credential = False
        if isinstance(model_cfg, str):
            model = model_cfg.strip()
        elif isinstance(model_cfg, dict) and not nested_advanced:
            provider = str(model_cfg.get("provider") or "auto").strip().lower() or "auto"
            model = str(model_cfg.get("default") or model_cfg.get("model") or "").strip()
            base_url = str(model_cfg.get("base_url") or "").strip()
            credential_reference = str(model_cfg.get("credential_ref") or "").strip()
            inline_credential = bool(str(model_cfg.get("api_key") or "").strip())

        secure_status = self.credentials.status()
        secure_configured = False
        if credential_reference and secure_status.available:
            try:
                secure_configured = bool(self.credentials.get(credential_reference))
            except CredentialStoreUnavailable:
                secure_configured = False

        env_names = provider_credential_env_names(provider)
        env_name = next(
            (name for name in env_names if str(self.environ.get(name) or "").strip()),
            None,
        )
        if inline_credential:
            credential_source = "config"
        elif secure_configured:
            credential_source = "secure_store"
        elif credential_reference and not secure_status.available:
            credential_source = "secure_store_unavailable"
        elif env_name:
            credential_source = "environment"
        else:
            credential_source = "none"

        routes = []
        for route in getattr(self.resident.kernel.router, "routes", ()):
            if str(route.provider) == "none":
                continue
            routes.append(
                {
                    "id": route.route_id,
                    "provider": route.provider,
                    "model": route.model,
                }
            )

        resource_status = dict(getattr(self.resident.kernel, "resource_status", {}) or {})
        result: dict[str, Any] = {
            "mode": "routes" if advanced_routes else "default",
            "editable": editable,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "credential": {
                "configured": credential_source in {"config", "secure_store", "environment"},
                "source": credential_source,
                "environment_name": env_name,
                "secure_store": {
                    "available": secure_status.available,
                    "backend": secure_status.backend,
                    "error": secure_status.error,
                },
            },
            "active_routes": routes,
            "cognition_available": bool(resource_status.get("available", bool(routes))),
            "configuration_error": resource_status.get("error"),
        }
        if advanced_routes:
            kernel_cfg = config.get("zn_kernel")
            route_values = kernel_cfg.get("routes") if isinstance(kernel_cfg, dict) else []
            result["route_count"] = len(route_values) if isinstance(route_values, list) else 0
        if nested_advanced:
            result["mode"] = "nested_model"
        return result

    @staticmethod
    def _has_advanced_routes(config: Mapping[str, Any]) -> bool:
        kernel_cfg = config.get("zn_kernel")
        if not isinstance(kernel_cfg, dict):
            return False
        routes = kernel_cfg.get("routes")
        return isinstance(routes, list) and len(routes) > 0

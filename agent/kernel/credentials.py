from __future__ import annotations

"""Resident-owned secure credential references for external resources.

The desktop may collect a credential from the user, but it does not own or
persist that secret. ZN's long-lived resident resolves a stable reference through
an OS credential backend and materializes the secret only into transient runtime
configuration immediately before a provider route is constructed.
"""

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


_CREDENTIAL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_PROVIDER_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "xai": ("XAI_API_KEY",),
}


class CredentialStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialStoreStatus:
    available: bool
    backend: str
    error: str | None = None


class CredentialStore(Protocol):
    def status(self) -> CredentialStoreStatus: ...

    def get(self, reference: str) -> str | None: ...

    def set(self, reference: str, secret: str) -> None: ...

    def delete(self, reference: str) -> None: ...


def normalize_credential_reference(reference: str) -> str:
    value = str(reference or "").strip()
    if not value or not _CREDENTIAL_REF_RE.fullmatch(value):
        raise ValueError("invalid ZN credential reference")
    return value


def provider_credential_reference(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", normalized):
        raise ValueError("invalid provider name for credential reference")
    return f"provider:{normalized}"


def provider_credential_env_names(provider: str) -> tuple[str, ...]:
    return _PROVIDER_ENV_NAMES.get(str(provider or "").strip().lower(), ())


class KeyringCredentialStore:
    """Use the host OS credential backend through Python keyring.

    No plaintext file fallback is provided. If a usable OS backend is not
    available, callers may keep using provider-standard environment variables or
    surface the unavailable secure-store state to the user.
    """

    def __init__(self, *, service_name: str = "znagent"):
        self.service_name = str(service_name or "znagent").strip() or "znagent"

    @staticmethod
    def _module():
        try:
            import keyring
        except ImportError as exc:
            raise CredentialStoreUnavailable(
                "secure credential backend is unavailable in this runtime"
            ) from exc
        return keyring

    def status(self) -> CredentialStoreStatus:
        try:
            keyring = self._module()
            backend = keyring.get_keyring()
            name = f"{type(backend).__module__}.{type(backend).__name__}"
            try:
                priority = float(getattr(backend, "priority", 0.0))
            except Exception:
                priority = 0.0
            if priority <= 0:
                return CredentialStoreStatus(
                    available=False,
                    backend=name,
                    error="no usable OS credential backend is available",
                )
            return CredentialStoreStatus(available=True, backend=name)
        except CredentialStoreUnavailable as exc:
            return CredentialStoreStatus(
                available=False,
                backend="unavailable",
                error=str(exc),
            )
        except Exception as exc:
            return CredentialStoreStatus(
                available=False,
                backend="unavailable",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _require(self):
        status = self.status()
        if not status.available:
            raise CredentialStoreUnavailable(status.error or "secure credential store unavailable")
        return self._module()

    def get(self, reference: str) -> str | None:
        keyring = self._require()
        ref = normalize_credential_reference(reference)
        try:
            value = keyring.get_password(self.service_name, ref)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                f"secure credential read failed: {type(exc).__name__}"
            ) from exc
        normalized = str(value or "").strip()
        return normalized or None

    def set(self, reference: str, secret: str) -> None:
        keyring = self._require()
        ref = normalize_credential_reference(reference)
        value = str(secret or "").strip()
        if not value:
            raise ValueError("credential secret must not be empty")
        try:
            keyring.set_password(self.service_name, ref, value)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                f"secure credential write failed: {type(exc).__name__}"
            ) from exc

    def delete(self, reference: str) -> None:
        keyring = self._require()
        ref = normalize_credential_reference(reference)
        try:
            if not keyring.get_password(self.service_name, ref):
                return
            keyring.delete_password(self.service_name, ref)
        except Exception as exc:
            raise CredentialStoreUnavailable(
                f"secure credential delete failed: {type(exc).__name__}"
            ) from exc


def _materialize_spec(spec: dict[str, Any], store: CredentialStore) -> None:
    if str(spec.get("api_key") or "").strip():
        return
    reference = str(spec.get("credential_ref") or "").strip()
    if not reference:
        return
    try:
        secret = store.get(reference)
    except CredentialStoreUnavailable:
        return
    if secret:
        spec["api_key"] = secret


def materialize_zn_credentials(
    config: Mapping[str, Any],
    *,
    store: CredentialStore | None = None,
) -> dict[str, Any]:
    """Return a deep-copied runtime config with referenced secrets materialized.

    The returned mapping is transient and must never be written back to disk or
    exposed through resident RPC/status snapshots.
    """

    resolved = copy.deepcopy(dict(config))
    credential_store = store or KeyringCredentialStore()

    model_cfg = resolved.get("model")
    if isinstance(model_cfg, dict):
        _materialize_spec(model_cfg, credential_store)
        nested = model_cfg.get("default")
        if isinstance(nested, dict):
            _materialize_spec(nested, credential_store)

    kernel_cfg = resolved.get("zn_kernel")
    if isinstance(kernel_cfg, dict):
        routes = kernel_cfg.get("routes")
        if isinstance(routes, list):
            for route in routes:
                if isinstance(route, dict):
                    _materialize_spec(route, credential_store)

    return resolved

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zn_agent.core.provider_settings as provider_settings_module
from zn_agent.core.config import load_zn_config
from zn_agent.core.credentials import CredentialStoreStatus, CredentialStoreUnavailable
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime, build_runtime
from zn_agent.core.provider_settings import ProviderSettingsConsistencyError, ProviderSettingsService
from zn_agent.core.worker import UnavailableModelWorkerFactory


class MemoryCredentialStore:
    def __init__(self, *, available: bool = True):
        self.values: dict[str, str] = {}
        self.available = available

    def status(self) -> CredentialStoreStatus:
        return CredentialStoreStatus(
            available=self.available,
            backend="test-memory" if self.available else "unavailable",
            error=None if self.available else "test secure store unavailable",
        )

    def _require(self) -> None:
        if not self.available:
            raise CredentialStoreUnavailable("test secure store unavailable")

    def get(self, reference: str) -> str | None:
        self._require()
        return self.values.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self._require()
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        self._require()
        self.values.pop(reference, None)


class ProviderSettingsTests(unittest.TestCase):
    def test_secure_provider_update_never_persists_or_returns_secret_and_hot_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            identity = resident.identity
            store = resident.store
            service = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )

            snapshot = service.update(
                {
                    "provider": "openai",
                    "model": "gpt-test",
                    "api_key": "zn-secret-value",
                }
            )

            saved_text = config_path.read_text(encoding="utf-8")
            saved = load_zn_config(config_path)
            self.assertNotIn("zn-secret-value", saved_text)
            self.assertEqual(saved["model"]["credential_ref"], "provider:openai")
            self.assertNotIn("api_key", saved["model"])
            self.assertEqual(credentials.values["provider:openai"], "zn-secret-value")
            self.assertNotIn("zn-secret-value", json.dumps(snapshot, default=str))
            self.assertTrue(snapshot["credential"]["configured"])
            self.assertEqual(snapshot["credential"]["source"], "secure_store")
            self.assertTrue(snapshot["cognition_available"])
            self.assertIs(resident.identity, identity)
            self.assertIs(resident.store, store)
            route = resident.kernel.router.routes[0]
            self.assertEqual(route.provider, "openai")
            self.assertEqual(route.model, "gpt-test")
            self.assertEqual(route.metadata["api_key"], "zn-secret-value")
            resident.store.close()

    def test_provider_base_url_requires_tls_except_for_explicit_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=root / "config.yaml",
                credential_store=credentials,
                environ={},
            )
            try:
                for base_url in (
                    "http://127.0.0.1:11434/v1",
                    "http://localhost:1234/v1",
                    "http://[::1]:8080/v1",
                    "https://provider.example/v1",
                ):
                    with self.subTest(base_url=base_url):
                        snapshot = service.update(
                            {
                                "provider": "openai",
                                "model": "gpt-test",
                                "base_url": base_url,
                            }
                        )
                        self.assertEqual(snapshot["base_url"], base_url)

                with self.assertRaisesRegex(ValueError, "must use HTTPS"):
                    service.update(
                        {
                            "provider": "openai",
                            "model": "gpt-test",
                            "base_url": "http://provider.example/v1",
                            "api_key": "must-not-be-stored",
                        }
                    )
                self.assertNotIn("provider:openai", credentials.values)
            finally:
                resident.store.close()

    def test_provider_base_url_rejects_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=root / "config.yaml",
                credential_store=credentials,
                environ={},
            )
            try:
                with self.assertRaisesRegex(ValueError, "embedded credentials"):
                    service.update(
                        {
                            "provider": "openai",
                            "model": "gpt-test",
                            "base_url": "https://user:password@provider.example/v1",
                        }
                    )
            finally:
                resident.store.close()

    def test_referenced_credential_restores_provider_after_resident_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            credentials = MemoryCredentialStore()
            first = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                first,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            service.update(
                {
                    "provider": "anthropic",
                    "model": "claude-test",
                    "api_key": "anthropic-secret",
                }
            )
            first_identity = first.identity
            first.store.close()

            restored = build_resident_runtime(
                config=load_zn_config(config_path),
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            try:
                self.assertEqual(restored.identity.name, first_identity.name)
                self.assertEqual(restored.identity.created_at, first_identity.created_at)
                route = restored.kernel.router.routes[0]
                self.assertEqual(route.provider, "anthropic")
                self.assertEqual(route.model, "claude-test")
                self.assertEqual(route.metadata["api_key"], "anthropic-secret")
            finally:
                restored.store.close()

    def test_missing_remote_credential_degrades_to_zero_model_instead_of_killing_runtime(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            runtime = build_runtime(
                config={"model": {"provider": "openai", "default": "gpt-test"}},
                store_path=Path(tmp) / "kernel.db",
                credential_store=MemoryCredentialStore(),
            )
            try:
                self.assertIsInstance(runtime.worker_factory, UnavailableModelWorkerFactory)
                self.assertEqual(runtime.router.routes[0].provider, "none")
                self.assertFalse(runtime.resource_status["available"])
                self.assertIn("credential", str(runtime.resource_status["error"]).lower())
            finally:
                runtime.store.close()

    def test_unavailable_secure_store_rejects_ui_secret_without_plaintext_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            unavailable = MemoryCredentialStore(available=False)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=unavailable,
            )
            service = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=unavailable,
                environ={},
            )
            with self.assertRaisesRegex(CredentialStoreUnavailable, "unavailable"):
                service.update(
                    {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key": "must-not-land-on-disk",
                    }
                )
            self.assertFalse(config_path.exists())
            resident.store.close()

    def test_advanced_routes_are_reported_but_not_overwritten_by_simple_editor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                "zn_kernel:\n  routes:\n    - id: primary\n      provider: ollama\n      model: local\n",
                encoding="utf-8",
            )
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config=load_zn_config(config_path),
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            snapshot = service.snapshot()
            self.assertEqual(snapshot["mode"], "routes")
            self.assertFalse(snapshot["editable"])
            with self.assertRaisesRegex(ValueError, "advanced zn_kernel.routes"):
                service.update({"provider": "openai", "model": "gpt-test"})
            self.assertNotIn("gpt-test", config_path.read_text(encoding="utf-8"))
            resident.store.close()

    def test_config_write_failure_restores_previous_credential_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            try:
                service.update(
                    {
                        "provider": "openai",
                        "model": "gpt-old",
                        "api_key": "old-secret",
                    }
                )
                with patch(
                    "zn_agent.core.provider_settings.save_zn_config",
                    side_effect=OSError("disk full"),
                ):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        service.update(
                            {
                                "provider": "openai",
                                "model": "gpt-new",
                                "api_key": "new-secret",
                            }
                        )

                self.assertEqual(credentials.values["provider:openai"], "old-secret")
                self.assertEqual(load_zn_config(config_path)["model"]["default"], "gpt-old")
                route = resident.kernel.router.routes[0]
                self.assertEqual(route.model, "gpt-old")
                self.assertEqual(route.metadata["api_key"], "old-secret")
            finally:
                resident.store.close()

    def test_hot_apply_failure_compensates_config_credential_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=config_path,
                credential_store=credentials,
                environ={},
            )
            try:
                service.update(
                    {
                        "provider": "openai",
                        "model": "gpt-old",
                        "api_key": "old-secret",
                    }
                )
                original_apply = provider_settings_module.apply_zn_cognitive_config

                def fail_new_config(runtime, config, **kwargs):
                    model = config.get("model") if isinstance(config, dict) else None
                    if isinstance(model, dict) and model.get("default") == "gpt-new":
                        raise RuntimeError("hot apply failed")
                    return original_apply(runtime, config, **kwargs)

                with patch(
                    "zn_agent.core.provider_settings.apply_zn_cognitive_config",
                    side_effect=fail_new_config,
                ):
                    with self.assertRaisesRegex(RuntimeError, "hot apply failed"):
                        service.update(
                            {
                                "provider": "openai",
                                "model": "gpt-new",
                                "api_key": "new-secret",
                            }
                        )

                self.assertEqual(credentials.values["provider:openai"], "old-secret")
                self.assertEqual(load_zn_config(config_path)["model"]["default"], "gpt-old")
                route = resident.kernel.router.routes[0]
                self.assertEqual(route.model, "gpt-old")
                self.assertEqual(route.metadata["api_key"], "old-secret")
            finally:
                resident.store.close()

    def test_incomplete_compensation_surfaces_consistency_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            service = ProviderSettingsService(
                resident,
                config_path=root / "config.yaml",
                credential_store=credentials,
                environ={},
            )
            try:
                with (
                    patch(
                        "zn_agent.core.provider_settings.save_zn_config",
                        side_effect=OSError("disk full"),
                    ),
                    patch.object(
                        service,
                        "_restore_credential",
                        side_effect=OSError("keyring rollback failed"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        ProviderSettingsConsistencyError,
                        "rollback was incomplete",
                    ):
                        service.update(
                            {
                                "provider": "openai",
                                "model": "gpt-test",
                                "api_key": "new-secret",
                            }
                        )
            finally:
                resident.store.close()

    def test_provider_settings_rpc_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials = MemoryCredentialStore()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
                credential_store=credentials,
            )
            settings = ProviderSettingsService(
                resident,
                config_path=root / "config.yaml",
                credential_store=credentials,
                environ={},
            )
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
                provider_settings=settings,
            )
            response = server.handle(
                {
                    "id": "settings-update",
                    "method": "provider_settings_update",
                    "params": {
                        "provider": "openrouter",
                        "model": "example/model",
                        "api_key": "rpc-secret",
                    },
                }
            )
            self.assertTrue(response["ok"])
            self.assertNotIn("rpc-secret", json.dumps(response, default=str))
            loaded = server.handle(
                {"id": "settings-get", "method": "provider_settings", "params": {}}
            )
            self.assertTrue(loaded["ok"])
            self.assertNotIn("rpc-secret", json.dumps(loaded, default=str))
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

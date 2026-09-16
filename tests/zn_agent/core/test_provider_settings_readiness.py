from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.credentials import CredentialStoreStatus
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.provider_settings import ProviderSettingsService


class MemoryCredentialStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    def status(self) -> CredentialStoreStatus:
        return CredentialStoreStatus(available=True, backend="test-memory")

    def get(self, reference: str) -> str | None:
        return self.values.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)


class ProviderSettingsReadinessTests(unittest.TestCase):
    def test_remote_provider_without_credential_is_saved_but_reported_unavailable(self):
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
                snapshot = service.update({
                    "provider": "openai",
                    "model": "gpt-test",
                })

                self.assertEqual(snapshot["provider"], "openai")
                self.assertEqual(snapshot["model"], "gpt-test")
                self.assertFalse(snapshot["cognition_available"])
                self.assertIn("credential", str(snapshot["configuration_error"]).lower())
                self.assertEqual(snapshot["active_routes"], [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

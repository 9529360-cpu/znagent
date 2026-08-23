from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory
from zn_agent.core.config import load_zn_config, zn_config_path
from zn_agent.core.provider_bridge import build_runtime_from_existing_stack
from zn_agent.core.worker import UnavailableModelWorkerFactory


class NativeRuntimeResourceTests(unittest.TestCase):
    def test_missing_zn_config_is_empty_not_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.yaml"
            self.assertEqual(load_zn_config(path), {})

    def test_zn_config_path_is_owned_by_zn_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                zn_config_path(environ={}, home=tmp),
                Path(tmp) / "config.yaml",
            )

    def test_loads_zn_yaml_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "model:\n  provider: openrouter\n  default: example/model\n",
                encoding="utf-8",
            )
            self.assertEqual(load_zn_config(path)["model"]["provider"], "openrouter")

    def test_zero_model_runtime_uses_unavailable_resource_without_legacy_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = build_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(runtime.worker_factory, UnavailableModelWorkerFactory)
                self.assertEqual(runtime.router.routes[0].provider, "none")
            finally:
                runtime.store.close()

    def test_openai_compatible_route_uses_zn_cognitive_resource_factory(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = build_runtime_from_existing_stack(
                config={
                    "zn_kernel": {
                        "routes": [
                            {
                                "id": "primary",
                                "provider": "openrouter",
                                "model": "example/model",
                                "api_key": "test-key",
                            }
                        ]
                    }
                },
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(runtime.worker_factory, CognitiveResourceWorkerFactory)
                route = runtime.router.routes[0]
                self.assertEqual(route.provider, "openrouter")
                self.assertEqual(route.metadata["base_url"], "https://openrouter.ai/api/v1")
                self.assertEqual(route.metadata["api_mode"], "chat_completions")
            finally:
                runtime.store.close()


if __name__ == "__main__":
    unittest.main()

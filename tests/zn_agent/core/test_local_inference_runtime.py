from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.local_inference_runtime import (
    LocalInferenceRuntimeDiscovery,
    _probe_openai_models,
)
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime


class _Graph:
    def installed_applications(self):
        return (
            SimpleNamespace(
                app_id="ollama-app",
                canonical_name="Ollama",
            ),
            SimpleNamespace(
                app_id="lmstudio-app",
                canonical_name="LM Studio",
            ),
        )

    def running_processes(self):
        return (
            SimpleNamespace(
                process_name="ollama.exe",
                resolved_app_id="ollama-app",
            ),
        )

    def hardware(self):
        return SimpleNamespace(
            ram_total_bytes=32 * 1024**3,
            ram_available_bytes=20 * 1024**3,
            gpus=(
                SimpleNamespace(name="Test GPU"),
            ),
        )

    def companion_context(self):
        return SimpleNamespace(
            power=SimpleNamespace(
                ac_status="online",
                battery_saver=False,
            )
        )


class LocalInferenceRuntimeDiscoveryTests(unittest.TestCase):
    def test_snapshot_combines_runtime_models_and_machine_capacity(self) -> None:
        def probe(provider, _base_url):
            return {
                "ollama": ("qwen-test:latest",),
                "lmstudio": (),
                "vllm": None,
            }[provider]

        snapshot = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=probe,
        ).snapshot()

        self.assertEqual(snapshot.usable_providers, ("ollama",))
        by_provider = {
            row.provider: row
            for row in snapshot.runtimes
        }
        self.assertTrue(by_provider["ollama"].application_installed)
        self.assertTrue(by_provider["ollama"].process_running)
        self.assertTrue(by_provider["ollama"].endpoint_reachable)
        self.assertEqual(
            by_provider["ollama"].model_ids,
            ("qwen-test:latest",),
        )

        self.assertTrue(by_provider["lmstudio"].application_installed)
        self.assertFalse(by_provider["lmstudio"].process_running)
        self.assertTrue(by_provider["lmstudio"].endpoint_reachable)
        self.assertEqual(by_provider["lmstudio"].model_ids, ())

        self.assertFalse(by_provider["vllm"].endpoint_reachable)
        self.assertEqual(snapshot.hardware.gpu_names, ("Test GPU",))
        self.assertEqual(snapshot.hardware.ac_status, "online")
        self.assertFalse(snapshot.hardware.battery_saver)

    def test_probe_never_calls_non_loopback_endpoint(self) -> None:
        for base_url in (
            "https://example.com/v1",
            "http://0.0.0.0:11434/v1",
        ):
            with self.subTest(base_url=base_url):
                self.assertIsNone(
                    _probe_openai_models(
                        "custom",
                        base_url,
                    )
                )

    def test_usable_provider_requires_reachable_endpoint_and_model(self) -> None:
        snapshot = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=lambda _provider, _base_url: (),
        ).snapshot()

        self.assertEqual(snapshot.usable_providers, ())

    def test_route_health_requires_exact_configured_model(self) -> None:
        discovery = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=lambda provider, _base_url: (
                ("qwen-test:latest",) if provider == "ollama" else None
            ),
        )
        available = discovery.route_health(
            ModelRoute(
                route_id="local-qwen",
                provider="ollama",
                model="qwen-test:latest",
                capabilities={"general": 0.8},
                metadata={"base_url": "http://127.0.0.1:11434/v1"},
            )
        )
        missing = discovery.route_health(
            ModelRoute(
                route_id="local-missing",
                provider="ollama",
                model="missing-model",
                capabilities={"general": 0.8},
                metadata={"base_url": "http://127.0.0.1:11434/v1"},
            )
        )

        self.assertTrue(available["available"])
        self.assertTrue(available["runtime_model_present"])
        self.assertFalse(missing["available"])
        self.assertFalse(missing["runtime_model_present"])

    def test_route_health_probes_exact_configured_loopback_base_url(self) -> None:
        calls = []
        discovery = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=lambda provider, base_url: (
                calls.append((provider, base_url)) or ("qwen-test:latest",)
            ),
        )

        result = discovery.route_health(
            ModelRoute(
                route_id="local-custom-port",
                provider="ollama",
                model="qwen-test:latest",
                capabilities={"general": 0.8},
                metadata={"base_url": "http://localhost:16666/v1"},
            )
        )

        self.assertTrue(result["available"])
        self.assertEqual(calls, [("ollama", "http://localhost:16666/v1")])

    def test_route_health_accepts_full_ipv4_loopback_range(self) -> None:
        calls = []
        discovery = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=lambda provider, base_url: (
                calls.append((provider, base_url)) or ("qwen-test:latest",)
            ),
        )
        result = discovery.route_health(
            ModelRoute(
                route_id="local-alt-loopback",
                provider="ollama",
                model="qwen-test:latest",
                capabilities={"general": 0.8},
                metadata={"base_url": "http://127.0.0.2:16666/v1"},
            )
        )

        self.assertTrue(result["available"])
        self.assertEqual(calls, [("ollama", "http://127.0.0.2:16666/v1")])

    def test_route_health_ignores_non_loopback_ollama_route(self) -> None:
        discovery = LocalInferenceRuntimeDiscovery(
            _Graph(),
            models_probe=lambda _provider, _base_url: (),
        )
        result = discovery.route_health(
            ModelRoute(
                route_id="remote-ollama",
                provider="ollama",
                model="qwen-test:latest",
                capabilities={"general": 0.8},
                metadata={"base_url": "https://ollama.example.test/v1"},
            )
        )

        self.assertIsNone(result)


class ProductLocalInferenceIntegrationTests(unittest.TestCase):
    def test_final_resident_exposes_read_only_local_runtime_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIs(
                    resident.local_inference.device_capabilities,
                    resident.device_capabilities,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

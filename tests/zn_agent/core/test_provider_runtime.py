from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.provider_runtime import (
    CapabilityProviderDescriptor,
    CapabilityProviderRuntime,
    CapabilityProviderStatus,
    build_machine_provider_runtime,
)


class CapabilityProviderRuntimeTests(unittest.TestCase):
    @staticmethod
    def _descriptor(
        provider_id: str = "zn.test",
        *,
        lifecycle_mode: str = "lazy",
    ) -> CapabilityProviderDescriptor:
        return CapabilityProviderDescriptor(
            provider_id=provider_id,
            description=" Test provider ",
            action_ids=("a.one", "a.one", "a.two"),
            lifecycle_mode=lifecycle_mode,
            idle_timeout_seconds=30,
            tags=("test", "test", "local"),
        )

    def test_descriptor_normalizes_contract(self) -> None:
        descriptor = self._descriptor(" zn.test ")

        self.assertEqual(descriptor.provider_id, "zn.test")
        self.assertEqual(descriptor.description, "Test provider")
        self.assertEqual(descriptor.action_ids, ("a.one", "a.two"))
        self.assertEqual(descriptor.tags, ("test", "local"))
        self.assertEqual(descriptor.idle_timeout_seconds, 30)

    def test_missing_health_probe_is_unknown_and_not_queryable(self) -> None:
        runtime = CapabilityProviderRuntime()
        runtime.register(self._descriptor())

        status = runtime.status("zn.test")

        self.assertEqual(status.state, "unknown")
        self.assertFalse(status.queryable)

    def test_duplicate_provider_owner_fails_closed(self) -> None:
        runtime = CapabilityProviderRuntime()
        runtime.register(self._descriptor())

        with self.assertRaisesRegex(ValueError, "already registered"):
            runtime.register(self._descriptor())
    def test_lazy_activation_uses_start_hook(self) -> None:
        runtime = CapabilityProviderRuntime()
        state = {"running": False, "calls": 0}

        def probe(descriptor):
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "healthy" if state["running"] else "unavailable",
                queryable=bool(state["running"]),
                running=bool(state["running"]),
            )

        def mark_running(_descriptor):
            state["calls"] += 1
            state["running"] = True

        runtime.register(
            self._descriptor(),
            health_probe=probe,
            start_hook=mark_running,
        )
        self.assertTrue(runtime.activate("zn.test").queryable)
        self.assertTrue(runtime.activate("zn.test").queryable)
        self.assertEqual(state["calls"], 1)
    def test_deactivate_uses_stop_hook_then_reprobes(self) -> None:
        runtime = CapabilityProviderRuntime()
        state = {"running": True, "calls": 0}

        def probe(descriptor):
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "healthy" if state["running"] else "unavailable",
                queryable=bool(state["running"]),
                running=bool(state["running"]),
            )

        def mark_stopped(_descriptor):
            state["calls"] += 1
            state["running"] = False

        runtime.register(
            self._descriptor(),
            health_probe=probe,
            stop_hook=mark_stopped,
        )
        result = runtime.deactivate("zn.test")
        self.assertEqual(state["calls"], 1)
        self.assertEqual(result.state, "unavailable")
        self.assertFalse(result.queryable)


class MachineProviderRuntimeTests(unittest.TestCase):
    @staticmethod
    def _action(action_id: str, *, state: str):
        descriptor = ActionDescriptor(
            action_id=action_id,
            provider="zn.windows",
            description=f"Action {action_id}",
        )

        def probe(current):
            return ActionAvailability(
                current.action_id,
                state,
            )

        return descriptor, probe

    def test_windows_health_aggregates_action_availability(self) -> None:
        fabric = ActionFabricRegistry()
        for action_id, state in (
            ("windows.context.read", "available"),
            ("windows.application.launch", "unavailable"),
            ("windows.application.activate", "unknown"),
        ):
            descriptor, probe = self._action(action_id, state=state)
            fabric.register(descriptor, availability_probe=probe)

        runtime = build_machine_provider_runtime(fabric)
        status = runtime.status("zn.windows")

        self.assertEqual(status.state, "degraded")
        self.assertTrue(status.queryable)
        self.assertTrue(status.running)
        self.assertEqual(status.evidence["registered_action_count"], 3)
        self.assertEqual(status.evidence["available_action_count"], 1)
        self.assertEqual(status.evidence["unknown_action_count"], 1)

    def test_empty_windows_provider_is_unavailable(self) -> None:
        runtime = build_machine_provider_runtime(ActionFabricRegistry())
        status = runtime.status("zn.windows")

        self.assertEqual(status.state, "unavailable")
        self.assertFalse(status.queryable)

    def test_local_inference_provider_uses_fresh_runtime_snapshot(self) -> None:
        snapshot = SimpleNamespace(
            usable_providers=("ollama",),
            runtimes=(
                SimpleNamespace(provider="ollama", endpoint_reachable=True),
                SimpleNamespace(provider="lmstudio", endpoint_reachable=False),
                SimpleNamespace(provider="vllm", endpoint_reachable=False),
            ),
            hardware=SimpleNamespace(
                gpu_names=("Intel Arc",),
                ac_status="online",
                battery_saver=False,
            ),
            observed_at="2026-09-21T00:00:00+00:00",
        )
        local_inference = SimpleNamespace(snapshot=lambda: snapshot)
        runtime = build_machine_provider_runtime(
            ActionFabricRegistry(),
            local_inference=local_inference,
        )

        descriptor = runtime.descriptor("zn.local_inference")
        status = runtime.status("zn.local_inference")

        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor.lifecycle_mode, "external")
        self.assertEqual(status.state, "healthy")
        self.assertTrue(status.queryable)
        self.assertEqual(status.evidence["usable_providers"], ("ollama",))
        self.assertEqual(status.evidence["gpu_count"], 1)


class ProductProviderRuntimeIntegrationTests(unittest.TestCase):
    def test_final_resident_exposes_windows_provider_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                descriptor = resident.provider_runtime.descriptor("zn.windows")
                self.assertIsNotNone(descriptor)
                self.assertEqual(
                    descriptor.action_ids,
                    tuple(
                        row.action_id
                        for row in resident.action_fabric.descriptors(provider="zn.windows")
                    ),
                )
                uia = resident.provider_runtime.descriptor("zn.windows.uia")
                self.assertIsNotNone(uia)
                self.assertEqual(
                    uia.action_ids,
                    tuple(
                        row.action_id
                        for row in resident.action_fabric.descriptors(provider="zn.windows.uia")
                    ),
                )
                self.assertEqual(
                    tuple(sorted((*descriptor.action_ids, *uia.action_ids))),
                    resident.action_fabric.names(),
                )
                status = resident.provider_runtime.status("zn.windows")
                self.assertIn(
                    status.state,
                    {"healthy", "degraded", "unavailable", "unknown"},
                )
                local = resident.provider_runtime.descriptor("zn.local_inference")
                self.assertIsNotNone(local)
                self.assertEqual(local.lifecycle_mode, "external")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

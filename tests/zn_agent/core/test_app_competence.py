from __future__ import annotations

import unittest

from zn_agent.core.action_fabric import ActionDescriptor, ActionFabricRegistry

from zn_agent.core.app_competence import (
    AppCompetenceBinding,
    AppCompetencePack,
    AppCompetenceRegistry,
)


class AppCompetenceRegistryTests(unittest.TestCase):
    def _pack(self, *, version: str = "1.2.3") -> AppCompetencePack:
        return AppCompetencePack(
            pack_id=f"example-{version}",
            app_id="example.app",
            app_version=version,
            aliases=("Example", "EXAMPLE APP"),
            bindings=(
                AppCompetenceBinding(
                    capability="install",
                    action_id="windows.application.install",
                    metadata={"execution_mode": 0, "stage_end_condition": 2},
                ),
                AppCompetenceBinding(
                    capability="uninstall",
                    action_id="windows.application.uninstall",
                ),
            ),
            source="test-fixture",
        )

    def test_resolves_exact_version_and_alias_without_execution_authority(self) -> None:
        registry = AppCompetenceRegistry()
        pack = self._pack()
        registry.register(pack)

        self.assertIs(registry.resolve("EXAMPLE", "1.2.3"), pack)
        binding = registry.binding("example app", "1.2.3", "INSTALL")
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.action_id, "windows.application.install")
        self.assertEqual(binding.metadata["stage_end_condition"], 2)

    def test_version_mismatch_fails_closed(self) -> None:
        registry = AppCompetenceRegistry()
        registry.register(self._pack())
        self.assertIsNone(registry.resolve("example.app", "1.2.4"))
        self.assertIsNone(registry.binding("example.app", "1.2.4", "install"))

    def test_multiple_versions_remain_distinct(self) -> None:
        registry = AppCompetenceRegistry()
        first = self._pack(version="1.2.3")
        second = self._pack(version="2.0.0")
        registry.register(first)
        registry.register(second)
        self.assertIs(registry.resolve("Example", "1.2.3"), first)
        self.assertIs(registry.resolve("Example", "2.0.0"), second)
        self.assertEqual(registry.packs(app="example"), (first, second))

    def test_rejects_duplicate_app_version_registration(self) -> None:
        registry = AppCompetenceRegistry()
        registry.register(self._pack())
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(self._pack())

    def test_rejects_alias_collision_between_apps(self) -> None:
        registry = AppCompetenceRegistry()
        registry.register(self._pack())
        other = AppCompetencePack(
            pack_id="other-1",
            app_id="other.app",
            app_version="1.0",
            aliases=("example",),
            bindings=(AppCompetenceBinding("open", "windows.application.open"),),
        )
        with self.assertRaisesRegex(ValueError, "alias already owned"):
            registry.register(other)

    def test_action_fabric_validation_rejects_unknown_action_ids(self) -> None:
        registry = AppCompetenceRegistry()
        registry.register(self._pack())
        fabric = ActionFabricRegistry()
        fabric.register(ActionDescriptor("windows.application.install", "windows", "install application"))
        with self.assertRaisesRegex(ValueError, "unknown Action Fabric actions"):
            registry.validate_action_fabric(fabric)

        fabric.register(ActionDescriptor("windows.application.uninstall", "windows", "uninstall application"))
        registry.validate_action_fabric(fabric)

    def test_pack_requires_unique_capabilities(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate capabilities"):
            AppCompetencePack(
                pack_id="bad",
                app_id="example.app",
                app_version="1",
                bindings=(
                    AppCompetenceBinding("Install", "a"),
                    AppCompetenceBinding("install", "b"),
                ),
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from zn_agent.core.action_fabric import ActionDescriptor, ActionFabricRegistry

from zn_agent.core.app_competence import (
    AppCompetenceBinding,
    AppCompetenceCompletion,
    AppCompetencePack,
    AppCompetenceRegistry,
    AppCompetenceStage,
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


    def test_staged_recipe_binds_semantic_actions_and_read_only_completion(self) -> None:
        registry = AppCompetenceRegistry()
        completion = AppCompetenceCompletion(
            action_id="windows.ui.control.read",
            arguments={
                "control_type": "checkbox",
                "automation_id": "AutoSave",
                "pattern": "toggle",
            },
            expected={"state.toggle_state": "on"},
        )
        stage = AppCompetenceStage(
            action_id="windows.ui.control.toggle",
            arguments={
                "control_type": "checkbox",
                "automation_id": "AutoSave",
                "state": "on",
            },
            completion=completion,
            timeout_ms=3500,
            metadata={"stage_end_condition": 2, "source_version": "16.0"},
        )
        pack = AppCompetencePack(
            pack_id="word-16-autosave",
            app_id="microsoft.word",
            app_version="16.0",
            bindings=(
                AppCompetenceBinding(
                    capability="enable_autosave",
                    action_id="windows.ui.control.toggle",
                    stages=(stage,),
                ),
            ),
        )
        registry.register(pack)

        plan = registry.stage_plan("microsoft.word", "16.0", "enable_autosave")
        self.assertEqual(plan, (stage,))
        self.assertEqual(plan[0].timeout_ms, 3500)
        self.assertEqual(plan[0].completion.action_id, "windows.ui.control.read")

        fabric = ActionFabricRegistry()
        fabric.register(
            ActionDescriptor(
                "windows.ui.control.toggle",
                "zn.windows.uia",
                "toggle control",
                effect_class="reversible_side_effect",
            )
        )
        fabric.register(
            ActionDescriptor(
                "windows.ui.control.read",
                "zn.windows.uia",
                "read control",
                effect_class="read_only",
            )
        )
        registry.validate_action_fabric(fabric)

    def test_competence_stage_rejects_runtime_native_authority(self) -> None:
        for key in ("application_id", "hwnd", "pid", "runtime_id", "x", "y", "coordinates"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "runtime/native action authority"):
                    AppCompetenceStage(
                        action_id="windows.ui.control.toggle",
                        arguments={key: 1},
                    )

    def test_competence_completion_must_use_read_only_action(self) -> None:
        registry = AppCompetenceRegistry()
        completion = AppCompetenceCompletion(
            action_id="windows.ui.control.toggle",
            arguments={"control_type": "checkbox", "pattern": "toggle"},
            expected={"state.toggle_state": "on"},
        )
        stage = AppCompetenceStage(
            action_id="windows.ui.control.toggle",
            arguments={"control_type": "checkbox", "state": "on"},
            completion=completion,
        )
        registry.register(
            AppCompetencePack(
                pack_id="bad-completion",
                app_id="example.app",
                app_version="1",
                bindings=(
                    AppCompetenceBinding(
                        "toggle",
                        "windows.ui.control.toggle",
                        stages=(stage,),
                    ),
                ),
            )
        )
        fabric = ActionFabricRegistry()
        fabric.register(
            ActionDescriptor(
                "windows.ui.control.toggle",
                "zn.windows.uia",
                "toggle control",
                effect_class="reversible_side_effect",
            )
        )
        with self.assertRaisesRegex(ValueError, "completion actions must be read_only"):
            registry.validate_action_fabric(fabric)


if __name__ == "__main__":
    unittest.main()

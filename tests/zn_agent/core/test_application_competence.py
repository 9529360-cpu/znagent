from __future__ import annotations

import unittest

from zn_agent.core.application_competence import (
    ApplicationCompetencePack,
    ApplicationCompetenceStage,
    ApplicationIdentityContract,
    UiDescriptor,
    application_competence_from_dict,
    evaluate_application_identity,
    evaluate_competence,
    evaluate_competence_stage,
    evaluate_ui_descriptor,
)
from zn_agent.core.machine_capability import InstalledApplication
from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation


NOW = "2026-09-21T15:00:00+00:00"
AFTER = "2026-09-21T14:59:00+00:00"


def app(*, version: str | None = "24.09", observed_at: str = NOW) -> InstalledApplication:
    return InstalledApplication(
        app_id="app-7zip",
        display_name="7-Zip",
        canonical_name="7-Zip",
        executable_path=r"C:\Program Files\7-Zip\7zFM.exe",
        package_identity=None,
        aumid=None,
        version=version,
        publisher="Igor Pavlov",
        launch_kind="executable",
        launch_target=r"C:\Program Files\7-Zip\7zFM.exe",
        capabilities=("generic_application",),
        observed_at=observed_at,
        evidence_source=("uninstall-registry",),
    )


def descriptor(descriptor_id: str = "install") -> UiDescriptor:
    return UiDescriptor(
        descriptor_id=descriptor_id,
        control_type=50000,
        name_equals="Install",
        automation_id_equals="InstallButton",
        class_name_equals="Button",
    )


def stage(*, condition: str = "target_present") -> ApplicationCompetenceStage:
    return ApplicationCompetenceStage(
        stage_id="install-1",
        label="Installer ready",
        selectors=(descriptor(),),
        completion_condition=condition,  # type: ignore[arg-type]
        requires_progress_observation=condition == "progress_complete",
    )


def pack(*, versions=("24.09",)) -> ApplicationCompetencePack:
    return ApplicationCompetencePack(
        schema_version=1,
        pack_id="7zip-install",
        revision=3,
        action_id="application.install",
        application=ApplicationIdentityContract(
            canonical_name="7-Zip",
            accepted_versions=tuple(versions),
            executable_name="7zFM.exe",
            publisher="Igor Pavlov",
        ),
        stages=(stage(),),
        evidence_versions=(("uia_schema", 1), ("visual_contract", 1)),
    )


def observation(**overrides):
    data = {
        "control_type": 50000,
        "name": "Install",
        "automation_id": "InstallButton",
        "class_name": "Button",
        "framework_id": "Win32",
        "is_enabled": True,
        "is_offscreen": False,
        "captured_at": NOW,
    }
    data.update(overrides)
    return data


class ApplicationCompetenceTests(unittest.TestCase):
    def test_exact_application_version_and_freshness_are_required(self) -> None:
        contract = pack().application
        exact = evaluate_application_identity(contract, app(), observed_after=AFTER)
        self.assertEqual(exact.status, "supported")
        self.assertIn("version", exact.matched_fields)

        drifted = evaluate_application_identity(
            contract,
            app(version="25.00"),
            observed_after=AFTER,
        )
        self.assertEqual(drifted.status, "mismatched")
        self.assertIn("version", drifted.mismatched_fields)

        unknown = evaluate_application_identity(
            contract,
            app(version=None),
            observed_after=AFTER,
        )
        self.assertEqual(unknown.status, "untested")
        self.assertIn("version", unknown.untested_fields)

    def test_stale_application_evidence_fails_closed(self) -> None:
        result = evaluate_application_identity(
            pack().application,
            app(observed_at="2026-09-21T14:00:00+00:00"),
            observed_after=AFTER,
        )
        self.assertEqual(result.status, "mismatched")
        self.assertIn("application_freshness", result.mismatched_fields)

    def test_selector_requires_stable_properties_and_fresh_ui_evidence(self) -> None:
        exact = evaluate_ui_descriptor(descriptor(), observation(), captured_after=AFTER)
        self.assertEqual(exact.status, "supported")

        missing = evaluate_ui_descriptor(
            descriptor(),
            observation(automation_id=""),
            captured_after=AFTER,
        )
        self.assertEqual(missing.status, "untested")
        self.assertIn("automation_id", missing.untested_fields)

        wrong = evaluate_ui_descriptor(
            descriptor(),
            observation(name="Cancel"),
            captured_after=AFTER,
        )
        self.assertEqual(wrong.status, "mismatched")
        self.assertIn("name", wrong.mismatched_fields)

        stale = evaluate_ui_descriptor(
            descriptor(),
            observation(captured_at="2026-09-21T14:00:00+00:00"),
            captured_after=AFTER,
        )
        self.assertEqual(stale.status, "mismatched")
        self.assertIn("ui_freshness", stale.mismatched_fields)

    def test_real_named_uia_observation_shape_can_satisfy_stable_descriptor(self) -> None:
        observed = NamedAutomationControlObservation(
            runtime_id=(1, 2, 3), process_id=42, process_name="7zFM.exe",
            name="Install", control_type=50000, class_name="Button",
            is_enabled=True, is_offscreen=False, left=10.0, top=10.0,
            right=100.0, bottom=40.0, center_x_fraction=0.5,
            center_y_fraction=0.5, captured_at=NOW,
        )
        stable = UiDescriptor(
            descriptor_id="named-install", control_type=50000,
            name_equals="Install", class_name_equals="Button",
        )
        result = evaluate_ui_descriptor(stable, observed, captured_after=AFTER)
        self.assertEqual(result.status, "supported")
        self.assertEqual(result.selected_descriptor_id, "named-install")

    def test_multiple_selector_variants_allow_bounded_fallback(self) -> None:
        alternate = UiDescriptor(
            descriptor_id="install-legacy",
            control_type=50000,
            name_equals="Install",
            class_name_equals="LegacyButton",
        )
        fallback_stage = ApplicationCompetenceStage(
            stage_id="install-1",
            label="Installer ready",
            selectors=(descriptor(), alternate),
        )
        result = evaluate_competence_stage(
            fallback_stage,
            [observation(automation_id="", class_name="LegacyButton")],
            captured_after=AFTER,
        )
        self.assertEqual(result.status, "supported")
        self.assertEqual(result.selected_descriptor_id, "install-legacy")

    def test_absence_requires_complete_enumeration(self) -> None:
        absent_stage = stage(condition="target_absent")
        incomplete = evaluate_competence_stage(
            absent_stage,
            [observation(name="Cancel", automation_id="CancelButton")],
            observation_complete=False,
        )
        self.assertEqual(incomplete.status, "untested")

        complete = evaluate_competence_stage(
            absent_stage,
            [observation(name="Cancel", automation_id="CancelButton")],
            observation_complete=True,
        )
        self.assertEqual(complete.status, "supported")

    def test_progress_stage_waits_until_progress_is_freshly_complete(self) -> None:
        progress_stage = stage(condition="progress_complete")
        waiting = evaluate_competence_stage(
            progress_stage,
            [observation()],
            captured_after=AFTER,
            progress_complete=None,
        )
        self.assertEqual(waiting.status, "untested")
        self.assertIn("progress_complete", waiting.untested_fields)

        complete = evaluate_competence_stage(
            progress_stage,
            [observation()],
            captured_after=AFTER,
            progress_complete=True,
        )
        self.assertEqual(complete.status, "supported")

    def test_pack_evaluation_combines_app_and_current_stage_evidence(self) -> None:
        result = evaluate_competence(
            pack(),
            app(),
            stage_id="install-1",
            observations=[observation()],
            application_observed_after=AFTER,
            ui_captured_after=AFTER,
            current_evidence_versions={"uia_schema": 1, "visual_contract": 1},
        )
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["stage"]["selected_descriptor_id"], "install")

    def test_evidence_version_contract_is_exact_and_fail_closed(self) -> None:
        exact = evaluate_competence(
            pack(), app(), stage_id="install-1", observations=[observation()],
            current_evidence_versions={"uia_schema": 1, "visual_contract": 1},
        )
        self.assertEqual(exact["evidence"]["status"], "supported")

        drifted = evaluate_competence(
            pack(), app(), stage_id="install-1", observations=[observation()],
            current_evidence_versions={"uia_schema": 1, "visual_contract": 2},
        )
        self.assertEqual(drifted["status"], "mismatched")
        self.assertIn("evidence_version:visual_contract", drifted["evidence"]["mismatched_fields"])

        missing = evaluate_competence(
            pack(), app(), stage_id="install-1", observations=[observation()],
            current_evidence_versions={"uia_schema": 1},
        )
        self.assertEqual(missing["status"], "untested")
        self.assertIn("evidence_version:visual_contract", missing["evidence"]["untested_fields"])

    def test_data_loader_rejects_executable_payloads_and_unknown_fields(self) -> None:
        raw = {
            "schema_version": 1,
            "pack_id": "7zip-install",
            "revision": 1,
            "action_id": "application.install",
            "application": {
                "canonical_name": "7-Zip",
                "accepted_versions": ["24.09"],
                "executable_name": "7zFM.exe",
            },
            "stages": [
                {
                    "stage_id": "install-1",
                    "label": "Installer ready",
                    "selectors": [
                        {
                            "descriptor_id": "install",
                            "control_type": 50000,
                            "name_equals": "Install",
                        }
                    ],
                }
            ],
            "evidence_versions": {"uia_schema": 1},
        }
        parsed = application_competence_from_dict(raw)
        self.assertEqual(parsed.application.accepted_versions, ("24.09",))
        self.assertEqual(parsed.evidence_versions, (("uia_schema", 1),))

        malicious = dict(raw)
        malicious["stages"] = [dict(raw["stages"][0], command="powershell.exe -enc ...")]
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            application_competence_from_dict(malicious)

        coordinates = dict(raw)
        coordinates["stages"] = [
            dict(
                raw["stages"][0],
                selectors=[dict(raw["stages"][0]["selectors"][0], x=100, y=200)],
            )
        ]
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            application_competence_from_dict(coordinates)

    def test_descriptor_and_version_contracts_cannot_be_weak_or_versionless(self) -> None:
        with self.assertRaisesRegex(ValueError, "anchor"):
            UiDescriptor(descriptor_id="weak", control_type=50000)
        with self.assertRaisesRegex(ValueError, "accepted version"):
            ApplicationIdentityContract(canonical_name="7-Zip", accepted_versions=())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.result_semantics import detect_masked_success, normalize_action_result
from agent.kernel.verified_experience import (
    VerifiedExperience,
    VerifiedExperienceStore,
    build_verified_experience,
)


class VerifiedExperienceTests(unittest.TestCase):
    @staticmethod
    def _python_command(code: str) -> str:
        args = [sys.executable, "-c", code]
        return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _run_to_terminal(resident, limit: int = 24):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_independent_text_verification_records_privacy_safe_restartable_experience(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "private-target.txt"
            secret_task = "SECRET_TASK learn from this private write"
            secret_content = "SECRET_CONTENT resident-owned learning"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                secret_task,
                payload={
                    "path": str(target),
                    "content": secret_content,
                    "model_policy": "never",
                },
            )
            result = self._run_to_terminal(first)
            self.assertTrue(result.success)

            experiences = first.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            experience = experiences[0]
            self.assertEqual(experience.verdict, "verified")
            self.assertEqual(experience.action_kind, "write_text")
            self.assertEqual(experience.expected_outcome["kind"], "text_equals")
            self.assertEqual(experience.expected_outcome["expected_chars"], len(secret_content))
            self.assertEqual(experience.verification["observation_kind"], "read_text")
            self.assertTrue(experience.verification["observation_success"])
            self.assertNotIn("path", experience.expected_outcome)

            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT data FROM verified_experiences WHERE experience_id=?",
                    (experience.experience_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            stored = str(row[0])
            for private_value in (
                secret_task,
                secret_content,
                str(target),
                str(root),
            ):
                self.assertNotIn(private_value, stored)

            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].experience_id, experience.experience_id)
            self.assertEqual(restored[0].verdict, "verified")
            second.store.close()

    def test_contradicted_postcondition_records_negative_experience(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "contradicted.txt"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                f"ensure {target} contains the requested content",
                payload={
                    "path": str(target),
                    "content": "intended state",
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            target.write_text("reality contradicted the action", encoding="utf-8")
            self.assertIsNone(resident.live_once())

            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "contradicted")
            self.assertFalse(experiences[0].verification["verified"])
            self.assertEqual(
                state.data["latest_verified_experience"]["experience_id"],
                experiences[0].experience_id,
            )
            self.assertEqual(
                state.data["latest_verified_experience"]["verdict"],
                "contradicted",
            )
            resident.store.close()

    def test_body_success_and_exit_zero_without_postcondition_do_not_create_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = self._python_command("print('body-success-only')")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                "run one command without claiming a learned postcondition",
                payload={
                    "command": command,
                    "workdir": str(root),
                    "model_policy": "never",
                },
            )

            result = self._run_to_terminal(resident)
            self.assertTrue(result.success)
            self.assertEqual(resident.verified_experiences.for_event(event.event_id), [])
            self.assertEqual(resident.verified_experiences.count(), 0)
            resident.store.close()

    def test_reported_or_model_text_success_without_independent_observation_is_not_experience(self):
        claimed = build_verified_experience(
            event_id="evt-model-claim",
            goal="model says the task worked",
            gap=None,
            source="external-cognition-assisted",
            domains=("general",),
            situation_evidence_fingerprint="evidence",
            action_kind="command",
            action_signature_hash="action",
            primary_action_result={
                "action_id": "body-action",
                "kind": "command",
                "success": True,
                "output": "model-reported success",
                "data": {"exit_code": 0},
            },
            primary_command="some command",
            expected_outcome={"kind": "command", "command": "verify it"},
            verification_result={
                "kind": "command",
                "verified": True,
                "model_text": "I checked it and it succeeded",
            },
        )
        self.assertIsNone(claimed)

    def test_masked_success_is_negative_evidence_not_positive_verification(self):
        self.assertEqual(
            detect_masked_success(
                "cargo build 2>&1 | tail -20",
                "error: could not compile `demo`",
            ),
            "pipeline_passthrough",
        )
        self.assertEqual(
            detect_masked_success(
                "cargo build || echo BUILD FAILED",
                "BUILD FAILED",
            ),
            "fallback_swallow",
        )
        self.assertIsNone(
            detect_masked_success(
                "grep error build.log | head -20",
                "error: could not compile `demo`",
            )
        )

        features = normalize_action_result(
            {
                "kind": "command",
                "success": True,
                "output": "error: could not compile `demo`",
                "data": {"exit_code": 0, "status": "completed"},
            },
            command="cargo build 2>&1 | tail -20",
        )
        self.assertTrue(features["masked_success"])
        self.assertEqual(features["failure_class"], "masked_success")

        experience = build_verified_experience(
            event_id="evt-masked",
            goal="build should really pass",
            gap=None,
            source="native",
            domains=("general",),
            situation_evidence_fingerprint="evidence",
            action_kind="command",
            action_signature_hash="action",
            primary_action_result={
                "action_id": "primary",
                "kind": "command",
                "success": True,
                "output": "started",
                "data": {"exit_code": 0},
            },
            primary_command="echo started",
            expected_outcome={
                "kind": "command",
                "command": "cargo build 2>&1 | tail -20",
                "expected_exit_code": 0,
            },
            verification_result={
                "kind": "command",
                "verified": True,
                "expected_exit_code": 0,
                "observed_exit_code": 0,
                "missing_output_contains": [],
                "observation": {
                    "action_id": "verification",
                    "kind": "command",
                    "success": True,
                    "output": "error: could not compile `demo`",
                    "data": {"exit_code": 0, "status": "completed"},
                },
            },
        )
        self.assertIsNotNone(experience)
        self.assertEqual(experience.verdict, "contradicted")
        self.assertFalse(experience.verification["verified"])

    def test_bounded_retention_keeps_contradiction(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            bounded = VerifiedExperienceStore(resident.store, max_records=3)
            for index in range(6):
                verdict = "contradicted" if index == 1 else "verified"
                bounded.record(
                    VerifiedExperience(
                        experience_id=f"vx-{index}",
                        event_id=f"evt-{index}",
                        source="native",
                        situation_evidence_fingerprint=f"evidence-{index}",
                        goal_fingerprint=f"goal-{index}",
                        gap_fingerprint=None,
                        domains=("general",),
                        action_kind="command",
                        action_signature_hash=f"action-{index}",
                        expected_outcome={
                            "kind": "command",
                            "expected_exit_code": index,
                        },
                        result_features={
                            "effect_class": "potential_side_effect",
                            "failure_class": None,
                        },
                        verification={
                            "kind": "command",
                            "verified": verdict == "verified",
                        },
                        verdict=verdict,
                        group_key=f"group-{index}",
                        created_at=f"2026-08-23T00:00:0{index}+00:00",
                    )
                )

            self.assertEqual(bounded.count(), 3)
            retained = bounded.recent(10)
            self.assertTrue(any(item.verdict == "contradicted" for item in retained))
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

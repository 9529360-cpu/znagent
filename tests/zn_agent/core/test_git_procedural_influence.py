from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent, derive_native_action_intents
from zn_agent.core.body import BodyActionResult
from zn_agent.core.git_semantics import git_stage_command
from zn_agent.core.models import AgentEvent
from zn_agent.core.procedural_influence import select_procedurally_influenced_intent
from zn_agent.core.procedural_tendency import CandidateProceduralTendency
from zn_agent.core.provider_bridge import build_resident_runtime


class GitProceduralInfluenceTests(unittest.TestCase):
    @staticmethod
    def _fingerprint(value) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return proc.stdout.strip()

    @classmethod
    def _repo(cls, root: Path) -> Path:
        cls._git(root, "init", "-q")
        cls._git(root, "config", "user.email", "zn-tests@example.invalid")
        cls._git(root, "config", "user.name", "ZN Tests")
        target = root / "tracked.txt"
        target.write_text("base\n", encoding="utf-8")
        cls._git(root, "add", "--", target.name)
        cls._git(root, "commit", "-qm", "initial")
        return target

    @classmethod
    def _candidate(cls, root: Path, target: Path, *, variant: str):
        domains = tuple(
            sorted(
                cls._fingerprint(item)
                for item in ("it/git", "filesystem")
            )
        )
        return CandidateProceduralTendency(
            tendency_id=f"pt-git-{variant}",
            group_key=f"group-git-{variant}",
            action_kind="command",
            domain_fingerprints=domains,
            expected_kind="git_path_staged",
            expected_exit_code=None,
            effect_class="potential_side_effect",
            failure_class=None,
            support_count=3,
            contradiction_count=0,
            distinct_event_count=3,
            native_support_count=3,
            assisted_support_count=0,
            reliability=1.0,
            maturity_state="supported",
            inhibited=False,
            applicability={
                "stable_target_fingerprint": cls._fingerprint(str(target)),
                "stable_workdir_fingerprint": cls._fingerprint(str(root)),
                "stable_verification_signature_hash": None,
                "stable_action_variant": variant,
                "target_variants": 1,
                "workdir_variants": 1,
                "verification_signature_variants": 0,
                "action_variant_variants": 1,
                "goal_variants": 3,
                "situation_variants": 3,
                "action_signature_variants": 1,
            },
            recent_verdicts=("verified", "verified", "verified"),
            supporting_experience_ids=("vx-1", "vx-2", "vx-3"),
            contradicting_experience_ids=(),
            first_seen_at="2026-08-23T10:00:00+00:00",
            last_seen_at="2026-08-23T12:00:00+00:00",
        )

    @staticmethod
    def _event(root: Path, target: Path) -> AgentEvent:
        return AgentEvent(
            event_id="evt-git-procedural",
            task="stage this repository path in the current Git index",
            payload={
                "path": str(target),
                "repo_path": str(root),
                "expected_outcome": {
                    "kind": "git_path_staged",
                    "path": str(target),
                },
                "required_capabilities": ["it/git", "filesystem"],
                "model_policy": "never",
            },
        )

    @staticmethod
    def _facts(root: Path, target: Path) -> dict:
        rel = target.relative_to(root).as_posix()
        return {
            "paths": [
                {
                    "path": str(target),
                    "exists": True,
                    "type": "file",
                    "size_bytes": target.stat().st_size,
                }
            ],
            "git": {
                "available": True,
                "root": str(root),
                "branch": "main",
                "staged_paths": [],
                "unstaged_paths": [rel],
                "untracked_paths": [],
                "conflicted_paths": [],
            },
        }

    @staticmethod
    def _run_to_terminal(resident, limit: int = 120):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 100) -> None:
        for _ in range(limit):
            state = resident.store.get_working_state()
            if state.stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"resident reached terminal result before {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach {stage}; current={resident.store.get_working_state().stage}"
        )

    def test_supported_variant_only_reorders_fresh_current_git_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked file.txt"
            target.write_text("changed\n", encoding="utf-8")
            event = self._event(root, target)
            facts = self._facts(root, target)
            intents = derive_native_action_intents(event, facts=facts)
            self.assertEqual(len(intents), 2)
            self.assertEqual(intents[0].expected_outcome["action_variant"], "git_add")
            self.assertEqual(
                intents[1].expected_outcome["action_variant"],
                "git_update_index",
            )
            for intent in intents:
                self.assertEqual(
                    intent.args["command"],
                    git_stage_command(
                        intent.expected_outcome["action_variant"],
                        intent.expected_outcome["relative_path"],
                    ),
                )

            candidate = self._candidate(root, target, variant="git_update_index")
            selected, influence = select_procedurally_influenced_intent(
                event,
                intents,
                candidates=(candidate,),
                current_domains=("it", "it/git", "filesystem"),
                facts=facts,
            )

            self.assertIsNotNone(influence)
            self.assertEqual(
                selected.expected_outcome["action_variant"],
                "git_update_index",
            )
            self.assertEqual(selected.args, intents[1].args)
            self.assertIn("git_goal_proven", influence.reality_matched_fields)
            self.assertIn("target_observed", influence.reality_matched_fields)
            self.assertIn("workdir_observed", influence.reality_matched_fields)

            serialized = json.dumps(influence.to_dict(), sort_keys=True)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn(str(target), serialized)
            self.assertNotIn("git update-index", serialized)

    def test_cross_target_missing_reality_and_corrupted_choice_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            other = root / "other.txt"
            other.write_text("other\n", encoding="utf-8")
            event = self._event(root, target)
            facts = self._facts(root, target)
            intents = derive_native_action_intents(event, facts=facts)

            wrong_target = self._candidate(root, other, variant="git_update_index")
            selected, influence = select_procedurally_influenced_intent(
                event,
                intents,
                candidates=(wrong_target,),
                current_domains=("it/git", "filesystem"),
                facts=facts,
            )
            self.assertIsNone(influence)
            self.assertEqual(selected.args, intents[0].args)

            missing_paths = {"git": facts["git"]}
            self.assertEqual(
                derive_native_action_intents(event, facts=missing_paths),
                (),
            )

            corrupted = NativeActionIntent.from_dict(intents[1].to_dict())
            corrupted.args["command"] = "git add -- other.txt"
            selected, influence = select_procedurally_influenced_intent(
                event,
                (intents[0], corrupted),
                candidates=(self._candidate(root, target, variant="git_update_index"),),
                current_domains=("it/git", "filesystem"),
                facts=facts,
            )
            self.assertIsNone(influence)
            self.assertEqual(selected.args, intents[0].args)

    def test_generic_command_cannot_impersonate_git_resident_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
            target.write_text("changed\n", encoding="utf-8")
            event = self._event(root, target)
            facts = self._facts(root, target)
            legitimate = derive_native_action_intents(event, facts=facts)[1]
            forged = NativeActionIntent(
                intent_id="act-forged",
                event_id=event.event_id,
                kind="command",
                args=dict(legitimate.args),
                expected_outcome=dict(legitimate.expected_outcome),
                source="structured_choice",
            )

            selected, influence = select_procedurally_influenced_intent(
                event,
                (forged,),
                candidates=(self._candidate(root, target, variant="git_update_index"),),
                current_domains=("it/git", "filesystem"),
                facts=facts,
            )

            self.assertIsNone(influence)
            self.assertIs(selected, forged)

    def test_active_resident_learns_plumbing_variant_then_biases_only_current_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = self._repo(root)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / ".zn" / "kernel.db",
            )
            original_dispatch = resident.body._dispatch
            failed_events: set[str] = set()

            def dispatch(action, started):
                command = str(action.args.get("command") or "")
                if (
                    action.kind == "command"
                    and command.startswith("git add -- ")
                    and action.event_id not in failed_events
                ):
                    failed_events.add(action.event_id)
                    return BodyActionResult(
                        action_id=action.action_id,
                        kind=action.kind,
                        success=False,
                        data={"command": command},
                        error="synthetic porcelain staging failure for learning",
                        event_id=action.event_id,
                        started_at=started,
                    )
                return original_dispatch(action, started)

            with patch.object(resident.body, "_dispatch", side_effect=dispatch):
                for index in range(3):
                    target.write_text(f"practice-{index}\n", encoding="utf-8")
                    event = resident.enqueue(
                        f"stage stable repository path practice {index}",
                        payload={
                            "path": str(target),
                            "repo_path": str(root),
                            "expected_outcome": {
                                "kind": "git_path_staged",
                                "path": str(target),
                            },
                            "model_policy": "never",
                            "required_capabilities": ["it/git", "filesystem"],
                        },
                    )
                    result = self._run_to_terminal(resident)
                    self.assertTrue(result.success)
                    experiences = resident.verified_experiences.for_event(event.event_id)
                    self.assertEqual(len(experiences), 1)
                    self.assertEqual(
                        experiences[0].expected_outcome["action_variant"],
                        "git_update_index",
                    )

            candidates = resident.verified_experiences.candidate_tendencies()
            plumbing = [
                item
                for item in candidates
                if item.expected_kind == "git_path_staged"
                and item.applicability.get("stable_action_variant") == "git_update_index"
            ]
            self.assertEqual(len(plumbing), 1)
            candidate = plumbing[0]
            self.assertEqual(candidate.maturity_state, "supported")
            self.assertEqual(candidate.support_count, 3)

            target.write_text("learned-current-choice\n", encoding="utf-8")
            event = resident.enqueue(
                "stage stable repository path using current reality",
                payload={
                    "path": str(target),
                    "repo_path": str(root),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": str(target),
                    },
                    "model_policy": "never",
                    "required_capabilities": ["it/git", "filesystem"],
                },
            )
            self._advance_until_stage(resident, "native_action")
            investigation = resident.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            self.assertTrue(
                any(
                    candidate.tendency_id in item
                    and "supported by current independent evidence" in item
                    for item in investigation.evidence
                ),
                investigation.evidence,
            )

            state = resident.store.get_working_state()
            selected = NativeActionIntent.from_dict(state.data["native_action_intent"])
            self.assertEqual(
                selected.expected_outcome["action_variant"],
                "git_update_index",
            )
            influence = state.data.get("procedural_action_influence")
            self.assertIsInstance(influence, dict)
            self.assertEqual(influence["tendency_id"], candidate.tendency_id)
            self.assertFalse(influence["revoked"])

            result = self._run_to_terminal(resident)
            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            commands = [
                item
                for item in resident.body.recent_actions(80)
                if item.event_id == event.event_id and item.kind == "command"
            ]
            self.assertEqual(len(commands), 1)
            self.assertTrue(
                str(commands[0].data.get("command") or "").startswith(
                    "git update-index --add -- "
                )
            )
            self.assertEqual(
                self._git(root, "diff", "--name-only", "--", target.name),
                "",
            )
            self.assertEqual(
                self._git(root, "diff", "--cached", "--name-only", "--", target.name),
                target.name,
            )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()

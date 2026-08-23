from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent.kernel.action import NativeActionIntent, derive_native_action_intents
from agent.kernel.models import AgentEvent
from agent.kernel.procedural_influence import select_procedurally_influenced_intent
from agent.kernel.procedural_tendency import CandidateProceduralTendency


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

    def test_supported_variant_only_reorders_fresh_current_git_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "tracked.txt"
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

            candidate = self._candidate(root, target, variant="git_update_index")
            selected, influence = select_procedurally_influenced_intent(
                event,
                intents,
                candidates=(candidate,),
                current_domains=("it/git", "filesystem"),
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


if __name__ == "__main__":
    unittest.main()

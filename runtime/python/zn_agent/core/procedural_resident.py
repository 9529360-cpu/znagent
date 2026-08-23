from __future__ import annotations

"""Bounded L3 influence and resident-owned recovery over native choices.

This layer sits inside the active world-aware resident hierarchy. Ordinary
single-action deliberation is unchanged. Choice recovery can consume either an
explicit current ``native_action_options`` contract or a resident-formed choice
whose equivalence is proven from a typed task postcondition plus current
Investigation evidence. Procedural evidence may reorder eligible choices, but it
never supplies Body arguments, bypasses anti-replay, skips verification, or
becomes a fast path.
"""

import os
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .action import (
    NativeActionIntent,
    current_text_equals_postcondition,
    derive_native_action_intents,
)
from .git_semantics import (
    current_git_goal_from_intent,
    git_path_stage_state,
    git_stage_command,
    normalized_git_path,
)
from .procedural_influence import (
    ProceduralActionInfluence,
    select_procedurally_influenced_intent,
)
from .result_semantics import normalize_action_result
from .world_closed_loop import WorldAwareTransferResidentRuntime


class ProcedurallyInfluencedResidentRuntime(WorldAwareTransferResidentRuntime):
    """Active resident with reality-gated procedural and native choice behavior."""

    _PROCEDURAL_INFLUENCE_KEY = "procedural_action_influence"
    _PROCEDURAL_REVOKED_KEY = "procedural_revoked_tendencies"
    _NATIVE_CHOICE_RECOVERY_KEY = "native_choice_recovery"
    _REPO_TEXT_BASELINE_KEY = "native_repo_text_baseline"
    _TARGETED_TEST_EXECUTION_KEY = "native_targeted_test_execution"
    _RECOVERABLE_CHOICE_SOURCES = frozenset({"structured_choice", "resident_choice"})
    _MAX_PROCEDURAL_REVOKED = 8
    _TARGETED_TEST_KIND = "python_unittest"
    _TARGETED_TEST_DEFAULT_TIMEOUT = 120.0
    _TARGETED_TEST_MAX_TIMEOUT = 300.0

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        # Any prior recovery marker described the previous movement. It remains
        # visible through action/verification but cannot silently describe a new
        # deliberation cycle.
        state.data.pop(self._NATIVE_CHOICE_RECOVERY_KEY, None)

        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intents = derive_native_action_intents(event, facts=facts)
        if not intents:
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        candidates = self.verified_experiences.candidate_tendencies(limit=16)
        intent, influence = select_procedurally_influenced_intent(
            event,
            intents,
            candidates=candidates,
            current_domains=readiness.domains,
            facts=facts,
            revoked_tendency_ids=self._revoked_tendency_ids(state),
        )
        if intent is None or influence is None:
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            if self._recover_from_blocked_structured_choices(
                event,
                state,
                intents,
                thought=thought,
            ):
                return None
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        # Existing evidence-bound anti-replay remains stronger than learned
        # familiarity. A procedure that points at a movement already contradicted
        # under unchanged reality is immediately revoked for this event.
        if self._action_blocked_by_current_evidence(event, state, intent):
            self._activate_procedural_influence(state, influence)
            self._revoke_active_procedural_influence(
                state,
                reason="blocked_by_current_evidence",
            )
            # A later choice, if any, is a native recovery rather than a
            # procedurally selected movement. Keep only the event-local revoked
            # ID so failure cannot be misattributed to the old candidate.
            state.data.pop(self._PROCEDURAL_INFLUENCE_KEY, None)
            if self._recover_from_blocked_structured_choices(
                event,
                state,
                intents,
                thought=thought,
            ):
                return None
            self.store.save_working_state(state)
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        self._activate_procedural_influence(state, influence)
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = f"perform body action: {intent.kind}"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            known = (
                f"current reality-supported procedural candidate {influence.tendency_id} "
                f"strengthened an already-formed {intent.kind} choice"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; verified procedural evidence biased only among current "
                "ZN-owned action shapes, while current event data still supplies the movement"
            )
            self._persist_enriched_thought(thought)
        return None

    def _recover_from_blocked_structured_choices(
        self,
        event,
        state,
        intents: Iterable[NativeActionIntent],
        *,
        thought=None,
    ) -> bool:
        """Advance to a later proven choice after current evidence blocks one.

        The bounded choice must already exist in current ZN action formation.
        Explicit event choices are accepted as their own structured contract;
        resident choices are accepted only because ``action.py`` formed them
        from typed goal semantics plus current Investigation evidence. This
        method never infers alternatives from task text, memories, model text or
        failed action arguments.
        """

        current = tuple(intents)
        if len(current) < 2:
            return False
        sources = {str(intent.source or "") for intent in current}
        if len(sources) != 1 or not sources.issubset(self._RECOVERABLE_CHOICE_SOURCES):
            return False
        choice_source = next(iter(sources))

        blocked_count = 0
        for index, intent in enumerate(current):
            if self._action_blocked_by_current_evidence(event, state, intent):
                blocked_count += 1
                continue
            if blocked_count == 0:
                return False

            self._begin_native_action_cycle(event, state, intent)
            state.data[self._NATIVE_CHOICE_RECOVERY_KEY] = {
                "selected_index": index,
                "choice_count": len(current),
                "blocked_prior_choices": blocked_count,
                "action_kind": intent.kind,
                "choice_source": choice_source,
                "evidence_version": self._evidence_fingerprint(event.event_id)[:16],
            }
            self.store.save_working_state(state)
            if thought is not None:
                action = f"perform body action: {intent.kind}"
                if action not in thought.possible_actions:
                    thought.possible_actions = (*thought.possible_actions, action)
                known = (
                    f"current evidence blocked {blocked_count} earlier {choice_source} "
                    f"choice(s); choice {index + 1} remains admissible"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                thought.reason = (
                    f"{thought.reason}; current Investigation evidence ruled out earlier "
                    "bounded alternatives, so native deliberation selected the first "
                    "remaining structured choice"
                )
                self._persist_enriched_thought(thought)
            return True
        return False

    def _repo_text_scope(self, event, intent: NativeActionIntent) -> dict[str, str] | None:
        """Return one tracked Git scope for an already-authorized exact replacement."""

        if (
            intent.kind != "write_text"
            or bool(intent.args.get("append", False))
            or intent.source not in {"native_deliberation", "resident_choice"}
        ):
            return None
        contract = self._verification_contract(event, intent)
        if (
            not isinstance(contract, dict)
            or str(contract.get("kind") or "").strip().lower() != "text_equals"
            or str(contract.get("action_variant") or "").strip().lower() != "replace"
        ):
            return None

        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        git = facts.get("git") if isinstance(facts.get("git"), dict) else {}
        if git.get("available") is False:
            return None
        root_text = str(git.get("root") or "").strip()
        head = str(git.get("head") or "").strip()
        path_text = str(intent.args.get("path") or "").strip()
        if not root_text or not head or not path_text:
            return None

        try:
            root = Path(root_text).expanduser().resolve(strict=True)
            requested = Path(path_text).expanduser()
            candidate = requested if requested.is_absolute() else root / requested
            lexical = Path(os.path.abspath(str(candidate)))
            resolved = lexical.resolve(strict=True)
            if resolved != lexical:
                return None
            relative = normalized_git_path(resolved.relative_to(root).as_posix())
        except (OSError, RuntimeError, ValueError):
            return None
        if not relative:
            return None

        path_facts = facts.get("paths") if isinstance(facts.get("paths"), list) else []
        matching = None
        for item in path_facts:
            if not isinstance(item, dict):
                continue
            try:
                observed = Path(str(item.get("path") or "")).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                continue
            if observed == resolved:
                matching = item
                break
        if (
            not isinstance(matching, dict)
            or not bool(matching.get("exists"))
            or str(matching.get("type") or "").strip().lower() != "file"
        ):
            return None

        def git_paths(key: str) -> set[str]:
            raw = git.get(key)
            if not isinstance(raw, list):
                return set()
            return {
                normalized_git_path(item)
                for item in raw
                if normalized_git_path(item)
            }

        # The first repository-delta slice deliberately excludes index mutation,
        # conflicts and untracked-file semantics. Existing text verification
        # remains available for those cases; this stronger proof only claims the
        # tracked worktree replacement shape it can identify cleanly.
        if (
            relative in git_paths("staged_paths")
            or relative in git_paths("untracked_paths")
            or relative in git_paths("conflicted_paths")
        ):
            return None

        return {
            "root": str(root),
            "head": head,
            "path": str(resolved),
            "relative_path": relative,
        }

    @staticmethod
    def _literal_repo_relative_path(value: Any) -> str | None:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            return None
        path = PurePosixPath(text)
        parts = path.parts
        if (
            path.is_absolute()
            or not parts
            or path.as_posix() in {"", ".", "/"}
            or any(part == ".." for part in parts)
            or ":" in parts[0]
        ):
            return None
        return path.as_posix()

    @staticmethod
    def _targeted_test_requested(event) -> bool:
        expected = event.payload.get("expected_outcome")
        return isinstance(expected, dict) and expected.get("targeted_test") is not None

    def _repo_targeted_test_spec(
        self,
        event,
        scope: dict[str, str],
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = event.payload.get("expected_outcome")
        if not isinstance(expected, dict):
            return None, None
        raw = expected.get("targeted_test")
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            return None, "targeted_test must be a structured python_unittest identity"

        allowed = {"kind", "path", "for_path", "timeout", "workdir"}
        unknown = sorted(str(key) for key in raw if key not in allowed)
        if unknown:
            return None, (
                "targeted_test contains unsupported authority fields: "
                + ", ".join(unknown)
            )
        kind = str(raw.get("kind") or "").strip().lower()
        if kind != self._TARGETED_TEST_KIND:
            return None, "targeted_test kind must be python_unittest"

        for_relative = self._literal_repo_relative_path(raw.get("for_path"))
        if not for_relative or for_relative != scope["relative_path"]:
            return None, "targeted_test for_path must exactly match the mutation target"

        test_relative = self._literal_repo_relative_path(raw.get("path"))
        if not test_relative:
            return None, "targeted_test path must be one literal repository-relative path"
        test_path = PurePosixPath(test_relative)
        if (
            not test_path.parts
            or test_path.parts[0] != "tests"
            or not test_path.name.startswith("test_")
            or test_path.suffix != ".py"
        ):
            return None, "targeted_test path must name one tests/**/test_*.py file"
        if test_relative == scope["relative_path"]:
            return None, "targeted_test file must be distinct from the mutation target"

        try:
            root = Path(scope["root"]).expanduser().resolve(strict=True)
            lexical = Path(os.path.abspath(str(root / Path(test_relative))))
            resolved = lexical.resolve(strict=True)
            if resolved != lexical:
                return None, "targeted_test path aliases through a symlink"
            resolved.relative_to(root)
            if not resolved.is_file():
                return None, "targeted_test path is not a regular file"
        except (OSError, RuntimeError, ValueError):
            return None, "targeted_test path does not resolve to a current repository file"

        raw_workdir = raw.get("workdir")
        if raw_workdir is not None and str(raw_workdir).strip():
            try:
                requested = Path(str(raw_workdir)).expanduser()
                candidate = requested if requested.is_absolute() else root / requested
                resolved_workdir = candidate.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                return None, "targeted_test workdir does not resolve to the current Git root"
            if resolved_workdir != root:
                return None, "targeted_test workdir must resolve exactly to the current Git root"

        raw_timeout = raw.get("timeout", self._TARGETED_TEST_DEFAULT_TIMEOUT)
        if isinstance(raw_timeout, bool):
            return None, "targeted_test timeout must be numeric"
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            return None, "targeted_test timeout must be numeric"
        if not 0.05 <= timeout <= self._TARGETED_TEST_MAX_TIMEOUT:
            return None, "targeted_test timeout is outside the bounded verification range"

        return {
            "kind": self._TARGETED_TEST_KIND,
            "root": str(root),
            "head": scope["head"],
            "relative_path": test_relative,
            "for_relative_path": for_relative,
            "timeout": timeout,
        }, None

    def _observe_targeted_test_snapshot(
        self,
        event,
        spec: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        observed = self.body.act(
            "git_diff",
            event_id=event.event_id,
            path=str(spec.get("root") or ""),
            relative_path=str(spec.get("relative_path") or ""),
        )
        data = observed.data if isinstance(observed.data, dict) else {}
        worktree = data.get("worktree") if isinstance(data.get("worktree"), dict) else {}
        staged = data.get("staged") if isinstance(data.get("staged"), dict) else {}
        problems: list[str] = []
        if not observed.success:
            problems.append(observed.error or "targeted test Git evidence could not be observed")
        if observed.success and str(data.get("root") or "").strip() != str(spec.get("root") or ""):
            problems.append("targeted test repository root changed")
        if observed.success and str(data.get("head") or "").strip() != str(spec.get("head") or ""):
            problems.append("targeted test repository HEAD changed")
        if observed.success and str(data.get("scope_relative_path") or "") != str(
            spec.get("relative_path") or ""
        ):
            problems.append("targeted test evidence resolved a different path")
        if observed.success and data.get("scope_tracked") is not True:
            problems.append("targeted test file is not tracked")
        if observed.success and bool(data.get("truncated")):
            problems.append("targeted test Git evidence is truncated")
        if observed.success and list(worktree.get("paths") or ()):
            problems.append("targeted test file has unstaged changes")
        if observed.success and list(staged.get("paths") or ()):
            problems.append("targeted test file has staged changes")
        if observed.success and list(data.get("untracked_paths") or ()):
            problems.append("targeted test file became untracked")

        snapshot = {
            "kind": self._TARGETED_TEST_KIND,
            "root": str(spec.get("root") or ""),
            "head": str(spec.get("head") or ""),
            "relative_path": str(spec.get("relative_path") or ""),
            "for_relative_path": str(spec.get("for_relative_path") or ""),
            "timeout": float(spec.get("timeout") or self._TARGETED_TEST_DEFAULT_TIMEOUT),
            "state_sha256": str(data.get("state_sha256") or ""),
            "worktree_patch_sha256": str(worktree.get("patch_sha256") or ""),
            "staged_patch_sha256": str(staged.get("patch_sha256") or ""),
            "source_action_id": observed.action_id,
        }
        if observed.success and not all(
            snapshot[key]
            for key in (
                "state_sha256",
                "worktree_patch_sha256",
                "staged_patch_sha256",
            )
        ):
            problems.append("targeted test evidence is missing deterministic fingerprints")
        return snapshot, problems

    @staticmethod
    def _targeted_test_snapshot_matches(
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> bool:
        keys = (
            "kind",
            "root",
            "head",
            "relative_path",
            "for_relative_path",
            "timeout",
            "state_sha256",
            "worktree_patch_sha256",
            "staged_patch_sha256",
        )
        return all(expected.get(key) == observed.get(key) for key in keys)

    @staticmethod
    def _targeted_unittest_command(spec: dict[str, Any]) -> str:
        relative = PurePosixPath(str(spec.get("relative_path") or ""))
        args = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            relative.parent.as_posix(),
            "-p",
            relative.name,
        ]
        return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)

    def _fail_repo_text_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        problems: Iterable[str],
        *,
        thought=None,
    ) -> bool:
        failure = "repository mutation precondition failed: " + "; ".join(
            str(item) for item in problems if str(item)
        )
        state.data["local_failure"] = failure
        self._record_failed_action(
            event,
            state,
            intent,
            source="precondition",
            failure=failure,
        )
        if isinstance(state.data.get(self._PROCEDURAL_INFLUENCE_KEY), dict):
            self._revoke_active_procedural_influence(
                state,
                reason="repository_precondition",
            )
        state.stage = "native_investigation"
        state.next_action = "refresh repository evidence before another mutation"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; current repository evidence no longer proves a safe "
                "baseline for the selected file mutation"
            )
            self._persist_enriched_thought(thought)
        return False

    def _prepare_repo_text_baseline(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ) -> bool:
        scope = self._repo_text_scope(event, intent)
        if scope is None:
            state.data.pop(self._REPO_TEXT_BASELINE_KEY, None)
            if self._targeted_test_requested(event):
                return self._fail_repo_text_precondition(
                    event,
                    state,
                    intent,
                    [
                        "targeted test verification requires the current tracked exact-replacement contract"
                    ],
                    thought=thought,
                )
            return True

        observed = self.body.act(
            "git_diff",
            event_id=event.event_id,
            path=scope["root"],
            relative_path=scope["relative_path"],
        )
        data = observed.data if isinstance(observed.data, dict) else {}
        worktree = data.get("worktree") if isinstance(data.get("worktree"), dict) else {}
        staged = data.get("staged") if isinstance(data.get("staged"), dict) else {}
        problems: list[str] = []
        if not observed.success:
            problems.append(observed.error or "target-scoped Git baseline could not be observed")
        if observed.success and str(data.get("root") or "").strip() != scope["root"]:
            problems.append("repository root changed before mutation")
        if observed.success and str(data.get("head") or "").strip() != scope["head"]:
            problems.append("repository HEAD changed before mutation")
        if observed.success and str(data.get("scope_relative_path") or "") != scope["relative_path"]:
            problems.append("target-scoped Git baseline resolved a different path")
        if observed.success and data.get("scope_tracked") is not True:
            problems.append("target is not a tracked repository path")
        if observed.success and bool(data.get("truncated")):
            problems.append("target-scoped Git baseline is truncated")
        if observed.success and list(staged.get("paths") or ()):
            problems.append("target has staged changes outside the first worktree-delta contract")
        if observed.success and list(data.get("untracked_paths") or ()):
            problems.append("target became untracked before mutation")

        baseline = state.data.get(self._REPO_TEXT_BASELINE_KEY)
        same_intent = (
            isinstance(baseline, dict)
            and str(baseline.get("intent_id") or "") == intent.intent_id
        )
        current_snapshot: dict[str, Any] = {
            "intent_id": intent.intent_id,
            "root": scope["root"],
            "head": scope["head"],
            "relative_path": scope["relative_path"],
            "state_sha256": str(data.get("state_sha256") or ""),
            "worktree_patch_sha256": str(worktree.get("patch_sha256") or ""),
            "staged_patch_sha256": str(staged.get("patch_sha256") or ""),
            "source_action_id": observed.action_id,
        }
        if observed.success and not all(
            current_snapshot[key]
            for key in (
                "state_sha256",
                "worktree_patch_sha256",
                "staged_patch_sha256",
            )
        ):
            problems.append("target-scoped Git baseline is missing deterministic fingerprints")

        targeted_snapshot: dict[str, Any] | None = None
        if not problems:
            targeted_spec, targeted_error = self._repo_targeted_test_spec(event, scope)
            if targeted_error:
                problems.append(targeted_error)
            elif targeted_spec is not None:
                targeted_snapshot, targeted_problems = self._observe_targeted_test_snapshot(
                    event,
                    targeted_spec,
                )
                problems.extend(targeted_problems)
        current_snapshot["targeted_test"] = targeted_snapshot

        if same_intent and not problems:
            for key in (
                "root",
                "head",
                "relative_path",
                "state_sha256",
                "worktree_patch_sha256",
                "staged_patch_sha256",
            ):
                if str(baseline.get(key) or "") != str(current_snapshot[key]):
                    problems.append("repository baseline became stale before mutation")
                    break
            prior_targeted = baseline.get("targeted_test")
            if targeted_snapshot is None:
                if prior_targeted is not None:
                    problems.append("targeted test baseline became stale before mutation")
            elif not isinstance(prior_targeted, dict) or not self._targeted_test_snapshot_matches(
                prior_targeted,
                targeted_snapshot,
            ):
                problems.append("targeted test baseline became stale before mutation")

        if problems:
            return self._fail_repo_text_precondition(
                event,
                state,
                intent,
                problems,
                thought=thought,
            )

        if not same_intent:
            state.data[self._REPO_TEXT_BASELINE_KEY] = current_snapshot
            self._sync_execution_context(event, state)
            # Persist before movement so a restart cannot silently discard the
            # baseline. A resumed native_action pulse must re-observe and match
            # this exact scoped state before it is allowed to write.
            self.store.save_working_state(state)
        return True

    def _verification_contract(self, event, intent):
        """Verify current exact-text and bounded resident Git goals."""

        explicit = event.payload.get("expected_outcome")
        explicit_kind = (
            str(explicit.get("kind") or "").strip().lower()
            if isinstance(explicit, dict)
            else ""
        )
        if explicit_kind == "git_path_staged":
            goal = current_git_goal_from_intent(intent.expected_outcome)
            expected_command = (
                git_stage_command(goal["action_variant"], goal["relative_path"])
                if goal is not None
                else None
            )
            if (
                goal is None
                or intent.source != "resident_choice"
                or intent.kind != "command"
                or str(intent.args.get("workdir") or "").strip() != goal["root"]
                or str(intent.args.get("command") or "").strip() != expected_command
            ):
                return {
                    "kind": "unsupported",
                    "requested_kind": "git_path_staged",
                    "error": (
                        "resident Git staging postcondition requires the exact current "
                        "bounded resident choice and repository root"
                    ),
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                }
            return {
                **goal,
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }

        if explicit is not None:
            if explicit_kind == "text_equals":
                goal = current_text_equals_postcondition(event)
                if goal is None:
                    return {
                        "kind": "unsupported",
                        "requested_kind": "text_equals",
                        "error": "text_equals postcondition requires path and expected_text",
                        "intent_id": intent.intent_id,
                        "action_signature": self._intent_signature(intent),
                    }
                contract = {
                    **goal,
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                }
            else:
                contract = super()._verification_contract(event, intent)
        else:
            raw_goal = intent.expected_outcome
            if isinstance(raw_goal, dict) and str(
                raw_goal.get("kind") or ""
            ).strip().lower() == "text_equals":
                path = str(raw_goal.get("path") or "").strip()
                intent_path = str(intent.args.get("path") or "").strip()
                if (
                    intent.kind != "write_text"
                    or not path
                    or path != intent_path
                    or "expected_text" not in raw_goal
                ):
                    return {
                        "kind": "unsupported",
                        "requested_kind": "text_equals",
                        "error": "resident text postcondition must match the current write target",
                        "intent_id": intent.intent_id,
                        "action_signature": self._intent_signature(intent),
                    }
                contract = {
                    "kind": "text_equals",
                    "path": path,
                    "expected_text": str(raw_goal.get("expected_text") or ""),
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                }
            else:
                contract = super()._verification_contract(event, intent)

        if (
            isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == "text_equals"
            and intent.kind == "write_text"
        ):
            contract = dict(contract)
            contract["action_variant"] = (
                "append" if bool(intent.args.get("append", False)) else "replace"
            )
        return contract

    def _observe_repo_backed_text_replacement(
        self,
        event,
        baseline: dict[str, Any],
        *,
        path: str,
        expected: str,
    ):
        text_observation = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=path,
            max_chars=max(1, len(expected) + 1),
        )
        text_verified = bool(
            text_observation.success
            and not bool(text_observation.data.get("truncated"))
            and text_observation.output == expected
        )

        diff_observation = self.body.act(
            "git_diff",
            event_id=event.event_id,
            path=str(baseline.get("root") or ""),
            relative_path=str(baseline.get("relative_path") or ""),
        )
        diff_data = (
            diff_observation.data if isinstance(diff_observation.data, dict) else {}
        )
        worktree = (
            diff_data.get("worktree")
            if isinstance(diff_data.get("worktree"), dict)
            else {}
        )
        staged = (
            diff_data.get("staged")
            if isinstance(diff_data.get("staged"), dict)
            else {}
        )
        repo_delta = {
            "checked": True,
            "root_match": str(diff_data.get("root") or "") == str(baseline.get("root") or ""),
            "head_match": str(diff_data.get("head") or "") == str(baseline.get("head") or ""),
            "scope_match": str(diff_data.get("scope_relative_path") or "")
            == str(baseline.get("relative_path") or ""),
            "tracked": diff_data.get("scope_tracked") is True,
            "not_truncated": not bool(diff_data.get("truncated")),
            "index_unchanged": str(staged.get("patch_sha256") or "")
            == str(baseline.get("staged_patch_sha256") or ""),
            "worktree_changed": str(worktree.get("patch_sha256") or "")
            != str(baseline.get("worktree_patch_sha256") or ""),
            "state_changed": str(diff_data.get("state_sha256") or "")
            != str(baseline.get("state_sha256") or ""),
            "no_untracked_target": not bool(diff_data.get("untracked_paths")),
            "observation_success": bool(diff_observation.success),
            "baseline_state_sha256": str(baseline.get("state_sha256") or ""),
            "observed_state_sha256": str(diff_data.get("state_sha256") or ""),
        }
        repo_verified = bool(
            diff_observation.success
            and all(
                bool(repo_delta[key])
                for key in (
                    "root_match",
                    "head_match",
                    "scope_match",
                    "tracked",
                    "not_truncated",
                    "index_unchanged",
                    "worktree_changed",
                    "state_changed",
                    "no_untracked_target",
                )
            )
        )
        repo_delta["verified"] = repo_verified
        return (
            text_observation,
            diff_observation,
            text_verified,
            repo_verified,
            repo_delta,
        )

    @staticmethod
    def _repo_text_verification_problems(
        text_observation,
        diff_observation,
        *,
        text_verified: bool,
        repo_verified: bool,
        repo_delta: dict[str, Any],
    ) -> list[str]:
        problems: list[str] = []
        if not text_observation.success:
            problems.append(
                text_observation.error or "current text state could not be observed"
            )
        elif not text_verified:
            problems.append("requested text state does not match current reality")
        if not diff_observation.success:
            problems.append(
                diff_observation.error or "target-scoped repository state could not be observed"
            )
        elif not repo_verified:
            failed_checks = [
                key
                for key in (
                    "root_match",
                    "head_match",
                    "scope_match",
                    "tracked",
                    "not_truncated",
                    "index_unchanged",
                    "worktree_changed",
                    "state_changed",
                    "no_untracked_target",
                )
                if not bool(repo_delta[key])
            ]
            problems.append(
                "target-scoped repository delta contradicted baseline: "
                + ", ".join(failed_checks)
            )
        return problems

    def _verify_repo_backed_text_replacement(
        self,
        event,
        state,
        intent: NativeActionIntent,
        contract: dict[str, Any],
        baseline: dict[str, Any],
        *,
        thought=None,
    ):
        path = str(contract.get("path") or "")
        expected = str(contract.get("expected_text") or "")
        (
            text_observation,
            diff_observation,
            text_verified,
            repo_verified,
            repo_delta,
        ) = self._observe_repo_backed_text_replacement(
            event,
            baseline,
            path=path,
            expected=expected,
        )

        problems = self._repo_text_verification_problems(
            text_observation,
            diff_observation,
            text_verified=text_verified,
            repo_verified=repo_verified,
            repo_delta=repo_delta,
        )
        targeted_requested = self._targeted_test_requested(event)
        targeted_baseline = baseline.get("targeted_test")
        targeted_result: dict[str, Any] | None = None
        final_text_observation = text_observation
        final_diff_observation = diff_observation
        final_text_verified = text_verified
        final_repo_verified = repo_verified
        final_repo_delta = repo_delta

        if targeted_requested:
            if not isinstance(targeted_baseline, dict):
                problems.append("targeted test baseline is missing from durable mutation state")
            elif not problems:
                targeted_pre, targeted_pre_problems = self._observe_targeted_test_snapshot(
                    event,
                    targeted_baseline,
                )
                if not targeted_pre_problems and not self._targeted_test_snapshot_matches(
                    targeted_baseline,
                    targeted_pre,
                ):
                    targeted_pre_problems.append(
                        "targeted test file evidence became stale before execution"
                    )
                problems.extend(targeted_pre_problems)
                targeted_result = {
                    "kind": self._TARGETED_TEST_KIND,
                    "relative_path": str(targeted_baseline.get("relative_path") or ""),
                    "for_relative_path": str(
                        targeted_baseline.get("for_relative_path") or ""
                    ),
                    "precondition_action_id": targeted_pre.get("source_action_id"),
                    "execution_action_id": None,
                    "postcondition_action_id": None,
                    "observed_exit_code": None,
                    "timed_out": False,
                    "result_features": None,
                    "verified": False,
                }

                if not problems:
                    prior_execution = state.data.get(self._TARGETED_TEST_EXECUTION_KEY)
                    if (
                        isinstance(prior_execution, dict)
                        and str(prior_execution.get("intent_id") or "") == intent.intent_id
                    ):
                        problems.append(
                            "targeted unittest execution may already have started; refusing replay after interruption"
                        )
                    else:
                        state.data[self._TARGETED_TEST_EXECUTION_KEY] = {
                            "intent_id": intent.intent_id,
                            "kind": self._TARGETED_TEST_KIND,
                            "state_sha256": str(
                                targeted_baseline.get("state_sha256") or ""
                            ),
                            "status": "started",
                            "action_id": None,
                        }
                        self._sync_execution_context(event, state)
                        # Persist before the potentially side-effecting verifier.
                        # If the process dies after this point, a resumed pulse
                        # fails closed instead of executing the same test twice.
                        self.store.save_working_state(state)

                        command = self._targeted_unittest_command(targeted_baseline)
                        test_observation = self.body.act(
                            "command",
                            event_id=event.event_id,
                            command=command,
                            workdir=str(targeted_baseline.get("root") or ""),
                            timeout=float(
                                targeted_baseline.get("timeout")
                                or self._TARGETED_TEST_DEFAULT_TIMEOUT
                            ),
                            max_output_chars=50_000,
                        )
                        result_features = normalize_action_result(
                            asdict(test_observation),
                            command=command,
                        )
                        exit_code = test_observation.data.get("exit_code")
                        timed_out = bool(test_observation.data.get("timed_out", False))
                        test_verified = bool(
                            test_observation.success
                            and not timed_out
                            and exit_code == 0
                            and not bool(result_features.get("masked_success"))
                            and not result_features.get("failure_class")
                        )
                        state.data[self._TARGETED_TEST_EXECUTION_KEY] = {
                            "intent_id": intent.intent_id,
                            "kind": self._TARGETED_TEST_KIND,
                            "state_sha256": str(
                                targeted_baseline.get("state_sha256") or ""
                            ),
                            "status": "completed",
                            "action_id": test_observation.action_id,
                            "verified": test_verified,
                        }
                        self._sync_execution_context(event, state)
                        # Record completion before any later verifier can crash.
                        # Restart still refuses replay; current execution may
                        # continue using the Body result already in memory.
                        self.store.save_working_state(state)
                        targeted_result.update(
                            {
                                "execution_action_id": test_observation.action_id,
                                "observed_exit_code": exit_code,
                                "timed_out": timed_out,
                                "result_features": result_features,
                                "verified": test_verified,
                            }
                        )
                        if not test_verified:
                            if timed_out:
                                problems.append("targeted unittest timed out")
                            elif exit_code != 0:
                                problems.append(
                                    f"targeted unittest exited with code {exit_code}"
                                )
                            elif result_features.get("masked_success"):
                                problems.append("targeted unittest shell status was masked")
                            elif result_features.get("failure_class"):
                                problems.append(
                                    "targeted unittest emitted deterministic failure evidence: "
                                    + str(result_features.get("failure_class"))
                                )
                            else:
                                problems.append("targeted unittest did not complete successfully")

                        if test_verified:
                            (
                                final_text_observation,
                                final_diff_observation,
                                final_text_verified,
                                final_repo_verified,
                                final_repo_delta,
                            ) = self._observe_repo_backed_text_replacement(
                                event,
                                baseline,
                                path=path,
                                expected=expected,
                            )
                            problems.extend(
                                self._repo_text_verification_problems(
                                    final_text_observation,
                                    final_diff_observation,
                                    text_verified=final_text_verified,
                                    repo_verified=final_repo_verified,
                                    repo_delta=final_repo_delta,
                                )
                            )
                            targeted_post, targeted_post_problems = (
                                self._observe_targeted_test_snapshot(
                                    event,
                                    targeted_baseline,
                                )
                            )
                            if (
                                not targeted_post_problems
                                and not self._targeted_test_snapshot_matches(
                                    targeted_baseline,
                                    targeted_post,
                                )
                            ):
                                targeted_post_problems.append(
                                    "targeted test file evidence changed during execution"
                                )
                            problems.extend(targeted_post_problems)
                            targeted_result["postcondition_action_id"] = targeted_post.get(
                                "source_action_id"
                            )
                            targeted_result["verified"] = bool(
                                targeted_result["verified"]
                                and final_text_verified
                                and final_repo_verified
                                and not targeted_post_problems
                            )
        elif isinstance(targeted_baseline, dict):
            problems.append("unexpected targeted test baseline without a current typed request")

        verified = bool(
            final_text_verified
            and final_repo_verified
            and not problems
            and (
                not targeted_requested
                or bool(targeted_result and targeted_result.get("verified"))
            )
        )
        verification_result = {
            "verified": verified,
            "kind": "text_equals",
            "path": path,
            "expected_chars": len(expected),
            "observed_chars": (
                int(
                    final_text_observation.data.get("chars")
                    or len(final_text_observation.output)
                )
                if final_text_observation.success
                else None
            ),
            "observation": asdict(final_text_observation),
            "repo_delta": final_repo_delta,
            "repo_observation_action_id": final_diff_observation.action_id,
            "targeted_test": targeted_result,
        }
        state.data["native_verification_result"] = verification_result
        self._record_verified_experience(
            event,
            state,
            intent,
            verification_result=verification_result,
        )
        self._sync_execution_context(event, state)

        if verified:
            reason = (
                "ZN completed the tracked text replacement only after fresh text, a "
                "target-scoped Git delta, a resident-derived targeted unittest, and a "
                "post-test current-reality recheck all matched durable evidence"
                if targeted_requested
                else (
                    "ZN completed the tracked text replacement only after fresh text "
                    "observation and a target-scoped Git delta both matched the persisted baseline"
                )
            )
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=path,
                reason=reason,
            )

        failure = "postcondition verification failed for tracked text replacement: " + "; ".join(
            problems or ["current reality did not prove the requested mutation"]
        )
        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _native_verification_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_contract = state.data.get("native_verification")
        raw_baseline = state.data.get(self._REPO_TEXT_BASELINE_KEY)
        raw_intent = state.data.get("native_action_intent")
        if (
            isinstance(raw_contract, dict)
            and str(raw_contract.get("kind") or "").strip().lower() == "text_equals"
            and isinstance(raw_baseline, dict)
            and isinstance(raw_intent, dict)
        ):
            intent = NativeActionIntent.from_dict(raw_intent)
            if (
                intent.kind == "write_text"
                and not bool(intent.args.get("append", False))
                and str(raw_baseline.get("intent_id") or "") == intent.intent_id
            ):
                return self._verify_repo_backed_text_replacement(
                    event,
                    state,
                    intent,
                    raw_contract,
                    raw_baseline,
                    thought=thought,
                )

        if not isinstance(raw_contract, dict) or str(
            raw_contract.get("kind") or ""
        ).strip().lower() != "git_path_staged":
            return super()._native_verification_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        if not isinstance(raw_intent, dict):
            state.stage = "native_deliberation"
            state.next_action = "reconstruct missing postcondition verification"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent.from_dict(raw_intent)
        goal = current_git_goal_from_intent(raw_contract)
        if goal is None:
            failure = "bounded Git staging verification contract is incomplete"
            verification_result = {
                "verified": False,
                "kind": "git_path_staged",
                "error": failure,
            }
            state.data["native_verification_result"] = verification_result
            self._sync_execution_context(event, state)
            return self._fail_postcondition_verification(
                event,
                state,
                intent,
                failure=failure,
                thought=thought,
            )

        observed = self.body.act(
            "git_state",
            event_id=event.event_id,
            path=goal["root"],
        )
        stage_state = (
            git_path_stage_state(observed.data, goal["relative_path"])
            if observed.success
            else None
        )
        verified = bool(stage_state is not None and stage_state["satisfied"])
        verification_result = {
            "verified": verified,
            "kind": "git_path_staged",
            "path": goal["path"],
            "root": goal["root"],
            "relative_path": goal["relative_path"],
            "action_variant": goal["action_variant"],
            "staged": bool(stage_state and stage_state["staged"]),
            "unstaged": bool(stage_state and stage_state["unstaged"]),
            "untracked": bool(stage_state and stage_state["untracked"]),
            "conflicted": bool(stage_state and stage_state["conflicted"]),
            "observation": asdict(observed),
        }
        state.data["native_verification_result"] = verification_result
        self._record_verified_experience(
            event,
            state,
            intent,
            verification_result=verification_result,
        )
        self._sync_execution_context(event, state)

        if verified:
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=goal["relative_path"],
                reason=(
                    "ZN completed the task only after a fresh structured Git observation "
                    "proved the target path is staged and matches the current worktree"
                ),
            )

        failure = (
            "postcondition Git staging verification failed: fresh repository state did not "
            "show the target exclusively staged"
            if observed.success
            else "postcondition Git staging verification failed: "
            + str(observed.error or "current repository state could not be observed")
        )
        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_intent = state.data.get("native_action_intent")
        if isinstance(raw_intent, dict):
            intent = NativeActionIntent.from_dict(raw_intent)
            if not self._prepare_repo_text_baseline(
                event,
                state,
                intent,
                thought=thought,
            ):
                return None

        result = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if state.stage == "native_investigation" and isinstance(
            state.data.get(self._PROCEDURAL_INFLUENCE_KEY),
            dict,
        ):
            self._revoke_active_procedural_influence(state, reason="body_failure")
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
        return result

    def _fail_postcondition_verification(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ):
        if isinstance(state.data.get(self._PROCEDURAL_INFLUENCE_KEY), dict):
            self._revoke_active_procedural_influence(
                state,
                reason="verification_contradiction",
            )
        return super()._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _enrich_thought_with_working_stage(self, thought, event) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return

        recovery = state.data.get(self._NATIVE_CHOICE_RECOVERY_KEY)
        if isinstance(recovery, dict):
            try:
                selected_index = int(recovery.get("selected_index"))
                blocked = int(recovery.get("blocked_prior_choices") or 0)
            except (TypeError, ValueError):
                selected_index = -1
                blocked = 0
            action_kind = str(recovery.get("action_kind") or "unknown").strip() or "unknown"
            choice_source = str(
                recovery.get("choice_source") or "structured_choice"
            ).strip() or "structured_choice"
            if selected_index >= 0 and blocked > 0:
                known = (
                    f"native choice recovery selected {choice_source} choice {selected_index + 1} "
                    f"({action_kind}) after current evidence blocked {blocked} earlier choice(s)"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)

        raw = state.data.get(self._PROCEDURAL_INFLUENCE_KEY)
        if not isinstance(raw, dict):
            return
        tendency_id = str(raw.get("tendency_id") or "").strip()
        action_kind = str(raw.get("action_kind") or "unknown").strip() or "unknown"
        if not tendency_id:
            return
        if bool(raw.get("revoked")):
            known = (
                f"procedural candidate {tendency_id} was revoked for this event after "
                "current action evidence contradicted its route"
            )
        else:
            known = (
                f"procedural candidate {tendency_id} currently biases the already-formed "
                f"{action_kind} choice; it does not supply action arguments or waive verification"
            )
        if known not in thought.known:
            thought.known = (*thought.known, known)

    def _activate_procedural_influence(
        self,
        state,
        influence: ProceduralActionInfluence,
    ) -> None:
        data = influence.to_dict()
        data["revoked"] = False
        data["revocation_reason"] = None
        state.data[self._PROCEDURAL_INFLUENCE_KEY] = data

    def _revoke_active_procedural_influence(self, state, *, reason: str) -> None:
        raw = state.data.get(self._PROCEDURAL_INFLUENCE_KEY)
        if not isinstance(raw, dict):
            return
        tendency_id = str(raw.get("tendency_id") or "").strip()
        if not tendency_id:
            return
        revoked = list(self._revoked_tendency_ids(state))
        if tendency_id not in revoked:
            revoked.append(tendency_id)
        state.data[self._PROCEDURAL_REVOKED_KEY] = revoked[-self._MAX_PROCEDURAL_REVOKED :]
        updated: dict[str, Any] = dict(raw)
        updated["revoked"] = True
        updated["revocation_reason"] = str(reason or "current_evidence")[:80]
        state.data[self._PROCEDURAL_INFLUENCE_KEY] = updated

    def _revoked_tendency_ids(self, state) -> tuple[str, ...]:
        raw = state.data.get(self._PROCEDURAL_REVOKED_KEY)
        if not isinstance(raw, list):
            return ()
        return tuple(
            str(item)
            for item in raw[-self._MAX_PROCEDURAL_REVOKED :]
            if str(item).strip()
        )

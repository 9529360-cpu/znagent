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
from dataclasses import asdict
from pathlib import Path
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
from .world_closed_loop import WorldAwareTransferResidentRuntime


class ProcedurallyInfluencedResidentRuntime(WorldAwareTransferResidentRuntime):
    """Active resident with reality-gated procedural and native choice behavior."""

    _PROCEDURAL_INFLUENCE_KEY = "procedural_action_influence"
    _PROCEDURAL_REVOKED_KEY = "procedural_revoked_tendencies"
    _NATIVE_CHOICE_RECOVERY_KEY = "native_choice_recovery"
    _REPO_TEXT_BASELINE_KEY = "native_repo_text_baseline"
    _RECOVERABLE_CHOICE_SOURCES = frozenset({"structured_choice", "resident_choice"})
    _MAX_PROCEDURAL_REVOKED = 8

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
        current_snapshot = {
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

        if same_intent and not problems:
            for key in (
                "root",
                "head",
                "relative_path",
                "state_sha256",
                "worktree_patch_sha256",
                "staged_patch_sha256",
            ):
                if str(baseline.get(key) or "") != current_snapshot[key]:
                    problems.append("repository baseline became stale before mutation")
                    break

        if problems:
            failure = "repository mutation precondition failed: " + "; ".join(problems)
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
        verified = bool(text_verified and repo_verified)
        verification_result = {
            "verified": verified,
            "kind": "text_equals",
            "path": path,
            "expected_chars": len(expected),
            "observed_chars": (
                int(text_observation.data.get("chars") or len(text_observation.output))
                if text_observation.success
                else None
            ),
            "observation": asdict(text_observation),
            "repo_delta": repo_delta,
            "repo_observation_action_id": diff_observation.action_id,
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
                response=path,
                reason=(
                    "ZN completed the tracked text replacement only after fresh text "
                    "observation and a target-scoped Git delta both matched the persisted baseline"
                ),
            )

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

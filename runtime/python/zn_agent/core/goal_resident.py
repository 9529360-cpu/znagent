from __future__ import annotations

"""Resident-owned continuation for bounded multi-step world-state goals.

A verified Body movement is not automatically a completed user goal. This layer
keeps typed composite goals alive across multiple verified movements, clears
stale action evidence after each substep, and forces a fresh observation before
deciding what to do next. It deliberately owns no generic planner and stores no
replayable action sequence.
"""

from dataclasses import asdict, replace
from typing import Any

from .browser_form_submit_resident import BrowserFormSubmitResidentRuntime
from .browser_named_goal import (
    browser_named_text_intent,
    browser_named_text_request,
    browser_named_text_state,
)
from .browser_named_target_sense import NativeBrowserNamedTargetSense
from .focused_text_sense import NativeFocusedTextSense
from .keyboard_text_body import KeyboardTextBody
from .models import ExecutionPath, utc_now
from .repo_goal import (
    repo_text_staged_action_intents,
    repo_text_staged_request,
    repo_text_staged_state,
)


class ResidentGoalRuntime(BrowserFormSubmitResidentRuntime):
    """Continue one typed goal until fresh reality proves the whole goal complete."""

    _RESIDENT_GOAL_PROGRESS_KEY = "resident_goal_progress"
    _BROWSER_GOAL_OBSERVATION_KEY = "resident_browser_goal_observation"
    _BROWSER_GOAL_BINDING_KEY = "resident_browser_goal_binding"
    _BROWSER_GOAL_FOCUS_VERIFICATION_KEY = "resident_browser_goal_focus_verification"
    _MAX_RESIDENT_GOAL_PROGRESS = 16

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.browser_named_target = NativeBrowserNamedTargetSense()

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        """Do not let a satisfied subcondition terminate a composite goal."""

        if browser_named_text_request(event) is not None:
            return self._browser_named_goal_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        if repo_text_staged_request(event) is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        local_failure = str(state.data.get("local_failure") or "").strip() or None
        investigation = self.investigator.investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        goal_state = repo_text_staged_state(event, investigation.state.facts)

        if investigation.resolved and not bool(goal_state and goal_state.get("satisfied")):
            following = self.investigator._choose_next_probe(
                event,
                readiness,
                facts=investigation.state.facts,
                performed=set(investigation.state.probe_keys),
                learning_evidence=learning_evidence,
            )
            investigation.state.status = "open"
            investigation.state.resolution = None
            investigation.state.unresolved = (
                str((goal_state or {}).get("blocked") or "").strip()
                or "the complete resident goal still has an unsatisfied subcondition"
            )
            investigation.state.next_probe = following
            investigation.state.updated_at = utc_now()
            self.investigator._save(investigation.state)
            investigation.resolved = False
            investigation.response = ""
            investigation.can_continue = bool(following)

        state.data["native_investigation"] = self._investigation_data(investigation.state)
        self._merge_investigation_into_thought(thought, investigation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        goal_state = repo_text_staged_state(event, investigation.state.facts)
        if goal_state is not None and goal_state.get("satisfied"):
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=(
                    f"{goal_state['path']}: requested repository text and staged state "
                    "are both satisfied"
                ),
                reason=(
                    "ZN completed the multi-step resident goal only after fresh file-content "
                    "and structured Git observations simultaneously proved the final state"
                ),
            )

        if investigation.can_continue:
            state.stage = "native_investigation"
            state.next_action = f"run native probe {investigation.state.next_probe}"
            self.store.save_working_state(state)
            return None

        state.stage = "native_deliberation"
        state.next_action = "form the next bounded movement from current goal evidence"
        self.store.save_working_state(state)
        return None

    def _browser_named_goal_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        request = browser_named_text_request(event)
        assert request is not None
        try:
            target = self.browser_named_target.probe_exact_edit(request["target_name"])
        except Exception as exc:
            reason = (
                "current foreground user-browser investigation could not prove one unique safe "
                f"exact-name Edit target: {type(exc).__name__}: {exc}"
            )
            return self._fail_composite_goal_investigation(event, state, reason=reason)

        binding = state.data.get(self._BROWSER_GOAL_BINDING_KEY)
        current_binding = {
            "process_name": target.process_name,
            "foreground_title": target.foreground_title,
        }
        if binding is None:
            state.data[self._BROWSER_GOAL_BINDING_KEY] = dict(current_binding)
        elif not isinstance(binding, dict) or any(
            str(binding.get(key) or "") != str(value)
            for key, value in current_binding.items()
        ):
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "foreground browser identity changed during the bounded named-text goal; "
                    "refusing to transfer input authority to a different window"
                ),
            )

        text_observation = None
        if target.has_keyboard_focus:
            try:
                text_observation = self.automation_text_state.probe()
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the exact named browser target is focused but fresh privacy-safe text "
                        f"evidence is unavailable: {type(exc).__name__}: {exc}"
                    ),
                )

        goal_state = browser_named_text_state(event, target, text_observation)
        assert goal_state is not None
        state.data[self._BROWSER_GOAL_OBSERVATION_KEY] = {
            "goal_state": dict(goal_state),
            "target": asdict(target),
            "text": asdict(text_observation) if text_observation is not None else None,
            "observed_at": utc_now(),
        }
        state.data.pop("local_failure", None)

        if thought is not None:
            known = (
                "fresh foreground-browser UI Automation evidence identified exactly one "
                "user-named safe Edit target"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; current browser reality places the composite goal in "
                f"phase={goal_state['phase']}"
            )
            self._persist_enriched_thought(thought)

        if goal_state["satisfied"]:
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=(
                    f"foreground browser target {request['target_name']!r} contains the "
                    "requested text"
                ),
                reason=(
                    "ZN completed the user-browser goal only after fresh exact-name target "
                    "identity and privacy-safe focused text digest evidence simultaneously "
                    "proved the requested final state"
                ),
            )

        blocked = str(goal_state.get("blocked") or "").strip()
        if blocked:
            return self._fail_composite_goal_investigation(event, state, reason=blocked)

        state.stage = "native_deliberation"
        state.next_action = (
            "form one bounded browser focus movement from current evidence"
            if goal_state["phase"] == "needs_focus"
            else "form one bounded browser text movement from current evidence"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_goal_from_fresh_investigation(
        self,
        event,
        state,
        *,
        readiness,
        response: str,
        reason: str,
    ):
        domains = self.kernel.self_model.infer_domains(
            event.task,
            self._required_capabilities(event),
        )
        completion = {
            "execution_path": ExecutionPath.INVESTIGATION.value,
            "success": True,
            "response": str(response),
            "model_invocations": 0,
            "reason": str(reason),
        }
        state.stage = "investigation_completion"
        state.next_action = "publish terminal EventOutcome"
        state.data["native_domains"] = list(domains)
        state.data["investigation_completion"] = completion
        state.data[self._INVESTIGATION_COMPLETION_ACCOUNTING_KEY] = {
            "version": self._ACCOUNTING_VERSION,
            "kind": "native_investigation_success",
            "domains": list(domains),
            "quality": 0.95,
        }
        self.store.save_working_state(state)
        self._apply_investigation_completion_accounting(event, state)
        return self._investigation_completion_result(event, completion)

    def _fail_composite_goal_investigation(self, event, state, *, reason: str):
        state.data["local_failure"] = str(reason)
        state.stage = "native_investigation"
        state.next_action = "stop before input and surface the current browser-goal evidence gap"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        self.life.begin_impasse(
            event,
            reason=str(reason),
            required_capabilities=self._required_capabilities(event),
            local_failure=str(reason),
        )
        return self._checkpoint_terminal_failure(event, state, reason=str(reason))

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        browser_request = browser_named_text_request(event)
        if browser_request is not None:
            raw_observation = state.data.get(self._BROWSER_GOAL_OBSERVATION_KEY)
            goal_state = (
                raw_observation.get("goal_state")
                if isinstance(raw_observation, dict)
                else None
            )
            if not isinstance(goal_state, dict):
                state.stage = "native_investigation"
                state.next_action = "re-observe the exact named browser target"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            intent = browser_named_text_intent(event, goal_state)
            if intent is None:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        str(goal_state.get("blocked") or "").strip()
                        or "fresh browser goal evidence did not form a safe next movement"
                    ),
                )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform user-browser goal substep through body: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; fresh exact target evidence formed only the current "
                        "browser movement and did not precommit the later substep"
                    )
                    self._persist_enriched_thought(thought)
                return None
            return None

        request = repo_text_staged_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        goal_state = repo_text_staged_state(event, facts)
        intents = repo_text_staged_action_intents(event, facts)

        if goal_state is not None and goal_state.get("satisfied"):
            state.stage = "native_investigation"
            state.next_action = "reconfirm the complete resident goal from current reality"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if intents:
            intent = intents[0]
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform goal substep through body: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    known = (
                        "the current resident goal still has an independently observable "
                        "unsatisfied subcondition"
                    )
                    if known not in thought.known:
                        thought.known = (*thought.known, known)
                    thought.reason = (
                        f"{thought.reason}; current evidence formed one bounded next movement "
                        "without precommitting the later goal steps"
                    )
                    self._persist_enriched_thought(thought)
                return None

        blocked = str((goal_state or {}).get("blocked") or "").strip()
        reason = blocked or (
            "current Investigation exhausted its probes without proving a safe next "
            "movement for the typed resident goal"
        )
        self.life.begin_impasse(
            event,
            reason=reason,
            required_capabilities=self._required_capabilities(event),
            local_failure=None,
        )
        return self._checkpoint_terminal_failure(event, state, reason=reason)

    def _pointer_click_contract(self, event, intent):
        request = browser_named_text_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "pointer_click"
            and str(raw_goal.get("kind") or "").strip().lower()
            == "browser_named_target_focused"
        ):
            scope: dict[str, Any] = {
                "kind": self._AUTOMATION_SCOPE_KIND,
                "process_name": str(raw_goal.get("process_name") or "").strip().lower(),
                "title_equals": str(raw_goal.get("title_equals") or "").strip(),
                "control_type": int(raw_goal.get("control_type") or 0),
            }
            class_name = str(raw_goal.get("class_name_equals") or "").strip()
            if class_name:
                scope["class_name_equals"] = class_name
            return {
                "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
                "center_x_fraction": float(intent.args["x_fraction"]),
                "center_y_fraction": float(intent.args["y_fraction"]),
                "width_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                "height_fraction": self._POINTER_CLICK_DEFAULT_REGION,
                "completion_scope": scope,
                "completion_event_kind": str(event.kind or "").strip().lower(),
                "action_precondition": {
                    "kind": self._UI_SCOPE_KIND,
                    "process_name": scope["process_name"],
                    "title_equals": scope["title_equals"],
                },
            }, None
        return super()._pointer_click_contract(event, intent)

    def _keyboard_text_contract(self, event, intent):
        request = browser_named_text_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "keyboard_text"
            and str(raw_goal.get("kind") or "").strip().lower()
            == "browser_named_text_equals"
        ):
            try:
                text, units = KeyboardTextBody.validate_text(intent.args.get("text"))
            except ValueError as exc:
                return None, str(exc)
            if text != request["text"]:
                return None, "browser goal text drifted from the current user-owned goal"
            expected_sha = NativeFocusedTextSense.digest_text(text)
            if (
                expected_sha != str(raw_goal.get("expected_text_sha256") or "")
                or len(text) != int(raw_goal.get("expected_text_chars") or -1)
            ):
                return None, "browser goal text digest authority drifted before input"
            scope = {
                "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
                "process_name": str(raw_goal.get("process_name") or "").strip().lower(),
                "title_equals": str(raw_goal.get("title_equals") or "").strip(),
                "control_type": int(raw_goal.get("control_type") or 0),
                "class_name_equals": str(raw_goal.get("class_name_equals") or "").strip(),
                "automation_id_equals": str(raw_goal.get("automation_id_equals") or "").strip(),
            }
            return {
                "kind": self._TEXT_OUTCOME_KIND,
                "text": text,
                "utf16_units": len(units),
                "expected_text_chars": len(text),
                "expected_text_sha256": expected_sha,
                "completion_scope": scope,
                "completion_event_kind": self._UI_EVENT_KIND,
                "action_precondition": {
                    "kind": self._UI_SCOPE_KIND,
                    "process_name": scope["process_name"],
                    "title_equals": scope["title_equals"],
                },
            }, None
        return super()._keyboard_text_contract(event, intent)

    def _verification_contract(self, event, intent, *, result=None):
        request = repo_text_staged_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "command"
            and intent.source == "resident_choice"
            and str(raw_goal.get("kind") or "").strip().lower() == "git_path_staged"
        ):
            staged_event = replace(
                event,
                payload={
                    **dict(event.payload or {}),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": request["path"],
                    },
                },
            )
            return super()._verification_contract(
                staged_event,
                intent,
                result=result,
            )
        return super()._verification_contract(event, intent, result=result)

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        """Treat a verified movement as progress until the composite goal is re-sensed."""

        is_repo_goal = repo_text_staged_request(event) is not None
        browser_request = browser_named_text_request(event)
        is_browser_goal = browser_request is not None
        if not is_repo_goal and not is_browser_goal:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        verification = state.data.get("native_verification_result")
        if not isinstance(verification, dict) or verification.get("verified") is not True:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        progress_verification_kind = str(verification.get("kind") or "")
        if is_browser_goal and intent.kind == "pointer_click":
            raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
            expected_runtime = raw_goal.get("target_runtime_id")
            if not isinstance(expected_runtime, list) or not expected_runtime:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the already-dispatched browser focus click lost its exact pre-click "
                        "RuntimeId evidence; refusing any replay"
                    ),
                )
            try:
                assert browser_request is not None
                focused = self.browser_named_target.probe_exact_edit(
                    browser_request["target_name"]
                )
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the browser focus click was already dispatched, but fresh exact-name "
                        "focus verification is unavailable; refusing any replay: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            focus_verified = bool(
                focused.has_keyboard_focus
                and tuple(focused.runtime_id)
                == tuple(int(value) for value in expected_runtime)
                and focused.process_name
                == str(raw_goal.get("process_name") or "").strip().lower()
                and focused.foreground_title
                == str(raw_goal.get("title_equals") or "").strip()
            )
            state.data[self._BROWSER_GOAL_FOCUS_VERIFICATION_KEY] = {
                "verified": focus_verified,
                "kind": "browser_named_target_focused",
                "expected_runtime_id": [int(value) for value in expected_runtime],
                "observed_runtime_id": list(focused.runtime_id),
                "observation": asdict(focused),
                "verified_at": utc_now(),
            }
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            if not focus_verified:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the browser focus click was already dispatched and its local visual "
                        "effect was observed, but fresh exact-name UI Automation evidence did "
                        "not prove that the same target gained focus; refusing automatic replay"
                    ),
                )
            progress_verification_kind = "browser_named_target_focused"

        latest = state.data.get("latest_verified_experience")
        experience_id = (
            str(latest.get("experience_id") or "").strip()
            if isinstance(latest, dict)
            else ""
        )
        raw_progress = state.data.get(self._RESIDENT_GOAL_PROGRESS_KEY)
        progress = list(raw_progress) if isinstance(raw_progress, list) else []
        progress.append(
            {
                "action_kind": str(intent.kind or ""),
                "verification_kind": progress_verification_kind,
                "experience_id": experience_id or None,
                "verified_at": utc_now(),
            }
        )
        state.data[self._RESIDENT_GOAL_PROGRESS_KEY] = progress[
            -self._MAX_RESIDENT_GOAL_PROGRESS :
        ]

        self._reset_investigation_after_goal_substep(event, state, intent)
        state.stage = "native_investigation"
        state.next_action = "re-sense the composite goal after the verified substep"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _reset_investigation_after_goal_substep(self, event, state, intent) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is not None:
            investigation.updated_at = utc_now()
            investigation.probes = ()
            investigation.probe_keys = ()
            investigation.facts = {}
            investigation.unresolved = None
            investigation.next_probe = None
            investigation.status = "open"
            investigation.resolution = None
            investigation.evidence = (
                *investigation.evidence,
                f"verified resident-goal substep completed: {intent.kind}; re-sensing current reality",
            )[-64:]
            self.investigator._save(investigation)

        for key in (
            "native_investigation",
            "native_deliberation",
            "native_action_intent",
            "native_action_result",
            "native_verification",
            "native_verification_result",
            "native_completion",
            "local_failure",
            self._BROWSER_GOAL_OBSERVATION_KEY,
            self._BROWSER_GOAL_FOCUS_VERIFICATION_KEY,
            self._REPO_TEXT_BASELINE_KEY,
            self._TARGETED_TEST_EXECUTION_KEY,
            self._PROCEDURAL_INFLUENCE_KEY,
            self._POINTER_CLICK_PRECONDITION_KEY,
            self._POINTER_CLICK_EXECUTION_KEY,
            self._SEMANTIC_PRECONDITION_KEY,
            self._AUTOMATION_TARGET_KEY,
            self._AUTOMATION_VERIFICATION_KEY,
            self._TEXT_PRECONDITION_KEY,
            self._TEXT_EXECUTION_KEY,
            self._TEXT_VERIFICATION_KEY,
        ):
            state.data.pop(key, None)

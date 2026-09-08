from __future__ import annotations

"""Install E2E-07 behavior onto the one existing Resident runtime."""

from .action import NativeActionIntent
from .body import BodyActionResult
from .browser_goal_understanding_resident import browser_semantic_lookup_goal
from .user_browser_causal_popup_adapter import CausalPopupAuthorizedExtensionUserBrowser
from .user_browser_causal_popup_body import install_user_browser_causal_popup_body
from .user_browser_extension_relay import UserBrowserExtensionRelayError


_CAUSAL_POSTCONDITION = "causal_child_verified_and_returned_to_exact_root"
_CAUSAL_VERIFY_PHASE = "verify_causal_child_result"
_CAUSAL_FAILED_PHASE = "causal_click_unverified_no_replay"
_INSTALL_MARKER = "_zn_user_browser_causal_popup_behavior_installed"


def install_user_browser_causal_popup_behavior(resident) -> None:
    """Decorate existing Resident seams without adding a Resident/store/router."""
    if getattr(resident, _INSTALL_MARKER, False):
        return

    current_adapter = resident._extension_user_browser
    sessions = getattr(current_adapter, "_sessions", None)
    if isinstance(sessions, dict) and sessions:
        raise RuntimeError("cannot install causal USER browser support while adapter sessions are active")
    causal_adapter = CausalPopupAuthorizedExtensionUserBrowser(resident.user_browser_extension)
    if resident.managed_browser is current_adapter:
        resident.managed_browser = causal_adapter
    resident._extension_user_browser = causal_adapter
    try:
        current_adapter.close()
    except Exception:
        pass

    install_user_browser_causal_popup_body(resident.body)

    original_begin = resident._begin_native_action_cycle
    original_native_action = resident._native_action_step
    original_complete = resident._complete_successful_body_action
    original_semantic_investigation = resident._semantic_lookup_investigation

    def begin_native_action_cycle(event, state, intent):
        goal = browser_semantic_lookup_goal(event)
        if (
            goal is not None
            and str(intent.kind or "").strip().lower() == "browser_click_named_button_to_url"
            and resident.user_browser_extension.authorized_tab() is not None
        ):
            args = dict(intent.args or {})
            args["causal_popup_allowed"] = True
            intent = NativeActionIntent(
                intent_id=intent.intent_id,
                event_id=intent.event_id,
                kind=intent.kind,
                args=args,
                expected_outcome=(
                    dict(intent.expected_outcome)
                    if isinstance(intent.expected_outcome, dict)
                    else intent.expected_outcome
                ),
                reason=intent.reason,
                source=intent.source,
                created_at=intent.created_at,
            )
        return original_begin(event, state, intent)

    def native_action_step(event, state, *, readiness, thought=None):
        raw_intent = state.data.get("native_action_intent")
        try:
            intent = NativeActionIntent.from_dict(raw_intent) if isinstance(raw_intent, dict) else None
        except (TypeError, ValueError):
            intent = None
        is_causal_click = bool(
            intent is not None
            and browser_semantic_lookup_goal(event) is not None
            and str(intent.kind or "").strip().lower() == "browser_click_named_button_to_url"
            and dict(intent.args or {}).get("causal_popup_allowed") is True
        )
        result = original_native_action(event, state, readiness=readiness, thought=thought)
        if not is_causal_click or result is not None:
            return result

        raw_result = state.data.get("native_action_result")
        if not isinstance(raw_result, dict) or raw_result.get("success") is True:
            return result
        result_data = raw_result.get("data") if isinstance(raw_result.get("data"), dict) else {}
        browser_evidence = (
            result_data.get("browser_evidence")
            if isinstance(result_data.get("browser_evidence"), dict)
            else {}
        )
        evidence_data = (
            browser_evidence.get("data")
            if isinstance(browser_evidence.get("data"), dict)
            else {}
        )
        crossed_nonreplayable_boundary = bool(
            result_data.get("side_effect_uncertain") is True
            or evidence_data.get("click_sent") is True
            or evidence_data.get("click_may_have_been_sent") is True
        )
        if not crossed_nonreplayable_boundary:
            return result

        failure = str(
            raw_result.get("error")
            or browser_evidence.get("error")
            or "causal popup click crossed the non-replayable boundary without the required proof"
        ).strip()
        raw_semantic = state.data.get(resident._SEMANTIC_LOOKUP_STATE_KEY)
        semantic = dict(raw_semantic) if isinstance(raw_semantic, dict) else {}
        semantic["phase"] = _CAUSAL_FAILED_PHASE
        semantic["causal_failure"] = failure[:512]
        semantic["causal_replay_blocked"] = True
        state.data[resident._SEMANTIC_LOOKUP_STATE_KEY] = semantic
        state.data["local_failure"] = failure[:512]
        resident._sync_execution_context(event, state)
        resident.store.save_working_state(state)
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason=(
                "the causal browser click may already have executed, but its exact child/root "
                f"proof failed; replay is blocked: {failure[:512]}"
            ),
        )

    def complete_successful_body_action(event, state, intent, *, response: str, reason: str):
        goal = browser_semantic_lookup_goal(event)
        raw_result = state.data.get("native_action_result")
        try:
            result = BodyActionResult(**raw_result) if isinstance(raw_result, dict) else None
        except (TypeError, ValueError):
            result = None
        if (
            goal is not None
            and str(intent.kind or "").strip().lower() == "browser_click_named_button_to_url"
            and result is not None
        ):
            data = dict(result.data or {})
            raw_semantic = state.data.get(resident._SEMANTIC_LOOKUP_STATE_KEY)
            semantic = dict(raw_semantic) if isinstance(raw_semantic, dict) else {}
            if (
                result.success
                and data.get("postcondition") == _CAUSAL_POSTCONDITION
                and data.get("relationship") == "causal_child"
                and data.get("opener_matches_root") is True
                and data.get("fresh_child_identity") is True
                and data.get("page_window_open_matches_expected") is True
                and data.get("causal_candidate_count") == 1
                and data.get("child_authority_task_scoped") is True
                and data.get("child_debugger_detached") is True
                and data.get("root_authorization_preserved") is True
                and data.get("root_generation_unchanged") is True
                and data.get("returned_to_exact_root_tab") is True
                and data.get("fresh_root_resense_after_return") is True
                and data.get("child_url_matches_expected") is True
            ):
                semantic["phase"] = _CAUSAL_VERIFY_PHASE
                semantic["causal_action_id"] = result.action_id
                state.data[resident._SEMANTIC_LOOKUP_STATE_KEY] = semantic
                resident._record_semantic_progress(
                    state,
                    str(intent.kind or ""),
                    "browser_semantic_causal_child_provider_verified",
                )
                resident._reset_investigation_after_goal_substep(event, state, intent)
                state.stage = "native_investigation"
                state.next_action = (
                    "freshly re-ground the exact root authorization after the child-tab interruption, "
                    "then interpret only the bounded transient child result"
                )
                resident._sync_execution_context(event, state)
                resident.store.save_working_state(state)
                return None
        return original_complete(event, state, intent, response=response, reason=reason)

    def semantic_lookup_investigation(event, state, goal: dict[str, str], *, readiness, thought=None):
        raw = state.data.get(resident._SEMANTIC_LOOKUP_STATE_KEY)
        semantic = dict(raw) if isinstance(raw, dict) else {}
        phase = str(semantic.get("phase") or "")
        if phase == _CAUSAL_FAILED_PHASE:
            return resident._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "causal popup verification already failed after a possibly executed click; "
                    "replay remains blocked: "
                    + str(semantic.get("causal_failure") or "required causal proof was not established")
                ),
            )
        if phase != _CAUSAL_VERIFY_PHASE:
            return original_semantic_investigation(
                event,
                state,
                goal,
                readiness=readiness,
                thought=thought,
            )

        action_id = str(semantic.get("causal_action_id") or "").strip()
        adapter = resident._extension_user_browser
        if not isinstance(adapter, CausalPopupAuthorizedExtensionUserBrowser) or not action_id:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "causal child authority was ephemeral and its bounded result is no longer present; "
                    "ZN will not replay the click after restart or adapter replacement"
                ),
            )

        try:
            context = resident._ensure_user_browser_task_context(event, state)
            root_url = str(semantic.get("url") or "").strip()
            expected_child_url = str(semantic.get("expected_url") or "").strip()
            if not root_url or not expected_child_url:
                raise UserBrowserExtensionRelayError("semantic task lost its exact root/child URL contract")

            fresh_root_target = resident._bind_exact_semantic_target(
                url=root_url,
                name=str(semantic.get("button_name") or ""),
                role="button",
            )
            after_context = resident._ensure_user_browser_task_context(event, state)
            if (
                int(after_context["tab_id"]) != int(context["tab_id"])
                or str(after_context["attached_at"]) != str(context["attached_at"])
                or str(fresh_root_target.get("url") or "") != root_url
            ):
                raise UserBrowserExtensionRelayError(
                    "root authorization changed while post-popup fresh re-grounding was in progress"
                )

            transient = adapter.causal_child_result(action_id)
            if not isinstance(transient, dict):
                raise UserBrowserExtensionRelayError(
                    "bounded child result is no longer available; refusing popup click replay"
                )
            if (
                str(transient.get("task_action_id") or "") != action_id
                or int(transient.get("root_tab_id") or 0) != int(context["tab_id"])
                or str(transient.get("authorization_attached_at") or "")
                != str(context["attached_at"])
                or str(transient.get("child_url") or "") != expected_child_url
            ):
                raise UserBrowserExtensionRelayError(
                    "transient child result does not belong to the current Work root authorization generation"
                )
            child_title = str(transient.get("child_title") or "").strip()
            if not child_title or goal["subject_value"] not in child_title:
                raise UserBrowserExtensionRelayError(
                    "bounded child title does not prove the requested subject anchor"
                )
            result_text = resident._interpret_semantic_result(event, goal, child_title)
            semantic["fresh_root_rebound_after_popup"] = True
            semantic["root_target_replaced_after_popup"] = bool(
                str(fresh_root_target.get("target_id") or "")
                != str(semantic.get("button_target_id") or "")
            )
            state.data[resident._SEMANTIC_LOOKUP_STATE_KEY] = semantic
            resident._sync_execution_context(event, state)
            resident.store.save_working_state(state)
        except Exception as exc:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "causal child was not allowed to complete the Work without a fresh exact-root "
                    f"re-ground and bounded result proof: {type(exc).__name__}: {exc}"
                ),
            )
        finally:
            adapter.discard_causal_child_result(action_id)

        return resident._complete_goal_from_fresh_investigation(
            event,
            state,
            readiness=readiness,
            response=result_text,
            reason=(
                "ZN completed the browser goal only after the exact root action produced one "
                "browser-native causal child, child debugger authority was released, the exact "
                "root authorization generation was freshly re-grounded, and the requested fact "
                "was verified from bounded transient child evidence"
            ),
        )

    resident._begin_native_action_cycle = begin_native_action_cycle
    resident._native_action_step = native_action_step
    resident._complete_successful_body_action = complete_successful_body_action
    resident._semantic_lookup_investigation = semantic_lookup_investigation
    setattr(resident, _INSTALL_MARKER, True)

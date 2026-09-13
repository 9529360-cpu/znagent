from __future__ import annotations

import json

import test_windows_interactive_user_browser_causal_popup as causal_e2e


class WindowsInteractiveE2E07DiagnosticTests(
    causal_e2e.E2E07UserBrowserCausalPopupTests
):
    """Expose the already-collected bounded E2E-07 trace when causal proof fails."""

    def _run_to_terminal(self, env, event_id: str, timeout: float = 40.0):
        result, trace = super()._run_to_terminal(env, event_id, timeout=timeout)
        print(
            "ZN_E2E07_DIAGNOSTIC_TRACE="
            + json.dumps(trace[-40:], ensure_ascii=False, default=str),
            flush=True,
        )
        resident = env.get("resident")
        if resident is not None:
            actions = [
                action
                for action in resident.body.recent_actions(512)
                if action.event_id == event_id
                and action.kind == "browser_click_named_button_to_url"
            ]
            safe_actions = []
            for action in actions:
                data = dict(action.data or {})
                browser_evidence = data.get("browser_evidence")
                evidence = dict(browser_evidence) if isinstance(browser_evidence, dict) else {}
                evidence_data = evidence.get("data")
                evidence_data = dict(evidence_data) if isinstance(evidence_data, dict) else {}
                safe_actions.append({
                    "success": action.success,
                    "error": action.error,
                    "side_effect_uncertain": data.get("side_effect_uncertain"),
                    "side_effect_dispatch_observed": data.get("side_effect_dispatch_observed"),
                    "browser_success": evidence.get("success"),
                    "browser_error": evidence.get("error"),
                    "browser_postcondition": evidence.get("postcondition"),
                    "click_sent": evidence_data.get("click_sent"),
                    "click_may_have_been_sent": evidence_data.get("click_may_have_been_sent"),
                    "causal_popup_observed": evidence_data.get("causal_popup_observed"),
                    "causal_candidate_count": evidence_data.get("causal_candidate_count"),
                    "unrelated_created_count": evidence_data.get("unrelated_created_count"),
                    "window_open_event_count": evidence_data.get("window_open_event_count"),
                    "page_window_open_matches_expected": evidence_data.get("page_window_open_matches_expected"),
                    "fresh_child_identity": evidence_data.get("fresh_child_identity"),
                    "opener_matches_root": evidence_data.get("opener_matches_root"),
                    "child_url_matches_expected": evidence_data.get("child_url_matches_expected"),
                    "child_debugger_detached": evidence_data.get("child_debugger_detached"),
                    "root_authorization_preserved": evidence_data.get("root_authorization_preserved"),
                    "root_generation_unchanged": evidence_data.get("root_generation_unchanged"),
                    "returned_to_exact_root_tab": evidence_data.get("returned_to_exact_root_tab"),
                    "fresh_root_resense_after_return": evidence_data.get("fresh_root_resense_after_return"),
                    "root_active_after_return": evidence_data.get("root_active_after_return"),
                    "root_window_focused_after_return": evidence_data.get("root_window_focused_after_return"),
                })
            print(
                "ZN_E2E07_DIAGNOSTIC_ACTIONS="
                + json.dumps(safe_actions, ensure_ascii=False, default=str),
                flush=True,
            )
        return result, trace

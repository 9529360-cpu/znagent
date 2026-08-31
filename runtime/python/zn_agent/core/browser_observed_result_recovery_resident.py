from __future__ import annotations

"""Crash recovery for browser effects whose verified Body result is already durable."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .body import BodyActionResult
from .cognitive_maintenance_resident import CognitiveMaintenanceResidentRuntime


class BrowserObservedResultRecoveryResidentRuntime(CognitiveMaintenanceResidentRuntime):
    """Resume a verified named-button result without replaying its side effect.

    ``SideEffectAwareBody`` durably records the Body result before it marks the
    matching side-effect attempt ``observed``. A process can therefore stop after
    those two facts are committed but before resident WorkingState records the
    successful movement. The old recovery path treated that window exactly like
    an attempt with no dispatch result and required a user decision.

    This layer closes only the strongest currently available browser case: an
    exact named-button click whose durable Body result proves the requested
    same-origin URL postcondition and proves the ephemeral session was closed.
    It never opens a browser, replays the click, or treats a merely ``started``
    attempt as completed. Missing, malformed, failed, or mismatched evidence
    falls through to the inherited fail-closed uncertainty path.
    """

    _OBSERVED_BROWSER_RESULT_KIND = "browser_click_named_button_to_url"

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
            recovered = self._durable_observed_button_result(event, intent)
            if recovered is not None:
                state.data["native_action_result"] = asdict(recovered)
                state.data.pop("local_failure", None)
                self._sync_execution_context(event, state)
                return self._complete_successful_body_action(
                    event,
                    state,
                    intent,
                    response=str(recovered.output or intent.args.get("expected_url") or ""),
                    reason=(
                        "ZN resumed the already durable, provider-verified named-button result "
                        "after interruption without replaying the browser side effect"
                    ),
                )
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _durable_observed_button_result(
        self,
        event,
        intent: NativeActionIntent,
    ) -> BodyActionResult | None:
        kind = str(intent.kind or "").strip().lower()
        if kind != self._OBSERVED_BROWSER_RESULT_KIND:
            return None

        signature_hash = self.body._signature_hash(kind, dict(intent.args))
        attempt = self.body._replay_blocking_attempt(
            event.event_id,
            signature_hash,
            include_observed=True,
        )
        if attempt is None or str(attempt["status"] or "").strip().lower() != "observed":
            return None
        if str(attempt["kind"] or "").strip().lower() != kind:
            return None
        if attempt["result_success"] != 1:
            return None
        result_action_id = str(attempt["result_action_id"] or "").strip()
        if not result_action_id:
            return None

        raw = self._native_body_result_row(
            action_id=result_action_id,
            event_id=event.event_id,
            kind=kind,
        )
        if raw is None:
            return None
        try:
            result = BodyActionResult(**raw)
        except (TypeError, ValueError):
            return None
        if result.action_id != result_action_id or result.event_id != event.event_id:
            return None
        if str(result.kind or "").strip().lower() != kind or result.success is not True:
            return None
        if not self._button_result_proves_intent(result, intent):
            return None
        return result

    def _native_body_result_row(
        self,
        *,
        action_id: str,
        event_id: str,
        kind: str,
    ) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.store.path, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                "SELECT action_id,event_id,kind,success,result_json "
                "FROM native_body_actions WHERE action_id=? AND event_id=? AND kind=?",
                (action_id, event_id, kind),
            ).fetchone()
        if row is None or int(row["success"] or 0) != 1:
            return None
        try:
            decoded = json.loads(str(row["result_json"] or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def _button_result_proves_intent(
        result: BodyActionResult,
        intent: NativeActionIntent,
    ) -> bool:
        data = result.data if isinstance(result.data, dict) else {}
        evidence = data.get("browser_evidence")
        if not isinstance(evidence, dict):
            return False

        start_url = str(intent.args.get("url") or "").strip()
        target_name = str(intent.args.get("target_name") or "").strip()
        expected_url = str(intent.args.get("expected_url") or "").strip()
        if not start_url or not target_name or not expected_url:
            return False
        postcondition = "url_equals_after_fresh_semantic_button_click"
        evidence_data = evidence.get("data")
        return bool(
            data.get("closed") is True
            and str(data.get("url") or "") == start_url
            and str(data.get("expected_url") or "") == expected_url
            and str(data.get("observed_url") or "") == expected_url
            and str(result.output or "") == expected_url
            and str(data.get("target_role") or "") == "button"
            and str(data.get("target_name") or "") == target_name
            and data.get("target_revalidated_before_dispatch") is True
            and str(data.get("postcondition") or "") == postcondition
            and evidence.get("success") is True
            and str(evidence.get("url_after") or "") == expected_url
            and str(evidence.get("postcondition") or "") == postcondition
            and isinstance(evidence_data, dict)
            and evidence_data.get("target_revalidated_before_dispatch") is True
        )

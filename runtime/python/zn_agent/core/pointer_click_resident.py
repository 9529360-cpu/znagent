from __future__ import annotations

"""Durable, evidence-bound pointer click lifecycle for the active ZN resident.

A click is not an idempotent movement: after input is sent, a process crash
cannot prove whether the target received it. This layer therefore persists the
last safe pre-click state and an execution-start marker before sending input.
An interrupted started click is investigated, never replayed blindly.
"""

import math
import time
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .models import utc_now
from .repo_test_resident import RepositoryVerifyingResidentRuntime


class VerifiedPointerClickResidentRuntime(RepositoryVerifyingResidentRuntime):
    """Active resident with one narrow, independently observed click effect."""

    _POINTER_CLICK_PRECONDITION_KEY = "native_pointer_click_precondition"
    _POINTER_CLICK_EXECUTION_KEY = "native_pointer_click_execution"
    _POINTER_CLICK_POSTCONDITION_KIND = "visual_region_changed"
    _POINTER_CLICK_SCENE_PRECONDITION_KIND = "desktop_scene_foreground_matches"
    _POINTER_CLICK_DEFAULT_REGION = 0.08
    _POINTER_CLICK_MIN_REGION = 0.01
    _POINTER_CLICK_MAX_REGION = 0.50

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("native_action_intent")
        if isinstance(raw, dict):
            intent = NativeActionIntent.from_dict(raw)
            if intent.kind == "pointer_click":
                return self._pointer_click_action_step(
                    event,
                    state,
                    intent,
                    thought=thought,
                )
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _pointer_click_action_step(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        thought=None,
    ):
        contract, error = self._pointer_click_contract(event, intent)
        if error:
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                error,
                thought=thought,
            )
        assert contract is not None
        scene_error = self._desktop_scene_precondition_error(contract.get("desktop_scene_precondition"))
        if scene_error:
            return self._fail_pointer_click_precondition(
                event, state, intent, scene_error, thought=thought
            )

        visual_region = getattr(self, "visual_region", None)
        if visual_region is None or not callable(getattr(visual_region, "probe", None)):
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                "pointer click requires the resident-owned local visual region sense",
                thought=thought,
            )

        execution = state.data.get(self._POINTER_CLICK_EXECUTION_KEY)
        if (
            isinstance(execution, dict)
            and str(execution.get("intent_id") or "") == intent.intent_id
            and str(execution.get("status") or "") == "started"
        ):
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                "pointer click may already have started before interruption; refusing blind replay",
                thought=thought,
            )

        prepared = state.data.get(self._POINTER_CLICK_PRECONDITION_KEY)
        same_preparation = (
            isinstance(prepared, dict)
            and str(prepared.get("intent_id") or "") == intent.intent_id
            and bool(prepared.get("position_verified"))
        )
        if not same_preparation:
            moved = self.body.act(
                "pointer_move",
                event_id=event.event_id,
                x_fraction=contract["center_x_fraction"],
                y_fraction=contract["center_y_fraction"],
            )
            if not moved.success:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    moved.error or "pointer could not be positioned before click",
                    thought=thought,
                )
            target_x = moved.data.get("target_x")
            target_y = moved.data.get("target_y")
            observed = self._wait_for_pointer_position(
                event_id=event.event_id,
                target_x=target_x,
                target_y=target_y,
            )
            if observed is None:
                return self._fail_pointer_click_precondition(
                    event,
                    state,
                    intent,
                    "fresh pointer observation contradicted the prepared click target",
                    thought=thought,
                )

            state.data[self._POINTER_CLICK_PRECONDITION_KEY] = {
                "intent_id": intent.intent_id,
                "position_verified": True,
                "target_x": int(target_x),
                "target_y": int(target_y),
                "center_x_fraction": contract["center_x_fraction"],
                "center_y_fraction": contract["center_y_fraction"],
                "width_fraction": contract["width_fraction"],
                "height_fraction": contract["height_fraction"],
                "position_observation_action_id": observed.action_id,
                "baseline": None,
                "prepared_at": utc_now(),
            }
            state.next_action = "capture a fresh local baseline and send one non-replayable click"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        prepared = dict(prepared)
        observed = self.body.act("pointer_state", event_id=event.event_id)
        if not self._pointer_matches(
            observed,
            prepared.get("target_x"),
            prepared.get("target_y"),
        ):
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                "pointer moved after click preparation; refusing to click a stale target",
                thought=thought,
            )

        try:
            baseline = visual_region.probe(
                center_x_fraction=contract["center_x_fraction"],
                center_y_fraction=contract["center_y_fraction"],
                width_fraction=contract["width_fraction"],
                height_fraction=contract["height_fraction"],
            )
        except Exception as exc:
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                f"fresh pre-click visual baseline failed: {type(exc).__name__}: {exc}",
                thought=thought,
            )

        prepared["baseline"] = asdict(baseline)
        prepared["baseline_at"] = utc_now()
        state.data[self._POINTER_CLICK_PRECONDITION_KEY] = prepared
        state.data[self._POINTER_CLICK_EXECUTION_KEY] = {
            "intent_id": intent.intent_id,
            "status": "started",
            "baseline_signature": baseline.signature,
            "started_at": utc_now(),
            "action_id": None,
        }
        self._sync_execution_context(event, state)
        # This durable write intentionally happens before input. If the process
        # dies after this point, restart refuses replay because input delivery is
        # unknowable rather than assuming the click did or did not happen.
        self.store.save_working_state(state)

        final_precondition_error = self._pointer_click_final_input_precondition(
            event,
            state,
            intent,
            contract,
            prepared,
        )
        if final_precondition_error:
            execution = dict(state.data[self._POINTER_CLICK_EXECUTION_KEY])
            execution.update(
                {
                    "status": "aborted",
                    "aborted_at": utc_now(),
                    "input_sent": False,
                    "error": str(final_precondition_error),
                }
            )
            state.data[self._POINTER_CLICK_EXECUTION_KEY] = execution
            return self._fail_pointer_click_precondition(
                event,
                state,
                intent,
                final_precondition_error,
                thought=thought,
            )

        result = self.body.act(
            "pointer_click",
            event_id=event.event_id,
            x_fraction=contract["center_x_fraction"],
            y_fraction=contract["center_y_fraction"],
            button="left",
        )
        state.data["native_action_result"] = asdict(result)
        state.data[self._POINTER_CLICK_EXECUTION_KEY] = {
            "intent_id": intent.intent_id,
            "status": "completed" if result.success else "failed",
            "baseline_signature": baseline.signature,
            "started_at": state.data[self._POINTER_CLICK_EXECUTION_KEY]["started_at"],
            "completed_at": utc_now(),
            "action_id": result.action_id,
            "success": bool(result.success),
        }

        if not result.success:
            failure = result.error or "pointer click input failed"
            state.data["local_failure"] = failure
            self._record_failed_action(
                event,
                state,
                intent,
                source="body",
                failure=failure,
            )
            state.stage = "native_investigation"
            state.next_action = "inspect the failed pointer click without replaying it"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        state.data["native_verification"] = {
            **contract,
            "intent_id": intent.intent_id,
            "action_signature": self._intent_signature(intent),
            "baseline_signature": baseline.signature,
        }
        state.stage = "native_verification"
        state.next_action = "re-observe the local visual region after the click"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _pointer_click_final_input_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        contract: dict[str, Any],
        prepared: dict[str, Any],
    ) -> str | None:
        """Return an error when a subclass cannot prove a final pre-input condition.

        The durable non-replayable ``started`` marker is already persisted when
        this hook runs. A failing subclass therefore aborts before input while a
        crash in this narrow danger zone still resolves conservatively as an
        uncertain started click on restart.
        """

        return self._desktop_scene_precondition_error(
            contract.get("desktop_scene_precondition")
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
        raw_intent = state.data.get("native_action_intent")
        if (
            isinstance(raw_contract, dict)
            and str(raw_contract.get("kind") or "").strip().lower()
            == self._POINTER_CLICK_POSTCONDITION_KIND
            and isinstance(raw_intent, dict)
        ):
            intent = NativeActionIntent.from_dict(raw_intent)
            if intent.kind == "pointer_click":
                return self._verify_pointer_click_effect(
                    event,
                    state,
                    intent,
                    raw_contract,
                    thought=thought,
                )

        return super()._native_verification_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _verify_pointer_click_effect(
        self,
        event,
        state,
        intent: NativeActionIntent,
        contract: dict[str, Any],
        *,
        thought=None,
    ):
        prepared = state.data.get(self._POINTER_CLICK_PRECONDITION_KEY)
        baseline = prepared.get("baseline") if isinstance(prepared, dict) else None
        baseline_signature = (
            str(baseline.get("signature") or "") if isinstance(baseline, dict) else ""
        )
        visual_region = getattr(self, "visual_region", None)
        if (
            not baseline_signature
            or visual_region is None
            or not callable(getattr(visual_region, "probe", None))
        ):
            failure = "pointer click verification lost its durable resident-owned visual baseline"
            verification_result = {
                "verified": False,
                "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
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

        try:
            observed = visual_region.probe(
                center_x_fraction=float(contract["center_x_fraction"]),
                center_y_fraction=float(contract["center_y_fraction"]),
                width_fraction=float(contract["width_fraction"]),
                height_fraction=float(contract["height_fraction"]),
            )
            observed_error = None
        except Exception as exc:
            observed = None
            observed_error = f"{type(exc).__name__}: {exc}"

        observed_signature = observed.signature if observed is not None else ""
        verified = bool(observed_signature and observed_signature != baseline_signature)
        verification_result = {
            "verified": verified,
            "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
            "baseline_signature": baseline_signature,
            "observed_signature": observed_signature or None,
            "center_x_fraction": contract.get("center_x_fraction"),
            "center_y_fraction": contract.get("center_y_fraction"),
            "width_fraction": contract.get("width_fraction"),
            "height_fraction": contract.get("height_fraction"),
            "baseline": baseline,
            "observation": asdict(observed) if observed is not None else None,
            "error": observed_error,
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
                response="target-local visual region changed after one bounded click",
                reason=(
                    "ZN completed only the explicitly typed visual_region_changed postcondition "
                    "after a fresh pre-click baseline and fresh post-click observation"
                ),
            )

        failure = (
            "pointer click postcondition verification failed: fresh target-local visual evidence "
            "did not differ from the persisted pre-click baseline"
            if observed is not None
            else "pointer click postcondition verification failed: fresh local visual observation "
            f"was unavailable ({observed_error})"
        )
        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _pointer_click_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        resident_visual = (
            str(intent.source or "").strip().lower() == "visual_stage_bridge"
            and isinstance(intent.expected_outcome, dict)
        )
        explicit = (
            dict(intent.expected_outcome or {})
            if resident_visual
            else event.payload.get("expected_outcome")
        )
        if not isinstance(explicit, dict):
            return None, (
                "pointer_click requires an explicit structured visual_region_changed postcondition"
            )
        kind = str(explicit.get("kind") or "").strip().lower()
        if kind != self._POINTER_CLICK_POSTCONDITION_KIND:
            return None, (
                "pointer_click currently supports only the explicit visual_region_changed postcondition"
            )
        allowed_outcome_fields = {"kind", "width_fraction", "height_fraction"}
        if resident_visual:
            allowed_outcome_fields.add("desktop_scene_precondition")
        unknown = sorted(
            str(key)
            for key in explicit
            if key not in allowed_outcome_fields
        )
        if unknown:
            return None, (
                "visual_region_changed contains unsupported authority fields: "
                + ", ".join(unknown)
            )

        args = intent.args if isinstance(intent.args, dict) else {}
        button = str(args.get("button") or "left").strip().lower()
        if button != "left":
            return None, "pointer_click currently supports only one left click"
        x, x_error = self._bounded_fraction(args.get("x_fraction"), "x_fraction", 0.0, 1.0)
        if x_error:
            return None, x_error
        y, y_error = self._bounded_fraction(args.get("y_fraction"), "y_fraction", 0.0, 1.0)
        if y_error:
            return None, y_error
        width, width_error = self._bounded_fraction(
            explicit.get("width_fraction", self._POINTER_CLICK_DEFAULT_REGION),
            "width_fraction",
            self._POINTER_CLICK_MIN_REGION,
            self._POINTER_CLICK_MAX_REGION,
        )
        if width_error:
            return None, width_error
        height, height_error = self._bounded_fraction(
            explicit.get("height_fraction", self._POINTER_CLICK_DEFAULT_REGION),
            "height_fraction",
            self._POINTER_CLICK_MIN_REGION,
            self._POINTER_CLICK_MAX_REGION,
        )
        if height_error:
            return None, height_error

        scene_precondition, scene_error = self._desktop_scene_precondition(
            event,
            intent=intent,
        )
        if scene_error:
            return None, scene_error
        return {
            "kind": self._POINTER_CLICK_POSTCONDITION_KIND,
            "center_x_fraction": x,
            "center_y_fraction": y,
            "width_fraction": width,
            "height_fraction": height,
            "desktop_scene_precondition": scene_precondition,
        }, None

    def _desktop_scene_precondition(
        self,
        event,
        *,
        intent: NativeActionIntent | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = event.payload.get("desktop_scene_precondition")
        if (
            intent is not None
            and str(intent.source or "").strip().lower() == "visual_stage_bridge"
            and isinstance(intent.expected_outcome, dict)
        ):
            raw = intent.expected_outcome.get("desktop_scene_precondition")
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            return None, "desktop_scene_precondition must be a structured object"
        allowed = {
            "kind",
            "application_id",
            "identity_sha256",
            "scene_id",
            "window_rect",
            "screen_width",
            "screen_height",
        }
        unknown = sorted(str(key) for key in raw if key not in allowed)
        if unknown:
            return None, (
                "desktop_scene_precondition contains unsupported fields: "
                + ", ".join(unknown)
            )
        kind = str(raw.get("kind") or "").strip().lower()
        application_id = str(raw.get("application_id") or "").strip()
        identity = str(raw.get("identity_sha256") or "").strip().lower()
        scene_id = str(raw.get("scene_id") or "").strip()
        if kind != self._POINTER_CLICK_SCENE_PRECONDITION_KIND:
            return None, "desktop_scene_precondition kind is unsupported"
        if (
            not application_id
            or len(identity) != 64
            or any(ch not in "0123456789abcdef" for ch in identity)
        ):
            return None, (
                "desktop_scene_precondition requires exact application_id and SHA-256 identity"
            )
        if not scene_id.startswith("desktop-scene-"):
            return None, "desktop_scene_precondition requires an opaque desktop scene_id"

        rect = raw.get("window_rect")
        if not isinstance(rect, dict) or set(rect) != {"left", "top", "right", "bottom"}:
            return None, "desktop_scene_precondition requires an exact window_rect"
        try:
            normalized_rect = {
                name: round(float(rect[name]), 3)
                for name in ("left", "top", "right", "bottom")
            }
            screen_width = int(raw.get("screen_width") or 0)
            screen_height = int(raw.get("screen_height") or 0)
        except (TypeError, ValueError):
            return None, "desktop_scene_precondition geometry is invalid"
        if (
            normalized_rect["right"] <= normalized_rect["left"]
            or normalized_rect["bottom"] <= normalized_rect["top"]
            or screen_width <= 0
            or screen_height <= 0
        ):
            return None, "desktop_scene_precondition geometry must have positive bounds"
        return {
            "kind": kind,
            "application_id": application_id,
            "identity_sha256": identity,
            "scene_id": scene_id,
            "window_rect": normalized_rect,
            "screen_width": screen_width,
            "screen_height": screen_height,
        }, None

    def _desktop_scene_precondition_error(self, precondition: Any) -> str | None:
        if precondition is None:
            return None
        if not isinstance(precondition, dict):
            return "pointer click lost its admitted desktop scene precondition"
        observer = getattr(self.body, "observe_desktop_scene_foreground", None)
        if not callable(observer):
            return "pointer click requires fresh desktop-scene foreground observation"
        try:
            observed = observer(application_id=str(precondition["application_id"]))
        except Exception as exc:
            return (
                "fresh desktop-scene foreground observation failed: "
                f"{type(exc).__name__}: {exc}"
            )
        if not isinstance(observed, dict):
            return "fresh desktop-scene foreground observation returned invalid evidence"
        if (
            str(observed.get("application_id") or "")
            != str(precondition["application_id"])
            or str(observed.get("identity_sha256") or "").lower()
            != str(precondition["identity_sha256"]).lower()
        ):
            return "desktop scene foreground identity drifted before pointer input"
        if dict(observed.get("window_rect") or {}) != dict(precondition.get("window_rect") or {}):
            return "desktop scene foreground geometry drifted before pointer input"

        pointer_state = self.body.act("pointer_state", event_id=None)
        if not getattr(pointer_state, "success", False):
            return "fresh primary-screen dimensions are unavailable before pointer input"
        try:
            width = int(pointer_state.data.get("screen_width") or 0)
            height = int(pointer_state.data.get("screen_height") or 0)
        except (AttributeError, TypeError, ValueError):
            return "fresh primary-screen dimensions are invalid before pointer input"
        if (
            width != int(precondition.get("screen_width") or 0)
            or height != int(precondition.get("screen_height") or 0)
        ):
            return "primary-screen geometry drifted before pointer input"
        return None

    def _fail_pointer_click_precondition(
        self,
        event,
        state,
        intent: NativeActionIntent,
        failure: str,
        *,
        thought=None,
    ):
        message = "pointer click precondition failed: " + str(failure or "unknown failure")
        state.data["local_failure"] = message
        investigation = self.investigator.current(event.event_id)
        if investigation is not None:
            investigation.facts = {
                **dict(investigation.facts or {}),
                "last_pointer_click_precondition_failure": {
                    "kind": intent.kind,
                    "failure": message,
                    "at": utc_now(),
                },
            }
            investigation.evidence = (
                *investigation.evidence,
                message,
            )[-64:]
            investigation.updated_at = utc_now()
            self.investigator._save(investigation)
        self._record_failed_action(
            event,
            state,
            intent,
            source="precondition",
            failure=message,
        )
        state.stage = "native_investigation"
        state.next_action = "refresh click target evidence before any further input"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if message not in thought.unknown:
                thought.unknown = (*thought.unknown, message)
            thought.reason = (
                f"{thought.reason}; the bounded click precondition was not proven from current reality"
            )
            self._persist_enriched_thought(thought)
        return None

    def _wait_for_pointer_position(
        self,
        *,
        event_id: str,
        target_x: Any,
        target_y: Any,
        timeout_seconds: float = 0.25,
    ):
        """Wait briefly for Windows to publish our successful SetCursorPos move."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            observed = self.body.act("pointer_state", event_id=event_id)
            if self._pointer_matches(observed, target_x, target_y):
                return observed
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)

    @staticmethod
    def _pointer_matches(observed, target_x: Any, target_y: Any) -> bool:
        if not getattr(observed, "success", False):
            return False
        try:
            expected_x = int(target_x)
            expected_y = int(target_y)
            current_x = int(observed.data["x"])
            current_y = int(observed.data["y"])
        except (KeyError, TypeError, ValueError):
            return False
        return abs(current_x - expected_x) <= 1 and abs(current_y - expected_y) <= 1

    @staticmethod
    def _bounded_fraction(
        value: Any,
        name: str,
        lower: float,
        upper: float,
    ) -> tuple[float | None, str | None]:
        if value is None:
            return None, f"pointer_click requires {name}"
        if isinstance(value, bool):
            return None, f"{name} must be numeric"
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None, f"{name} must be numeric"
        if not math.isfinite(result) or not lower <= result <= upper:
            return None, f"{name} must be finite and between {lower} and {upper}"
        return round(result, 6), None

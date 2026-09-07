from __future__ import annotations

"""Resident composition for deterministic application awareness and verified movement."""

import uuid
from dataclasses import asdict

from .action import NativeActionIntent
from .action_authority import install_worker_authority_gate
from .application_goal import application_open_goal
from .broad_goal_autonomous_resident import BroadGoalAutonomousResidentRuntime
from .device_capability_graph import DeviceCapabilityGraph
from .machine_capability_body import MachineCapabilityBody
from .models import utc_now


class ApplicationAwareResidentRuntime(BroadGoalAutonomousResidentRuntime):
    """Give the one existing Resident a deterministic view of its Windows body."""

    _APPLICATION_OBSERVATION_KEY = "machine_application_observation"
    # Retain the persisted V1 key for compatibility; V2 stores both launch and
    # foreground-activation verification progress in this same bounded record.
    _APPLICATION_LAUNCH_PROGRESS_KEY = "machine_application_launch_progress"
    _APPLICATION_VERIFICATION_KIND = "application_open"
    _APPLICATION_FOREGROUND_VERIFICATION_KIND = "application_foreground"
    _MAX_APPLICATION_VERIFICATION_OBSERVATIONS = 16

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.device_capabilities = DeviceCapabilityGraph()
        self.body = MachineCapabilityBody(resident=self, device_capabilities=self.device_capabilities)
        installer = getattr(self, "_install_body_dispatch_health_observer", None)
        if callable(installer):
            installer()
        # Parent installed WorkerRun authority on the previous concrete Body. The
        # replacement is still the same Resident-owned Body surface, so reinstall
        # the same gate rather than creating another authority system.
        install_worker_authority_gate(self.body, resident=self)

    def _investigation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        goal = application_open_goal(event)
        if goal is None:
            return super()._investigation_step(
                event, state, readiness=readiness,
                learning_evidence=learning_evidence, thought=thought,
            )

        progress = state.data.get(self._APPLICATION_LAUNCH_PROGRESS_KEY)
        progress = dict(progress) if isinstance(progress, dict) else {}
        prior_app_id = str(progress.get("application_id") or "").strip()
        raw_prior_intent = state.data.get("native_action_intent")
        if not prior_app_id and isinstance(raw_prior_intent, dict):
            raw_args = raw_prior_intent.get("args")
            if isinstance(raw_args, dict):
                prior_app_id = str(raw_args.get("application_id") or "").strip()
        resolution = self.device_capabilities.resolve_application(
            goal.application_name, force_refresh=not bool(prior_app_id)
        )
        if resolution.status == "not_installed":
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"application {goal.application_name!r} is not installed according to current "
                    "machine inventory; ZN will not invent an executable path"
                ),
            )
        if resolution.status == "ambiguous":
            names = ", ".join(
                f"{item.canonical_name} [{item.app_id}]" for item in resolution.candidates[:8]
            )
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"application name {goal.application_name!r} is ambiguous in current machine "
                    f"inventory: {names}; ZN will not choose one arbitrarily"
                ),
            )

        application = resolution.application
        assert application is not None
        if prior_app_id and application.app_id != prior_app_id:
            return self._fail_composite_goal_investigation(
                event, state,
                reason="application identity changed after movement admission; refusing authority transfer",
            )

        processes, windows = self.device_capabilities.application_runtime(application)
        visible = tuple(window for window in windows if window.visible)
        foreground = tuple(window for window in visible if window.foreground)
        state.data[self._APPLICATION_OBSERVATION_KEY] = {
            "query": goal.application_name,
            "resolution_status": resolution.status,
            "application": asdict(application),
            "processes": [asdict(item) for item in processes],
            "windows": [asdict(item) for item in visible],
            "observed_at": utc_now(),
        }

        if foreground:
            window = foreground[0]
            state.data.pop("local_failure", None)
            reason = (
                "fresh process/window observations prove the requested installed application is "
                f"the foreground application at exact HWND={window.hwnd}"
            )
            if self._prior_activation_dispatched(state, application.app_id):
                reason += " after one identity-bound activation request"
            else:
                reason += "; no activation or duplicate launch was needed"
            return self._complete_goal_from_fresh_investigation(
                event, state, readiness=readiness,
                response=f"{application.canonical_name} is foreground at HWND={window.hwnd}",
                reason=reason,
            )

        activation_failure = self._prior_failed_activation_dispatch(state, application.app_id)
        if activation_failure:
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"{activation_failure}; Windows did not permit/produce the requested foreground "
                    "transition; the existing application process was preserved and no duplicate "
                    "launch was sent"
                ),
            )

        state.data.pop("local_failure", None)
        if len(visible) > 1:
            handles = ", ".join(str(window.hwnd) for window in visible)
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"{application.canonical_name} has multiple visible matching top-level windows "
                    f"({handles}) and none is foreground; first-slice activation refuses to choose "
                    "one arbitrarily"
                ),
            )

        if len(visible) == 1:
            window = visible[0]
            state.stage = "native_deliberation"
            state.next_action = (
                f"activate the unique fresh existing application window HWND={window.hwnd} without launching"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if processes:
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"{application.canonical_name} is already running but has no currently visible "
                    "top-level window; ZN does not resurrect hidden/tray-only instances and refuses "
                    "to manufacture a duplicate process"
                ),
            )

        if self._prior_activation_intent(state, application.app_id):
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    "the exact existing application instance disappeared during activation; "
                    "refusing to silently convert the stale activation authority into a launch"
                ),
            )
        if progress.get("dispatch_succeeded") is True and progress.get("action_kind") in {None, "launch_application"}:
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"launch dispatch for {application.canonical_name} returned, but fresh machine "
                    "observation still cannot prove a matching process/window; refusing blind replay"
                ),
            )
        if not application.launchable:
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"{application.canonical_name} is installed but current native evidence does "
                    "not expose a safe launch mechanism"
                ),
            )

        state.stage = "native_deliberation"
        state.next_action = "launch the exact resolved installed application identity once"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _deliberation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        goal = application_open_goal(event)
        if goal is None:
            return super()._deliberation_step(
                event, state, readiness=readiness,
                learning_evidence=learning_evidence, thought=thought,
            )
        raw = state.data.get(self._APPLICATION_OBSERVATION_KEY)
        application = raw.get("application") if isinstance(raw, dict) else None
        windows = raw.get("windows") if isinstance(raw, dict) else None
        processes = raw.get("processes") if isinstance(raw, dict) else None
        if not isinstance(application, dict):
            state.stage = "native_investigation"
            state.next_action = "freshly resolve the requested installed application"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        app_id = str(application.get("app_id") or "").strip()
        if not app_id:
            return self._fail_composite_goal_investigation(
                event, state, reason="machine application observation lost its application identity"
            )
        fresh = self.device_capabilities.resolve_application(goal.application_name)
        if fresh.status != "resolved" or fresh.application is None:
            state.stage = "native_investigation"
            state.next_action = "re-resolve changed application inventory before movement authority"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        if fresh.application.app_id != app_id:
            return self._fail_composite_goal_investigation(
                event, state, reason="resolved application identity changed before movement authority"
            )

        visible = [item for item in windows if isinstance(item, dict) and item.get("visible")] if isinstance(windows, list) else []
        observed_processes = [item for item in processes if isinstance(item, dict)] if isinstance(processes, list) else []
        if len(visible) == 1 and observed_processes:
            window = visible[0]
            expected_hwnd = int(window.get("hwnd") or 0)
            expected_pid = int(window.get("process_id") or 0)
            if not expected_hwnd or not expected_pid:
                state.stage = "native_investigation"
                state.next_action = "re-observe exact application window/process identity"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            intent = NativeActionIntent(
                intent_id=f"application-activate-{uuid.uuid4().hex[:12]}",
                event_id=event.event_id,
                kind="activate_application_window",
                args={"application_id": app_id},
                expected_outcome={
                    "kind": self._APPLICATION_FOREGROUND_VERIFICATION_KIND,
                    "application_id": app_id,
                    "expected_window_handle": expected_hwnd,
                    "expected_process_id": expected_pid,
                },
                reason=(
                    "fresh machine facts prove exactly one visible background window for the resolved "
                    "application; request activation by application identity and verify the exact HWND"
                ),
                source="resident_choice",
            )
            if self._action_blocked_by_current_evidence(event, state, intent):
                return self._checkpoint_terminal_failure(
                    event, state,
                    reason=(
                        "the same exact application-window activation remains blocked; refusing blind "
                        "replay or duplicate launch"
                    ),
                )
            self._begin_native_action_cycle(event, state, intent)
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent(
            intent_id=f"application-launch-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="launch_application",
            args={"application_id": app_id},
            expected_outcome={"kind": self._APPLICATION_VERIFICATION_KIND, "application_id": app_id},
            reason=(
                "fresh machine facts resolve one installed application and no current instance; "
                "dispatch only its identity-bound native launch target"
            ),
            source="resident_choice",
        )
        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event, state, reason="the same application launch remains blocked; refusing replay"
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        return None

    def _verification_contract(self, event, intent, *, result=None):
        goal = application_open_goal(event)
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        requested_kind = str(expected.get("kind") or "").strip().lower()
        if goal is not None and intent.kind == "launch_application" and requested_kind == self._APPLICATION_VERIFICATION_KIND:
            app_id = str(expected.get("application_id") or "").strip()
            if app_id and app_id == str(intent.args.get("application_id") or "").strip():
                return {"kind": self._APPLICATION_VERIFICATION_KIND, "application_id": app_id}
            return {
                "kind": "unsupported", "requested_kind": self._APPLICATION_VERIFICATION_KIND,
                "error": "application launch identity drifted before verification",
            }

        if goal is not None and intent.kind == "activate_application_window" and requested_kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND:
            app_id = str(expected.get("application_id") or "").strip()
            expected_hwnd = int(expected.get("expected_window_handle") or 0)
            expected_pid = int(expected.get("expected_process_id") or 0)
            result_data = result.data if result is not None and isinstance(result.data, dict) else {}
            body_hwnd = int(result_data.get("window_handle") or 0)
            body_pid = int(result_data.get("process_id") or 0)
            if not app_id or app_id != str(intent.args.get("application_id") or "").strip():
                return {
                    "kind": "unsupported", "requested_kind": requested_kind,
                    "error": "application activation identity drifted before verification",
                }
            if not expected_hwnd or not expected_pid or body_hwnd != expected_hwnd or body_pid != expected_pid:
                return {
                    "kind": "unsupported", "requested_kind": requested_kind,
                    "error": (
                        "application activation target changed across the Body authority boundary; "
                        "refusing to verify a silently retargeted window"
                    ),
                }
            return {
                "kind": self._APPLICATION_FOREGROUND_VERIFICATION_KIND,
                "application_id": app_id,
                "expected_window_handle": expected_hwnd,
                "expected_process_id": expected_pid,
            }
        return super()._verification_contract(event, intent, result=result)

    def _native_verification_step(self, event, state, *, readiness, thought=None):
        contract = state.data.get("native_verification")
        raw_intent = state.data.get("native_action_intent")
        if not (isinstance(contract, dict) and isinstance(raw_intent, dict)):
            return super()._native_verification_step(
                event, state, readiness=readiness, thought=thought
            )
        kind = str(contract.get("kind") or "").strip().lower()
        if kind not in {
            self._APPLICATION_VERIFICATION_KIND,
            self._APPLICATION_FOREGROUND_VERIFICATION_KIND,
        }:
            return super()._native_verification_step(
                event, state, readiness=readiness, thought=thought
            )

        intent = NativeActionIntent.from_dict(raw_intent)
        app_id = str(contract.get("application_id") or "").strip()
        application = self.device_capabilities.application_by_id(app_id)
        processes = ()
        visible = ()
        if application is not None:
            processes, windows = self.device_capabilities.application_runtime(application)
            visible = tuple(window for window in windows if window.visible)

        expected_hwnd = int(contract.get("expected_window_handle") or 0)
        expected_pid = int(contract.get("expected_process_id") or 0)
        foreground_observation = None
        exact_window = None
        exact_process = None
        if kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND and application is not None:
            exact_window = next(
                (
                    window for window in visible
                    if window.hwnd == expected_hwnd
                    and window.process_id == expected_pid
                    and window.resolved_app_id == app_id
                ),
                None,
            )
            exact_process = next(
                (
                    process for process in processes
                    if process.process_id == expected_pid and process.resolved_app_id == app_id
                ),
                None,
            )
            foreground_observation = self.device_capabilities.foreground_application()
            verified = bool(
                exact_window is not None
                and exact_process is not None
                and foreground_observation is not None
                and foreground_observation.window.visible
                and foreground_observation.window.hwnd == expected_hwnd
                and foreground_observation.window.process_id == expected_pid
                and foreground_observation.window.resolved_app_id == app_id
                and foreground_observation.application is not None
                and foreground_observation.application.app_id == app_id
            )
        else:
            verified = bool(application is not None and processes and visible)

        progress = state.data.get(self._APPLICATION_LAUNCH_PROGRESS_KEY)
        progress = dict(progress) if isinstance(progress, dict) else {}
        observations = int(progress.get("verification_observations") or 0) + 1
        action_result = state.data.get("native_action_result")
        action_data = action_result.get("data") if isinstance(action_result, dict) else None
        dispatch_sent = bool(action_data.get("dispatch_sent")) if isinstance(action_data, dict) else False
        progress.update({
            "application_id": app_id,
            "action_kind": intent.kind,
            "dispatch_succeeded": dispatch_sent,
            "verification_observations": observations,
            "last_process_ids": [item.process_id for item in processes],
            "last_window_handles": [item.hwnd for item in visible],
            "last_observed_at": utc_now(),
        })
        state.data[self._APPLICATION_LAUNCH_PROGRESS_KEY] = progress

        if kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND:
            foreground_window = (
                foreground_observation.window if foreground_observation is not None else None
            )
            verification = {
                "verified": verified,
                "kind": kind,
                "application_id": app_id,
                "expected_window_handle": expected_hwnd,
                "expected_process_id": expected_pid,
                "application_present": application is not None,
                "target_window_visible": exact_window is not None,
                "target_process_present": exact_process is not None,
                "foreground_window_handle": (
                    foreground_window.hwnd if foreground_window is not None else None
                ),
                "foreground_process_id": (
                    foreground_window.process_id if foreground_window is not None else None
                ),
                "foreground_application_id": (
                    foreground_observation.application.app_id
                    if foreground_observation is not None and foreground_observation.application is not None
                    else None
                ),
                "observation_count": observations,
                "observed_at": utc_now(),
            }
        else:
            verification = {
                "verified": verified,
                "kind": kind,
                "application_id": app_id,
                "application_present": application is not None,
                "process_ids": [item.process_id for item in processes],
                "window_handles": [item.hwnd for item in visible],
                "observation_count": observations,
                "observed_at": utc_now(),
            }
        state.data["native_verification_result"] = verification
        self._sync_execution_context(event, state)

        if verified:
            self._record_verified_experience(event, state, intent, verification_result=verification)
            if kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND:
                return self._complete_successful_body_action(
                    event, state, intent,
                    response=(
                        f"verified {application.canonical_name} foreground at exact HWND={expected_hwnd}"
                    ),
                    reason=(
                        "ZN completed existing-application activation only after fresh OS foreground "
                        "observation proved the exact authority-bound HWND/PID and application identity"
                    ),
                )
            return self._complete_successful_body_action(
                event, state, intent,
                response=f"verified {application.canonical_name} process/window from fresh machine state",
                reason=(
                    "ZN completed application launch only after fresh process and visible-window "
                    "observations resolved back to the same installed application identity"
                ),
            )

        if observations < self._MAX_APPLICATION_VERIFICATION_OBSERVATIONS:
            state.stage = "native_verification"
            if kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND:
                state.next_action = (
                    "freshly re-observe the exact application foreground postcondition; "
                    "do not redispatch activation"
                )
            else:
                state.next_action = (
                    "freshly re-observe process/window state for the dispatched application; "
                    "do not replay launch"
                )
            self.store.save_working_state(state)
            return None

        self._record_verified_experience(event, state, intent, verification_result=verification)
        if kind == self._APPLICATION_FOREGROUND_VERIFICATION_KIND:
            failure = (
                "Windows did not permit/produce the requested foreground transition for the exact "
                "application HWND within bounded fresh observations; the existing application "
                "process was preserved and no duplicate launch was sent"
            )
        else:
            failure = (
                "application launch dispatch returned, but bounded fresh observations did not "
                "prove a visible window resolving to the same application identity; refusing replay"
            )
        return self._fail_postcondition_verification(
            event, state, intent, failure=failure, thought=thought,
        )

    @staticmethod
    def _prior_activation_intent(state, app_id: str) -> bool:
        raw = state.data.get("native_action_intent")
        if not isinstance(raw, dict) or str(raw.get("kind") or "") != "activate_application_window":
            return False
        args = raw.get("args")
        return isinstance(args, dict) and str(args.get("application_id") or "").strip() == app_id

    @classmethod
    def _prior_activation_dispatched(cls, state, app_id: str) -> bool:
        if not cls._prior_activation_intent(state, app_id):
            return False
        raw_result = state.data.get("native_action_result")
        data = raw_result.get("data") if isinstance(raw_result, dict) else None
        return isinstance(data, dict) and bool(data.get("dispatch_sent"))

    @classmethod
    def _prior_failed_activation_dispatch(cls, state, app_id: str) -> str | None:
        if not cls._prior_activation_dispatched(state, app_id):
            return None
        raw_result = state.data.get("native_action_result")
        if not isinstance(raw_result, dict) or bool(raw_result.get("success")):
            return None
        return str(raw_result.get("error") or "existing application activation request failed").strip()

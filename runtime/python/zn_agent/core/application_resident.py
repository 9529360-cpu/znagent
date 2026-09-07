from __future__ import annotations

"""Resident composition for deterministic application awareness and verified launch."""

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
    _APPLICATION_LAUNCH_PROGRESS_KEY = "machine_application_launch_progress"
    _APPLICATION_VERIFICATION_KIND = "application_open"
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
                reason="application identity changed after launch admission; refusing authority transfer",
            )

        processes, windows = self.device_capabilities.application_runtime(application)
        visible = tuple(window for window in windows if window.visible)
        state.data[self._APPLICATION_OBSERVATION_KEY] = {
            "query": goal.application_name,
            "resolution_status": resolution.status,
            "application": asdict(application),
            "processes": [asdict(item) for item in processes],
            "windows": [asdict(item) for item in visible],
            "observed_at": utc_now(),
        }
        state.data.pop("local_failure", None)

        if visible:
            reason = (
                "fresh process and top-level-window observations resolve to the same installed "
                "application identity"
            )
            if progress.get("dispatch_succeeded") is True:
                reason += " after launch dispatch"
            else:
                reason += "; the application was already running so no duplicate launch was sent"
            return self._complete_goal_from_fresh_investigation(
                event, state, readiness=readiness,
                response=f"{application.canonical_name} is running with visible window HWND={visible[0].hwnd}",
                reason=reason,
            )

        if processes:
            return self._fail_composite_goal_investigation(
                event, state,
                reason=(
                    f"{application.canonical_name} is already running but has no currently visible "
                    "top-level window; V1 does not yet focus/activate hidden instances, so ZN "
                    "refuses to manufacture a duplicate process"
                ),
            )
        if progress.get("dispatch_succeeded") is True:
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
            state.next_action = "re-resolve changed application inventory before launch"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        if fresh.application.app_id != app_id:
            return self._fail_composite_goal_investigation(
                event, state, reason="resolved application identity changed before launch authority"
            )

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
        if (
            goal is not None
            and intent.kind == "launch_application"
            and str(expected.get("kind") or "").strip().lower() == self._APPLICATION_VERIFICATION_KIND
        ):
            app_id = str(expected.get("application_id") or "").strip()
            if app_id and app_id == str(intent.args.get("application_id") or "").strip():
                return {"kind": self._APPLICATION_VERIFICATION_KIND, "application_id": app_id}
            return {
                "kind": "unsupported", "requested_kind": self._APPLICATION_VERIFICATION_KIND,
                "error": "application launch identity drifted before verification",
            }
        return super()._verification_contract(event, intent, result=result)

    def _native_verification_step(self, event, state, *, readiness, thought=None):
        contract = state.data.get("native_verification")
        raw_intent = state.data.get("native_action_intent")
        if not (
            isinstance(contract, dict)
            and str(contract.get("kind") or "").strip().lower() == self._APPLICATION_VERIFICATION_KIND
            and isinstance(raw_intent, dict)
        ):
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
        verified = bool(application is not None and processes and visible)

        progress = state.data.get(self._APPLICATION_LAUNCH_PROGRESS_KEY)
        progress = dict(progress) if isinstance(progress, dict) else {}
        observations = int(progress.get("verification_observations") or 0) + 1
        action_result = state.data.get("native_action_result")
        action_data = action_result.get("data") if isinstance(action_result, dict) else None
        dispatch_sent = bool(action_data.get("dispatch_sent")) if isinstance(action_data, dict) else False
        progress.update({
            "application_id": app_id,
            "dispatch_succeeded": dispatch_sent,
            "verification_observations": observations,
            "last_process_ids": [item.process_id for item in processes],
            "last_window_handles": [item.hwnd for item in visible],
            "last_observed_at": utc_now(),
        })
        state.data[self._APPLICATION_LAUNCH_PROGRESS_KEY] = progress
        verification = {
            "verified": verified,
            "kind": self._APPLICATION_VERIFICATION_KIND,
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
            state.next_action = (
                "freshly re-observe process/window state for the dispatched application; "
                "do not replay launch"
            )
            self.store.save_working_state(state)
            return None

        self._record_verified_experience(event, state, intent, verification_result=verification)
        return self._fail_postcondition_verification(
            event, state, intent,
            failure=(
                "application launch dispatch returned, but bounded fresh observations did not "
                "prove a visible window resolving to the same application identity; refusing replay"
            ),
            thought=thought,
        )

from __future__ import annotations

"""Narrow product ingress for Research and Local Office representative Work."""

from .action_authority import install_worker_authority_gate
from .app_competence import AppCompetenceRegistry
from .app_competence_execution import (
    AppCompetenceRecipeExecution,
    AppCompetenceRecipeExecutor,
    AppCompetenceStageHandoff,
)
from .browser_goal_understanding_resident import browser_semantic_lookup_goal
from .browser_spreadsheet_behavior import install_browser_spreadsheet_behavior
from .current_app_text_cleanup_behavior import install_current_app_text_cleanup_behavior
from .current_app_text_cleanup_completion import install_current_app_text_cleanup_completion
from .document_research_completion_behavior import (
    install_document_research_completion_behavior,
)
from .document_research_completion_safety import (
    install_document_research_completion_safety,
)
from .explorer_selected_file_behavior import install_explorer_selected_file_behavior
from .local_file_discovery import build_local_file_discovery_capability
from .local_inference_runtime import LocalInferenceRuntimeDiscovery
from .local_office_behavior import install_local_office_behavior
from .presentation_work_behavior import install_presentation_work_behavior
from .document_work_behavior import install_document_work_behavior
from .local_service_recovery_behavior import install_local_service_recovery_behavior
from .models import utc_now
from .long_running_terminal_behavior import install_long_running_terminal_behavior
from .research_information_resident import ResearchInformationResidentRuntime
from .user_browser_extension_relay import UserBrowserExtensionRelayError
from .user_browser_multi_record_result import (
    parse_verified_record_excerpts,
    requested_multi_record_count,
)
from .action_execution import build_machine_action_execution_runtime
from .action_fabric import build_machine_action_fabric
from .app_competence import AppCompetenceRegistry
from .app_competence_execution import AppCompetenceRecipeExecutor
from .provider_runtime import build_machine_provider_runtime
from .reflex_intent import build_resident_reflex_intents
from .windows_audio_reflex_behavior import install_windows_audio_reflex_behavior
from .windows_companion_body import WindowsCompanionAwareBody
from .windows_companion_work_context import bind_windows_companion_work_context
from .visual_stage_bridge import (
    VisualStageBridgeResult,
    build_current_visual_stage_bridge,
)


_RESEARCH_INTENT_MARKERS = (
    "研究",
    "帮我查一下",
    "查一下最近",
    "查一下这几个",
    "查查",
    "多个来源",
    "几个来源",
    "别只看一个来源",
    "现在的价格",
    "当前价格",
    "主要区别",
    "最近的趋势",
    "行业的趋势",
    "都在讨论",
    "为什么这么多人聊",
    "弄明白",
    "research",
    "multiple sources",
    "more than one source",
    "current price",
    "compare prices",
    "latest trend",
    "recent trend",
    "why people are talking",
)

_CONTINUATION_INTENT_MARKERS = (
    "继续刚才那个调查",
    "继续刚才的调查",
    "继续刚才那个研究",
    "继续刚才的研究",
    "继续调查",
    "继续研究",
    "continue that research",
    "continue the research",
    "continue the investigation",
)

_EXISTING_SESSION_MARKERS = (
    "已经登录",
    "已登录",
    "already logged",
    "already signed in",
    "logged-in",
    "signed-in",
    "existing session",
)
_EXISTING_SESSION_CONTAINER_MARKERS = (
    "系统",
    "portal",
    "system",
)
_EXISTING_SESSION_LOOKUP_MARKERS = (
    "查",
    "找",
    "lookup",
    "find",
    "show",
)
_EXISTING_SESSION_RECORD_MARKERS = (
    "订单",
    "记录",
    "order",
    "record",
)


class ProductResearchInformationResidentRuntime(ResearchInformationResidentRuntime):
    """Final product Resident with narrow Research and local Office admission."""

    _VISUAL_COMPETENCE_HANDOFF_KEY = "app_competence_visual_handoff"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep one product Body and one DeviceCapabilityGraph. The companion-aware
        # layer extends the existing application/browser/file/pointer/keyboard/UIA
        # stack; it does not introduce another execution or machine-truth surface.
        self.body = WindowsCompanionAwareBody(
            resident=self,
            device_capabilities=self.device_capabilities,
        )
        # Semantic Action Fabric is descriptive/discovery-only. Real effects
        # still pass through this one Body plus existing authority/verification.
        self.action_fabric = build_machine_action_fabric(self.device_capabilities)
        self.reflex_intents = build_resident_reflex_intents()
        self.local_inference = LocalInferenceRuntimeDiscovery(self.device_capabilities)
        self.provider_runtime = build_machine_provider_runtime(
            self.action_fabric,
            local_inference=self.local_inference,
        )
        self.action_executor = build_machine_action_execution_runtime(
            self.action_fabric,
            self.body,
            device_capabilities=self.device_capabilities,
        )
        # Read-only local file discovery is compiled resident competence. It
        # returns only fresh path/metadata evidence from explicit known-folder
        # scopes and never delegates path authority to a model.
        self.capabilities.register(build_local_file_discovery_capability())
        self.app_competences = AppCompetenceRegistry()
        self.app_competence_executor = AppCompetenceRecipeExecutor(
            self.app_competences,
            self.action_executor,
        )
        installer = getattr(self, "_install_body_dispatch_health_observer", None)
        if callable(installer):
            installer()
        install_worker_authority_gate(self.body, resident=self)
        install_windows_audio_reflex_behavior(self)
        install_current_app_text_cleanup_behavior(self)
        install_current_app_text_cleanup_completion(self)
        install_local_office_behavior(self)
        install_presentation_work_behavior(self)
        install_document_work_behavior(self)
        install_long_running_terminal_behavior(self)
        install_local_service_recovery_behavior(self)
        install_explorer_selected_file_behavior(self)
        install_browser_spreadsheet_behavior(self)
        install_document_research_completion_behavior(self)
        install_document_research_completion_safety(self)

    def _current_visual_stage_bridge(self, event):
        """Bind bounded visual cognition through current Work privacy/route policy."""

        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        raw_policy = payload.get("route_policy")
        if raw_policy is not None and not isinstance(raw_policy, dict):
            raise RuntimeError("visual stage route_policy is malformed")
        classification = str(payload.get("data_classification") or "private").strip() or "private"
        return build_current_visual_stage_bridge(
            action_runtime=self.action_executor,
            kernel=self.kernel,
            route_policy=dict(raw_policy or {}),
            data_classification=classification,
        )

    def evaluate_visual_stage(
        self,
        *,
        event,
        state,
        application_id: str,
        instruction: str,
        decision_id: str,
        step_index: int | None = None,
        allow_tap: bool = True,
    ) -> VisualStageBridgeResult:
        """Evaluate one stage and admit only a TAP into the existing native action cycle."""

        cognitive_decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not cognitive_decision.use_model or cognitive_decision.max_calls < 1:
            raise RuntimeError(
                "visual stage requires bounded image cognition, but current model policy "
                f"does not permit it: {cognitive_decision.reason}"
            )

        result = self._current_visual_stage_bridge(event).evaluate(
            event_id=event.event_id,
            decision_id=decision_id,
            application_id=application_id,
            instruction=instruction,
            step_index=step_index,
        )
        state.data["visual_stage_decision"] = {
            "decision_id": str(decision_id),
            "scene_id": result.scene_id,
            "regrounded_scene_id": result.regrounded_scene_id,
            "decision": result.inference.decision.audit(),
            "provider": result.inference.provider,
            "model": result.inference.model,
            "requires_completion_verification": bool(
                result.requires_completion_verification
            ),
            "tap_admitted": bool(result.pointer_intent is not None and allow_tap),
        }
        if result.pointer_intent is not None and allow_tap:
            self._begin_native_action_cycle(event, state, result.pointer_intent)
        elif result.pointer_intent is not None:
            state.stage = "native_investigation"
            state.next_action = (
                "refuse a second TAP for the same visual competence stage; "
                "re-check completion from fresh reality"
            )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    def advance_app_competence_recipe_once(
        self,
        *,
        registry: AppCompetenceRegistry,
        event,
        state,
        app: str,
        version: str,
        capability: str,
        application_id: str,
        authority_context=None,
    ) -> tuple[AppCompetenceRecipeExecution, VisualStageBridgeResult | None]:
        """Advance one recipe boundary and at most one bounded visual decision."""

        active_handoff = state.data.get(self._VISUAL_COMPETENCE_HANDOFF_KEY)
        if isinstance(active_handoff, dict):
            active_status = str(active_handoff.get("status") or "").strip().lower()
            if (
                active_status == "pointer_active"
                and str(getattr(state, "stage", "") or "").strip().lower()
                in {"native_action", "native_verification", "native_completion"}
            ):
                raise RuntimeError(
                    "visual competence recipe has an in-flight native action; "
                    "resume the resident action lifecycle before recipe re-entry"
                )

        executor = AppCompetenceRecipeExecutor(registry, self.action_executor)
        recipe = executor.execute(
            app=app,
            version=version,
            capability=capability,
            event_id=event.event_id,
            application_id=application_id,
            authority_context=authority_context,
        )
        state.data["app_competence_recipe"] = {
            "pack_id": recipe.pack_id,
            "app_id": recipe.app_id,
            "app_version": recipe.app_version,
            "capability": recipe.capability,
            "status": recipe.status,
            "stage_statuses": [stage.status for stage in recipe.stages],
            "pending_handoff_id": (
                recipe.stages[-1].handoff.handoff_id
                if recipe.stages and recipe.stages[-1].handoff is not None
                else None
            ),
            "error": recipe.error,
        }

        if recipe.status != "pending":
            state.data.pop("app_competence_visual_handoff", None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return recipe, None

        handoff = recipe.stages[-1].handoff if recipe.stages else None
        if handoff is None:
            raise RuntimeError("pending competence recipe lost its visual stage handoff")
        visual = self.admit_competence_visual_handoff(
            event=event,
            state=state,
            handoff=handoff,
        )
        return recipe, visual

    def admit_competence_visual_handoff(
        self,
        *,
        event,
        state,
        handoff: AppCompetenceStageHandoff,
    ) -> VisualStageBridgeResult | None:
        """Consume one executor handoff without creating a second recipe loop."""

        if not isinstance(handoff, AppCompetenceStageHandoff):
            raise TypeError("visual competence handoff must be AppCompetenceStageHandoff")
        if str(getattr(event, "event_id", "") or "") != handoff.event_id:
            raise ValueError("visual competence handoff event_id does not match current event")

        raw = state.data.get(self._VISUAL_COMPETENCE_HANDOFF_KEY)
        prior = dict(raw) if isinstance(raw, dict) else {}
        same_handoff = str(prior.get("handoff_id") or "") == handoff.handoff_id
        prior_status = str(prior.get("status") or "").strip().lower()
        if same_handoff and prior_status in {
            "pointer_active",
            "finish_observed",
            "repeat_tap_blocked",
        }:
            return None
        if same_handoff and prior_status == "evaluating":
            state.stage = "native_investigation"
            state.next_action = (
                "investigate the unresolved visual cognition dispatch without replaying it"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        tap_consumed = bool(
            same_handoff
            and (
                prior.get("tap_consumed") is True
                or prior_status == "effect_verified"
            )
        )
        attempt = (
            max(0, int(prior.get("observation_attempt") or 0)) + 1
            if same_handoff
            else 0
        )
        decision_id = f"{handoff.handoff_id}:observation:{attempt}"
        marker = {
            "handoff_id": handoff.handoff_id,
            "stage_index": handoff.stage_index,
            "application_id": handoff.application_id,
            "instruction": handoff.instruction,
            "step_instruction_index": handoff.step_instruction_index,
            "stage_end_condition": handoff.stage_end_condition,
            "observation_attempt": attempt,
            "decision_id": decision_id,
            "status": "evaluating",
            "tap_consumed": tap_consumed,
            "updated_at": utc_now(),
        }
        state.data[self._VISUAL_COMPETENCE_HANDOFF_KEY] = marker
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

        try:
            result = self.evaluate_visual_stage(
                event=event,
                state=state,
                application_id=handoff.application_id,
                instruction=handoff.instruction,
                decision_id=decision_id,
                step_index=handoff.step_instruction_index,
                allow_tap=not tap_consumed,
            )
        except Exception as exc:
            marker = dict(state.data.get(self._VISUAL_COMPETENCE_HANDOFF_KEY) or marker)
            marker.update(
                {
                    "status": "observation_failed",
                    "error_type": type(exc).__name__,
                    "updated_at": utc_now(),
                }
            )
            state.data[self._VISUAL_COMPETENCE_HANDOFF_KEY] = marker
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            raise

        marker = dict(state.data.get(self._VISUAL_COMPETENCE_HANDOFF_KEY) or marker)
        action = result.inference.decision.action
        if action == "TAP":
            status = "repeat_tap_blocked" if tap_consumed else "pointer_active"
        elif action == "WAIT":
            status = "waiting"
        else:
            status = "finish_observed"
        marker.update(
            {
                "status": status,
                "decision_id": decision_id,
                "pointer_intent_id": (
                    result.pointer_intent.intent_id
                    if result.pointer_intent is not None and not tap_consumed
                    else None
                ),
                "tap_consumed": tap_consumed,
                "updated_at": utc_now(),
            }
        )
        state.data[self._VISUAL_COMPETENCE_HANDOFF_KEY] = marker
        if action != "TAP" or tap_consumed:
            state.stage = "native_investigation"
            if action == "FINISH":
                state.next_action = (
                    "re-check the visual competence completion from fresh reality"
                )
            elif action == "TAP":
                state.next_action = (
                    "investigate the unproven visual competence completion; "
                    "a second TAP for this handoff is blocked"
                )
            else:
                state.next_action = (
                    "wait before another fresh visual competence observation"
                )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    @staticmethod
    def _is_visual_stage_intent(intent) -> bool:
        return (
            str(getattr(intent, "kind", "") or "").strip().lower() == "pointer_click"
            and str(getattr(intent, "source", "") or "").strip().lower()
            == "visual_stage_bridge"
        )

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        """Account a verified visual TAP, then continue instead of closing the event."""

        if not self._is_visual_stage_intent(intent):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        result = super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )
        if result is None and state.stage != "native_completion":
            return None
        return self._roll_forward_verified_visual_stage(
            event,
            state,
            intent,
            result=result,
        )

    def _resume_native_completion(self, event, state):
        raw_intent = state.data.get("native_action_intent")
        if isinstance(raw_intent, dict):
            from .action import NativeActionIntent

            intent = NativeActionIntent.from_dict(raw_intent)
            if self._is_visual_stage_intent(intent):
                result = super()._resume_native_completion(event, state)
                if result is None or not result.success:
                    return result
                return self._roll_forward_verified_visual_stage(
                    event,
                    state,
                    intent,
                    result=result,
                )
        return super()._resume_native_completion(event, state)

    def _roll_forward_verified_visual_stage(self, event, state, intent, *, result):
        """Convert the durable Body completion checkpoint into a visual substep checkpoint."""

        raw_progress = state.data.get("visual_stage_progress")
        progress = list(raw_progress) if isinstance(raw_progress, list) else []
        decision = state.data.get("visual_stage_decision")
        verification = state.data.get("native_verification_result")
        intent_id = str(getattr(intent, "intent_id", "") or "")
        if not any(
            isinstance(item, dict) and str(item.get("intent_id") or "") == intent_id
            for item in progress
        ):
            progress.append(
                {
                    "intent_id": intent_id,
                    "decision_id": (
                        str(decision.get("decision_id") or "")
                        if isinstance(decision, dict)
                        else ""
                    ),
                    "scene_id": (
                        decision.get("scene_id")
                        if isinstance(decision, dict)
                        else None
                    ),
                    "regrounded_scene_id": (
                        decision.get("regrounded_scene_id")
                        if isinstance(decision, dict)
                        else None
                    ),
                    "verified": bool(
                        isinstance(verification, dict)
                        and verification.get("verified") is True
                    ),
                    "completed_at": utc_now(),
                }
            )
        state.data["visual_stage_progress"] = progress[-32:]
        handoff = state.data.get(self._VISUAL_COMPETENCE_HANDOFF_KEY)
        if isinstance(handoff, dict):
            active_decision = str(handoff.get("decision_id") or "")
            current_decision = (
                str(decision.get("decision_id") or "")
                if isinstance(decision, dict)
                else ""
            )
            if active_decision and active_decision == current_decision:
                handoff = dict(handoff)
                handoff.update(
                    {
                        "status": "effect_verified",
                        "tap_consumed": True,
                        "verified_intent_id": intent_id,
                        "updated_at": utc_now(),
                    }
                )
                state.data[self._VISUAL_COMPETENCE_HANDOFF_KEY] = handoff
        state.data.pop("native_completion", None)
        state.data.pop("native_completion_scope", None)
        state.stage = "native_investigation"
        state.next_action = (
            "re-check the admitted visual stage completion from fresh reality "
            "before any further pointer input"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def bind_work_event_context(self, event_payload):
        """Attach fresh bounded device context before Work event durability.

        The returned projection is historical start-context evidence only. Body
        mutation paths continue to reacquire current authority independently.
        """

        return bind_windows_companion_work_context(
            event_payload,
            device_capabilities=self.device_capabilities,
        )

    def _has_explicit_current_user_browser_authority(self) -> bool:
        getter = getattr(self, "user_browser_authorization", None)
        if not callable(getter):
            return False
        try:
            authorization = getter()
        except Exception:
            return False
        if not isinstance(authorization, dict):
            return False
        return (
            authorization.get("authorized") is True
            and str(authorization.get("plane") or "").strip().lower() == "user"
            and str(authorization.get("browser_ownership") or "").strip().lower() == "user"
            and str(authorization.get("authorization_scope") or "").strip().lower()
            == "explicit_current_tab"
        )

    def _is_explicit_existing_session_record_lookup(self, event) -> bool:
        """Admit only the bounded E2E-04-style existing-session lookup entrance."""

        if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
            return False
        payload = getattr(event, "payload", None) or {}
        if payload.get("body_action") or payload.get("native_action"):
            return False
        task = " ".join(str(getattr(event, "task", "") or "").split())
        if not task or requested_multi_record_count(task) is None:
            return False
        lowered = task.casefold()
        if not all(
            any(marker.casefold() in lowered for marker in markers)
            for markers in (
                _EXISTING_SESSION_MARKERS,
                _EXISTING_SESSION_CONTAINER_MARKERS,
                _EXISTING_SESSION_LOOKUP_MARKERS,
                _EXISTING_SESSION_RECORD_MARKERS,
            )
        ):
            return False
        # The natural phrase "the system I'm already logged into" is intentionally
        # not a global synonym for "browser". It becomes USER-browser ingress only
        # while the user has explicitly authorized the current browser tab.
        return self._has_explicit_current_user_browser_authority()

    def _admit_grounded_reflex_action_candidate(self, event, state) -> bool:
        resolution = self.reflex_intents.resolve(event)
        match = resolution.match
        if resolution.status != "matched" or match is None or not match.action_id:
            return False

        reflex = self.reflex_intents.descriptor(match.intent_id)
        if reflex is None or not {
            "action_candidate",
            "requires_grounding",
        }.issubset(set(reflex.tags)):
            return False

        action = self.action_fabric.descriptor(match.action_id)
        if action is None or not action.body_action_kind:
            return False

        state.data["reflex_intent"] = {
            "event_id": event.event_id,
            "intent_id": match.intent_id,
            "action_id": action.action_id,
            "body_action_kind": action.body_action_kind,
            "slots": dict(match.slots),
        }
        state.stage = "native_investigation"
        state.next_action = "ground deterministic reflex through current machine evidence"
        self.store.save_working_state(state)
        return True

    def _orient_step(self, event, state, *, readiness, thought=None):
        if self._admit_grounded_reflex_action_candidate(event, state):
            return None
        if (
            browser_semantic_lookup_goal(event) is None
            and self._is_explicit_existing_session_record_lookup(event)
        ):
            proposed = self._orient_browser_goal_from_cognition(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
            if proposed is not False:
                return proposed
        return super()._orient_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _interpret_semantic_result(self, event, goal: dict[str, str], context: str) -> str:
        """Extend the existing USER Browser lookup to one bounded plural result set."""

        expected_count = requested_multi_record_count(str(getattr(event, "task", "") or ""))
        if expected_count is None:
            return super()._interpret_semantic_result(event, goal, context)

        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            raise UserBrowserExtensionRelayError(
                "multi-record business result interpretation requires bounded language understanding and model use is disabled"
            )
        result = self.kernel.run_goal(
            (
                "Read only this freshly observed bounded result context and verify the plural "
                "record set the user requested. Return exactly "
                '{"status":"verified","records":["VERBATIM RECORD 1","VERBATIM RECORD 2"]} '
                "with exactly the requested number of records only when the context itself "
                f"explicitly presents exactly {expected_count} requested records. Each list item "
                "must be one complete record excerpt copied verbatim from the context, must "
                "contain enough record identity and the requested business fact to answer the "
                "user, and must preserve source order. If the context has fewer or more relevant "
                "records, is ambiguous, or any requested fact is missing, return exactly "
                '{"status":"not_verified","records":[]}. Never infer missing facts, reorder '
                "records, claim actions, authority or completion. "
                f"User task: {event.task}\nDesired result: {goal['desired_result']}\n"
                f"Fresh context: {context}"
            ),
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "browser_semantic_multi_record_result_interpretation_only",
                "expected_record_count": expected_count,
            },
            max_attempts_override=1,
            goal_id=f"goal-browser-semantic-multi-record-result-{event.event_id}",
        )
        self._add_semantic_model_invocations(event, self._model_invocations(result))
        if not (result.worker_result.success and result.assessment.success):
            raise UserBrowserExtensionRelayError(
                "bounded multi-record business result interpretation failed"
            )
        records = parse_verified_record_excerpts(
            result.worker_result.response,
            context=context,
            expected_count=expected_count,
        )
        if records is None:
            raise UserBrowserExtensionRelayError(
                "fresh result context did not verify the requested bounded record set"
            )
        return f"{goal['subject_value']}:\n" + "\n".join(
            f"- {record}" for record in records
        )

    def _is_research_event(self, event) -> bool:
        # Research Work is a product Work path, not a catch-all replacement for
        # native Resident investigation. Events without a durable Root Work
        # remain owned by the existing native/recovery path.
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None or root.parent_work_item_id is not None:
            return False

        task = " ".join(str(getattr(event, "task", "") or "").split())
        lowered = task.casefold()
        if any(marker.casefold() in lowered for marker in _CONTINUATION_INTENT_MARKERS):
            thread_id = str(getattr(event, "payload", {}).get("work_thread_id") or "").strip()
            return self._latest_research_bundle(thread_id) is not None if thread_id else False
        return any(marker.casefold() in lowered for marker in _RESEARCH_INTENT_MARKERS)

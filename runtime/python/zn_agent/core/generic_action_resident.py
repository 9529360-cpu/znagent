from __future__ import annotations

"""Generic bounded cognition-to-Action-Fabric resident loop."""

import uuid

from .action import NativeActionIntent
from .action_execution import ActionRequest
from .browser import BrowserPermissionContext
from .browser_loop import (
    browser_loop_catalog,
    browser_loop_spec,
    close_browser_loop_session,
    execute_browser_loop_step,
    parse_browser_permission,
    validate_browser_loop_arguments,
)
from .cognition import CognitiveIncrement
from .generic_action_loop import (
    build_generic_action_context,
    looks_like_generic_action_message,
    parse_generic_action_completion,
    parse_generic_action_proposal,
    summarize_action_execution,
)
from .models import ExecutionPath, ResidentRunResult, utc_now
from .research_information_resident import ResearchInformationResidentRuntime


class GenericActionResidentRuntime(ResearchInformationResidentRuntime):
    """Let bounded cognition propose one semantic action at a time.

    ZN retains action availability, schema, Body authority, verification,
    durable recovery and completion authority. The model can only propose the
    next catalog action or cite Resident-owned verified executions as evidence.
    """

    _GENERIC_ACTION_LOOP_KEY = "generic_action_loop"
    _GENERIC_ACTION_STAGE = "generic_action_execute"
    _GENERIC_ACTION_COMPLETION_STAGE = "generic_action_completion"
    _GENERIC_ACTION_MAX_STEPS = 12
    _GENERIC_ACTION_MAX_PROTOCOL_REPAIRS = 2
    _GENERIC_ACTION_MAX_REVERIFY_ATTEMPTS = 8

    def _browser_loop_provider(self, event):
        """Resident-owned browser provider, or None when no provider exists.

        Explicit injection (``browser_provider`` / ``managed_browser``) wins;
        otherwise the default managed-browser adapter is built lazily and
        cached. Building never launches a browser; a session opens only when
        the model proposes ``browser.navigate`` / ``browser.observe``.
        """
        for attribute in ("browser_provider", "managed_browser"):
            try:
                candidate = getattr(self, attribute, None)
            except Exception:
                candidate = None
            if candidate is not None:
                return candidate
        cache = getattr(self, "__dict__", {})
        if "_browser_loop_provider_cache" in cache:
            return cache["_browser_loop_provider_cache"]
        try:
            from .browser_provider_registry import build_managed_browser_adapter

            provider = build_managed_browser_adapter()
        except Exception:
            provider = None
        self._browser_loop_provider_cache = provider
        return provider

    def _browser_loop_permission(self, event):
        """Caller-owned browser permission, or None when not supplied.

        The permission comes from a resident-owned attribute or from the
        event payload (``browser_permission``). It is never model-supplied:
        the model proposes only targets and action arguments.
        """
        candidate = getattr(self, "browser_permission_context", None)
        if isinstance(candidate, BrowserPermissionContext):
            return candidate
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        return parse_browser_permission(payload.get("browser_permission"))

    def _resolve_browser_loop(self, event):
        provider = self._browser_loop_provider(event)
        if provider is None:
            raise ValueError("browser loop has no browser provider for this event")
        permission = self._browser_loop_permission(event)
        if permission is None:
            raise ValueError(
                "browser loop requires a caller-supplied browser_permission context; "
                "the model cannot grant browser permission itself"
            )
        return provider, permission

    def _browser_loop_available(self, event) -> bool:
        try:
            self._resolve_browser_loop(event)
        except (ValueError, TypeError):
            return False
        return True

    def _model_led_event_enabled(self, event) -> bool:
        """Explicitly selected model-led Work reuses the existing Resident loop.

        A model chooses the next semantic Action Fabric step, but ZN still owns
        the event, Work ledger, action authorization, verification and recovery.
        Ordinary Work and isolated cognition questions keep their prior routes.
        """
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        return payload.get("agent_loop") is True and self._generic_action_request_enabled(event)

    def _begin_model_led_event(self, event, state):
        required = self._required_capabilities(event)
        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=f"model-led Work requires permitted cognition: {decision.reason}",
            )

        # This is the SAME Resident event and the SAME cognitive resource
        # routing as ordinary Work. No separate model, tool or completion owner.
        impasse = self.life.begin_impasse(
            event,
            reason="model-led Work needs the next grounded decision",
            required_capabilities=required,
            local_failure=None,
        )
        cognition = self._build_cognition_request(event, impasse, required)
        state.data["impasse_id"] = impasse.impasse_id
        state.data["cognitive_budget"] = {
            "use_external_cognition": True,
            "max_model_calls": decision.max_model_calls,
            "reason": decision.reason,
        }
        state.data["cognition_request"] = {
            "request_id": cognition.request_id,
            "impasse_id": cognition.impasse_id,
            "event_id": cognition.event_id,
            "question": cognition.question,
            "required_capabilities": list(cognition.required_capabilities),
            "context": cognition.context,
            "created_at": cognition.created_at,
        }
        loop = self._generic_action_loop_state(state)
        loop["model_led"] = True
        loop["status"] = (
            "awaiting_next_model_decision" if loop["history"]
            else "awaiting_first_model_decision"
        )
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        state.stage = "external_cognition"
        state.next_action = "obtain first model decision using resident cognition"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _generic_action_request_enabled(self, event, context=None) -> bool:
        if str(getattr(event, "kind", "") or "") != "desktop_user_event":
            return False
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        if payload.get("body_action") is not None or payload.get("native_action") is not None:
            return False
        # An explicit cognition_question is a caller-owned isolation boundary:
        # do not silently append a machine-action catalog to that bounded
        # question. Active Work steering is the exception because its
        # cognition_question is Resident-authored plan context for the new event.
        if payload.get("cognition_question") and not isinstance(payload.get("work_steering"), dict):
            return False
        bounded = context if isinstance(context, dict) else {}
        if any(str(key).endswith("_contract") for key in bounded):
            return False
        return True

    def _generic_action_loop_state(self, state) -> dict:
        raw = state.data.get(self._GENERIC_ACTION_LOOP_KEY)
        if isinstance(raw, dict):
            loop = dict(raw)
        else:
            loop = {"version": 1}
        history = loop.get("history")
        loop["history"] = [dict(item) for item in history if isinstance(item, dict)] if isinstance(history, list) else []
        loop["protocol_repairs"] = max(0, int(loop.get("protocol_repairs") or 0))
        loop["model_invocations"] = max(0, int(loop.get("model_invocations") or 0))
        return loop

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(
            event,
            impasse,
            required,
            deliberation,
        )
        context = dict(request.context or {})
        if not self._generic_action_request_enabled(event, context):
            return request

        state = self.store.get_working_state()
        loop = self._generic_action_loop_state(state)
        history = tuple(loop.get("history") or ())
        action_context = build_generic_action_context(
            fabric=self.action_fabric,
            device_capabilities=self.device_capabilities,
            task=event.task,
            history=history,
        )
        if isinstance(loop.get("last_failure"), dict):
            action_context["last_failure"] = dict(loop["last_failure"])
        if loop.get("last_protocol_error"):
            action_context["last_protocol_error"] = str(loop["last_protocol_error"])[:1200]
        if self._browser_loop_available(event):
            action_context["available_actions"].extend(browser_loop_catalog())
            browser_state = loop.get("browser")
            action_context["browser_loop"] = (
                dict(browser_state)
                if isinstance(browser_state, dict)
                else {"session_open": False, "url": "", "page_id": ""}
            )
        context["generic_action_loop"] = action_context
        request.context = context

        protocol = (
            " ZN can execute one semantic local machine action at a time through the supplied "
            "generic_action_loop catalog. Never invent an action id or argument outside its schema. "
            "Never invent opaque local identifiers or semantic selectors such as application_id, "
            "control_name, or automation_id; obtain them from current context or fresh verified "
            "read-only action evidence first. If a local action is needed, return ONLY "
            '{"zn_action_proposal":{"action_id":"catalog.action.id","arguments":{}}}. '
            "After verified action evidence exists, either propose the next single action or, only when "
            "that evidence now satisfies the original user task, return ONLY "
            '{"zn_action_completion":{"execution_ids":["verified-id"],"response":"brief user-facing result"}}. '
            "Completion execution_ids must cite only verified ids supplied in recent_verified_executions."
        )
        if history:
            protocol += (
                " This event is already inside the generic action loop, so plain prose is not a valid "
                "completion signal; use one of the two exact JSON envelopes."
            )
        else:
            protocol += (
                " If the bounded question genuinely needs no local observation or effect, plain prose "
                "remains valid and no action envelope is required."
            )
        if self._browser_loop_available(event):
            protocol += (
                " Browser work uses the same envelopes with the browser.* catalog: start with "
                "browser.navigate to open the loop session, then use browser.semantic_* actions that "
                "find targets by exact accessible name on the currently pinned page, and browser.observe "
                "to re-observe. Never invent a session id, page id, or target id; the loop owns the "
                "session and pins the URL. After a URL-drift failure, decide again from the fresh "
                "observation instead of reusing the stale page."
            )
        request.question = str(request.question or "") + protocol
        return request

    def _external_cognition_step(self, event, state):
        raw = state.data.get("cognition_request")
        context = (
            raw.get("context")
            if isinstance(raw, dict) and isinstance(raw.get("context"), dict)
            else {}
        )
        generic = "generic_action_loop" in context
        run = super()._external_cognition_step(event, state)
        if not generic or run is None or not run.success:
            return run
        # CapabilityRecovery persists a recoverable external_completion first.
        # Generic desktop work must promote that durable result into the normal
        # cognition-integration stage instead of terminalizing model prose.
        return self._promote_external_completion(event, state, run)

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        raw_request = state.data.get("cognition_request")
        request_context = (
            raw_request.get("context")
            if isinstance(raw_request, dict) and isinstance(raw_request.get("context"), dict)
            else {}
        )
        if "generic_action_loop" not in request_context:
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        raw = state.data.get("cognitive_increment")
        if not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        increment = CognitiveIncrement.from_dict(raw)
        proposal = parse_generic_action_proposal(increment.content)
        if proposal is not None:
            return self._admit_generic_action_proposal(event, state, increment, proposal)

        completion = parse_generic_action_completion(increment.content)
        if completion is not None:
            return self._complete_generic_action_loop(event, state, increment, completion)

        loop = self._generic_action_loop_state(state)
        if looks_like_generic_action_message(increment.content):
            return self._reject_generic_action_cognition(
                event,
                state,
                "generic Action Fabric cognition returned a malformed strict JSON envelope",
            )
        if loop.get("history"):
            return self._reject_generic_action_cognition(
                event,
                state,
                "plain model prose cannot complete an event after generic machine actions have started",
            )
        return super()._cognition_integration_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _accept_generic_action_increment(self, event, state, increment) -> int:
        integration = state.data.get("cognition_integration")
        if (
            isinstance(integration, dict)
            and integration.get("accepted") is True
            and str(integration.get("increment_id") or "") == increment.increment_id
        ):
            external = state.data.get("external_cognition_result")
            return max(0, int(external.get("model_invocations") or 0)) if isinstance(external, dict) else 0

        external = state.data.get("external_cognition_result")
        external_data = external if isinstance(external, dict) else {}
        invocations = max(0, int(external_data.get("model_invocations") or 0))
        accepted_run = ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=True,
            response=increment.content,
            model_invocations=invocations,
            reason=f"accepted one bounded Action Fabric proposal from {increment.source}",
        )
        self.life.resolve_impasse(
            event,
            accepted_run,
            resolution_source=increment.source,
        )
        self.investigator.resolve_from_external(
            event.event_id,
            increment.content or "external cognition proposed one bounded semantic action",
        )
        domains = self.kernel.self_model.integrate_external_learning(
            event.task,
            self._required_capabilities(event),
            quality=increment.quality,
            confidence=increment.confidence,
        )
        state.data["cognition_integration"] = {
            "increment_id": increment.increment_id,
            "accepted": True,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.data["integrated_learning_domains"] = list(domains)
        return invocations

    def _clear_generic_cognition_state(self, state) -> None:
        for key in (
            "cognitive_increment",
            "external_cognition_result",
            "cognition_integration",
            "cognition_request",
            "impasse_id",
        ):
            state.data.pop(key, None)

    def _admit_generic_action_proposal(self, event, state, increment, proposal):
        loop = self._generic_action_loop_state(state)
        history = list(loop.get("history") or ())
        admitted = max(0, int(loop.get("actions_admitted") or 0))
        if admitted >= self._GENERIC_ACTION_MAX_STEPS:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="generic Action Fabric loop reached its bounded action limit",
            )

        browser_spec = browser_loop_spec(proposal.action_id)
        if browser_spec is not None:
            return self._admit_browser_loop_proposal(
                event, state, increment, proposal, browser_spec
            )

        descriptor = self.action_fabric.descriptor(proposal.action_id)
        if descriptor is None or not descriptor.body_action_kind:
            return self._reject_generic_action_cognition(
                event,
                state,
                f"model proposed unknown or non-executable Action Fabric action: {proposal.action_id}",
            )
        availability = self.action_fabric.availability(proposal.action_id)
        if not availability.available:
            return self._reject_generic_action_cognition(
                event,
                state,
                "model proposed an action that is not currently available: "
                f"{proposal.action_id}: {availability.state}: {availability.reason}",
            )

        invocations = self._accept_generic_action_increment(event, state, increment)
        loop["model_invocations"] = max(0, int(loop.get("model_invocations") or 0)) + invocations
        loop["actions_admitted"] = admitted + 1
        loop["protocol_repairs"] = 0
        proposal_id = f"generic-action-{uuid.uuid4().hex[:12]}"
        loop["pending"] = {
            "proposal_id": proposal_id,
            "action_id": proposal.action_id,
            "arguments": dict(proposal.arguments),
            "increment_id": increment.increment_id,
            "attempts": 0,
            "uncertain_attempts": 0,
            "admitted_at": utc_now(),
        }
        loop["status"] = "action_pending"
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop

        if descriptor.effect_class != "read_only":
            intent = NativeActionIntent(
                intent_id=proposal_id,
                event_id=event.event_id,
                kind=descriptor.body_action_kind,
                args=dict(proposal.arguments),
                expected_outcome={
                    "kind": "action_fabric",
                    "action_id": proposal.action_id,
                },
                reason=(
                    "external cognition proposed one schema-bounded semantic action; "
                    "ZN retained Body authority and verification"
                ),
                source="external_cognition_action_proposal",
            )
            state.data["native_action_intent"] = intent.to_dict()

        self._clear_generic_cognition_state(state)
        state.stage = self._GENERIC_ACTION_STAGE
        state.next_action = f"execute verified semantic action {proposal.action_id}"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _admit_browser_loop_proposal(self, event, state, increment, proposal, spec):
        loop = self._generic_action_loop_state(state)
        admitted = max(0, int(loop.get("actions_admitted") or 0))
        if admitted >= self._GENERIC_ACTION_MAX_STEPS:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="generic Action Fabric loop reached its bounded action limit",
            )
        try:
            normalized = validate_browser_loop_arguments(spec, proposal.arguments)
            _, permission = self._resolve_browser_loop(event)
        except ValueError as exc:
            return self._reject_generic_action_cognition(
                event,
                state,
                f"browser loop proposal rejected: {exc}",
            )
        if spec.kind is not None and not permission.allows_action(spec.kind):
            return self._reject_generic_action_cognition(
                event,
                state,
                f"browser permission does not allow {spec.kind.value}; the model cannot widen it",
            )

        invocations = self._accept_generic_action_increment(event, state, increment)
        loop["model_invocations"] = max(0, int(loop.get("model_invocations") or 0)) + invocations
        loop["actions_admitted"] = admitted + 1
        loop["protocol_repairs"] = 0
        proposal_id = f"browser-loop-{uuid.uuid4().hex[:12]}"
        loop["pending"] = {
            "proposal_id": proposal_id,
            "action_id": proposal.action_id,
            "arguments": dict(normalized),
            "increment_id": increment.increment_id,
            "attempts": 0,
            "uncertain_attempts": 0,
            "admitted_at": utc_now(),
            "browser_action": True,
        }
        loop["status"] = "action_pending"
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop

        if spec.effect_class != "read_only":
            intent = NativeActionIntent(
                intent_id=proposal_id,
                event_id=event.event_id,
                kind="browser_semantic_action",
                args={"action_id": proposal.action_id, "arguments": dict(normalized)},
                expected_outcome={
                    "kind": "browser_loop",
                    "action_id": proposal.action_id,
                },
                reason=(
                    "external cognition proposed one schema-bounded browser semantic action; "
                    "ZN retained browser permission authority and post-step verification"
                ),
                source="external_cognition_browser_proposal",
            )
            state.data["native_action_intent"] = intent.to_dict()

        self._clear_generic_cognition_state(state)
        state.stage = self._GENERIC_ACTION_STAGE
        state.next_action = f"execute verified browser semantic action {proposal.action_id}"
        state.blocked_by = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage in {"orient", "model_led_prepare"} and self._model_led_event_enabled(event):
            return self._begin_model_led_event(event, state)
        if state.stage == self._GENERIC_ACTION_STAGE:
            return self._generic_action_step(event, state)
        if state.stage == self._GENERIC_ACTION_COMPLETION_STAGE:
            return self._resume_generic_action_completion(event, state)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _generic_action_step(self, event, state):
        loop = self._generic_action_loop_state(state)
        pending = loop.get("pending")
        if not isinstance(pending, dict):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="generic Action Fabric stage lost its durable pending proposal",
            )

        action_id = str(pending.get("action_id") or "").strip()
        arguments = pending.get("arguments")
        proposal_id = str(pending.get("proposal_id") or "").strip()
        if not action_id or not proposal_id or not isinstance(arguments, dict):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="generic Action Fabric pending proposal is malformed",
            )

        if pending.get("browser_action") is True:
            return self._generic_browser_action_step(event, state, loop, pending)

        descriptor = self.action_fabric.descriptor(action_id)
        if descriptor is None or not descriptor.body_action_kind:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=f"generic Action Fabric action disappeared before execution: {action_id}",
            )

        raw_reverification = pending.get("reverification")
        if isinstance(raw_reverification, dict):
            pending["reverify_attempts"] = max(
                0,
                int(pending.get("reverify_attempts") or 0),
            ) + 1
            pending["last_reverify_at"] = utc_now()
            loop["pending"] = pending
            loop["status"] = "reverifying"
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            self.store.save_working_state(state)
            execution = self.action_executor.verify_checkpoint(raw_reverification)
        else:
            pending["attempts"] = max(0, int(pending.get("attempts") or 0)) + 1
            pending["last_attempt_at"] = utc_now()
            loop["pending"] = pending
            loop["status"] = "executing"
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            self.store.save_working_state(state)
            execution = self.action_executor.execute(
                ActionRequest(
                    action_id,
                    dict(arguments),
                    event_id=event.event_id,
                )
            )

        summary = summarize_action_execution(execution)
        summary["proposal_id"] = proposal_id
        summary["recorded_at"] = utc_now()

        if execution.status == "pending":
            try:
                pending["reverification"] = (
                    self.action_executor.reverification_checkpoint(execution)
                )
            except (KeyError, TypeError, ValueError) as exc:
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason=(
                        "generic Action Fabric produced a pending execution without a "
                        f"durable-safe reverification contract: {type(exc).__name__}: {exc}"
                    ),
                )
            pending["last_pending_execution"] = summary
            reverify_attempts = max(
                0,
                int(pending.get("reverify_attempts") or 0),
            )
            if reverify_attempts >= self._GENERIC_ACTION_MAX_REVERIFY_ATTEMPTS:
                loop.pop("pending", None)
                loop["status"] = "pending_verification_exhausted"
                loop["last_failure"] = summary
                state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
                state.data.pop("native_action_intent", None)
                failure = (
                    "Action Fabric effect remained pending without fresh proof after "
                    f"{reverify_attempts} bounded reverification attempts: {action_id}"
                )
                state.data["local_failure"] = failure
                self.investigator.reopen_after_external(
                    event.event_id,
                    failure,
                )
                state.stage = "native_investigation"
                state.next_action = (
                    "inspect the unproven asynchronous effect before choosing another action"
                )
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None

            loop["pending"] = pending
            loop["status"] = "reverify_pending"
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            state.stage = self._GENERIC_ACTION_STAGE
            state.next_action = (
                f"re-observe pending semantic action {action_id} without redispatch"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if execution.success:
            history = [
                dict(item)
                for item in loop.get("history") or ()
                if isinstance(item, dict)
                and str(item.get("proposal_id") or "") != proposal_id
            ]
            history.append(summary)
            loop["history"] = history[-self._GENERIC_ACTION_MAX_STEPS :]
            loop.pop("pending", None)
            loop["status"] = "awaiting_next_cognition"
            loop["last_verified_execution_id"] = summary["execution_id"]
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            state.data.pop("native_action_intent", None)
            state.data.pop("local_failure", None)
            if loop.get("model_led") is True:
                # A fresh verified result must be checkpointed before the next
                # cognition request reads the durable Work state. This stage
                # also survives a crash between verification and model recall.
                state.stage = "model_led_prepare"
                state.next_action = "prepare model decision from verified Body evidence"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return self._begin_model_led_event(event, state)
            self.investigator.reopen_after_external(
                event.event_id,
                f"verified Action Fabric execution {summary['execution_id']} changed current reality",
            )
            state.stage = "native_deliberation"
            state.next_action = "reassess the remaining user goal from verified action evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if execution.status == "uncertain" and descriptor.effect_class != "read_only":
            pending["uncertain_attempts"] = max(
                0,
                int(pending.get("uncertain_attempts") or 0),
            ) + 1
            pending["last_uncertain_execution"] = summary
            loop["pending"] = pending
            loop["status"] = "reverify_pending"
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            if pending["uncertain_attempts"] <= 2:
                state.stage = self._GENERIC_ACTION_STAGE
                state.next_action = (
                    "re-enter the same Action Fabric execution so Body can verify-before-replay"
                )
                self.store.save_working_state(state)
                return None
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "generic Action Fabric side effect remained uncertain after bounded "
                    f"verify-before-replay attempts: {action_id}"
                ),
            )

        loop.pop("pending", None)
        loop["status"] = "action_failed"
        loop["last_failure"] = summary
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        state.data.pop("native_action_intent", None)
        failure = (
            execution.error
            or execution.verification.reason
            or f"Action Fabric execution failed: {action_id}"
        )
        state.data["local_failure"] = str(failure)[:1600]
        if loop.get("model_led") is True and descriptor.effect_class == "read_only":
            # A failed read cannot have dispatched an effect. Let the model
            # choose a different observation/tool directly from fresh failure
            # evidence, rather than returning ownership to a native planner.
            state.stage = "model_led_prepare"
            state.next_action = "reconsider read tool after verified failure"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._begin_model_led_event(event, state)
        self.investigator.reopen_after_external(
            event.event_id,
            f"Action Fabric execution failed after accepted cognition: {str(failure)[:900]}",
        )
        state.stage = "native_investigation"
        state.next_action = "inspect the failed semantic action before asking cognition for a repair"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _generic_browser_action_step(self, event, state, loop, pending):
        """Execute one admitted browser proposal exactly once, then verify.

        Unlike the Action Fabric path there is no reverification re-entry
        here: a dispatched, uncertain, or failed browser effect is never
        re-dispatched. The failure (with fresh observation evidence) goes
        back to cognition / investigation so the next decision is made from
        fresh state.
        """
        action_id = str(pending.get("action_id") or "").strip()
        arguments = pending.get("arguments")
        proposal_id = str(pending.get("proposal_id") or "").strip()
        spec = browser_loop_spec(action_id)
        if spec is None or not isinstance(arguments, dict):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="browser loop pending proposal is malformed",
            )
        try:
            provider, permission = self._resolve_browser_loop(event)
        except ValueError as exc:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=f"browser loop lost its provider or permission before execution: {exc}",
            )
        pending["attempts"] = max(0, int(pending.get("attempts") or 0)) + 1
        pending["last_attempt_at"] = utc_now()
        loop["pending"] = pending
        loop["status"] = "executing"
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        self.store.save_working_state(state)

        result = execute_browser_loop_step(
            provider,
            session=loop.get("browser"),
            permission=permission,
            action_id=action_id,
            arguments=arguments,
        )
        loop["browser"] = dict(result.session)
        summary = summarize_action_execution(result.execution)
        summary["proposal_id"] = proposal_id
        summary["recorded_at"] = utc_now()

        if result.execution.success:
            history = [
                dict(item)
                for item in loop.get("history") or ()
                if isinstance(item, dict)
                and str(item.get("proposal_id") or "") != proposal_id
            ]
            history.append(summary)
            loop["history"] = history[-self._GENERIC_ACTION_MAX_STEPS :]
            loop.pop("pending", None)
            loop["status"] = "awaiting_next_cognition"
            loop["last_verified_execution_id"] = summary["execution_id"]
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
            state.data.pop("native_action_intent", None)
            state.data.pop("local_failure", None)
            if loop.get("model_led") is True:
                state.stage = "model_led_prepare"
                state.next_action = "prepare model decision from verified browser evidence"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return self._begin_model_led_event(event, state)
            self.investigator.reopen_after_external(
                event.event_id,
                f"verified browser execution {summary['execution_id']} changed current reality",
            )
            state.stage = "native_deliberation"
            state.next_action = "reassess the remaining user goal from verified browser evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        loop.pop("pending", None)
        loop["status"] = "action_failed"
        loop["last_failure"] = summary
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        state.data.pop("native_action_intent", None)
        failure = (
            result.execution.error
            or result.execution.verification.reason
            or f"browser loop execution failed: {action_id}"
        )
        state.data["local_failure"] = str(failure)[:1600]
        if loop.get("model_led") is True and spec.effect_class == "read_only":
            state.stage = "model_led_prepare"
            state.next_action = "reconsider browser read after verified failure"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._begin_model_led_event(event, state)
        self.investigator.reopen_after_external(
            event.event_id,
            f"browser loop execution failed after accepted cognition: {str(failure)[:900]}",
        )
        state.stage = "native_investigation"
        state.next_action = "inspect the failed browser semantic action before asking cognition for a repair"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_generic_action_loop(self, event, state, increment, completion):
        loop = self._generic_action_loop_state(state)
        history = [dict(item) for item in loop.get("history") or () if isinstance(item, dict)]
        if not history:
            return self._reject_generic_action_cognition(
                event,
                state,
                "generic action completion cannot precede verified Action Fabric evidence",
            )

        by_id = {
            str(item.get("execution_id") or ""): item
            for item in history
            if str(item.get("execution_id") or "")
        }
        cited = tuple(completion.execution_ids)
        invalid = [
            execution_id
            for execution_id in cited
            if execution_id not in by_id or by_id[execution_id].get("verified") is not True
        ]
        latest_id = str(history[-1].get("execution_id") or "")
        if invalid or not latest_id or latest_id not in cited:
            return self._reject_generic_action_cognition(
                event,
                state,
                "generic action completion cited missing/stale/unverified execution evidence",
            )

        invocations = self._accept_generic_action_increment(event, state, increment)
        total_invocations = max(0, int(loop.get("model_invocations") or 0)) + invocations
        loop["model_invocations"] = total_invocations
        loop["status"] = "completed"
        loop["completion_execution_ids"] = list(cited)
        loop["completed_at"] = utc_now()
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        self._clear_generic_cognition_state(state)
        state.data.pop("native_action_intent", None)
        state.data.pop("local_failure", None)

        response = completion.response.strip() or "Completed with verified local action evidence."
        checkpoint = {
            "execution_path": ExecutionPath.BODY.value,
            "success": True,
            "response": response,
            "model_invocations": total_invocations,
            "reason": (
                "ZN completed generic desktop work only after cognition cited current "
                "Resident-owned verified Action Fabric execution evidence"
            ),
            "execution_ids": list(cited),
        }
        state.data["generic_action_completion"] = checkpoint
        browser_state = loop.get("browser")
        if isinstance(browser_state, dict) and browser_state.get("session_id"):
            try:
                browser_provider, _ = self._resolve_browser_loop(event)
            except ValueError:
                browser_provider = None
            close_browser_loop_session(browser_provider, browser_state)
            loop.pop("browser", None)
            state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        state.stage = self._GENERIC_ACTION_COMPLETION_STAGE
        state.next_action = "publish terminal EventOutcome"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return self._generic_action_completion_result(event, checkpoint)

    def _resume_generic_action_completion(self, event, state):
        raw = state.data.get("generic_action_completion")
        if not isinstance(raw, dict):
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.BODY,
                success=False,
                model_invocations=0,
                reason="durable generic action completion checkpoint is missing",
            )
        return self._generic_action_completion_result(event, raw)

    @staticmethod
    def _generic_action_completion_result(event, raw):
        if raw.get("success") is not True:
            raise ValueError("generic action completion checkpoint must record success")
        execution_path = ExecutionPath(str(raw.get("execution_path") or ""))
        if execution_path is not ExecutionPath.BODY:
            raise ValueError("generic action completion must use the Body execution path")
        execution_ids = raw.get("execution_ids")
        if not isinstance(execution_ids, list) or not all(str(item).strip() for item in execution_ids):
            raise ValueError("generic action completion must retain verified execution ids")
        return ResidentRunResult(
            event=event,
            execution_path=execution_path,
            success=True,
            response=str(raw.get("response") or ""),
            model_invocations=max(0, int(raw.get("model_invocations") or 0)),
            reason=str(raw.get("reason") or ""),
        )

    def _reject_generic_action_cognition(self, event, state, reason):
        loop = self._generic_action_loop_state(state)
        external = state.data.get("external_cognition_result")
        if isinstance(external, dict):
            loop["model_invocations"] = max(
                0,
                int(loop.get("model_invocations") or 0),
            ) + max(0, int(external.get("model_invocations") or 0))
        loop["protocol_repairs"] = max(0, int(loop.get("protocol_repairs") or 0)) + 1
        loop["last_protocol_error"] = str(reason)[:1200]
        loop["status"] = "protocol_repair"
        state.data[self._GENERIC_ACTION_LOOP_KEY] = loop
        self._clear_generic_cognition_state(state)
        state.data["local_failure"] = str(reason)[:1600]

        if loop["protocol_repairs"] > self._GENERIC_ACTION_MAX_PROTOCOL_REPAIRS:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "generic Action Fabric cognition exceeded bounded protocol repair attempts: "
                    f"{reason}"
                ),
            )

        if loop.get("model_led") is True:
            # The existing bounded protocol-repair budget still applies; the
            # model should correct its proposal from the same Work evidence.
            state.stage = "model_led_prepare"
            state.next_action = "repair rejected model tool proposal"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return self._begin_model_led_event(event, state)
        self.investigator.reopen_after_external(
            event.event_id,
            f"generic Action Fabric cognition was rejected: {str(reason)[:900]}",
        )
        state.stage = "native_investigation"
        state.next_action = "repair the rejected generic action proposal from bounded evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None
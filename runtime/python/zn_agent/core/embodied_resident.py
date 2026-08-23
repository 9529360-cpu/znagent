from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent, derive_native_action_intent
from .budget import CognitiveBudgetManager
from .capabilities import CapabilityRegistry
from .cognition import CognitiveIncrement
from .memory import StructuredMemory
from .models import (
    AgentEvent,
    ExecutionPath,
    ResidentRunResult,
    WorkingState,
    utc_now,
)
from .resident import ZNResidentRuntime
from .result_semantics import normalize_action_result
from .self_model import TaskReadiness
from .verified_experience import VerifiedExperienceStore, build_verified_experience


class EmbodiedResidentRuntime(ZNResidentRuntime):
    """Resident runtime whose native cognition can produce concrete body action.

    The compatibility base class still provides the mature event/action methods,
    but this resident owns its birth sequence so it never instantiates a legacy
    LifeCore and then swaps in a richer one. Body, Investigation and embodied
    Life are present from the first loaded durable state.

        Situation -> Thought -> Body -> evidence/outcome -> Situation
        Impasse -> external cognition -> CognitiveIncrement -> Thought -> result

    It does not turn tools into skills and it does not add policy gates. Body
    and external brains remain resources; the resident decides how to use and
    integrate them.
    """

    _ACTIVE_THOUGHT_KINDS = {
        *ZNResidentRuntime._ACTIVE_THOUGHT_KINDS,
        "body_action",
        "verify_action",
        "integrate_cognition",
    }
    _FAILED_ACTION_RECORDS_KEY = "native_action_failure_records"
    _MAX_FAILED_ACTION_RECORDS = 16
    _VOLATILE_FACT_KEYS = frozenset(
        {
            "captured_at",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "observed_at",
            "checked_at",
            "sampled_at",
            "timestamp",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        # Do not call ZNResidentRuntime.__init__: it deliberately constructs the
        # compatibility ZNLifeCore first, which cannot deserialize the richer
        # CognitiveSituation persisted by this resident. An embodied resident is
        # born once with the correct organs instead of being assembled after a
        # temporary legacy birth.
        self.kernel = kernel
        self.store = kernel.store
        self.identity = kernel.identity
        self.capabilities = capabilities or CapabilityRegistry()
        self.budget = budget or CognitiveBudgetManager()
        self.memory = StructuredMemory(self.store)
        self.verified_experiences = VerifiedExperienceStore(self.store)
        self._cycle_lock = threading.RLock()
        self.store.recover_interrupted_events()
        self.store.get_working_state()

        from .body import NativeBody
        from .embodied_investigation import EmbodiedInvestigator
        from .embodied_life import EmbodiedLifeCore

        self.body = NativeBody(resident=self)
        self.investigator = EmbodiedInvestigator(self)
        self.life = EmbodiedLifeCore(self)
        self.life.wake()

    def _advance_event_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        if state.stage == "native_action":
            return self._native_action_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if state.stage == "native_verification":
            return self._native_verification_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if state.stage == "cognition_integration":
            return self._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _deliberation_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        learning_evidence: list[dict[str, Any]],
        thought=None,
    ) -> ResidentRunResult | None:
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)

        if intent is not None:
            # A failed movement remains blocked while the Investigation facts
            # describing current reality are unchanged. A different failure in
            # between cannot erase it, and a merely repeated probe does not
            # unlock it. Genuinely revised facts create a new evidence version.
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform body action: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; native evidence supports a concrete body movement"
                    )
                    self._persist_enriched_thought(thought)
                return None

        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _begin_native_action_cycle(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
    ) -> None:
        """Begin one new movement without carrying a stale verdict into it.

        Prior failed verification remains available as bounded history, but the
        active verification slot is cleared before a genuinely different action
        becomes current. This keeps one compact task context instead of letting
        old result fields silently masquerade as present reality.
        """
        raw_context = state.data.get("execution_context")
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        raw_history = context.get("verification_history")
        history = list(raw_history) if isinstance(raw_history, list) else []
        prior = state.data.get("native_verification_result")
        if isinstance(prior, dict):
            history.append(
                self._verification_summary(
                    prior,
                    error=str(state.data.get("local_failure") or "").strip() or None,
                )
            )
        context["verification_history"] = history[-8:]
        state.data["execution_context"] = context

        state.data.pop("native_verification", None)
        state.data.pop("native_verification_result", None)
        state.data.pop("native_action_result", None)
        state.data.pop("local_failure", None)
        # This field existed before evidence-bound records. Keep lazy read
        # migration for old persisted state, but never carry the one-slot guard
        # into a newly admitted action cycle.
        state.data.pop("native_action_failure_signature", None)
        state.data["native_action_intent"] = intent.to_dict()
        state.stage = "native_action"
        state.next_action = f"move body: {intent.kind}"
        self._sync_execution_context(event, state)

    def _native_action_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        raw = state.data.get("native_action_intent")
        if not isinstance(raw, dict):
            state.stage = "native_deliberation"
            state.next_action = "reconstruct missing native action intent"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent.from_dict(raw)
        result = self.body.act(
            intent.kind,
            event_id=event.event_id,
            **dict(intent.args),
        )
        state.data["native_action_result"] = asdict(result)

        if result.success:
            verification = self._verification_contract(event, intent)
            if verification is not None:
                # A successful movement is evidence, not proof that the user's
                # requested state now exists. Persist the postcondition and let
                # a later resident pulse re-observe reality before completion.
                state.data["native_verification"] = verification
                state.stage = "native_verification"
                state.next_action = "verify the requested postcondition from current reality"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "verify the body action against the requested postcondition"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the body movement returned successfully but task "
                        "completion still requires independent observation"
                    )
                    self._persist_enriched_thought(thought)
                return None

            self._sync_execution_context(event, state)
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=result.output.strip()
                or json.dumps(result.data, ensure_ascii=False, sort_keys=True),
                reason=f"ZN completed the task through its body: {intent.kind}",
            )

        self.kernel.self_model.observe_native_outcome(
            event.task,
            self._required_capabilities(event),
            success=False,
        )
        failure = result.error or f"body action {intent.kind} failed"
        state.data["local_failure"] = failure
        self._record_failed_action(
            event,
            state,
            intent,
            source="body",
            failure=failure,
        )
        state.stage = "native_investigation"
        state.next_action = "inspect the failed body movement and update the hypothesis"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; the attempted body movement produced new failure evidence"
            )
            self._persist_enriched_thought(thought)
        return None

    def _native_verification_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        raw_contract = state.data.get("native_verification")
        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_contract, dict) or not isinstance(raw_intent, dict):
            state.stage = "native_deliberation"
            state.next_action = "reconstruct missing postcondition verification"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent.from_dict(raw_intent)
        kind = str(raw_contract.get("kind") or "")
        verified = False
        response = ""
        failure = ""
        verification_result: dict[str, Any]

        if kind == "text_equals":
            path = str(raw_contract.get("path") or "")
            expected = str(raw_contract.get("expected_text") or "")
            observed = self.body.act(
                "read_text",
                event_id=event.event_id,
                path=path,
                max_chars=max(1, len(expected) + 1),
            )
            verified = bool(
                observed.success
                and not bool(observed.data.get("truncated"))
                and observed.output == expected
            )
            verification_result = {
                "verified": verified,
                "kind": kind,
                "path": path,
                "expected_chars": len(expected),
                "observed_chars": (
                    int(observed.data.get("chars") or len(observed.output))
                    if observed.success
                    else None
                ),
                "observation": asdict(observed),
            }
            response = path
            if observed.success:
                failure = (
                    f"postcondition verification failed for {path}: requested text state "
                    "does not match current reality"
                )
            else:
                failure = (
                    f"postcondition verification failed for {path}: "
                    f"{observed.error or 'current text state could not be observed'}"
                )

        elif kind == "command":
            command = str(raw_contract.get("command") or "").strip()
            workdir = str(raw_contract.get("workdir") or "").strip() or None
            expected_exit_code = int(raw_contract.get("expected_exit_code", 0))
            expected_output = [
                str(item)
                for item in raw_contract.get("output_contains") or ()
                if str(item)
            ]
            observed = self.body.act(
                "command",
                event_id=event.event_id,
                command=command,
                **({"workdir": workdir} if workdir else {}),
                timeout=max(0.05, float(raw_contract.get("timeout", 60.0))),
                max_output_chars=max(
                    128,
                    int(raw_contract.get("max_output_chars", 50_000)),
                ),
            )
            exit_code = observed.data.get("exit_code")
            timed_out = bool(observed.data.get("timed_out", False))
            missing_output = [
                fragment
                for fragment in expected_output
                if fragment not in observed.output
            ]
            result_features = normalize_action_result(
                asdict(observed),
                command=command,
            )
            masked_success = bool(result_features.get("masked_success"))
            verified = bool(
                not timed_out
                and exit_code == expected_exit_code
                and not missing_output
                and not masked_success
            )
            verification_result = {
                "verified": verified,
                "kind": kind,
                "command": command,
                "workdir": workdir,
                "expected_exit_code": expected_exit_code,
                "observed_exit_code": exit_code,
                "expected_output_contains": expected_output,
                "missing_output_contains": missing_output,
                "result_features": result_features,
                "observation": asdict(observed),
            }
            response = observed.output.strip() or (
                f"verified postcondition command with exit code {exit_code}"
            )
            problems: list[str] = []
            if timed_out:
                problems.append("verification command timed out")
            if exit_code != expected_exit_code:
                problems.append(
                    f"expected exit code {expected_exit_code}, observed {exit_code}"
                )
            if missing_output:
                problems.append(
                    "missing expected output fragment(s): "
                    + ", ".join(repr(item) for item in missing_output)
                )
            if masked_success:
                problems.append(
                    "verification shell status was masked by deterministic failure evidence"
                )
            failure = (
                "postcondition command verification failed: "
                + ("; ".join(problems) or "current reality did not satisfy the check")
            )

        else:
            requested = str(raw_contract.get("requested_kind") or kind or "<empty>")
            failure = str(
                raw_contract.get("error")
                or f"unsupported postcondition verification kind: {requested}"
            )
            verification_result = {
                "verified": False,
                "kind": kind or "unsupported",
                "requested_kind": requested,
                "error": failure,
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
                response=response,
                reason=(
                    "ZN completed the task only after independently verifying the "
                    "requested postcondition through its body"
                ),
            )

        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )

    def _record_verified_experience(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        verification_result: dict[str, Any],
    ) -> None:
        raw_contract = state.data.get("native_verification")
        raw_primary = state.data.get("native_action_result")
        if not isinstance(raw_contract, dict) or not isinstance(raw_primary, dict):
            return

        context = state.data.get("execution_context")
        context_data = context if isinstance(context, dict) else {}
        integration = state.data.get("cognition_integration")
        source = (
            "external-cognition-assisted"
            if isinstance(integration, dict) and bool(integration.get("accepted"))
            else "native"
        )
        primary_command = (
            str(intent.args.get("command") or "").strip() or None
            if intent.kind in {"command", "terminal", "shell"}
            else None
        )
        experience = build_verified_experience(
            event_id=event.event_id,
            goal=event.task,
            gap=str(context_data.get("current_gap") or "").strip() or None,
            source=source,
            domains=self._required_capabilities(event),
            situation_evidence_fingerprint=self._evidence_fingerprint(event.event_id),
            action_kind=intent.kind,
            action_signature_hash=self._signature_hash(intent),
            primary_action_result=raw_primary,
            primary_command=primary_command,
            expected_outcome=raw_contract,
            verification_result=verification_result,
        )
        if experience is None:
            return
        self.verified_experiences.record(experience)
        state.data["latest_verified_experience"] = {
            "experience_id": experience.experience_id,
            "verdict": experience.verdict,
            "group_key": experience.group_key,
            "source": experience.source,
        }

    def _fail_postcondition_verification(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        failure: str,
        thought=None,
    ) -> None:
        self.kernel.self_model.observe_native_outcome(
            event.task,
            self._required_capabilities(event),
            success=False,
        )
        state.data["local_failure"] = failure
        self._record_failed_action(
            event,
            state,
            intent,
            source="verification",
            failure=failure,
        )
        state.stage = "native_investigation"
        state.next_action = "investigate the contradicted postcondition before another movement"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            if failure not in thought.unknown:
                thought.unknown = (*thought.unknown, failure)
            thought.reason = (
                f"{thought.reason}; current reality contradicted the expected result of my "
                "previous body movement"
            )
            self._persist_enriched_thought(thought)
        return None

    def _complete_successful_body_action(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        response: str,
        reason: str,
    ) -> ResidentRunResult:
        domains = self.kernel.self_model.observe_native_outcome(
            event.task,
            self._required_capabilities(event),
            success=True,
            quality=0.95,
        )
        state.stage = "complete"
        state.next_action = None
        state.data["native_domains"] = list(domains)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        self.store.record_runtime_task(model_invocations=0)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=response,
            model_invocations=0,
            reason=reason,
        )

    def _sync_execution_context(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> dict[str, Any]:
        """Keep one bounded task-level execution view inside durable work state.

        This is not a plan tree. It is the minimum current contract needed for
        the same resident to remember what it is trying to achieve, what still
        blocks it, what result it expects, and what reality most recently said.
        """
        raw_context = state.data.get("execution_context")
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        context["goal"] = event.task
        context["stage"] = str(state.stage or "idle")

        gap = str(state.data.get("local_failure") or "").strip()
        if not gap:
            deliberation = state.data.get("native_deliberation")
            if isinstance(deliberation, dict):
                gap = str(deliberation.get("unknown") or "").strip()
        if not gap:
            investigation = self.investigator.current(event.event_id)
            if investigation is not None:
                gap = str(investigation.unresolved or "").strip()
        context["current_gap"] = gap or None

        raw_expected = state.data.get("native_verification")
        if not isinstance(raw_expected, dict):
            explicit = event.payload.get("expected_outcome")
            raw_expected = explicit if isinstance(explicit, dict) else None
        context["expected_outcome"] = (
            self._expected_outcome_summary(raw_expected)
            if isinstance(raw_expected, dict)
            else None
        )

        raw_verification = state.data.get("native_verification_result")
        context["latest_verification"] = (
            self._verification_summary(
                raw_verification,
                error=str(state.data.get("local_failure") or "").strip() or None,
            )
            if isinstance(raw_verification, dict)
            else None
        )

        raw_intent = state.data.get("native_action_intent")
        if isinstance(raw_intent, dict):
            context["current_action"] = {
                "intent_id": str(raw_intent.get("intent_id") or "") or None,
                "kind": str(raw_intent.get("kind") or "") or None,
                "reason": str(raw_intent.get("reason") or "")[:600] or None,
            }
        else:
            context["current_action"] = None
        history = context.get("verification_history")
        if isinstance(history, list):
            context["verification_history"] = history[-8:]
        else:
            context["verification_history"] = []

        failed_actions = self._failure_records(state)
        evidence_fingerprint = self._evidence_fingerprint(event.event_id)
        current_failures = [
            item
            for item in failed_actions
            if str(item.get("evidence_fingerprint") or "") == evidence_fingerprint
        ]
        context["failed_actions"] = {
            "total": len(failed_actions),
            "current_evidence_count": len(current_failures),
            "evidence_version": evidence_fingerprint[:16],
            "recent": [self._failure_summary(item) for item in failed_actions[-8:]],
        }
        context["updated_at"] = utc_now()
        state.data["execution_context"] = context
        return context

    @staticmethod
    def _expected_outcome_summary(raw: dict[str, Any]) -> dict[str, Any]:
        kind = str(raw.get("kind") or "").strip().lower() or "unknown"
        summary: dict[str, Any] = {"kind": kind}
        if raw.get("path") is not None:
            summary["path"] = str(raw.get("path"))
        if raw.get("expected_text") is not None:
            summary["expected_chars"] = len(str(raw.get("expected_text") or ""))
        if raw.get("expected_exit_code") is not None:
            summary["expected_exit_code"] = raw.get("expected_exit_code")
        elif raw.get("exit_code") is not None:
            summary["expected_exit_code"] = raw.get("exit_code")
        output = raw.get("output_contains")
        if isinstance(output, str):
            summary["output_contains"] = [output]
        elif isinstance(output, (list, tuple)):
            summary["output_contains"] = [str(item) for item in output if str(item)][:8]
        return summary

    @staticmethod
    def _verification_summary(
        raw: dict[str, Any],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "kind": str(raw.get("kind") or "unknown"),
            "verified": bool(raw.get("verified")),
        }
        for key in (
            "path",
            "expected_chars",
            "observed_chars",
            "expected_exit_code",
            "observed_exit_code",
            "requested_kind",
        ):
            if raw.get(key) is not None:
                summary[key] = raw.get(key)
        missing = raw.get("missing_output_contains")
        if isinstance(missing, (list, tuple)) and missing:
            summary["missing_output_contains"] = [str(item) for item in missing][:8]
        message = str(error or raw.get("error") or "").strip()
        if message:
            summary["error"] = message[:1000]
        return summary

    @staticmethod
    def _verification_contract(
        event: AgentEvent,
        intent: NativeActionIntent,
    ) -> dict[str, Any] | None:
        explicit = event.payload.get("expected_outcome")
        if explicit is not None:
            if not isinstance(explicit, dict):
                return {
                    "kind": "unsupported",
                    "requested_kind": type(explicit).__name__,
                    "error": "expected_outcome must be a structured object",
                    "intent_id": intent.intent_id,
                    "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
                }

            requested_kind = str(explicit.get("kind") or "").strip().lower()
            if requested_kind in {"command", "command_check", "command_succeeds"}:
                command = str(explicit.get("command") or "").strip()
                if not command:
                    return {
                        "kind": "unsupported",
                        "requested_kind": requested_kind or "command",
                        "error": "command postcondition requires a verification command",
                        "intent_id": intent.intent_id,
                        "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
                    }
                try:
                    expected_exit_code = int(explicit.get("exit_code", 0))
                    timeout = max(0.05, float(explicit.get("timeout", 60.0)))
                    max_output_chars = max(
                        128,
                        int(explicit.get("max_output_chars", 50_000)),
                    )
                except (TypeError, ValueError):
                    return {
                        "kind": "unsupported",
                        "requested_kind": requested_kind,
                        "error": "command postcondition has invalid numeric limits",
                        "intent_id": intent.intent_id,
                        "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
                    }
                raw_output = explicit.get("output_contains")
                if raw_output is None:
                    output_contains: list[str] = []
                elif isinstance(raw_output, str):
                    output_contains = [raw_output]
                elif isinstance(raw_output, (list, tuple)):
                    output_contains = [str(item) for item in raw_output if str(item)]
                else:
                    return {
                        "kind": "unsupported",
                        "requested_kind": requested_kind,
                        "error": (
                            "command postcondition output_contains must be a string or list"
                        ),
                        "intent_id": intent.intent_id,
                        "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
                    }
                workdir = (
                    str(explicit.get("workdir") or intent.args.get("workdir") or "").strip()
                    or None
                )
                return {
                    "kind": "command",
                    "command": command,
                    "workdir": workdir,
                    "expected_exit_code": expected_exit_code,
                    "output_contains": output_contains,
                    "timeout": timeout,
                    "max_output_chars": max_output_chars,
                    "intent_id": intent.intent_id,
                    "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
                }

            return {
                "kind": "unsupported",
                "requested_kind": requested_kind or "<empty>",
                "error": (
                    "unsupported expected_outcome kind: "
                    f"{requested_kind or '<empty>'}"
                ),
                "intent_id": intent.intent_id,
                "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
            }

        # Replace/create text mutations have a naturally observable exact
        # postcondition, so they get verification without requiring callers to
        # describe a second probe. Append and generic commands require an
        # explicit task-level expected_outcome before action success can be
        # distinguished from goal completion.
        if intent.kind != "write_text" or bool(intent.args.get("append", False)):
            return None
        path = str(intent.args.get("path") or "").strip()
        if not path:
            return None
        return {
            "kind": "text_equals",
            "path": path,
            "expected_text": str(intent.args.get("content") or ""),
            "intent_id": intent.intent_id,
            "action_signature": EmbodiedResidentRuntime._intent_signature(intent),
        }

    def _external_cognition_step(
        self,
        event: AgentEvent,
        state: WorkingState,
    ) -> ResidentRunResult | None:
        """Borrow cognition without accepting or learning it yet."""
        raw = state.data.get("cognition_request")
        if not isinstance(raw, dict):
            raise RuntimeError("external cognition stage has no cognition request")

        required = tuple(raw.get("required_capabilities") or self._required_capabilities(event))
        question = str(raw.get("question") or event.task)
        context = dict(raw.get("context") or {})
        impasse_id = str(raw.get("impasse_id") or state.data.get("impasse_id") or "")

        budget = state.data.get("cognitive_budget")
        max_calls = 1
        decision_reason = "native investigation exhausted its current probes"
        if isinstance(budget, dict):
            try:
                max_calls = max(1, int(budget.get("max_model_calls") or 1))
            except (TypeError, ValueError):
                max_calls = 1
            decision_reason = str(budget.get("reason") or decision_reason)

        kernel_result = self.kernel.run_goal(
            question,
            required_capabilities=required,
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "impasse_id": impasse_id,
                "cognition_request": {
                    "request_id": raw.get("request_id"),
                    "context": context,
                },
            },
            max_attempts_override=max_calls,
        )
        invocations = sum(
            1
            for experience in kernel_result.experiences
            if experience.metrics.get("model_invoked", True) is not False
        )
        prompt_tokens, completion_tokens = self._sum_tokens(kernel_result)
        self.store.record_runtime_task(
            model_invocations=invocations,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        state.current_goal_id = kernel_result.goal.goal_id

        reason = decision_reason
        if not kernel_result.assessment.success and kernel_result.worker_result.error:
            reason = kernel_result.worker_result.error
        if not kernel_result.assessment.success:
            state.stage = "failed"
            state.next_action = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            self.life.mark_impasse_unresolved(event, reason)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MODEL,
                success=False,
                response=kernel_result.worker_result.response,
                model_invocations=invocations,
                reason=reason,
                kernel_result=kernel_result,
            )

        route_id = kernel_result.goal.route_id or "external"
        increment = CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id=impasse_id or None,
            source=f"external:{route_id}",
            question=question,
            content=kernel_result.worker_result.response,
            quality=kernel_result.assessment.quality,
            confidence=kernel_result.assessment.confidence,
        )
        # The increment is durable working state, but the impasse remains open
        # and SelfModel is not credited yet. Acceptance belongs to the next ZN
        # Thought, not to the external worker's success flag.
        state.data["cognitive_increment"] = increment.to_dict()
        state.data["external_cognition_result"] = {
            "model_invocations": invocations,
            "reason": reason,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.stage = "cognition_integration"
        state.next_action = "judge and integrate borrowed cognition"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _cognition_integration_step(
        self,
        event: AgentEvent,
        state: WorkingState,
        *,
        readiness: TaskReadiness,
        thought=None,
    ) -> ResidentRunResult | None:
        raw = state.data.get("cognitive_increment")
        if not isinstance(raw, dict):
            state.stage = "native_deliberation"
            state.next_action = "recover missing cognitive increment"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        increment = CognitiveIncrement.from_dict(raw)
        if thought is not None:
            known = (
                f"I received a bounded cognitive increment from {increment.source} "
                f"with confidence={increment.confidence:.2f}"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; borrowed cognition has returned to my own state for integration"
            )
            self._persist_enriched_thought(thought)

        external = state.data.get("external_cognition_result")
        external_data = external if isinstance(external, dict) else {}
        invocations = max(0, int(external_data.get("model_invocations") or 0))

        integration = state.data.get("cognition_integration")
        integration_data = integration if isinstance(integration, dict) else {}
        if not integration_data.get("accepted"):
            # This is the point where ZN accepts the borrowed increment. Only
            # now do we close the impasse, stage learning evidence, and update
            # ZN's knowledge profile.
            accepted_run = ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MODEL,
                success=True,
                response=increment.content,
                model_invocations=invocations,
                reason=f"accepted cognitive increment from {increment.source}",
            )
            self.life.resolve_impasse(
                event,
                accepted_run,
                resolution_source=increment.source,
            )
            self.investigator.resolve_from_external(
                event.event_id,
                increment.content or "external cognition supplied the missing increment",
            )
            domains = self.kernel.self_model.integrate_external_learning(
                event.task,
                self._required_capabilities(event),
                quality=increment.quality,
                confidence=increment.confidence,
            )
            integration_data = {
                "increment_id": increment.increment_id,
                "accepted": True,
                "source": increment.source,
                "quality": increment.quality,
                "confidence": increment.confidence,
            }
            state.data["cognition_integration"] = integration_data
            state.data["integrated_learning_domains"] = list(domains)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)

        # Re-check whether the accepted increment accompanies a concrete native
        # body intent. The action stays ZN-owned; external text is never passed
        # straight through as a shell/tool instruction. Borrowed text is not new
        # reality evidence, so it cannot by itself unlock a failed movement.
        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        intent = derive_native_action_intent(event, facts=facts)
        if intent is not None:
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                state.next_action = f"move body after cognition: {intent.kind}"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None

            failure = (
                "borrowed cognition did not change current reality enough to justify "
                "repeating the previously failed body action"
            )
            state.data["local_failure"] = failure
            state.stage = "failed"
            state.next_action = None
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return ResidentRunResult(
                event=event,
                execution_path=ExecutionPath.MODEL,
                success=False,
                response=increment.content,
                model_invocations=invocations,
                reason=failure,
            )

        state.stage = "complete"
        state.next_action = None
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=True,
            response=increment.content,
            model_invocations=invocations,
            reason=(
                f"ZN accepted and integrated a bounded cognitive increment from "
                f"{increment.source} before completing the event"
            ),
        )

    def _enrich_thought_with_working_stage(self, thought, event: AgentEvent) -> None:
        super()._enrich_thought_with_working_stage(thought, event)
        state = self.store.get_working_state()
        if state.current_event_id != event.event_id:
            return

        if state.stage == "native_action":
            raw = state.data.get("native_action_intent")
            if not isinstance(raw, dict):
                return
            intent = NativeActionIntent.from_dict(raw)
            action = f"perform body action: {intent.kind}"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "body_action"
            thought.action_target = event.event_id
            thought.reason = "native cognition has selected a concrete movement of my body"
            return

        if state.stage == "native_verification":
            action = "verify the previous body movement against current reality"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "verify_action"
            thought.action_target = event.event_id
            thought.reason = (
                "a successful body call is only evidence; the requested postcondition must "
                "be observed before I can call the task complete"
            )
            return

        if state.stage == "cognition_integration":
            raw = state.data.get("cognitive_increment")
            increment = raw if isinstance(raw, dict) else {}
            source = str(increment.get("source") or "external cognition")
            action = "judge and integrate borrowed cognition into my own state"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "integrate_cognition"
            thought.action_target = event.event_id
            thought.reason = f"a bounded increment from {source} has returned for my judgment"

    def _action_blocked_by_current_evidence(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
    ) -> bool:
        evidence_fingerprint = self._evidence_fingerprint(event.event_id)
        signature_hash = self._signature_hash(intent)
        records = self._failure_records(state)
        if any(
            str(item.get("signature_hash") or "") == signature_hash
            and str(item.get("evidence_fingerprint") or "") == evidence_fingerprint
            for item in records
        ):
            return True

        # Upgrade an interrupted resident that still has the previous one-slot
        # anti-replay field. Once the evidence ledger exists, the old field is
        # ignored and will be removed when a new action is admitted.
        legacy = str(state.data.get("native_action_failure_signature") or "")
        if not records and legacy and legacy == self._intent_signature(intent):
            self._record_failed_action(
                event,
                state,
                intent,
                source="legacy",
                failure=str(state.data.get("local_failure") or "prior body action failed"),
                evidence_fingerprint=evidence_fingerprint,
            )
            return True
        return False

    def _record_failed_action(
        self,
        event: AgentEvent,
        state: WorkingState,
        intent: NativeActionIntent,
        *,
        source: str,
        failure: str,
        evidence_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = evidence_fingerprint or self._evidence_fingerprint(event.event_id)
        signature_hash = self._signature_hash(intent)
        record = {
            "signature_hash": signature_hash,
            "kind": intent.kind,
            "evidence_fingerprint": fingerprint,
            "source": str(source or "body")[:80],
            "failure": str(failure or "body action failed")[:1000],
            "at": utc_now(),
        }
        records = [
            item
            for item in self._failure_records(state)
            if not (
                str(item.get("signature_hash") or "") == signature_hash
                and str(item.get("evidence_fingerprint") or "") == fingerprint
            )
        ]
        records.append(record)
        state.data[self._FAILED_ACTION_RECORDS_KEY] = records[
            -self._MAX_FAILED_ACTION_RECORDS :
        ]
        return record

    def _evidence_fingerprint(self, event_id: str) -> str:
        investigation = self.investigator.current(event_id)
        facts = investigation.facts if investigation is not None else {}
        stable = self._stable_fact_value(facts)
        encoded = json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _stable_fact_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._stable_fact_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if not cls._volatile_fact_key(str(key))
            }
        if isinstance(value, (list, tuple)):
            return [cls._stable_fact_value(item) for item in value]
        if isinstance(value, set):
            normalized = [cls._stable_fact_value(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @classmethod
    def _volatile_fact_key(cls, key: str) -> bool:
        normalized = str(key or "").strip().lower()
        return normalized in cls._VOLATILE_FACT_KEYS or normalized.endswith("_at")

    @classmethod
    def _failure_records(cls, state: WorkingState) -> list[dict[str, Any]]:
        raw = state.data.get(cls._FAILED_ACTION_RECORDS_KEY)
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)][
            -cls._MAX_FAILED_ACTION_RECORDS :
        ]

    @classmethod
    def _failure_summary(cls, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "signature": str(raw.get("signature_hash") or "")[:16],
            "kind": str(raw.get("kind") or "unknown"),
            "evidence_version": str(raw.get("evidence_fingerprint") or "")[:16],
            "source": str(raw.get("source") or "unknown")[:80],
            "failure": str(raw.get("failure") or "")[:500] or None,
        }

    @classmethod
    def _signature_hash(cls, intent: NativeActionIntent) -> str:
        raw = cls._intent_signature(intent).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _intent_signature(intent: NativeActionIntent) -> str:
        return json.dumps(
            {"kind": intent.kind, "args": intent.args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
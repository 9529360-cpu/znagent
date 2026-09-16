from __future__ import annotations

"""Narrow product ingress for Research and Local Office representative Work."""

from .action_authority import install_worker_authority_gate
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
from .local_office_behavior import install_local_office_behavior
from .local_service_recovery_behavior import install_local_service_recovery_behavior
from .long_running_terminal_behavior import install_long_running_terminal_behavior
from .research_information_resident import ResearchInformationResidentRuntime
from .user_browser_extension_relay import UserBrowserExtensionRelayError
from .user_browser_multi_record_result import (
    parse_verified_record_excerpts,
    requested_multi_record_count,
)
from .windows_companion_body import WindowsCompanionAwareBody
from .windows_companion_work_context import bind_windows_companion_work_context


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep one product Body and one DeviceCapabilityGraph. The companion-aware
        # layer extends the existing application/browser/file/pointer/keyboard/UIA
        # stack; it does not introduce another execution or machine-truth surface.
        self.body = WindowsCompanionAwareBody(
            resident=self,
            device_capabilities=self.device_capabilities,
        )
        installer = getattr(self, "_install_body_dispatch_health_observer", None)
        if callable(installer):
            installer()
        install_worker_authority_gate(self.body, resident=self)
        install_current_app_text_cleanup_behavior(self)
        install_current_app_text_cleanup_completion(self)
        install_local_office_behavior(self)
        install_long_running_terminal_behavior(self)
        install_local_service_recovery_behavior(self)
        install_browser_spreadsheet_behavior(self)
        install_document_research_completion_behavior(self)
        install_document_research_completion_safety(self)

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

    def _orient_step(self, event, state, *, readiness, thought=None):
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

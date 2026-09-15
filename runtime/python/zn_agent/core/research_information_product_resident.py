from __future__ import annotations

"""Narrow product ingress for Research and Local Office representative Work."""

from .action_authority import install_worker_authority_gate
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
from .windows_companion_body import WindowsCompanionAwareBody
from .windows_companion_current_app_guard import (
    install_windows_companion_current_app_guard,
)
from .windows_companion_foreground_desktop_guard import (
    install_windows_companion_foreground_desktop_guard,
)
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
        # Install after the E2E-13 behavior so this wrapper is the outermost
        # orientation gate: stale start-context is rejected before _begin() can
        # ground whatever application happens to be foreground later.
        install_windows_companion_current_app_guard(self)
        # Natural/model-understood foreground-desktop goals may not become typed
        # until after orientation. Guard their shared investigation and native-
        # action seams until submit is durably dispatched, so recovery cannot
        # silently transfer the user's "current app" reference to a later window.
        # The existing desktop-goal runtime still owns every fresh movement and
        # post-effect verification; historical context never grants authority.
        install_windows_companion_foreground_desktop_guard(self)
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

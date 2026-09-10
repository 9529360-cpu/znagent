from __future__ import annotations

"""Narrow product ingress for Research and Local Office representative Work."""

from .local_office_behavior import install_local_office_behavior
from .research_information_resident import ResearchInformationResidentRuntime


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

_OFFICE_SOURCE_KEYS = ("downloads_path", "source_workspace_path")


class ProductResearchInformationResidentRuntime(ResearchInformationResidentRuntime):
    """Final product Resident with narrow Research and local Office admission."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        install_local_office_behavior(self)

        # RecoveryBoundedWorkLedger keeps the exact destination authority on the
        # durable Work thread.  Office ingress also carries an explicitly
        # authorized source workspace, but does not duplicate the attached
        # destination path into every event payload.  Normalize that durable
        # Work evidence at the product boundary before the Office behavior
        # evaluates its authority preconditions.
        office_advance = self._advance_event_step

        def advance_with_work_workspace(event, state, *, readiness, learning_evidence, thought=None):
            payload = getattr(event, "payload", {}) or {}
            has_office_source = any(str(payload.get(key) or "").strip() for key in _OFFICE_SOURCE_KEYS)
            if has_office_source and not str(payload.get("workspace_path") or "").strip():
                thread_id = str(payload.get("work_thread_id") or "").strip()
                thread = self.work_ledger.get_thread(thread_id) if thread_id else None
                association = self.work_ledger.workspace_for(thread) if thread is not None else None
                if association is not None:
                    payload["workspace_path"] = association.path
                    event.payload = payload
            return office_advance(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        self._advance_event_step = advance_with_work_workspace

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

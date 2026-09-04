from __future__ import annotations

"""Recoverable cognition and bounded managed-browser research for Broad Work.

CapabilityRecoveryResidentRuntime checkpoints a successful external model call
as ``external_completion`` before accounting. That is correct for an ordinary
model-answer event, while criterion-bound Broad Work needs the response as a
non-terminal proposed next step. This adapter preserves that mature recovery
boundary, promotes the result into the existing CognitiveIncrement stage, and
adds one recoverable research movement through ZN's existing managed Chromium.
"""

import hashlib
import json
from urllib.parse import urlsplit

from .broad_goal_coding_resident import BroadGoalCodingResidentRuntime
from .browser import BrowserPermissionContext
from .cognition import CognitiveIncrement
from .models import utc_now
from .research_managed_browser import ResearchSemanticPlaywrightManagedBrowser
from .steerable_work import WorkItem
from .work import title_for_work_task


class BroadGoalRecoverableCodingResidentRuntime(BroadGoalCodingResidentRuntime):
    """Keep model proposals non-terminal and make browser research real evidence."""

    _BROAD_RESEARCH_KEY = "broad_goal_research_step"
    _BROAD_RESEARCH_HISTORY_KEY = "broad_goal_research_history"
    _MAX_RESEARCH_EVIDENCE_TEXT = 8192

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        if state.stage == "external_completion" and self._criterion_bound_root(event) is not None:
            run = self._resume_external_completion(event, state)
            if not run.success:
                return run
            return self._promote_external_completion(event, state, run)
        if state.stage == "broad_goal_research":
            return self._broad_goal_research_step(event, state)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _external_cognition_step(self, event, state):
        root = self._criterion_bound_root(event)
        run = super()._external_cognition_step(event, state)
        if root is None or run is None or not run.success:
            return run
        return self._promote_external_completion(event, state, run)

    def _promote_external_completion(self, event, state, run):
        raw_completion = state.data.get(self._EXTERNAL_COMPLETION_KEY)
        completion = raw_completion if isinstance(raw_completion, dict) else {}
        kernel_result = run.kernel_result
        if kernel_result is None:
            goal_id = str(completion.get("goal_id") or state.current_goal_id or "").strip()
            if goal_id:
                kernel_result = self.kernel.load_goal_result(goal_id)

        quality = 0.5
        confidence = 0.5
        route_id = str(completion.get("route_id") or "external").strip() or "external"
        if kernel_result is not None:
            quality = float(kernel_result.assessment.quality)
            confidence = float(kernel_result.assessment.confidence)
            route_id = str(kernel_result.route.route_id or route_id).strip() or route_id

        raw_request = state.data.get("cognition_request")
        request = raw_request if isinstance(raw_request, dict) else {}
        impasse_id = str(request.get("impasse_id") or state.data.get("impasse_id") or "").strip()
        increment = CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id=impasse_id or None,
            source=f"external:{route_id}",
            question=str(request.get("question") or event.task),
            content=str(run.response or ""),
            quality=quality,
            confidence=confidence,
        )

        # The recoverable external-completion layer already applied provider
        # accounting, impasse resolution and learning exactly once.
        state.data["cognitive_increment"] = increment.to_dict()
        state.data["external_cognition_result"] = {
            "model_invocations": int(run.model_invocations),
            "reason": str(run.reason or ""),
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.data["cognition_integration"] = {
            "increment_id": increment.increment_id,
            "accepted": True,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
            "accepted_via": "recoverable_external_completion",
        }
        state.data.pop(self._EXTERNAL_COMPLETION_KEY, None)
        state.data.pop(self._EXTERNAL_COMPLETION_ACCOUNTING_KEY, None)
        state.stage = "cognition_integration"
        state.next_action = "judge and execute one bounded Broad Work proposal"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _accept_borrowed_increment(self, event, state, increment: CognitiveIncrement) -> None:
        integration = state.data.get("cognition_integration")
        if (
            isinstance(integration, dict)
            and integration.get("accepted") is True
            and str(integration.get("increment_id") or "") == increment.increment_id
        ):
            return
        super()._accept_borrowed_increment(event, state, increment)

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(
            event,
            impasse,
            required,
            deliberation,
        )
        root = self._criterion_bound_root(event)
        if root is None:
            return request

        state = self.store.get_working_state()
        raw_history = state.data.get(self._BROAD_RESEARCH_HISTORY_KEY)
        history = raw_history if isinstance(raw_history, list) else []
        research = []
        remaining = 7000
        for item in reversed(history[-4:]):
            if not isinstance(item, dict) or remaining <= 0:
                continue
            text = str(item.get("text") or "")[: min(3500, remaining)]
            remaining -= len(text)
            research.append(
                {
                    "url": str(item.get("url") or "")[:2048],
                    "title": str(item.get("title") or "")[:500],
                    "captured_at": str(item.get("captured_at") or "")[:100],
                    "text": text,
                }
            )
        research.reverse()
        request.question += (
            " A third allowed V1 form is real managed-browser research: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"research_page",'
            '"url":"https://..."},"acceptance":{"kind":"page_read",'
            '"url":"https://..."}}}. '
            "Use research_page when current external facts are needed. Action and acceptance URLs "
            "must match exactly. Do not invent page contents: ZN will navigate and read the page. "
            "Prefer authoritative primary sources. "
            "Fresh managed-browser research evidence already collected: "
            f"{json.dumps(research, ensure_ascii=False)}."
        )
        request.context = {
            **dict(request.context or {}),
            "rolling_step_contract": "research-page-or-write-file-or-run-python-v1",
            "research_evidence_count": len(history),
        }
        return request

    def _cognition_integration_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        increment = CognitiveIncrement.from_dict(raw)
        proposal = self._parse_research_page_step(root, increment.content)
        if proposal is None:
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        self._accept_borrowed_increment(event, state, increment)
        identity = hashlib.sha256(
            f"{event.event_id}\0{increment.increment_id}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        child = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[f'page_read: {proposal["url"]}'],
        )
        self.work_ledger._save_item(child)
        state.data[self._BROAD_RESEARCH_KEY] = {
            "work_item_id": child.work_item_id,
            "root_work_item_id": root.work_item_id,
            "work_thread_id": root.work_thread_id,
            "plan_version": root.plan_version,
            "objective": proposal["objective"],
            "url": proposal["url"],
            "increment_id": increment.increment_id,
        }
        state.stage = "broad_goal_research"
        state.next_action = "navigate managed Chromium and capture fresh page evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _broad_goal_research_step(self, event, state):
        raw_step = state.data.get(self._BROAD_RESEARCH_KEY)
        if not isinstance(raw_step, dict):
            state.stage = "native_deliberation"
            state.next_action = "recover missing Broad Work research proposal"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        thread_id = str(raw_step.get("work_thread_id") or "").strip()
        child_id = str(raw_step.get("work_item_id") or "").strip()
        plan_version = int(raw_step.get("plan_version") or 0)
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(thread_id)
                if item.work_item_id == child_id
            ),
            None,
        )
        if child is None:
            raise RuntimeError("Broad Work research checkpoint lost its durable child WorkItem")
        current_version = self.work_ledger.plan_version(thread_id)
        if plan_version != current_version or child.plan_version != current_version:
            child.status = "superseded"
            child.blocker = "research proposal belongs to a stale Work plan"
            child.updated_at = utc_now()
            self.work_ledger._save_item(child)
            return self._roll_forward_research_state(event, state)
        if child.status == "completed":
            return self._roll_forward_research_state(event, state)

        browser = self.managed_browser
        if not isinstance(browser, ResearchSemanticPlaywrightManagedBrowser):
            return self._fail_research_step(
                event,
                state,
                child,
                "readable managed Chromium adapter is unavailable",
            )

        url = str(raw_step.get("url") or "").strip()
        session = None
        try:
            permission = BrowserPermissionContext(
                allow_navigation=True,
                allow_private_network=bool(event.payload.get("allow_private_research", False)),
                allowed_origins=(self._origin_url(url),),
            )
            session = browser.open_session(permission=permission, headless=True)
            page = self._navigate_and_read(browser, session.session_id, url, permission)
        except Exception as exc:
            return self._fail_research_step(
                event,
                state,
                child,
                f"managed browser research failed: {type(exc).__name__}: {exc}",
            )
        finally:
            if session is not None:
                try:
                    browser.close_session(session.session_id)
                except Exception:
                    pass

        text = str(page.get("text") or "")[: self._MAX_RESEARCH_EVIDENCE_TEXT]
        observed_url = str(page.get("url") or "").strip()
        captured_at = str(page.get("captured_at") or "").strip()
        if not text.strip() or not observed_url or not captured_at:
            return self._fail_research_step(
                event,
                state,
                child,
                "managed browser returned incomplete page evidence",
            )
        evidence = {
            "url": observed_url,
            "title": str(page.get("title") or "")[:500],
            "captured_at": captured_at,
            "text": text,
            "links": [
                {
                    "href": str(item.get("href") or "")[:2048],
                    "text": str(item.get("text") or "")[:240],
                }
                for item in (page.get("links") or [])[:12]
                if isinstance(item, dict)
            ],
            "provider": str(page.get("provider") or "")[:200],
            "profile_scope": str(page.get("profile_scope") or "")[:200],
        }
        child.status = "completed"
        child.result = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        child.blocker = None
        child.completed_at = utc_now()
        child.updated_at = child.completed_at
        self.work_ledger._save_item(child)

        raw_history = state.data.get(self._BROAD_RESEARCH_HISTORY_KEY)
        history = list(raw_history) if isinstance(raw_history, list) else []
        history.append(evidence)
        state.data[self._BROAD_RESEARCH_HISTORY_KEY] = history[-6:]
        state.data.pop("local_failure", None)
        return self._roll_forward_research_state(event, state)

    def _fail_research_step(self, event, state, child: WorkItem, failure: str):
        child.status = "blocked"
        child.blocker = failure[:6000]
        child.result = child.blocker
        child.updated_at = utc_now()
        self.work_ledger._save_item(child)
        state.data["local_failure"] = failure[:6000]
        investigation = self.investigator.current(event.event_id)
        if investigation is not None and investigation.status == "resolved_external":
            evidence = list(investigation.evidence)
            failure_evidence = f"new managed-browser failure after external cognition: {failure[:1000]}"
            if failure_evidence not in evidence:
                evidence.append(failure_evidence)
            investigation.status = "open"
            investigation.resolution = None
            investigation.unresolved = failure[:1000]
            investigation.next_probe = None
            investigation.updated_at = utc_now()
            investigation.evidence = tuple(evidence[-64:])
            self.investigator._save(investigation)
        state.data.pop(self._BROAD_RESEARCH_KEY, None)
        state.stage = "native_investigation"
        state.next_action = "investigate the real managed-browser failure before choosing another step"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _roll_forward_research_state(self, event, state):
        state.data.pop(self._BROAD_RESEARCH_KEY, None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_deliberation"
        state.next_action = "choose the next bounded Work step from fresh research evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _parse_research_page_step(self, root: WorkItem, content: str):
        try:
            raw = json.loads(str(content or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not objective or len(objective) > 600:
            return None
        if not isinstance(action, dict) or not isinstance(acceptance, dict):
            return None
        if str(action.get("kind") or "").strip() != "research_page":
            return None
        if str(acceptance.get("kind") or "").strip() != "page_read":
            return None
        url = str(action.get("url") or "").strip()
        if url != str(acceptance.get("url") or "").strip():
            return None
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return None
        return {"objective": objective, "url": url}

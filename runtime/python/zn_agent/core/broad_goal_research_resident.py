from __future__ import annotations

"""Bounded managed-browser research for criterion-bound Broad Work.

This layer does not own a second planner, browser, work store, or model router.
It only turns one validated model proposal into a durable child WorkItem and
executes that movement through ZN's existing readable managed Chromium adapter.
"""

import hashlib
import json
from urllib.parse import urlsplit

from .broad_goal_recoverable_resident import BroadGoalRecoverableCodingResidentRuntime
from .browser import BrowserPermissionContext
from .cognition import CognitiveIncrement
from .models import utc_now
from .research_managed_browser import ResearchSemanticPlaywrightManagedBrowser
from .steerable_work import WorkItem
from .work import title_for_work_task


class BroadGoalResearchResidentRuntime(BroadGoalRecoverableCodingResidentRuntime):
    """Add one real research movement while keeping the existing Resident lifecycle."""

    _BROAD_RESEARCH_KEY = "broad_goal_research_step"
    _BROAD_RESEARCH_HISTORY_KEY = "broad_goal_research_history"
    _MAX_RESEARCH_EVIDENCE_TEXT = 8192

    def _criterion_bound_root(self, event) -> WorkItem | None:
        root = super()._criterion_bound_root(event)
        if root is not None:
            return root
        recover = getattr(self.work_ledger, "recover_steered_root_acceptance", None)
        if callable(recover):
            recovered = recover(event)
            if recovered is not None:
                return super()._criterion_bound_root(event)
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
        if state.stage == "broad_goal_research":
            return self._broad_goal_research_step(event, state)
        return super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

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
        research: list[dict[str, str]] = []
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

        historical_items = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.status == "completed" and item.plan_version < root.plan_version
        ][-8:]
        historical = [
            {
                "plan_version": item.plan_version,
                "objective": item.objective[:300],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:900],
            }
            for item in historical_items
        ]
        steering = event.payload.get("work_steering")
        previous_root_context = None
        if isinstance(steering, dict) and str(steering.get("mode") or "") == "active_steer":
            previous_event_id = str(steering.get("previous_event_id") or "").strip()
            previous = self.work_ledger.work_item_for_event(previous_event_id)
            if (
                previous is not None
                and previous.work_thread_id == root.work_thread_id
                and previous.parent_work_item_id is None
                and previous.plan_version < root.plan_version
            ):
                previous_root_context = {
                    "plan_version": previous.plan_version,
                    "objective": previous.objective[:1200],
                }

        request.question += (
            " A third allowed V1 form is real managed-browser research: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"research_page",'
            '"url":"https://..."},"acceptance":{"kind":"page_read",'
            '"url":"https://..."}}}. '
            "Use research_page when current external facts are needed. Action and acceptance URLs "
            "must match exactly. Do not invent page contents: ZN will navigate and read the page. "
            "Prefer authoritative primary sources. A URL that already has completed page_read evidence in "
            "the current plan is no longer a useful next step; ZN will reject an exact repeat instead of "
            "replaying the browser action. "
            "Fresh managed-browser research evidence already collected: "
            f"{json.dumps(research, ensure_ascii=False)}. "
            "The immediately superseded Root objective is historical task context only; preserve its "
            "product subject while obeying the user's current steering, and never treat the old objective "
            "as current-plan acceptance evidence: "
            f"{json.dumps(previous_root_context, ensure_ascii=False)}. "
            "Historical completed evidence from superseded plans is context only and NEVER counts as "
            "acceptance for the current plan; use it to avoid repeating already-observed facts or workspace "
            "work, then freshly verify anything that must advance the current plan: "
            f"{json.dumps(historical, ensure_ascii=False)}."
        )
        request.context = {
            **dict(request.context or {}),
            "rolling_step_contract": "research-page-or-write-file-or-run-python-v1",
            "research_evidence_count": len(history),
            "historical_prior_plan_evidence_count": len(historical),
            "previous_root_context": previous_root_context,
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

        if self._has_completed_current_plan_research(root, proposal["url"]):
            return self._reject_no_progress_research(event, state, root, increment, proposal)

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

    def _has_completed_current_plan_research(self, root: WorkItem, url: str) -> bool:
        criterion = f"page_read: {url}"
        return any(
            item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
            and criterion in item.acceptance_criteria
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
        )

    def _next_progress_action_kind(self, root: WorkItem) -> str:
        current = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
        ]
        if not any(
            any(criterion.startswith("text_equals:") for criterion in item.acceptance_criteria)
            for item in current
        ):
            return "write_file"
        if not any(
            any(criterion.startswith("command_exit:") for criterion in item.acceptance_criteria)
            for item in current
        ):
            return "run_python"
        return "verify_python"

    def _reject_no_progress_research(
        self,
        event,
        state,
        root: WorkItem,
        increment: CognitiveIncrement,
        proposal: dict[str, str],
    ):
        target_kind = self._next_progress_action_kind(root)
        url = proposal["url"]
        failure = (
            "ZN rejected a no-progress Broad Work step: research_page URL "
            f"{url!r} already has completed current-plan page_read evidence; replaying the same "
            f"browser action cannot advance the Root. Switch to {target_kind}."
        )
        self._accept_borrowed_increment(event, state, increment)
        repair_key = str(getattr(self, "_PROTOCOL_REPAIR_KEY", "broad_goal_protocol_repair"))
        max_chars = int(getattr(self, "_MAX_REJECTED_PROTOCOL_CHARS", 12_000))
        state.data[repair_key] = {
            "error": failure,
            "kind": target_kind,
            "content": str(increment.content or "")[:max_chars],
            "reason": "no_progress_repeat",
        }
        state.data["local_failure"] = failure
        investigation = self.investigator.current(event.event_id)
        if investigation is not None and investigation.status == "resolved_external":
            evidence = list(investigation.evidence)
            if failure not in evidence:
                evidence.append(failure)
            investigation.status = "open"
            investigation.resolution = None
            investigation.unresolved = failure
            investigation.next_probe = None
            investigation.updated_at = utc_now()
            investigation.evidence = tuple(evidence[-64:])
            self.investigator._save(investigation)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_investigation"
        state.next_action = f"switch from repeated research to one progress-producing {target_kind} step"
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

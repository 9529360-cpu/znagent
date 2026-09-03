from __future__ import annotations

"""Resident closure for authorized-page references researched in managed Chromium."""

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from .action import NativeActionIntent
from .browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserPermissionContext
from .goal_resident import ResidentGoalRuntime
from .research_managed_browser import ResearchSemanticPlaywrightManagedBrowser
from .user_browser_extension_relay import UserBrowserExtensionRelayError
from .user_browser_extension_resident import UserBrowserExtensionResidentRuntime


_RELEASE_CODE_RE = re.compile(
    r"(?:release\s+code|发布(?:版本)?代码|发行(?:版本)?代码)\s*[:：#-]?\s*([A-Za-z0-9][A-Za-z0-9._-]{2,63})",
    re.IGNORECASE,
)
_REFERENCE_CUES = ("reference", "release", "registry", "note", "参考", "发布", "发行")
_DETAIL_CUES = ("detail", "release", "record", "version", "详情", "明细", "发布", "版本")


class UserBrowserManagedResearchResidentRuntime(UserBrowserExtensionResidentRuntime):
    """Research A-page references, then reuse the guarded USER form-submit path."""

    _MANAGED_RESEARCH_STATE_KEY = "resident_user_browser_managed_reference_research"
    _USER_BROWSER_TASK_CONTEXT_KEY = "resident_user_browser_task_context"
    _USER_BROWSER_TASK_CONTEXT_EVENT_KEY = "_resident_user_browser_task_context"
    _USER_BROWSER_CONTEXT_ACTIONS = frozenset(
        {
            "browser_type_named_text",
            "browser_click_named_button_to_url",
            "browser_fill_named_text_and_click_named_button_to_url",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.managed_browser = ResearchSemanticPlaywrightManagedBrowser()

    @classmethod
    def _natural_managed_reference_search(cls, event) -> bool:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return False
        task = " ".join(str(event.task or "").strip().split())
        if not task or len(task) > 1200:
            return False
        lowered = task.lower()
        has_reference = "reference" in lowered or "参考" in task
        has_code = "release code" in lowered or ("code" in lowered and "release" in lowered) or "代码" in task
        has_return = any(cue in lowered for cue in ("come back", "return", "back on this page")) or "回来" in task or "回到" in task
        has_search = "search" in lowered or "find" in lowered or "搜索" in task or "查找" in task
        return bool(has_reference and has_code and has_return and has_search)

    def _orient_step(self, event, state, *, readiness, thought=None):
        # This task is already fully bounded by Resident-owned language rules and
        # is intentionally supported with model_policy=never. Do not let the more
        # generic foreground-browser cognition router consume it first merely
        # because the user says "this page". Enter the existing Resident goal
        # lifecycle directly; fresh browser evidence still owns every world fact.
        if self._natural_managed_reference_search(event):
            return ResidentGoalRuntime._orient_step(
                self,
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        return super()._orient_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        if payload.get("required_capabilities") is None and cls._natural_managed_reference_search(event):
            return ("browser",)
        return super()._required_capabilities(event)

    def _semantic_lookup_investigation(self, event, state, *, readiness, thought=None):
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"authorized browser task context was lost before fresh Sense: {type(exc).__name__}: {exc}",
            )
        return super()._semantic_lookup_investigation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _semantic_lookup_deliberation(self, event, state, *, readiness, thought=None):
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"authorized browser task context was lost before action: {type(exc).__name__}: {exc}",
            )
        return super()._semantic_lookup_deliberation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _begin_native_action_cycle(self, event, state, intent):
        context = state.data.get(self._USER_BROWSER_TASK_CONTEXT_KEY)
        if (
            isinstance(context, dict)
            and str(intent.kind or "").strip().lower() in self._USER_BROWSER_CONTEXT_ACTIONS
        ):
            args = dict(intent.args or {})
            args["authorized_tab_id"] = int(context["tab_id"])
            args["authorization_attached_at"] = str(context["attached_at"])
            intent = NativeActionIntent(
                intent_id=intent.intent_id,
                event_id=intent.event_id,
                kind=intent.kind,
                args=args,
                expected_outcome=(
                    dict(intent.expected_outcome)
                    if isinstance(intent.expected_outcome, dict)
                    else intent.expected_outcome
                ),
                reason=intent.reason,
                source=intent.source,
                created_at=intent.created_at,
            )
        return super()._begin_native_action_cycle(event, state, intent)

    def _ensure_user_browser_task_context(self, event, state) -> dict[str, Any]:
        raw = state.data.get(self._USER_BROWSER_TASK_CONTEXT_KEY)
        if not isinstance(raw, dict):
            raw = (event.payload or {}).get(self._USER_BROWSER_TASK_CONTEXT_EVENT_KEY)
        current = self.user_browser_extension.authorized_tab()
        if current is None:
            raise UserBrowserExtensionRelayError(
                "the browser tab explicitly authorized for this task is no longer available"
            )

        if isinstance(raw, dict):
            try:
                expected_tab_id = int(raw.get("tab_id"))
            except (TypeError, ValueError) as exc:
                raise UserBrowserExtensionRelayError(
                    "stored browser task context has invalid tab identity"
                ) from exc
            expected_attached_at = str(raw.get("attached_at") or "").strip()
            expected_origin = str(raw.get("origin") or "").strip()
            if (
                expected_tab_id != current.tab_id
                or not expected_attached_at
                or expected_attached_at != current.attached_at
            ):
                raise UserBrowserExtensionRelayError(
                    "current browser authorization is not the authorization that owns this Work"
                )
            fresh = self.probe_user_browser_extension_tab()
            after = self.user_browser_extension.authorized_tab()
            if (
                after is None
                or after.tab_id != expected_tab_id
                or after.attached_at != expected_attached_at
                or int(fresh.get("tab_id") or 0) != expected_tab_id
            ):
                raise UserBrowserExtensionRelayError(
                    "browser task authorization changed while fresh context evidence was being observed"
                )
            fresh_origin = self._origin_url(str(fresh.get("url") or ""))
            if expected_origin and fresh_origin != expected_origin:
                raise UserBrowserExtensionRelayError(
                    "authorized browser task context left its original origin"
                )
            context = {
                "tab_id": expected_tab_id,
                "attached_at": expected_attached_at,
                "origin": expected_origin or fresh_origin,
                "initial_url": str(raw.get("initial_url") or fresh.get("url") or ""),
            }
        else:
            before_tab_id = current.tab_id
            before_attached_at = current.attached_at
            fresh = self.probe_user_browser_extension_tab()
            after = self.user_browser_extension.authorized_tab()
            if (
                after is None
                or after.tab_id != before_tab_id
                or after.attached_at != before_attached_at
                or int(fresh.get("tab_id") or 0) != before_tab_id
            ):
                raise UserBrowserExtensionRelayError(
                    "browser authorization changed while the Work was binding its task context"
                )
            context = {
                "tab_id": before_tab_id,
                "attached_at": before_attached_at,
                "origin": self._origin_url(str(fresh.get("url") or "")),
                "initial_url": str(fresh.get("url") or ""),
            }

        state.data[self._USER_BROWSER_TASK_CONTEXT_KEY] = dict(context)
        event.payload = dict(event.payload or {})
        event.payload[self._USER_BROWSER_TASK_CONTEXT_EVENT_KEY] = dict(context)
        self.store._save_event(event)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return context

    def _investigation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        if not self._natural_managed_reference_search(event):
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"reference research lost its explicitly authorized browser task context: {type(exc).__name__}: {exc}",
            )
        existing = state.data.get(self._MANAGED_RESEARCH_STATE_KEY)
        if isinstance(existing, dict) and existing.get("release_code") and existing.get("search"):
            state.stage = "native_deliberation"
            state.next_action = "submit the researched release code on the freshly re-sensed authorized page"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        try:
            initial = self._discover_authorized_reference_context()
            references = self._rank_reference_candidates(initial.get("references"))
            if len(references) < 2:
                raise UserBrowserExtensionRelayError("the authorized page did not expose at least two bounded reference candidates")
            research = self._research_managed_references(references)
            code = str(research["release_code"])
            self._ensure_user_browser_task_context(event, state)
            self._adopt_authorized_extension_browser()
            fresh_search = self._discover_unique_search_form(code)
            fresh_tab = self.probe_user_browser_extension_tab()
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            if self.managed_browser is self._extension_user_browser:
                try:
                    self._restore_browser_after_extension()
                except Exception:
                    pass
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"ZN could not complete bounded managed-browser reference research: {type(exc).__name__}: {exc}",
            )

        initial_search = initial.get("search_form") if isinstance(initial.get("search_form"), dict) else {}
        initial_target = str(initial_search.get("textbox_target_id") or "")
        fresh_target = str(fresh_search.get("textbox_target_id") or "")
        initial_title = str(initial.get("title") or "")
        fresh_title = str(fresh_tab.get("title") or "")
        state.data[self._MANAGED_RESEARCH_STATE_KEY] = {
            "release_code": code,
            "sources": research["sources"],
            "initial_authorized_page": {
                "url": str(initial.get("url") or ""),
                "title": initial_title,
                "textbox_target_id": initial_target,
                "observed_at": str(initial.get("observed_at") or ""),
            },
            "fresh_authorized_page": {
                "url": str(fresh_tab.get("url") or ""),
                "title": fresh_title,
                "textbox_target_id": fresh_target,
                "observed_at": str(fresh_tab.get("observed_at") or ""),
            },
            "authorized_page_changed_during_research": bool(
                (initial_target and fresh_target and initial_target != fresh_target) or initial_title != fresh_title
            ),
            "search": fresh_search,
        }
        state.data.pop("local_failure", None)
        if thought is not None:
            known = "two independently observed managed-browser sources agreed on one release code before returning to the authorized user page"
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; ZN preserved the authorized USER tab, investigated references in an ephemeral managed browser, "
                "then freshly re-sensed the exact authorized tab before forming the existing guarded submit movement"
            )
            self._persist_enriched_thought(thought)
        state.stage = "native_deliberation"
        state.next_action = "submit the researched release code through the existing guarded USER browser Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _deliberation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        if not self._natural_managed_reference_search(event):
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"the explicitly authorized browser task context is no longer available: {type(exc).__name__}: {exc}",
            )
        evidence = state.data.get(self._MANAGED_RESEARCH_STATE_KEY)
        if not isinstance(evidence, dict):
            state.stage = "native_investigation"
            state.next_action = "inspect the authorized page references and investigate them in managed Chromium"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        code = str(evidence.get("release_code") or "")
        search = evidence.get("search")
        if not code or not isinstance(search, dict):
            state.stage = "native_investigation"
            state.next_action = "rebuild bounded research evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        self._adopt_authorized_extension_browser()
        intent = NativeActionIntent(
            intent_id=f"browser-managed-research-search-{event.event_id}",
            event_id=event.event_id,
            kind=self._BROWSER_FILL_AND_SUBMIT,
            args={
                "url": str(search.get("url") or ""),
                "textbox_name": str(search.get("textbox_name") or ""),
                "text": code,
                "button_name": str(search.get("button_name") or ""),
                "expected_url": str(search.get("expected_url") or ""),
            },
            reason=(
                "two managed-browser sources agreed on the release code and the authorized A page was freshly re-sensed; "
                "reuse the existing guarded USER form movement so target re-observation, postcondition verification and non-replay remain unchanged"
            ),
            source="resident_choice",
        )
        if not self._action_blocked_by_current_evidence(event, state, intent):
            self._begin_native_action_cycle(event, state, intent)
            self.store.save_working_state(state)
            if thought is not None:
                action = "search the freshly re-sensed authorized page for the independently researched release code"
                if action not in thought.possible_actions:
                    thought.possible_actions = (*thought.possible_actions, action)
                self._persist_enriched_thought(thought)
        return None

    def _discover_authorized_reference_context(self) -> dict[str, Any]:
        self._adopt_authorized_extension_browser()
        try:
            authorized = self.user_browser_extension.authorized_tab()
            if authorized is None:
                raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
            command = self.user_browser_extension.request_command(
                "probe_current_tab",
                args={"discover_reference_context": True},
                timeout_seconds=5.0,
                expected_tab_id=authorized.tab_id,
                expected_attached_at=authorized.attached_at,
            )
            if command.get("success") is not True:
                raise UserBrowserExtensionRelayError(str(command.get("error") or "authorized-page reference discovery failed"))
            result = command.get("result")
            if not isinstance(result, dict):
                raise UserBrowserExtensionRelayError("authorized-page reference discovery returned no structured evidence")
            if int(result.get("tab_id") or 0) != authorized.tab_id:
                raise UserBrowserExtensionRelayError("authorized-page reference discovery changed tab identity")
            result = dict(result)
            result["observed_at"] = str(command.get("completed_at") or "")
            return result
        finally:
            self._restore_browser_after_extension()

    @staticmethod
    def _rank_reference_candidates(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        ranked: list[tuple[int, int, dict[str, str]]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw[:16]):
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            text = " ".join(str(item.get("text") or "").strip().split())
            if not href or not text or href in seen:
                continue
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            seen.add(href)
            haystack = f"{text} {parsed.path}".lower()
            score = sum(1 for cue in _REFERENCE_CUES if cue in haystack)
            ranked.append((score, -index, {"href": href, "text": text[:240]}))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:6]]

    def _research_managed_references(self, references: list[dict[str, str]]) -> dict[str, Any]:
        browser = self.managed_browser
        if not isinstance(browser, ResearchSemanticPlaywrightManagedBrowser):
            raise RuntimeError("readable managed browser adapter is unavailable")
        allowed_origins = tuple(dict.fromkeys(self._origin_url(str(item["href"])) for item in references))
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=True,
            allowed_origins=allowed_origins,
        )
        session = browser.open_session(permission=permission, headless=True)
        source_evidence: list[dict[str, str]] = []
        codes: dict[str, list[str]] = defaultdict(list)
        try:
            for reference in references:
                source_url = str(reference["href"])
                page = self._navigate_and_read(browser, session.session_id, source_url, permission)
                code = self._release_code(page.get("text"))
                evidence_url = str(page.get("url") or source_url)
                observed_at = str(page.get("captured_at") or "")
                if code is None:
                    for detail in self._detail_candidates(page, source_url):
                        detail_page = self._navigate_and_read(browser, session.session_id, detail, permission)
                        detail_code = self._release_code(detail_page.get("text"))
                        if detail_code is None:
                            continue
                        code = detail_code
                        evidence_url = str(detail_page.get("url") or detail)
                        observed_at = str(detail_page.get("captured_at") or "")
                        break
                if code is None:
                    continue
                source_evidence.append(
                    {
                        "source_url": source_url,
                        "evidence_url": evidence_url,
                        "release_code": code,
                        "observed_at": observed_at,
                    }
                )
                if source_url not in codes[code]:
                    codes[code].append(source_url)
                if len(codes[code]) >= 2:
                    return {"release_code": code, "sources": source_evidence}
            raise RuntimeError("managed reference investigation did not find two distinct sources agreeing on one release code")
        finally:
            browser.close_session(session.session_id)

    @staticmethod
    def _navigate_and_read(browser, session_id: str, url: str, permission: BrowserPermissionContext) -> dict[str, Any]:
        observation = browser.observe(session_id)
        action = BrowserAction.create(
            session_id=session_id,
            kind=BrowserActionKind.NAVIGATE,
            page_id=observation.page_id,
            args={"url": url},
            expected={"url_equals": url},
        )
        authority = BrowserActionAuthority.from_observation(action, observation, permission)
        effect = browser.act(action, authority)
        if not effect.success:
            raise RuntimeError(effect.error or "managed browser navigation failed")
        return browser.read_page(session_id, page_id=effect.page_id)

    @staticmethod
    def _release_code(value: Any) -> str | None:
        matches = [match.group(1).strip() for match in _RELEASE_CODE_RE.finditer(str(value or ""))]
        unique = list(dict.fromkeys(match for match in matches if match))
        return unique[0] if len(unique) == 1 else None

    @staticmethod
    def _detail_candidates(page: dict[str, Any], source_url: str) -> list[str]:
        raw = page.get("links")
        if not isinstance(raw, list):
            return []
        origin = UserBrowserManagedResearchResidentRuntime._origin(source_url)
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw[:24]):
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            label = str(item.get("text") or "").strip()
            if not href or href in seen or href == source_url:
                continue
            try:
                if UserBrowserManagedResearchResidentRuntime._origin(href) != origin:
                    continue
                parsed = urlsplit(href)
            except ValueError:
                continue
            seen.add(href)
            haystack = f"{label} {parsed.path}".lower()
            score = sum(1 for cue in _DETAIL_CUES if cue in haystack)
            if score > 0:
                scored.append((score, -index, href))
        scored.sort(reverse=True)
        return [item[2] for item in scored[:4]]

    @staticmethod
    def _origin(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)

    @staticmethod
    def _origin_url(value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        scheme = parsed.scheme.lower()
        if not host or scheme not in {"http", "https"}:
            raise ValueError("managed reference URL must be HTTP(S)")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default = 80 if scheme == "http" else 443
        netloc = host if parsed.port in {None, default} else f"{host}:{parsed.port}"
        return f"{scheme}://{netloc}"
from __future__ import annotations

"""Direct Research & Information Work representative path for the one Resident.

The layer composes existing durable Work, WebResource, ModelRouter cognition,
NativeBody file mutation, and file identity verification. It does not create a
second agent, planner, router, memory store, or provider abstraction.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .file_identity import compare_file_identities, observe_file_identity
from .learned_behavior_resident import MemoryLearnedBehaviorResidentRuntime
from .models import CognitionRequest, ExecutionPath, ResidentRunResult, utc_now
from .research_information_work import (
    MAX_SEARCH_RESULTS,
    MAX_SELECTED_SOURCES,
    ResearchBundle,
    apply_verified_synthesis,
    build_source_observation,
    canonical_source_url,
    dedupe_source_observations,
    evidence_pack,
    independent_read_sources,
    parse_synthesis_json,
    render_research_markdown,
    render_research_response,
    research_completion_errors,
    search_candidates,
)
from .web_resource import WebDocument, WebResource


_RESEARCH_MARKERS = (
    "研究", "查一下", "查查", "调查", "多个来源", "几个来源", "别只看一个来源",
    "现在的价格", "当前价格", "主要区别", "最近的趋势", "行业的趋势", "都在讨论",
    "为什么这么多人聊", "弄明白", "research", "look into", "investigate",
    "multiple sources", "more than one source", "current price", "compare prices",
    "latest trend", "recent trend", "why people are talking",
)
_AMBIGUOUS_REFERENTS = (
    "这个东西", "这个行业", "这个产品", "这个模型", "这个项目", "这东西", "它", "刚才那个",
    "this thing", "this industry", "this product", "this model", "that thing", "that one",
)
_CONTINUATION_MARKERS = (
    "继续刚才那个调查", "继续刚才的调查", "继续刚才那个研究", "继续刚才的研究", "继续调查", "继续研究",
    "continue that research", "continue the research", "continue the investigation",
)
_DELIVERABLE_MARKERS = (
    "放进项目文件夹", "放到项目文件夹", "整理成一份", "可编辑", "能继续编辑", "写进项目",
    "save it in the project", "project folder", "editable document", "editable file",
)
_RECOMMENDATION_MARKERS = ("建议", "推荐", "给我一个建议", "recommend", "recommendation")
_CURRENT_MARKERS = ("现在", "当前", "最近", "最新", "today", "current", "latest", "recent", "right now")
_CAPITALIZED_ENTITY = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Za-z0-9._+\-/]*(?:\s+[A-Z0-9][A-Za-z0-9._+\-/]*){0,3}(?![A-Za-z0-9_])")
_QUOTED_ENTITY = re.compile(r"[\"'“”‘’`](.{2,120}?)[\"'“”‘’`]")


class ResearchInformationResidentRuntime(MemoryLearnedBehaviorResidentRuntime):
    """Execute bounded normal-language Research Work through reusable ZN contracts."""

    _RESEARCH_META_KEY = "research_information_work_v1"
    _BUNDLE_ACCEPTANCE = "research_bundle:v1"
    _ARTIFACT_ACCEPTANCE = "research_artifact_verification:v1"
    _MAX_RESEARCH_MODEL_CALLS = 4
    _FRESHNESS_RECHECK_SECONDS = 6 * 60 * 60

    def __init__(self, *args, research_web_resource: WebResource | None = None, research_web_error: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.research_web_resource = research_web_resource
        self.research_web_error = str(research_web_error or "").strip() or None

    def configure_research_web_resource(self, resource: WebResource | None, *, error: str | None = None) -> None:
        self.research_web_resource = resource
        self.research_web_error = str(error or "").strip() or None

    def _advance_event_step(self, event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        if stage == "orient" and self._is_research_event(event):
            return self._begin_research_work(event, state)
        if stage == "research_plan":
            return self._research_plan_step(event, state)
        if stage == "research_acquire":
            return self._research_acquire_step(event, state)
        if stage == "research_synthesize":
            return self._research_synthesis_step(event, state)
        if stage == "research_deliver":
            return self._research_deliver_step(event, state)
        return super()._advance_event_step(event, state, readiness=readiness, learning_evidence=learning_evidence, thought=thought)

    def _is_research_event(self, event) -> bool:
        task = " ".join(str(getattr(event, "task", "") or "").split())
        lowered = task.casefold()
        if any(marker.casefold() in lowered for marker in _RESEARCH_MARKERS):
            return True
        if any(marker.casefold() in lowered for marker in _CONTINUATION_MARKERS):
            thread_id = str(getattr(event, "payload", {}).get("work_thread_id") or "").strip()
            return self._latest_research_bundle(thread_id) is not None if thread_id else False
        return False

    @staticmethod
    def _requests_deliverable(task: str) -> bool:
        lowered = str(task or "").casefold()
        return any(marker.casefold() in lowered for marker in _DELIVERABLE_MARKERS)

    @staticmethod
    def _requests_recommendation(task: str) -> bool:
        lowered = str(task or "").casefold()
        return any(marker.casefold() in lowered for marker in _RECOMMENDATION_MARKERS)

    @staticmethod
    def _has_ambiguous_referent(task: str) -> bool:
        lowered = str(task or "").casefold()
        return any(marker.casefold() in lowered for marker in _AMBIGUOUS_REFERENTS)

    @staticmethod
    def _is_continuation(task: str) -> bool:
        lowered = str(task or "").casefold()
        return any(marker.casefold() in lowered for marker in _CONTINUATION_MARKERS)

    @staticmethod
    def _is_current_sensitive(task: str) -> bool:
        lowered = str(task or "").casefold()
        return any(marker.casefold() in lowered for marker in _CURRENT_MARKERS)

    def _begin_research_work(self, event, state):
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None or root.parent_work_item_id is not None:
            return self._research_blocked(event, state, "research requires a durable Root Work created by the normal user Work ingress", response="这项研究目前没有绑定到可持续的 Work，无法安全开始。")

        meta = {
            "work_thread_id": root.work_thread_id,
            "root_work_item_id": root.work_item_id,
            "plan_version": root.plan_version,
            "deliverable_requested": self._requests_deliverable(event.task),
            "recommendation_required": self._requests_recommendation(event.task),
            "follow_up_round": 0,
            "model_invocations": 0,
            "pending_queries": [],
        }
        state.data[self._RESEARCH_META_KEY] = meta

        if meta["deliverable_requested"] and self._authorized_workspace(event, root.work_thread_id) is None:
            return self._research_blocked(event, state, "editable research deliverable requires one exact authorized Work workspace", response="我可以先研究，但你要求把结果放进项目文件夹；当前 Work 没有唯一授权的项目目录。请先指定/绑定要写入的项目文件夹。")

        prior = self._latest_research_bundle(root.work_thread_id)
        if self._is_continuation(event.task) and prior is not None:
            bundle = ResearchBundle.from_dict(prior.to_dict())
            bundle.goal = str(event.task)[:2_000]
            bundle.artifact = None
            bundle.status = "collecting"
            bundle.updated_at = utc_now()
            item_id = self._persist_research_bundle(event, bundle)
            meta["bundle_work_item_id"] = item_id
            state.data[self._RESEARCH_META_KEY] = meta
            if self._bundle_requires_freshness_refresh(bundle, event.task):
                meta["pending_queries"] = [bundle.resolved_subject]
                state.stage = "research_acquire"
                state.next_action = "refresh time-sensitive source evidence before continuing"
            else:
                state.stage = "research_synthesize"
                state.next_action = "continue from durable Research Work evidence"
            self.store.save_working_state(state)
            return None

        if self._has_ambiguous_referent(event.task):
            candidates = self._bounded_referent_candidates(event, root.work_thread_id)
            if len(candidates) == 1:
                subject = candidates[0]
                bundle = ResearchBundle(goal=str(event.task)[:2_000], resolved_subject=subject, search_queries=[subject])
                item_id = self._persist_research_bundle(event, bundle)
                meta["bundle_work_item_id"] = item_id
                meta["pending_queries"] = [subject]
                meta["resolved_from"] = "bounded_current_work_context"
                state.data[self._RESEARCH_META_KEY] = meta
                state.stage = "research_acquire"
                state.next_action = "search current public sources for the uniquely resolved subject"
                self.store.save_working_state(state)
                return None
            if not candidates:
                return self._research_blocked(event, state, "ambiguous research target has no bounded current-context referent", response="你说的“这个东西”在当前 Work 上下文里没有唯一指代。请告诉我具体要研究的对象。")
            rendered = "、".join(candidates[:4])
            return self._research_blocked(event, state, "ambiguous research target has multiple equally plausible current-context referents", response=f"当前上下文里有多个可能对象：{rendered}。你指的是哪一个？")

        state.stage = "research_plan"
        state.next_action = "resolve the explicit research subject and bounded search queries"
        self.store.save_working_state(state)
        return None

    def _bounded_referent_candidates(self, event, thread_id: str) -> list[str]:
        messages = self.work_ledger.list_messages(thread_id, limit=8)
        current_message_id = str(event.payload.get("work_message_id") or "")
        prior_users = [item for item in messages if item.role == "user" and item.message_id != current_message_id]
        if not prior_users:
            prior = self._latest_research_bundle(thread_id)
            return [prior.resolved_subject] if prior is not None and prior.resolved_subject else []
        text = str(prior_users[-1].text or "")[:2_000]
        candidates: list[str] = []
        for match in _QUOTED_ENTITY.findall(text):
            value = " ".join(match.split())[:120]
            if value and value not in candidates:
                candidates.append(value)
        for match in _CAPITALIZED_ENTITY.findall(text):
            value = " ".join(match.split())[:120]
            folded = value.casefold()
            if folded in {"i", "the", "this", "that", "product", "model"}:
                continue
            if value and value not in candidates:
                candidates.append(value)
        return candidates[:4]

    def _research_plan_step(self, event, state):
        prompt = (
            "You are a replaceable cognition resource inside one ZN Research Work. Do not answer the research question and do not invent current facts. "
            "Resolve only the explicit subject already present in the user's request and propose bounded public-web search queries. Return ONLY JSON shaped exactly as "
            '{"research_plan":{"subject":"...","queries":["...", "..."]}}. Use 1-3 concise queries. The subject must be grounded in the user request, not guessed from popularity. '
            f"User research goal: {str(event.task)[:2000]}"
        )
        raw, blocker = self._run_research_cognition(event, state, purpose="research_plan", prompt=prompt, context={"research_goal": str(event.task)[:2_000]})
        if blocker is not None:
            return self._research_blocked(event, state, blocker, response=blocker)
        try:
            parsed = json.loads(str(raw or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        plan = parsed.get("research_plan") if isinstance(parsed, dict) and set(parsed) == {"research_plan"} else None
        if not isinstance(plan, Mapping):
            return self._research_blocked(event, state, "research cognition did not return a valid bounded research plan", response="我没能形成可靠的研究对象/搜索计划，因此没有开始猜测式搜索。")
        subject = " ".join(str(plan.get("subject") or "").split())[:600]
        queries_raw = plan.get("queries")
        queries = [" ".join(str(value or "").split())[:300] for value in (queries_raw if isinstance(queries_raw, list) else []) if " ".join(str(value or "").split())][:3]
        if not subject or not queries or not self._subject_grounded_in_task(subject, event.task):
            return self._research_blocked(event, state, "research plan subject was not grounded in the explicit user request", response="研究对象仍不够明确，我不会根据网络热度替你猜。请补充具体对象。")

        bundle = ResearchBundle(goal=str(event.task)[:2_000], resolved_subject=subject, search_queries=list(queries))
        item_id = self._persist_research_bundle(event, bundle)
        meta = self._research_meta(state)
        meta["bundle_work_item_id"] = item_id
        meta["pending_queries"] = list(queries)
        state.data[self._RESEARCH_META_KEY] = meta
        state.stage = "research_acquire"
        state.next_action = "search and extract multiple independent current source documents"
        self.store.save_working_state(state)
        return None

    @staticmethod
    def _subject_grounded_in_task(subject: str, task: str) -> bool:
        left = " ".join(str(subject or "").casefold().split())
        right = " ".join(str(task or "").casefold().split())
        if not left or not right:
            return False
        if left in right:
            return True
        tokens = [token for token in re.findall(r"[a-z0-9][a-z0-9._+\-/]{1,}", left) if len(token) >= 2]
        return bool(tokens and any(token in right for token in tokens))

    def _research_acquire_step(self, event, state):
        bundle = self._load_current_bundle(event, state)
        if bundle is None:
            return self._research_blocked(event, state, "durable Research Work lost its evidence bundle", response="研究证据状态丢失，ZN 已停止而不是重新猜测。")
        resource = self.research_web_resource
        if resource is None:
            detail = self.research_web_error or "no configured ZN WebResource is available"
            return self._research_blocked(event, state, f"无法获得当前来源：{detail}", response=f"无法获得当前来源：{detail}")
        policy_blocker = self._public_web_policy_blocker(event)
        if policy_blocker is not None:
            return self._research_blocked(event, state, policy_blocker, response=policy_blocker)

        meta = self._research_meta(state)
        pending_raw = meta.get("pending_queries")
        pending = [" ".join(str(value or "").split())[:300] for value in (pending_raw if isinstance(pending_raw, list) else []) if " ".join(str(value or "").split())][:3]
        if not pending:
            pending = list(bundle.search_queries[:3]) or [bundle.resolved_subject]

        candidates = []
        seen_candidate_ids = {source.canonical_url for source in bundle.sources if source.canonical_url}
        search_failures: list[str] = []
        for query in pending:
            try:
                results = resource.search(query, limit=MAX_SEARCH_RESULTS)
            except Exception as exc:
                search_failures.append(f"search {query!r}: {type(exc).__name__}: {str(exc)[:1000]}")
                continue
            for item in search_candidates(results):
                canonical = canonical_source_url(item.url)
                if not canonical or canonical in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(canonical)
                candidates.append(item)
                if len(candidates) >= MAX_SELECTED_SOURCES:
                    break
            if len(candidates) >= MAX_SELECTED_SOURCES:
                break

        observations = list(bundle.sources)
        if candidates:
            requested = [item.url for item in candidates]
            try:
                documents = resource.extract(requested)
            except Exception as exc:
                documents = []
                search_failures.append(f"extract: {type(exc).__name__}: {str(exc)[:1000]}")
            for index, candidate in enumerate(candidates):
                document = self._matching_document(candidate.url, documents, index=index)
                observations.append(build_source_observation(candidate, document))

        bundle.acquisition_failures.extend(search_failures)
        bundle.acquisition_failures = bundle.acquisition_failures[-16:]
        bundle.sources = dedupe_source_observations(observations)
        bundle.search_queries = list(dict.fromkeys((*bundle.search_queries, *pending)))[:8]
        bundle.status = "evidence_collected"
        bundle.updated_at = utc_now()
        self._persist_research_bundle(event, bundle)

        read_sources = independent_read_sources(bundle)
        if len({item.source_id for item in read_sources}) < 2:
            failure_details = [f"{item.requested_url}: {item.error or item.extraction_status}" for item in bundle.sources if item.extraction_status != "read"]
            detail = " | ".join((search_failures + failure_details)[-5:]) or "search/extraction produced fewer than two independent readable source documents"
            return self._research_blocked(event, state, f"无法获得足够的当前来源：{detail}", response=f"无法获得足够的当前来源，研究已阻塞：{detail}")

        meta["pending_queries"] = []
        state.data[self._RESEARCH_META_KEY] = meta
        state.stage = "research_synthesize"
        state.next_action = "synthesize only from the bounded extracted Evidence Pack"
        self.store.save_working_state(state)
        return None

    @staticmethod
    def _matching_document(requested_url: str, documents: list[WebDocument], *, index: int) -> WebDocument | None:
        requested_canonical = canonical_source_url(requested_url)
        for document in documents:
            metadata = document.metadata if isinstance(document.metadata, Mapping) else {}
            explicit = str(metadata.get("requestedURL") or "").strip()
            if explicit and canonical_source_url(explicit) == requested_canonical:
                return document
        for document in documents:
            if canonical_source_url(document.url) == requested_canonical:
                return document
        if len(documents) == 1 and index == 0:
            return documents[0]
        return None

    def _research_synthesis_step(self, event, state):
        bundle = self._load_current_bundle(event, state)
        if bundle is None:
            return self._research_blocked(event, state, "durable Research Work lost its evidence bundle before synthesis", response="研究证据状态丢失，无法进行有依据的综合。")
        if self._bundle_requires_freshness_refresh(bundle, event.task):
            meta = self._research_meta(state)
            if int(meta.get("freshness_refreshes") or 0) < 1:
                meta["freshness_refreshes"] = 1
                meta["pending_queries"] = list(bundle.search_queries[:2]) or [bundle.resolved_subject]
                state.data[self._RESEARCH_META_KEY] = meta
                state.stage = "research_acquire"
                state.next_action = "refresh stale time-sensitive source evidence"
                self.store.save_working_state(state)
                return None

        pack = evidence_pack(bundle)
        prompt = (
            "You are a replaceable cognition resource inside one ZN Research Work. Use ONLY the provided Evidence Pack. Never add a price, date, specification, source, event, or factual claim not supported by an exact quote from a source whose extraction_status is read. "
            "Search snippets and provider-generated answers are not evidence. Source authority/freshness/directness may affect interpretation but no source is absolute truth. Preserve material disagreement as a conflict instead of averaging or silently choosing. Return ONLY JSON shaped as "
            '{"research_synthesis":{"claims":[{"text":"...","supports":[{"source_id":"source-...","quote":"exact source excerpt"}]}],"conflicts":[{"field":"...","claims":[{"value":"...","source_id":"source-...","quote":"exact excerpt"},{"value":"...","source_id":"source-...","quote":"exact excerpt"}],"status":"unresolved|context-dependent|stale-source-suspected"}],"recommendation":{"text":"...","supports":[{"source_id":"source-...","quote":"exact excerpt"}]},"unknowns":["..."],"follow_up_queries":["..."]}}. '
            "If no recommendation is justified, use null. Use at most two follow_up_queries and only when another current source could materially resolve a conflict/unknown. Evidence Pack follows:\n"
            + json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
        )
        raw, blocker = self._run_research_cognition(event, state, purpose="research_synthesis", prompt=prompt, context={"research_evidence_pack": pack})
        if blocker is not None:
            return self._research_blocked(event, state, blocker, response=blocker)
        try:
            parsed = parse_synthesis_json(raw or "")
            bundle = apply_verified_synthesis(bundle, parsed)
        except ValueError as exc:
            return self._research_blocked(event, state, f"grounded research synthesis was rejected: {exc}", response="研究认知输出没有通过 ZN 的 evidence/citation 校验，因此没有把它当成结论。")
        self._persist_research_bundle(event, bundle)

        meta = self._research_meta(state)
        follow_round = int(meta.get("follow_up_round") or 0)
        if bundle.follow_up_queries and follow_round < 1:
            meta["follow_up_round"] = follow_round + 1
            meta["pending_queries"] = list(bundle.follow_up_queries)
            bundle.follow_up_queries = []
            bundle.status = "follow_up_required"
            self._persist_research_bundle(event, bundle)
            state.data[self._RESEARCH_META_KEY] = meta
            state.stage = "research_acquire"
            state.next_action = "investigate one bounded follow-up round for unresolved evidence"
            self.store.save_working_state(state)
            return None

        errors = research_completion_errors(bundle, recommendation_required=bool(meta.get("recommendation_required")))
        if errors:
            return self._research_blocked(event, state, "research completion verification failed: " + "; ".join(errors), response="研究没有通过完成校验：" + "；".join(errors))

        if bool(meta.get("deliverable_requested")):
            state.stage = "research_deliver"
            state.next_action = "write and freshly verify the grounded editable Markdown artifact"
            self.store.save_working_state(state)
            return None
        return self._complete_research(event, state, bundle)

    def _research_deliver_step(self, event, state):
        bundle = self._load_current_bundle(event, state)
        meta = self._research_meta(state)
        if bundle is None:
            return self._research_blocked(event, state, "durable Research Work lost its evidence bundle before file delivery", response="研究证据状态丢失，未写入项目文件。")
        thread_id = str(meta.get("work_thread_id") or "").strip()
        workspace = self._authorized_workspace(event, thread_id)
        if workspace is None:
            return self._research_blocked(event, state, "research deliverable destination is not one exact authorized project workspace", response="当前没有唯一授权的项目目录，因此没有创建文件。")

        markdown = render_research_markdown(bundle, title=bundle.resolved_subject)
        destination = workspace / self._research_filename(bundle.resolved_subject, event.event_id)
        try:
            resolved_destination = destination.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            return self._research_blocked(event, state, f"research deliverable path cannot be resolved: {exc}", response="研究结果路径无法安全解析，因此没有创建文件。")
        if resolved_destination.parent != workspace:
            return self._research_blocked(event, state, "research deliverable escaped the authorized project workspace", response="研究结果路径超出了授权项目目录，因此没有创建文件。")

        before = observe_file_identity(resolved_destination)
        if not before.get("observable") or before.get("exists"):
            return self._research_blocked(event, state, "research deliverable target already exists or is not safely observable", response="目标研究文档已存在或无法安全观察，ZN 没有覆盖它。")

        write = self.body.act("write_text", event_id=event.event_id, path=str(resolved_destination), content=markdown, append=False, create_parents=False, encoding="utf-8")
        if not write.success:
            return self._research_blocked(event, state, f"research Markdown write failed: {write.error or write.output}", response="研究完成了，但本地 Markdown 写入失败；ZN 没有把未验证文件当成交付结果。")

        first_identity = observe_file_identity(resolved_destination)
        reread = self.body.act("read_text", event_id=event.event_id, path=str(resolved_destination), max_chars=max(20_000, len(markdown) + 1), encoding="utf-8")
        second_identity = observe_file_identity(resolved_destination)
        comparison = compare_file_identities(first_identity, second_identity)
        required_sections = ("# ", "## Summary", "## Key findings", "## Conflicting evidence / uncertainty", "## Recommendation", "## Sources")
        source_ids = [item.source_id for item in independent_read_sources(bundle)]
        verified = (
            first_identity.get("exists") is True and first_identity.get("type") == "file" and first_identity.get("digest_complete") is True
            and reread.success and reread.output == markdown and comparison.get("exact") is True
            and all(section in reread.output for section in required_sections) and all(source_id in reread.output for source_id in source_ids)
        )
        if not verified:
            return self._research_blocked(event, state, "fresh research artifact reread/identity verification failed", response="Markdown 已尝试写入，但 fresh reread / file identity 校验没有通过，因此任务没有被标记完成。")

        bundle.artifact = {
            "kind": "markdown", "path": str(resolved_destination), "content_sha256": first_identity.get("content_sha256"),
            "size_bytes": first_identity.get("size_bytes"), "observed_at": second_identity.get("observed_at"),
            "fresh_reread_verified": True, "identity_exact_after_reread": True,
        }
        bundle.updated_at = utc_now()
        self._persist_research_bundle(event, bundle)
        self._persist_artifact_verification(event, bundle)
        return self._complete_research(event, state, bundle)

    def _complete_research(self, event, state, bundle: ResearchBundle):
        meta = self._research_meta(state)
        errors = research_completion_errors(bundle, recommendation_required=bool(meta.get("recommendation_required")))
        if bool(meta.get("deliverable_requested")) and (not isinstance(bundle.artifact, dict) or bundle.artifact.get("fresh_reread_verified") is not True):
            errors.append("editable artifact has no fresh reread/file-identity verification")
        if errors:
            return self._research_blocked(event, state, "research completion verification failed: " + "; ".join(errors), response="研究没有通过最终完成校验：" + "；".join(errors))

        bundle.status = "complete"
        bundle.updated_at = utc_now()
        self._persist_research_bundle(event, bundle)
        response = render_research_response(bundle)
        if isinstance(bundle.artifact, dict):
            response += f"\n\n可编辑 Markdown：{bundle.artifact.get('path')}"
        state.stage = "complete"
        state.next_action = None
        state.blocked_by = None
        self.store.save_working_state(state)
        invocations = max(0, int(meta.get("model_invocations") or 0))
        return ResidentRunResult(event=event, execution_path=ExecutionPath.MODEL if invocations else ExecutionPath.INVESTIGATION, success=True, response=response, model_invocations=invocations, reason="Research Work completed only after multi-source extraction, grounded synthesis, and required artifact verification")

    def _research_blocked(self, event, state, reason: str, *, response: str):
        state.stage = "failed"
        state.next_action = None
        state.blocked_by = "research_blocked"
        state.data["research_blocker"] = str(reason)[:4_000]
        self.store.save_working_state(state)
        meta = self._research_meta(state)
        invocations = max(0, int(meta.get("model_invocations") or 0))
        return ResidentRunResult(event=event, execution_path=ExecutionPath.MODEL if invocations else ExecutionPath.INVESTIGATION, success=False, response=str(response)[:8_000], model_invocations=invocations, reason=str(reason)[:4_000])

    def _run_research_cognition(self, event, state, *, purpose: str, prompt: str, context: dict[str, Any]) -> tuple[str | None, str | None]:
        meta = self._research_meta(state)
        prior_calls = max(0, int(meta.get("model_invocations") or 0))
        if prior_calls >= self._MAX_RESEARCH_MODEL_CALLS:
            return None, "research cognition call bound was exhausted before verified completion"

        route_policy = event.payload.get("route_policy")
        request_context = {
            "research_purpose": purpose[:120], "work_thread_id": str(meta.get("work_thread_id") or "")[:200],
            "root_work_item_id": str(meta.get("root_work_item_id") or "")[:200], "plan_version": int(meta.get("plan_version") or 1), **dict(context),
        }
        if route_policy is not None:
            request_context["route_policy"] = route_policy
        request = CognitionRequest(request_id=f"cog-{uuid.uuid4().hex[:12]}", impasse_id=f"research-{purpose}-{event.event_id}", event_id=event.event_id, question=prompt, required_capabilities=("general",), context=request_context)
        try:
            kernel_result = self.kernel.run_goal(
                request.question, required_capabilities=request.required_capabilities, priority=event.priority,
                metadata={"resident_event_id": event.event_id, "research_purpose": purpose, "cognition_request": {"request_id": request.request_id, "context": request.context}},
                max_attempts_override=1,
            )
        except Exception as exc:
            return None, f"research cognition unavailable: {type(exc).__name__}: {str(exc)[:1200]}"

        invocations = sum(1 for experience in kernel_result.experiences if experience.metrics.get("model_invoked", True) is not False)
        prompt_tokens, completion_tokens = self._sum_tokens(kernel_result)
        self.store.record_runtime_task(model_invocations=invocations, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        meta["model_invocations"] = prior_calls + invocations
        state.data[self._RESEARCH_META_KEY] = meta
        self.store.save_working_state(state)
        if not kernel_result.assessment.success:
            detail = kernel_result.worker_result.error or "no eligible/healthy cognition route completed the request"
            return None, f"research cognition blocker: {detail}"
        return str(kernel_result.worker_result.response or ""), None

    @staticmethod
    def _public_web_policy_blocker(event) -> str | None:
        policy = event.payload.get("route_policy")
        if not isinstance(policy, Mapping):
            return None
        classification = str(policy.get("data_classification") or "").strip().lower()
        if classification in {"private", "local_only", "cloud_denied"}:
            return "current Work data policy does not permit sending this research subject to a public WebResource"
        if bool(policy.get("local_only")) or bool(policy.get("cloud_forbidden")):
            return "current Work policy forbids public-web research for this data"
        return None

    def _authorized_workspace(self, event, thread_id: str) -> Path | None:
        explicit = str(event.payload.get("workspace_path") or "").strip()
        if not explicit or not thread_id:
            return None
        thread = self.work_ledger.get_thread(thread_id)
        if thread is None:
            return None
        association = self.work_ledger.workspace_for(thread)
        if association is None:
            return None
        try:
            event_path = Path(explicit).resolve(strict=True)
            work_path = Path(association.path).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if event_path != work_path or not event_path.is_dir():
            return None
        return event_path

    @staticmethod
    def _research_filename(subject: str, event_id: str) -> str:
        ascii_slug = re.sub(r"[^a-z0-9]+", "-", str(subject or "").casefold()).strip("-")[:48] or "brief"
        suffix = hashlib.sha256(str(event_id).encode("utf-8")).hexdigest()[:8]
        return f"research-{ascii_slug}-{suffix}.md"

    def _research_meta(self, state) -> dict[str, Any]:
        raw = state.data.get(self._RESEARCH_META_KEY)
        return dict(raw) if isinstance(raw, dict) else {}

    def _persist_research_bundle(self, event, bundle: ResearchBundle) -> str:
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None:
            raise RuntimeError("Research Work lost its durable Root")
        current_plan = self.work_ledger.plan_version(root.work_thread_id)
        if root.plan_version != current_plan:
            raise RuntimeError("Research Work rejected evidence for a stale plan")
        items = self.work_ledger.list_work_items(root.work_thread_id, limit=256)
        item = next((value for value in items if value.parent_work_item_id == root.work_item_id and value.plan_version == current_plan and self._BUNDLE_ACCEPTANCE in value.acceptance_criteria), None)
        if item is None:
            item = self.work_ledger.create_child_item(root_work_item_id=root.work_item_id, objective="Preserve bounded source/evidence/provenance for the current Research Work", acceptance_criteria=[self._BUNDLE_ACCEPTANCE], title="Research evidence")
        now = utc_now()
        item.status = "completed"
        item.result = json.dumps(bundle.to_dict(), ensure_ascii=False, separators=(",", ":"))
        item.blocker = None
        item.completed_at = now
        item.updated_at = now
        self.work_ledger._save_item(item)
        return item.work_item_id

    def _persist_artifact_verification(self, event, bundle: ResearchBundle) -> None:
        if not isinstance(bundle.artifact, dict):
            return
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None:
            return
        item = self.work_ledger.create_child_item(root_work_item_id=root.work_item_id, objective="Freshly reread and identity-verify the editable Research deliverable", acceptance_criteria=[self._ARTIFACT_ACCEPTANCE], title="Verify research artifact")
        now = utc_now()
        item.status = "completed"
        item.result = json.dumps(bundle.artifact, ensure_ascii=False, separators=(",", ":"))
        item.blocker = None
        item.completed_at = now
        item.updated_at = now
        self.work_ledger._save_item(item)

    def _load_current_bundle(self, event, state) -> ResearchBundle | None:
        meta = self._research_meta(state)
        item_id = str(meta.get("bundle_work_item_id") or "").strip()
        root = self.work_ledger.work_item_for_event(event.event_id)
        if root is None:
            return None
        items = self.work_ledger.list_work_items(root.work_thread_id, limit=256)
        candidates = [item for item in items if item.parent_work_item_id == root.work_item_id and item.plan_version == root.plan_version and self._BUNDLE_ACCEPTANCE in item.acceptance_criteria and item.result]
        if item_id:
            candidates.sort(key=lambda item: item.work_item_id != item_id)
        if not candidates:
            return None
        try:
            raw = json.loads(str(candidates[0].result or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return ResearchBundle.from_dict(raw) if isinstance(raw, Mapping) else None

    def _latest_research_bundle(self, thread_id: str) -> ResearchBundle | None:
        if not thread_id:
            return None
        items = [item for item in self.work_ledger.list_work_items(thread_id, limit=256) if self._BUNDLE_ACCEPTANCE in item.acceptance_criteria and item.result]
        items.sort(key=lambda item: str(item.updated_at or ""), reverse=True)
        for item in items:
            try:
                raw = json.loads(str(item.result or ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(raw, Mapping):
                return ResearchBundle.from_dict(raw)
        return None

    def _bundle_requires_freshness_refresh(self, bundle: ResearchBundle, task: str) -> bool:
        if not self._is_current_sensitive(task):
            return False
        now = datetime.now(timezone.utc)
        for source in independent_read_sources(bundle):
            try:
                captured = datetime.fromisoformat(source.captured_at.replace("Z", "+00:00"))
                if captured.tzinfo is None:
                    captured = captured.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return True
            if (now - captured.astimezone(timezone.utc)).total_seconds() > self._FRESHNESS_RECHECK_SECONDS:
                return True
        return False

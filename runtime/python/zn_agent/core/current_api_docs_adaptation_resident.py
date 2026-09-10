from __future__ import annotations

"""Bounded current-page API-doc adaptation for one existing ZN Resident.

This composes existing User Browser, managed research, Work, File, Terminal and
WorkerRun capabilities. It owns no second agent, router, Body, store or Root
completion authority.
"""

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .action_authority import ActionAuthorityContext, bind_worker_authority_arg
from .application_resident import ApplicationAwareResidentRuntime
from .cognition import CognitiveIncrement
from .delegated_work_coordinator import DelegatedWorkCoordinator
from .models import utc_now
from .path_context import resolved_within
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .worker_context_boundary import WorkerContextPack
from .work import title_for_work_task


class CurrentApiDocsDelegatedWorkCoordinator(DelegatedWorkCoordinator):
    """Use the Resident's E2E-25 phase order without owning new truth."""

    def next_worker_phase(self, root: WorkItem, items, runs):
        if self.resident._is_current_api_docs_adaptation_root(root):
            return self.resident._next_worker_phase(root, items, runs)
        return super().next_worker_phase(root, items, runs)

    def bind_worker_request(
        self,
        event,
        root: WorkItem,
        request,
        worker,
        child,
        *,
        expected_action: str,
        completed,
    ):
        request = super().bind_worker_request(
            event,
            root,
            request,
            worker,
            child,
            expected_action=expected_action,
            completed=completed,
        )
        if expected_action != "read_workspace_file":
            return request
        inventory = self.resident._workspace_inventory_for_worker(event, worker)
        context = dict(request.context or {})
        raw_pack = context.get("worker_context_pack")
        if not isinstance(raw_pack, dict):
            raise RuntimeError("workspace read WorkerRun lost its bounded context pack")
        evidence = list(raw_pack.get("relevant_evidence") or [])[-7:]
        evidence.append({"kind": "workspace_inventory", "entries": inventory})
        pack = WorkerContextPack(
            root_goal_summary=str(raw_pack.get("root_goal_summary") or ""),
            work_item_objective=str(raw_pack.get("work_item_objective") or ""),
            acceptance_criteria=tuple(raw_pack.get("acceptance_criteria") or ()),
            plan_version=int(raw_pack.get("plan_version") or 0),
            relevant_evidence=tuple(item for item in evidence if isinstance(item, dict)),
            artifact_refs=tuple(
                item for item in (raw_pack.get("artifact_refs") or []) if isinstance(item, dict)
            ),
            tool_scope=tuple(raw_pack.get("tool_scope") or ()),
            authority_scope=tuple(raw_pack.get("authority_scope") or ()),
            forbidden_actions=tuple(raw_pack.get("forbidden_actions") or ()),
            expected_result_schema=dict(raw_pack.get("expected_result_schema") or {}),
            provenance=dict(raw_pack.get("provenance") or {}),
            data_classification=str(raw_pack.get("data_classification") or "private"),
        )
        context["worker_context_pack"] = pack.to_dict()
        request.context = context
        request.question += (
            " Choose exactly one relevant regular file from workspace_inventory. "
            "Do not guess a path that is absent from that inventory."
        )
        return request


class CurrentApiDocsAdaptationResidentRuntime(ApplicationAwareResidentRuntime):
    """Close one representative current-docs -> existing-code -> real-result path."""

    _CURRENT_SOURCE_KEY = "e2e25_current_page_source"
    _WORKSPACE_READ_KEY = "e2e25_workspace_read"
    _PREVERIFY_EVIDENCE_KEY = "e2e25_preverification_evidence"
    _MAX_WORKSPACE_READ_CHARS = 1200
    _MAX_WORKSPACE_INVENTORY = 24

    @staticmethod
    def _is_current_api_docs_adaptation_text(text: str) -> bool:
        normalized = " ".join(str(text or "").casefold().split())
        current_page = any(
            value in normalized
            for value in ("这个网站", "当前网站", "this website", "current page")
        )
        api_docs = "api" in normalized and any(
            value in normalized for value in ("文档", "docs", "documentation")
        )
        adapt = any(
            value in normalized
            for value in ("适配", "升级", "adapt", "update the project", "upgrade")
        )
        run = any(
            value in normalized
            for value in ("跑起来", "运行", "run it", "run the project")
        )
        verify = any(
            value in normalized
            for value in ("确认能用", "确认", "验证", "verify", "confirm")
        )
        return current_page and api_docs and adapt and run and verify

    @classmethod
    def _is_current_api_docs_adaptation_root(cls, root: WorkItem) -> bool:
        return cls._is_current_api_docs_adaptation_text(str(root.objective or ""))

    @staticmethod
    def _root_requests_delegated_worker_sequence(root: WorkItem) -> bool:
        if CurrentApiDocsAdaptationResidentRuntime._is_current_api_docs_adaptation_root(root):
            return True
        return ApplicationAwareResidentRuntime._root_requests_delegated_worker_sequence(root)

    def _delegated_work_coordinator(self) -> DelegatedWorkCoordinator:
        coordinator = getattr(self, "_delegated_work_coordinator_instance", None)
        if coordinator is None or not isinstance(
            coordinator, CurrentApiDocsDelegatedWorkCoordinator
        ):
            coordinator = CurrentApiDocsDelegatedWorkCoordinator(self)
            self._delegated_work_coordinator_instance = coordinator
        return coordinator

    def _next_worker_phase(self, root, items, runs):
        if not self._is_current_api_docs_adaptation_root(root):
            return super()._next_worker_phase(root, items, runs)
        current_children = [
            item
            for item in items
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        item_by_id = {item.work_item_id: item for item in current_children}
        accepted = {
            run.work_item_id: run
            for run in runs
            if run.state == "completed"
            and run.verification_status == "accepted"
            and run.work_item_id in item_by_id
            and item_by_id[run.work_item_id].status == "completed"
        }
        if not any(run.executor_kind == "research" for run in accepted.values()):
            return "research", "research_current_page"
        real_children = [
            item
            for item in current_children
            if not any(
                c.startswith("delegated_worker_evidence:")
                for c in item.acceptance_criteria
            )
        ]
        if not any(
            item.status == "completed"
            and any(c.startswith("file_read:") for c in item.acceptance_criteria)
            for item in real_children
        ):
            return "coding", "read_workspace_file"
        return super()._next_worker_phase(root, items, runs)

    def _e2e25_required_phase_evidence(self, root: WorkItem) -> tuple[bool, str]:
        """Require every current-plan delegated phase and its real Body effect.

        Retry exhaustion is supervision evidence, not permission to skip a phase.
        This gate prevents an unbound later cognition increment from proposing a
        final Root verifier while required research/workspace evidence is absent.
        """

        items = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        item_by_id = {item.work_item_id: item for item in items}
        accepted_phase_keys: set[str] = set()
        for run in self.work_ledger.list_worker_runs(thread_id=root.work_thread_id, limit=256):
            item = item_by_id.get(run.work_item_id)
            if (
                run.plan_version != root.plan_version
                or run.state != "completed"
                or run.verification_status != "accepted"
                or item is None
                or item.status != "completed"
            ):
                continue
            for criterion in item.acceptance_criteria:
                value = str(criterion).strip()
                if value.startswith("delegated_worker_evidence:"):
                    accepted_phase_keys.add(value.split(":", 1)[1].strip())

        required_phases = {
            "research/research_current_page",
            "coding/read_workspace_file",
            "coding/write_file",
            "coding/run_python",
            "review/run_python",
        }
        missing_phases = sorted(required_phases - accepted_phase_keys)
        if missing_phases:
            return False, "missing accepted delegated phases: " + ", ".join(missing_phases)

        real_completed = [
            item
            for item in items
            if item.status == "completed"
            and not any(
                str(c).startswith("delegated_worker_evidence:")
                for c in item.acceptance_criteria
            )
        ]

        def has(prefix: str) -> bool:
            return any(
                any(str(c).startswith(prefix) for c in item.acceptance_criteria)
                for item in real_completed
            )

        missing_effects = [
            prefix.rstrip(":")
            for prefix in ("page_read:", "file_read:", "text_equals:")
            if not has(prefix)
        ]
        command_count = sum(
            1
            for item in real_completed
            if any(str(c).startswith("command_exit:") for c in item.acceptance_criteria)
        )
        if command_count < 2:
            missing_effects.append("two command_exit effects (coding + review)")
        if missing_effects:
            return False, "missing current-plan real effects: " + ", ".join(missing_effects)
        return True, "current-plan research/read/write/run/review evidence complete"

    def _fresh_workspace_preverification_evidence(
        self, event, root: WorkItem
    ) -> tuple[dict[str, Any] | None, str | None]:
        workspace_raw = str(event.payload.get("workspace_path") or "").strip()
        if not workspace_raw:
            return None, "E2E-25 final verification requires the attached workspace"
        try:
            workspace = Path(workspace_raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            return None, f"attached workspace is unavailable: {type(exc).__name__}: {exc}"

        writes = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
            and any(str(c).startswith("text_equals:") for c in item.acceptance_criteria)
        ]
        if not writes:
            return None, "E2E-25 final verification requires a completed workspace write"
        criterion = next(
            str(c)
            for c in reversed(writes[-1].acceptance_criteria)
            if str(c).startswith("text_equals:")
        )
        relative = criterion.split(":", 1)[1].strip()
        rel = Path(relative)
        if not relative or rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            return None, "completed workspace write lost its safe relative path"
        target = resolved_within(workspace, workspace / rel)
        if target is None or not target.is_file():
            return None, "completed workspace write no longer resolves to a regular workspace file"

        git_state = self.body.act("git_state", event_id=event.event_id, path=str(workspace))
        git_diff = self.body.act("git_diff", event_id=event.event_id, path=str(workspace))
        fresh_file = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=str(target),
            max_chars=50_000,
        )
        if not git_state.success:
            return None, "fresh Git state failed: " + str(git_state.error or "unknown error")
        if not git_diff.success:
            return None, "fresh Git diff failed: " + str(git_diff.error or "unknown error")
        if not fresh_file.success or not str(fresh_file.output or "").strip():
            return None, "fresh workspace file read failed before Root verification"
        diff_text = str(git_diff.output or "")
        normalized_relative = rel.as_posix()
        if normalized_relative not in diff_text and rel.name not in diff_text:
            return None, "fresh Git diff does not prove the declared workspace source changed"
        return {
            "workspace": str(workspace),
            "relative_path": normalized_relative,
            "git_state_chars": len(str(git_state.output or "")),
            "git_diff_chars": len(diff_text),
            "fresh_file_chars": len(str(fresh_file.output or "")),
            "captured_at": fresh_file.completed_at,
        }, None

    def _parse_verify_python_step(self, event, root: WorkItem, content: str):
        proposal = super()._parse_verify_python_step(event, root, content)
        if proposal is None or not self._is_current_api_docs_adaptation_root(root):
            return proposal
        complete, _reason = self._e2e25_required_phase_evidence(root)
        if not complete:
            return None
        return proposal

    def _begin_root_verification(self, event, state, root, increment, proposal):
        if not self._is_current_api_docs_adaptation_root(root):
            return super()._begin_root_verification(event, state, root, increment, proposal)
        complete, reason = self._e2e25_required_phase_evidence(root)
        if not complete:
            self._accept_borrowed_increment(event, state, increment)
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "E2E-25 Root verification rejected: " + reason,
            )
        evidence, failure = self._fresh_workspace_preverification_evidence(event, root)
        if failure is not None or evidence is None:
            self._accept_borrowed_increment(event, state, increment)
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "E2E-25 Root verification rejected: " + str(failure or "missing fresh workspace evidence"),
            )
        state.data[self._PREVERIFY_EVIDENCE_KEY] = evidence
        return super()._begin_root_verification(event, state, root, increment, proposal)

    @staticmethod
    def _expected_worker_schema(expected_action: str) -> dict[str, Any]:
        if expected_action == "research_current_page":
            return {
                "zn_work_step": {
                    "objective": "...",
                    "action": {"kind": "research_current_page"},
                    "acceptance": {"kind": "page_read_current_reference"},
                }
            }
        if expected_action == "read_workspace_file":
            return {
                "zn_work_step": {
                    "objective": "...",
                    "action": {"kind": "read_workspace_file", "path": "relative/path"},
                    "acceptance": {"kind": "file_read", "path": "same path"},
                }
            }
        return ApplicationAwareResidentRuntime._expected_worker_schema(expected_action)

    @staticmethod
    def _delegated_worker_instruction(executor_kind: str, expected_action: str) -> str:
        if expected_action == "research_current_page":
            return (
                " DELEGATED WORKER: research current page. Return ONLY research_current_page. "
                "Do not provide, infer, replace, or copy any URL; ZN owns resolution of the user's "
                "explicitly authorized current USER Browser reference. Do not request browser credentials, "
                "cookies, session state, workspace writes, Terminal execution, or Root acceptance."
            )
        if expected_action == "read_workspace_file":
            return (
                " DELEGATED WORKER: inspect existing workspace. Return ONLY read_workspace_file for one "
                "regular file from the provided bounded workspace_inventory. This step is read-only. "
                "Do not propose content, shell, writes, Git mutation, or Root acceptance."
            )
        return ApplicationAwareResidentRuntime._delegated_worker_instruction(
            executor_kind, expected_action
        )

    @staticmethod
    def _worker_objective(executor_kind: str, expected_action: str) -> str:
        if expected_action == "research_current_page":
            return "Read the API documentation currently referenced by the authorized USER Browser page"
        if expected_action == "read_workspace_file":
            return "Read the existing workspace source relevant to the documented API before changing it"
        return ApplicationAwareResidentRuntime._worker_objective(
            executor_kind, expected_action
        )

    def _scope_allows(self, worker, expected_action: str) -> bool:
        if expected_action == "research_current_page":
            return (
                worker.executor_kind == "research"
                and "managed_browser.read" in set(worker.tool_scope)
                and "web_read" in set(worker.authority_scope)
            )
        if expected_action == "read_workspace_file":
            return (
                worker.executor_kind == "coding"
                and "workspace.read" in set(worker.tool_scope)
                and "workspace_read" in set(worker.authority_scope)
            )
        return super()._scope_allows(worker, expected_action)

    def _parse_research_page_step(self, root: WorkItem, content: str):
        parsed = super()._parse_research_page_step(root, content)
        if parsed is not None:
            return parsed
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict) or set(step) != {
            "objective",
            "action",
            "acceptance",
        }:
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if (
            not objective
            or len(objective) > 600
            or not isinstance(action, dict)
            or not isinstance(acceptance, dict)
        ):
            return None
        if set(action) != {"kind"} or action.get("kind") != "research_current_page":
            return None
        if (
            set(acceptance) != {"kind"}
            or acceptance.get("kind") != "page_read_current_reference"
        ):
            return None
        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return None
        return {"objective": objective, "source_kind": "current_user_browser_page"}

    def _parse_read_workspace_file_step(
        self, event, root: WorkItem, content: str
    ):
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict) or set(step) != {
            "objective",
            "action",
            "acceptance",
        }:
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if (
            not objective
            or len(objective) > 600
            or not isinstance(action, dict)
            or not isinstance(acceptance, dict)
        ):
            return None
        if (
            set(action) != {"kind", "path"}
            or action.get("kind") != "read_workspace_file"
        ):
            return None
        if set(acceptance) != {"kind", "path"} or acceptance.get("kind") != "file_read":
            return None
        relative = str(action.get("path") or "").strip()
        if relative != str(acceptance.get("path") or "").strip():
            return None
        rel = Path(relative)
        if (
            not relative
            or rel.is_absolute()
            or not rel.parts
            or any(part in {"", ".", ".."} for part in rel.parts)
        ):
            return None
        if rel.parts[0].casefold() == ".git" or any(
            token in rel.name.casefold()
            for token in ("credential", "secret", "password", "token", ".env")
        ):
            return None
        workspace_raw = str(event.payload.get("workspace_path") or "").strip()
        if not workspace_raw:
            return None
        try:
            workspace = Path(workspace_raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        target = resolved_within(workspace, workspace / rel)
        if target is None or not target.is_file():
            return None
        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return None
        return {
            "objective": objective,
            "relative_path": rel.as_posix(),
            "absolute_path": str(target),
            "workspace": str(workspace),
        }

    def _proposal_contract_valid(
        self, event, root, expected_action: str, content: str
    ) -> bool:
        if expected_action == "research_current_page":
            return self._parse_research_page_step(root, content) is not None
        if expected_action == "read_workspace_file":
            return self._parse_read_workspace_file_step(event, root, content) is not None
        return super()._proposal_contract_valid(event, root, expected_action, content)

    def _proposal_contract_failure_reason(
        self, event, root, expected_action: str, content: str
    ) -> str:
        if expected_action == "research_current_page":
            return "current-page research requires the exact URL-free research_current_page/page_read_current_reference schema"
        if expected_action == "read_workspace_file":
            return "workspace inspection must name one current regular file inside the attached workspace with matching file_read acceptance"
        return super()._proposal_contract_failure_reason(
            event, root, expected_action, content
        )

    @staticmethod
    def _proposal_action_kind(content: str) -> str | None:
        raw = parse_exact_json_payload(content)
        if isinstance(raw, dict):
            step = raw.get("zn_work_step")
            if isinstance(step, dict) and isinstance(step.get("action"), dict):
                kind = str(step["action"].get("kind") or "").strip()
                if kind in {"research_current_page", "read_workspace_file"}:
                    return kind
        return ApplicationAwareResidentRuntime._proposal_action_kind(content)

    def _worker_authority_context(
        self, event, worker, expected_action: str
    ) -> ActionAuthorityContext:
        item = self.work_ledger._work_item_by_id(worker.work_item_id)
        if item is None or item.plan_version != worker.plan_version:
            raise PermissionError("WorkerRun lost its current WorkItem authority")
        if int(self.work_ledger.plan_version(item.work_thread_id)) != worker.plan_version:
            raise PermissionError("WorkerRun belongs to a stale Work plan")
        return ActionAuthorityContext(
            work_thread_id=item.work_thread_id,
            work_item_id=item.work_item_id,
            worker_run_id=worker.worker_run_id,
            plan_version=worker.plan_version,
            executor_kind=worker.executor_kind,
            expected_action=expected_action,
            tool_scope=tuple(worker.tool_scope),
            authority_scope=tuple(worker.authority_scope),
            workspace_root=str(event.payload.get("workspace_path") or "").strip()
            or None,
        )

    def _workspace_inventory_for_worker(self, event, worker) -> list[dict[str, Any]]:
        workspace = Path(str(event.payload.get("workspace_path") or "")).expanduser().resolve(strict=True)
        context = self._worker_authority_context(
            event, worker, "read_workspace_file"
        )
        args = bind_worker_authority_arg(
            {"path": str(workspace), "limit": self._MAX_WORKSPACE_INVENTORY},
            context,
        )
        result = self.body.act("list_directory", event_id=event.event_id, **args)
        if not result.success:
            raise RuntimeError(result.error or "workspace inventory failed")
        entries = []
        for raw in result.data.get("entries", [])[: self._MAX_WORKSPACE_INVENTORY]:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            kind = str(raw.get("type") or "").strip()
            if not name or name == ".git" or name.casefold().startswith(".env"):
                continue
            if any(
                token in name.casefold()
                for token in ("credential", "secret", "password", "token")
            ):
                continue
            candidate = resolved_within(workspace, workspace / name)
            if candidate is None:
                continue
            entries.append(
                {
                    "path": name,
                    "type": kind,
                    "size_bytes": max(0, int(raw.get("size_bytes") or 0)),
                }
            )
        return entries

    def _resolve_current_user_browser_page(self, event, state) -> dict[str, Any]:
        bound = self._ensure_user_browser_task_context(event, state)
        before = self.user_browser_extension.authorized_tab()
        if before is None:
            raise RuntimeError(
                "current-page research requires one explicitly authorized USER Browser tab"
            )
        fresh = self.probe_user_browser_extension_tab()
        after = self.user_browser_extension.authorized_tab()
        if after is None:
            raise RuntimeError(
                "USER Browser authorization disappeared while resolving current page"
            )
        if (
            int(before.tab_id) != int(bound["tab_id"])
            or str(before.attached_at) != str(bound["attached_at"])
            or int(after.tab_id) != int(bound["tab_id"])
            or str(after.attached_at) != str(bound["attached_at"])
            or int(fresh.get("tab_id") or 0) != int(bound["tab_id"])
        ):
            raise RuntimeError(
                "USER Browser authorization generation changed while resolving current page"
            )
        url = str(fresh.get("url") or "").strip()
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError as exc:
            raise RuntimeError("current USER Browser page has an invalid URL") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise RuntimeError(
                "current USER Browser page is not a safe HTTP(S) research reference"
            )
        origin = self._origin_url(url)
        if origin != str(bound.get("origin") or ""):
            raise RuntimeError(
                "current USER Browser page escaped the Work authorization origin"
            )
        reference = {
            "source_kind": "current_user_browser_page",
            "url": url,
            "origin": origin,
            "tab_id": int(bound["tab_id"]),
            "attached_at": str(bound["attached_at"]),
            "observed_at": utc_now(),
        }
        state.data[self._CURRENT_SOURCE_KEY] = reference
        return reference

    def _cognition_integration_step(
        self, event, state, *, readiness, thought=None
    ):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        delegated = self._delegated_meta_from_state(state)
        if (
            root is None
            or not isinstance(raw, dict)
            or not isinstance(delegated, dict)
        ):
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        increment = CognitiveIncrement.from_dict(raw)
        expected = str(delegated.get("expected_action") or "").strip()
        if expected == "research_current_page":
            proposal = self._parse_research_page_step(root, increment.content)
            if proposal is None:
                return super()._cognition_integration_step(
                    event, state, readiness=readiness, thought=thought
                )
            try:
                reference = self._resolve_current_user_browser_page(event, state)
            except Exception as exc:
                self._accept_borrowed_increment(event, state, increment)
                return self._return_to_investigation_after_rejection(
                    event,
                    state,
                    f"current-page reference resolution failed: {type(exc).__name__}: {exc}",
                )
            transformed = dict(raw)
            transformed["content"] = json.dumps(
                {
                    "zn_work_step": {
                        "objective": proposal["objective"],
                        "action": {
                            "kind": "research_page",
                            "url": reference["url"],
                        },
                        "acceptance": {
                            "kind": "page_read",
                            "url": reference["url"],
                        },
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            request = state.data.get("cognition_request")
            if isinstance(request, dict) and isinstance(request.get("context"), dict):
                meta = request["context"].get(self._DELEGATED_CONTEXT_KEY)
                if isinstance(meta, dict):
                    meta["expected_action"] = "research_page"
            state.data["cognitive_increment"] = transformed
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        if expected != "read_workspace_file":
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        proposal = self._parse_read_workspace_file_step(
            event, root, increment.content
        )
        if proposal is None:
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        worker_run_id = str(delegated.get("worker_run_id") or "").strip()
        worker = self.work_ledger.worker_run(worker_run_id)
        if (
            worker is None
            or worker.plan_version != root.plan_version
            or not self._scope_allows(worker, expected)
        ):
            self._accept_borrowed_increment(event, state, increment)
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "workspace read proposal lost current WorkerRun authority",
            )
        self._accept_borrowed_increment(event, state, increment)
        self.work_ledger.complete_worker_run(
            worker.worker_run_id,
            result_summary=increment.content,
            claimed_completion=self._claims_completion(increment.content),
            verification_status="scope_admitted",
            model_route_id=self._route_id_from_increment(increment),
            metrics={"source": increment.source, "increment_id": increment.increment_id},
        )
        state.data[self._DELEGATED_PENDING_KEY] = dict(delegated)
        identity = hashlib.sha256(
            f"{event.event_id}\0{increment.increment_id}\0workspace-read".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        effect = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[f'file_read: {proposal["relative_path"]}'],
        )
        self.work_ledger._save_item(effect)
        context = self._worker_authority_context(event, worker, expected)
        args = bind_worker_authority_arg(
            {
                "path": proposal["absolute_path"],
                "max_chars": self._MAX_WORKSPACE_READ_CHARS,
            },
            context,
        )
        result = self.body.act("read_text", event_id=event.event_id, **args)
        if not result.success:
            failure = result.error or "workspace read failed"
            effect.status = "blocked"
            effect.blocker = failure[:6000]
            effect.result = effect.blocker
            effect.updated_at = utc_now()
            self.work_ledger._save_item(effect)
            self._reject_delegated_execution_evidence(state, failure=failure)
            return self._return_to_investigation_after_rejection(
                event, state, failure
            )
        evidence = {
            "path": proposal["relative_path"],
            "text": str(result.output or "")[: self._MAX_WORKSPACE_READ_CHARS],
            "chars": int(result.data.get("chars") or 0),
            "returned_chars": int(result.data.get("returned_chars") or 0),
            "truncated": bool(result.data.get("truncated")),
            "captured_at": result.completed_at,
        }
        effect.status = "completed"
        effect.result = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        effect.completed_at = utc_now()
        effect.updated_at = effect.completed_at
        self.work_ledger._save_item(effect)
        state.data[self._WORKSPACE_READ_KEY] = {
            "plan_version": root.plan_version,
            **evidence,
        }
        self._accept_delegated_execution_evidence(
            state,
            effect_work_item_id=effect.work_item_id,
            result_summary=effect.result,
            artifact_refs=[
                {"kind": "workspace_file", "path": proposal["relative_path"]}
            ],
        )
        for key in (
            "cognitive_increment",
            "external_cognition_result",
            "cognition_integration",
            "cognition_request",
            "impasse_id",
        ):
            state.data.pop(key, None)
        state.data.pop("local_failure", None)
        state.stage = "native_deliberation"
        state.next_action = (
            "choose the smallest workspace change from fresh docs and existing source evidence"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

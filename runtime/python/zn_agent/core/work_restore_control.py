from __future__ import annotations

"""Explicit control-plane authority for Work restore, continuation, and steering."""

import hashlib
import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .evidence_bound_work import EvidenceBoundSteerableWorkLedger
from .models import utc_now
from .route_policy_intake import bind_work_event_route_policy
from .steerable_work import SteerableWorkLedger
from .work import WorkMessage
from .work_control import ResidentWorkControl


_CONTINUE = re.compile(r"(?:继续做|接着做|继续|接着)")
_BARE_CURRENT_CONTINUE = re.compile(
    r"^(?:那)?(?:继续(?:做)?|接着(?:做)?)(?:吧|一下)?[。！!？?]*$"
)
_INSPECTION_FOLLOWUPS = (
    re.compile(r"^(?:我)?先?看(?:看|一下)?(?:现在)?(?:做到哪(?:一步)?(?:了)?|进度|进展|什么情况)$"),
    re.compile(r"^先?告诉我(?:现在)?(?:做到哪(?:一步)?(?:了)?|进度|进展|什么情况)$"),
    re.compile(r"^(?:我)?先?看看?现在什么情况$"),
    re.compile(r"^(?:你)?(?:现在)?(?:做到哪(?:一步)?(?:了)?|进度|进展|什么情况)(?:了)?$"),
)
_LATEST_REFERENCE = ("刚才", "刚刚", "上次", "之前那个", "前面那个")
_YESTERDAY_REFERENCE = ("昨天", "昨日")
_STEERING_CUES = (
    "先别",
    "别做",
    "不要",
    "不做",
    "先把",
    "先做",
    "改成",
    "改简单",
    "简单一点",
    "简化",
    "暂停",
    "暂时不",
)
_CONTEXT_TASK_LIMIT = 500
_CONTEXT_RESULT_LIMIT = 500
_CONTEXT_FOLLOWUP_LIMIT = 1000
_INSPECTION_ITEM_LIMIT = 16
_INSPECTION_ARTIFACT_LIMIT = 4
_INSPECTION_TEXT_LIMIT = 800
_INSPECTION_ARTIFACT_READ_LIMIT = 50_000
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|secret|authorization)\b\s*[:=]\s*[^\s,;]+"
)
_SECRET_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b")


class RestoreAwareWorkControl(ResidentWorkControl):
    """Reconnect natural references to durable Work and steer explicit plan changes.

    Bare continuation reconnects to the exact active event. An explicit plan
    change such as ``登录先别做，先把核心记账跑起来`` increments the same Root
    Work's plan version and supersedes the old active plan. A bounded
    continuation inspection is a read-only status operation over that same Work;
    it never grants execution permission. Completed Work follow-ups still start
    a fresh event without replaying the completed event.
    """

    def __init__(self, ledger):
        # The daemon historically constructs RecoveryBoundedWorkLedger directly.
        # Upgrade that face onto the same resident/store rather than creating a
        # second Work product or scheduler. Both objects point at the same SQLite
        # truth; this control surface owns the steerable path immediately.
        if not isinstance(ledger, EvidenceBoundSteerableWorkLedger):
            ledger = EvidenceBoundSteerableWorkLedger(ledger.resident)
        super().__init__(ledger)
        self._continuation_ingress_aliases: dict[str, str] = {}

    @staticmethod
    def continuation_reference(task: str) -> str | None:
        normalized = " ".join(str(task or "").strip().split())
        if not normalized or _CONTINUE.search(normalized) is None:
            return None
        if any(cue in normalized for cue in _YESTERDAY_REFERENCE):
            return "yesterday"
        if any(cue in normalized for cue in _LATEST_REFERENCE):
            return "latest"
        return None

    @staticmethod
    def continuation_followup(task: str) -> str | None:
        normalized = " ".join(str(task or "").strip().split())
        match = _CONTINUE.search(normalized)
        if match is None:
            return None
        followup = normalized[match.end() :].lstrip(" ，,。；;:：-—\t")
        return followup or None

    @classmethod
    def continuation_inspection_followup(cls, task: str) -> str | None:
        """Recognize only an explicit continuation plus a narrow status query."""
        if cls.continuation_reference(task) is None:
            return None
        followup = cls.continuation_followup(task)
        if followup is None:
            return None
        normalized = re.sub(r"[。！!？?，,；;]+$", "", followup.strip())
        return normalized if any(pattern.fullmatch(normalized) for pattern in _INSPECTION_FOLLOWUPS) else None

    @staticmethod
    def active_inspection_task(task: str) -> str | None:
        """Recognize a same-thread progress question without changing the plan."""
        normalized = re.sub(
            r"[。！!？?，,；;]+$",
            "",
            " ".join(str(task or "").strip().split()),
        )
        if not normalized:
            return None
        return (
            normalized
            if any(pattern.fullmatch(normalized) for pattern in _INSPECTION_FOLLOWUPS)
            else None
        )

    @classmethod
    def active_steering_followup(cls, task: str) -> str | None:
        """Recognize explicit active-plan edits without treating every suffix as steering."""
        followup = cls.continuation_followup(task)
        if followup is None:
            return None
        return followup if any(cue in followup for cue in _STEERING_CUES) else None

    @staticmethod
    def _bare_current_continue(task: str) -> bool:
        normalized = " ".join(str(task or "").strip().split())
        return bool(normalized and _BARE_CURRENT_CONTINUE.fullmatch(normalized))

    def _latest_message_is_inspection(self, thread_id: str) -> bool:
        messages = self.ledger.list_messages(thread_id, limit=1)
        if not messages:
            return False
        latest = messages[-1]
        return bool(latest.role == "user" and latest.detail.get("inspection") is True)

    @staticmethod
    def _inspection_execution_options(kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        kind = str(options.pop("kind", "desktop_user_event") or "desktop_user_event")
        priority = int(options.pop("priority", 0) or 0)
        payload = options.pop("payload", None)
        if kind != "desktop_user_event":
            options["kind"] = kind
        if priority != 0:
            options["priority"] = priority
        if payload not in (None, {}):
            options["payload"] = payload
        return options

    def start(self, thread_id: str, task: str, **kwargs):
        reference = self.continuation_reference(task)
        if reference is None:
            normalized_thread = self.ledger._normalize_thread_id(thread_id)
            self.reconcile_cancelled_runs(thread_id=normalized_thread)
            current = self.ledger.get_thread(normalized_thread)
            active = (
                self.ledger._active_run_for_thread(normalized_thread)
                if current is not None
                else None
            )

            if active is not None and not self._bare_current_continue(task):
                inspection = self.active_inspection_task(task)
                if inspection is not None:
                    execution_options = self._inspection_execution_options(kwargs)
                    if execution_options:
                        raise ValueError(
                            "active Work inspection is read-only and does not accept execution options"
                        )
                    return self._inspect_referenced_work(
                        current,
                        active,
                        task,
                        reference="current",
                        ingress_thread_id=normalized_thread,
                    )

                # A new message sent inside the same active conversation is
                # steering by product semantics. Do not require users to prefix
                # ordinary corrections with "继续". The durable steer path still
                # owns plan versioning, fresh re-sense, stale-result rejection
                # and Body safety.
                return self._steer_referenced_active_work(
                    current,
                    active,
                    task,
                    followup=" ".join(str(task or "").strip().split()),
                    reference="current",
                    ingress_thread_id=normalized_thread,
                    start_kwargs=kwargs,
                )

            # ``继续`` is intentionally admitted only after a durable inspection
            # message on this exact thread. This keeps the new behavior bounded
            # and lets a restart preserve the status-first -> resume sequence
            # without relying on the in-memory ingress alias helper.
            if self._bare_current_continue(task):
                if current is not None and self._latest_message_is_inspection(normalized_thread):
                    if active is None:
                        raise ValueError(
                            "the inspected Work is already complete; say what should happen next so ZN can form a fresh task instead of replaying the completed event"
                        )
                    return self._resume_referenced_active_work(
                        current,
                        active,
                        task,
                        reference="current",
                        ingress_thread_id=normalized_thread,
                    )
            return super().start(thread_id, task, **kwargs)

        self.reconcile_cancelled_runs()
        thread = self._referenced_thread(reference)
        active = self.ledger._active_run_for_thread(thread.thread_id)
        inspection = self.continuation_inspection_followup(task)
        if inspection is not None:
            execution_options = self._inspection_execution_options(kwargs)
            if execution_options:
                raise ValueError("continuation inspection is read-only and does not accept execution options")
            inspected_run = active or self._latest_completed_run(thread.thread_id)
            if inspected_run is None:
                raise ValueError("the referenced Work has no durable resident event to inspect")
            return self._inspect_referenced_work(
                thread,
                inspected_run,
                task,
                reference=reference,
                ingress_thread_id=thread_id,
            )

        followup = self.continuation_followup(task)
        if active is not None:
            steering = self.active_steering_followup(task)
            if steering is not None:
                return self._steer_referenced_active_work(
                    thread,
                    active,
                    task,
                    followup=steering,
                    reference=reference,
                    ingress_thread_id=thread_id,
                    start_kwargs=kwargs,
                )
            if followup is not None:
                raise ValueError(
                    "the referenced Work is still active; the new instruction is not an explicit plan change, so ZN will not silently reinterpret or drop it"
                )
            return self._resume_referenced_active_work(
                thread,
                active,
                task,
                reference=reference,
                ingress_thread_id=thread_id,
            )

        if followup is None:
            raise ValueError(
                "the referenced Work is already complete; say what should happen next so ZN can form a fresh task instead of replaying the completed event"
            )
        return self._start_referenced_completed_followup(
            thread,
            task,
            followup=followup,
            reference=reference,
            ingress_thread_id=thread_id,
            start_kwargs=kwargs,
        )

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_event = str(event_id or "").strip()
        work_run = self.ledger.get_run(normalized_event)
        if work_run is not None and work_run.thread_id != normalized_thread:
            alias = self._continuation_ingress_aliases.get(normalized_event)
            if alias == normalized_thread:
                progress = super().progress(work_run.thread_id, normalized_event)
                return self._with_continuation_inspection(
                    work_run.thread_id,
                    normalized_event,
                    progress,
                )
        progress = super().progress(normalized_thread, normalized_event)
        return self._with_continuation_inspection(
            normalized_thread,
            normalized_event,
            progress,
        )

    def _with_continuation_inspection(
        self,
        thread_id: str,
        event_id: str,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        messages = self.ledger.list_messages(thread_id, limit=1)
        if not messages:
            return progress
        latest = messages[-1]
        detail = latest.detail if latest.role == "user" else {}
        if (
            detail.get("inspection") is not True
            or str(detail.get("inspected_event_id") or "") != event_id
        ):
            return progress
        projection = self._continuation_inspection_projection(
            thread_id,
            event_id,
            progress,
        )
        projection["reference"] = str(detail.get("reference") or "continuation")
        progress["continuation_inspection"] = projection
        artifact_summary = ", ".join(
            f"{item.get('path') or item.get('name')}={item.get('current', {}).get('status', 'unknown')}"
            for item in projection.get("artifacts", [])[:_INSPECTION_ARTIFACT_LIMIT]
        )
        summary = (
            f"Current Work: {projection['root_goal']} · plan v{projection['plan_version']} · "
            f"completed {len(projection['completed'])}, active {len(projection['active'])}, "
            f"blocked {len(projection['blocked'])} · "
            f"fresh environment {'changed' if projection['drift_detected'] else 'checked'}"
        )
        if artifact_summary:
            summary += f" · artifacts {artifact_summary}"
        summary += " · inspection only; execution was not resumed"
        progress["stage"] = "inspection_complete"
        progress["next_action"] = self._public_text(summary, limit=1400)
        return progress

    def _inspect_referenced_work(
        self,
        thread,
        run,
        task: str,
        *,
        reference: str,
        ingress_thread_id: str,
    ):
        event = self.resident.store.get_event(run.event_id)
        if event is None:
            raise RuntimeError("referenced Work lost its durable resident event")

        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[run.event_id] = normalized_ingress

        self.ledger._append(
            thread,
            WorkMessage(
                message_id=f"msg-{uuid.uuid4().hex[:16]}",
                thread_id=thread.thread_id,
                role="user",
                text=" ".join(str(task or "").strip().split()),
                detail={
                    "continuation": True,
                    "inspection": True,
                    "reference": reference,
                    "inspected_event_id": run.event_id,
                    "new_resident_event": False,
                    "execution_permission": False,
                },
            ),
        )
        return self.get_snapshot(thread.thread_id), event

    @classmethod
    def _public_text(cls, value: Any, *, limit: int = _INSPECTION_TEXT_LIMIT) -> str:
        text = " ".join(str(value or "").strip().split())
        text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", text)
        text = _SECRET_TOKEN.sub("<redacted>", text)
        return text[: max(0, int(limit))]

    @staticmethod
    def _contained_relative(workspace: Path, target: Path) -> str | None:
        try:
            return target.resolve(strict=False).relative_to(workspace.resolve(strict=False)).as_posix()
        except (OSError, RuntimeError, ValueError):
            return None

    def _artifact_target(self, workspace: Path, artifact) -> tuple[Path, str] | None:
        relative = str(artifact.metadata.get("workspace_relative_path") or "").strip()
        if relative:
            candidate = (workspace / relative).resolve(strict=False)
            contained = self._contained_relative(workspace, candidate)
            if contained is None:
                return None
            return candidate, contained
        path = str(artifact.path or "").strip()
        if not path:
            return None
        candidate = Path(path).expanduser().resolve(strict=False)
        contained = self._contained_relative(workspace, candidate)
        if contained is None:
            return None
        return candidate, contained

    def _inspect_artifacts(
        self,
        thread_id: str,
        event_id: str,
        workspace: Path,
        *,
        workspace_present: bool,
    ) -> tuple[list[dict[str, Any]], bool]:
        selected: list[tuple[Any, Path, str]] = []
        seen: set[str] = set()
        for artifact in self.ledger.list_artifacts(thread_id, limit=32):
            if str(artifact.kind or "") != "file":
                continue
            target = self._artifact_target(workspace, artifact)
            if target is None:
                continue
            candidate, relative = target
            key = relative.casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append((artifact, candidate, relative))
            if len(selected) >= _INSPECTION_ARTIFACT_LIMIT:
                break

        result: list[dict[str, Any]] = []
        drift = False
        for artifact, candidate, relative in selected:
            historical = {
                "status": "recorded",
                "recorded_at": str(artifact.created_at),
            }
            current: dict[str, Any]
            if not workspace_present:
                current = {
                    "status": "workspace_missing",
                    "observed_at": utc_now(),
                }
                drift = True
            else:
                observed = self.resident.body.act(
                    "inspect_path",
                    event_id=event_id,
                    path=str(candidate),
                )
                observed_at = str(observed.completed_at)
                if not observed.success:
                    current = {"status": "unavailable", "observed_at": observed_at}
                    drift = True
                elif not bool(observed.data.get("exists")):
                    current = {"status": "missing", "observed_at": observed_at}
                    drift = True
                elif str(observed.data.get("type") or "") != "file":
                    current = {"status": "type_changed", "observed_at": observed_at}
                    drift = True
                else:
                    read = self.resident.body.act(
                        "read_text",
                        event_id=event_id,
                        path=str(candidate),
                        max_chars=_INSPECTION_ARTIFACT_READ_LIMIT,
                    )
                    read_at = str(read.completed_at)
                    historical_complete = artifact.metadata.get("truncated") is not True
                    current_complete = read.success and read.data.get("truncated") is not True
                    if historical_complete and current_complete:
                        historical_hash = hashlib.sha256(
                            str(artifact.content or "").encode("utf-8", errors="replace")
                        ).hexdigest()
                        current_hash = hashlib.sha256(
                            str(read.output or "").encode("utf-8", errors="replace")
                        ).hexdigest()
                        matches = historical_hash == current_hash
                        current = {
                            "status": "unchanged" if matches else "modified",
                            "observed_at": read_at,
                            "matches_historical": matches,
                        }
                        drift = drift or not matches
                    else:
                        current = {
                            "status": "present" if read.success else "unreadable",
                            "observed_at": read_at,
                            "matches_historical": None,
                        }
                        drift = drift or not read.success
            result.append(
                {
                    "name": self._public_text(artifact.name, limit=160),
                    "kind": "file",
                    "path": relative,
                    "historical": historical,
                    "current": current,
                }
            )
        return result, drift

    def _current_environment_projection(
        self,
        thread_id: str,
        event_id: str,
        thread,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        workspace_ref = self.ledger.workspace_for(thread)
        if workspace_ref is None:
            return (
                {
                    "workspace_attached": False,
                    "workspace_present": False,
                    "git": None,
                    "inspected_at": utc_now(),
                },
                [],
                False,
            )

        workspace = Path(workspace_ref.path).expanduser().resolve(strict=False)
        observed = self.resident.body.act(
            "inspect_path",
            event_id=event_id,
            path=str(workspace),
        )
        workspace_present = bool(
            observed.success
            and observed.data.get("exists") is True
            and observed.data.get("type") == "directory"
        )
        environment: dict[str, Any] = {
            "workspace_attached": True,
            "workspace_name": self._public_text(workspace_ref.name, limit=160),
            "workspace_present": workspace_present,
            "workspace_observed_at": str(observed.completed_at),
            "git": None,
        }
        drift = not workspace_present

        if workspace_present:
            git = self.resident.body.act(
                "git_state",
                event_id=event_id,
                path=str(workspace),
                limit=64,
            )
            if git.success:
                git_root = Path(str(git.data.get("root") or "")).resolve(strict=False)
                relation = (
                    "workspace_root"
                    if git_root == workspace
                    else "workspace_within_repo"
                    if self._contained_relative(git_root, workspace) is not None
                    else "unexpected_root"
                )
                if relation == "unexpected_root":
                    drift = True
                environment["git"] = {
                    "is_repository": True,
                    "branch": self._public_text(git.data.get("branch"), limit=120),
                    "head": self._public_text(git.data.get("head_short"), limit=32),
                    "dirty": bool(git.data.get("dirty")),
                    "changed_files": max(0, int(git.data.get("changed_files") or 0)),
                    "workspace_relation": relation,
                    "observed_at": str(git.completed_at),
                }
            else:
                environment["git"] = {
                    "is_repository": False,
                    "observed_at": str(git.completed_at),
                }

        artifacts, artifact_drift = self._inspect_artifacts(
            thread_id,
            event_id,
            workspace,
            workspace_present=workspace_present,
        )
        drift = drift or artifact_drift
        environment["drift_detected"] = drift
        environment["inspected_at"] = utc_now()
        return environment, artifacts, drift

    def _continuation_inspection_projection(
        self,
        thread_id: str,
        event_id: str,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        thread = self.ledger.get_thread(thread_id)
        if thread is None:
            raise RuntimeError("continuation inspection lost its durable WorkThread")
        plan_version = int(self.ledger.plan_version(thread_id))
        items = self.ledger.list_work_items(thread_id, limit=256)
        current = [item for item in items if item.plan_version == plan_version]
        roots = [item for item in current if item.parent_work_item_id is None]
        if len(roots) != 1:
            raise RuntimeError("continuation inspection requires one exact current Root WorkItem")
        root = roots[0]
        children = [item for item in current if item.parent_work_item_id == root.work_item_id]
        children = children[:_INSPECTION_ITEM_LIMIT]

        def item_view(item) -> dict[str, Any]:
            result = {
                "title": self._public_text(item.title, limit=240),
                "objective": self._public_text(item.objective, limit=500),
                "status": str(item.status),
                "updated_at": str(item.updated_at),
            }
            if item.completed_at:
                result["completed_at"] = str(item.completed_at)
            if item.blocker:
                result["blocker"] = self._public_text(item.blocker, limit=600)
            return result

        completed = [item_view(item) for item in children if item.status == "completed"]
        active = [
            item_view(item)
            for item in children
            if item.status in {"proposed", "ready", "running"}
        ]
        blocked = [item_view(item) for item in children if item.status == "blocked"]
        blockers = [
            {
                "title": view["title"],
                "historical": view.get("blocker") or "blocked in durable Work truth",
                "current_status": "not_reprobed",
            }
            for view in blocked
        ]
        if root.blocker:
            blockers.insert(
                0,
                {
                    "title": self._public_text(root.title, limit=240),
                    "historical": self._public_text(root.blocker, limit=600),
                    "current_status": "not_reprobed",
                },
            )
        blockers = blockers[:_INSPECTION_ITEM_LIMIT]

        environment, artifacts, drift = self._current_environment_projection(
            thread_id,
            event_id,
            thread,
        )
        updated_values = [str(item.updated_at) for item in current if item.updated_at]
        projection: dict[str, Any] = {
            "mode": "continuation_inspection",
            "read_only": True,
            "inspection_complete": True,
            "reference": "continuation",
            "work_status": str(root.status),
            "root_goal": self._public_text(root.objective, limit=800),
            "plan_version": plan_version,
            "plan": [item_view(item) for item in children],
            "completed": completed,
            "active": active,
            "blocked": blocked,
            "blockers": blockers,
            "artifacts": artifacts,
            "environment": environment,
            "drift_detected": drift,
            "last_durable_progress_at": max(updated_values) if updated_values else str(root.updated_at),
            "inspected_at": str(environment.get("inspected_at") or utc_now()),
        }
        delegation = progress.get("delegation")
        if isinstance(delegation, dict):
            projection["delegation"] = delegation
        return projection

    def _resume_referenced_active_work(
        self,
        thread,
        active,
        task: str,
        *,
        reference: str,
        ingress_thread_id: str,
    ):
        progress = super().progress(thread.thread_id, active.event_id)
        if progress.get("terminal") or progress.get("finalized"):
            raise ValueError(
                "the referenced Work has already reached a durable terminal outcome; ZN will not reinterpret 'continue' as permission to repeat it"
            )

        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[active.event_id] = normalized_ingress

        self.ledger._append(
            thread,
            WorkMessage(
                message_id=f"msg-{uuid.uuid4().hex[:16]}",
                thread_id=thread.thread_id,
                role="user",
                text=" ".join(str(task or "").strip().split()),
                detail={
                    "continuation": True,
                    "reference": reference,
                    "resumed_event_id": active.event_id,
                    "new_resident_event": False,
                },
            ),
        )
        event = self.resident.store.get_event(active.event_id)
        if event is None:
            raise RuntimeError("referenced active Work lost its durable resident event")
        return self.get_snapshot(thread.thread_id), event

    def _steer_referenced_active_work(
        self,
        thread,
        active,
        task: str,
        *,
        followup: str,
        reference: str,
        ingress_thread_id: str,
        start_kwargs: dict[str, Any],
    ):
        kwargs = dict(start_kwargs)
        raw_payload = kwargs.pop("payload", None)
        if raw_payload is not None and not isinstance(raw_payload, dict):
            raise ValueError("work steering payload must be an object")
        kind = str(kwargs.pop("kind", "desktop_user_event") or "desktop_user_event")
        priority = int(kwargs.pop("priority", 0) or 0)
        if kwargs:
            raise TypeError(
                f"unsupported Work steering options: {', '.join(sorted(kwargs))}"
            )

        bounded_followup = self._bounded_context_text(
            followup,
            limit=_CONTEXT_FOLLOWUP_LIMIT,
        )
        payload = dict(raw_payload or {})

        # Steering creates the next ResidentEvent through the plan transition
        # path rather than ordinary Work.start(). Preserve the same Work-owned
        # privacy boundary before that event can be materialized: first reject
        # an already-unsteerable live state, then validate/merge durable thread
        # policy and copy it into the exact next-event payload. The ledger still
        # repeats its own state check and owns the atomic plan transition.
        self.ledger._assert_steerable_resident_state(active.event_id)
        durable_thread = self.ledger.get_thread(thread.thread_id)
        if durable_thread is None:
            raise RuntimeError("active Work steering lost its durable WorkThread")
        bind_work_event_route_policy(
            self.ledger,
            durable_thread,
            task=task,
            event_payload=payload,
        )

        snapshot, event = self.ledger.steer_active(
            thread.thread_id,
            active.event_id,
            task,
            objective=bounded_followup,
            reference=reference,
            kind=kind,
            priority=priority,
            payload=payload,
        )
        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[event.event_id] = normalized_ingress
        return snapshot, event

    def _start_referenced_completed_followup(
        self,
        thread,
        task: str,
        *,
        followup: str,
        reference: str,
        ingress_thread_id: str,
        start_kwargs: dict[str, Any],
    ):
        previous = self._latest_completed_run(thread.thread_id)
        if previous is None:
            raise ValueError("the referenced Work has no completed resident event to continue from")
        previous_event = self.resident.store.get_event(previous.event_id)
        if previous_event is None:
            raise RuntimeError("referenced completed Work lost its durable resident event")
        previous_outcome = self.resident.store.get_event_outcome(previous.event_id)
        if previous_outcome is None:
            raise RuntimeError("referenced completed Work lost its durable terminal outcome")

        previous_task = self._bounded_context_text(
            previous_event.task,
            limit=_CONTEXT_TASK_LIMIT,
        )
        previous_result = self._bounded_context_text(
            previous_outcome.response or previous_outcome.reason,
            limit=_CONTEXT_RESULT_LIMIT,
        )
        bounded_followup = self._bounded_context_text(
            followup,
            limit=_CONTEXT_FOLLOWUP_LIMIT,
        )

        kwargs = dict(start_kwargs)
        raw_payload = kwargs.get("payload")
        if raw_payload is not None and not isinstance(raw_payload, dict):
            raise ValueError("work continuation payload must be an object")
        payload = dict(raw_payload or {})
        if "work_continuation" in payload:
            raise ValueError("work_continuation is resident-owned continuation metadata")

        payload["work_continuation"] = {
            "mode": "completed_followup",
            "reference": reference,
            "previous_event_id": previous.event_id,
            "previous_event_status": str(previous_event.status.value),
            "previous_task_excerpt": previous_task,
            "previous_outcome_success": bool(previous_outcome.success),
            "previous_execution_path": str(previous_outcome.execution_path.value),
            "previous_result_excerpt": previous_result,
            "followup": bounded_followup,
            "requires_fresh_resense": True,
            "replay_previous_event": False,
        }
        payload["cognition_question"] = self._continuation_cognition_question(
            previous_task=previous_task,
            previous_result=previous_result,
            previous_success=bool(previous_outcome.success),
            previous_execution_path=str(previous_outcome.execution_path.value),
            followup=bounded_followup,
            explicit_question=self._bounded_context_text(
                payload.get("cognition_question") or payload.get("unknown"),
                limit=_CONTEXT_FOLLOWUP_LIMIT,
            ),
        )
        kwargs["payload"] = payload

        snapshot, event = super().start(thread.thread_id, task, **kwargs)
        if event.event_id == previous.event_id:
            raise RuntimeError("completed Work continuation unexpectedly reused a terminal event")
        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[event.event_id] = normalized_ingress
        return snapshot, event

    def _latest_completed_run(self, thread_id: str):
        normalized = self.ledger._normalize_thread_id(thread_id)
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM work_runs WHERE thread_id=? AND ledger_state='finalized' ORDER BY created_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        return self.ledger._run_from_row(row) if row is not None else None

    def _referenced_thread(self, reference: str):
        candidates = [
            thread
            for thread in self.ledger.list_threads(limit=100)
            if self.ledger.list_messages(thread.thread_id, limit=1)
        ]
        if reference == "latest":
            if not candidates:
                raise ValueError("there is no previous Work to continue")
            return candidates[0]

        if reference != "yesterday":
            raise ValueError("unsupported Work continuation reference")
        local_now = datetime.now().astimezone()
        expected = local_now.date() - timedelta(days=1)
        yesterday = [
            thread
            for thread in candidates
            if self._local_date(thread.updated_at, local_now.tzinfo) == expected
        ]
        if not yesterday:
            raise ValueError("there is no durable Work from yesterday to continue")
        if len(yesterday) != 1:
            raise ValueError(
                "more than one durable Work thread matches yesterday; ZN will not guess which one the user meant"
            )
        return yesterday[0]

    @staticmethod
    def _bounded_context_text(value: Any, *, limit: int) -> str:
        text = " ".join(str(value or "").strip().split())
        return text[: max(0, int(limit))]

    @classmethod
    def _continuation_cognition_question(
        cls,
        *,
        previous_task: str,
        previous_result: str,
        previous_success: bool,
        previous_execution_path: str,
        followup: str,
        explicit_question: str,
    ) -> str:
        historical_result = previous_result or (
            "the previous Work reached a successful terminal outcome"
            if previous_success
            else "the previous Work reached a failed terminal outcome"
        )
        current_question = explicit_question or followup
        return (
            "Continue the same durable Work with a fresh follow-up objective. "
            f"Historical prior task, context only: {previous_task}. "
            f"Historical terminal result, context only: success={str(previous_success).lower()}, "
            f"execution_path={previous_execution_path}, result={historical_result}. "
            f"New objective: {followup}. "
            f"Current isolated question: {current_question}. "
            "Treat all prior task/result information as historical context, not current-world fact. "
            "Re-sense the current computer, workspace, browser or application state before acting. "
            "Do not repeat any previous side effect merely because it happened before; replay of the previous event is forbidden."
        )

    @staticmethod
    def _local_date(value: str, local_tz):
        try:
            observed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(local_tz).date()

    def prepare_missing_restore(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_point = str(restore_point_id or "").strip()
        if not normalized_point:
            raise ValueError("missing-file restore preparation requires restore_point_id")
        prepare = getattr(self.resident, "prepare_missing_work_restore", None)
        if not callable(prepare):
            raise RuntimeError("resident does not support Work restore application")
        return prepare(normalized_thread, normalized_point)

    def approve_missing_restore(
        self,
        thread_id: str,
        application_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("missing-file restore approval requires application_id")
        approve = getattr(self.resident, "approve_missing_work_restore", None)
        if not callable(approve):
            raise RuntimeError("resident does not support Work restore application")
        return approve(normalized_thread, normalized_application)

    def restore_application(self, application_id: str) -> dict[str, Any]:
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("restore application inspection requires application_id")
        inspect = getattr(self.resident, "inspect_work_restore_application", None)
        if not callable(inspect):
            raise RuntimeError("resident does not support Work restore application")
        return inspect(normalized_application)

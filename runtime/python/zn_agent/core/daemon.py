from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Sequence, TextIO

from .error_safety import public_exception_text
from .mcp_read_capability_host import ApprovedMcpReadProvider, McpReadCapabilityHost
from .stdio_mcp import StdioMcpClient
from .outcome_aware_work_control import OutcomeAwareRestoreWorkControl
from .provider_bridge import build_resident_runtime_from_existing_stack
from .provider_settings import ProviderSettingsService
from .recovery_bounded_work import RecoveryBoundedWorkLedger
from .recovery_control import ResidentRecoveryRequired
from .service import ResidentService
from .project_team import assemble_team
from .team_memory import team_shared_memory
from .team_request import parse_team_request
from .team_timeline import (
    build_team_timeline,
    parse_team_role,
    record_assignee_override,
)
from .team_work_owner import TEAM_SPEC_KEY
from .team_runner import TeamRunner


class ResidentRpcServer:
    """Newline-delimited JSON-RPC over stdio for the Electron host.

    The RPC pipe is only a face/control surface. ZN's life loop runs on its own
    background thread, so an idle UI does not mean an idle or recreated self.
    Slower outside-world perception has its own rhythm and cannot stall the
    resident heartbeat/thought loop.
    """

    def __init__(
        self,
        resident=None,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        life_interval: float = 2.0,
        provider_settings: ProviderSettingsService | None = None,
        mcp_approvals: Sequence[ApprovedMcpReadProvider] = (),
        mcp_client_factory: Callable[..., Any] = StdioMcpClient,
    ):
        self.resident = resident or build_resident_runtime_from_existing_stack()
        self.service = ResidentService(self.resident)
        self.work = RecoveryBoundedWorkLedger(self.resident)
        # Local import: keeps the suggestions wiring in its own merge hunk
        # (P1-3 precedent) instead of the shared top-level import block.
        from .suggestions import SuggestionEngine

        self.suggestions = SuggestionEngine(self.resident, self.work)
        self.work_control = OutcomeAwareRestoreWorkControl(self.work)
        self.resident.cognitive_delta_handler = self.work.publish_response_delta
        self.resident.cognitive_response_reset_handler = self.work.reset_response_stream
        self.provider_settings = provider_settings or ProviderSettingsService(self.resident)
        # No plugin starts automatically. Only trusted host-approved entries can
        # be explicitly connected. All effects still go through this Body.
        self.mcp_capabilities = McpReadCapabilityHost(
            self.resident, approvals=mcp_approvals, client_factory=mcp_client_factory,
        )
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self.life_interval = max(0.25, float(life_interval))
        self._shutdown = False
        self._life_stop = threading.Event()
        self._life_thread: threading.Thread | None = None
        self._world_thread: threading.Thread | None = None
        self._fatal_life_error_handler: Callable[[BaseException], None] | None = None

    def serve_forever(self) -> int:
        self.service.acquire()
        self.resident.live_once()
        self._start_life_loop()
        self._write({"type": "ready", "status": self.resident.status()})
        try:
            for line in self.input:
                if self._shutdown:
                    break
                line = line.strip()
                if not line:
                    continue
                request: dict[str, Any] | None = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    response = self.handle(request)
                except Exception as exc:
                    request_id = request.get("id") if isinstance(request, dict) else None
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": public_exception_text(exc),
                    }
                self._write(response)
        finally:
            self._stop_life_loop()
            self.mcp_capabilities.close()
            self.service.release()
            try:
                self.resident.store.close()
            except Exception:
                pass
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = str(request.get("method") or "").strip()
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        if method == "ping":
            result: Any = {
                "alive": True,
                "pulse_count": self.resident.life.snapshot().pulse_count,
            }
        elif method == "status":
            result = self.resident.status()
        elif method == "self":
            result = self.resident.life.snapshot_dict()
        elif method == "provider_settings":
            result = self.provider_settings.snapshot()
        elif method == "provider_settings_update":
            result = self.provider_settings.update(params)
        elif method == "mcp_capabilities":
            if params:
                raise ValueError("mcp_capabilities accepts no execution parameters")
            result = self.mcp_capabilities.catalog()
        elif method == "mcp_connect":
            if set(params) != {"provider_id"}:
                raise ValueError("mcp_connect accepts only a preapproved provider_id")
            provider_id = str(params.get("provider_id") or "").strip()
            if not provider_id:
                raise ValueError("mcp_connect requires provider_id")
            result = self.mcp_capabilities.connect(provider_id)
        elif method == "mcp_disconnect":
            if set(params) != {"provider_id"}:
                raise ValueError("mcp_disconnect accepts only a preapproved provider_id")
            provider_id = str(params.get("provider_id") or "").strip()
            if not provider_id:
                raise ValueError("mcp_disconnect requires provider_id")
            result = self.mcp_capabilities.disconnect(provider_id)
        elif method == "suggestions_list":
            result = self.suggestions.list_suggestions(
                limit=max(1, min(50, int(params.get("limit") or 8))),
            )
        elif method == "suggestions_dismiss":
            key = str(params.get("key") or params.get("suggestion_key") or "").strip()
            if not key:
                raise ValueError("suggestions_dismiss requires key")
            result = self.suggestions.dismiss(key)
        elif method == "work_list":
            result = [
                self._work_snapshot(snapshot, artifact_limit=1)
                for snapshot in self.work_control.list_snapshots(
                    thread_limit=max(1, min(100, int(params.get("limit") or 24))),
                    message_limit=max(
                        1, min(500, int(params.get("message_limit") or 120))
                    ),
                )
            ]
        elif method == "work_create":
            metadata = params.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("work_create metadata must be an object")
            thread = self.work.create_thread(
                thread_id=str(params.get("thread_id") or "").strip() or None,
                title=str(params.get("title") or "New work"),
                metadata=metadata,
            )
            result = self._work_snapshot((thread, []), artifact_limit=0)
        elif method == "work_get":
            thread_id = str(params.get("thread_id") or "").strip()
            if not thread_id:
                raise ValueError("work_get requires thread_id")
            result = self._work_snapshot(
                self.work_control.get_snapshot(
                    thread_id,
                    message_limit=max(
                        1, min(500, int(params.get("message_limit") or 120))
                    ),
                )
            )
        elif method == "work_attach_workspace":
            thread_id = str(params.get("thread_id") or "").strip()
            workspace_path = str(params.get("workspace_path") or "").strip()
            if not thread_id:
                raise ValueError("work_attach_workspace requires thread_id")
            if not workspace_path:
                raise ValueError("work_attach_workspace requires workspace_path")
            thread = self.work.attach_workspace(
                thread_id,
                workspace_path,
                name=str(params.get("workspace_name") or "").strip() or None,
            )
            result = self._work_snapshot(
                self.work_control.get_snapshot(
                    thread.thread_id,
                    message_limit=max(
                        1, min(500, int(params.get("message_limit") or 120))
                    ),
                )
            )
        elif method == "work_detach_workspace":
            thread_id = str(params.get("thread_id") or "").strip()
            if not thread_id:
                raise ValueError("work_detach_workspace requires thread_id")
            thread = self.work.detach_workspace(thread_id)
            result = self._work_snapshot(
                self.work_control.get_snapshot(
                    thread.thread_id,
                    message_limit=max(
                        1, min(500, int(params.get("message_limit") or 120))
                    ),
                )
            )
        elif method == "work_start":
            thread_id = str(params.get("thread_id") or "").strip()
            task = str(params.get("task") or "").strip()
            if not thread_id:
                raise ValueError("work_start requires thread_id")
            if not task:
                raise ValueError("work_start requires task")
            payload = params.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise ValueError("work_start payload must be an object")
            payload = dict(payload or {})
            # Team entry: a user sentence asking for a team becomes durable
            # resident-owned ingress metadata (like work_plan_version), so
            # the resident's team driver picks it up instead of the generic
            # agent loop swallowing it as free text. A caller-supplied
            # team_request is never trusted -- the parse owns it.
            payload.pop("team_request", None)
            team_request = parse_team_request(task)
            if team_request is not None:
                payload["team_request"] = {
                    "project_title": team_request.project_title,
                    "role_keys": list(team_request.role_keys),
                }
            snapshot, event = self.work_control.start(
                thread_id,
                task,
                kind=str(params.get("kind") or "desktop_user_event"),
                priority=int(params.get("priority") or 0),
                payload=payload,
            )
            progress = self.work_control.progress(thread_id, event.event_id)
            if progress.get("finalized"):
                snapshot = self.work_control.get_snapshot(thread_id)
            result = {
                "thread": self._work_snapshot(snapshot),
                "progress": progress,
            }
        elif method == "work_progress":
            thread_id = str(params.get("thread_id") or "").strip()
            event_id = str(params.get("event_id") or "").strip()
            if not thread_id:
                raise ValueError("work_progress requires thread_id")
            if not event_id:
                raise ValueError("work_progress requires event_id")
            progress = self.work_control.progress(thread_id, event_id)
            result = {"progress": progress}
            if progress.get("finalized"):
                result["thread"] = self._work_snapshot(
                    self.work_control.get_snapshot(
                        thread_id,
                        message_limit=max(
                            1, min(500, int(params.get("message_limit") or 120))
                        ),
                    )
                )
        elif method == "work_resolve_uncertain":
            thread_id = str(params.get("thread_id") or "").strip()
            event_id = str(params.get("event_id") or "").strip()
            attempt_id = str(params.get("attempt_id") or "").strip()
            decision = str(params.get("decision") or "").strip().lower()
            if not thread_id:
                raise ValueError("work_resolve_uncertain requires thread_id")
            if not event_id:
                raise ValueError("work_resolve_uncertain requires event_id")
            if not attempt_id:
                raise ValueError("work_resolve_uncertain requires attempt_id")
            progress = self.work_control.resolve_uncertain(
                thread_id,
                event_id,
                attempt_id=attempt_id,
                decision=decision,
            )
            result = {"progress": progress}
            if progress.get("finalized"):
                result["thread"] = self._work_snapshot(
                    self.work_control.get_snapshot(
                        thread_id,
                        message_limit=max(
                            1, min(500, int(params.get("message_limit") or 120))
                        ),
                    )
                )
        elif method == "work_cancel":
            thread_id = str(params.get("thread_id") or "").strip()
            event_id = str(params.get("event_id") or "").strip()
            if not thread_id:
                raise ValueError("work_cancel requires thread_id")
            if not event_id:
                raise ValueError("work_cancel requires event_id")
            progress = self.work_control.cancel(thread_id, event_id)
            result = {
                "progress": progress,
                "thread": self._work_snapshot(
                    self.work_control.get_snapshot(
                        thread_id,
                        message_limit=max(
                            1, min(500, int(params.get("message_limit") or 120))
                        ),
                    )
                ),
            }
        elif method == "work_restore_prepare":
            thread_id = str(params.get("thread_id") or "").strip()
            restore_point_id = str(params.get("restore_point_id") or "").strip()
            if not thread_id:
                raise ValueError("work_restore_prepare requires thread_id")
            if not restore_point_id:
                raise ValueError("work_restore_prepare requires restore_point_id")
            result = self.work_control.prepare_missing_restore(
                thread_id, restore_point_id
            )
        elif method == "work_restore_approve":
            thread_id = str(params.get("thread_id") or "").strip()
            application_id = str(params.get("application_id") or "").strip()
            if not thread_id:
                raise ValueError("work_restore_approve requires thread_id")
            if not application_id:
                raise ValueError("work_restore_approve requires application_id")
            result = self.work_control.approve_missing_restore(
                thread_id, application_id
            )
        elif method == "work_restore_application":
            application_id = str(params.get("application_id") or "").strip()
            if not application_id:
                raise ValueError("work_restore_application requires application_id")
            result = self.work_control.restore_application(application_id)
        elif method.startswith("routine_"):
            result = self._routine_result(method, params)
        elif method == "work_submit":
            thread_id = str(params.get("thread_id") or "").strip()
            task = str(params.get("task") or "").strip()
            if not thread_id:
                raise ValueError("work_submit requires thread_id")
            if not task:
                raise ValueError("work_submit requires task")
            payload = params.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise ValueError("work_submit payload must be an object")
            try:
                snapshot, run = self.work.submit(
                    thread_id,
                    task,
                    kind=str(params.get("kind") or "desktop_user_event"),
                    priority=int(params.get("priority") or 0),
                    payload=payload,
                )
            except ResidentRecoveryRequired as exc:
                work_run = self.work.get_run(exc.event_id)
                if work_run is None or work_run.thread_id != thread_id:
                    raise
                progress = self.work_control.progress(thread_id, exc.event_id)
                result = {
                    "thread": self._work_snapshot(
                        self.work_control.get_snapshot(thread_id)
                    ),
                    "progress": progress,
                    "recovery_required": True,
                }
            else:
                result = {
                    "thread": self._work_snapshot(snapshot),
                    "run": self._run_result(run),
                    "recovery_required": False,
                }
        elif method == "team_timeline":
            thread_id = str(params.get("thread_id") or "").strip()
            if not thread_id:
                raise ValueError("team_timeline requires thread_id")
            result = self._team_timeline(thread_id)
        elif method == "team_assign":
            thread_id = str(params.get("thread_id") or "").strip()
            specialist = str(params.get("specialist") or "").strip()
            instruction = str(params.get("instruction") or "").strip()
            if not thread_id:
                raise ValueError("team_assign requires thread_id")
            if not specialist:
                raise ValueError("team_assign requires specialist")
            result = self._team_assign(thread_id, specialist, instruction)
        elif method == "agent_run":
            task = str(params.get("task") or "").strip()
            if not task:
                raise ValueError("agent_run requires task")
            if params.get("max_turns") is not None:
                raise ValueError(
                    "agent_run no longer owns a separate model tool loop; "
                    "max_turns is unsupported by Resident Work"
                )
            thread_id = str(params.get("thread_id") or "").strip()
            if not thread_id:
                thread_id = self.work.create_thread(title=task[:100]).thread_id

            # Drive the SAME durable Resident Work as work_submit. The model
            # proposes semantic Action Fabric actions inside the Resident, and
            # execution, permissions, verification and recovery remain ZN-owned.
            snapshot, run = self.work.submit(
                thread_id,
                task,
                payload={"agent_loop": True},
            )
            reason = (
                "cancelled" if bool(getattr(run, "cancelled", False))
                else "resident_completed" if run.success
                else "resident_failed"
            )
            result = {
                "completed": bool(run.success),
                "final_text": str(run.response or ""),
                "turns_used": int(run.model_invocations),
                "model_invocations": int(run.model_invocations),
                "stopped_reason": reason,
                # Do not invent a second tool transcript; Work/Action Fabric
                # retain the authoritative per-effect evidence and outcomes.
                "steps": [],
                "thread": self._work_snapshot(snapshot),
                "work_event_id": run.event.event_id,
                "execution_path": run.execution_path.value,
            }
        elif method == "pulses":
            limit = self._limit(params)
            result = [
                {
                    "sequence": pulse.sequence,
                    "at": pulse.at,
                    "mode": pulse.mode,
                    "attention": pulse.attention,
                    "intention": pulse.intention,
                    "observations": list(pulse.observations),
                    "thought": asdict(pulse.thought) if pulse.thought else None,
                }
                for pulse in self.resident.life.recent_pulses(limit)
            ]
        elif method == "situations":
            result = [
                asdict(item)
                for item in self.resident.life.recent_situations(self._limit(params))
            ]
        elif method == "thoughts":
            result = [
                asdict(item)
                for item in self.resident.life.recent_thoughts(self._limit(params))
            ]
        elif method == "impasses":
            result = [
                asdict(item)
                for item in self.resident.life.recent_impasses(self._limit(params))
            ]
        elif method == "learning":
            result = [
                asdict(item)
                for item in self.resident.life.recent_learning_candidates(
                    self._limit(params)
                )
            ]
        elif method == "neural":
            nervous = getattr(self.resident, "nervous", None)
            result = (
                [asdict(item) for item in nervous.recent_traces(self._limit(params))]
                if nervous is not None
                else []
            )
        elif method == "perceive":
            nervous = getattr(self.resident, "nervous", None)
            if nervous is None:
                raise ValueError("resident has no nervous system")
            summary = str(params.get("summary") or "").strip()
            if not summary:
                raise ValueError("perceive requires summary")
            features = params.get("features") or []
            if not isinstance(features, list):
                raise ValueError("features must be a list")
            metadata = params.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            channel = str(params.get("channel") or "sense").strip().lower()
            kwargs = {
                "features": tuple(str(item) for item in features),
                "source": str(params.get("source") or channel or "sense"),
                "salience": float(params.get("salience", 0.5)),
                "valence": float(params.get("valence", 0.0)),
                "arousal": float(params.get("arousal", 0.3)),
                "metadata": metadata,
            }
            if channel == "vision" and hasattr(self.resident, "perceive_visual"):
                trace = self.resident.perceive_visual(summary, **kwargs)
            elif channel in {"world", "web", "world/web"} and hasattr(
                self.resident, "perceive_world"
            ):
                trace = self.resident.perceive_world(summary, **kwargs)
            else:
                trace = nervous.perceive(channel, summary, **kwargs)
            result = asdict(trace)
        elif method == "world_follow":
            world = getattr(self.resident, "world", None)
            if world is None:
                raise ValueError("resident has no world sensory organ")
            topic = str(params.get("topic") or "").strip()
            if not topic:
                raise ValueError("world_follow requires topic")
            result = asdict(
                world.follow(
                    topic,
                    priority=int(params.get("priority") or 0),
                    interval_seconds=int(params.get("interval_seconds") or 1800),
                    source=str(params.get("source") or "self"),
                )
            )
        elif method == "world_focuses":
            world = getattr(self.resident, "world", None)
            result = (
                [
                    asdict(item)
                    for item in world.focuses(
                        enabled_only=bool(params.get("enabled_only", True)),
                        limit=self._limit(params),
                    )
                ]
                if world is not None
                else []
            )
        elif method == "world_observe":
            world = getattr(self.resident, "world", None)
            if world is None:
                raise ValueError("resident has no world sensory organ")
            focus_id = str(params.get("focus_id") or "").strip()
            if not focus_id:
                raise ValueError("world_observe requires focus_id")
            result = asdict(
                world.observe(
                    focus_id,
                    limit=max(1, min(10, int(params.get("limit") or 5))),
                )
            )
        elif method == "submit":
            task = str(params.get("task") or "").strip()
            if not task:
                raise ValueError("submit requires task")
            run = self.resident.submit(
                task,
                kind=str(params.get("kind") or "user_task"),
                priority=int(params.get("priority") or 0),
                payload=(
                    params.get("payload")
                    if isinstance(params.get("payload"), dict)
                    else None
                ),
            )
            result = self._run_result(run)
        elif method == "remember":
            key = str(params.get("key") or "").strip()
            if not key:
                raise ValueError("remember requires key")
            aliases = params.get("aliases") or []
            if not isinstance(aliases, list):
                raise ValueError("aliases must be a list")
            self.resident.memory.remember(
                key,
                params.get("value"),
                aliases=tuple(str(value) for value in aliases),
            )
            result = {"saved": True, "key": key}
        elif method == "forget":
            key = str(params.get("key") or "").strip()
            if not key:
                raise ValueError("forget requires key")
            self.resident.memory.forget(key)
            result = {"forgotten": True, "key": key}
        elif method == "shutdown":
            self._shutdown = True
            self._life_stop.set()
            self.mcp_capabilities.close()
            result = {"shutting_down": True}
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _limit(params: dict[str, Any]) -> int:
        return max(1, min(200, int(params.get("limit") or 20)))

    def _team_timeline(self, thread_id: str) -> dict[str, Any]:
        """Read-only team timeline for one thread, derived from the Work log."""
        if self.work.get_thread(thread_id) is None:
            raise ValueError(f"unknown work thread: {thread_id!r}")
        messages = self.work.list_messages(thread_id, limit=500)
        artifacts = self.work.list_artifacts(thread_id, limit=48)
        entries = build_team_timeline(messages, artifacts=artifacts)
        team_id: str | None = None
        for entry in entries:
            team_id = str(entry.get("team_id") or "").strip() or team_id
        members: list[str] = []
        if team_id:
            shared = team_shared_memory(self.resident.memory, team_id)
            spec = shared.recall(TEAM_SPEC_KEY)
            if spec is not None and isinstance(spec.value, dict):
                project = str(spec.value.get("project_title") or "").strip()
                roles = [str(key) for key in (spec.value.get("role_keys") or [])]
                if project and roles:
                    members = [
                        member.name
                        for member in assemble_team(
                            project,
                            roles,
                            team_id=team_id,
                            work_thread_id=thread_id,
                        ).members
                    ]
        if not members:
            seen: list[str] = []
            for entry in entries:
                author = str(entry.get("author") or "")
                if author and author not in ("coordinator", "user") and author not in seen:
                    seen.append(author)
            members = seen
        return {"team_id": team_id, "members": members, "entries": entries}

    def _team_assign(self, thread_id: str, specialist: str, instruction: str) -> dict[str, Any]:
        """``@specialist`` assignment: reassign the next pending plan item.

        The override is durable (team shared memory) and the assignment is
        journaled, so it shows up in the timeline and survives restarts.
        While a team event is running, ``work_start`` would refuse a second
        event on the thread -- this RPC is the steering path that works
        regardless of the active event.
        """
        if self.work.get_thread(thread_id) is None:
            raise ValueError(f"unknown work thread: {thread_id!r}")
        messages = self.work.list_messages(thread_id, limit=500)
        team_id: str | None = None
        for message in reversed(messages):
            parsed = parse_team_role(message.role)
            if parsed is not None:
                team_id = parsed[0]
                break
        if not team_id:
            raise ValueError("该 Work 没有运行中的团队，@指派需要先组团队")
        shared = team_shared_memory(self.resident.memory, team_id)
        spec = shared.recall(TEAM_SPEC_KEY)
        if spec is None or not isinstance(spec.value, dict):
            raise ValueError("团队记录缺失，无法指派")
        project = str(spec.value.get("project_title") or "").strip()
        roles = [str(key) for key in (spec.value.get("role_keys") or [])]
        if not project or not roles:
            raise ValueError("团队记录缺失，无法指派")
        team = assemble_team(
            project, roles, team_id=team_id, work_thread_id=thread_id
        )
        member_names = [member.name for member in team.members]
        if specialist not in member_names:
            raise ValueError(
                f"团队里没有专员 {specialist!r}，可选：{', '.join(member_names)}"
            )
        work_ledger = getattr(self.resident, "work_ledger", None)
        if work_ledger is None:
            raise ValueError("resident has no work ledger")
        plan_match = shared.recall(TeamRunner.PLAN_MAP_KEY)
        id_map = (
            dict(plan_match.value)
            if plan_match is not None and isinstance(plan_match.value, dict)
            else {}
        )
        pending = None
        for plan_item in team.plan:
            wid = id_map.get(plan_item.item_id)
            runs = (
                work_ledger.list_worker_runs(work_item_id=wid, limit=1)
                if wid
                else []
            )
            if not runs:
                pending = plan_item
                break
        if pending is None:
            raise ValueError("团队已无待派发任务，@指派无下一步可派")
        record_assignee_override(
            self.resident.memory, team_id, pending.item_id, specialist
        )
        text = f"@{specialist} {instruction}".strip() or f"@{specialist}"
        self.work.append_message(
            thread_id,
            role=f"team:{team_id}:user",
            text=text,
            detail={
                "kind": "assignment",
                "team_id": team_id,
                "author": "user",
                "from_author": "user",
                "to_author": specialist,
                "item_title": pending.title,
                "instruction": instruction,
            },
        )
        return {
            "team_id": team_id,
            "specialist": specialist,
            "item_id": pending.item_id,
            "item_title": pending.title,
            "instruction": instruction,
        }

    def _work_snapshot(
        self,
        snapshot,
        *,
        artifact_limit: int = 8,
    ) -> dict[str, Any]:
        thread, messages = snapshot
        bounded_artifact_limit = max(0, min(8, int(artifact_limit)))
        artifacts = (
            self.work.list_artifacts(thread.thread_id, limit=bounded_artifact_limit)
            if bounded_artifact_limit > 0
            else []
        )
        # Reconnecting faces discover the existing event rather than submitting
        # the user's task again. This is identity only, never replay authority.
        active_run = self.work._active_run_for_thread(thread.thread_id)
        return {
            "id": thread.thread_id,
            "title": thread.title,
            "metadata": thread.metadata,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
            "active_run": (
                {"thread_id": active_run.thread_id, "event_id": active_run.event_id}
                if active_run is not None else None
            ),
            "messages": [
                {
                    "id": message.message_id,
                    "role": message.role,
                    "text": message.text,
                    "detail": message.detail,
                    "created_at": message.created_at,
                }
                for message in messages
            ],
            "artifacts": [
                {
                    "id": artifact.artifact_id,
                    "event_id": artifact.event_id,
                    "kind": artifact.kind,
                    "name": artifact.name,
                    "path": artifact.path,
                    "content": artifact.content,
                    "metadata": artifact.metadata,
                    "created_at": artifact.created_at,
                }
                for artifact in artifacts
            ],
        }

    def _start_life_loop(self) -> None:
        self._life_stop.clear()
        if not self._life_thread or not self._life_thread.is_alive():
            self._life_thread = threading.Thread(
                target=self._life_loop,
                name="zn-life",
                daemon=True,
            )
            self._life_thread.start()

        world = getattr(self.resident, "world", None)
        if world is not None and (
            not self._world_thread or not self._world_thread.is_alive()
        ):
            self._world_thread = threading.Thread(
                target=self._world_loop,
                name="zn-world-sense",
                daemon=True,
            )
            self._world_thread.start()

    def _stop_life_loop(self) -> None:
        self._life_stop.set()
        for thread in (self._life_thread, self._world_thread):
            if thread and thread.is_alive():
                thread.join(timeout=max(1.0, self.life_interval * 2.0))
        self._life_thread = None
        self._world_thread = None

    def set_fatal_life_error_handler(
        self,
        handler: Callable[[BaseException], None] | None,
    ) -> None:
        self._fatal_life_error_handler = handler

    def _fail_life_closed(self, error: BaseException) -> None:
        self._shutdown = True
        self._life_stop.set()
        handler = self._fatal_life_error_handler
        if handler is not None:
            handler(error)

    def _life_loop(self) -> None:
        next_lease_heartbeat = 0.0
        while not self._life_stop.wait(self.life_interval):
            now = time.monotonic()
            if now >= next_lease_heartbeat:
                try:
                    self.service.heartbeat()
                except Exception as exc:
                    self._fail_life_closed(exc)
                    return
                next_lease_heartbeat = now + self.service.heartbeat_interval
            try:
                self.resident.live_once()
            except Exception:
                continue

    def _world_loop(self) -> None:
        sense_interval = max(5.0, self.life_interval * 2.0)
        while not self._life_stop.wait(sense_interval):
            world = getattr(self.resident, "world", None)
            if world is None:
                continue
            try:
                world.maybe_observe()
            except Exception:
                continue

    @staticmethod
    def _run_result(run) -> dict[str, Any]:
        return {
            "event_id": run.event.event_id,
            "execution_path": run.execution_path.value,
            "success": run.success,
            "cancelled": bool(getattr(run, "cancelled", False)),
            "response": run.response,
            "model_invocations": run.model_invocations,
            "capability_name": run.capability_name,
            "reason": run.reason,
        }

    def _routine_manager(self):
        manager = getattr(self.resident, "routines", None)
        if manager is None:
            raise ValueError("routines are unavailable on this resident")
        return manager

    @staticmethod
    def _routine_id(params: dict[str, Any]) -> str:
        routine_id = str(params.get("routine_id") or "").strip()
        if not routine_id:
            raise ValueError("routine_id is required")
        return routine_id

    def _routine_result(self, method: str, params: dict[str, Any]) -> Any:
        """Dispatch routine_* RPC methods to the resident's RoutineManager."""
        manager = self._routine_manager()
        if method == "routine_propose":
            text = str(params.get("text") or "").strip()
            if not text:
                raise ValueError("routine_propose requires text")
            return manager.propose(text)
        if method == "routine_confirm":
            draft = params.get("draft")
            if not isinstance(draft, dict):
                raise ValueError("routine_confirm requires a draft object")
            return manager.confirm(draft)
        if method == "routine_list":
            return manager.list_routines(limit=self._limit(params))
        if method == "routine_get":
            return manager.snapshot(self._routine_id(params))
        if method == "routine_runs":
            return manager.runs(self._routine_id(params), limit=self._limit(params))
        if method == "routine_pause":
            return manager.pause(
                self._routine_id(params),
                reason=str(params.get("reason") or "").strip() or None,
            )
        if method == "routine_resume":
            return manager.resume(self._routine_id(params))
        if method == "routine_edit":
            fields = params.get("fields")
            if not isinstance(fields, dict):
                raise ValueError("routine_edit requires a fields object")
            return manager.edit(self._routine_id(params), fields=fields)
        if method == "routine_delete":
            return manager.delete(self._routine_id(params))
        if method == "routine_test_run":
            return manager.test_run(self._routine_id(params))
        if method == "routine_acknowledge":
            return manager.acknowledge(self._routine_id(params))
        raise ValueError(f"unknown method: {method}")

    def _write(self, payload: dict[str, Any]) -> None:
        self.output.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self.output.flush()


def main() -> int:
    return ResidentRpcServer().serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
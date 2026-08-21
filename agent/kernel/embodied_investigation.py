from __future__ import annotations

from typing import Any

from .investigation import NativeInvestigator
from .models import AgentEvent
from .self_model import TaskReadiness


class EmbodiedInvestigator(NativeInvestigator):
    """Native investigation whose probes are movements of ZN's Body.

    The parent class owns hypothesis selection, evidence accumulation and the
    multi-pulse reasoning loop. This subclass only changes *how* a concrete
    probe touches the computer: all host interaction goes through NativeBody,
    so perception and action share one body history instead of parallel ad-hoc
    filesystem/process implementations.
    """

    def _run_probe(
        self,
        key: str,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        facts: dict[str, Any],
        learning_evidence: list[dict[str, Any]],
    ) -> list[str]:
        body = getattr(self.resident, "body", None)
        if body is None:
            return super()._run_probe(
                key,
                event,
                readiness,
                facts=facts,
                learning_evidence=learning_evidence,
            )

        if key == "body":
            result = body.act("sense", event_id=event.event_id)
            if not result.success:
                return [f"body probe failed: {result.error or 'unknown error'}"]
            total = int(result.data.get("disk_total_bytes") or 0)
            free = int(result.data.get("disk_free_bytes") or 0)
            ratio = (free / total) if total > 0 else 0.0
            facts["body"] = {
                "hostname": result.data.get("hostname"),
                "pid": result.data.get("pid"),
                "cwd": result.data.get("cwd"),
                "system": result.data.get("system"),
                "architecture": result.data.get("architecture"),
                "disk_free_ratio": ratio,
            }
            return [
                "body: "
                f"host={result.data.get('hostname')}; pid={result.data.get('pid')}; "
                f"cwd={result.data.get('cwd')}; system={result.data.get('system')}; "
                f"disk_free={ratio:.3f}"
            ]

        if key == "paths":
            path_facts: list[dict[str, Any]] = []
            evidence: list[str] = []
            for raw in self._path_candidates(event):
                result = body.act(
                    "inspect_path",
                    event_id=event.event_id,
                    path=raw,
                )
                if result.success:
                    item = dict(result.data)
                else:
                    item = {
                        "path": str(raw),
                        "exists": False,
                        "type": "unavailable",
                        "error": result.error,
                    }
                path_facts.append(item)
                evidence.append(
                    "path: "
                    f"{item.get('path')} exists={item.get('exists')} "
                    f"type={item.get('type', 'missing')} size={item.get('size_bytes', 0)}"
                )
            facts["paths"] = path_facts
            return evidence or ["path probe found no concrete referenced path"]

        if key == "file_preview":
            previews: list[dict[str, Any]] = []
            evidence: list[str] = []
            for item in self._previewable_paths(facts):
                path = str(item.get("path") or "")
                result = body.act(
                    "read_text",
                    event_id=event.event_id,
                    path=path,
                    max_chars=16384,
                )
                if not result.success:
                    continue
                preview = {
                    "path": path,
                    "preview": result.output,
                    "chars": int(result.data.get("chars") or len(result.output)),
                    "truncated": bool(result.data.get("truncated", False)),
                }
                previews.append(preview)
                evidence.append(
                    f"file content observed locally: {path} chars={preview['chars']} "
                    f"truncated={preview['truncated']}"
                )
            facts["file_previews"] = previews
            return evidence or ["referenced files did not yield readable text content"]

        if key == "git":
            workspace = (
                event.payload.get("workspace_path")
                or event.payload.get("project_path")
                or event.payload.get("repo_path")
            )
            if not workspace:
                sensed = body.sense()
                workspace = sensed.get("cwd")
            result = body.act(
                "git_state",
                event_id=event.event_id,
                path=str(workspace or "."),
            )
            if not result.success:
                facts["git"] = {"available": False, "error": result.error}
                return ["git workspace probe did not find a repository"]
            git_fact = dict(result.data)
            git_fact["available"] = True
            facts["git"] = git_fact
            return [
                "git: "
                f"root={git_fact.get('root')}; branch={git_fact.get('branch')}; "
                f"dirty={git_fact.get('dirty')}; changed_files={git_fact.get('changed_files')}"
            ]

        if key == "processes":
            process_facts: list[dict[str, Any]] = []
            evidence: list[str] = []
            for pid in self._process_candidates(event):
                result = body.act(
                    "process_state",
                    event_id=event.event_id,
                    pid=pid,
                )
                item = dict(result.data) if result.success else {
                    "pid": pid,
                    "alive": False,
                    "error": result.error,
                }
                process_facts.append(item)
                evidence.append(
                    f"process: pid={pid} alive={item.get('alive')}"
                )
            facts["processes"] = process_facts
            return evidence or ["process probe found no referenced process"]

        # Experience comparison is cognition over ZN-owned state, not a body
        # movement, so keep the parent's resident-side implementation.
        return super()._run_probe(
            key,
            event,
            readiness,
            facts=facts,
            learning_evidence=learning_evidence,
        )

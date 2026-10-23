from __future__ import annotations

"""Bounded browser-reference + workspace adaptation for the existing ZN Resident.

This composes existing User Browser, managed research, Work, File, Terminal and
WorkerRun capabilities. It owns no second agent, router, Body, store or Root
completion authority. Scenario E2Es may exercise this layer, but they do not own
its routing or execution semantics.

NOTE (port to main @ fafd2f08): the delegated-worker phase machinery from the
source branch (#384) depended on ``delegated_work_coordinator`` /
``next_worker_phase`` / ``bind_worker_request`` / ``_delegated_meta_from_state``,
which main retired in cb0d1cb1 ("retire scenario-owned acceptance surface").
Those pieces (the DelegatedWorkCoordinator subclass, the phase driver, the
worker-request binder and the cognition-integration worker-run binding) are
intentionally NOT ported: there is no equivalent in main. Kept is the
routing-adjacent adaptation layer: composite-Work classification predicates plus
the bounded Root-verification gates (phase-evidence + fresh workspace
pre-verification) that run on the existing Work ledger and Body.
"""

from pathlib import Path
from typing import Any

from .application_resident import ApplicationAwareResidentRuntime
from .composite_work_routing import classify_composite_work_text
from .path_context import resolved_within
from .steerable_work import WorkItem

class BrowserWorkspaceAdaptationResidentRuntime(ApplicationAwareResidentRuntime):
    """Compose current browser evidence with bounded workspace change and verification."""

    _CURRENT_SOURCE_KEY = "browser_workspace_current_page_source_v1"
    _WORKSPACE_READ_KEY = "browser_workspace_read_v1"
    _PREVERIFY_EVIDENCE_KEY = "browser_workspace_preverification_evidence_v1"

    @staticmethod
    def _is_browser_workspace_adaptation_text(text: str) -> bool:
        decision = classify_composite_work_text(text)
        return bool(
            decision.preempt_narrow_browser
            and "local_verification" in decision.surfaces
        )

    @classmethod
    def _is_browser_workspace_adaptation_root(cls, root: WorkItem) -> bool:
        return cls._is_browser_workspace_adaptation_text(str(root.objective or ""))

    def _required_adaptation_phase_evidence(self, root: WorkItem) -> tuple[bool, str]:
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
            return None, "browser+workspace adaptation final verification requires the attached workspace"
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
            return None, "browser+workspace adaptation final verification requires a completed workspace write"
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
        if proposal is None or not self._is_browser_workspace_adaptation_root(root):
            return proposal
        complete, _reason = self._required_adaptation_phase_evidence(root)
        if not complete:
            return None
        return proposal

    def _begin_root_verification(self, event, state, root, increment, proposal):
        if not self._is_browser_workspace_adaptation_root(root):
            return super()._begin_root_verification(event, state, root, increment, proposal)
        complete, reason = self._required_adaptation_phase_evidence(root)
        if not complete:
            self._accept_borrowed_increment(event, state, increment)
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "browser+workspace adaptation Root verification rejected: " + reason,
            )
        evidence, failure = self._fresh_workspace_preverification_evidence(event, root)
        if failure is not None or evidence is None:
            self._accept_borrowed_increment(event, state, increment)
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "browser+workspace adaptation Root verification rejected: " + str(failure or "missing fresh workspace evidence"),
            )
        state.data[self._PREVERIFY_EVIDENCE_KEY] = evidence
        return super()._begin_root_verification(event, state, root, increment, proposal)


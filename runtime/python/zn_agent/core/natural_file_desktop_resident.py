from __future__ import annotations

"""Natural Work closure from one authorized workspace file into a focused desktop Edit."""

import hashlib
import re
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .action import NativeActionIntent
from .file_identity import compare_file_identities, observe_file_identity
from .keyboard_text_body import KeyboardTextBody
from .models import WorkingState, utc_now
from .natural_file_work_resident import NaturalFileWorkResidentRuntime
from .path_context import canonical_host_path, resolved_within


_SOURCE_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?\s*\.?\s*txt(?=[，,。；;\s]|$)",
    re.I,
)
_MAX_ENTRIES = 64
_MAX_CANDIDATES = 8
_MAX_SOURCE_BYTES = 8 * 1024
_MAX_READ_CHARS = 1024
_BROWSER_PROCESS_NAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}


class NaturalFileDesktopResidentRuntime(NaturalFileWorkResidentRuntime):
    """Carry one freshly observed file value into the user's focused desktop Edit.

    The Work-level grounding added here is deliberately narrow. It chooses one
    top-level txt file from an already attached workspace, reads a bounded
    single-line value, freshly binds the currently focused non-browser UIA Edit,
    and then reuses the inherited ``keyboard_text`` lifecycle. The source text is
    not persisted in the action intent: the resident stores only file identity
    and a digest, then freshly rereads the file when the guarded action contract
    is formed and again when the postcondition is verified.
    """

    _FILE_TO_DESKTOP_OUTCOME_KIND = "workspace_file_to_focused_text"
    _FILE_TO_DESKTOP_FACT_KEY = "natural_file_to_focused_desktop"
    _SOURCE_PROBE_LABEL = "bind one bounded workspace text source"
    _DESTINATION_PROBE_LABEL = "bind the exact currently focused desktop Edit"

    @classmethod
    def _natural_file_to_focused_desktop_request(cls, event) -> dict[str, str] | None:
        payload = event.payload or {}
        task = " ".join(str(event.task or "").strip().split())
        if (
            str(event.kind or "").strip().lower() != "desktop_user_event"
            or not str(payload.get("workspace_path") or "").strip()
            or payload.get("body_action")
            or payload.get("native_action")
            or "昨天" not in task
            or "输入框" not in task
            or not any(cue in task for cue in ("当前打开的软件", "当前软件", "这个软件", "打开的软件"))
            or not any(cue in task for cue in ("填到", "填进", "输入到", "输入进", "放到"))
            or "确认" not in task
        ):
            return None
        hint = _SOURCE_HINT.search(task)
        if hint is None:
            return None
        name_hint = hint.group("v").strip()
        if not name_hint:
            return None
        return {
            "workspace_path": str(payload["workspace_path"]),
            "name_hint": name_hint,
        }

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_file_to_focused_desktop_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        facts = dict(investigation.facts)
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)

        source, source_notes = self._observe_source_file(event, request)
        facts["natural_file_desktop_source"] = source
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key="natural_file_desktop_source",
            label=self._SOURCE_PROBE_LABEL,
            notes=source_notes,
        )

        destination: dict[str, Any] = {
            "complete": False,
            "failure_reason": str(source.get("failure_reason") or ""),
        }
        destination_notes: list[str] = []
        if source.get("complete") is True:
            destination, destination_notes = self._observe_focused_destination(source)
            self._record_probe(
                evidence,
                probes,
                probe_keys,
                key="natural_file_desktop_destination",
                label=self._DESTINATION_PROBE_LABEL,
                notes=destination_notes,
            )
        facts["natural_file_desktop_destination"] = destination

        failure = str(source.get("failure_reason") or destination.get("failure_reason") or "").strip() or None
        intent = None if failure else self._file_to_desktop_intent(event, source, destination)
        if intent is None and failure is None:
            failure = "fresh file and focused-desktop evidence did not establish one safe transfer"

        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = failure
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)
        self._merge_investigation_into_thought(thought, self._investigation_result(investigation))

        if intent is None:
            reason = failure or "bounded file-to-desktop transfer could not be grounded safely"
            if thought is not None:
                if reason not in thought.unknown:
                    thought.unknown = (*thought.unknown, reason)
                thought.reason = f"{thought.reason}; ZN stopped before desktop input because fresh evidence was insufficient"
                self._persist_enriched_thought(thought)
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="the exact file-to-desktop action remains blocked by unchanged failure evidence; ZN will not replay it",
            )

        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = "fill the freshly bound focused desktop Edit from the freshly bound workspace file"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = (
                f"{thought.reason}; one exact workspace source and one exact focused desktop Edit are freshly bound, "
                "so the existing non-replayable keyboard-text Body can perform the transfer"
            )
            self._persist_enriched_thought(thought)
        return None

    def _investigation_result(self, investigation):
        from .investigation import InvestigationResult

        return InvestigationResult(state=investigation)

    def _keyboard_text_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "keyboard_text"
            or str(expected.get("kind") or "").strip().lower() != self._FILE_TO_DESKTOP_OUTCOME_KIND
        ):
            return super()._keyboard_text_contract(event, intent)

        text, error = self._fresh_source_text(event, expected)
        if error or text is None:
            return None, error or "workspace source text is unavailable"

        completion_scope = expected.get("completion_scope")
        action_precondition = expected.get("action_precondition")
        if not isinstance(completion_scope, dict) or not isinstance(action_precondition, dict):
            return None, "file-to-desktop intent lost its exact focused-target authority"

        synthetic_event = replace(
            event,
            kind=self._UI_EVENT_KIND,
            payload={
                "expected_outcome": {"kind": self._TEXT_OUTCOME_KIND},
                "completion_scope": dict(completion_scope),
                "action_precondition": dict(action_precondition),
                "model_policy": "never",
            },
        )
        transient_intent = NativeActionIntent(
            intent_id=intent.intent_id,
            event_id=intent.event_id,
            kind=intent.kind,
            args={"text": text},
            expected_outcome=intent.expected_outcome,
            reason=intent.reason,
            source=intent.source,
            created_at=intent.created_at,
        )
        return super()._keyboard_text_contract(synthetic_event, transient_intent)

    def _observe_source_file(
        self,
        event,
        request: Mapping[str, str],
    ) -> tuple[dict[str, Any], list[str]]:
        try:
            workspace = canonical_host_path(request["workspace_path"]).resolve(strict=True)
            if not workspace.is_dir():
                raise ValueError
        except (OSError, RuntimeError, ValueError):
            return self._source_failure("the authorized workspace is unavailable")

        listing = self.body.act(
            "list_directory",
            event_id=event.event_id,
            path=str(workspace),
            limit=_MAX_ENTRIES + 1,
        )
        if not listing.success:
            return self._source_failure(
                f"bounded workspace enumeration failed: {listing.error or 'unknown error'}"
            )
        entries = [dict(item) for item in (listing.data.get("entries") or ()) if isinstance(item, Mapping)]
        if len(entries) > _MAX_ENTRIES:
            return self._source_failure("bounded workspace enumeration reached its top-level entry limit")

        hint = str(request["name_hint"]).casefold()
        yesterday = datetime.now().astimezone().date() - timedelta(days=1)
        candidates: list[dict[str, Any]] = []
        date_unknown = False
        for item in entries:
            name = str(item.get("name") or "")
            raw_path = str(item.get("path") or "")
            if str(item.get("type") or "").lower() != "file" or not raw_path:
                continue
            path = canonical_host_path(raw_path)
            if Path(name).suffix.casefold() != ".txt" or hint not in Path(name).stem.casefold():
                continue
            if not self._direct_child(path, workspace):
                continue
            if len(candidates) >= _MAX_CANDIDATES:
                return self._source_failure("too many top-level filename candidates for bounded selection")
            inspected = self.body.act("inspect_path", event_id=event.event_id, path=str(path))
            identity = observe_file_identity(path)
            day = self._identity_day(identity)
            date_unknown = date_unknown or day is None
            candidates.append(
                {
                    "name": name,
                    "path": str(path),
                    "identity": identity,
                    "matches_yesterday": day == yesterday if day else None,
                    "safe": bool(
                        inspected.success
                        and inspected.data.get("exists") is True
                        and str(inspected.data.get("type") or "").lower() == "file"
                        and self._exact_file(identity, path)
                        and int(identity.get("size_bytes") or 0) <= _MAX_SOURCE_BYTES
                    ),
                }
            )

        if date_unknown:
            return self._source_failure("a filename candidate could not be freshly dated, so it cannot be safely excluded")
        plausible = [item for item in candidates if item.get("matches_yesterday") is True]
        if not candidates:
            return self._source_failure("no top-level txt filename matches the requested name hint")
        if len(plausible) != 1:
            return self._source_failure(
                "the requested yesterday-modified file is ambiguous" if plausible else "no matching filename was freshly observed as modified yesterday"
            )
        selected = plausible[0]
        if selected.get("safe") is not True:
            return self._source_failure("the selected workspace file is not a bounded safe text source")

        path = str(selected["path"])
        baseline = selected.get("identity")
        pre = observe_file_identity(path)
        if compare_file_identities(baseline if isinstance(baseline, dict) else None, pre).get("exact") is not True:
            return self._source_failure("the selected workspace file changed before it could be read")
        observed = self.body.act("read_text", event_id=event.event_id, path=path, max_chars=_MAX_READ_CHARS)
        post = observe_file_identity(path)
        text = str(observed.output) if observed.success else ""
        if not observed.success:
            return self._source_failure(str(observed.error or "workspace source read failed"))
        if bool(observed.data.get("truncated")):
            return self._source_failure("the selected workspace source exceeds the bounded complete-text limit")
        if compare_file_identities(pre, post).get("exact") is not True:
            return self._source_failure("the selected workspace file changed while it was being read")
        try:
            validated, units = KeyboardTextBody.validate_text(text)
        except ValueError as exc:
            return self._source_failure(f"workspace source cannot be safely entered as bounded text: {exc}")
        digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()
        return {
            "complete": True,
            "workspace_path": str(workspace),
            "name_hint": str(request["name_hint"]),
            "path": path,
            "name": str(selected["name"]),
            "identity": dict(post),
            "text_sha256": digest,
            "text_chars": len(validated),
            "utf16_units": len(units),
            "candidate_count": len(candidates),
            "failure_reason": None,
        }, [
            f"bounded workspace source selection: name_matches={len(candidates)} yesterday_matches=1",
            f"fresh source read: chars={len(validated)} sha256={digest}",
        ]

    def _observe_focused_destination(
        self,
        source: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        foreground, error = self._probe_foreground_window()
        if foreground is None:
            return self._destination_failure("foreground desktop window is unavailable: " + str(error))
        process_name = str(foreground.process_name or "").strip().lower()
        if not process_name or process_name in _BROWSER_PROCESS_NAMES:
            return self._destination_failure("this natural desktop transfer requires a focused non-browser application")
        automation, error = self._probe_focused_automation_element()
        if automation is None:
            return self._destination_failure("focused UI Automation element is unavailable: " + str(error))
        if (
            int(automation.process_id) != int(foreground.process_id)
            or str(automation.process_name or "").strip().lower() != process_name
            or int(automation.control_type) != 50004
            or not automation.is_enabled
            or not automation.is_keyboard_focusable
            or not automation.has_keyboard_focus
            or automation.is_offscreen
            or automation.is_password
        ):
            return self._destination_failure("the currently focused desktop target is not one safe writable UIA Edit")
        scope = {
            "kind": self._AUTOMATION_TEXT_SCOPE_KIND,
            "process_name": process_name,
            "title_equals": str(foreground.title or "").strip(),
            "control_type": 50004,
            "class_name_equals": str(automation.class_name or "").strip(),
            "automation_id_equals": str(automation.automation_id or "").strip(),
        }
        if not scope["title_equals"]:
            return self._destination_failure("the focused desktop window has no exact title for action authority")
        target, target_error = self._probe_text_target(scope)
        if target is None:
            return self._destination_failure("fresh focused desktop text state is unavailable: " + str(target_error))
        text_state = target["text"]
        expected_digest = str(source.get("text_sha256") or "")
        expected_chars = int(source.get("text_chars") or -1)
        already_matches = bool(
            int(text_state.text_length) == expected_chars
            and str(text_state.text_sha256 or "") == expected_digest
        )
        if int(text_state.text_length) != 0 and not already_matches:
            return self._destination_failure(
                "the focused desktop Edit already contains different text; ZN will not delete or replace it implicitly"
            )
        action_precondition = {
            "kind": "foreground_window_matches",
            "process_name": process_name,
            "title_equals": scope["title_equals"],
        }
        return {
            "complete": True,
            "completion_scope": scope,
            "action_precondition": action_precondition,
            "target_runtime_id": list(target["automation"].runtime_id),
            "initial_text_length": int(text_state.text_length),
            "already_matches": already_matches,
            "failure_reason": None,
        }, [
            f"fresh focused desktop target: process={process_name} control_type=50004",
            f"privacy-safe initial text state: length={int(text_state.text_length)} already_matches={already_matches}",
        ]

    def _file_to_desktop_intent(
        self,
        event,
        source: Mapping[str, Any],
        destination: Mapping[str, Any],
    ) -> NativeActionIntent | None:
        identity = source.get("identity")
        scope = destination.get("completion_scope")
        action_precondition = destination.get("action_precondition")
        if not isinstance(identity, Mapping) or not isinstance(scope, Mapping) or not isinstance(action_precondition, Mapping):
            return None
        return NativeActionIntent(
            intent_id=f"file-desktop-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="keyboard_text",
            args={},
            expected_outcome={
                "kind": self._FILE_TO_DESKTOP_OUTCOME_KIND,
                "workspace_path": str(source.get("workspace_path") or ""),
                "source_path": str(source.get("path") or ""),
                "source_identity": dict(identity),
                "source_text_sha256": str(source.get("text_sha256") or ""),
                "source_text_chars": int(source.get("text_chars") or 0),
                "source_utf16_units": int(source.get("utf16_units") or 0),
                "completion_scope": dict(scope),
                "action_precondition": dict(action_precondition),
            },
            reason=(
                "fresh bounded workspace evidence identifies one exact text source and fresh desktop evidence identifies "
                "one exact focused non-browser Edit; reuse the existing non-replayable keyboard-text lifecycle"
            ),
            source="resident_choice",
        )

    def _fresh_source_text(
        self,
        event,
        expected: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        path = str(expected.get("source_path") or "").strip()
        workspace = str(expected.get("workspace_path") or "").strip()
        baseline = expected.get("source_identity")
        if not path or not workspace or not isinstance(baseline, Mapping):
            return None, "file-to-desktop intent lost its exact source-file identity"
        if not self._direct_child(path, workspace):
            return None, "file-to-desktop source escaped the attached workspace"
        pre = observe_file_identity(path)
        if compare_file_identities(dict(baseline), pre).get("exact") is not True:
            return None, "workspace source identity no longer matches the investigated file"
        observed = self.body.act("read_text", event_id=event.event_id, path=path, max_chars=_MAX_READ_CHARS)
        post = observe_file_identity(path)
        if not observed.success or bool(observed.data.get("truncated")):
            return None, str(observed.error or "fresh workspace source read failed")
        if compare_file_identities(pre, post).get("exact") is not True:
            return None, "workspace source changed during fresh action-time read"
        text = str(observed.output)
        try:
            validated, units = KeyboardTextBody.validate_text(text)
        except ValueError as exc:
            return None, f"workspace source is no longer safe bounded keyboard text: {exc}"
        digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()
        if (
            digest != str(expected.get("source_text_sha256") or "")
            or len(validated) != int(expected.get("source_text_chars") or -1)
            or len(units) != int(expected.get("source_utf16_units") or -1)
        ):
            return None, "workspace source content no longer matches the investigated digest"
        return validated, None

    @staticmethod
    def _identity_day(identity: Mapping[str, Any]):
        try:
            return datetime.fromtimestamp(int(identity["mtime_ns"]) / 1_000_000_000).astimezone().date()
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _exact_file(identity: Mapping[str, Any], path: Any) -> bool:
        try:
            expected = canonical_host_path(str(path))
            observed = canonical_host_path(str(identity.get("path") or ""))
        except (OSError, RuntimeError, ValueError):
            return False
        return bool(
            identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is True
            and identity.get("type") == "file"
            and identity.get("digest_complete") is True
            and observed == expected
        )

    @staticmethod
    def _direct_child(path: Any, workspace: Any) -> bool:
        try:
            root = canonical_host_path(str(workspace)).resolve(strict=True)
            lexical = canonical_host_path(str(path))
            resolved = resolved_within(root, lexical)
            return lexical.parent == root and resolved is not None and resolved.parent == root
        except (OSError, RuntimeError, ValueError):
            return False

    @staticmethod
    def _source_failure(reason: str) -> tuple[dict[str, Any], list[str]]:
        return {"complete": False, "failure_reason": reason}, [reason]

    @staticmethod
    def _destination_failure(reason: str) -> tuple[dict[str, Any], list[str]]:
        return {"complete": False, "failure_reason": reason}, [reason]

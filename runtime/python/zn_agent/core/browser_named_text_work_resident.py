from __future__ import annotations

"""Ordinary Work ownership for exact semantic managed-browser text entry."""

import hashlib
import re
from dataclasses import asdict

from .action import NativeActionIntent
from .body import BodyActionResult
from .browser_text_work_body import BrowserTextWorkBody
from .terminal_input_recovery_resident import TerminalInputRecoveryResidentRuntime


_EN_TEXT_ENTRY_RE = re.compile(
    r'\b(?:type|enter|fill)\s+["“]([^"”\r\n]{1,512})["”]\s+'
    r'(?:into|in)\s+(?:the\s+)?(?:textbox|field|input)\s+'
    r'["“]([^"”\r\n]{1,160})["”]',
    re.IGNORECASE,
)
_ZH_TEXT_ENTRY_RE = re.compile(
    r'(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”]\s*'
    r'(?:中|里)?\s*(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”]'
)
_ZH_TEXT_ENTRY_RE_REVERSED = re.compile(
    r'(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”]\s*'
    r'(?:到|进|至)\s*(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”]'
)
_NATURAL_URL_BOUNDARY_RE = re.compile(r"[“”‘’，。！？；：）】》]")


class BrowserNamedTextWorkResidentRuntime(TerminalInputRecoveryResidentRuntime):
    """Form, execute, recover, and verify one explicit named-textbox mutation.

    The parser is intentionally deterministic and narrow. A normal Work must
    provide exactly one HTTP(S) URL, explicit text-entry wording, one quoted
    plaintext value, and one quoted accessible textbox name. The provider remains
    authority for unique exact-name binding, writable native textbox semantics,
    password refusal, fresh-node revalidation, and the post-dispatch text digest.
    """

    _BROWSER_TYPE_NAMED_TEXT = "browser_type_named_text"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = BrowserTextWorkBody(resident=self)

    @staticmethod
    def _explicit_urls(task: str) -> tuple[str, ...]:
        # Chinese prose commonly attaches full-width punctuation directly to a
        # URL. The shared ASCII-oriented extractor otherwise treats the following
        # sentence text as part of the URL path. Normalize only delimiter
        # characters for URL discovery; the original task remains untouched for
        # target/text parsing and durable Work content.
        bounded = _NATURAL_URL_BOUNDARY_RE.sub(" ", str(task or ""))
        return TerminalInputRecoveryResidentRuntime._explicit_urls(bounded)

    @classmethod
    def _looks_like_text_interaction(cls, task: str) -> bool:
        remainder = str(task or "")
        for url in cls._explicit_urls(remainder):
            remainder = remainder.replace(url, " ")
        lowered = remainder.lower()
        return bool(
            any(marker in lowered for marker in ("textbox", "field", "input"))
            or any(marker in remainder for marker in ("文本框", "输入框", "字段"))
        ) and bool(
            any(cue in lowered for cue in ("type ", "enter ", "fill "))
            or any(cue in remainder for cue in ("输入", "填写"))
        )

    @classmethod
    def _natural_navigation_url(cls, event) -> str | None:
        if cls._looks_like_text_interaction(str(event.task or "")):
            return None
        return super()._natural_navigation_url(event)

    @classmethod
    def _natural_named_text_request(cls, event) -> tuple[str, str, str] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 1:
            return None
        url = urls[0]
        remainder = task.replace(url, " ")

        matches: list[tuple[str, str]] = []
        for match in _EN_TEXT_ENTRY_RE.finditer(remainder):
            text = match.group(1)
            target_name = match.group(2).strip()
            if text and target_name:
                matches.append((text, target_name))
        for match in _ZH_TEXT_ENTRY_RE.finditer(remainder):
            target_name = match.group(1).strip()
            text = match.group(2)
            if text and target_name:
                matches.append((text, target_name))
        for match in _ZH_TEXT_ENTRY_RE_REVERSED.finditer(remainder):
            text = match.group(1)
            target_name = match.group(2).strip()
            if text and target_name:
                matches.append((text, target_name))

        unique: list[tuple[str, str]] = []
        for item in matches:
            if item not in unique:
                unique.append(item)
        if len(unique) != 1:
            return None
        text, target_name = unique[0]
        return url, target_name, text

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        if (
            event.payload.get("required_capabilities") is None
            and cls._natural_named_text_request(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_named_text_request(event)
        if request is not None:
            url, target_name, text = request
            intent = NativeActionIntent(
                intent_id=f"browser-named-text-{event.event_id}",
                event_id=event.event_id,
                kind=self._BROWSER_TYPE_NAMED_TEXT,
                args={"url": url, "target_name": target_name, "text": text},
                reason=(
                    "the current user Work supplies the exact browser URL, quoted plaintext "
                    "value and exact quoted accessible textbox name"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform body action: {self._BROWSER_TYPE_NAMED_TEXT}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied exact textbox authority and text "
                        "so ZN does not need a model to invent either"
                    )
                    self._persist_enriched_thought(thought)
                return None
        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    @staticmethod
    def _generic_guarded_side_effect(intent: NativeActionIntent) -> bool:
        if str(intent.kind or "").strip().lower() == "browser_type_named_text":
            return True
        return TerminalInputRecoveryResidentRuntime._generic_guarded_side_effect(intent)

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_intent = state.data.get("native_action_intent")
        if isinstance(raw_intent, dict):
            intent = NativeActionIntent.from_dict(raw_intent)
            recovered = self._durable_observed_named_text_result(event, intent)
            if recovered is not None:
                state.data["native_action_result"] = asdict(recovered)
                state.data.pop("local_failure", None)
                self._sync_execution_context(event, state)
                return self._complete_successful_body_action(
                    event,
                    state,
                    intent,
                    response=str(recovered.output or "text entry completed"),
                    reason=(
                        "ZN resumed the already durable, provider-verified named-textbox result "
                        "after interruption without replaying text entry"
                    ),
                )
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _durable_observed_named_text_result(
        self,
        event,
        intent: NativeActionIntent,
    ) -> BodyActionResult | None:
        kind = str(intent.kind or "").strip().lower()
        if kind != self._BROWSER_TYPE_NAMED_TEXT:
            return None
        signature_hash = self.body._signature_hash(kind, dict(intent.args))
        attempt = self.body._replay_blocking_attempt(
            event.event_id,
            signature_hash,
            include_observed=True,
        )
        if attempt is None or str(attempt["status"] or "").strip().lower() != "observed":
            return None
        if attempt["result_success"] != 1:
            return None
        result_action_id = str(attempt["result_action_id"] or "").strip()
        if not result_action_id:
            return None
        raw = self._native_body_result_row(
            action_id=result_action_id,
            event_id=event.event_id,
            kind=kind,
        )
        if raw is None:
            return None
        try:
            result = BodyActionResult(**raw)
        except (TypeError, ValueError):
            return None
        if not self._named_text_result_proves_intent(result, intent):
            return None
        return result

    @staticmethod
    def _named_text_result_proves_intent(
        result: BodyActionResult,
        intent: NativeActionIntent,
    ) -> bool:
        if result.success is not True:
            return False
        if result.event_id != intent.event_id:
            return False
        data = result.data if isinstance(result.data, dict) else {}
        evidence = data.get("browser_evidence")
        evidence_data = evidence.get("data") if isinstance(evidence, dict) else None
        url = str(intent.args.get("url") or "").strip()
        target_name = str(intent.args.get("target_name") or "").strip()
        text = intent.args.get("text")
        if not isinstance(text, str) or not text or not url or not target_name:
            return False
        expected_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected_length = len(text)
        postcondition = "same_exact_target_text_equals_requested"
        return bool(
            result.kind == "browser_type_named_text"
            and data.get("closed") is True
            and str(data.get("url") or "") == url
            and str(data.get("target_role") or "") == "textbox"
            and str(data.get("target_name") or "") == target_name
            and data.get("exact_node_continuity") is True
            and data.get("input_sent") is True
            and str(data.get("postcondition") or "") == postcondition
            and int(data.get("expected_text_length") or -1) == expected_length
            and str(data.get("expected_text_sha256") or "") == expected_digest
            and int(data.get("text_length_after") or -1) == expected_length
            and str(data.get("text_sha256_after") or "") == expected_digest
            and isinstance(evidence, dict)
            and evidence.get("success") is True
            and str(evidence.get("postcondition") or "") == postcondition
            and isinstance(evidence_data, dict)
            and evidence_data.get("exact_node_continuity") is True
            and evidence_data.get("input_sent") is True
            and int(evidence_data.get("expected_text_length") or -1) == expected_length
            and str(evidence_data.get("expected_text_sha256") or "") == expected_digest
            and int(evidence_data.get("text_length_after") or -1) == expected_length
            and str(evidence_data.get("text_sha256_after") or "") == expected_digest
        )

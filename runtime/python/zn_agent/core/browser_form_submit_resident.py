from __future__ import annotations

"""Ordinary Work ownership for bounded same-session browser form submission."""

import hashlib
import re
from dataclasses import asdict

from .action import NativeActionIntent
from .body import BodyActionResult
from .browser_form_submit_body import BrowserFormSubmitBody
from .browser_named_text_work_resident import BrowserNamedTextWorkResidentRuntime


_EN_FORM_RE = re.compile(
    r'\b(?:type|enter|fill)\s+["“]([^"”\r\n]{1,512})["”]\s+'
    r'(?:into|in)\s+(?:the\s+)?(?:textbox|field|input)\s+'
    r'["“]([^"”\r\n]{1,160})["”].{0,120}?'
    r'\b(?:click|press)\s+(?:the\s+)?button\s+["“]([^"”\r\n]{1,160})["”]',
    re.IGNORECASE,
)
_ZH_FORM_RE = re.compile(
    r'(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”]\s*'
    r'(?:中|里)?\s*(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”].{0,120}?'
    r'(?:点击|按下)\s*(?:按钮)?\s*["“]([^"”\r\n]{1,160})["”]'
)
_ZH_FORM_RE_REVERSED = re.compile(
    r'(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”]\s*'
    r'(?:到|进|至)\s*(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”].{0,120}?'
    r'(?:点击|按下)\s*(?:按钮)?\s*["“]([^"”\r\n]{1,160})["”]'
)
_EN_ENTER_FORM_RE = re.compile(
    r'\b(?:type|enter|fill)\s+["“]([^"”\r\n]{1,512})["”]\s+'
    r'(?:into|in)\s+(?:the\s+)?(?:textbox|field|input)\s+'
    r'["“]([^"”\r\n]{1,160})["”].{0,120}?'
    r'\b(?:press|hit)\s+(?:the\s+)?(?:enter|return)(?:\s+key)?\b',
    re.IGNORECASE,
)
_ZH_ENTER_FORM_RE = re.compile(
    r'(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”]\s*'
    r'(?:中|里)?\s*(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”].{0,120}?'
    r'(?:按下?|敲下?)\s*(?:Enter|回车)(?:键)?',
    re.IGNORECASE,
)
_ZH_ENTER_FORM_RE_REVERSED = re.compile(
    r'(?:输入|填写)\s*["“]([^"”\r\n]{1,512})["”]\s*'
    r'(?:到|进|至)\s*(?:文本框|输入框|字段)\s*["“]([^"”\r\n]{1,160})["”].{0,120}?'
    r'(?:按下?|敲下?)\s*(?:Enter|回车)(?:键)?',
    re.IGNORECASE,
)


class BrowserFormSubmitResidentRuntime(BrowserNamedTextWorkResidentRuntime):
    """Close explicit semantic form tasks without broad browser authority.

    A click-submit task must provide exactly two HTTP(S) URLs in order (start
    and expected destination), one quoted plaintext value, one exact quoted
    textbox name, and one exact quoted button name. A second MANAGED-only slice
    accepts the same explicit URLs/text/textbox authority when the user explicitly
    asks to press Enter. No model chooses the destination, targets, text, key, or
    expected result.
    """

    _BROWSER_FILL_AND_SUBMIT = "browser_fill_named_text_and_click_named_button_to_url"
    _BROWSER_FILL_AND_PRESS_ENTER = "browser_fill_named_text_and_press_enter_to_url"

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = BrowserFormSubmitBody(resident=self)
        installer = getattr(self, "_install_body_dispatch_health_observer", None)
        if callable(installer):
            installer()

    @classmethod
    def _natural_form_submit_request(
        cls,
        event,
    ) -> tuple[str, str, str, str, str] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 2:
            return None
        start_url, expected_url = urls
        remainder = task
        for url in urls:
            remainder = remainder.replace(url, " ")

        matches: list[tuple[str, str, str]] = []
        for match in _EN_FORM_RE.finditer(remainder):
            text = match.group(1)
            textbox_name = match.group(2).strip()
            button_name = match.group(3).strip()
            if text and textbox_name and button_name:
                matches.append((text, textbox_name, button_name))
        for match in _ZH_FORM_RE.finditer(remainder):
            textbox_name = match.group(1).strip()
            text = match.group(2)
            button_name = match.group(3).strip()
            if text and textbox_name and button_name:
                matches.append((text, textbox_name, button_name))
        for match in _ZH_FORM_RE_REVERSED.finditer(remainder):
            text = match.group(1)
            textbox_name = match.group(2).strip()
            button_name = match.group(3).strip()
            if text and textbox_name and button_name:
                matches.append((text, textbox_name, button_name))

        unique: list[tuple[str, str, str]] = []
        for item in matches:
            if item not in unique:
                unique.append(item)
        if len(unique) != 1:
            return None
        text, textbox_name, button_name = unique[0]
        return start_url, textbox_name, text, button_name, expected_url

    @classmethod
    def _natural_enter_submit_request(
        cls,
        event,
    ) -> tuple[str, str, str, str] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 2:
            return None
        start_url, expected_url = urls
        remainder = task
        for url in urls:
            remainder = remainder.replace(url, " ")

        matches: list[tuple[str, str]] = []
        for match in _EN_ENTER_FORM_RE.finditer(remainder):
            text = match.group(1)
            textbox_name = match.group(2).strip()
            if text and textbox_name:
                matches.append((text, textbox_name))
        for match in _ZH_ENTER_FORM_RE.finditer(remainder):
            textbox_name = match.group(1).strip()
            text = match.group(2)
            if text and textbox_name:
                matches.append((text, textbox_name))
        for match in _ZH_ENTER_FORM_RE_REVERSED.finditer(remainder):
            text = match.group(1)
            textbox_name = match.group(2).strip()
            if text and textbox_name:
                matches.append((text, textbox_name))

        unique: list[tuple[str, str]] = []
        for item in matches:
            if item not in unique:
                unique.append(item)
        if len(unique) != 1:
            return None
        text, textbox_name = unique[0]
        return start_url, textbox_name, text, expected_url

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        if event.payload.get("required_capabilities") is None and (
            cls._natural_enter_submit_request(event) is not None
            or cls._natural_form_submit_request(event) is not None
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
        enter_request = self._natural_enter_submit_request(event)
        if enter_request is not None:
            start_url, textbox_name, text, expected_url = enter_request
            intent = NativeActionIntent(
                intent_id=f"browser-form-enter-submit-{event.event_id}",
                event_id=event.event_id,
                kind=self._BROWSER_FILL_AND_PRESS_ENTER,
                args={
                    "url": start_url,
                    "textbox_name": textbox_name,
                    "text": text,
                    "expected_url": expected_url,
                },
                reason=(
                    "the current user Work supplies the exact managed-browser start URL, "
                    "quoted plaintext, exact semantic textbox name, explicit Enter key "
                    "interaction and explicit final URL"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform body action: {self._BROWSER_FILL_AND_PRESS_ENTER}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied all form, Enter-key and result "
                        "authority, so ZN can keep the bounded mutations in one managed-browser session"
                    )
                    self._persist_enriched_thought(thought)
                return None

        request = self._natural_form_submit_request(event)
        if request is not None:
            start_url, textbox_name, text, button_name, expected_url = request
            intent = NativeActionIntent(
                intent_id=f"browser-form-submit-{event.event_id}",
                event_id=event.event_id,
                kind=self._BROWSER_FILL_AND_SUBMIT,
                args={
                    "url": start_url,
                    "textbox_name": textbox_name,
                    "text": text,
                    "button_name": button_name,
                    "expected_url": expected_url,
                },
                reason=(
                    "the current user Work supplies the exact start URL, quoted plaintext, "
                    "exact semantic textbox and button names, and explicit final URL"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform body action: {self._BROWSER_FILL_AND_SUBMIT}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied all form and result authority, "
                        "so ZN can keep the bounded mutations in one managed-browser session"
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
        if str(intent.kind or "").strip().lower() in {
            BrowserFormSubmitResidentRuntime._BROWSER_FILL_AND_SUBMIT,
            BrowserFormSubmitResidentRuntime._BROWSER_FILL_AND_PRESS_ENTER,
        }:
            return True
        return BrowserNamedTextWorkResidentRuntime._generic_guarded_side_effect(intent)

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
            recovered = self._durable_observed_form_submit_result(event, intent)
            if recovered is not None:
                state.data["native_action_result"] = asdict(recovered)
                state.data.pop("local_failure", None)
                self._sync_execution_context(event, state)
                return self._complete_successful_body_action(
                    event,
                    state,
                    intent,
                    response=str(recovered.output or intent.args.get("expected_url") or ""),
                    reason=(
                        "ZN resumed the already durable, provider-verified form submission "
                        "after interruption without replaying text entry or the submit interaction"
                    ),
                )
        return super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _durable_observed_form_submit_result(
        self,
        event,
        intent: NativeActionIntent,
    ) -> BodyActionResult | None:
        kind = str(intent.kind or "").strip().lower()
        if kind not in {self._BROWSER_FILL_AND_SUBMIT, self._BROWSER_FILL_AND_PRESS_ENTER}:
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
        if kind == self._BROWSER_FILL_AND_SUBMIT:
            proven = self._form_submit_result_proves_intent(result, intent)
        else:
            proven = self._enter_submit_result_proves_intent(result, intent)
        if not proven:
            return None
        return result

    @staticmethod
    def _form_submit_result_proves_intent(
        result: BodyActionResult,
        intent: NativeActionIntent,
    ) -> bool:
        if result.success is not True or result.event_id != intent.event_id:
            return False
        data = result.data if isinstance(result.data, dict) else {}
        text_evidence = data.get("text_evidence")
        text_data = text_evidence.get("data") if isinstance(text_evidence, dict) else None
        submit_evidence = data.get("submit_evidence")
        submit_data = (
            submit_evidence.get("data") if isinstance(submit_evidence, dict) else None
        )
        url = str(intent.args.get("url") or "").strip()
        expected_url = str(intent.args.get("expected_url") or "").strip()
        textbox_name = str(intent.args.get("textbox_name") or "").strip()
        button_name = str(intent.args.get("button_name") or "").strip()
        text = intent.args.get("text")
        if (
            not isinstance(text, str)
            or not text
            or not url
            or not expected_url
            or not textbox_name
            or not button_name
        ):
            return False
        expected_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected_length = len(text)
        return bool(
            result.kind == BrowserFormSubmitResidentRuntime._BROWSER_FILL_AND_SUBMIT
            and data.get("closed") is True
            and str(data.get("url") or "") == url
            and str(data.get("expected_url") or "") == expected_url
            and str(data.get("observed_url") or "") == expected_url
            and str(data.get("textbox_name") or "") == textbox_name
            and str(data.get("button_name") or "") == button_name
            and int(data.get("expected_text_length") or -1) == expected_length
            and str(data.get("expected_text_sha256") or "") == expected_digest
            and int(data.get("text_length_after") or -1) == expected_length
            and str(data.get("text_sha256_after") or "") == expected_digest
            and str(data.get("text_postcondition") or "")
            == "same_exact_target_text_equals_requested"
            and data.get("text_exact_node_continuity") is True
            and isinstance(text_evidence, dict)
            and text_evidence.get("success") is True
            and isinstance(text_data, dict)
            and text_data.get("input_sent") is True
            and text_data.get("exact_node_continuity") is True
            and int(text_data.get("expected_text_length") or -1) == expected_length
            and str(text_data.get("expected_text_sha256") or "") == expected_digest
            and int(text_data.get("text_length_after") or -1) == expected_length
            and str(text_data.get("text_sha256_after") or "") == expected_digest
            and isinstance(submit_evidence, dict)
            and submit_evidence.get("success") is True
            and isinstance(submit_data, dict)
            and submit_data.get("target_revalidated_before_dispatch") is True
        )

    @staticmethod
    def _enter_submit_result_proves_intent(
        result: BodyActionResult,
        intent: NativeActionIntent,
    ) -> bool:
        if result.success is not True or result.event_id != intent.event_id:
            return False
        data = result.data if isinstance(result.data, dict) else {}
        text_evidence = data.get("text_evidence")
        text_data = text_evidence.get("data") if isinstance(text_evidence, dict) else None
        submit_evidence = data.get("submit_evidence")
        submit_data = (
            submit_evidence.get("data") if isinstance(submit_evidence, dict) else None
        )
        url = str(intent.args.get("url") or "").strip()
        expected_url = str(intent.args.get("expected_url") or "").strip()
        textbox_name = str(intent.args.get("textbox_name") or "").strip()
        text = intent.args.get("text")
        if (
            not isinstance(text, str)
            or not text
            or not url
            or not expected_url
            or not textbox_name
        ):
            return False
        expected_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected_length = len(text)
        return bool(
            result.kind == BrowserFormSubmitResidentRuntime._BROWSER_FILL_AND_PRESS_ENTER
            and data.get("closed") is True
            and str(data.get("url") or "") == url
            and str(data.get("expected_url") or "") == expected_url
            and str(data.get("observed_url") or "") == expected_url
            and str(data.get("textbox_name") or "") == textbox_name
            and str(data.get("submit_key") or "") == "Enter"
            and int(data.get("expected_text_length") or -1) == expected_length
            and str(data.get("expected_text_sha256") or "") == expected_digest
            and int(data.get("text_length_after") or -1) == expected_length
            and str(data.get("text_sha256_after") or "") == expected_digest
            and str(data.get("text_postcondition") or "")
            == "same_exact_target_text_equals_requested"
            and data.get("text_exact_node_continuity") is True
            and data.get("textbox_revalidated_before_enter") is True
            and data.get("text_revalidated_before_enter") is True
            and data.get("enter_dispatched") is True
            and str(data.get("submit_postcondition") or "")
            == "url_equals_after_fresh_semantic_textbox_enter"
            and isinstance(text_evidence, dict)
            and text_evidence.get("success") is True
            and isinstance(text_data, dict)
            and text_data.get("input_sent") is True
            and text_data.get("exact_node_continuity") is True
            and int(text_data.get("expected_text_length") or -1) == expected_length
            and str(text_data.get("expected_text_sha256") or "") == expected_digest
            and int(text_data.get("text_length_after") or -1) == expected_length
            and str(text_data.get("text_sha256_after") or "") == expected_digest
            and isinstance(submit_evidence, dict)
            and submit_evidence.get("success") is True
            and str(submit_evidence.get("postcondition") or "")
            == "url_equals_after_fresh_semantic_textbox_enter"
            and isinstance(submit_data, dict)
            and submit_data.get("target_revalidated_before_dispatch") is True
            and submit_data.get("text_revalidated_before_dispatch") is True
            and submit_data.get("press_sent") is True
            and str(submit_data.get("key") or "") == "Enter"
            and str(submit_data.get("expected_url") or "") == expected_url
            and int(submit_data.get("expected_text_length") or -1) == expected_length
            and str(submit_data.get("expected_text_sha256") or "") == expected_digest
        )

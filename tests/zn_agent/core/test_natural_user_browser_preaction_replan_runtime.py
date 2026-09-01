from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from zn_agent.core.user_browser_extension_relay import (
    AuthorizedUserBrowserTab,
    UserBrowserExtensionCommandUncertainError,
    UserBrowserExtensionRelayError,
)
from zn_agent.core.user_browser_extension_resident import UserBrowserExtensionResidentRuntime


_QUERY = "alice@example.test"
_OLD_URL = "https://example.test/account"
_NEW_URL = "https://example.test/account/updated"
_OLD_ACTION = "https://example.test/results"
_NEW_ACTION = "https://example.test/find"
_NEW_FINAL = "https://example.test/find?q=alice%40example.test"
_OLD_TEXTBOX_ID = "backend:101"
_OLD_BUTTON_ID = "backend:102"
_NEW_TEXTBOX_ID = "backend:201"
_NEW_BUTTON_ID = "backend:202"
_TEXTBOX_NAME = "Account search"
_BUTTON_NAME = "Search"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _ReplanningSearchRelay:
    """In-memory extension peer that changes the page between Sense and action admission."""

    def __init__(
        self,
        *,
        reject_fresh_search: bool = False,
        uncertain_type: bool = False,
        contradict_final_page: bool = False,
    ) -> None:
        self.tab_id = 71
        self.current_url = _OLD_URL
        self.text = ""
        self.discovery_calls = 0
        self.type_calls = 0
        self.click_calls = 0
        self.final_page_probes = 0
        self.reject_fresh_search = reject_fresh_search
        self.uncertain_type = uncertain_type
        self.contradict_final_page = contradict_final_page
        self.commands: list[tuple[str, dict]] = []
        self.mutated_target_ids: list[str] = []

    def authorized_tab(self):
        return AuthorizedUserBrowserTab(
            tab_id=self.tab_id,
            url=self.current_url,
            title="Account",
            attached_at="2026-09-01T00:00:00Z",
        )

    def request_command(self, kind, *, args=None, timeout_seconds=5.0):
        del timeout_seconds
        command_args = dict(args or {})
        self.commands.append((str(kind), command_args))

        if kind == "probe_current_tab" and command_args.get("discover_unique_search_form") is True:
            self.discovery_calls += 1
            if self.discovery_calls == 1:
                result = self._search_form(
                    url=_OLD_URL,
                    action=_OLD_ACTION,
                    textbox_id=_OLD_TEXTBOX_ID,
                    button_id=_OLD_BUTTON_ID,
                )
                # The first observation is now stale: the same authorized tab
                # refreshes/routes and rebuilds the form before deliberation.
                self.current_url = _NEW_URL
                return self._success(result)
            if self.reject_fresh_search:
                raise UserBrowserExtensionRelayError(
                    "fresh page exposes only a sensitive password, OTP, identity-authentication, or payment field"
                )
            return self._success(
                self._search_form(
                    url=_NEW_URL,
                    action=_NEW_ACTION,
                    textbox_id=_NEW_TEXTBOX_ID,
                    button_id=_NEW_BUTTON_ID,
                )
            )

        if kind == "probe_current_tab":
            if self.click_calls:
                self.final_page_probes += 1
            return self._success(
                {
                    "tab_id": self.tab_id,
                    "url": self.current_url,
                    "title": "Search results" if self.click_calls else "Account updated",
                }
            )

        if kind == "observe_named_textbox":
            self._require_name(command_args, _TEXTBOX_NAME)
            return self._success(
                {
                    "tab_id": self.tab_id,
                    "url": self.current_url,
                    "title": "Account updated",
                    "target_id": _NEW_TEXTBOX_ID,
                    "role": "searchbox",
                    "name": _TEXTBOX_NAME,
                    "text_length": len(self.text),
                    "text_sha256": _digest(self.text),
                }
            )

        if kind == "type_named_textbox":
            self.type_calls += 1
            self._require_name(command_args, _TEXTBOX_NAME)
            if command_args.get("target_id") != _NEW_TEXTBOX_ID:
                raise AssertionError("stale textbox identity reached the mutation boundary")
            if command_args.get("expected_url") != _NEW_URL:
                raise AssertionError("stale page URL reached the mutation boundary")
            if command_args.get("text") != _QUERY:
                raise AssertionError("unexpected search text")
            self.mutated_target_ids.append(str(command_args["target_id"]))
            if self.uncertain_type:
                raise UserBrowserExtensionCommandUncertainError(
                    "browser extension command result was lost after delivery; side effect may have occurred"
                )
            before = self.text
            self.text = _QUERY
            return self._success(
                {
                    "tab_id": self.tab_id,
                    "url_before": _NEW_URL,
                    "url_after": _NEW_URL,
                    "target_id": _NEW_TEXTBOX_ID,
                    "input_sent": True,
                    "exact_node_continuity": True,
                    "text_length_before": len(before),
                    "text_sha256_before": _digest(before),
                    "text_length_after": len(_QUERY),
                    "text_sha256_after": _digest(_QUERY),
                    "expected_text_length": len(_QUERY),
                    "expected_text_sha256": _digest(_QUERY),
                    "expected_utf16_units": len(_QUERY.encode("utf-16-le")) // 2,
                    "postcondition": "same_exact_target_text_equals_requested",
                }
            )

        if kind == "observe_named_button":
            self._require_name(command_args, _BUTTON_NAME)
            return self._success(
                {
                    "tab_id": self.tab_id,
                    "url": _NEW_URL,
                    "title": "Account updated",
                    "target_id": _NEW_BUTTON_ID,
                    "role": "button",
                    "name": _BUTTON_NAME,
                }
            )

        if kind == "click_named_button_to_url":
            self.click_calls += 1
            self._require_name(command_args, _BUTTON_NAME)
            if command_args.get("target_id") != _NEW_BUTTON_ID:
                raise AssertionError("stale button identity reached the mutation boundary")
            if command_args.get("expected_url_before") != _NEW_URL:
                raise AssertionError("stale page URL reached the click boundary")
            if command_args.get("expected_url_after") != _NEW_FINAL:
                raise AssertionError("unexpected final URL authority")
            if self.text != _QUERY:
                raise AssertionError("submit click occurred without the requested retained text")
            self.mutated_target_ids.append(str(command_args["target_id"]))
            if not self.contradict_final_page:
                self.current_url = _NEW_FINAL
            return self._success(
                {
                    "tab_id": self.tab_id,
                    "url_before": _NEW_URL,
                    "url_after": _NEW_FINAL,
                    "target_id": _NEW_BUTTON_ID,
                    "click_sent": True,
                    "exact_node_continuity": True,
                    "target_revalidated_before_dispatch": True,
                    "expected_url": _NEW_FINAL,
                    "postcondition": "url_equals_after_fresh_semantic_button_click",
                }
            )

        raise AssertionError(f"unexpected extension command: {kind}")

    def _search_form(self, *, url: str, action: str, textbox_id: str, button_id: str) -> dict:
        return {
            "tab_id": self.tab_id,
            "url": url,
            "title": "Account",
            "form_method": "get",
            "form_action": action,
            "query_parameter": "q",
            "textbox_target_id": textbox_id,
            "textbox_name": _TEXTBOX_NAME,
            "button_target_id": button_id,
            "button_name": _BUTTON_NAME,
        }

    @staticmethod
    def _success(result: dict) -> dict:
        return {
            "success": True,
            "result": result,
            "completed_at": "2026-09-01T00:00:01Z",
        }

    @staticmethod
    def _require_name(args: dict, expected: str) -> None:
        if args.get("target_name") != expected:
            raise AssertionError(f"unexpected exact target name: {args.get('target_name')!r}")


class NaturalUserBrowserPreactionReplanRuntimeTests(unittest.TestCase):
    def _run(self, task: str, relay: _ReplanningSearchRelay):
        temp = tempfile.TemporaryDirectory()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=Path(temp.name) / "kernel.db",
        )
        self.assertIsInstance(resident, UserBrowserExtensionResidentRuntime)
        resident.user_browser_extension = relay
        resident._extension_user_browser = AuthorizedExtensionUserBrowser(relay)
        try:
            result = resident.submit(task, payload={"model_policy": "never"})
            return result
        finally:
            resident.store.close()
            temp.cleanup()

    def test_formal_runtime_replans_changed_page_and_completes_for_two_natural_phrasings(self) -> None:
        tasks = (
            f"Search this page for {_QUERY}.",
            f"在当前页面查找 {_QUERY}",
        )
        for task in tasks:
            with self.subTest(task=task):
                relay = _ReplanningSearchRelay()
                result = self._run(task, relay)

                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertIn(_NEW_FINAL, result.response)
                self.assertGreaterEqual(relay.discovery_calls, 4)
                self.assertEqual(relay.type_calls, 1)
                self.assertEqual(relay.click_calls, 1)
                self.assertGreaterEqual(relay.final_page_probes, 1)
                self.assertEqual(
                    relay.mutated_target_ids,
                    [_NEW_TEXTBOX_ID, _NEW_BUTTON_ID],
                )
                self.assertNotIn(_OLD_TEXTBOX_ID, relay.mutated_target_ids)
                self.assertNotIn(_OLD_BUTTON_ID, relay.mutated_target_ids)

    def test_fresh_sensitive_page_refusal_never_falls_back_to_stale_binding(self) -> None:
        relay = _ReplanningSearchRelay(reject_fresh_search=True)
        result = self._run(f"Search this page for {_QUERY}.", relay)

        self.assertFalse(result.success)
        self.assertGreaterEqual(relay.discovery_calls, 2)
        self.assertEqual(relay.type_calls, 0)
        self.assertEqual(relay.click_calls, 0)
        self.assertEqual(relay.mutated_target_ids, [])

    def test_uncertain_delivered_text_side_effect_is_not_replayed(self) -> None:
        relay = _ReplanningSearchRelay(uncertain_type=True)
        result = self._run(f"Search this page for {_QUERY}.", relay)

        self.assertFalse(result.success)
        self.assertEqual(relay.type_calls, 1)
        self.assertEqual(relay.click_calls, 0)
        type_commands = [kind for kind, _args in relay.commands if kind == "type_named_textbox"]
        self.assertEqual(type_commands, ["type_named_textbox"])

    def test_click_success_evidence_is_not_completion_without_fresh_final_page_state(self) -> None:
        relay = _ReplanningSearchRelay(contradict_final_page=True)
        result = self._run(f"Search this page for {_QUERY}.", relay)

        self.assertFalse(result.success)
        self.assertEqual(relay.type_calls, 1)
        self.assertEqual(relay.click_calls, 1)
        self.assertGreaterEqual(relay.final_page_probes, 1)
        self.assertNotEqual(relay.current_url, _NEW_FINAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)

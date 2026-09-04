from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.user_browser_extension_relay import (
    AuthorizedUserBrowserTab,
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionCommandUncertainError,
    UserBrowserExtensionRelayError,
)
from zn_agent.core.user_browser_extension_resident import UserBrowserExtensionResidentRuntime
from zn_agent.core.user_browser_managed_research_resident import (
    UserBrowserManagedResearchResidentRuntime,
)


class _TaskContextRelay:
    def __init__(self) -> None:
        self.current = AuthorizedUserBrowserTab(
            tab_id=41,
            url="https://example.test/account",
            title="Account",
            attached_at="auth-a",
        )

    def authorized_tab(self):
        return self.current


class _Store:
    def __init__(self) -> None:
        self.saved_events = []
        self.saved_states = []

    def _save_event(self, event) -> None:
        self.saved_events.append(event)

    def save_working_state(self, state) -> None:
        self.saved_states.append(state)


class UserBrowserTaskContextIdentityTests(unittest.TestCase):
    def test_same_tab_reauthorization_cannot_receive_old_pending_command(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(
            tab_id=17,
            url="https://example.test/account",
            title="Account",
        )
        original = relay.authorized_tab()
        self.assertIsNotNone(original)
        outcome: dict[str, object] = {}

        def request() -> None:
            try:
                outcome["result"] = relay.request_command(
                    "probe_current_tab",
                    timeout_seconds=3.0,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=request)
        worker.start()
        try:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if relay.status()["pending_commands"] == 1:
                    break
                time.sleep(0.01)
            self.assertEqual(relay.status()["pending_commands"], 1)

            relay.revoke(tab_id=17)
            relay.authorize(
                tab_id=17,
                url="https://example.test/account",
                title="Account reauthorized",
            )
            replacement = relay.authorized_tab()
            self.assertIsNotNone(replacement)
            self.assertNotEqual(original.attached_at, replacement.attached_at)

            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(outcome.get("error"), UserBrowserExtensionRelayError)
            self.assertNotIsInstance(
                outcome.get("error"),
                UserBrowserExtensionCommandUncertainError,
            )
            self.assertNotIn("result", outcome)
            self.assertIsNone(relay.next_command(tab_id=17, wait_seconds=0))
        finally:
            relay.close()
            worker.join(timeout=2.0)

    def test_same_tab_reauthorization_makes_delivered_command_uncertain_not_replayable(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(
            tab_id=23,
            url="https://example.test/account",
            title="Account",
        )
        outcome: dict[str, object] = {}

        def request() -> None:
            try:
                outcome["result"] = relay.request_command(
                    "type_named_textbox",
                    args={"target_name": "Customer", "target_id": "backend:1", "expected_url": "https://example.test/account", "text": "alice@example.test"},
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=request)
        worker.start()
        try:
            command = relay.next_command(tab_id=23, wait_seconds=1.0)
            self.assertIsNotNone(command)
            self.assertEqual(relay.status()["inflight_commands"], 1)
            original_generation = str(command["authorization_attached_at"])

            relay.revoke(tab_id=23)
            relay.authorize(
                tab_id=23,
                url="https://example.test/account",
                title="Account reauthorized",
            )
            current = relay.authorized_tab()
            self.assertIsNotNone(current)
            self.assertNotEqual(original_generation, current.attached_at)

            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(
                outcome.get("error"),
                UserBrowserExtensionCommandUncertainError,
            )
            self.assertNotIn("result", outcome)
            with self.assertRaises(UserBrowserExtensionRelayError):
                relay.complete_command(
                    tab_id=23,
                    command_id=command["command_id"],
                    success=True,
                    result={"tab_id": 23},
                )
        finally:
            relay.close()
            worker.join(timeout=2.0)

    def test_delivered_exact_click_can_register_only_its_direct_expected_child(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(
            tab_id=31,
            url="https://example.test/account",
            title="Account",
        )
        outcome: dict[str, object] = {}

        def request_click() -> None:
            try:
                outcome["result"] = relay.request_command(
                    "click_named_button_to_url",
                    args={
                        "target_name": "查询订单",
                        "target_id": "backend:9",
                        "expected_url_before": "https://example.test/account",
                        "expected_url_after": "https://example.test/results?customer=alice",
                        "expect_direct_child": True,
                    },
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=request_click)
        worker.start()
        try:
            command = relay.next_command(tab_id=31, wait_seconds=1.0)
            self.assertIsNotNone(command)
            with self.assertRaisesRegex(UserBrowserExtensionRelayError, "opener"):
                relay.authorize_child_from_command(
                    tab_id=31,
                    command_id=command["command_id"],
                    child_tab_id=44,
                    opener_tab_id=99,
                    url="https://example.test/results?customer=alice",
                    title="Result",
                )
            with self.assertRaisesRegex(UserBrowserExtensionRelayError, "expected result URL"):
                relay.authorize_child_from_command(
                    tab_id=31,
                    command_id=command["command_id"],
                    child_tab_id=44,
                    opener_tab_id=31,
                    url="https://example.test/results?customer=bob",
                    title="Result",
                )

            registered = relay.authorize_child_from_command(
                tab_id=31,
                command_id=command["command_id"],
                child_tab_id=44,
                opener_tab_id=31,
                url="https://example.test/results?customer=alice",
                title="Result",
            )
            self.assertTrue(registered["registered"])
            self.assertEqual(registered["child"]["tab_id"], 44)
            self.assertEqual(relay.status()["authorized_child_pages"], 1)

            relay.complete_command(
                tab_id=31,
                command_id=command["command_id"],
                success=True,
                result={"tab_id": 44, "postcondition": "direct_child_verified"},
            )
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertNotIn("error", outcome)
            self.assertEqual(outcome["result"]["target_tab_id"], 31)
        finally:
            relay.close()
            worker.join(timeout=2.0)

    def test_registered_child_receives_commands_but_unrelated_tab_never_does(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.start()
        relay.authorize(tab_id=51, url="https://example.test/account", title="Account")
        click_outcome: dict[str, object] = {}

        def click_request() -> None:
            try:
                click_outcome["result"] = relay.request_command(
                    "click_named_button_to_url",
                    args={
                        "expected_url_after": "https://example.test/result",
                        "expect_direct_child": True,
                    },
                    timeout_seconds=5.0,
                )
            except Exception as exc:
                click_outcome["error"] = exc

        click_worker = threading.Thread(target=click_request)
        click_worker.start()
        try:
            click_command = relay.next_command(tab_id=51, wait_seconds=1.0)
            self.assertIsNotNone(click_command)
            relay.authorize_child_from_command(
                tab_id=51,
                command_id=click_command["command_id"],
                child_tab_id=52,
                opener_tab_id=51,
                url="https://example.test/result",
                title="Result",
            )
            relay.complete_command(
                tab_id=51,
                command_id=click_command["command_id"],
                success=True,
                result={"tab_id": 52},
            )
            click_worker.join(timeout=2.0)

            with self.assertRaisesRegex(UserBrowserExtensionRelayError, "not part"):
                relay.request_command(
                    "probe_current_tab",
                    target_tab_id=99,
                    timeout_seconds=0.1,
                )

            outcome: dict[str, object] = {}

            def probe_child() -> None:
                try:
                    outcome["result"] = relay.request_command(
                        "probe_current_tab",
                        target_tab_id=52,
                        timeout_seconds=5.0,
                    )
                except Exception as exc:
                    outcome["error"] = exc

            worker = threading.Thread(target=probe_child)
            worker.start()
            command = relay.next_command(tab_id=51, wait_seconds=1.0)
            self.assertIsNotNone(command)
            self.assertEqual(command["tab_id"], 51)
            self.assertEqual(command["target_tab_id"], 52)
            relay.complete_command(
                tab_id=51,
                command_id=command["command_id"],
                success=True,
                result={"tab_id": 52, "url": "https://example.test/result"},
            )
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertNotIn("error", outcome)
        finally:
            relay.close()
            click_worker.join(timeout=2.0)

    def test_work_context_pins_tab_authorization_generation_not_foreground_or_title(self) -> None:
        resident = UserBrowserManagedResearchResidentRuntime.__new__(
            UserBrowserManagedResearchResidentRuntime
        )
        relay = _TaskContextRelay()
        resident.user_browser_extension = relay
        resident.store = _Store()
        resident._sync_execution_context = lambda event, state: None
        resident.probe_user_browser_extension_tab = lambda: {
            "tab_id": relay.current.tab_id,
            "url": relay.current.url,
            "title": relay.current.title,
        }
        event = SimpleNamespace(payload={}, task="查一下 alice@example.test 的订单状态")
        state = SimpleNamespace(data={})

        bound = resident._ensure_user_browser_task_context(event, state)
        self.assertEqual(bound["tab_id"], 41)
        self.assertEqual(bound["attached_at"], "auth-a")
        self.assertEqual(bound["origin"], "https://example.test")

        # Title and path are page state, not task authority.
        relay.current = AuthorizedUserBrowserTab(
            tab_id=41,
            url="https://example.test/account?fresh=1",
            title="Completely different title",
            attached_at="auth-a",
        )
        fresh = resident._ensure_user_browser_task_context(event, state)
        self.assertEqual(fresh["attached_at"], "auth-a")

        # Re-authorizing even the same tab is a new authority generation and
        # cannot silently inherit the existing Work.
        relay.current = AuthorizedUserBrowserTab(
            tab_id=41,
            url="https://example.test/account?fresh=1",
            title="Looks identical",
            attached_at="auth-b",
        )
        with self.assertRaisesRegex(
            UserBrowserExtensionRelayError,
            "not the authorization that owns this Work",
        ):
            resident._ensure_user_browser_task_context(event, state)

    def test_browser_action_cycle_carries_only_resident_owned_context_evidence(self) -> None:
        resident = UserBrowserManagedResearchResidentRuntime.__new__(
            UserBrowserManagedResearchResidentRuntime
        )
        state = SimpleNamespace(
            data={
                resident._USER_BROWSER_TASK_CONTEXT_KEY: {
                    "tab_id": 52,
                    "attached_at": "auth-52",
                    "origin": "https://example.test",
                }
            }
        )
        event = SimpleNamespace(event_id="event-1")
        intent = NativeActionIntent(
            intent_id="intent-1",
            event_id="event-1",
            kind="browser_type_named_text",
            args={
                "url": "https://example.test/account",
                "target_name": "Customer",
                "text": "alice@example.test",
            },
        )
        sentinel = object()

        with patch.object(
            UserBrowserExtensionResidentRuntime,
            "_begin_native_action_cycle",
            autospec=True,
            return_value=sentinel,
        ) as parent:
            result = resident._begin_native_action_cycle(event, state, intent)

        self.assertIs(result, sentinel)
        forwarded = parent.call_args.args[3]
        self.assertEqual(forwarded.args["authorized_tab_id"], 52)
        self.assertEqual(forwarded.args["authorization_attached_at"], "auth-52")
        self.assertEqual(forwarded.args["target_name"], "Customer")


if __name__ == "__main__":
    unittest.main(verbosity=2)

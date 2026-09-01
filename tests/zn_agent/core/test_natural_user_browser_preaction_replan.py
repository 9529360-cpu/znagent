from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.user_browser_extension_resident import UserBrowserExtensionResidentRuntime


class _AuthorizedRelay:
    @staticmethod
    def authorized_tab():
        return SimpleNamespace(tab_id=17)


class _Store:
    def __init__(self) -> None:
        self.saved = 0

    def save_working_state(self, state) -> None:
        self.saved += 1


class NaturalUserBrowserPreactionReplanTests(unittest.TestCase):
    def test_changed_current_page_returns_to_investigation_before_any_body_action(self) -> None:
        resident = object.__new__(UserBrowserExtensionResidentRuntime)
        resident.user_browser_extension = _AuthorizedRelay()
        resident.store = _Store()
        resident._adopt_authorized_extension_browser = lambda: None
        resident._sync_execution_context = lambda event, state: None

        old = {
            "url": "https://example.test/account",
            "textbox_name": "Account search",
            "textbox_target_id": "backend:101",
            "button_name": "Search",
            "button_target_id": "backend:102",
            "expected_url": "https://example.test/results?q=alice%40example.test",
            "query_parameter": "q",
            "observed_at": "old",
            "source": "zn_browser_extension_search_discovery",
        }
        changed = {
            "url": "https://example.test/account/updated",
            "textbox_name": "Account search",
            "textbox_target_id": "backend:201",
            "button_name": "Search",
            "button_target_id": "backend:202",
            "expected_url": "https://example.test/find?q=alice%40example.test",
            "query_parameter": "q",
            "observed_at": "fresh",
            "source": "zn_browser_extension_search_discovery",
        }
        resident._discover_unique_search_form = lambda query: dict(changed)

        body_actions: list[object] = []
        resident._action_blocked_by_current_evidence = lambda event, state, intent: False
        resident._begin_native_action_cycle = lambda event, state, intent: body_actions.append(intent)

        event = SimpleNamespace(
            event_id="evt-search-replan",
            task="Search this page for alice@example.test.",
            payload={"model_policy": "never"},
        )
        state = SimpleNamespace(
            data={resident._NATURAL_SEARCH_STATE_KEY: dict(old)},
            stage="native_deliberation",
            next_action="form search movement",
        )

        result = UserBrowserExtensionResidentRuntime._deliberation_step(
            resident,
            event,
            state,
            readiness=None,
            learning_evidence=[],
            thought=None,
        )

        self.assertIsNone(result)
        self.assertEqual(body_actions, [])
        self.assertEqual(state.stage, "native_investigation")
        self.assertIn("newly observed current page", state.next_action)
        self.assertEqual(state.data[resident._NATURAL_SEARCH_STATE_KEY], changed)
        self.assertNotIn("local_failure", state.data)
        self.assertEqual(resident.store.saved, 1)

    def test_unchanged_fresh_binding_admits_guarded_form_action(self) -> None:
        resident = object.__new__(UserBrowserExtensionResidentRuntime)
        resident.user_browser_extension = _AuthorizedRelay()
        resident.store = _Store()
        resident._adopt_authorized_extension_browser = lambda: None
        resident._sync_execution_context = lambda event, state: None

        evidence = {
            "url": "https://example.test/account",
            "textbox_name": "Account search",
            "textbox_target_id": "backend:101",
            "button_name": "Search",
            "button_target_id": "backend:102",
            "expected_url": "https://example.test/results?q=alice%40example.test",
            "query_parameter": "q",
            "observed_at": "old",
            "source": "zn_browser_extension_search_discovery",
        }
        fresh = dict(evidence)
        fresh["observed_at"] = "fresh"
        resident._discover_unique_search_form = lambda query: dict(fresh)
        resident._action_blocked_by_current_evidence = lambda event, state, intent: False

        admitted = []

        def begin(event, state, intent) -> None:
            admitted.append(intent)
            state.stage = "native_action"

        resident._begin_native_action_cycle = begin

        event = SimpleNamespace(
            event_id="evt-search-current",
            task="Search this page for alice@example.test.",
            payload={"model_policy": "never"},
        )
        state = SimpleNamespace(
            data={resident._NATURAL_SEARCH_STATE_KEY: dict(evidence)},
            stage="native_deliberation",
            next_action="form search movement",
        )

        result = UserBrowserExtensionResidentRuntime._deliberation_step(
            resident,
            event,
            state,
            readiness=None,
            learning_evidence=[],
            thought=None,
        )

        self.assertIsNone(result)
        self.assertEqual(len(admitted), 1)
        intent = admitted[0]
        self.assertEqual(intent.kind, resident._BROWSER_FILL_AND_SUBMIT)
        self.assertEqual(intent.args["url"], evidence["url"])
        self.assertEqual(intent.args["textbox_name"], evidence["textbox_name"])
        self.assertEqual(intent.args["button_name"], evidence["button_name"])
        self.assertEqual(intent.args["expected_url"], evidence["expected_url"])
        self.assertEqual(intent.args["text"], "alice@example.test")
        self.assertEqual(state.data[resident._NATURAL_SEARCH_STATE_KEY]["observed_at"], "fresh")
        self.assertEqual(resident.store.saved, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""W-4 ConversationDriver: enum + three predicates + site mapping.

Pins the driver triples (turn lifecycle owner / tools execute locally /
input rebuild source), the frozen site mapping (every existing mode
mapped, unknown sites fail closed), and the declarative wiring
(class attributes on the four owner classes).
"""

from __future__ import annotations

import unittest

from zn_agent.core.agentic_tool_loop import AgenticToolLoop
from zn_agent.core.conversation_driver import (
    CONVERSATION_SITES,
    ConversationDriver,
    InputRebuildSource,
    TurnLifecycleOwner,
    describe,
    driver_for_site,
    input_rebuild_source,
    tools_execute_locally,
    turn_lifecycle_owner,
)
from zn_agent.core.resident import ZNResidentRuntime
from zn_agent.core.team_work_owner import TeamWorkOwner
from zn_agent.core.veteran_work_owner import VeteranEngineeringWorkOwner


class ConversationDriverPredicateTests(unittest.TestCase):
    def test_every_driver_has_exactly_its_triple(self) -> None:
        expected = {
            ConversationDriver.RESIDENT_PULSE: (
                TurnLifecycleOwner.ZN_RESIDENT,
                True,
                InputRebuildSource.DURABLE_STATE,
            ),
            ConversationDriver.MODEL_TOOL_LOOP: (
                TurnLifecycleOwner.MODEL,
                True,
                InputRebuildSource.MESSAGE_LIST,
            ),
            ConversationDriver.EXTERNAL_WORKER: (
                TurnLifecycleOwner.EXTERNAL_WORKER,
                False,
                InputRebuildSource.EXTERNAL,
            ),
        }
        self.assertEqual(set(expected), set(ConversationDriver))
        for driver, triple in expected.items():
            with self.subTest(driver=driver.value):
                self.assertEqual(turn_lifecycle_owner(driver), triple[0])
                self.assertEqual(tools_execute_locally(driver), triple[1])
                self.assertEqual(input_rebuild_source(driver), triple[2])

    def test_no_two_drivers_share_a_triple(self) -> None:
        triples = [
            (
                turn_lifecycle_owner(driver),
                tools_execute_locally(driver),
                input_rebuild_source(driver),
            )
            for driver in ConversationDriver
        ]
        self.assertEqual(len(set(triples)), len(triples))

    def test_enum_values_are_stable_strings(self) -> None:
        self.assertEqual(ConversationDriver.RESIDENT_PULSE.value, "resident_pulse")
        self.assertEqual(ConversationDriver.MODEL_TOOL_LOOP.value, "model_tool_loop")
        self.assertEqual(ConversationDriver.EXTERNAL_WORKER.value, "external_worker")


class ConversationDriverSiteMappingTests(unittest.TestCase):
    def test_site_set_is_frozen(self) -> None:
        # A new conversation-driving mode must add its site here
        # explicitly instead of silently going unmapped.
        self.assertEqual(
            set(CONVERSATION_SITES),
            {
                "ordinary",
                "broad_goal",
                "generic_action",
                "model_led_generic_action",
                "team",
                "delegated_subagent",
                "model_tool_loop",
                "veteran_mission",
            },
        )

    def test_every_site_resolves_to_its_driver(self) -> None:
        expected = {
            "ordinary": ConversationDriver.RESIDENT_PULSE,
            "broad_goal": ConversationDriver.RESIDENT_PULSE,
            "generic_action": ConversationDriver.RESIDENT_PULSE,
            "model_led_generic_action": ConversationDriver.RESIDENT_PULSE,
            "team": ConversationDriver.RESIDENT_PULSE,
            "delegated_subagent": ConversationDriver.RESIDENT_PULSE,
            "model_tool_loop": ConversationDriver.MODEL_TOOL_LOOP,
            "veteran_mission": ConversationDriver.EXTERNAL_WORKER,
        }
        for site, driver in expected.items():
            with self.subTest(site=site):
                self.assertIs(driver_for_site(site), driver)

    def test_unknown_site_fails_closed(self) -> None:
        for unknown in ("", "team_lead", "warp", "resident", "RESIDENT_PULSE"):
            with self.subTest(site=unknown):
                with self.assertRaises(ValueError):
                    driver_for_site(unknown)

    def test_describe_round_trips_predicates_and_sites(self) -> None:
        for driver in ConversationDriver:
            with self.subTest(driver=driver.value):
                info = describe(driver)
                self.assertEqual(info["driver"], driver.value)
                self.assertEqual(
                    info["turn_lifecycle_owner"],
                    turn_lifecycle_owner(driver).value,
                )
                self.assertEqual(
                    info["tools_execute_locally"],
                    tools_execute_locally(driver),
                )
                self.assertEqual(
                    info["input_rebuild_source"],
                    input_rebuild_source(driver).value,
                )
                self.assertEqual(
                    info["sites"],
                    [
                        site
                        for site in CONVERSATION_SITES
                        if driver_for_site(site) is driver
                    ],
                )


class ConversationDriverWiringTests(unittest.TestCase):
    def test_owner_class_attributes_match_the_mapping(self) -> None:
        # Declarative wiring only: no behavior branches on these.
        self.assertIs(
            ZNResidentRuntime.conversation_driver,
            driver_for_site("ordinary"),
        )
        self.assertIs(
            TeamWorkOwner.conversation_driver,
            driver_for_site("team"),
        )
        self.assertIs(
            AgenticToolLoop.conversation_driver,
            driver_for_site("model_tool_loop"),
        )
        self.assertIs(
            VeteranEngineeringWorkOwner.conversation_driver,
            driver_for_site("veteran_mission"),
        )


if __name__ == "__main__":
    unittest.main()

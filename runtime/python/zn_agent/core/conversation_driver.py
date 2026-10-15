from __future__ import annotations

"""W-4 ConversationDriver: one explicit shape for ZN's conversation drivers.

This module borrows only the *mechanism shape* of Warp's
ConversationDriver split -- a driver enum plus three predicates saying
who owns the turn lifecycle, who executes tool calls locally, and who
rebuilds the input from messages. It contains no Warp code (Warp's
client is AGPL-3.0; copying its code into ZN would force ZN to be
AGPL-licensed). It also introduces no new runtime: every driver below
names a conversation-driving shape ZN already has, and the mapping in
:func:`driver_for_site` is the whole point -- existing modes expressed
in one clean vocabulary, not a new execution path.

The three predicates, in the order they are always stated:

1. ``turn_lifecycle_owner`` -- who decides that a turn starts, what
   happens in it, and when the conversation is done.
2. ``tools_execute_locally`` -- whether ZN itself executes the tool
   calls (through the Body / Action Fabric / local tool runner), or
   whether they run somewhere else.
3. ``input_rebuild_source`` -- what the next turn's input is rebuilt
   from: ZN's durable state (event / ledger / working state), an
   in-memory message list replayed each turn, or the external
   worker's own state (ZN does not rebuild it).

What the predicates deliberately do NOT capture: who *proposes* the
next step (in model-led generic action the model proposes, but ZN
still owns the event, ledger, authorization, verification and
recovery -- so it is still the resident-pulse driver), and which
dispatch branch or state shape a resident event uses (team, broad
goal, generic action are dispatch branches inside the one resident
pulse, not separate drivers).

Transports and input adapters are not drivers: the stdio JSON-RPC
server (``daemon.ResidentRpcServer``), the TCP socket service
(``resident_server.ResidentSocketService``) and the channel
supervisor (``channel_runtime``) all feed events into the resident
pulse; they do not own a turn lifecycle of their own.
"""

from enum import Enum


class TurnLifecycleOwner(str, Enum):
    """Who owns a conversation's turn lifecycle."""

    ZN_RESIDENT = "zn_resident"
    MODEL = "model"
    EXTERNAL_WORKER = "external_worker"


class InputRebuildSource(str, Enum):
    """What the next turn's input is rebuilt from."""

    DURABLE_STATE = "durable_state"
    MESSAGE_LIST = "message_list"
    EXTERNAL = "external"


class ConversationDriver(str, Enum):
    """The conversation-driving shapes ZN already has."""

    #: ZN's resident pulse owns the turn lifecycle, executes tools
    #: locally, and rebuilds each turn's input from durable state.
    RESIDENT_PULSE = "resident_pulse"
    #: The model owns the turn lifecycle (it decides the next tool call
    #: or that it is done), ZN executes the tool calls locally, and the
    #: input is rebuilt from the in-memory message list each turn.
    MODEL_TOOL_LOOP = "model_tool_loop"
    #: An external worker owns the turn lifecycle and executes its own
    #: tools; ZN only plans, advances and polls the mission, and does
    #: not rebuild the worker's input.
    EXTERNAL_WORKER = "external_worker"


#: The single source of truth for the three predicates: driver ->
#: (turn lifecycle owner, tools execute locally, input rebuild source).
_DRIVER_TRIPLES: dict[
    ConversationDriver, tuple[TurnLifecycleOwner, bool, InputRebuildSource]
] = {
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


def turn_lifecycle_owner(driver: ConversationDriver) -> TurnLifecycleOwner:
    """Who owns ``driver``'s turn lifecycle."""
    return _DRIVER_TRIPLES[driver][0]


def tools_execute_locally(driver: ConversationDriver) -> bool:
    """Whether ZN itself executes ``driver``'s tool calls."""
    return _DRIVER_TRIPLES[driver][1]


def input_rebuild_source(driver: ConversationDriver) -> InputRebuildSource:
    """What ``driver``'s next turn input is rebuilt from."""
    return _DRIVER_TRIPLES[driver][2]


#: Every conversation-driving site in ZN, frozen. A new mode must add
#: its site here (with its driver) instead of silently going unmapped.
CONVERSATION_SITES: tuple[str, ...] = (
    # Ordinary resident events: one pulse per step, input from the
    # durable AgentEvent plus the bounded Work-ledger conversation
    # projection (work_conversation_context), tools via the Body.
    "ordinary",
    # Broad-goal events (autonomous Root acceptance, research /
    # write / run / verify): same pulse, input from Work ledger +
    # working state.
    "broad_goal",
    # Generic-action events (ZN-led): ZN native deliberation decides,
    # the model proposes one bounded Action Fabric action per impasse,
    # input rebuilt from the durable loop history of verified
    # executions.
    "generic_action",
    # Model-led generic-action events (``agent_loop=True``): the model
    # chooses the next step, but ZN still owns the event, Work ledger,
    # action authorization, verification and recovery -- proposal
    # source is not lifecycle ownership, so this is still the
    # resident-pulse driver.
    "model_led_generic_action",
    # Team events: TeamWorkResidentRuntime + TeamWorkOwner.advance,
    # one durable driver step per pulse, specialist steps executed
    # through the Body, input rebuilt from durable team state (plan,
    # ledger, journal, working state).
    "team",
    # Continuable sub-agent delegations (DSH-7): supervisor messages
    # are delivered into the sub-agent's next cognition question
    # exactly once, as quoted supervisor context. The messages are
    # one input ingredient, not a message-list replay, and the parent
    # resident pulse still owns the lifecycle -- still the
    # resident-pulse driver.
    "delegated_subagent",
    # AgenticToolLoop.run: the model decides the next tool call or
    # that it is done; ZN executes the calls locally; input is the
    # in-memory message list replayed each turn.
    "model_tool_loop",
    # Veteran engineering missions: the external Codex worker (MCP
    # stdio subprocess) owns the mission's turns and executes its own
    # tools; ZN only plans / advances / polls the mission.
    "veteran_mission",
)


#: Site -> driver. Many-to-one is the finding, not a gap: on these
#: three predicates, ZN's single / broad-goal / generic-action /
#: team / delegated-subagent modes are the same driver; their
#: differences live in dispatch and state shape, not in who owns a
#: turn, who executes tools, or what input is rebuilt from.
_SITE_DRIVERS: dict[str, ConversationDriver] = {
    "ordinary": ConversationDriver.RESIDENT_PULSE,
    "broad_goal": ConversationDriver.RESIDENT_PULSE,
    "generic_action": ConversationDriver.RESIDENT_PULSE,
    "model_led_generic_action": ConversationDriver.RESIDENT_PULSE,
    "team": ConversationDriver.RESIDENT_PULSE,
    "delegated_subagent": ConversationDriver.RESIDENT_PULSE,
    "model_tool_loop": ConversationDriver.MODEL_TOOL_LOOP,
    "veteran_mission": ConversationDriver.EXTERNAL_WORKER,
}


def driver_for_site(site: str) -> ConversationDriver:
    """The driver for one conversation-driving site.

    Fails closed on an unknown site: an unmapped mode must be added
    to :data:`CONVERSATION_SITES` / :data:`_SITE_DRIVERS` explicitly,
    never silently defaulted to a driver.
    """
    try:
        return _SITE_DRIVERS[site]
    except KeyError:
        raise ValueError(
            f"unknown conversation site: {site!r}; add it to the W-4 "
            "mapping instead of defaulting to a driver"
        ) from None


def describe(driver: ConversationDriver) -> dict[str, object]:
    """The driver plus its three predicates and its sites."""
    return {
        "driver": driver.value,
        "turn_lifecycle_owner": turn_lifecycle_owner(driver).value,
        "tools_execute_locally": tools_execute_locally(driver),
        "input_rebuild_source": input_rebuild_source(driver).value,
        "sites": [site for site in CONVERSATION_SITES if _SITE_DRIVERS[site] is driver],
    }

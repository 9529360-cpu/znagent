from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    build_machine_action_execution_runtime,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.cognition import CognitiveIncrement
from zn_agent.core.generic_action_loop import (
    build_generic_action_context,
    parse_generic_action_completion,
    parse_generic_action_proposal,
)
from zn_agent.core import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime
from zn_agent.core.models import AgentEvent, ExecutionPath, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)


class _Body:
    def __init__(self):
        self.calls = []

    def act(self, kind, *, event_id=None, **kwargs):
        self.calls.append((kind, event_id, dict(kwargs)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"value": "fresh"},
            event_id=event_id,
        )


class _Device:
    def installed_applications(self):
        return (
            SimpleNamespace(
                app_id="app.other",
                display_name="Other App",
                canonical_name="other app",
                launchable=True,
            ),
            SimpleNamespace(
                app_id="app.notepad",
                display_name="Notepad",
                canonical_name="notepad",
                launchable=True,
            ),
            SimpleNamespace(
                app_id="app.hidden",
                display_name="Hidden",
                canonical_name="hidden",
                launchable=False,
            ),
        )

    def foreground_application(self):
        return None


def _fabric():
    fabric = ActionFabricRegistry()
    fabric.register(
        ActionDescriptor(
            action_id="test.read",
            provider="test",
            description="Read one fresh test value.",
            body_action_kind="test_read",
            input_schema={"type": "object", "additionalProperties": False},
            effect_class="read_only",
            verification=("fresh body result",),
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            reason="test action is available",
        ),
    )
    return fabric


def _launch_fabric():
    fabric = ActionFabricRegistry()
    fabric.register(
        ActionDescriptor(
            action_id="windows.application.launch",
            provider="zn.windows",
            description="Launch one resolved application.",
            body_action_kind="launch_application",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {"application_id": {"type": "string"}},
                "additionalProperties": False,
            },
            effect_class="potential_side_effect",
            verification=("fresh process/window observation",),
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            reason="test launch is available",
        ),
    )
    return fabric


class _PendingLaunchGraph:
    def __init__(self, *, ready: bool):
        self.ready = bool(ready)
        self.application = SimpleNamespace(app_id="app.demo")

    def application_by_id(self, app_id, *, force_refresh=False):
        del force_refresh
        return self.application if app_id == "app.demo" else None

    def application_runtime(self, application):
        if application is not self.application or not self.ready:
            return (), ()
        processes = (
            SimpleNamespace(process_id=41, resolved_app_id="app.demo"),
        )
        windows = (
            SimpleNamespace(
                hwnd=99,
                process_id=41,
                resolved_app_id="app.demo",
                visible=True,
            ),
        )
        return processes, windows


class GenericActionProtocolTests(unittest.TestCase):
    def test_safe_history_keeps_nested_identity_and_selector_evidence(self):
        history = (
            {
                "execution_id": "exec-resolve",
                "action_id": "windows.application.resolve",
                "verified": True,
                "observations": [
                    {
                        "source": "body_result",
                        "data": {
                            "application": {
                                "application_id": "app.demo",
                                "canonical_name": "Demo",
                            }
                        },
                    }
                ],
            },
            {
                "execution_id": "exec-controls",
                "action_id": "windows.ui.controls.list",
                "verified": True,
                "observations": [
                    {
                        "source": "body_result",
                        "data": {
                            "controls": [
                                {
                                    "automation_id": "Editor",
                                    "control_type": 50004,
                                }
                            ]
                        },
                    }
                ],
            },
        )
        context = build_generic_action_context(
            fabric=_fabric(),
            device_capabilities=_Device(),
            task="use the resolved application and Editor control",
            history=history,
        )
        recent = context["recent_verified_executions"]
        self.assertEqual(
            recent[0]["observations"][0]["data"]["application"]["application_id"],
            "app.demo",
        )
        self.assertEqual(
            recent[1]["observations"][0]["data"]["controls"][0]["automation_id"],
            "Editor",
        )
        self.assertNotIn("launchable_applications", context)

    def test_strict_proposal_and_completion_envelopes(self):
        proposal = parse_generic_action_proposal(
            '{"zn_action_proposal":{"action_id":"test.read","arguments":{}}}'
        )
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.action_id, "test.read")
        self.assertEqual(dict(proposal.arguments), {})

        self.assertIsNone(
            parse_generic_action_proposal(
                'Use this: {"zn_action_proposal":{"action_id":"test.read","arguments":{}}}'
            )
        )
        self.assertIsNone(
            parse_generic_action_proposal(
                '{"zn_action_proposal":{"action_id":"test.read","arguments":{},"extra":1}}'
            )
        )

        completion = parse_generic_action_completion(
            '{"zn_action_completion":{"execution_ids":["exec-1"],"response":"done"}}'
        )
        self.assertIsNotNone(completion)
        self.assertEqual(completion.execution_ids, ("exec-1",))
        self.assertEqual(completion.response, "done")

        self.assertIsNone(
            parse_generic_action_completion(
                '{"zn_action_completion":{"execution_ids":[],"response":"done"}}'
            )
        )

    def test_context_exposes_available_actions_without_raw_application_inventory(self):
        context = build_generic_action_context(
            fabric=_fabric(),
            device_capabilities=_Device(),
            task="Open Notepad and type hello",
        )
        self.assertEqual(
            [row["action_id"] for row in context["available_actions"]],
            ["test.read"],
        )
        self.assertNotIn("launchable_applications", context)
        self.assertIn("foreground_application", context)


class GenericActionResidentLoopTests(unittest.TestCase):
    def _resident(self, root: Path):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        fabric = _fabric()
        body = _Body()
        resident.action_fabric = fabric
        resident.action_executor = ActionExecutionRuntime(fabric, body)
        resident.device_capabilities = _Device()
        resident._accept_generic_action_increment = lambda event, state, increment: 1
        return resident, body

    @staticmethod
    def _increment(event, content):
        return CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id="impasse-test",
            source="external:test",
            question=event.task,
            content=content,
            quality=1.0,
            confidence=1.0,
        )

    @staticmethod
    def _state(event, increment):
        return WorkingState(
            current_event_id=event.event_id,
            stage="cognition_integration",
            data={
                "cognition_request": {
                    "context": {"generic_action_loop": {"version": 1}},
                },
                "cognitive_increment": increment.to_dict(),
                "external_cognition_result": {"model_invocations": 1},
            },
        )

    def test_verified_action_returns_to_deliberation_and_completion_requires_evidence_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, body = self._resident(Path(tmp))
            event = AgentEvent(
                event_id="evt-generic-action",
                task="inspect the current test value",
                kind="desktop_user_event",
            )
            increment = self._increment(
                event,
                '{"zn_action_proposal":{"action_id":"test.read","arguments":{}}}',
            )
            state = self._state(event, increment)
            resident.store.save_working_state(state)

            admitted = resident._cognition_integration_step(
                event,
                state,
                readiness=SimpleNamespace(),
            )
            self.assertIsNone(admitted)
            self.assertEqual(state.stage, resident._GENERIC_ACTION_STAGE)
            self.assertEqual(body.calls, [])

            executed = resident._generic_action_step(event, state)
            self.assertIsNone(executed)
            self.assertEqual(state.stage, "native_deliberation")
            self.assertEqual(len(body.calls), 1)
            loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
            self.assertEqual(len(loop["history"]), 1)
            evidence_id = loop["history"][0]["execution_id"]
            self.assertTrue(loop["history"][0]["verified"])

            completion_increment = self._increment(
                event,
                (
                    '{"zn_action_completion":{"execution_ids":["'
                    + evidence_id
                    + '"],"response":"fresh value inspected"}}'
                ),
            )
            state.stage = "cognition_integration"
            state.data["cognition_request"] = {
                "context": {"generic_action_loop": {"version": 1}},
            }
            state.data["cognitive_increment"] = completion_increment.to_dict()
            state.data["external_cognition_result"] = {"model_invocations": 1}

            completed = resident._cognition_integration_step(
                event,
                state,
                readiness=SimpleNamespace(),
            )
            self.assertIsNotNone(completed)
            self.assertTrue(completed.success)
            self.assertIs(completed.execution_path, ExecutionPath.BODY)
            self.assertEqual(completed.response, "fresh value inspected")
            self.assertEqual(
                state.stage,
                resident._GENERIC_ACTION_COMPLETION_STAGE,
            )
            resident.store.close()

    def test_pending_launch_reverifies_after_restart_without_redispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, _ = self._resident(root)
            fabric = _launch_fabric()
            first_body = _Body()
            first_graph = _PendingLaunchGraph(ready=False)
            resident.action_fabric = fabric
            resident.action_executor = build_machine_action_execution_runtime(
                fabric,
                first_body,
                device_capabilities=first_graph,
            )
            resident.device_capabilities = first_graph

            event = AgentEvent(
                event_id="evt-generic-launch-pending",
                task="launch the resolved demo application",
                kind="desktop_user_event",
            )
            increment = self._increment(
                event,
                (
                    '{"zn_action_proposal":{"action_id":"windows.application.launch",'
                    '"arguments":{"application_id":"app.demo"}}}'
                ),
            )
            state = self._state(event, increment)
            resident.store.save_working_state(state)

            admitted = resident._cognition_integration_step(
                event,
                state,
                readiness=SimpleNamespace(),
            )
            self.assertIsNone(admitted)
            pending = resident._generic_action_step(event, state)
            self.assertIsNone(pending)
            self.assertEqual(len(first_body.calls), 1)
            self.assertEqual(state.stage, resident._GENERIC_ACTION_STAGE)
            loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
            self.assertEqual(loop["status"], "reverify_pending")
            self.assertIn("reverification", loop["pending"])
            resident.store.close()

            restored, _ = self._resident(root)
            restored_fabric = _launch_fabric()
            restored_body = _Body()
            restored_graph = _PendingLaunchGraph(ready=True)
            restored.action_fabric = restored_fabric
            restored.action_executor = build_machine_action_execution_runtime(
                restored_fabric,
                restored_body,
                device_capabilities=restored_graph,
            )
            restored.device_capabilities = restored_graph
            try:
                restored_state = restored.store.get_working_state()
                resumed = restored._generic_action_step(event, restored_state)
                self.assertIsNone(resumed)
                self.assertEqual(restored_body.calls, [])
                self.assertEqual(restored_state.stage, "native_deliberation")
                restored_loop = restored_state.data[restored._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(restored_loop["status"], "awaiting_next_cognition")
                self.assertEqual(len(restored_loop["history"]), 1)
                self.assertTrue(restored_loop["history"][0]["verified"])
            finally:
                restored.store.close()

    def test_model_prose_cannot_finish_after_action_history_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ = self._resident(Path(tmp))
            event = AgentEvent(
                event_id="evt-generic-prose",
                task="do local work",
                kind="desktop_user_event",
            )
            increment = self._increment(event, "all done")
            state = self._state(event, increment)
            state.data[resident._GENERIC_ACTION_LOOP_KEY] = {
                "version": 1,
                "history": [
                    {
                        "execution_id": "exec-verified",
                        "verified": True,
                    }
                ],
            }
            resident.store.save_working_state(state)

            result = resident._cognition_integration_step(
                event,
                state,
                readiness=SimpleNamespace(),
            )
            self.assertIsNone(result)
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn(
                "plain model prose cannot complete",
                state.data["local_failure"],
            )
            resident.store.close()


class _LoopWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.calls.append(goal.task)
        cognition = goal.metadata.get("cognition_request")
        context = cognition.get("context") if isinstance(cognition, dict) else {}
        loop = context.get("generic_action_loop") if isinstance(context, dict) else {}
        history = (
            loop.get("recent_verified_executions")
            if isinstance(loop, dict)
            else []
        )
        if not history:
            response = (
                '{"zn_action_proposal":{"action_id":"test.read","arguments":{}}}'
            )
        else:
            latest = history[-1]
            execution_id = str(latest.get("execution_id") or "")
            response = (
                '{"zn_action_completion":{"execution_ids":["'
                + execution_id
                + '"],"response":"fresh value inspected"}}'
            )
        return WorkerResult(
            success=True,
            response=response,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _LoopFactory:
    def __init__(self):
        self.calls = []

    def create(self, route):
        return _LoopWorker(self)


class GenericActionEndToEndTests(unittest.TestCase):
    def test_desktop_event_runs_model_action_evidence_model_completion_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _LoopFactory()
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "kernel.db"),
                routes=[
                    ModelRoute(
                        "primary",
                        "test",
                        "model",
                        {"general": 0.9},
                    )
                ],
                worker_factory=factory,
            )
            resident = ProductResearchInformationResidentRuntime(kernel=kernel)
            fabric = _fabric()
            body = _Body()
            resident.action_fabric = fabric
            resident.action_executor = ActionExecutionRuntime(fabric, body)
            resident.device_capabilities = _Device()
            try:
                event = resident.enqueue(
                    "inspect the current test value",
                    kind="desktop_user_event",
                )
                result = resident.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                self.assertTrue(result.success)
                self.assertIs(result.execution_path, ExecutionPath.BODY)
                self.assertEqual(result.response, "fresh value inspected")
                self.assertEqual(len(body.calls), 1)
                self.assertEqual(body.calls[0][0], "test_read")
                self.assertEqual(len(factory.calls), 2)
                outcome = resident.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
                self.assertIs(outcome.execution_path, ExecutionPath.BODY)
                self.assertEqual(outcome.model_invocations, 2)
                self.assertEqual(result.model_invocations, 2)
                working = resident.store.get_working_state()
                self.assertEqual(working.stage, "idle")
                self.assertIsNone(working.current_event_id)
                self.assertNotIn(
                    resident._GENERIC_ACTION_LOOP_KEY,
                    working.data,
                )
            finally:
                resident.store.close()


class _PlainWorker:
    def run(self, goal, kernel_context):
        return WorkerResult(
            success=True,
            response="plain answer",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _PlainFactory:
    def create(self, route):
        return _PlainWorker()


class _TwoStepWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        cognition = goal.metadata.get("cognition_request")
        context = cognition.get("context") if isinstance(cognition, dict) else {}
        loop = context.get("generic_action_loop") if isinstance(context, dict) else {}
        history = loop.get("recent_verified_executions") if isinstance(loop, dict) else []
        history = history if isinstance(history, list) else []
        self.factory.calls += 1
        if len(history) < 2:
            response = '{"zn_action_proposal":{"action_id":"test.read","arguments":{}}}'
        else:
            ids = [str(item.get("execution_id") or "") for item in history[-2:]]
            response = (
                '{"zn_action_completion":{"execution_ids":'
                + repr(ids).replace("'", '"')
                + ',"response":"two verified reads complete"}}'
            )
        return WorkerResult(
            success=True,
            response=response,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _TwoStepFactory:
    def __init__(self):
        self.calls = 0

    def create(self, route):
        return _TwoStepWorker(self)


class GenericActionProductBehaviorTests(unittest.TestCase):
    def _kernel(self, root: Path, factory):
        return ZNKernelRuntime(
            store=KernelStore(root / "kernel.db"),
            routes=[ModelRoute("primary", "test", "model", {"general": 0.9})],
            worker_factory=factory,
        )

    def test_plain_desktop_question_can_still_finish_as_model_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = ProductResearchInformationResidentRuntime(
                kernel=self._kernel(Path(tmp), _PlainFactory())
            )
            fabric = _fabric()
            body = _Body()
            resident.action_fabric = fabric
            resident.action_executor = ActionExecutionRuntime(fabric, body)
            resident.device_capabilities = _Device()
            try:
                event = resident.enqueue(
                    "answer a question without touching the desktop",
                    kind="desktop_user_event",
                )
                result = resident.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                self.assertTrue(result.success)
                self.assertIs(result.execution_path, ExecutionPath.MODEL)
                self.assertEqual(result.response, "plain answer")
                self.assertEqual(body.calls, [])
            finally:
                resident.store.close()

    def test_multiple_verified_actions_roll_back_into_cognition_before_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _TwoStepFactory()
            resident = ProductResearchInformationResidentRuntime(
                kernel=self._kernel(Path(tmp), factory)
            )
            fabric = _fabric()
            body = _Body()
            resident.action_fabric = fabric
            resident.action_executor = ActionExecutionRuntime(fabric, body)
            resident.device_capabilities = _Device()
            try:
                event = resident.enqueue(
                    "perform two verified local reads",
                    kind="desktop_user_event",
                )
                result = resident.run_once(target_event_id=event.event_id)
                self.assertIsNotNone(result)
                self.assertTrue(result.success)
                self.assertIs(result.execution_path, ExecutionPath.BODY)
                self.assertEqual(result.response, "two verified reads complete")
                self.assertEqual(len(body.calls), 2)
                self.assertEqual(factory.calls, 3)
                self.assertEqual(result.model_invocations, 3)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()

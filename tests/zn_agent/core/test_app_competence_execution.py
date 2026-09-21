from __future__ import annotations

import unittest

from zn_agent.core.action_execution import (
    ActionExecution,
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.app_competence import (
    AppCompetenceBinding,
    AppCompetenceCompletion,
    AppCompetencePack,
    AppCompetenceRegistry,
    AppCompetenceStage,
)
from zn_agent.core.app_competence_execution import (
    AppCompetenceRecipeExecutor,
    completion_expected_matches,
)
from zn_agent.core.body import BodyActionResult
from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)
from zn_agent.core.visual_action_reasoner import VisualActionDecision, VisualActionInference
from zn_agent.core.visual_stage_bridge import VisualStageBridgeResult


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class _IntegratedBody:
    def __init__(self) -> None:
        self.state = "off"
        self.calls: list[tuple[str, str | None, dict]] = []

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, event_id, dict(args)))
        if kind == "test_toggle":
            self.state = str(args["state"])
            return BodyActionResult(
                action_id=f"body-{len(self.calls)}",
                kind=kind,
                success=True,
                data={"dispatch_sent": True},
                event_id=event_id,
            )
        if kind == "test_read":
            return BodyActionResult(
                action_id=f"body-{len(self.calls)}",
                kind=kind,
                success=True,
                data={"state": {"toggle_state": self.state}},
                event_id=event_id,
            )
        raise AssertionError(kind)


class _RecipeRuntime:
    def __init__(self, fabric: ActionFabricRegistry) -> None:
        self.fabric = fabric
        self.calls: list[ActionRequest] = []
        self.state = "off"
        self.read_sequence: list[str] = []
        self.stage_dispatches = 0
        self.stage_mode = "success"

    def execute(self, request: ActionRequest) -> ActionExecution:
        self.calls.append(request)
        descriptor = self.fabric.descriptor(request.action_id)
        assert descriptor is not None

        if request.action_id == "test.read":
            value = (
                self.read_sequence.pop(0)
                if self.read_sequence
                else self.state
            )
            data = {
                "state": {
                    "toggle_state": value,
                    "detail": {"stable": value == "on"},
                }
            }
            body = BodyActionResult(
                action_id=f"body-{len(self.calls)}",
                kind="test_read",
                success=True,
                data=data,
                event_id=request.event_id,
            )
            observation = ActionObservation(
                request.action_id,
                "body_result",
                data=data,
            )
            verification = ActionVerification(
                "verified",
                "fresh read",
                evidence={"source": "test"},
            )
            return ActionExecution(
                execution_id=f"exec-{len(self.calls)}",
                request=request,
                descriptor=descriptor,
                status="verified",
                verification=verification,
                observations=(observation,),
                body_result=body,
            )

        if request.action_id == "test.toggle":
            self.stage_dispatches += 1
            if self.stage_mode == "success":
                self.state = "on"
                body = BodyActionResult(
                    action_id=f"body-{len(self.calls)}",
                    kind="test_toggle",
                    success=True,
                    data={
                        "dispatch_sent": True,
                        "postcondition_verified": True,
                    },
                    event_id=request.event_id,
                )
                verification = ActionVerification(
                    "verified",
                    "stage action verified",
                )
                status = "verified"
                error = None
            elif self.stage_mode == "replay_blocked":
                body = BodyActionResult(
                    action_id=f"body-{len(self.calls)}",
                    kind="test_toggle",
                    success=False,
                    data={
                        "dispatch_sent": False,
                        "side_effect_uncertain": True,
                        "replay_blocked": True,
                    },
                    error="prior dispatch uncertain",
                    event_id=request.event_id,
                )
                verification = ActionVerification(
                    "uncertain",
                    "prior dispatch uncertain",
                )
                status = "uncertain"
                error = "prior dispatch uncertain"
            else:
                body = BodyActionResult(
                    action_id=f"body-{len(self.calls)}",
                    kind="test_toggle",
                    success=False,
                    data={
                        "dispatch_sent": False,
                        "side_effect_uncertain": False,
                    },
                    error="pre-dispatch rejection",
                    event_id=request.event_id,
                )
                verification = ActionVerification(
                    "failed",
                    "pre-dispatch rejection",
                )
                status = "failed"
                error = "pre-dispatch rejection"
            return ActionExecution(
                execution_id=f"exec-{len(self.calls)}",
                request=request,
                descriptor=descriptor,
                status=status,
                verification=verification,
                body_result=body,
                error=error,
            )

        if request.action_id == "test.inventory":
            data = {"count": 3}
            body = BodyActionResult(
                action_id=f"body-{len(self.calls)}",
                kind="test_inventory",
                success=True,
                data=data,
                event_id=request.event_id,
            )
            verification = ActionVerification("verified", "read completed")
            return ActionExecution(
                execution_id=f"exec-{len(self.calls)}",
                request=request,
                descriptor=descriptor,
                status="verified",
                verification=verification,
                observations=(
                    ActionObservation(
                        request.action_id,
                        "body_result",
                        data=data,
                    ),
                ),
                body_result=body,
            )

        raise AssertionError(request.action_id)


def _fabric() -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    available = lambda descriptor: ActionAvailability(
        descriptor.action_id,
        "available",
        evidence={"source": "test"},
    )
    registry.register(
        ActionDescriptor(
            "test.toggle",
            "test",
            "toggle semantic control",
            body_action_kind="test_toggle",
            input_schema={
                "type": "object",
                "required": ["application_id", "state"],
                "properties": {
                    "application_id": {"type": "string"},
                    "state": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
        ),
        availability_probe=available,
    )
    registry.register(
        ActionDescriptor(
            "test.read",
            "test",
            "read semantic control",
            body_action_kind="test_read",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {
                    "application_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="read_only",
        ),
        availability_probe=available,
    )
    registry.register(
        ActionDescriptor(
            "windows.desktop.scene.capture",
            "test",
            "visual grounding substrate",
            body_action_kind="windows_desktop_scene_capture",
            input_schema={
                "type": "object",
                "required": ["application_id"],
                "properties": {
                    "application_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
        ),
        availability_probe=available,
    )
    registry.register(
        ActionDescriptor(
            "test.inventory",
            "test",
            "read inventory",
            body_action_kind="test_inventory",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            effect_class="read_only",
        ),
        availability_probe=available,
    )
    return registry


def _registry(
    *,
    stage: AppCompetenceStage | None = None,
) -> AppCompetenceRegistry:
    registry = AppCompetenceRegistry()
    if stage is None:
        stage = AppCompetenceStage(
            action_id="test.toggle",
            arguments={"state": "on"},
            completion=AppCompetenceCompletion(
                action_id="test.read",
                expected={"state.toggle_state": "on"},
            ),
            timeout_ms=200,
        )
    registry.register(
        AppCompetencePack(
            pack_id="demo-1",
            app_id="demo.app",
            app_version="1.0",
            aliases=("Demo",),
            bindings=(
                AppCompetenceBinding(
                    capability="enable",
                    action_id=stage.action_id,
                    stages=(stage,),
                ),
            ),
            source="test",
        )
    )
    return registry


class AppCompetenceRecipeExecutorTests(unittest.TestCase):
    def _executor(self, runtime: _RecipeRuntime, clock: _Clock):
        return AppCompetenceRecipeExecutor(
            _registry(),
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

    def test_preflight_completion_skips_side_effect(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        runtime.state = "on"
        clock = _Clock()
        executor = self._executor(runtime, clock)

        result = executor.execute(
            app="Demo",
            version="1.0",
            capability="enable",
            event_id="evt-recipe",
            application_id="app-runtime-1",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.stages[0].status, "already_verified")
        self.assertEqual(runtime.stage_dispatches, 0)
        self.assertEqual(
            [call.action_id for call in runtime.calls],
            ["test.read"],
        )
        self.assertEqual(
            runtime.calls[0].args["application_id"],
            "app-runtime-1",
        )

    def test_stage_dispatches_once_then_polls_completion(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        runtime.read_sequence = ["off", "off", "on"]
        clock = _Clock()
        executor = self._executor(runtime, clock)

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-stage",
            application_id="app-runtime-1",
        )

        self.assertTrue(result.success, result.error)
        stage = result.stages[0]
        self.assertEqual(stage.status, "verified")
        self.assertEqual(runtime.stage_dispatches, 1)
        self.assertEqual(len(stage.completion_checks), 2)
        self.assertEqual(clock.sleeps, [0.05])
        self.assertEqual(
            [call.action_id for call in runtime.calls],
            ["test.read", "test.toggle", "test.read", "test.read"],
        )
        self.assertTrue(
            all(call.event_id == "evt-stage" for call in runtime.calls)
        )

    def test_timeout_after_dispatch_is_uncertain_and_never_redispatches(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        runtime.stage_mode = "replay_blocked"
        runtime.read_sequence = ["off"] * 20
        clock = _Clock()
        executor = self._executor(runtime, clock)

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-uncertain",
            application_id="app-runtime-1",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.stages[0].status, "uncertain")
        self.assertEqual(runtime.stage_dispatches, 1)
        self.assertGreaterEqual(len(result.stages[0].completion_checks), 1)
        self.assertIn("refusing blind redispatch", result.error or "")

    def test_restart_recovers_from_completion_truth_without_redispatch(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        runtime.stage_mode = "replay_blocked"
        runtime.read_sequence = ["off"] * 20
        first_clock = _Clock()
        first = self._executor(runtime, first_clock).execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-recover",
            application_id="app-runtime-1",
        )
        self.assertEqual(first.status, "uncertain")
        self.assertEqual(runtime.stage_dispatches, 1)

        runtime.state = "on"
        runtime.read_sequence = []
        second_clock = _Clock()
        second = self._executor(runtime, second_clock).execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-recover",
            application_id="app-runtime-1",
        )

        self.assertTrue(second.success, second.error)
        self.assertEqual(second.stages[0].status, "already_verified")
        self.assertEqual(runtime.stage_dispatches, 1)

    def test_visual_handoff_rejects_ambiguous_or_unbounded_runtime_fields(self) -> None:
        base = {
            "handoff_id": "competence-visual-1234567890abcdef1234",
            "kind": "visual_action",
            "stage_index": 0,
            "event_id": "evt",
            "application_id": "app-runtime-1",
            "grounding_action_id": "windows.desktop.scene.capture",
            "instruction": "Click Continue",
            "step_instruction_index": 0,
        }
        from zn_agent.core.app_competence_execution import AppCompetenceStageHandoff

        for field, value in (
            ("stage_index", True),
            ("stage_index", -1),
            ("step_instruction_index", True),
            ("step_instruction_index", -1),
            ("stage_end_condition", True),
            ("stage_end_condition", -1),
        ):
            with self.subTest(field=field, value=value):
                values = dict(base)
                values[field] = value
                with self.assertRaises(ValueError):
                    AppCompetenceStageHandoff(**values)

        values = dict(base)
        values["instruction"] = "x" * 769
        with self.assertRaisesRegex(ValueError, "exceeds 768"):
            AppCompetenceStageHandoff(**values)

    def test_visual_stage_returns_stable_pending_handoff_without_dispatch(self) -> None:
        stage = AppCompetenceStage(
            action_id="windows.desktop.scene.capture",
            execution_mode="visual_action",
            completion=AppCompetenceCompletion(
                action_id="test.read",
                expected={"state.toggle_state": "on"},
            ),
            timeout_ms=200,
            metadata={
                "instruction": "Click the visible Continue button",
                "step_instruction_index": 2,
                "stage_end_condition": 2,
            },
        )
        registry = _registry(stage=stage)
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        first = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-visual",
            application_id="app-runtime-1",
        )
        second = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-visual",
            application_id="app-runtime-1",
        )

        self.assertFalse(first.success)
        self.assertEqual(first.status, "pending")
        self.assertEqual(first.stages[0].status, "pending")
        handoff = first.stages[0].handoff
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.kind, "visual_action")
        self.assertEqual(handoff.application_id, "app-runtime-1")
        self.assertEqual(handoff.step_instruction_index, 2)
        self.assertEqual(handoff.stage_end_condition, 2)
        self.assertEqual(
            handoff.instruction,
            "Click the visible Continue button",
        )
        self.assertEqual(
            handoff.handoff_id,
            second.stages[0].handoff.handoff_id,
        )
        self.assertEqual(runtime.stage_dispatches, 0)
        self.assertEqual(
            [call.action_id for call in runtime.calls],
            ["test.read", "test.read"],
        )

    def test_visual_stage_reentry_advances_only_from_completion_truth(self) -> None:
        stage = AppCompetenceStage(
            action_id="windows.desktop.scene.capture",
            execution_mode="visual_action",
            completion=AppCompetenceCompletion(
                action_id="test.read",
                expected={"state.toggle_state": "on"},
            ),
            timeout_ms=200,
            metadata={
                "instruction": "Click the visible Continue button",
                "step_instruction_index": 0,
            },
        )
        registry = _registry(stage=stage)
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        pending = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-visual-recover",
            application_id="app-runtime-1",
        )
        self.assertEqual(pending.status, "pending")
        self.assertEqual(runtime.stage_dispatches, 0)

        runtime.state = "on"
        recovered = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-visual-recover",
            application_id="app-runtime-1",
        )
        self.assertTrue(recovered.success, recovered.error)
        self.assertEqual(recovered.stages[0].status, "already_verified")
        self.assertIsNone(recovered.stages[0].handoff)
        self.assertEqual(runtime.stage_dispatches, 0)

    def test_distinct_visual_steps_are_not_rejected_as_duplicate_side_effects(self) -> None:
        completion = AppCompetenceCompletion(
            action_id="test.read",
            expected={"state.toggle_state": "on"},
        )
        stages = tuple(
            AppCompetenceStage(
                action_id="windows.desktop.scene.capture",
                execution_mode="visual_action",
                completion=completion,
                timeout_ms=200,
                metadata={
                    "instruction": instruction,
                    "step_instruction_index": index,
                },
            )
            for index, instruction in enumerate(("Click Continue", "Click Finish"))
        )
        registry = AppCompetenceRegistry()
        registry.register(
            AppCompetencePack(
                pack_id="visual-demo",
                app_id="demo.app",
                app_version="1.0",
                bindings=(
                    AppCompetenceBinding(
                        capability="enable",
                        action_id="windows.desktop.scene.capture",
                        stages=stages,
                    ),
                ),
            )
        )
        runtime = _RecipeRuntime(_fabric())
        clock = _Clock()
        result = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        ).execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-two-visual",
            application_id="app-runtime-1",
        )
        self.assertEqual(result.status, "pending")
        self.assertNotIn("duplicate", result.error or "")

    def test_product_resident_visual_recipe_advances_one_verified_boundary_at_a_time(self) -> None:
        stage = AppCompetenceStage(
            action_id="windows.desktop.scene.capture",
            execution_mode="visual_action",
            completion=AppCompetenceCompletion(
                action_id="test.read",
                expected={"state.toggle_state": "on"},
            ),
            timeout_ms=200,
            metadata={
                "instruction": "Click the visible Continue button",
                "step_instruction_index": 0,
                "stage_end_condition": 2,
            },
        )
        registry = _registry(stage=stage)
        runtime = _RecipeRuntime(_fabric())
        resident = object.__new__(ProductResearchInformationResidentRuntime)
        resident.action_executor = runtime
        resident._sync_execution_context = lambda event, state: None
        saved = []
        resident.store = type(
            "Store",
            (),
            {"save_working_state": lambda self, state: saved.append(state)},
        )()
        decisions = ["TAP", "FINISH"]

        def evaluate_visual_stage(**kwargs):
            action = decisions.pop(0)
            state = kwargs["state"]
            if action == "TAP":
                state.stage = "native_action"
                state.next_action = "move body: pointer_click"
                return VisualStageBridgeResult(
                    inference=VisualActionInference(
                        decision=VisualActionDecision("TAP", 0.5, 0.5),
                        provider="fake",
                        model="fake",
                    ),
                    scene_id="desktop-scene-before",
                    regrounded_scene_id="desktop-scene-after",
                )
            return VisualStageBridgeResult(
                inference=VisualActionInference(
                    decision=VisualActionDecision("FINISH"),
                    provider="fake",
                    model="fake",
                ),
                scene_id="desktop-scene-finish",
                requires_completion_verification=True,
            )

        resident.evaluate_visual_stage = evaluate_visual_stage
        event = type("Event", (), {"event_id": "evt-visual-recipe"})()
        state = type(
            "State",
            (),
            {"data": {}, "stage": "native_investigation", "next_action": ""},
        )()

        first, first_visual = resident.advance_app_competence_recipe_once(
            registry=registry,
            event=event,
            state=state,
            app="demo.app",
            version="1.0",
            capability="enable",
            application_id="app-runtime-1",
        )
        self.assertEqual(first.status, "pending")
        self.assertEqual(first_visual.inference.decision.action, "TAP")
        self.assertEqual(state.stage, "native_action")
        self.assertEqual(
            state.data["app_competence_visual_handoff"]["observation_attempt"],
            0,
        )
        self.assertEqual(
            state.data["app_competence_visual_handoff"]["status"],
            "pointer_active",
        )

        blocked, blocked_visual = resident.advance_app_competence_recipe_once(
            registry=registry,
            event=event,
            state=state,
            app="demo.app",
            version="1.0",
            capability="enable",
            application_id="app-runtime-1",
        )
        self.assertEqual(blocked.status, "pending")
        self.assertIsNone(blocked_visual)
        self.assertEqual(decisions, ["FINISH"])

        state.stage = "native_investigation"
        state.data["app_competence_visual_handoff"]["status"] = "effect_verified"
        second, second_visual = resident.advance_app_competence_recipe_once(
            registry=registry,
            event=event,
            state=state,
            app="demo.app",
            version="1.0",
            capability="enable",
            application_id="app-runtime-1",
        )
        self.assertEqual(second.status, "pending")
        self.assertEqual(second_visual.inference.decision.action, "FINISH")
        self.assertIn("fresh reality", state.next_action)
        self.assertEqual(
            state.data["app_competence_visual_handoff"]["observation_attempt"],
            1,
        )
        self.assertEqual(
            state.data["app_competence_visual_handoff"]["status"],
            "finish_observed",
        )

        runtime.state = "on"
        third, third_visual = resident.advance_app_competence_recipe_once(
            registry=registry,
            event=event,
            state=state,
            app="demo.app",
            version="1.0",
            capability="enable",
            application_id="app-runtime-1",
        )
        self.assertTrue(third.success, third.error)
        self.assertEqual(third.status, "verified")
        self.assertIsNone(third_visual)
        self.assertNotIn("app_competence_visual_handoff", state.data)
        self.assertEqual(decisions, [])
        self.assertGreaterEqual(len(saved), 3)

    def test_side_effect_without_completion_is_rejected_before_dispatch(self) -> None:
        stage = AppCompetenceStage(
            action_id="test.toggle",
            arguments={"state": "on"},
            timeout_ms=200,
        )
        registry = _registry(stage=stage)
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-no-proof",
            application_id="app-runtime-1",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertIn("requires a read-only completion proof", result.error or "")
        self.assertEqual(runtime.calls, [])

    def test_read_only_stage_needs_no_completion_and_no_application_injection(self) -> None:
        stage = AppCompetenceStage(
            action_id="test.inventory",
            timeout_ms=200,
        )
        registry = _registry(stage=stage)
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-read",
            application_id="ignored-for-this-action",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.stages[0].status, "verified")
        self.assertEqual(runtime.calls[0].args, {})

    def test_missing_runtime_application_id_fails_before_side_effect(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = self._executor(runtime, clock)

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-missing-app",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertEqual(runtime.stage_dispatches, 0)
        self.assertIn("requires current runtime application_id", result.error or "")

    def test_completion_matcher_accepts_nested_and_dotted_expected_paths(self) -> None:
        observed = {
            "state": {
                "toggle_state": "on",
                "detail": {"stable": True},
            },
            "count": 2,
        }
        self.assertTrue(
            completion_expected_matches(
                observed,
                {
                    "state.toggle_state": "on",
                    "state": {"detail": {"stable": True}},
                    "count": 2,
                },
            )
        )
        self.assertFalse(
            completion_expected_matches(
                observed,
                {"state.toggle_state": "off"},
            )
        )
        self.assertFalse(
            completion_expected_matches(
                observed,
                {"state": {}},
            )
        )

    def test_integrates_with_real_action_execution_runtime(self) -> None:
        fabric = _fabric()
        body = _IntegratedBody()
        runtime = ActionExecutionRuntime(fabric, body)
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            _registry(),
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-integrated",
            application_id="app-runtime-1",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.stages[0].status, "verified")
        self.assertEqual(
            [kind for kind, _event, _args in body.calls],
            ["test_read", "test_toggle", "test_read"],
        )
        self.assertTrue(
            all(event == "evt-integrated" for _kind, event, _args in body.calls)
        )
        self.assertTrue(
            all(
                args.get("application_id") == "app-runtime-1"
                for _kind, _event, args in body.calls
            )
        )

    def test_preflight_deadline_expiry_never_dispatches_side_effect(self) -> None:
        fabric = _fabric()
        clock = _Clock()

        class _SlowPreflightRuntime(_RecipeRuntime):
            def execute(self, request: ActionRequest) -> ActionExecution:
                result = super().execute(request)
                if request.action_id == "test.read":
                    clock.now += 0.25
                return result

        runtime = _SlowPreflightRuntime(fabric)
        executor = self._executor(runtime, clock)
        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-slow-preflight",
            application_id="app-runtime-1",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertEqual(runtime.stage_dispatches, 0)
        self.assertIn("deadline elapsed during completion preflight", result.error or "")

    def test_unrelated_invalid_pack_does_not_block_current_recipe(self) -> None:
        registry = _registry()
        registry.register(
            AppCompetencePack(
                pack_id="future-1",
                app_id="future.app",
                app_version="9.0",
                bindings=(
                    AppCompetenceBinding(
                        capability="future",
                        action_id="future.action.not.loaded",
                    ),
                ),
            )
        )
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        runtime.state = "on"
        clock = _Clock()
        executor = AppCompetenceRecipeExecutor(
            registry,
            runtime,
            poll_interval_ms=50,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        result = executor.execute(
            app="demo.app",
            version="1.0",
            capability="enable",
            event_id="evt-current-pack",
            application_id="app-runtime-1",
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(runtime.stage_dispatches, 0)

    def test_exact_version_mismatch_fails_without_action(self) -> None:
        fabric = _fabric()
        runtime = _RecipeRuntime(fabric)
        clock = _Clock()
        executor = self._executor(runtime, clock)

        result = executor.execute(
            app="demo.app",
            version="1.0.1",
            capability="enable",
            event_id="evt-version",
            application_id="app-runtime-1",
        )

        self.assertFalse(result.success)
        self.assertIn("no exact app/version competence pack", result.error or "")
        self.assertEqual(runtime.calls, [])


if __name__ == "__main__":
    unittest.main()

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

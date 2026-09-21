from __future__ import annotations

"""Bridge verified desktop scenes into bounded visual decisions and pointer intents."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .action import NativeActionIntent
from .action_execution import ActionExecutionRuntime, ActionRequest
from .desktop_scene import DesktopScene, load_desktop_scene_artifact
from .visual_action_reasoner import GeminiVisualActionReasoner, VisualActionInference


SceneLoader = Callable[[str], DesktopScene]


@dataclass(frozen=True, slots=True)
class VisualStageBridgeResult:
    inference: VisualActionInference
    scene_id: str
    regrounded_scene_id: str | None = None
    pointer_intent: NativeActionIntent | None = None
    event_payload: dict[str, object] | None = None
    requires_completion_verification: bool = False


class DesktopVisualStageBridge:
    """One SEE -> bounded decision seam; pointer delivery stays in the resident lifecycle."""

    def __init__(
        self,
        *,
        action_runtime: ActionExecutionRuntime,
        reasoner: GeminiVisualActionReasoner,
        scene_loader: SceneLoader = load_desktop_scene_artifact,
    ) -> None:
        self.action_runtime = action_runtime
        self.reasoner = reasoner
        self.scene_loader = scene_loader

    def evaluate(
        self,
        *,
        event_id: str,
        decision_id: str,
        application_id: str,
        instruction: str,
        step_index: int | None = None,
    ) -> VisualStageBridgeResult:
        stable_event = str(event_id or "").strip()
        decision_key = str(decision_id or "").strip()
        app_id = str(application_id or "").strip()
        if not stable_event or not decision_key or not app_id:
            raise ValueError(
                "visual stage bridge requires stable event_id, decision_id and application_id"
            )
        decision_token = hashlib.sha256(decision_key.encode("utf-8")).hexdigest()[:16]

        scene_event = f"{stable_event}:visual-stage:{decision_token}:see"
        scene = self._capture_verified_scene(scene_event, app_id)
        inference = self.reasoner.infer(
            instruction=instruction,
            image_bytes=Path(scene.screenshot.local_path).read_bytes(),
            mime_type="image/png",
            step_index=step_index,
        )
        decision = inference.decision
        if decision.action == "WAIT":
            return VisualStageBridgeResult(inference=inference, scene_id=scene.scene_id)
        if decision.action == "FINISH":
            return VisualStageBridgeResult(
                inference=inference,
                scene_id=scene.scene_id,
                requires_completion_verification=True,
            )

        assert decision.x_fraction is not None and decision.y_fraction is not None
        reground_event = f"{stable_event}:visual-stage:{decision_token}:reground"
        regrounded = self._capture_verified_scene(reground_event, app_id)
        if scene.foreground.identity_sha256 != regrounded.foreground.identity_sha256:
            raise RuntimeError(
                "desktop foreground identity changed between visual decision and re-ground"
            )
        self._assert_point_inside_foreground(
            regrounded,
            decision.x_fraction,
            decision.y_fraction,
        )

        scene_precondition = {
            "kind": "desktop_scene_foreground_matches",
            "application_id": regrounded.foreground.application_id,
            "identity_sha256": regrounded.foreground.identity_sha256,
            "scene_id": regrounded.scene_id,
            "window_rect": regrounded.foreground.window_rect.audit(),
            "screen_width": regrounded.screenshot.width,
            "screen_height": regrounded.screenshot.height,
        }
        expected_outcome = {
            "kind": "visual_region_changed",
            "width_fraction": 0.08,
            "height_fraction": 0.08,
            "desktop_scene_precondition": scene_precondition,
        }
        intent_digest = hashlib.sha256(
            (
                f"{stable_event}\x1f{decision_token}\x1f{regrounded.scene_id}\x1f"
                f"{decision.x_fraction:.6f}\x1f{decision.y_fraction:.6f}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        intent = NativeActionIntent(
            intent_id=f"visual-tap-{intent_digest}",
            event_id=stable_event,
            kind="pointer_click",
            args={
                "x_fraction": decision.x_fraction,
                "y_fraction": decision.y_fraction,
                "button": "left",
            },
            expected_outcome=expected_outcome,
            reason="bounded visual stage TAP admitted after fresh desktop scene re-ground",
            source="visual_stage_bridge",
        )
        return VisualStageBridgeResult(
            inference=inference,
            scene_id=scene.scene_id,
            regrounded_scene_id=regrounded.scene_id,
            pointer_intent=intent,
            event_payload={
                "expected_outcome": expected_outcome,
                "desktop_scene_precondition": scene_precondition,
            },
        )

    def _capture_verified_scene(self, scene_event_id: str, application_id: str) -> DesktopScene:
        execution = self.action_runtime.execute(
            ActionRequest(
                action_id="windows.desktop.scene.capture",
                args={"application_id": application_id},
                event_id=scene_event_id,
            )
        )
        if not execution.success:
            raise RuntimeError(
                "desktop scene capture was not independently verified: "
                + str(execution.error or execution.verification.reason)
            )
        return self.scene_loader(scene_event_id)

    @staticmethod
    def _assert_point_inside_foreground(
        scene: DesktopScene,
        x_fraction: float,
        y_fraction: float,
    ) -> None:
        x = float(x_fraction) * float(scene.screenshot.width)
        y = float(y_fraction) * float(scene.screenshot.height)
        rect = scene.foreground.window_rect
        if not (rect.left <= x <= rect.right and rect.top <= y <= rect.bottom):
            raise RuntimeError(
                "visual TAP fell outside the freshly re-grounded foreground window"
            )

def build_current_visual_stage_bridge(
    *,
    action_runtime: ActionExecutionRuntime,
    kernel: Any,
) -> DesktopVisualStageBridge:
    """Bind the bridge to the first current ZN cognition resource with image support."""

    router = getattr(kernel, "router", None)
    routes = tuple(getattr(router, "routes", ()) or ())
    factory = getattr(kernel, "worker_factory", None)
    create = getattr(factory, "create", None)
    if not routes or not callable(create):
        raise RuntimeError("current ZN kernel has no usable cognition resource factory")

    failures: list[str] = []
    for route in routes:
        route_id = str(getattr(route, "route_id", "") or "").strip() or "unknown"
        try:
            worker = create(route)
        except Exception as exc:
            failures.append(f"{route_id}:{type(exc).__name__}")
            continue
        resource = getattr(worker, "resource", None)
        if not callable(getattr(resource, "invoke_image", None)):
            continue
        return DesktopVisualStageBridge(
            action_runtime=action_runtime,
            reasoner=GeminiVisualActionReasoner(resource),
        )

    detail = ", ".join(failures[:4])
    suffix = f" ({detail})" if detail else ""
    raise RuntimeError("no current ZN cognition resource supports bounded image invocation" + suffix)

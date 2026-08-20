from __future__ import annotations

from .models import Goal, ModelRoute
from .self_model import SelfModel


class NoRouteAvailable(RuntimeError):
    pass


class ModelRouter:
    """Kernel-owned deterministic model selection.

    Models do not select themselves. The kernel combines declared route priors
    with observed route performance from SelfModel.
    """

    def __init__(self, routes: list[ModelRoute], self_model: SelfModel):
        if not routes:
            raise ValueError("at least one model route is required")
        self.routes = tuple(routes)
        self.self_model = self_model

    def select(self, goal: Goal, excluded: set[str] | None = None) -> ModelRoute:
        excluded = excluded or set()
        candidates = [route for route in self.routes if route.route_id not in excluded]
        if not candidates:
            raise NoRouteAvailable("no model routes remain")

        required = goal.required_capabilities or ("general",)

        def score(route: ModelRoute) -> tuple[float, str]:
            capability_scores = []
            for capability in required:
                prior = route.capabilities.get(
                    capability, route.capabilities.get("general", 0.5)
                )
                capability_scores.append(
                    self.self_model.route_score(route.route_id, capability, prior)
                )
            capability_score = sum(capability_scores) / len(capability_scores)
            total = (
                0.62 * capability_score
                + 0.28 * max(0.0, min(1.0, route.reliability))
                - 0.06 * max(0.0, min(1.0, route.cost_weight))
                - 0.04 * max(0.0, min(1.0, route.latency_weight))
            )
            return total, route.route_id

        return max(candidates, key=score)

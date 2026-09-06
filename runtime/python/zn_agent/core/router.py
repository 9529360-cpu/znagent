from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import Goal, ModelRoute
from .self_model import SelfModel


class NoRouteAvailable(RuntimeError):
    pass


class ModelRouter:
    """Kernel-owned deterministic model selection.

    Selection is deliberately two-stage:

    1. hard eligibility removes routes that are unavailable, unhealthy, lack a
       required capability, violate explicit provider/model policy, or cannot
       receive the goal's data under locality/privacy/authority policy;
    2. soft scoring ranks only the remaining legal candidates using declared
       priors plus SelfModel evidence, reliability, cost and latency.

    A forbidden route never survives as a merely low-scoring fallback.
    """

    def __init__(self, routes: list[ModelRoute], self_model: SelfModel):
        if not routes:
            raise ValueError("at least one model route is required")
        self.routes = tuple(routes)
        self.self_model = self_model

    def select(self, goal: Goal, excluded: set[str] | None = None) -> ModelRoute:
        excluded = excluded or set()
        policy = self._route_policy(goal)
        candidates: list[ModelRoute] = []
        rejection_reasons: dict[str, tuple[str, ...]] = {}

        for route in self.routes:
            reasons = self._ineligibility_reasons(
                route,
                goal,
                excluded=excluded,
                policy=policy,
            )
            if reasons:
                rejection_reasons[route.route_id] = tuple(reasons)
            else:
                candidates.append(route)

        if not candidates:
            detail = "; ".join(
                f"{route_id}: {', '.join(reasons)}"
                for route_id, reasons in sorted(rejection_reasons.items())
            )
            suffix = f" ({detail})" if detail else ""
            raise NoRouteAvailable(f"no eligible model route remains{suffix}")

        required = goal.required_capabilities or ("general",)

        def score(route: ModelRoute) -> tuple[float, str]:
            capability_scores = []
            for capability in required:
                prior = self._declared_prior(route, capability)
                # Hard capability eligibility guarantees this is declared.
                if prior is None:
                    raise NoRouteAvailable(
                        f"route {route.route_id} lost required capability eligibility"
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

    def _ineligibility_reasons(
        self,
        route: ModelRoute,
        goal: Goal,
        *,
        excluded: set[str],
        policy: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        if route.route_id in excluded:
            reasons.append("excluded by retry/runtime state")

        metadata = route.metadata if isinstance(route.metadata, dict) else {}
        if metadata.get("model_available") is False or metadata.get("available") is False:
            reasons.append("route unavailable")
        health = str(metadata.get("health") or "").strip().lower()
        if metadata.get("healthy") is False or health in {"down", "failed", "unhealthy", "disabled"}:
            reasons.append("route unhealthy")

        required = goal.required_capabilities or ("general",)
        missing = [
            capability
            for capability in required
            if self._declared_prior(route, capability) is None
        ]
        if missing:
            reasons.append("missing required capabilities: " + ", ".join(missing))

        pinned_provider = str(policy.get("pinned_provider") or "").strip().lower()
        pinned_model = str(policy.get("pinned_model") or "").strip()
        if pinned_provider and route.provider.strip().lower() != pinned_provider:
            reasons.append("provider is not user pinned provider")
        if pinned_model and route.model != pinned_model:
            reasons.append("model is not user pinned model")

        denied_providers = self._string_set(policy.get("denied_providers"), lower=True)
        denied_models = self._string_set(policy.get("denied_models"), lower=False)
        if route.provider.strip().lower() in denied_providers:
            reasons.append("provider explicitly denied")
        if route.model in denied_models:
            reasons.append("model explicitly denied")

        classification = str(policy.get("data_classification") or "").strip().lower()
        local_only = bool(policy.get("local_only")) or bool(policy.get("cloud_forbidden"))
        if classification in {"local_only", "cloud_denied"}:
            local_only = True
        if local_only and not self._is_explicit_local_route(route):
            reasons.append("cloud/non-local route forbidden by data policy")

        required_tags = self._string_set(policy.get("required_policy_tags"), lower=True)
        route_tags = self._string_set(metadata.get("policy_tags"), lower=True)
        if required_tags and not required_tags.issubset(route_tags):
            reasons.append("route lacks required policy tags")

        required_authority = self._string_set(
            policy.get("required_authority_scopes"),
            lower=True,
        )
        route_authority = self._string_set(metadata.get("authority_scopes"), lower=True)
        if required_authority and not required_authority.issubset(route_authority):
            reasons.append("route lacks required authority policy scope")

        return reasons

    def _declared_prior(self, route: ModelRoute, capability: str) -> float | None:
        """Return a declared capability prior, never an undeclared default.

        Domain aliases may satisfy a capability when SelfModel maps the capability
        into that declared domain. ``general`` does not silently satisfy a more
        specific capability: a route that never declared research/coding/etc. is
        ineligible for that requirement rather than receiving the historical 0.5
        prior.
        """

        raw = str(capability or "general").strip().lower() or "general"
        keys: list[str] = [raw]
        domains = self.self_model.infer_domains("", (raw,))
        for domain in reversed(domains):
            for key in (domain, domain.rsplit("/", 1)[-1]):
                normalized = str(key or "").strip().lower()
                if normalized and normalized != "general" and normalized not in keys:
                    keys.append(normalized)
        if raw == "general" and "general" not in keys:
            keys.append("general")

        normalized_caps = {
            str(key).strip().lower(): value
            for key, value in route.capabilities.items()
        }
        for key in keys:
            if key not in normalized_caps:
                continue
            prior = max(0.0, min(1.0, float(normalized_caps[key])))
            # A zero declaration is an explicit lack of capability.
            return prior if prior > 0.0 else None
        return None

    @classmethod
    def _route_policy(cls, goal: Goal) -> dict[str, Any]:
        metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
        policy: dict[str, Any] = {}

        direct = metadata.get("route_policy")
        if isinstance(direct, dict):
            policy.update(direct)

        cognition = metadata.get("cognition_request")
        if isinstance(cognition, dict):
            context = cognition.get("context")
            if isinstance(context, dict):
                nested = context.get("route_policy")
                if isinstance(nested, dict):
                    policy.update(nested)
                pack = context.get("worker_context_pack")
                if isinstance(pack, dict):
                    classification = str(pack.get("data_classification") or "").strip()
                    if classification and "data_classification" not in policy:
                        policy["data_classification"] = classification
        return policy

    @staticmethod
    def _is_explicit_local_route(route: ModelRoute) -> bool:
        metadata = route.metadata if isinstance(route.metadata, dict) else {}
        if metadata.get("local") is True:
            return True
        deployment = str(metadata.get("deployment") or metadata.get("location") or "").strip().lower()
        return deployment in {"local", "on_device", "on-device", "localhost"}

    @staticmethod
    def _string_set(value: object, *, lower: bool) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            items: Iterable[object] = (value,)
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = value
        else:
            return set()
        result: set[str] = set()
        for item in items:
            text = str(item or "").strip()
            if text:
                result.add(text.lower() if lower else text)
        return result

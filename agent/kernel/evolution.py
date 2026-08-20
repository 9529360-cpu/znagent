from __future__ import annotations

import uuid

from .models import Experience, Goal, ImprovementProposal
from .self_model import SelfModel
from .store import KernelStore


class EvolutionEngine:
    """Produces evidence-backed candidate improvement proposals.

    V1 never mutates the live agent. It creates a proposal that a later
    experiment runner can implement in an isolated worktree, benchmark, and
    either promote or reject.
    """

    def __init__(self, store: KernelStore, self_model: SelfModel):
        self.store = store
        self.self_model = self_model

    def consider(self, goal: Goal, experience: Experience) -> ImprovementProposal | None:
        if experience.assessment.success and experience.assessment.quality >= 0.7:
            return None

        capabilities = goal.required_capabilities or ("general",)
        estimates = [self.self_model.get(cap) for cap in capabilities]
        weakest = min(estimates, key=lambda item: item.score)
        mature_weakness = weakest.evidence_count >= 3 and weakest.score < 0.65
        scope = "kernel_or_skill" if mature_weakness else "skill_or_policy"

        proposal = ImprovementProposal(
            proposal_id=f"imp-{uuid.uuid4().hex[:12]}",
            goal_id=goal.goal_id,
            capability=weakest.name,
            scope=scope,
            hypothesis=(
                f"The agent is underperforming on '{weakest.name}'. A bounded change "
                "to planning, routing, tool procedure, or kernel policy may improve "
                "verified task success without increasing regressions."
            ),
            experiment=(
                f"Reproduce goal {goal.goal_id} plus a regression set for "
                f"'{weakest.name}'. Implement the candidate only in an isolated "
                "worktree. Compare success rate, verification pass rate, latency, "
                "and cost against the current kernel. Promote only on a measured win."
            ),
        )
        self.store.add_proposal(proposal)
        return proposal

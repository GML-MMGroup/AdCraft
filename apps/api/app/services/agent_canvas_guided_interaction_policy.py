"""Deterministic policy for opening or bypassing guided concept choices."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_requirements import CapabilityRequirementProjectionV1


@dataclass(frozen=True)
class GuidedInteractionPolicyDecision:
    candidate_count: int
    requires_concept_interaction: bool
    reason: str


class GuidedInteractionPolicyService:
    """Select a bounded candidate count from canonical Requirement authority."""

    def decide_candidate_count(
        self,
        projection: CapabilityRequirementProjectionV1,
        *,
        default_candidate_count: int,
    ) -> GuidedInteractionPolicyDecision:
        if any(directive.strength == "hard" for directive in projection.relevant_directives):
            return GuidedInteractionPolicyDecision(
                candidate_count=1,
                requires_concept_interaction=False,
                reason="explicit_ledger_direction",
            )
        return GuidedInteractionPolicyDecision(
            candidate_count=max(2, default_candidate_count),
            requires_concept_interaction=True,
            reason="creative_direction_ambiguous",
        )

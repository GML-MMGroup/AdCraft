"""Deterministic policy for opening or bypassing guided concept choices."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_requirements import (
    CapabilityRequirementProjectionV1,
)


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
        if default_candidate_count not in {1, 3}:
            raise ValueError("Capability policy candidate count must be one or three.")
        if default_candidate_count == 1:
            return GuidedInteractionPolicyDecision(
                candidate_count=1,
                requires_concept_interaction=False,
                reason="single_candidate_capability",
            )
        return GuidedInteractionPolicyDecision(
            candidate_count=3,
            requires_concept_interaction=True,
            reason="normal_guided_proposal",
        )

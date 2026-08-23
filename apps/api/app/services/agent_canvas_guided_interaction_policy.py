"""Deterministic policy for opening or bypassing guided concept choices."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_requirements import (
    CapabilityRequirementProjectionV1,
    RequirementDirectiveV1,
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
        if any(
            _is_matching_local_hard_direction(projection, directive)
            for directive in projection.relevant_directives
        ):
            return GuidedInteractionPolicyDecision(
                candidate_count=1,
                requires_concept_interaction=False,
                reason="explicit_ledger_direction",
            )
        return GuidedInteractionPolicyDecision(
            candidate_count=default_candidate_count,
            requires_concept_interaction=default_candidate_count == 3,
            reason=(
                "creative_direction_ambiguous"
                if default_candidate_count == 3
                else "single_candidate_capability"
            ),
        )


def _is_matching_local_hard_direction(
    projection: CapabilityRequirementProjectionV1,
    directive: RequirementDirectiveV1,
) -> bool:
    if directive.strength != "hard":
        return False
    if directive.scope_kind == "node":
        # The requirement projection has already filtered node directives to the
        # current target node and its direct inputs.
        return True
    return (
        directive.scope_kind == "capability"
        and projection.capability_id in directive.capability_ids
    )

"""Resolve one immutable Character Proposal target from current authority."""

from __future__ import annotations

from typing import Literal

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    CapabilityIdV1,
    CharacterProposalTargetV1,
)
from app.schemas.agent_canvas_production_journey import JourneyActionProjectionV2
from app.schemas.agent_canvas_requirements import RequirementLedgerRevisionV1
from app.services.agent_canvas_requirements import character_occurrence_authority_for_authoring


def resolve_character_proposal_target(
    *,
    action: JourneyActionProjectionV2,
    requirement_revision: RequirementLedgerRevisionV1,
) -> CharacterProposalTargetV1:
    """Freeze the one included Character occurrence owned by a current action."""

    if (
        action.stage != "character"
        or action.action_kind != "invoke_capability:character_design"
        or action.occurrence_id is None
        or action.character_phase != "main"
    ):
        raise _scope_error("The current action does not identify a Character Main occurrence.")

    try:
        authority = character_occurrence_authority_for_authoring(requirement_revision)
    except V2PersistenceError as error:
        raise _scope_error(
            "The Character occurrence authority is invalid.",
            details={"authority_code": error.code},
        ) from error
    occurrences = authority.occurrences
    occurrence = next(
        (item for item in occurrences if item.occurrence_id == action.occurrence_id),
        None,
    )
    if occurrence is None:
        raise _scope_error("The current Character occurrence is not in the active Ledger.")
    if occurrence.occurrence_index != occurrences.index(occurrence) + 1:
        raise _scope_error("The current Character occurrence index is not authoritative.")

    return CharacterProposalTargetV1.create(
        occurrence_id=occurrence.occurrence_id,
        occurrence_index=occurrence.occurrence_index,
        occurrence_count=len(occurrences),
        requirement_revision_id=requirement_revision.revision_id,
        requirement_revision_no=requirement_revision.revision_no,
    )


def resolve_character_proposal_target_for_dispatch(
    *,
    action: JourneyActionProjectionV2 | None,
    capability_id: CapabilityIdV1,
    publication_kind: Literal["proposal", "internal_document"],
    requirement_revision: RequirementLedgerRevisionV1,
) -> CharacterProposalTargetV1 | None:
    """Project scope only for a guided Character Proposal dispatch."""

    if publication_kind != "proposal" or capability_id != "character_design":
        return None
    if action is None:
        raise _scope_error("A Character Proposal dispatch requires a current Journey action.")
    return resolve_character_proposal_target(
        action=action,
        requirement_revision=requirement_revision,
    )


def _scope_error(message: str, *, details: dict[str, object] | None = None) -> V2PersistenceError:
    return V2PersistenceError(
        "character_proposal_scope_invalid",
        message,
        stage="agent_canvas_character_proposal_scope",
        details=details or {},
    )

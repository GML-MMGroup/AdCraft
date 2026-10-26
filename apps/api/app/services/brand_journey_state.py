"""Deterministic stage order and transitions for the brand journey.

The brand journey never shares state with the fixed ad production journey.
Creation-mode journeys remain untouched; this module owns only
brand_professional_v1 stage ordering and successor logic.
"""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandJourneyStateV1,
    BrandStage,
    BrandTreatmentSubstep,
)

BRAND_STAGE_ORDER: tuple[BrandStage, ...] = (
    "brand-memory",
    "campaign",
    "hypothesis",
    "adspec",
    "skill-stack",
    "treatment",
    "production",
)

TREATMENT_SUBSTEP_ORDER: tuple[BrandTreatmentSubstep, ...] = (
    "hook",
    "story",
    "character",
    "scene",
    "visual",
    "camera",
    "editing",
    "sound",
)


def brand_successor(stage: BrandStage) -> BrandStage | None:
    """Return the deterministic successor of a brand stage."""

    index = BRAND_STAGE_ORDER.index(stage)
    if index + 1 >= len(BRAND_STAGE_ORDER):
        return None
    return BRAND_STAGE_ORDER[index + 1]


def treatment_substep_successor(
    substep: BrandTreatmentSubstep,
) -> BrandTreatmentSubstep | None:
    """Return the deterministic successor of a treatment sub-step."""

    index = TREATMENT_SUBSTEP_ORDER.index(substep)
    if index + 1 >= len(TREATMENT_SUBSTEP_ORDER):
        return None
    return TREATMENT_SUBSTEP_ORDER[index + 1]


def first_treatment_substep() -> BrandTreatmentSubstep:
    return TREATMENT_SUBSTEP_ORDER[0]


def advance_brand_stage(journey: BrandJourneyStateV1) -> BrandJourneyStateV1:
    """Advance one brand stage exactly once; replay is idempotent by evidence."""

    successor = brand_successor(journey.stage)
    if successor is None:
        raise _invalid("brand_journey_terminal_conflict")
    return journey.model_copy(
        update={
            "stage": successor,
            "treatment_substep": (first_treatment_substep() if successor == "treatment" else None),
            "stage_revision": journey.stage_revision + 1,
            "stage_status": "ready",
        }
    )


def advance_treatment_substep(journey: BrandJourneyStateV1) -> BrandJourneyStateV1:
    """Advance one treatment sub-step, or finish the treatment stage."""

    if journey.stage != "treatment":
        raise _invalid("brand_stage_action_mismatch")
    current = journey.treatment_substep or first_treatment_substep()
    successor = treatment_substep_successor(current)
    if successor is None:
        return journey.model_copy(
            update={"stage_status": "ready", "stage_revision": journey.stage_revision + 1}
        )
    return journey.model_copy(
        update={
            "treatment_substep": successor,
            "stage_revision": journey.stage_revision + 1,
            "stage_status": "ready",
        }
    )


def _invalid(code: str) -> V2PersistenceError:
    return V2PersistenceError(code, "Invalid brand journey transition.", stage="brand_journey")

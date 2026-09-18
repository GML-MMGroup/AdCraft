"""Fixed, versioned slot schemas for Brand Memory, Campaign, and AdSpec.

Capabilities may only reference slot ids declared here. Unknown slot ids fail
closed before any persistence write.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.brand_professional_mode import (
    BrandSlotValueV1,
    BrandStage,
)

SLOT_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class BrandSlotDefinition:
    slot_id: str
    stage: BrandStage
    required: bool
    question: str


_SLOTS: tuple[BrandSlotDefinition, ...] = (
    BrandSlotDefinition("brand_positioning", "brand-memory", False, "How is the brand positioned?"),
    BrandSlotDefinition("brand_audience", "brand-memory", True, "Who is the main audience?"),
    BrandSlotDefinition(
        "brand_personality", "brand-memory", False, "What is the brand personality?"
    ),
    BrandSlotDefinition("brand_price_band", "brand-memory", False, "What is the price band?"),
    BrandSlotDefinition("brand_avoid", "brand-memory", False, "What must the brand avoid?"),
    BrandSlotDefinition(
        "brand_product_visual", "brand-memory", False, "Is there a product visual reference?"
    ),
    BrandSlotDefinition(
        "campaign_goal", "campaign", True, "What is the advertising goal this time?"
    ),
    BrandSlotDefinition("campaign_platform", "campaign", True, "Which platform is this for?"),
    BrandSlotDefinition("campaign_duration", "campaign", True, "How long is the video?"),
    BrandSlotDefinition("campaign_aspect_ratio", "campaign", True, "What is the aspect ratio?"),
    BrandSlotDefinition("campaign_cta", "campaign", False, "Is there a call to action?"),
)

_SLOT_INDEX: dict[tuple[str, str], BrandSlotDefinition] = {
    (slot.stage, slot.slot_id): slot for slot in _SLOTS
}


def resolve_slot(stage: str, slot_id: str) -> BrandSlotDefinition:
    """Return the slot definition or raise brand_slot_unknown."""

    slot = _SLOT_INDEX.get((stage, slot_id))
    if slot is None:
        raise _unknown_slot(stage, slot_id)
    return slot


def slots_for_stage(stage: BrandStage) -> tuple[BrandSlotDefinition, ...]:
    return tuple(slot for slot in _SLOTS if slot.stage == stage)


def validate_slot_values(values: tuple[BrandSlotValueV1, ...]) -> None:
    """Fail closed on unknown slot ids or wrong stages before persistence."""

    for value in values:
        slot = _SLOT_INDEX.get((value.stage, value.slot_id))
        if slot is None:
            raise _unknown_slot(value.stage, value.slot_id)


def required_slots(stage: BrandStage) -> tuple[BrandSlotDefinition, ...]:
    return tuple(slot for slot in slots_for_stage(stage) if slot.required)


def missing_required_slots(
    stage: BrandStage,
    values: tuple[BrandSlotValueV1, ...],
) -> tuple[str, ...]:
    """Return required slot ids that are still not user-confirmed."""

    confirmed = {
        value.slot_id
        for value in values
        if value.stage == stage and value.provenance == "user_confirmed"
    }
    return tuple(slot.slot_id for slot in required_slots(stage) if slot.slot_id not in confirmed)


def _unknown_slot(stage: str, slot_id: str) -> ValueError:
    from app.persistence.errors import V2PersistenceError

    return V2PersistenceError(
        "brand_slot_unknown",
        f"Unknown brand slot: {stage}/{slot_id}",
        stage="brand_slot_schema",
    )

"""Fixed, versioned slot schemas for Brand Memory, Campaign, and AdSpec.

Capabilities may only reference slot ids declared here. Unknown slot ids fail
closed before any persistence write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.brand_professional_mode import (
    BrandSlotValueV1,
    BrandStage,
)

SLOT_SCHEMA_VERSION = "3"

# A slot declares the information nature a user-confirmed value carries.  Values
# the Agent inferred on its own are always tentative assumptions instead, so
# "assumption" is derived from provenance rather than declared per slot.
SlotKind = Literal["fact", "constraint", "preference"]
SlotValueKind = Literal["fact", "constraint", "preference", "assumption"]


@dataclass(frozen=True)
class BrandSlotDefinition:
    slot_id: str
    stage: BrandStage
    required: bool
    question: str
    kind: SlotKind = "fact"


_SLOTS: tuple[BrandSlotDefinition, ...] = (
    BrandSlotDefinition(
        "brand_product_identity",
        "brand-memory",
        True,
        "What product or service are we advertising?",
    ),
    BrandSlotDefinition(
        "brand_product_focus",
        "brand-memory",
        True,
        "Which primary use case or supported benefit should this advertisement emphasize?",
        kind="preference",
    ),
    BrandSlotDefinition(
        "brand_positioning",
        "brand-memory",
        False,
        "How is the brand positioned?",
        kind="preference",
    ),
    BrandSlotDefinition("brand_audience", "brand-memory", True, "Who is the main audience?"),
    BrandSlotDefinition(
        "brand_personality",
        "brand-memory",
        False,
        "What is the brand personality?",
        kind="preference",
    ),
    BrandSlotDefinition("brand_price_band", "brand-memory", False, "What is the price band?"),
    BrandSlotDefinition(
        "brand_avoid",
        "brand-memory",
        False,
        "What must the brand avoid?",
        kind="constraint",
    ),
    BrandSlotDefinition(
        "brand_product_visual", "brand-memory", False, "Is there a product visual reference?"
    ),
    BrandSlotDefinition("brand_name", "brand-memory", False, "What is the brand name?"),
    BrandSlotDefinition(
        "brand_required_elements",
        "brand-memory",
        False,
        "Which brand or product elements must appear?",
        kind="constraint",
    ),
    BrandSlotDefinition(
        "campaign_goal", "campaign", True, "What is the advertising goal this time?"
    ),
    BrandSlotDefinition("campaign_platform", "campaign", True, "Which platform is this for?"),
    BrandSlotDefinition(
        "campaign_duration", "campaign", True, "How long is the video?", kind="constraint"
    ),
    BrandSlotDefinition(
        "campaign_aspect_ratio", "campaign", True, "What is the aspect ratio?", kind="constraint"
    ),
    BrandSlotDefinition(
        "campaign_cta", "campaign", False, "Is there a call to action?", kind="preference"
    ),
    BrandSlotDefinition("campaign_name", "campaign", False, "What is this campaign called?"),
    BrandSlotDefinition(
        "campaign_audience", "campaign", False, "Who should this particular campaign reach?"
    ),
    BrandSlotDefinition(
        "campaign_core_message",
        "campaign",
        False,
        "What should viewers remember from this campaign?",
        kind="preference",
    ),
    BrandSlotDefinition(
        "campaign_non_goals",
        "campaign",
        False,
        "What should this campaign not emphasize?",
        kind="constraint",
    ),
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


def slot_value_kind(slot: BrandSlotDefinition, provenance: str) -> SlotValueKind:
    """Derive the information nature persisted with one slot value."""

    if provenance == "agent_recommended":
        return "assumption"
    return slot.kind


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

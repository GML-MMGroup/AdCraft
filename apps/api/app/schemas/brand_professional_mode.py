"""Contracts for the Brand Professional Mode decision journey."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BrandMode = Literal["creation", "brand"]
BrandStage = Literal[
    "brand-memory",
    "campaign",
    "hypothesis",
    "adspec",
    "skill-stack",
    "treatment",
    "production",
]
BrandTreatmentSubstep = Literal[
    "hook",
    "story",
    "character",
    "scene",
    "visual",
    "camera",
    "editing",
    "sound",
]
BrandCapabilityId = Literal[
    "brand-strategy",
    "creative-strategy",
    "creative-treatment",
]
SlotProvenance = Literal["user_confirmed", "agent_recommended"]
AdSpecItemState = Literal["locked", "open", "variable"]
SkillStackKind = Literal["creative_method", "audiovisual_style"]


class _BrandModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrandSlotValueV1(_BrandModel):
    """One persisted slot value with decision provenance."""

    slot_id: str = Field(min_length=1, max_length=80)
    stage: BrandStage
    value: str = Field(min_length=1, max_length=2000)
    kind: Literal["fact", "constraint", "preference", "assumption"] = "fact"
    provenance: SlotProvenance
    confirmed_at: datetime | None = None


class BrandShortOptionV1(_BrandModel):
    """One short option label with an optional collapsed explanation."""

    option_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=48)
    why: str | None = Field(default=None, max_length=240)


class BrandOptionCardV1(_BrandModel):
    """Exactly three short options for one slot question or sub-step."""

    card_id: str = Field(min_length=1, max_length=120)
    stage: BrandStage
    stage_revision: int = Field(ge=1)
    target_slot_id: str | None = Field(default=None, max_length=80)
    question: str = Field(min_length=1, max_length=400)
    options: tuple[BrandShortOptionV1, ...] = Field(min_length=3, max_length=3)


class BrandSlotEvidenceV1(_BrandModel):
    """Private evidence for a semantic slot update or conflict clarification."""

    stage: Literal["brand-memory", "campaign"]
    slot_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)
    source_quote: str = Field(min_length=1, max_length=2000)


class BrandStrategyOutputV1(_BrandModel):
    """Structured output of the brand-strategy capability."""

    slot_values: tuple[BrandSlotValueV1, ...] = Field(default=(), max_length=32)
    slot_evidence: tuple[BrandSlotEvidenceV1, ...] = Field(default=(), max_length=32)
    clarifications: tuple[BrandSlotEvidenceV1, ...] = Field(default=(), max_length=1)
    question_card: BrandOptionCardV1 | None = None


class CreativeHypothesisCandidateV1(_BrandModel):
    """One candidate creative hypothesis."""

    candidate_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=48)
    insight: str = Field(min_length=1, max_length=800)
    mechanism: str = Field(min_length=1, max_length=300)
    hypothesis: str = Field(min_length=1, max_length=1200)
    product_role: str = Field(min_length=1, max_length=300)
    hook_mechanism: str = Field(min_length=1, max_length=300)
    why: str | None = Field(default=None, max_length=240)


class CreativeStrategyOutputV1(_BrandModel):
    """Structured output of the creative-strategy capability."""

    # The MVP shows the user exactly three directions; the contract is exact so a
    # model that diverges internally cannot publish a 2- or 4-option card.
    candidates: tuple[CreativeHypothesisCandidateV1, ...] = Field(min_length=3, max_length=3)


class CreativeTreatmentStepOutputV1(_BrandModel):
    """Three options for one treatment sub-step."""

    step_key: BrandTreatmentSubstep
    question: str = Field(min_length=1, max_length=400)
    options: tuple[BrandShortOptionV1, ...] = Field(min_length=3, max_length=3)


class CreativeTreatmentOutputV1(_BrandModel):
    """Structured output of the creative-treatment capability."""

    step: CreativeTreatmentStepOutputV1


class AdSpecItemV1(_BrandModel):
    """One AdSpec line with its decision state."""

    item_key: str = Field(min_length=1, max_length=80)
    item_text: str = Field(min_length=1, max_length=600)
    state: AdSpecItemState = "open"


class AdSpecStateV1(_BrandModel):
    """Locked / open / variable view of the confirmed AdSpec."""

    items: tuple[AdSpecItemV1, ...] = Field(min_length=1, max_length=64)


class SkillStackEntryV1(_BrandModel):
    """One skill inside the confirmed skill stack."""

    skill_kind: SkillStackKind
    skill_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    selected: bool = True
    version: str | None = Field(default=None, min_length=1, max_length=80)
    reason: str | None = Field(default=None, min_length=1, max_length=600)


class BrandSkillReferenceV1(_BrandModel):
    skill_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)


class BrandSkillRecommendationV1(BrandSkillReferenceV1):
    reason: str = Field(min_length=1, max_length=600)


class BrandSkillRecommendationsV1(_BrandModel):
    creative_methods: tuple[BrandSkillRecommendationV1, ...] = Field(min_length=1, max_length=7)
    audiovisual_styles: tuple[BrandSkillRecommendationV1, ...] = Field(min_length=3, max_length=3)


class BrandCreativeMethodV1(BrandSkillReferenceV1):
    skill_kind: Literal["creative_method"] = "creative_method"
    title: str
    summary: str


class BrandCreativeMethodCatalogV1(_BrandModel):
    items: tuple[BrandCreativeMethodV1, ...]


class BrandSkillSelectionRequestV1(_BrandModel):
    """Save a user draft or explicitly confirm it; never infer choices from prose."""

    card_id: str = Field(min_length=1, max_length=120)
    expected_stage_revision: int = Field(ge=1)
    creative_methods: tuple[BrandSkillReferenceV1, ...] = Field(min_length=1, max_length=7)
    audiovisual_style: BrandSkillReferenceV1
    confirm: bool = False


class SkillStackV1(_BrandModel):
    """Confirmed creative method and audiovisual style skills."""

    entries: tuple[SkillStackEntryV1, ...] = Field(default=(), max_length=64)


class TreatmentStepResultV1(_BrandModel):
    """One confirmed treatment sub-step."""

    step_key: BrandTreatmentSubstep
    selected_label: str = Field(min_length=1, max_length=160)
    detail: str = Field(default="", max_length=2000)
    confirmed_at: datetime


class BrandJourneyStateV1(_BrandModel):
    """Deterministic brand journey projection."""

    policy_version: Literal["brand_professional_v1"] = "brand_professional_v1"
    stage: BrandStage = "brand-memory"
    treatment_substep: BrandTreatmentSubstep | None = None
    stage_revision: int = Field(default=1, ge=1)
    stage_status: Literal["ready", "working", "waiting_user", "completed"] = "ready"


class BrandDecisionPanelV1(_BrandModel):
    """Read model behind the frontend decision panel."""

    project_id: str
    workflow_id: str
    mode: BrandMode
    journey: BrandJourneyStateV1
    brand_name: str
    slot_values: tuple[BrandSlotValueV1, ...] = Field(default=(), max_length=128)
    open_card: BrandOptionCardV1 | None = None
    hypotheses: tuple[CreativeHypothesisCandidateV1, ...] = Field(default=(), max_length=8)
    selected_hypothesis_id: str | None = None
    adspec: AdSpecStateV1 | None = None
    skill_stack: SkillStackV1 | None = None
    treatment_steps: tuple[TreatmentStepResultV1, ...] = Field(default=(), max_length=8)
    treatment_locked: bool = False


class BrandDecisionLogEntryV1(_BrandModel):
    """One immutable decision log record."""

    log_id: str
    stage: BrandStage
    action: Literal[
        "select",
        "reject",
        "fusion",
        "recommend",
        "edit",
        "confirm",
        "lock",
    ]
    target_type: str = Field(min_length=1, max_length=60)
    target_id: str | None = None
    detail: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class BrandInspectionConversationTurnV1(_BrandModel):
    """One full conversation turn for developer inspection."""

    turn_id: str
    role: Literal["user", "assistant", "system"]
    text: str = ""
    selected_option_ids: tuple[str, ...] = Field(default=(), max_length=8)
    created_at: datetime


class BrandSlotActionRequestV1(_BrandModel):
    """User selection for one open option card."""

    card_id: str = Field(min_length=1, max_length=120)
    option_id: str = Field(min_length=1, max_length=80)
    value_text: str = Field(min_length=1, max_length=2000)
    provenance: SlotProvenance = "user_confirmed"


class BrandHypothesisActionRequestV1(_BrandModel):
    """User selection of one creative hypothesis candidate."""

    hypothesis_id: str = Field(min_length=1, max_length=80)


class BrandTreatmentActionRequestV1(_BrandModel):
    """User selection for one open treatment option card."""

    card_id: str = Field(min_length=1, max_length=120)
    option_id: str = Field(min_length=1, max_length=80)
    selected_label: str = Field(min_length=1, max_length=160)
    detail: str = Field(default="", max_length=2000)


class BrandLockActionRequestV1(_BrandModel):
    """Treatment lock request; accepted only after all eight sub-steps."""

    confirm: bool = True

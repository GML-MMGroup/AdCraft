"""Role-local transport of immutable reviewed Brand decisions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.brand_professional_mode import (
    AdSpecStateV1,
    BrandAssetReferenceV1,
    BrandBriefSummaryV1,
    BrandTreatmentSubstep,
    CreativeHypothesisCandidateV1,
    SkillStackV1,
)
from app.schemas.brand_treatment_detail import TreatmentSectionV1

BrandProductionRoleV1 = Literal[
    "general", "script", "product", "character", "scene", "storyboard", "video", "bgm"
]


class BrandProductionStepV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_key: BrandTreatmentSubstep
    selected_label: str = Field(min_length=1, max_length=160)
    sections: tuple[TreatmentSectionV1, ...] = Field(default=(), max_length=4)
    legacy_detail: str | None = Field(default=None, max_length=2000)


class BrandProductionContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_version: Literal["brand_role_v1"] = "brand_role_v1"
    source_content_digest: str
    role: BrandProductionRoleV1
    brand_profile: BrandBriefSummaryV1
    campaign_brief: BrandBriefSummaryV1
    selected_hypothesis: CreativeHypothesisCandidateV1 | None = None
    adspec: AdSpecStateV1 | None = None
    skill_stack: SkillStackV1 | None = None
    treatment_steps: tuple[BrandProductionStepV1, ...] = Field(default=(), max_length=8)
    omitted_sections: tuple[str, ...] = ()
    authorized_asset_references: tuple[BrandAssetReferenceV1, ...] = ()
    complete: bool
    missing_sections: tuple[str, ...] = ()
    execution_limitations: tuple[str, ...] = ()

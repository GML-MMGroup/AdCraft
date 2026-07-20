from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_planning import (
    V2BgmBrief,
    V2CharacterBrief,
    V2ExpertBriefPlan,
    V2ProductBrief,
    V2SceneBrief,
)
from app.schemas.workflow_v2_screenplay import (
    V2ScriptPlanV2,
    V2SpecialistHandoffContext,
)


class V2ExpertBriefInputAssetDescriptor(BaseModel):
    asset_id: str
    version_id: str | None = None
    display_name: str | None = None
    media_type: Literal["image", "video", "audio", "text"] | str = "image"
    semantic_type: str | None = None
    public_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2ExpertBriefPlannerInput(BaseModel):
    workflow_id: str
    script_plan: V2ScriptPlanV2
    request: WorkflowV2PlanFromPromptRequest
    input_asset_descriptors: list[V2ExpertBriefInputAssetDescriptor] = Field(default_factory=list)
    normalized_request: dict[str, Any] = Field(default_factory=dict)
    specialist_handoffs: list[V2SpecialistHandoffContext] = Field(default_factory=list)


class V2ExpertBriefPlannerOutput(BaseModel):
    script_brief_id: str
    script_version_id: str
    product_briefs: list[V2ProductBrief] = Field(default_factory=list)
    character_briefs: list[V2CharacterBrief] = Field(default_factory=list)
    scene_briefs: list[V2SceneBrief] = Field(default_factory=list)
    bgm_brief: V2BgmBrief
    specialist_quality_audit: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    def to_plan(self) -> V2ExpertBriefPlan:
        return V2ExpertBriefPlan(
            script_brief_id=self.script_brief_id,
            script_version_id=self.script_version_id,
            product_briefs=self.product_briefs,
            character_briefs=self.character_briefs,
            scene_briefs=self.scene_briefs,
            bgm_brief=self.bgm_brief,
            specialist_quality_audit=self.specialist_quality_audit,
            metadata=self.metadata,
            warnings=self.warnings,
        )


class V2ExpertBriefQualityFailure(BaseModel):
    code: str
    message: str
    item_id: str | None = None
    slot_type: str | None = None
    evidence: str | None = None


class V2ExpertBriefQualityResult(BaseModel):
    passed: bool
    failures: list[V2ExpertBriefQualityFailure] = Field(default_factory=list)


class V2ExpertBriefRepairContext(BaseModel):
    failed_output: V2ExpertBriefPlannerOutput | None = None
    quality_result: V2ExpertBriefQualityResult | None = None
    validation_error_paths: list[str] = Field(default_factory=list)

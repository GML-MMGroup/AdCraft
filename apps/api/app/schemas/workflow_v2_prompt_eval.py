from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.workflow_v2_acceptance import V2WorkflowAcceptanceReport


V2PromptEvalMode = Literal["mock", "real", "workflow_acceptance"]
V2PromptEvalReplayMode = Literal["mock", "workflow_acceptance"]
V2PromptEvalStage = Literal[
    "script_writer",
    "expert_brief",
    "specialist_prompts",
    "storyboard_detail_prompts",
    "reference_bundle",
    "provider_payload",
    "all",
]
V2PromptEvalStatus = Literal["passed", "failed", "partial_failed", "error"]


class V2PromptEvalAdRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    product_name: str | None = Field(default=None, max_length=120)
    duration_seconds: int = Field(default=30, ge=1, le=300)
    aspect_ratio: str = "16:9"
    audio_mode: Literal["none", "bgm_only", "full"] = "bgm_only"
    reference_mode: Literal["best_effort", "strict"] = "best_effort"
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2PromptEvalInputAssetDescriptor(BaseModel):
    asset_id: str
    version_id: str | None = None
    display_name: str | None = None
    media_type: Literal["image", "video", "audio", "text"] = "image"
    semantic_type: str = "generic_reference"
    file_path: str | None = None
    public_url: str | None = None
    reference_role: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2PromptEvalQualityAssertion(BaseModel):
    gate: str
    severity: Literal["hard", "soft"] = "soft"
    expected: Literal["pass", "fail"] = "pass"
    notes: str | None = None


class V2PromptEvalFixture(BaseModel):
    fixture_id: str
    title: str
    ad_request: V2PromptEvalAdRequest
    input_asset_descriptors: list[V2PromptEvalInputAssetDescriptor] = Field(default_factory=list)
    expected_language: str = "English"
    expected_ad_type: str
    expected_slots: list[str] = Field(default_factory=list)
    quality_assertions: list[V2PromptEvalQualityAssertion] = Field(default_factory=list)


class V2PromptProfilePayloadInjection(BaseModel):
    key: str
    value: Any
    stages: list[V2PromptEvalStage] = Field(default_factory=lambda: ["provider_payload"])


class V2PromptProfile(BaseModel):
    profile_id: str
    title: str
    description: str = ""
    prompt_suffix: str | None = None
    specialist_prompt_suffix: str | None = None
    provider_payload_injections: list[V2PromptProfilePayloadInjection] = Field(default_factory=list)


class V2PromptEvalRunRequest(BaseModel):
    fixture_id: str
    prompt_profile_id: str = "current"
    mode: V2PromptEvalMode = "mock"
    selected_stages: list[V2PromptEvalStage] = Field(default_factory=lambda: ["all"])

    @field_validator("selected_stages", mode="after")
    @classmethod
    def normalize_selected_stages(cls, value: list[V2PromptEvalStage]) -> list[V2PromptEvalStage]:
        return value or ["all"]


class V2PromptEvalReplayRequest(BaseModel):
    prompt_profile_id: str = "current"
    mode: V2PromptEvalReplayMode = "mock"
    selected_stages: list[V2PromptEvalStage] = Field(default_factory=lambda: ["all"])

    @field_validator("selected_stages", mode="after")
    @classmethod
    def normalize_selected_stages(cls, value: list[V2PromptEvalStage]) -> list[V2PromptEvalStage]:
        return value or ["all"]


class V2PromptEvalComparisonRequest(BaseModel):
    baseline_profile_id: str = "current"
    candidate_profile_id: str = "candidate"
    fixture_ids: list[str] = Field(default_factory=list)
    mode: V2PromptEvalMode = "mock"
    selected_stages: list[V2PromptEvalStage] = Field(default_factory=lambda: ["all"])


class V2PromptEvalQualityFailure(BaseModel):
    failure_code: str
    message: str
    stage: V2PromptEvalStage
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    gate: str
    hard_failure: bool = False
    evidence: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    owner: str | None = None
    prompt_scope: str | None = None
    path_kind: str | None = None


class V2PromptEvalPromptOutput(BaseModel):
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    media_type: str | None = None
    prompt: str | None = None
    provider_prompt: str | None = None
    canonical_provider_prompt: str | None = None
    captured_provider_request_prompt: str | None = None
    provider_prompt_match: bool | None = None
    materializer_mode: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    prompt_isolation_audit: dict[str, Any] = Field(default_factory=dict)
    prompt_registry_ref: dict[str, Any] = Field(default_factory=dict)
    prompt_lineage: dict[str, Any] = Field(default_factory=dict)
    provider_request_capture: dict[str, Any] = Field(default_factory=dict)
    provider_payload_summary: dict[str, Any] = Field(default_factory=dict)


class V2PromptEvalStageResult(BaseModel):
    stage: V2PromptEvalStage
    status: V2PromptEvalStatus
    checked_item_count: int = 0
    checked_slot_count: int = 0
    outputs: list[V2PromptEvalPromptOutput] = Field(default_factory=list)
    failures: list[V2PromptEvalQualityFailure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class V2PromptEvalReport(BaseModel):
    eval_run_id: str
    status: V2PromptEvalStatus
    mode: V2PromptEvalMode
    profile_id: str
    fixture_id: str | None = None
    workflow_id: str | None = None
    selected_stages: list[V2PromptEvalStage] = Field(default_factory=list)
    stages: list[V2PromptEvalStageResult] = Field(default_factory=list)
    failures: list[V2PromptEvalQualityFailure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report_path: str | None = None
    trace_path: str | None = None
    created_at: str
    error_code: str | None = None
    error_message: str | None = None
    acceptance_report: V2WorkflowAcceptanceReport | None = None
    provider_payload_captures: list[dict[str, Any]] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    prompt_lineage: list[dict[str, Any]] = Field(default_factory=list)


class V2PromptEvalComparisonReport(BaseModel):
    eval_run_id: str
    status: V2PromptEvalStatus
    baseline_profile_id: str
    candidate_profile_id: str
    fixture_ids: list[str] = Field(default_factory=list)
    mode: V2PromptEvalMode
    selected_stages: list[V2PromptEvalStage] = Field(default_factory=list)
    baseline_reports: list[V2PromptEvalReport] = Field(default_factory=list)
    candidate_reports: list[V2PromptEvalReport] = Field(default_factory=list)
    regressions: list[V2PromptEvalQualityFailure] = Field(default_factory=list)
    report_path: str | None = None
    trace_path: str | None = None
    created_at: str
    error_code: str | None = None
    error_message: str | None = None

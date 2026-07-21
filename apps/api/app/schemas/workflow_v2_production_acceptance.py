from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest, WorkflowV2RuntimeSnapshot
from app.schemas.workflow_v2_acceptance import V2WorkflowAcceptanceExpectedCounts


V2ProductionAcceptanceLifecycleStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "blocked",
    "failed",
    "cancelled",
]
V2ProductionAcceptanceTechnicalVerdict = Literal["pending", "passed", "failed"]


class V2ProductionAcceptanceInputAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str
    intent: Literal["product_reference", "style_reference", "generic_reference"]
    display_name: str
    content_type: str


class V2ProductionAcceptanceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    title: str
    request: WorkflowV2PlanFromPromptRequest
    expected_counts: V2WorkflowAcceptanceExpectedCounts
    required_nodes: list[str] = Field(default_factory=list)
    required_slot_types: dict[str, list[str]] = Field(default_factory=dict)
    required_reference_relationships: list[dict[str, Any]] = Field(default_factory=list)
    input_assets: list[V2ProductionAcceptanceInputAsset] = Field(default_factory=list)
    manual_review_checks: list[str] = Field(default_factory=list)


class V2ProductionAcceptanceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str


class V2ProductionAcceptanceBlocker(BaseModel):
    code: str
    stage: Literal["preflight"] = "preflight"
    message: str
    capability: str | None = None


class V2ProductionAcceptanceFailure(BaseModel):
    code: str
    source_error_code: str | None = None
    stage: str
    message: str
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    provider_task_id: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class _LifecycleVerdictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: V2ProductionAcceptanceLifecycleStatus
    technical_verdict: V2ProductionAcceptanceTechnicalVerdict

    @model_validator(mode="after")
    def validate_lifecycle_verdict(self) -> "_LifecycleVerdictModel":
        expected = {
            "queued": "pending",
            "running": "pending",
            "waiting": "pending",
            "blocked": "pending",
            "completed": "passed",
            "failed": "failed",
            "cancelled": "failed",
        }[self.lifecycle_status]
        if self.technical_verdict != expected:
            raise ValueError(f"{self.lifecycle_status} requires technical_verdict={expected}.")
        return self


class V2ProductionAcceptanceRunState(_LifecycleVerdictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(ge=1)
    acceptance_run_id: str
    fixture_id: str
    idempotency_key_hash: str
    current_stage: str
    workflow_id: str | None = None
    execution_id: str | None = None
    blockers: list[V2ProductionAcceptanceBlocker] = Field(default_factory=list)
    failure: V2ProductionAcceptanceFailure | None = None
    report_path: str | None = None
    review_path: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class V2ProductionAcceptanceRunView(_LifecycleVerdictModel):
    acceptance_run_id: str
    fixture_id: str
    current_stage: str
    workflow_id: str | None = None
    execution_id: str | None = None
    blockers: list[V2ProductionAcceptanceBlocker] = Field(default_factory=list)
    failure: V2ProductionAcceptanceFailure | None = None
    runtime: WorkflowV2RuntimeSnapshot | None = None
    report_available: bool
    review_available: bool
    report_url: str | None = None
    review_url: str | None = None
    idempotent_replay: bool = False
    created_at: str
    updated_at: str
    finished_at: str | None = None


class V2ProductionAcceptanceCheck(BaseModel):
    check_id: str
    stage: str
    status: Literal["passed", "failed", "warning", "not_run"]
    message: str
    subject_ids: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


class V2ProductionAcceptanceMediaProbe(BaseModel):
    media_type: Literal["image", "video", "audio"]
    readable: bool
    size_bytes: int = Field(ge=0)
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_video: bool = False
    has_audio: bool = False
    error: str | None = None


class V2ProductionAcceptanceReviewEntry(BaseModel):
    order: int = Field(ge=1)
    group: Literal[
        "product",
        "character",
        "scene",
        "storyboard",
        "bgm",
        "final_composition",
    ]
    node_id: str
    item_id: str
    slot_id: str
    slot_type: str
    asset_id: str
    version_id: str
    public_url: str | None = None
    summary_prompt: str | None = None
    specialist_prompt: str | None = None
    provider_prompt: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    provider_model: str | None = None
    probe: V2ProductionAcceptanceMediaProbe
    warnings: list[str] = Field(default_factory=list)


class V2ProductionAcceptanceReport(_LifecycleVerdictModel):
    schema_version: Literal[1] = 1
    acceptance_run_id: str
    fixture_id: str
    workflow_id: str | None = None
    execution_id: str | None = None
    manual_review_required: bool = False
    fixture_snapshot: dict[str, Any]
    capability_snapshot: dict[str, Any]
    checks: list[V2ProductionAcceptanceCheck]
    failures: list[V2ProductionAcceptanceFailure]
    warnings: list[str]
    metrics: dict[str, Any]
    provider_task_summaries: list[dict[str, Any]]
    review_manifest: list[V2ProductionAcceptanceReviewEntry]
    created_at: str

    @model_validator(mode="after")
    def validate_review_requirement(self) -> "V2ProductionAcceptanceReport":
        expected = self.technical_verdict == "passed"
        if self.manual_review_required != expected:
            raise ValueError("manual_review_required is true only for a passed technical verdict.")
        return self

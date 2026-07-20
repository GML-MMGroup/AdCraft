from typing import Any, Literal

from pydantic import BaseModel, Field


QualityStatus = Literal["unchecked", "passed", "warning", "failed", "unavailable"]
QualityIssueSeverity = Literal["info", "warning", "error"]


class QualityIssue(BaseModel):
    code: str
    severity: QualityIssueSeverity
    message: str
    asset_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AssetQualityReview(BaseModel):
    quality_status: QualityStatus
    quality_score: float
    quality_issues: list[QualityIssue]
    quality_warnings: list[str] = Field(default_factory=list)
    reviewer: str


class NodeQualitySummary(BaseModel):
    status: QualityStatus
    score: float
    reviewed_assets: int
    passed_assets: int
    warning_assets: int
    failed_assets: int
    unavailable_assets: int
    reviewer: str
    issues: list[QualityIssue] = Field(default_factory=list)


class WorkflowQualityReviewResponse(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    quality_summary: NodeQualitySummary
    assets: list[dict[str, Any]] = Field(default_factory=list)

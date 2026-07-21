from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class V2WorkflowAcceptanceExpectedCounts(BaseModel):
    product_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    scene_count: int = Field(ge=0)
    storyboard_shot_count: int = Field(ge=0)


class V2WorkflowAcceptanceFixture(BaseModel):
    fixture_id: str
    title: str
    input_prompt: str
    duration_seconds: int = Field(default=30, ge=1)
    expected_counts: V2WorkflowAcceptanceExpectedCounts
    required_nodes: list[str] = Field(default_factory=list)
    required_slot_types: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_terms_by_slot_type: dict[str, list[str]] = Field(default_factory=dict)
    required_reference_relationships: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class V2WorkflowAcceptanceFailure(BaseModel):
    code: str
    stage: str
    fixture_id: str
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    message: str


class V2WorkflowAcceptanceCheck(BaseModel):
    name: str
    status: Literal["passed", "failed"]
    failures: list[V2WorkflowAcceptanceFailure] = Field(default_factory=list)


class V2WorkflowAcceptanceReport(BaseModel):
    status: Literal["passed", "failed"]
    fixture_id: str
    workflow_id: str | None = None
    checks: list[V2WorkflowAcceptanceCheck]
    failures: list[V2WorkflowAcceptanceFailure]
    provider_payload_snapshots: list[dict[str, Any]] = Field(default_factory=list)

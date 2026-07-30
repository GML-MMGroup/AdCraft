"""Shared durable contracts for progressive Agent Canvas creative sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.agent_canvas import (
    CanvasBindingKindV2,
    CanvasInputRoleV2,
    CanvasNodeTypeV2,
)


AgentCanvasSpecialistNameV2 = Literal[
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
]
GuidedDeliveryActionTypeV2 = Literal[
    "add_another_node",
    "generate_existing_drafts",
    "continue_to_composition",
    "prepare_composition",
    "edit_composition_sources",
    "export_current_cut",
    "skip_topic",
]


class _CreativeSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidedDeliveryActionV2(_CreativeSessionModel):
    action: GuidedDeliveryActionTypeV2
    label: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    topic_id: str | None = Field(default=None, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    ordered_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    manifest_revision: int | None = Field(default=None, ge=1)
    confirmation_required: bool
    reason: str = Field(min_length=1, max_length=1_024)


class PlanningTopicProgressV2(_CreativeSessionModel):
    topic_id: str = Field(min_length=1, max_length=160)
    topic_kind: str = Field(min_length=1, max_length=80)
    display_order: int = Field(ge=0)
    required: bool
    specialist_name: AgentCanvasSpecialistNameV2
    status: Literal[
        "pending",
        "working",
        "completed",
        "skipped",
        "deferred",
        "reopened",
    ]
    outcome: str | None = Field(default=None, max_length=160)
    related_node_ids: tuple[str, ...] = Field(default=(), max_length=32)


class CreativeSessionStateV2(_CreativeSessionModel):
    skill_run_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    skill_id: str = Field(min_length=1, max_length=160)
    skill_version: str = Field(min_length=1, max_length=80)
    status: Literal["active", "superseded"]
    current_topic_id: str | None = Field(default=None, max_length=160)
    topics: tuple[PlanningTopicProgressV2, ...] = Field(default=(), max_length=32)
    deferred_topic_ids: tuple[str, ...] = Field(default=(), max_length=32)
    memory_revision: int = Field(ge=0)
    updated_at: datetime


class ProjectCreativeMemoryV2(_CreativeSessionModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    creative_goal: str = Field(default="", max_length=4_000)
    target_audience: str = Field(default="", max_length=2_000)
    duration_format: str = Field(default="", max_length=256)
    approved_style_summary: str = Field(default="", max_length=4_000)
    approved_node_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    open_questions: tuple[str, ...] = Field(default=(), max_length=32)
    deferred_topics: tuple[str, ...] = Field(default=(), max_length=32)
    rejection_notes: tuple[str, ...] = Field(default=(), max_length=32)
    conversation_summary: str = Field(default="", max_length=16_384)
    summary_through_sequence_no: int = Field(default=0, ge=0)
    memory_revision: int = Field(ge=0)
    updated_at: datetime


class DraftReferenceIntentV2(_CreativeSessionModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    binding_kind: CanvasBindingKindV2
    input_role: CanvasInputRoleV2
    required: bool = True
    display_order: int = Field(ge=0, le=127)


class ProposedDraftReferenceV2(DraftReferenceIntentV2):
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class SpecialistDraftV2(_CreativeSessionModel):
    node_type: CanvasNodeTypeV2
    semantic_role: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(min_length=1, max_length=8_192)
    generation_prompt: str | None = Field(default=None, max_length=32_768)
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    reference_intents: tuple[DraftReferenceIntentV2, ...] = Field(
        default=(),
        max_length=64,
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=32)


class ExpertActivityV2(_CreativeSessionModel):
    activity_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    specialist_name: AgentCanvasSpecialistNameV2
    operation: Literal["propose_concepts", "revise_concepts", "materialize_draft"]
    status: Literal["started", "waiting", "completed", "failed"]
    error_code: str | None = Field(default=None, max_length=160)
    error_message: str | None = Field(default=None, max_length=1_024)
    created_at: datetime
    updated_at: datetime | None = None


class ResolvedImageTargetV2(_CreativeSessionModel):
    asset_id: str = Field(min_length=1, max_length=160)
    owner_node_id: str | None = Field(default=None, max_length=160)
    owner_semantic_role: str | None = Field(default=None, max_length=160)
    specialist_name: AgentCanvasSpecialistNameV2 | Literal["quick_media_agent"]
    display_name: str = Field(min_length=1, max_length=256)
    checksum: str = Field(min_length=1, max_length=160)

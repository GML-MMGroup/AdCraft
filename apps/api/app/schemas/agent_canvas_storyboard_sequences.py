"""Sequence-local authoring contracts for guided storyboard production."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_working_documents import (
    AgentAnchorV2,
    StoryboardNarrativeSegmentV2,
    StoryboardPlanRowV2,
)


class _StoryboardSequenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryboardSequenceRowDraftV2(_StoryboardSequenceModel):
    panel_index: int = Field(ge=1, le=9)
    content_beat: str = Field(min_length=1, max_length=4_096)
    anchor_aliases: tuple[str, ...] = Field(default=(), max_length=64)
    camera_description: str = Field(min_length=1, max_length=4_096)

    @model_validator(mode="after")
    def validate_anchor_aliases(self) -> "StoryboardSequenceRowDraftV2":
        if len(self.anchor_aliases) != len(set(self.anchor_aliases)):
            raise ValueError("Storyboard row anchor aliases must be unique.")
        return self


class StoryboardSequenceDraftV2(_StoryboardSequenceModel):
    sequence_id: str = Field(min_length=1, max_length=160)
    narrative_goal: str = Field(min_length=1, max_length=4_096)
    start_state: str = Field(min_length=1, max_length=2_048)
    end_state: str = Field(min_length=1, max_length=2_048)
    continuity_from_previous: str | None = Field(default=None, max_length=2_048)
    rows: tuple[StoryboardSequenceRowDraftV2, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_rows(self) -> "StoryboardSequenceDraftV2":
        if [row.panel_index for row in self.rows] != list(range(1, 10)):
            raise ValueError("Storyboard sequence panels must be ordered from 1 through 9.")
        return self


class StoryboardSequencePlanDraftV2(_StoryboardSequenceModel):
    narrative_outline: str = Field(min_length=1, max_length=16_384)
    aspect_ratio: str = Field(min_length=1, max_length=32)
    total_duration_seconds: float = Field(gt=0, le=3_600)
    sequences: tuple[StoryboardSequenceDraftV2, ...] = Field(
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_sequence_ids(self) -> "StoryboardSequencePlanDraftV2":
        sequence_ids = [sequence.sequence_id for sequence in self.sequences]
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("Storyboard sequence ids must be unique.")
        return self


class StoryboardOutlineSegmentDraftV2(_StoryboardSequenceModel):
    order: int = Field(ge=1, le=128)
    start_seconds: float = Field(ge=0, le=3_600)
    end_seconds: float = Field(gt=0, le=3_600)
    narrative_goal: str = Field(min_length=1, max_length=4_096)
    start_state: str = Field(min_length=1, max_length=2_048)
    end_state: str = Field(min_length=1, max_length=2_048)
    continuity_from_previous: str | None = Field(default=None, max_length=2_048)

    @model_validator(mode="after")
    def validate_timing(self) -> "StoryboardOutlineSegmentDraftV2":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Storyboard outline segment end must follow its start.")
        return self


class StoryboardSequenceOutlineDraftV2(_StoryboardSequenceModel):
    narrative_outline: str = Field(min_length=1, max_length=16_384)
    aspect_ratio: str = Field(min_length=1, max_length=32)
    total_duration_seconds: float = Field(gt=0, le=3_600)
    segments: tuple[StoryboardOutlineSegmentDraftV2, ...] = Field(min_length=1, max_length=128)


class StoryboardSegmentMaterializationDraftV2(_StoryboardSequenceModel):
    rows: tuple[StoryboardSequenceRowDraftV2, ...] = Field(min_length=9, max_length=9)
    generation_prompt: str = Field(min_length=1, max_length=16_384)

    @model_validator(mode="after")
    def validate_rows(self) -> "StoryboardSegmentMaterializationDraftV2":
        if [row.panel_index for row in self.rows] != list(range(1, 10)):
            raise ValueError("Storyboard segment panels must be ordered from 1 through 9.")
        return self


class StoryboardSegmentAuthoringContextV2(_StoryboardSequenceModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    plan_content_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    sequence: StoryboardNarrativeSegmentV2
    prior_end_state: str | None = Field(default=None, max_length=2_048)
    anchors: tuple[AgentAnchorV2, ...] = Field(default=(), max_length=64)
    style_excerpt: str | None = Field(default=None, max_length=8_192)


class StoryboardGridAuthoringContextV2(_StoryboardSequenceModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    plan_revision: int = Field(ge=1)
    plan_content_digest: str = Field(pattern=r"^sha256:[0-9a-zA-Z_-]+$")
    sequence: StoryboardNarrativeSegmentV2
    rows: tuple[StoryboardPlanRowV2, ...] = Field(min_length=9, max_length=9)
    anchors: tuple[AgentAnchorV2, ...] = Field(default=(), max_length=64)
    style_excerpt: str | None = Field(default=None, max_length=8_192)

    @model_validator(mode="after")
    def validate_sequence_scope(self) -> "StoryboardGridAuthoringContextV2":
        if any(row.sequence_id != self.sequence.sequence_id for row in self.rows):
            raise ValueError("Storyboard context rows must belong to one sequence.")
        if [row.panel_index for row in self.rows] != list(range(1, 10)):
            raise ValueError("Storyboard context requires panels 1 through 9.")
        return self


class StoryboardVideoAuthoringContextV2(StoryboardGridAuthoringContextV2):
    storyboard_grid_node_id: str | None = Field(default=None, max_length=160)
    resolved_binding_ids: tuple[str, ...] = Field(default=(), max_length=64)

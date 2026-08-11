"""Bounded contracts for progressive Agent Canvas stage authoring."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import CanvasCreativeRoleV2, CanvasNodeTypeV2
from app.schemas.agent_canvas_commands import AgentPlacementHintV2
from app.schemas.agent_canvas_conversation import ConceptOptionRecordV2
from app.schemas.agent_canvas_creative_session import (
    CreativeGoalV2,
    DraftReferenceIntentV2,
    ProposedDraftReferenceV2,
)
from app.schemas.agent_canvas_production_journey import JourneyStageV1
from app.schemas.agent_working_documents import AgentDocumentContextExcerptV2


class _ProgressiveAuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidedQuestionChoiceV1(_ProgressiveAuthoringModel):
    choice_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2_048)


class GuidedQuestionV1(_ProgressiveAuthoringModel):
    question_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=2_048)
    choices: tuple[GuidedQuestionChoiceV1, ...] = Field(min_length=2, max_length=5)
    allow_free_text: bool
    requirement_paths: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_unique_choices(self) -> "GuidedQuestionV1":
        choice_ids = tuple(choice.choice_id for choice in self.choices)
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("Guided question choice IDs must be unique.")
        if len(self.requirement_paths) != len(set(self.requirement_paths)):
            raise ValueError("Guided question requirement paths must be unique.")
        return self


class GuidedQuestionnaireV1(_ProgressiveAuthoringModel):
    questions: tuple[GuidedQuestionV1, ...] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=2_048)

    @model_validator(mode="after")
    def validate_unique_questions(self) -> "GuidedQuestionnaireV1":
        question_ids = tuple(question.question_id for question in self.questions)
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Guided questionnaire IDs must be unique.")
        return self


class StageAuthoringContextV1(_ProgressiveAuthoringModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    session_revision: int = Field(ge=1)
    stage: JourneyStageV1
    foundation_item_id: str | None = Field(default=None, max_length=160)
    creative_goal: CreativeGoalV2
    requirement_facts: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)
    selected_concept: ConceptOptionRecordV2 | None = None
    style_snapshot_id: str | None = Field(default=None, max_length=160)
    internal_skill_ref: str = Field(min_length=1, max_length=320)
    style_projection: str | None = Field(default=None, max_length=8_192)
    working_document_excerpts: tuple[AgentDocumentContextExcerptV2, ...] = Field(
        default=(),
        max_length=16,
    )
    references: tuple[ProposedDraftReferenceV2, ...] = Field(default=(), max_length=64)


class StageDraftSpecV1(_ProgressiveAuthoringModel):
    draft_key: str = Field(min_length=1, max_length=160)
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(min_length=1, max_length=8_192)
    structured_identity: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=64)
    reference_intents: tuple[DraftReferenceIntentV2, ...] = Field(
        default=(),
        max_length=64,
    )


class StageDraftSelectionV1(_ProgressiveAuthoringModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=256)
    drafts: tuple[StageDraftSpecV1, ...] = Field(min_length=1, max_length=16)


class StageDraftPublicationResultV1(_ProgressiveAuthoringModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    created_node_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    created_binding_ids: tuple[str, ...] = Field(default=(), max_length=128)
    prompt_preparation_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    placement_hints: tuple[AgentPlacementHintV2, ...] = Field(min_length=1, max_length=16)

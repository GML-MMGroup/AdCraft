"""Strict guided-interaction and durable-awaiting contracts for Agent Canvas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.language import BCP47Tag


class _GuidedInteractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidedReferencePreviewV1(_GuidedInteractionModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class GuidedAcceptedReferenceV1(_GuidedInteractionModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    binding_kind: str = Field(min_length=1, max_length=80)
    input_role: str = Field(min_length=1, max_length=80)
    required: bool = False
    display_order: int = Field(ge=0, le=127)
    semantic_reference_role: str | None = Field(default=None, max_length=80)
    display_name: str = Field(min_length=1, max_length=256)
    media_type: Literal["text", "image", "video", "audio"]


class GuidedChoiceOptionV1(_GuidedInteractionModel):
    option_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=240)
    difference_tags: tuple[Annotated[str, Field(min_length=1, max_length=80)], ...] = Field(
        default=(), max_length=6
    )
    recommended: bool = False
    reference_preview: tuple[GuidedReferencePreviewV1, ...] = Field(default=(), max_length=8)


class GuidedQuestionV1(_GuidedInteractionModel):
    question_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=512)
    input_kind: Literal["single_select"] = "single_select"
    options: tuple[GuidedChoiceOptionV1, ...] = Field(min_length=2, max_length=4)
    allow_custom: bool = False
    allow_skip: bool = False
    required: bool = True

    @model_validator(mode="after")
    def validate_skip_policy(self) -> "GuidedQuestionV1":
        if self.required and self.allow_skip:
            raise ValueError("A required guided question cannot be skipped.")
        if len({option.option_id for option in self.options}) != len(self.options):
            raise ValueError("Guided question option IDs must be unique.")
        return self


class GuidedQuestionnaireV1(_GuidedInteractionModel):
    content_kind: Literal["questionnaire"] = "questionnaire"
    questions: tuple[GuidedQuestionV1, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_question_ids(self) -> "GuidedQuestionnaireV1":
        if len({question.question_id for question in self.questions}) != len(self.questions):
            raise ValueError("Guided question IDs must be unique.")
        return self


class GuidedConceptChoiceV2(_GuidedInteractionModel):
    content_kind: Literal["concept_choice"] = "concept_choice"
    proposal_id: str | None = Field(default=None, min_length=1, max_length=160)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    action_id: str = Field(min_length=1, max_length=160)
    occurrence_id: str | None = Field(default=None, max_length=160)
    capability_id: str = Field(min_length=1, max_length=80)
    options: tuple[GuidedChoiceOptionV1, ...] = Field(min_length=3, max_length=3)
    allow_custom: Literal[True] = True
    allow_exclusion: bool

    @model_validator(mode="after")
    def validate_option_ids(self) -> "GuidedConceptChoiceV2":
        if len({option.option_id for option in self.options}) != len(self.options):
            raise ValueError("Guided concept option IDs must be unique.")
        if sum(option.recommended for option in self.options) != 1:
            raise ValueError("A guided concept requires exactly one recommended option.")
        return self


class GuidedMediaReviewV1(_GuidedInteractionModel):
    content_kind: Literal["media_review"] = "media_review"
    node_id: str = Field(min_length=1, max_length=160)
    node_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=512)


GuidedInteractionContentV1: TypeAlias = Annotated[
    GuidedQuestionnaireV1 | GuidedConceptChoiceV2 | GuidedMediaReviewV1,
    Field(discriminator="content_kind"),
]

GuidedInteractionKindV1 = Literal[
    "clarification_questionnaire",
    "concept_choice",
    "media_review",
]
GuidedInteractionStatusV1 = Literal["open", "submitted", "closed", "superseded"]
GuidedInteractionActionV1 = Literal[
    "answer",
    "select",
    "custom",
    "skip",
    "revise",
    "defer",
    "exclude",
    "delegate",
    "accept",
    "retry",
    "replace",
]


class GuidedInteractionV1(_GuidedInteractionModel):
    interaction_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    kind: GuidedInteractionKindV1
    status: GuidedInteractionStatusV1
    response_locale: BCP47Tag
    expected_session_revision: int = Field(ge=1)
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    context: str = Field(min_length=1, max_length=1_024)
    content: GuidedInteractionContentV1
    allowed_actions: tuple[GuidedInteractionActionV1, ...] = Field(min_length=1, max_length=8)
    submit_path: str = Field(min_length=1, max_length=512)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_kind_content(self) -> "GuidedInteractionV1":
        expected_content = {
            "clarification_questionnaire": "questionnaire",
            "concept_choice": "concept_choice",
            "media_review": "media_review",
        }[self.kind]
        if self.content.content_kind != expected_content:
            raise ValueError("Guided interaction kind does not match its content.")
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("Guided interaction actions must be unique.")
        return self


class GuidedQuestionAnswerV1(_GuidedInteractionModel):
    answer_kind: Literal["option"]
    question_id: str = Field(min_length=1, max_length=160)
    option_id: str = Field(min_length=1, max_length=160)


class GuidedCustomAnswerV1(_GuidedInteractionModel):
    answer_kind: Literal["custom"]
    question_id: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2_048)


class GuidedSkipAnswerV1(_GuidedInteractionModel):
    answer_kind: Literal["skip"]
    question_id: str = Field(min_length=1, max_length=160)


GuidedAnswerV1: TypeAlias = Annotated[
    GuidedQuestionAnswerV1 | GuidedCustomAnswerV1 | GuidedSkipAnswerV1,
    Field(discriminator="answer_kind"),
]


class GuidedQuestionnaireSubmitV1(_GuidedInteractionModel):
    submission_kind: Literal["questionnaire"]
    expected_interaction_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    answers: tuple[GuidedAnswerV1, ...] = Field(min_length=1, max_length=4)


class GuidedConceptSubmitV2(_GuidedInteractionModel):
    submission_kind: Literal["concept_choice"]
    expected_interaction_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    action: Literal["select", "custom", "defer", "exclude", "delegate"]
    option_id: str | None = Field(default=None, min_length=1, max_length=160)
    custom_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_048,
        validation_alias=AliasChoices("custom_text", "custom_value"),
    )
    accepted_references: tuple[GuidedAcceptedReferenceV1, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "GuidedConceptSubmitV2":
        if self.action == "select" and self.option_id is None:
            raise ValueError("Selecting a guided concept requires an option ID.")
        if self.action == "custom" and self.custom_text is None:
            raise ValueError("A custom guided concept requires a value.")
        if self.action not in {"select", "custom"} and (
            self.option_id is not None or self.custom_text is not None
        ):
            raise ValueError("This guided concept action does not accept a value.")
        return self


class GuidedMediaReviewSubmitV1(_GuidedInteractionModel):
    submission_kind: Literal["media_review"]
    expected_interaction_revision: int = Field(ge=1)
    expected_session_revision: int = Field(ge=1)
    action: Literal["accept", "retry", "replace", "exclude"]
    instruction: str | None = Field(default=None, min_length=1, max_length=2_048)


GuidedInteractionSubmitRequestV1: TypeAlias = Annotated[
    GuidedQuestionnaireSubmitV1 | GuidedConceptSubmitV2 | GuidedMediaReviewSubmitV1,
    Field(discriminator="submission_kind"),
]


class GuidedInteractionAcceptedV1(_GuidedInteractionModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    interaction_id: str = Field(min_length=1, max_length=160)
    submission_id: str = Field(min_length=1, max_length=160)
    receipt_id: str = Field(min_length=1, max_length=160)
    created_node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    created_binding_ids: tuple[str, ...] = Field(default=(), max_length=128)
    document_revisions: dict[str, int] = Field(default_factory=dict)
    continuation_id: str | None = Field(default=None, max_length=160)
    automatic_run_command_ids: tuple[str, ...] = Field(default=(), max_length=32)
    resulting_session_revision: int = Field(ge=1)
    events_cursor: int = Field(ge=0)
    replayed: bool = False


class GuidanceAwaitingV2(_GuidedInteractionModel):
    awaiting_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    checkpoint_id: str = Field(min_length=1, max_length=160)
    kind: Literal[
        "clarification",
        "concept_selection",
        "media_review",
        "manual_node_run",
        "milestone_idle",
    ]
    requires_user_action: bool
    resume_policy: Literal[
        "submit_interaction",
        "node_terminal",
        "next_user_message",
        "explicit_resume",
    ]
    interaction_id: str | None = Field(default=None, min_length=1, max_length=160)
    node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    stage: JourneyStageV2
    stage_revision: int = Field(ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_resume_evidence(self) -> "GuidanceAwaitingV2":
        interaction_kinds = {"clarification", "concept_selection", "media_review"}
        if self.kind in interaction_kinds:
            if (
                self.interaction_id is None
                or self.resume_policy != "submit_interaction"
                or not self.requires_user_action
                or self.node_ids
            ):
                raise ValueError("Interaction waits require one Submit interaction.")
        elif self.kind == "manual_node_run":
            if (
                not self.node_ids
                or self.interaction_id is not None
                or self.resume_policy != "node_terminal"
                or not self.requires_user_action
            ):
                raise ValueError("Manual Node Run waits require terminal Node evidence.")
        elif (
            self.interaction_id is not None
            or self.node_ids
            or self.requires_user_action
            or self.resume_policy not in {"next_user_message", "explicit_resume"}
        ):
            raise ValueError("Milestone idle cannot claim interaction or Node work.")
        return self


class GuidanceAwaitingResumeProofV2(_GuidedInteractionModel):
    awaiting_id: str = Field(min_length=1, max_length=160)
    expected_session_revision: int = Field(ge=1)
    evidence_kind: Literal[
        "submit_interaction",
        "node_terminal",
        "next_user_message",
        "explicit_resume",
    ]
    interaction_id: str | None = Field(default=None, min_length=1, max_length=160)
    node_ids: tuple[str, ...] = Field(default=(), max_length=32)
    source_turn_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "GuidanceAwaitingResumeProofV2":
        if self.evidence_kind == "submit_interaction":
            if self.interaction_id is None or self.node_ids or self.source_turn_id is not None:
                raise ValueError("Submit evidence requires only an interaction ID.")
        elif self.evidence_kind == "node_terminal":
            if (
                not self.node_ids
                or self.interaction_id is not None
                or self.source_turn_id is not None
            ):
                raise ValueError("Node-terminal evidence requires exact Node IDs.")
        elif self.evidence_kind == "next_user_message":
            if self.source_turn_id is None or self.interaction_id is not None or self.node_ids:
                raise ValueError("New-message evidence requires only a source Turn ID.")
        elif self.interaction_id is not None or self.node_ids or self.source_turn_id is not None:
            raise ValueError("Explicit resume evidence does not accept resource identities.")
        return self


class GuidedInteractionSubmissionRecordV1(_GuidedInteractionModel):
    submission_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    interaction_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=256)
    request: GuidedInteractionSubmitRequestV1
    result: GuidedInteractionAcceptedV1 | None = None
    created_at: datetime

"""Strict contracts for durable Agent Canvas Decision Bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_requirements import (
    RequirementControlNameV1,
    RequirementControlPatchV1,
    RequirementElementKindV1,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreativeDirectiveDecisionEffectV1(_FrozenModel):
    effect_type: Literal["creative_directive"] = "creative_directive"
    directive: str = Field(min_length=1, max_length=2_048)
    scope_kind: Literal["global", "capability"] = "global"
    capability_ids: tuple[CapabilityIdV1, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_scope(self) -> CreativeDirectiveDecisionEffectV1:
        if self.scope_kind == "global" and self.capability_ids:
            raise ValueError("global creative directives cannot target capabilities")
        if self.scope_kind == "capability" and not self.capability_ids:
            raise ValueError("capability creative directives require capability_ids")
        return self


class SetControlDecisionEffectV1(_FrozenModel):
    effect_type: Literal["set_control"] = "set_control"
    control: RequirementControlNameV1
    value: str | int | float

    @model_validator(mode="after")
    def validate_control_value(self) -> SetControlDecisionEffectV1:
        TypeAdapter(RequirementControlPatchV1).validate_python(
            {
                "control": self.control,
                "value": self.value,
                "source_quote": "Decision Bundle option effect.",
            }
        )
        return self


class SetElementPresenceDecisionEffectV1(_FrozenModel):
    effect_type: Literal["set_element_presence"] = "set_element_presence"
    element_kind: RequirementElementKindV1
    presence: Literal["include", "exclude"]


DecisionBundleEffectV1: TypeAlias = Annotated[
    CreativeDirectiveDecisionEffectV1
    | SetControlDecisionEffectV1
    | SetElementPresenceDecisionEffectV1,
    Field(discriminator="effect_type"),
]


class DecisionBundleOptionDraftV1(_FrozenModel):
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_024)
    effects: tuple[DecisionBundleEffectV1, ...] = Field(default=(), max_length=12)


class DecisionBundleQuestionDraftV1(_FrozenModel):
    prompt: str = Field(min_length=1, max_length=1_024)
    selection_mode: Literal["single", "multiple"]
    allow_custom_answer: bool
    allow_skip: bool
    options: tuple[DecisionBundleOptionDraftV1, ...] = Field(min_length=2, max_length=6)


class DecisionBundleDraftV1(_FrozenModel):
    title: str = Field(min_length=1, max_length=160)
    introduction: str = Field(min_length=1, max_length=1_024)
    questions: tuple[DecisionBundleQuestionDraftV1, ...] = Field(min_length=1, max_length=5)


class DecisionBundleOptionV1(DecisionBundleOptionDraftV1):
    option_id: str = Field(min_length=1, max_length=160)


class DecisionBundleQuestionV1(_FrozenModel):
    question_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=1_024)
    selection_mode: Literal["single", "multiple"]
    allow_custom_answer: bool
    allow_skip: bool
    options: tuple[DecisionBundleOptionV1, ...] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def validate_option_identities(self) -> DecisionBundleQuestionV1:
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("Decision Bundle option IDs must be unique")
        return self


class DecisionBundleAnswerV1(_FrozenModel):
    question_id: str = Field(min_length=1, max_length=160)
    selected_option_ids: tuple[str, ...] = Field(default=(), max_length=6)
    custom_answer: str | None = Field(default=None, min_length=1, max_length=2_048)
    skipped: bool = False

    @model_validator(mode="after")
    def validate_answer_form(self) -> DecisionBundleAnswerV1:
        forms = (
            int(bool(self.selected_option_ids))
            + int(self.custom_answer is not None)
            + int(self.skipped)
        )
        if forms != 1:
            raise ValueError("each Decision Bundle answer must use exactly one answer form")
        if len(self.selected_option_ids) != len(set(self.selected_option_ids)):
            raise ValueError("selected Decision Bundle option IDs must be unique")
        return self


class DecisionBundleV1(_FrozenModel):
    bundle_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    source_turn_id: str = Field(min_length=1, max_length=160)
    replacement_bundle_id: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["open", "answered", "skipped", "superseded"]
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    introduction: str = Field(min_length=1, max_length=1_024)
    questions: tuple[DecisionBundleQuestionV1, ...] = Field(min_length=1, max_length=5)
    answers: tuple[DecisionBundleAnswerV1, ...] = Field(default=(), max_length=5)
    requirement_revision_no: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_identities(self) -> DecisionBundleV1:
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Decision Bundle question IDs must be unique")
        answer_ids = [answer.question_id for answer in self.answers]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("Decision Bundle answers must target unique questions")
        if any(question_id not in set(question_ids) for question_id in answer_ids):
            raise ValueError("Decision Bundle answer references an unknown question")
        return self


class SubmitDecisionBundleActionV1(_StrictModel):
    action: Literal["submit"] = "submit"
    expected_revision: int = Field(ge=1)
    # Bundle-specific completeness is validated against the persisted questions so
    # malformed submissions retain the stable domain error contract.
    answers: tuple[DecisionBundleAnswerV1, ...] = Field(default=(), max_length=5)


class SkipDecisionBundleActionV1(_StrictModel):
    action: Literal["skip_bundle"] = "skip_bundle"
    expected_revision: int = Field(ge=1)


DecisionBundleActionRequestV1: TypeAlias = Annotated[
    SubmitDecisionBundleActionV1 | SkipDecisionBundleActionV1,
    Field(discriminator="action"),
]


class DecisionBundleActionAcceptedV1(_FrozenModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    bundle_id: str = Field(min_length=1, max_length=160)
    status: Literal["answered", "skipped"]
    revision: int = Field(ge=2)
    requirement_revision_no: int = Field(ge=1)
    turn_id: str = Field(min_length=1, max_length=160)
    events_cursor: int = Field(ge=0)
    replayed: bool = False

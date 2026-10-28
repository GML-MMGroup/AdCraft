"""Quoted creative-method facts supplied to bounded creation authoring."""

from pydantic import BaseModel, ConfigDict


class CreativeMethodSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_id: str
    title: str
    summary: str


class CreativeMethodContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_id: str
    version: str
    title: str
    core_principle: str
    story_structure: str
    hook_methods: str
    product_role: str
    common_mistakes: str

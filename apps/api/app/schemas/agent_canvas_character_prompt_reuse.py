"""Internal retained creative proofs, never executable preparation evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas_role_prompt_preparation import RoleBindingSnapshotV2


class CharacterPromptReuseProofV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    authority_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    content_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    brief_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class LegacyCharacterPromptProofV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    stage_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipe_digest: str = Field(min_length=1)
    node_inputs_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    content_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    brief_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    parent: RoleBindingSnapshotV2

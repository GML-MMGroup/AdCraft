"""Internal proof that a derived visual prompt may survive source evidence refresh."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DerivativePromptReuseProofV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    authority_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    content_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    brief_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

"""Typed normalized safety decisions for fictional and identifiable identities."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IdentitySafetyDecisionV1(BaseModel):
    """The only normalized identity classification accepted by V2 media admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    classification: Literal["fictional", "identifiable_person_likeness"]
    source: Literal["normalized_agent", "structured_request", "platform_default"]
    normalized_revision: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )

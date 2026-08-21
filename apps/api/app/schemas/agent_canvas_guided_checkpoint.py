"""Strict origin identity for one guided media checkpoint."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GuidedCheckpointOriginV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_id: str = Field(min_length=1, max_length=160)
    guidance_session_id: str = Field(min_length=1, max_length=160)
    stage: Literal["storyboard_grids"] = "storyboard_grids"
    stage_revision: int = Field(ge=1)


def guided_checkpoint_id(
    workflow_id: str,
    guidance_session_id: str,
    *,
    stage_revision: int,
) -> str:
    """Return the stable identity for one exact guided checkpoint."""

    source = f"{workflow_id}:{guidance_session_id}:storyboard_grids:{stage_revision}"
    return "guided-checkpoint:" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]

"""Dependency-light shared contracts for Agent Canvas command authoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentPlacementHintV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "append_flow",
        "after_anchor",
        "right_sibling",
        "near_selection",
    ]
    anchor_node_id: str | None = Field(default=None, max_length=160)
    group_key: str | None = Field(default=None, max_length=160)

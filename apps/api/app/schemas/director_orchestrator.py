from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DirectorIntent = Literal[
    "chat",
    "clarify",
    "create_workflow",
    "update_node_prompt",
    "update_node_prompt_and_run",
    "run_node",
    "update_item_prompt",
    "update_item_prompt_and_run",
    "run_item",
    "update_director_context",
    "suggest_action",
]


class DirectorDecision(BaseModel):
    intent: DirectorIntent
    action: str
    target: dict[str, Any] | None = None
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = False
    reason: str
    warnings: list[str] = Field(default_factory=list)

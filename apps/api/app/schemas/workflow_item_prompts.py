from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkflowItemPromptUpdateRequest(BaseModel):
    prompt: str = Field(max_length=8_000)
    semantic_type: str | None = None
    mark_stale: bool = True

    @field_validator("semantic_type")
    @classmethod
    def strip_semantic_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkflowItemPromptUpdateResponse(BaseModel):
    workflow_id: str
    node_id: str
    node_type: str
    item_id: str
    semantic_type: str | None = None
    prompt: str
    prompt_source: str = "user"
    manual_prompt_dirty: bool = True
    status: str
    stale_item_ids: list[str] = Field(default_factory=list)
    target: dict[str, Any] = Field(default_factory=dict)

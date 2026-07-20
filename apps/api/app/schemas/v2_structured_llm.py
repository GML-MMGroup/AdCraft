from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class V2StructuredLLMCallMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=64)
    stage_name: str = Field(min_length=1, max_length=96)
    attempt_kind: Literal["initial", "repair"]
    reasoning_mode: Literal["disabled", "bounded", "provider_default"]
    thinking_budget: int = Field(ge=0)
    timeout_seconds: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    attempt_count: int = Field(ge=0, le=2)
    transient_retry_used: bool
    elapsed_ms: int = Field(ge=0)
    response_format: Literal["json_schema", "json_object"]
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    finish_reason: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=128)

"""Bounded, content-free statistics for local execution records."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class LocalModelActivityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_ref: str | None
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    active: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    blocked: int = Field(ge=0)
    skipped: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    mean_success_seconds: float | None = Field(default=None, ge=0)
    duration_samples: int = Field(default=0, ge=0)
    error_codes: dict[str, int] = Field(default_factory=dict)


class LocalRuntimeStatisticsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generated_at: datetime
    period_days: int = Field(ge=1, le=90)
    sampled_members: int = Field(ge=0)
    truncated: bool = False
    cost_available: bool = False
    items: tuple[LocalModelActivityV1, ...] = ()

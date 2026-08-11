"""Shared strict error contracts for Agent Canvas public projections."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CanvasNodeErrorV2(BaseModel):
    """One safe, retry-aware Canvas error projection."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool

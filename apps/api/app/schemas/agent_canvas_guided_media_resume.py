"""Private contracts for durable guided media confirmation resume delivery."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2


GuidedMediaResumeStatus = Literal["queued", "running", "completed", "failed"]


def guided_media_resume_delivery_id(submission_id: str, confirmation_id: str) -> str:
    """Return the stable private identity for one accepted confirmation resume."""

    digest = sha256(f"{submission_id}\x1f{confirmation_id}".encode("utf-8")).hexdigest()
    return f"guided_media_resume_{digest[:32]}"


class GuidedMediaConfirmationResumeDeliveryV1(BaseModel):
    """One fenced, replay-safe delivery for post-accept confirmation work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    submission_id: str = Field(min_length=1)
    confirmation_id: str = Field(min_length=1)
    status: GuidedMediaResumeStatus
    attempt_no: int = Field(ge=0)
    max_attempts: Literal[2] = 2
    available_at: datetime
    lease_owner_id: str | None = None
    lease_generation: int = Field(ge=0)
    lease_expires_at: datetime | None = None
    error: CanvasNodeErrorV2 | None = None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None = None

    @model_validator(mode="after")
    def validate_authority_state(self) -> "GuidedMediaConfirmationResumeDeliveryV1":
        expected_id = guided_media_resume_delivery_id(
            self.submission_id,
            self.confirmation_id,
        )
        if self.delivery_id != expected_id:
            raise ValueError("delivery_id does not match the submission confirmation identity")
        if self.status == "queued" and any(
            value is not None
            for value in (
                self.lease_owner_id,
                self.lease_expires_at,
                self.error,
                self.terminal_at,
            )
        ):
            raise ValueError("queued delivery cannot have lease or terminal state")
        if self.status == "running" and (
            self.lease_owner_id is None
            or self.lease_expires_at is None
            or self.error is not None
            or self.terminal_at is not None
        ):
            raise ValueError("running delivery requires only active lease state")
        if self.status == "completed" and (
            self.terminal_at is None
            or self.lease_owner_id is not None
            or self.lease_expires_at is not None
            or self.error is not None
        ):
            raise ValueError("completed delivery requires a clean terminal state")
        if self.status == "failed" and (
            self.terminal_at is None
            or self.error is None
            or self.lease_owner_id is not None
            or self.lease_expires_at is not None
        ):
            raise ValueError("failed delivery requires a safe terminal error")
        return self

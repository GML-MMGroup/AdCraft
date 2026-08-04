from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TianpuyueCallbackLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider: Literal["tianpuyue"] = "tianpuyue"
    base_url: str = Field(min_length=1)
    created_at: datetime
    expires_at: datetime
    renew_after: datetime

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or parsed.hostname != "webhook.site":
            raise ValueError("Automatic Tianpuyue callback lease must use webhook.site HTTPS.")
        return normalized

    @model_validator(mode="after")
    def validate_times(self) -> "TianpuyueCallbackLease":
        self.created_at = _utc(self.created_at)
        self.expires_at = _utc(self.expires_at)
        self.renew_after = _utc(self.renew_after)
        if not self.created_at <= self.renew_after < self.expires_at:
            raise ValueError("Tianpuyue callback lease timestamps are inconsistent.")
        return self


class WebhookSiteTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uuid: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    created_at: datetime
    expires_at: datetime

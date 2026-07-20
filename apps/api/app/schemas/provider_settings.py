from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator


ProviderCredentialConsumer = Literal["llm", "image", "video"]
CredentialSource = Literal["project_dotenv", "process_environment", "unconfigured"]
CredentialTestCapability = Literal["minimal_request", "unsupported"]


def _normalize_secret_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if not isinstance(value, str):
        raise ValueError("Credential values must be strings.")

    normalized = value.strip()
    if not normalized:
        raise ValueError("Credential values must not be empty.")
    if any(character in normalized for character in ("\r", "\n", "\x00")):
        raise ValueError("Credential values contain unsupported control characters.")
    return normalized


class VolcengineCredentialUpdateRequest(BaseModel):
    """A non-empty partial update for the three independent Ark consumers."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "llm_api_key": "placeholder-text-key",
                    "image_api_key": "placeholder-image-key",
                    "video_api_key": "placeholder-video-key",
                }
            ]
        }
    )

    llm_api_key: SecretStr | None = None
    image_api_key: SecretStr | None = None
    video_api_key: SecretStr | None = None

    @field_validator("llm_api_key", "image_api_key", "video_api_key", mode="before")
    @classmethod
    def normalize_supplied_secret(cls, value: object) -> object:
        return _normalize_secret_value(value)

    @model_validator(mode="after")
    def require_at_least_one_secret(self) -> "VolcengineCredentialUpdateRequest":
        if not any((self.llm_api_key, self.image_api_key, self.video_api_key)):
            raise ValueError("At least one credential value must be supplied.")
        return self

    def supplied_values(self) -> dict[ProviderCredentialConsumer, str]:
        values: dict[ProviderCredentialConsumer, str] = {}
        if self.llm_api_key is not None:
            values["llm"] = self.llm_api_key.get_secret_value()
        if self.image_api_key is not None:
            values["image"] = self.image_api_key.get_secret_value()
        if self.video_api_key is not None:
            values["video"] = self.video_api_key.get_secret_value()
        return values


class ProviderCredentialConsumerStatus(BaseModel):
    configured: bool
    masked_api_key: str | None = None
    source: CredentialSource
    test_capability: CredentialTestCapability


class VolcengineCredentialSetStatus(BaseModel):
    llm: ProviderCredentialConsumerStatus
    image: ProviderCredentialConsumerStatus
    video: ProviderCredentialConsumerStatus


class ProviderCredentialStatusResponse(BaseModel):
    provider: Literal["volcengine_ark"] = "volcengine_ark"
    credentials: VolcengineCredentialSetStatus


class ProviderCredentialUpdateResponse(ProviderCredentialStatusResponse):
    updated_consumers: list[ProviderCredentialConsumer]
    applied: Literal[True] = True
    applied_at: datetime


class VolcengineCredentialTestRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"consumer": "llm", "api_key": "placeholder-text-key"},
                {"consumer": "llm"},
            ]
        }
    )

    consumer: ProviderCredentialConsumer
    api_key: SecretStr | None = None

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_candidate_secret(cls, value: object) -> object:
        return _normalize_secret_value(value)


class ProviderCredentialTestResponse(BaseModel):
    provider: Literal["volcengine_ark"] = "volcengine_ark"
    accepted: Literal[True] = True
    tested_consumer: ProviderCredentialConsumer
    model_id: str | None = None
    tested_at: datetime


class ProviderCredentialErrorDetail(BaseModel):
    code: str
    message: str


class ProviderCredentialErrorResponse(BaseModel):
    detail: ProviderCredentialErrorDetail

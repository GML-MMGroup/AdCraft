"""Provider-neutral public contracts for installation model configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


ProviderCapabilityV1 = Literal["text", "image", "video", "audio"]
ProviderConnectionStateV1 = Literal["configured", "unconfigured", "invalid"]
ModelCapabilityV1 = Literal["agent", "text", "image", "video", "audio"]
ModelAvailabilityV1 = Literal[
    "available", "unavailable", "unauthorized", "unsupported", "deprecated"
]
ModelDefaultKeyV1 = Literal["agent", "text", "image", "video", "audio"]


def _normalize_secret(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if not isinstance(value, str):
        raise ValueError("Credential values must be strings.")
    normalized = value.strip()
    if not normalized or any(character in normalized for character in ("\r", "\n", "\x00")):
        raise ValueError("Credential values are invalid.")
    return normalized


class ProviderCredentialCapabilityStatusV1(BaseModel):
    configured: bool
    fingerprint: str | None = None
    source: Literal["project_dotenv", "process_environment", "unconfigured"]
    test_capability: Literal["minimal_request", "unsupported"]


class ProviderConnectionStatusV1(BaseModel):
    provider_id: str
    display_name: str
    capabilities: tuple[ProviderCapabilityV1, ...]
    connection_state: ProviderConnectionStateV1
    credentials: dict[ProviderCapabilityV1, ProviderCredentialCapabilityStatusV1]
    credential_revision: int
    updated_at: datetime | None = None


class ProviderListResponseV1(BaseModel):
    items: tuple[ProviderConnectionStatusV1, ...]


class ProviderCredentialUpdateRequestV1(BaseModel):
    """A partial provider credential mutation with explicit clearing semantics."""

    model_config = ConfigDict(extra="forbid")

    api_keys: dict[ProviderCapabilityV1, SecretStr] = Field(default_factory=dict)
    clear_capabilities: tuple[ProviderCapabilityV1, ...] = ()

    @field_validator("api_keys", mode="before")
    @classmethod
    def normalize_api_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: _normalize_secret(secret) for key, secret in value.items()}

    @model_validator(mode="after")
    def validate_mutation(self) -> "ProviderCredentialUpdateRequestV1":
        keys = set(self.api_keys)
        cleared = set(self.clear_capabilities)
        if not keys and not cleared:
            raise ValueError("At least one credential capability must be supplied.")
        if keys.intersection(cleared):
            raise ValueError("Credential capabilities cannot be set and cleared together.")
        return self

    def secret_values(self) -> dict[ProviderCapabilityV1, str]:
        return {
            capability: credential.get_secret_value()
            for capability, credential in self.api_keys.items()
        }


class ProviderCredentialUpdateResponseV1(BaseModel):
    provider: ProviderConnectionStatusV1
    updated_capabilities: tuple[ProviderCapabilityV1, ...]
    cleared_capabilities: tuple[ProviderCapabilityV1, ...]
    applied_at: datetime


class ProviderCredentialTestRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: ProviderCapabilityV1
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    api_key: SecretStr | None = None

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        return _normalize_secret(value)


class ProviderCredentialTestResponseV1(BaseModel):
    provider_id: str
    capability: ProviderCapabilityV1
    accepted: Literal[True] = True
    model_ref: str | None = None
    tested_at: datetime


class ProviderModelSummaryV1(BaseModel):
    model_ref: str
    provider_id: str
    provider_model_id: str
    display_name: str
    capability: ModelCapabilityV1
    capability_metadata: dict[str, Any] = Field(default_factory=dict)
    availability: ModelAvailabilityV1
    unavailable_reason: str | None = None
    catalog_revision: int


class ProviderModelListResponseV1(BaseModel):
    items: tuple[ProviderModelSummaryV1, ...]


class ModelDefaultsResponseV1(BaseModel):
    defaults: dict[ModelDefaultKeyV1, str]
    revisions: dict[ModelDefaultKeyV1, int]


class ModelDefaultsPatchRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: dict[ModelDefaultKeyV1, str] = Field(min_length=1)


class ProviderModelSyncResponseV1(BaseModel):
    provider_id: str
    sync_run_id: str
    catalog_revision: int | None = None
    status: Literal["succeeded"] = "succeeded"

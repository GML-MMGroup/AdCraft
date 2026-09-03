"""Provider-neutral public contracts for installation model configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


ProviderCapabilityV1 = Literal["text", "image", "video", "audio"]
ProviderConnectionStateV1 = Literal["configured", "unconfigured", "invalid"]
ModelCapabilityV1 = Literal["agent", "text", "image", "video", "audio"]
ModelAvailabilityV1 = Literal[
    "available", "unavailable", "unauthorized", "unsupported", "deprecated"
]
ModelDefaultKeyV1 = Literal["agent", "text", "image", "video", "audio"]
ModelDefaultModeV1 = Literal["automatic", "explicit"]
ProviderTransportKindV1 = Literal[
    "pi_native_openai_compatible",
    "litellm_chat",
    "litellm_openai_image",
    "openai_images_native",
    "ark_image_native",
    "ark_video_native",
    "minimax_video_native",
    "tianpuyue_audio_native",
    "fake",
]
ProviderReleaseTierV1 = Literal["default", "optional", "compatible", "experimental"]
ProviderConformanceStatusV1 = Literal["unverified", "compatible", "certified", "revoked"]
ProviderParameterValueTypeV1 = Literal["integer", "number", "string", "boolean", "enum"]
ReferenceInputModeNameV1 = Literal[
    "text_only",
    "native_reference_slots",
    "text_plus_single_first_frame_image",
    "provider_only_instructions",
]


class LiteLLMGatewayProfileV1(BaseModel):
    """Frozen, secret-free identity for one LiteLLM gateway route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gateway_id: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=320)
    model_alias: str = Field(min_length=1, max_length=160)
    projection_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @field_validator("endpoint")
    @classmethod
    def validate_loopback_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LiteLLM gateway endpoint must be an approved loopback URL.")
        return value.rstrip("/")


class LiteLLMRouteV1(BaseModel):
    """One operation-scoped alias in a generated LiteLLM projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_ref: str = Field(min_length=3, max_length=320)
    provider_model_id: str = Field(min_length=1, max_length=240)
    model_alias: str = Field(min_length=1, max_length=160)
    operation: str = Field(min_length=1, max_length=120)
    contract_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    adapter_revision: str = Field(min_length=1, max_length=80)
    capability_revision: str = Field(min_length=1, max_length=80)


class LiteLLMGatewayProjectionV1(BaseModel):
    """Generated local gateway configuration without credentials or prompts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    gateway_id: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=320)
    routes: tuple[LiteLLMRouteV1, ...] = Field(max_length=256)
    projection_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


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
    model_config = ConfigDict(extra="forbid")

    configured: bool
    fingerprint: str | None = None
    source: Literal["project_dotenv", "process_environment", "unconfigured"]
    test_capability: Literal["minimal_request", "unsupported"]
    endpoint: "ProviderEndpointMetadataV1 | None" = None


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
    base_urls: dict[ProviderCapabilityV1, str] = Field(default_factory=dict)
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
        endpoints = set(self.base_urls)
        cleared = set(self.clear_capabilities)
        if not keys and not endpoints and not cleared:
            raise ValueError("At least one credential capability must be supplied.")
        if keys.intersection(cleared) or endpoints.intersection(cleared):
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


class ProviderEndpointMetadataV1(BaseModel):
    """Non-secret identity for an approved provider endpoint."""

    model_config = ConfigDict(extra="forbid")

    scheme: Literal["https", "http"]
    host: str = Field(min_length=1, max_length=253)
    path: str = Field(default="", max_length=512)
    fingerprint: str = Field(min_length=8, max_length=128)


class ModelParameterDescriptorV1(BaseModel):
    """Declarative model parameter metadata; it contains no executable policy."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    value_type: ProviderParameterValueTypeV1
    required: bool = False
    allowed_values: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    minimum: int | float | None = None
    maximum: int | float | None = None
    default: object | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "ModelParameterDescriptorV1":
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("parameter_descriptor_bounds_invalid")
        if self.value_type != "enum" and self.allowed_values:
            raise ValueError("parameter_descriptor_values_invalid")
        if self.value_type == "enum" and not self.allowed_values:
            raise ValueError("parameter_descriptor_values_required")
        return self


class ModelParameterMatrixV1(BaseModel):
    """A bounded, versioned declaration of representable parameter combinations."""

    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=80)
    descriptors: tuple[ModelParameterDescriptorV1, ...] = Field(max_length=64)
    legal_combinations: tuple[dict[str, object], ...] = Field(default_factory=tuple, max_length=256)

    @model_validator(mode="after")
    def validate_matrix_references(self) -> "ModelParameterMatrixV1":
        descriptor_names = {descriptor.name for descriptor in self.descriptors}
        if len(descriptor_names) != len(self.descriptors):
            raise ValueError("parameter_descriptor_duplicate")
        if any(
            set(combination).difference(descriptor_names) for combination in self.legal_combinations
        ):
            raise ValueError("parameter_combination_unknown")
        return self


class ReferenceInputModeV1(BaseModel):
    """Semantic reference input mode owned by the selected adapter profile."""

    model_config = ConfigDict(extra="forbid")

    mode: ReferenceInputModeNameV1
    max_references: int = Field(ge=0, le=64)
    allowed_roles: tuple[str, ...] = Field(default_factory=tuple, max_length=64)


class ReferenceInputPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modes: tuple[ReferenceInputModeV1, ...] = Field(max_length=16)
    max_images: int = Field(ge=0, le=64)


class ProviderAdapterProfileV1(BaseModel):
    """One trusted adapter claim for one exact model/capability revision."""

    model_config = ConfigDict(extra="forbid")

    model_ref: str = Field(min_length=3, max_length=320)
    adapter_id: str = Field(min_length=1, max_length=120)
    transport_kind: ProviderTransportKindV1
    capability: ModelCapabilityV1
    request_mode: str = Field(min_length=1, max_length=80)
    accepted_input_modes: tuple[str, ...] = Field(min_length=1, max_length=16)
    reference_policy: ReferenceInputPolicyV1
    gateway_profile: LiteLLMGatewayProfileV1 | None = None
    parameter_schema_id: str = Field(min_length=1, max_length=120)
    parameter_matrix: ModelParameterMatrixV1 | None = None
    result_protocol: str = Field(min_length=1, max_length=120)
    supports_remote_task_lookup: bool
    supports_provider_idempotency: bool
    release_tier: ProviderReleaseTierV1 = "optional"
    conformance_status: ProviderConformanceStatusV1 = "unverified"
    adapter_revision: str = Field(min_length=1, max_length=80)
    capability_revision: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_parameter_schema_identity(self) -> "ProviderAdapterProfileV1":
        if (
            self.parameter_matrix is not None
            and self.parameter_matrix.schema_id != self.parameter_schema_id
        ):
            raise ValueError("parameter_schema_mismatch")
        return self


class ProviderModelConformanceSummaryV1(BaseModel):
    """Secret-free conformance evidence for one frozen model operation."""

    model_config = ConfigDict(extra="forbid")

    model_ref: str = Field(min_length=3, max_length=320)
    provider_id: str = Field(min_length=1, max_length=80)
    provider_model_id: str = Field(min_length=1, max_length=240)
    adapter_id: str = Field(min_length=1, max_length=120)
    transport_kind: ProviderTransportKindV1
    operation: str = Field(min_length=1, max_length=120)
    contract_digest: str = Field(min_length=8, max_length=128)
    capability_revision: str = Field(min_length=1, max_length=80)
    adapter_revision: str = Field(min_length=1, max_length=80)
    status: ProviderConformanceStatusV1
    safe_summary: dict[str, object] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class ProviderConformanceTargetV1(BaseModel):
    """Exact provider identity frozen into one conformance diagnostic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_ref: str = Field(min_length=3, max_length=320)
    provider_model_id: str = Field(min_length=1, max_length=240)
    adapter_id: str = Field(min_length=1, max_length=120)
    transport_kind: ProviderTransportKindV1
    capability: ModelCapabilityV1
    operation: str = Field(min_length=1, max_length=120)
    adapter_revision: str = Field(min_length=1, max_length=80)
    capability_revision: str = Field(min_length=1, max_length=80)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_model_identity(self) -> "ProviderConformanceTargetV1":
        _provider_id, separator, provider_model_id = self.model_ref.partition(":")
        if not separator or provider_model_id != self.provider_model_id:
            raise ValueError("provider_conformance_model_identity_mismatch")
        return self


class ProviderModelSummaryV2(ProviderModelSummaryV1):
    """Additive catalog response with trusted adapter/capability metadata."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str | None = None
    transport_kind: ProviderTransportKindV1 | None = None
    release_tier: ProviderReleaseTierV1 | None = None
    conformance_status: ProviderConformanceStatusV1 = "unverified"
    accepted_input_modes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    parameter_schema_id: str | None = None
    parameter_descriptors: tuple[ModelParameterDescriptorV1, ...] = Field(
        default_factory=tuple,
        max_length=64,
    )
    reference_policy: ReferenceInputPolicyV1 | None = None


ProviderCredentialCapabilityStatusV1.model_rebuild()


class ProviderModelListResponseV1(BaseModel):
    items: tuple[ProviderModelSummaryV1, ...]


class ProviderModelListResponseV2(BaseModel):
    """Additive model catalog response with trusted adapter metadata."""

    items: tuple[ProviderModelSummaryV2, ...]


class ModelDefaultsResponseV1(BaseModel):
    defaults: dict[ModelDefaultKeyV1, str]
    modes: dict[ModelDefaultKeyV1, ModelDefaultModeV1]
    revisions: dict[ModelDefaultKeyV1, int]


class ModelDefaultsPatchRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: dict[ModelDefaultKeyV1, str] = Field(default_factory=dict)
    modes: dict[ModelDefaultKeyV1, ModelDefaultModeV1] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mutation(self) -> "ModelDefaultsPatchRequestV1":
        if not self.defaults and not self.modes:
            raise ValueError("At least one model default or mode must be supplied.")
        return self


class ProviderModelSyncResponseV1(BaseModel):
    provider_id: str
    sync_run_id: str
    catalog_revision: int | None = None
    status: Literal["succeeded"] = "succeeded"

"""Bounded, secret-free import contracts for configured Agent operation evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ConfiguredAgentEvidenceIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_ref: str = Field(min_length=3, max_length=320)
    expected_catalog_revision: int = Field(ge=1)
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]{0,119}$")
    adapter_id: Literal["pi-openai-compatible-v1"] = "pi-openai-compatible-v1"
    adapter_revision: Literal["pi-openai-compatible-v1"] = "pi-openai-compatible-v1"
    transport_kind: Literal["pi_native_openai_compatible"] = "pi_native_openai_compatible"
    capability_revision: str = Field(min_length=1, max_length=80)
    contract_digest: str = Field(min_length=8, max_length=128)
    operation_policy_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class ConfiguredAgentEvidenceChecksV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_output: StrictBool
    tool_calls: StrictBool
    reasoning_controls: StrictBool
    streaming: StrictBool
    timeout_policy: StrictBool
    transport: StrictBool


class ConfiguredAgentEvidenceRequestV1(ConfiguredAgentEvidenceIdentityV1):
    status: Literal["compatible", "revoked"]
    evidence_kind: Literal["real_provider", "deterministic"]
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
    duration_ms: int = Field(ge=0, le=86_400_000)
    checks: ConfiguredAgentEvidenceChecksV1

    @model_validator(mode="after")
    def compatible_requires_all_checks(self) -> "ConfiguredAgentEvidenceRequestV1":
        if self.status == "compatible" and not all(self.checks.model_dump().values()):
            raise ValueError("Compatible operation evidence requires all checks to pass.")
        return self


class ConfiguredAgentEvidenceTargetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    identity: ConfiguredAgentEvidenceIdentityV1
    status: Literal["unverified", "compatible", "certified", "revoked"]
    latest_run_id: str | None = None


class ConfiguredAgentEvidenceTargetsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[ConfiguredAgentEvidenceTargetV1, ...]


class ConfiguredAgentEvidenceReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conformance_run_id: str
    model_ref: str
    operation: str
    status: Literal["compatible", "revoked"]

"""Credential-free Agent capability contract models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_runtime import AgentName


AgentModelRole = Literal["agent"]


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentCapabilityV1(_CapabilityModel):
    name: AgentName
    operations: tuple[str, ...] = Field(min_length=1, max_length=64)
    model_role: AgentModelRole

    @field_validator("operations")
    @classmethod
    def validate_operations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(operation.strip() for operation in value)
        if any(not operation for operation in normalized):
            raise ValueError("Agent operations must not be blank.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Agent operations must be unique.")
        return normalized


class AgentCapabilityContractV1(_CapabilityModel):
    contract_version: Literal["1"] = "1"
    agents: tuple[AgentCapabilityV1, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_unique_agents(self) -> "AgentCapabilityContractV1":
        names = tuple(agent.name for agent in self.agents)
        if len(names) != len(set(names)):
            raise ValueError("Agent capability names must be unique.")
        return self


class VideoAgentOperationDefinitionV1(_CapabilityModel):
    operation: str = Field(min_length=1, max_length=120)
    capability_id: CapabilityIdV1 | None = None
    internal_skill_id: str | None = Field(default=None, min_length=1, max_length=160)
    style_projection_role: str | None = Field(default=None, min_length=1, max_length=160)
    context_contract_name: str = Field(min_length=1, max_length=160)
    result_contract_name: str = Field(min_length=1, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    max_skill_context_bytes: int = Field(default=8_192, ge=1, le=32_768)
    max_handoffs: Literal[0] = 0

    @property
    def internal_skill_id_count(self) -> int:
        return int(self.internal_skill_id is not None)

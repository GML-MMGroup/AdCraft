"""Credential-free Agent capability contract models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.agent_runtime import AgentName


AgentModelRole = Literal[
    "front_desk",
    "script",
    "product_design",
    "character",
    "scene",
    "storyboard",
    "final_video",
    "bgm",
]


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentCapabilityV1(_CapabilityModel):
    name: AgentName
    operations: tuple[str, ...] = Field(min_length=1, max_length=16)
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

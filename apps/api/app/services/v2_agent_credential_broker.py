"""In-memory credential delivery for the private Pi Agent runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings
from app.schemas.agent_capabilities import AgentCapabilityV1
from app.schemas.agent_runtime import AgentName
from app.services.v2_agent_capability_contract import (
    V2AgentCapabilityContractService,
)


class AgentCapabilityLookup(Protocol):
    def get(self, agent_name: str) -> AgentCapabilityV1 | None: ...


class AgentCredentialError(RuntimeError):
    """Stable credential lookup failure that never embeds a credential value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentCredentialSnapshot:
    protocol_version: str
    provider: str
    model_id: str
    model_policy_id: str
    base_url: str
    supports_tool_calls: bool
    supports_strict_structured_output: bool
    supports_streaming: bool
    supports_streamed_tool_calls: bool
    supports_reasoning_controls: bool
    api_key: str = field(repr=False)


class V2AgentCredentialBroker:
    """Resolve one allowlisted runtime credential reference from current settings."""

    def __init__(
        self,
        settings: Settings,
        *,
        capabilities: AgentCapabilityLookup | None = None,
    ) -> None:
        self._settings = settings
        self._capabilities = capabilities or V2AgentCapabilityContractService()

    def snapshot(
        self,
        credential_ref: str,
        *,
        agent_name: AgentName,
        operation: str,
        model_policy_id: str,
    ) -> AgentCredentialSnapshot:
        if credential_ref != "llm-default":
            raise AgentCredentialError(
                "agent_credential_ref_unknown",
                "Agent runtime credential reference is not registered.",
            )
        capability = self._capabilities.get(agent_name)
        if capability is None:
            raise AgentCredentialError(
                "agent_name_not_registered",
                "Agent runtime name is not registered.",
            )
        if operation not in capability.operations:
            raise AgentCredentialError(
                "agent_operation_not_allowed",
                "Agent runtime operation is not registered for this Agent.",
            )
        expected_policy_id = f"{agent_name}.{operation}.v1"
        if model_policy_id != expected_policy_id:
            raise AgentCredentialError(
                "agent_model_policy_mismatch",
                "Agent runtime model policy does not match the requested operation.",
            )
        model_id = _model_for_role(self._settings, capability.model_role)
        if not model_id or not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise AgentCredentialError(
                "agent_model_unavailable",
                "The configured text model is unavailable.",
            )
        return AgentCredentialSnapshot(
            protocol_version=self._settings.agent_runtime_protocol_version,
            provider=self._settings.llm_provider,
            model_id=model_id,
            model_policy_id=model_policy_id,
            base_url=self._settings.llm_base_url,
            supports_tool_calls=True,
            supports_strict_structured_output=True,
            supports_streaming=True,
            supports_streamed_tool_calls=False,
            supports_reasoning_controls=False,
            api_key=self._settings.llm_api_key,
        )


def _model_for_role(settings: Settings, model_role: str) -> str:
    field_name = {
        "front_desk": "llm_front_desk_model",
        "script": "llm_script_model",
        "product_design": "llm_product_design_model",
        "character": "llm_character_model",
        "scene": "llm_scene_model",
        "storyboard": "llm_storyboard_model",
        "final_video": "llm_final_video_model",
        "bgm": "llm_bgm_model",
        "quick_media": "llm_final_video_model",
    }.get(model_role)
    if field_name is None:
        raise AgentCredentialError(
            "agent_model_role_not_registered",
            "Agent runtime model role is not registered.",
        )
    return str(getattr(settings, field_name, ""))

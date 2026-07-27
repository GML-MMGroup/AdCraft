"""In-memory credential delivery for the private Pi Agent runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings


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
    base_url: str
    api_key: str = field(repr=False)


class V2AgentCredentialBroker:
    """Resolve one allowlisted runtime credential reference from current settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def snapshot(self, credential_ref: str) -> AgentCredentialSnapshot:
        if credential_ref != "llm-default":
            raise AgentCredentialError(
                "agent_credential_ref_unknown",
                "Agent runtime credential reference is not registered.",
            )
        if not self._settings.llm_api_key or not self._settings.llm_base_url:
            raise AgentCredentialError(
                "agent_model_unavailable",
                "The configured text model is unavailable.",
            )
        return AgentCredentialSnapshot(
            protocol_version=self._settings.agent_runtime_protocol_version,
            provider=self._settings.llm_provider,
            model_id=self._settings.llm_front_desk_model,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
        )

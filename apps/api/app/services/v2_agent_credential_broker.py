"""Secret-safe credential delivery for frozen private Pi Agent model selections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings
from app.persistence.database import V2Database, create_v2_database
from app.persistence.provider_model_repository import ProviderModelRecord, ProviderModelRepository
from app.schemas.agent_capabilities import AgentCapabilityV1
from app.schemas.agent_operation_recovery import AgentOperationPolicyV2
from app.schemas.agent_runtime import AgentModelExecutionPolicyV1, AgentName
from app.services.agent_model_execution_policy import (
    AgentModelExecutionPolicyError,
    resolve_agent_model_execution_policy,
)
from app.services.provider_credentials import CredentialSettingsError, ProviderCredentialRegistry
from app.services.v2_agent_capability_contract import V2AgentCapabilityContractService


class AgentCapabilityLookup(Protocol):
    def get(self, agent_name: str) -> AgentCapabilityV1 | None: ...


class AgentModelLookup(Protocol):
    def get_model(self, model_ref: str) -> ProviderModelRecord: ...


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
    model_ref: str
    model_id: str
    model_policy_id: str
    base_url: str
    supports_tool_calls: bool
    supports_strict_structured_output: bool
    supports_streaming: bool
    supports_streamed_tool_calls: bool
    supports_reasoning_controls: bool
    execution_policy: AgentModelExecutionPolicyV1
    api_key: str = field(repr=False)


class V2AgentCredentialBroker:
    """Authorize and resolve credentials only for Python-frozen catalog model references."""

    def __init__(
        self,
        settings: Settings,
        *,
        capabilities: AgentCapabilityLookup | None = None,
        model_repository: AgentModelLookup | None = None,
        credential_registry: ProviderCredentialRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._capabilities = capabilities or V2AgentCapabilityContractService()
        self._model_repository = model_repository
        self._credential_registry = credential_registry or ProviderCredentialRegistry()

    def snapshot(
        self,
        credential_ref: str,
        *,
        agent_name: AgentName,
        operation: str,
        model_policy_id: str,
        model_ref: str | None,
        operation_policy: AgentOperationPolicyV2,
    ) -> AgentCredentialSnapshot:
        self._authorize(
            credential_ref,
            agent_name=agent_name,
            operation=operation,
            model_policy_id=model_policy_id,
            operation_policy=operation_policy,
        )
        if model_ref is None:
            raise AgentCredentialError(
                "agent_model_policy_mismatch",
                "Agent runtime did not supply a frozen model reference.",
            )
        record = self._record(model_ref)
        self._validate_model(record, operation=operation)
        try:
            provider_definition = self._credential_registry.get(record.provider_id)
            binding = provider_definition.binding_for_capability("text")
        except CredentialSettingsError as error:
            raise AgentCredentialError(
                "provider_credentials_missing",
                "The selected provider text credential is not configured.",
            ) from error
        api_key = str(getattr(self._settings, binding.settings_field, "") or "")
        base_url = str(getattr(self._settings, binding.endpoint_field, "") or "")
        if not api_key or not base_url:
            raise AgentCredentialError(
                "provider_credentials_missing",
                "The selected provider text credential is not configured.",
            )
        metadata = record.capability_metadata
        try:
            execution_policy = resolve_agent_model_execution_policy(
                model_ref=record.model_ref,
                operation_policy=operation_policy,
                capability_metadata=metadata,
            )
        except AgentModelExecutionPolicyError as error:
            raise AgentCredentialError(error.code, str(error)) from error
        return AgentCredentialSnapshot(
            protocol_version=self._settings.agent_runtime_protocol_version,
            provider=provider_definition.display_name,
            model_ref=record.model_ref,
            model_id=record.provider_model_id,
            model_policy_id=model_policy_id,
            base_url=base_url,
            supports_tool_calls=_metadata_flag(metadata, "supports_tool_calls"),
            supports_strict_structured_output=_metadata_flag(
                metadata, "supports_structured_output"
            ),
            supports_streaming=_metadata_flag(metadata, "supports_streaming"),
            supports_streamed_tool_calls=_metadata_flag(metadata, "supports_streamed_tool_calls"),
            supports_reasoning_controls=_metadata_flag(metadata, "supports_reasoning_controls"),
            execution_policy=execution_policy,
            api_key=api_key,
        )

    def _authorize(
        self,
        credential_ref: str,
        *,
        agent_name: AgentName,
        operation: str,
        model_policy_id: str,
        operation_policy: AgentOperationPolicyV2,
    ) -> None:
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
        if operation_policy.agent_name != agent_name or operation_policy.operation != operation:
            raise AgentCredentialError(
                "agent_model_policy_mismatch",
                "Agent runtime operation policy does not match the requested run.",
            )
        expected_policy_id = operation_policy.policy_id
        if model_policy_id != expected_policy_id:
            raise AgentCredentialError(
                "agent_model_policy_mismatch",
                "Agent runtime model policy does not match the requested operation.",
            )

    def _record(self, model_ref: str) -> ProviderModelRecord:
        repository = self._model_repository
        database: V2Database | None = None
        if repository is None:
            database = create_v2_database(self._settings.media_data_dir)
            repository = ProviderModelRepository(database)
        try:
            record = repository.get_model(model_ref)
        except ValueError as error:
            raise AgentCredentialError(
                "agent_model_unavailable",
                "The frozen text model is unavailable.",
            ) from error
        finally:
            if database is not None:
                database.dispose()
        return record

    @staticmethod
    def _validate_model(record: ProviderModelRecord, *, operation: str) -> None:
        if record.provider_id != "siliconflow" or record.model_ref != "siliconflow:zai-org/GLM-5.2":
            raise AgentCredentialError(
                "agent_model_incompatible",
                "Agent language operations require the configured SiliconFlow GLM-5.2 model.",
            )
        if record.availability != "available":
            raise AgentCredentialError(
                "agent_model_unavailable",
                "The frozen text model is unavailable.",
            )
        if record.capability != "text":
            raise AgentCredentialError(
                "agent_model_incompatible",
                "Agent operations require a text-capable model.",
            )
        metadata = record.capability_metadata
        if (
            not _metadata_flag(metadata, "agent_compatible")
            or not _metadata_flag(metadata, "supports_tool_calls")
            or not _metadata_flag(metadata, "supports_structured_output")
        ):
            raise AgentCredentialError(
                "agent_model_incompatible",
                "The frozen text model is incompatible with the Agent operation.",
            )


def _metadata_flag(metadata: dict[str, object], key: str) -> bool:
    return bool(metadata.get(key))

"""Secret-safe credential delivery for frozen private Pi Agent model selections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.core.config import Settings
from app.persistence.database import V2Database, create_v2_database
from app.persistence.provider_model_repository import ProviderModelRecord, ProviderModelRepository
from app.schemas.agent_capabilities import AgentCapabilityV1
from app.schemas.agent_operation_recovery import AgentOperationPolicyV2
from app.schemas.agent_runtime import AgentModelExecutionPolicyV1, AgentName
from app.schemas.provider_models import OpenRouterRoutingPolicyV1, ProviderAdapterProfileV1
from app.services.agent_model_execution_policy import (
    AgentModelExecutionPolicyError,
    resolve_agent_model_execution_policy,
)
from app.services.provider_credentials import CredentialSettingsError, ProviderCredentialRegistry
from app.services.provider_model_catalog import ProviderModelCatalogService
from app.services.openrouter_policy import build_openrouter_routing_policy
from app.services.v2_agent_capability_contract import V2AgentCapabilityContractService


class AgentCapabilityLookup(Protocol):
    def get(self, agent_name: str) -> AgentCapabilityV1 | None: ...


class AgentModelLookup(Protocol):
    def get_model(self, model_ref: str) -> ProviderModelRecord: ...


GatewayHealthProbe = Callable[[ProviderAdapterProfileV1, str], Mapping[str, object]]


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
    adapter_id: str
    transport_kind: str
    capability_revision: str
    adapter_revision: str
    execution_policy: AgentModelExecutionPolicyV1
    api_key: str = field(repr=False)
    gateway_id: str | None = None
    model_alias: str | None = None
    projection_digest: str | None = None
    openrouter_routing: OpenRouterRoutingPolicyV1 | None = None


class V2AgentCredentialBroker:
    """Authorize and resolve credentials only for Python-frozen catalog model references."""

    def __init__(
        self,
        settings: Settings,
        *,
        capabilities: AgentCapabilityLookup | None = None,
        model_repository: AgentModelLookup | None = None,
        credential_registry: ProviderCredentialRegistry | None = None,
        gateway_health_probe: GatewayHealthProbe | None = None,
    ) -> None:
        self._settings = settings
        self._capabilities = capabilities or V2AgentCapabilityContractService()
        self._model_repository = model_repository
        self._credential_registry = credential_registry or ProviderCredentialRegistry()
        self._gateway_health_probe = gateway_health_probe or self._probe_litellm_gateway

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
        self._validate_model(record)
        metadata = record.capability_metadata
        adapter_profile = _agent_adapter_profile(record)
        openrouter_routing = _openrouter_routing_policy(record, adapter_profile)
        if adapter_profile.transport_kind == "litellm_chat":
            self._validate_litellm_gateway(adapter_profile, operation=operation)
        try:
            provider_definition = self._credential_registry.get(record.provider_id)
            binding = provider_definition.binding_for_capability("text")
        except CredentialSettingsError as error:
            raise AgentCredentialError(
                "provider_credentials_missing",
                "The selected provider text credential is not configured.",
            ) from error
        api_key = str(getattr(self._settings, binding.settings_field, "") or "")
        provider_base_url = str(getattr(self._settings, binding.endpoint_field, "") or "")
        if not api_key or not provider_base_url:
            raise AgentCredentialError(
                "provider_credentials_missing",
                "The selected provider text credential is not configured.",
            )
        base_url = (
            adapter_profile.gateway_profile.endpoint
            if adapter_profile.transport_kind == "litellm_chat"
            and adapter_profile.gateway_profile is not None
            else provider_base_url
        )
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
            adapter_id=adapter_profile.adapter_id,
            transport_kind=adapter_profile.transport_kind,
            capability_revision=adapter_profile.capability_revision,
            adapter_revision=adapter_profile.adapter_revision,
            execution_policy=execution_policy,
            api_key=api_key,
            gateway_id=(
                adapter_profile.gateway_profile.gateway_id
                if adapter_profile.gateway_profile is not None
                else None
            ),
            model_alias=(
                adapter_profile.gateway_profile.model_alias
                if adapter_profile.gateway_profile is not None
                else None
            ),
            projection_digest=(
                adapter_profile.gateway_profile.projection_digest
                if adapter_profile.gateway_profile is not None
                else None
            ),
            openrouter_routing=openrouter_routing,
        )

    def _validate_litellm_gateway(
        self,
        profile: ProviderAdapterProfileV1,
        *,
        operation: str,
    ) -> None:
        try:
            health = self._gateway_health_probe(profile, operation)
        except AgentCredentialError:
            raise
        except Exception as error:
            raise AgentCredentialError(
                "provider_gateway_unavailable",
                "The configured LiteLLM gateway is unavailable.",
            ) from error
        if health.get("status") != "ready":
            raise AgentCredentialError(
                "provider_gateway_unavailable",
                "The configured LiteLLM gateway is unavailable.",
            )
        gateway_profile = profile.gateway_profile
        if gateway_profile is None:
            raise AgentCredentialError(
                "agent_model_incompatible",
                "The selected LiteLLM route has no gateway profile.",
            )
        if (
            health.get("gateway_id") not in {None, gateway_profile.gateway_id}
            or health.get("projection_digest") != gateway_profile.projection_digest
        ):
            raise AgentCredentialError(
                "provider_gateway_config_stale",
                "The LiteLLM gateway projection is stale.",
            )
        aliases = health.get("aliases")
        if (
            not isinstance(aliases, Mapping)
            or aliases.get(gateway_profile.model_alias) != profile.model_ref
        ):
            raise AgentCredentialError(
                "provider_gateway_config_stale",
                "The LiteLLM gateway model alias is stale.",
            )
        operations = health.get("operations")
        if operations is not None and (
            not isinstance(operations, (list, tuple, set)) or operation not in operations
        ):
            raise AgentCredentialError(
                "provider_gateway_config_stale",
                "The LiteLLM gateway operation contract is stale.",
            )

    def _probe_litellm_gateway(
        self,
        profile: ProviderAdapterProfileV1,
        _operation: str,
    ) -> Mapping[str, object]:
        gateway_profile = profile.gateway_profile
        if gateway_profile is None:
            raise AgentCredentialError(
                "agent_model_incompatible",
                "The selected LiteLLM route has no gateway profile.",
            )
        request = Request(
            f"{gateway_profile.endpoint.rstrip('/')}/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(
                request,
                timeout=self._settings.agent_runtime_connect_timeout_seconds,
            ) as response:
                raw = response.read(65_536)
        except (OSError, URLError) as error:
            raise AgentCredentialError(
                "provider_gateway_unavailable",
                "The configured LiteLLM gateway is unavailable.",
            ) from error
        try:
            health = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise AgentCredentialError(
                "provider_gateway_unavailable",
                "The configured LiteLLM gateway returned an invalid health response.",
            ) from error
        if not isinstance(health, Mapping):
            raise AgentCredentialError(
                "provider_gateway_unavailable",
                "The configured LiteLLM gateway returned an invalid health response.",
            )
        return health

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
            repository = ProviderModelCatalogService(ProviderModelRepository(database))
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
    def _validate_model(record: ProviderModelRecord) -> None:
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
        raw_profile = metadata.get("adapter_profile")
        if raw_profile is not None:
            try:
                profile = ProviderAdapterProfileV1.model_validate(raw_profile)
            except ValidationError as error:
                raise AgentCredentialError(
                    "agent_model_incompatible",
                    "The selected Agent transport profile is invalid.",
                ) from error
            if profile.conformance_status == "revoked":
                raise AgentCredentialError(
                    "model_conformance_revoked",
                    "The selected Agent model conformance is revoked.",
                )
            if profile.conformance_status == "unverified":
                raise AgentCredentialError(
                    "model_conformance_required",
                    "The selected Agent model requires conformance evidence.",
                )
        structured_transport = metadata.get("structured_transport")
        if (
            not _metadata_flag(metadata, "agent_compatible")
            or not _metadata_flag(metadata, "supports_structured_output")
            or (
                structured_transport in {"streamed_tool_call", "non_streaming_tool_call"}
                and not _metadata_flag(metadata, "supports_tool_calls")
            )
            or (
                structured_transport == "streaming_json_object"
                and not _metadata_flag(metadata, "supports_streaming")
            )
        ):
            raise AgentCredentialError(
                "agent_model_incompatible",
                "The frozen text model is incompatible with the Agent operation.",
            )


def _metadata_flag(metadata: dict[str, object], key: str) -> bool:
    return bool(metadata.get(key))


def _agent_adapter_profile(record: ProviderModelRecord) -> ProviderAdapterProfileV1:
    raw_profile = record.capability_metadata.get("adapter_profile")
    if raw_profile is None:
        return ProviderAdapterProfileV1(
            model_ref=record.model_ref,
            adapter_id="pi-openai-compatible-v1",
            transport_kind="pi_native_openai_compatible",
            capability="text",
            request_mode="agent_structured",
            accepted_input_modes=("text_only",),
            reference_policy={
                "modes": [{"mode": "text_only", "max_references": 0}],
                "max_images": 0,
            },
            parameter_schema_id="agent-text-v1",
            result_protocol="structured_agent_result",
            supports_remote_task_lookup=False,
            supports_provider_idempotency=False,
            release_tier="default",
            conformance_status="compatible",
            adapter_revision="pi-openai-compatible-v1",
            capability_revision=f"catalog-{record.catalog_revision}",
        )
    try:
        profile = ProviderAdapterProfileV1.model_validate(raw_profile)
    except ValidationError as error:
        raise AgentCredentialError(
            "agent_model_incompatible",
            "The selected Agent transport profile is invalid.",
        ) from error
    if profile.model_ref != record.model_ref or profile.capability != "text":
        raise AgentCredentialError(
            "agent_model_incompatible",
            "The selected Agent transport profile does not match the frozen model.",
        )
    if profile.transport_kind.startswith("litellm_") and (
        profile.conformance_status != "certified" or profile.gateway_profile is None
    ):
        raise AgentCredentialError(
            "agent_model_incompatible",
            "The selected LiteLLM route is not certified for Agent execution.",
        )
    if profile.transport_kind not in {"pi_native_openai_compatible", "litellm_chat"}:
        raise AgentCredentialError(
            "agent_model_incompatible",
            "The selected transport cannot execute Agent text operations.",
        )
    return profile


def _openrouter_routing_policy(
    record: ProviderModelRecord,
    profile: ProviderAdapterProfileV1,
) -> OpenRouterRoutingPolicyV1 | None:
    raw = record.capability_metadata.get("openrouter_routing")
    if record.provider_id != "openrouter":
        if raw is not None:
            raise AgentCredentialError(
                "openrouter_routing_contract_invalid",
                "A non-OpenRouter Agent model cannot carry OpenRouter routing policy.",
            )
        return None
    try:
        routing = OpenRouterRoutingPolicyV1.model_validate(raw)
    except ValidationError as error:
        raise AgentCredentialError(
            "openrouter_routing_contract_invalid",
            "The selected OpenRouter Agent model has no valid frozen routing policy.",
        ) from error
    expected = build_openrouter_routing_policy(
        model_ref=record.model_ref,
        adapter_revision=profile.adapter_revision,
        capability_revision=profile.capability_revision,
        operation_contract="openrouter-agent-text-v1",
    )
    if routing != expected:
        raise AgentCredentialError(
            "openrouter_routing_contract_invalid",
            "The selected OpenRouter Agent routing policy is stale.",
        )
    return routing

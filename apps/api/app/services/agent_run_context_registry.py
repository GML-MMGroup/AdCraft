"""Closed input-context authority for production Video Agent operations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel

from app.schemas.agent_canvas_capabilities import (
    CapabilityInvocationContextV2,
    NextActionContextV1,
    TurnIntentContextV2,
)
from app.schemas.agent_canvas_materialization import CapabilityMaterializationContextV1
from app.schemas.agent_canvas_storyboard_sequences import StoryboardSegmentAuthoringContextV2
from app.schemas.agent_capabilities import VideoAgentOperationDefinitionV1
from app.schemas.agent_operation_contexts import (
    AgentCommandReplanContextV2,
    AssetRevisionAgentContext,
    BgmExpertAgentContext,
    CharacterExpertAgentContext,
    ConversationSummaryAgentContext,
    DirectorTurnContextV2,
    FrontDeskIntentAgentContext,
    IntentContractAgentContext,
    ProductExpertAgentContext,
    QuickMediaAgentContext,
    SceneExpertAgentContext,
    ScriptWriterAgentContext,
    VideoParameterIntentContextV2,
    WorkflowConversationAgentContext,
)
from app.schemas.agent_runtime import AgentRunContext, AgentRunRequest


@dataclass(frozen=True, slots=True)
class AgentRunContextDefinition:
    """One immutable context name and its exact Pydantic model class."""

    contract_name: str
    model: type[BaseModel]


class AgentRunContextRegistryError(ValueError):
    """Stable fail-closed error raised before durable Agent dispatch."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


_EXPLICIT_CONTEXT_MODELS: tuple[type[BaseModel], ...] = (
    AgentRunContext,
    FrontDeskIntentAgentContext,
    IntentContractAgentContext,
    ScriptWriterAgentContext,
    ProductExpertAgentContext,
    CharacterExpertAgentContext,
    SceneExpertAgentContext,
    BgmExpertAgentContext,
    AssetRevisionAgentContext,
    QuickMediaAgentContext,
    WorkflowConversationAgentContext,
    ConversationSummaryAgentContext,
    DirectorTurnContextV2,
    AgentCommandReplanContextV2,
    VideoParameterIntentContextV2,
    TurnIntentContextV2,
    NextActionContextV1,
    CapabilityInvocationContextV2,
    CapabilityMaterializationContextV1,
    StoryboardSegmentAuthoringContextV2,
)


class AgentRunContextRegistry:
    """Resolve exact context classes without imports or aliases from runtime input."""

    def __init__(
        self,
        models: Iterable[type[BaseModel]] = _EXPLICIT_CONTEXT_MODELS,
    ) -> None:
        definitions = tuple(AgentRunContextDefinition(model.__name__, model) for model in models)
        by_name = {definition.contract_name: definition for definition in definitions}
        if len(by_name) != len(definitions):
            raise AgentRunContextRegistryError(
                "agent_context_registry_invalid",
                "Agent context contract names must be unique.",
            )
        self._definitions = definitions
        self._by_name = MappingProxyType(by_name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    def definitions(self) -> tuple[AgentRunContextDefinition, ...]:
        return self._definitions

    def resolve(self, contract_name: str) -> type[BaseModel]:
        try:
            return self._by_name[contract_name].model
        except KeyError as error:
            raise AgentRunContextRegistryError(
                "agent_context_registry_invalid",
                "Agent context contract is not registered.",
                details={"context_contract_name": contract_name[:160]},
            ) from error

    def validate_operation_context(
        self,
        definition: VideoAgentOperationDefinitionV1,
        context: BaseModel,
    ) -> None:
        expected_model = self.resolve(definition.context_contract_name)
        if type(context) is not expected_model:
            raise AgentRunContextRegistryError(
                "agent_context_registry_invalid",
                "Video Agent operation and context model do not match.",
                details={
                    "operation": definition.operation[:160],
                    "declared_context_contract_name": definition.context_contract_name[:160],
                    "actual_context_contract_name": type(context).__name__[:160],
                },
            )


AGENT_RUN_CONTEXT_REGISTRY = AgentRunContextRegistry()


def validate_video_agent_operation_context(operation: str, context: BaseModel) -> None:
    """Validate one operation/context pair before request persistence or dispatch."""

    from app.services.video_agent_operation_registry import VideoAgentOperationRegistry

    definition = VideoAgentOperationRegistry().resolve(operation)
    AGENT_RUN_CONTEXT_REGISTRY.validate_operation_context(definition, context)


def validate_video_agent_context_parity(
    definitions: Iterable[VideoAgentOperationDefinitionV1],
    registry: AgentRunContextRegistry = AGENT_RUN_CONTEXT_REGISTRY,
) -> None:
    """Validate operation metadata against context authority and request Schema."""

    from app.services.v2_agent_contract_registry import (
        validate_video_agent_contract_parity,
    )

    definitions = tuple(definitions)
    validate_video_agent_contract_parity(definitions)
    request_definitions = AgentRunRequest.model_json_schema().get("$defs", {})
    errors: list[dict[str, str]] = []
    for definition in definitions:
        try:
            model = registry.resolve(definition.context_contract_name)
        except AgentRunContextRegistryError:
            errors.append(
                {
                    "operation": definition.operation[:160],
                    "context_contract_name": definition.context_contract_name[:160],
                    "reason": "context_not_registered",
                }
            )
    for context_definition in registry.definitions():
        if context_definition.contract_name not in request_definitions:
            errors.append(
                {
                    "operation": "<request-union>",
                    "context_contract_name": context_definition.contract_name[:160],
                    "reason": "registered_context_missing_from_agent_run_request",
                }
            )
            continue
        if model.__name__ not in request_definitions:
            errors.append(
                {
                    "operation": definition.operation[:160],
                    "context_contract_name": definition.context_contract_name[:160],
                    "reason": "context_missing_from_agent_run_request",
                }
            )
    if errors:
        raise AgentRunContextRegistryError(
            "agent_context_registry_invalid",
            "Video Agent operation context parity is invalid.",
            details={"invalid_definitions": errors[:16]},
        )

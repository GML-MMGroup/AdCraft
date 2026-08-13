"""Explicit structured contracts accepted from the private Pi runtime."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import get_args

from pydantic import BaseModel, ValidationError

from app.schemas.front_desk import FrontDeskIntentOutput
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCanvasScriptOutput,
    AgentCanvasTextOutput,
    AgentCommandPlanDraftV2,
    SpecialistDraft,
)
from app.schemas.agent_canvas_capabilities import (
    BgmProposalResultV1,
    CharacterProposalResultV1,
    CompactTurnIntentDecisionV3,
    NextActionCommandV1,
    ProductProposalResultV1,
    PropProposalResultV1,
    QuickMediaProposalResultV1,
    SceneProposalResultV1,
    ScriptProposalResultV1,
    StoryboardProposalResultV1,
    TurnIntentDecisionV2,
    VideoProposalResultV1,
    WorldSettingProposalResultV1,
)
from app.schemas.agent_canvas_decision_bundles import DecisionBundleDraftV1
from app.schemas.agent_canvas_materialization import (
    CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS,
)
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSegmentMaterializationDraftV2,
    StoryboardSequenceOutlineDraftV2,
)
from app.schemas.agent_canvas_video_parameters import VideoParameterIntentV2
from app.schemas.agent_capabilities import VideoAgentOperationDefinitionV1
from app.schemas.specialist_agents import SpecialistResult
from app.schemas.v2_agent_conversations import (
    ConversationSummaryResult,
    WorkflowConversationReply,
)
from app.schemas.v2_quick_media import V2QuickMediaPromptPlan
from app.schemas.workflow_v2_expert_brief_contracts import (
    V2BgmExpertPlan,
    V2CharacterExpertPlan,
    V2ExpertBriefPlannerOutput,
    V2ProductExpertPlan,
    V2SceneExpertPlan,
)
from app.schemas.workflow_v2_intent import V2IntentPlan
from app.schemas.workflow_v2_prompt_contracts import (
    V2BgmPromptPlan,
    V2CharacterMainPromptPlan,
    V2CharacterPromptPlan,
    V2CharacterThreeViewPromptPlan,
    V2ProductMainPromptPlan,
    V2ProductMultiViewPromptPlan,
    V2ProductPromptPlan,
    V2SceneMainPromptPlan,
    V2SceneMultiViewPromptPlan,
    V2ScenePromptPlan,
    V2ShotCellPromptPlan,
    V2ShotVideoPromptPlan,
)
from app.schemas.workflow_v2_screenplay import V2EditableScriptDocument, V2ScriptPlanV2
from app.schemas.workflow_v2_storyboard_detail import V2StoryboardDetailPlan
from app.schemas.workflow_v2_style import V2VisualStyleScopeRepairOutput


@dataclass(frozen=True, slots=True)
class AgentStructuredContractDefinition:
    """One immutable contract name and its exact Pydantic model."""

    contract_name: str
    model: type[BaseModel]


class AgentStructuredContractRegistryError(ValueError):
    """Stable fail-closed registry error raised before provider dispatch."""

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


_EXPLICIT_CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    SpecialistDraft,
    AgentActionEnvelopeV2,
    AgentCanvasScriptOutput,
    AgentCanvasTextOutput,
    AgentCommandPlanDraftV2,
    VideoParameterIntentV2,
    CompactTurnIntentDecisionV3,
    TurnIntentDecisionV2,
    NextActionCommandV1,
    DecisionBundleDraftV1,
    WorldSettingProposalResultV1,
    ProductProposalResultV1,
    PropProposalResultV1,
    CharacterProposalResultV1,
    SceneProposalResultV1,
    ScriptProposalResultV1,
    StoryboardProposalResultV1,
    VideoProposalResultV1,
    BgmProposalResultV1,
    QuickMediaProposalResultV1,
    SpecialistResult,
    FrontDeskIntentOutput,
    V2EditableScriptDocument,
    V2ExpertBriefPlannerOutput,
    V2ProductExpertPlan,
    V2CharacterExpertPlan,
    V2SceneExpertPlan,
    V2BgmExpertPlan,
    V2IntentPlan,
    V2ScriptPlanV2,
    V2StoryboardDetailPlan,
    V2VisualStyleScopeRepairOutput,
    ConversationSummaryResult,
    WorkflowConversationReply,
    StoryboardSequenceOutlineDraftV2,
    StoryboardSegmentMaterializationDraftV2,
    V2QuickMediaPromptPlan,
    V2ProductMainPromptPlan,
    V2ProductMultiViewPromptPlan,
    V2ProductPromptPlan,
    V2CharacterMainPromptPlan,
    V2CharacterThreeViewPromptPlan,
    V2CharacterPromptPlan,
    V2SceneMainPromptPlan,
    V2SceneMultiViewPromptPlan,
    V2ScenePromptPlan,
    V2ShotCellPromptPlan,
    V2ShotVideoPromptPlan,
    V2BgmPromptPlan,
    *CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS.values(),
)


class AgentStructuredContractRegistry:
    """Resolve the closed Python-owned structured contract allowlist."""

    def __init__(
        self,
        models: Iterable[type[BaseModel]] = _EXPLICIT_CONTRACT_MODELS,
    ) -> None:
        definitions = tuple(
            AgentStructuredContractDefinition(model.__name__, model) for model in models
        )
        by_name = {definition.contract_name: definition for definition in definitions}
        if len(by_name) != len(definitions):
            raise AgentStructuredContractRegistryError(
                "agent_contract_registry_invalid",
                "Agent structured contract names must be unique.",
            )
        self._definitions = definitions
        self._by_name = MappingProxyType(by_name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    def definitions(self) -> tuple[AgentStructuredContractDefinition, ...]:
        return self._definitions

    def resolve(self, contract_name: str) -> type[BaseModel]:
        try:
            return self._by_name[contract_name].model
        except KeyError as error:
            raise AgentStructuredContractRegistryError(
                "agent_contract_not_allowed",
                "Agent structured contract is not registered.",
                details={"contract_name": contract_name[:160]},
            ) from error

    def validate_operation_model(
        self,
        definition: VideoAgentOperationDefinitionV1,
        model: type[BaseModel],
    ) -> None:
        declared_model = self.resolve(definition.result_contract_name)
        compatible_models = _compatible_models(declared_model)
        if model not in compatible_models:
            raise AgentStructuredContractRegistryError(
                "agent_contract_registry_invalid",
                "Video Agent operation and structured contract model do not match.",
                details={
                    "operation": definition.operation[:160],
                    "declared_contract_name": definition.result_contract_name[:160],
                    "actual_contract_name": model.__name__[:160],
                },
            )


AGENT_STRUCTURED_CONTRACT_REGISTRY = AgentStructuredContractRegistry()


def validate_video_agent_contract_parity(
    definitions: Iterable[VideoAgentOperationDefinitionV1],
    registry: AgentStructuredContractRegistry = AGENT_STRUCTURED_CONTRACT_REGISTRY,
) -> None:
    """Fail when production operation metadata names an unknown contract."""

    errors: list[dict[str, str]] = []
    for definition in definitions:
        try:
            declared_model = registry.resolve(definition.result_contract_name)
        except AgentStructuredContractRegistryError:
            errors.append(
                {
                    "operation": definition.operation[:160],
                    "contract_name": definition.result_contract_name[:160],
                }
            )
            continue
        for model in (declared_model, *_compatible_models(declared_model)):
            try:
                registry.validate_operation_model(definition, model)
            except AgentStructuredContractRegistryError:
                errors.append(
                    {
                        "operation": definition.operation[:160],
                        "contract_name": definition.result_contract_name[:160],
                        "actual_contract_name": model.__name__[:160],
                    }
                )
    if errors:
        raise AgentStructuredContractRegistryError(
            "agent_contract_registry_invalid",
            "Video Agent operation contracts are not registered.",
            details={"invalid_definitions": errors[:16]},
        )


def _compatible_models(model: type[BaseModel]) -> tuple[type[BaseModel], ...]:
    if not getattr(model, "__pydantic_root_model__", False):
        return (model,)
    annotation = model.model_fields["root"].annotation
    compatible: list[type[BaseModel]] = [model]
    for item in get_args(annotation):
        if not isinstance(item, type) or not issubclass(item, BaseModel):
            continue
        if all(item is not existing for existing in compatible):
            compatible.append(item)
    return tuple(compatible)


def validate_agent_contract(contract_name: str, value: object) -> BaseModel:
    """Validate one registered Pi submission without dynamic imports."""

    model = AGENT_STRUCTURED_CONTRACT_REGISTRY.resolve(contract_name)
    if model is FrontDeskIntentOutput:
        return _validate_front_desk_contract(value)
    return model.model_validate(value)


def _validate_front_desk_contract(value: object) -> FrontDeskIntentOutput:
    try:
        return FrontDeskIntentOutput.model_validate(value)
    except ValidationError as error:
        if not isinstance(value, dict) or "v2_planning_seed" not in value:
            raise
        if not error.errors() or any(
            item.get("loc", ())[:1] != ("v2_planning_seed",) for item in error.errors()
        ):
            raise
        core_value = dict(value)
        core_value.pop("v2_planning_seed", None)
        return FrontDeskIntentOutput.model_validate(core_value)

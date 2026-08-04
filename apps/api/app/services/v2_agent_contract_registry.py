"""Allowlisted structured contracts accepted from the private Pi runtime."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from app.schemas.front_desk import FrontDeskIntentOutput
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCanvasScriptOutput,
    AgentCanvasTextOutput,
    AgentCommandPlanDraftV2,
    ConceptProposalDraftV2,
    SpecialistDraft,
)
from app.schemas.agent_canvas_creative_session import (
    CreationModeDecisionV2,
    DelegatedProposalChoiceV2,
    NextGuidanceDecisionV2,
    SpecialistDraftV2,
)
from app.schemas.specialist_agents import SpecialistResult
from app.schemas.workflow_v2_expert_brief_contracts import (
    V2BgmExpertPlan,
    V2CharacterExpertPlan,
    V2ExpertBriefPlannerOutput,
    V2ProductExpertPlan,
    V2SceneExpertPlan,
)
from app.schemas.workflow_v2_intent import V2IntentPlan
from app.schemas.workflow_v2_prompt_contracts import (
    V2CharacterMainPromptPlan,
    V2CharacterThreeViewPromptPlan,
    V2BgmPromptPlan,
    V2ProductMainPromptPlan,
    V2ProductMultiViewPromptPlan,
    V2SceneMainPromptPlan,
    V2SceneMultiViewPromptPlan,
    V2ShotCellPromptPlan,
    V2ShotVideoPromptPlan,
)
from app.schemas.workflow_v2_screenplay import V2EditableScriptDocument, V2ScriptPlanV2
from app.schemas.workflow_v2_storyboard_detail import V2StoryboardDetailPlan
from app.schemas.workflow_v2_style import V2VisualStyleScopeRepairOutput


_CONTRACTS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        SpecialistDraft,
        AgentActionEnvelopeV2,
        AgentCanvasScriptOutput,
        AgentCanvasTextOutput,
        AgentCommandPlanDraftV2,
        ConceptProposalDraftV2,
        SpecialistDraftV2,
        CreationModeDecisionV2,
        NextGuidanceDecisionV2,
        DelegatedProposalChoiceV2,
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
        V2ProductMainPromptPlan,
        V2ProductMultiViewPromptPlan,
        V2CharacterMainPromptPlan,
        V2CharacterThreeViewPromptPlan,
        V2SceneMainPromptPlan,
        V2SceneMultiViewPromptPlan,
        V2ShotCellPromptPlan,
        V2ShotVideoPromptPlan,
        V2BgmPromptPlan,
    )
}


def validate_agent_contract(contract_name: str, value: object) -> BaseModel:
    """Validate one registered Pi submission without dynamic imports."""

    model = _CONTRACTS.get(contract_name)
    if model is None:
        raise ValueError("Agent structured contract is not registered.")
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

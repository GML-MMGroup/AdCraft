"""Allowlisted structured contracts accepted from the private Pi runtime."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.front_desk import FrontDeskIntentOutput
from app.schemas.agent_runtime import SpecialistDraft
from app.schemas.specialist_agents import SpecialistResult
from app.schemas.workflow_v2_expert_brief_contracts import V2ExpertBriefPlannerOutput
from app.schemas.workflow_v2_intent import V2IntentPlan
from app.schemas.workflow_v2_prompt_contracts import (
    V2CharacterMainPromptPlan,
    V2CharacterThreeViewPromptPlan,
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
        SpecialistResult,
        FrontDeskIntentOutput,
        V2EditableScriptDocument,
        V2ExpertBriefPlannerOutput,
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
    )
}


def validate_agent_contract(contract_name: str, value: object) -> BaseModel:
    """Validate one registered Pi submission without dynamic imports."""

    model = _CONTRACTS.get(contract_name)
    if model is None:
        raise ValueError("Agent structured contract is not registered.")
    return model.model_validate(value)

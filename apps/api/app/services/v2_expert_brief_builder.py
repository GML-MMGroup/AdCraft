from __future__ import annotations

from app.core.config import Settings
from app.schemas.workflow_v2 import WorkflowV2PlanFromPromptRequest
from app.schemas.workflow_v2_planning import V2ExpertBriefPlan, V2ScriptPlan
from app.services.v2_expert_brief_planner import V2ExpertBriefPlanner


class V2ExpertBriefBuilder:
    """Compatibility wrapper around the production V2 expert brief planner."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._planner = V2ExpertBriefPlanner(settings or Settings(agno_mock_mode=True))

    def build(
        self,
        *,
        script_plan: V2ScriptPlan,
        request: WorkflowV2PlanFromPromptRequest,
    ) -> V2ExpertBriefPlan:
        return self._planner.plan_briefs(
            script_plan,
            request,
            workflow_id="v2_expert_brief_builder",
            input_asset_descriptors=[],
            force_mock=True,
        )

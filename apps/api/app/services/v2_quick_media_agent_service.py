"""Pi prompt planning for free media with Python-owned provider execution."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.v2_quick_media import V2QuickMediaPromptPlan
from app.schemas.workflow_v2 import WorkflowV2FreeNodeGenerateRequest
from app.services.v2_pi_agent_context import V2AgentContextBuilder
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)


class V2QuickMediaAgentError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class V2QuickMediaAgentService:
    def __init__(
        self,
        settings: Settings,
        *,
        runtime: StructuredGenerationRuntime | None = None,
        context_builder: V2AgentContextBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime or StructuredGenerationRuntime(settings=settings)
        self._context_builder = context_builder or V2AgentContextBuilder(settings)

    def plan(
        self,
        *,
        workflow_id: str,
        node_id: str,
        request: WorkflowV2FreeNodeGenerateRequest,
    ) -> V2QuickMediaPromptPlan:
        context = self._context_builder.build_quick_media(
            workflow_id=workflow_id,
            node_id=node_id,
            request=request,
        )
        if self._settings.agent_runtime_mode == "fake":
            return _fake_plan(context.output_media_type, context.user_input)
        operation = f"free_{context.output_media_type}"
        try:
            result = self._runtime.run(
                StructuredGenerationSpec(
                    stage_name="quick_media_prompt",
                    operation=operation,
                    agent_name="video_agent",
                    contract_name="V2QuickMediaPromptPlan",
                    model_id=self._settings.llm_creative_model,
                    system_prompt="",
                    input_payload=context.model_dump(mode="json"),
                    agent_context=context,
                    output_model=V2QuickMediaPromptPlan,
                    trace_metadata={
                        "workflow_id": workflow_id,
                        "node_id": node_id,
                    },
                    quality_validator=lambda plan: _validate_plan(
                        plan,
                        context.output_media_type,
                    ),
                )
            )
        except StructuredGenerationRuntimeError as exc:
            raise V2QuickMediaAgentError("quick_media_planning_failed", str(exc)) from exc
        return _validate_plan(result.output, context.output_media_type)


def _validate_plan(
    plan: V2QuickMediaPromptPlan,
    media_type: str,
) -> V2QuickMediaPromptPlan:
    if plan.output_media_type != media_type or plan.operation != f"free_{media_type}":
        raise V2QuickMediaAgentError(
            "quick_media_output_invalid",
            "Quick Media returned a prompt plan for the wrong media type.",
        )
    return plan


def _fake_plan(media_type: str, user_input: str) -> V2QuickMediaPromptPlan:
    return V2QuickMediaPromptPlan(
        output_media_type=media_type,
        summary_prompt=f"Standalone {media_type} concept: {user_input}",
        provider_prompt=(
            f"Create a polished standalone {media_type} asset. Creative direction: {user_input}"
        ),
        negative_prompt="watermark, unintended text, low quality",
        agent_name="video_agent",
        operation=f"free_{media_type}",
        quality_notes=["Deterministic Quick Media fake plan."],
    )

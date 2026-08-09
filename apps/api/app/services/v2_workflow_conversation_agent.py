"""Front Desk Pi operations for bounded workflow conversation and summaries."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.agent_operation_contexts import (
    ConversationSummaryAgentContext,
    WorkflowConversationAgentContext,
)
from app.schemas.v2_agent_conversations import (
    ConversationSummaryResult,
    WorkflowConversationReply,
)
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationRuntimeError,
    StructuredGenerationSpec,
)


class V2WorkflowConversationAgentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class V2WorkflowConversationAgent:
    def __init__(
        self,
        settings: Settings,
        *,
        runtime: StructuredGenerationRuntime | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime or StructuredGenerationRuntime(settings=settings)

    def reply(
        self,
        context: WorkflowConversationAgentContext,
    ) -> WorkflowConversationReply:
        if self._settings.agent_runtime_mode == "fake":
            return WorkflowConversationReply(
                message=(
                    "I can help refine this workflow. Choose one exact Character "
                    "or Scene target for a targeted revision."
                ),
                clarification_required=True,
            )
        return self._run(
            operation="workflow_conversation",
            contract_name="WorkflowConversationReply",
            context=context,
            output_model=WorkflowConversationReply,
        )

    def summarize(
        self,
        context: ConversationSummaryAgentContext,
    ) -> ConversationSummaryResult:
        if self._settings.agent_runtime_mode == "fake":
            visible = " ".join(message.content for message in context.recent_messages)
            return ConversationSummaryResult(
                summary=(visible or context.previous_summary or "No visible messages.")[:16_384]
            )
        return self._run(
            operation="conversation_summary",
            contract_name="ConversationSummaryResult",
            context=context,
            output_model=ConversationSummaryResult,
        )

    def _run(self, *, operation, contract_name, context, output_model):
        try:
            return self._runtime.run(
                StructuredGenerationSpec(
                    stage_name=operation,
                    operation=operation,
                    agent_name="video_agent",
                    contract_name=contract_name,
                    model_id=self._settings.llm_front_desk_model,
                    system_prompt="",
                    input_payload=context.model_dump(mode="json"),
                    agent_context=context,
                    output_model=output_model,
                    trace_metadata={
                        "workflow_id": context.workflow_id,
                        "conversation_id": context.conversation_id,
                    },
                )
            ).output
        except StructuredGenerationRuntimeError as error:
            raise V2WorkflowConversationAgentError(error.code, str(error)) from error

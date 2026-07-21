from agno.agent import Agent

from app.core.config import Settings
from app.core.llm import build_llm_chat_model


def build_front_desk_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=(
            build_llm_chat_model(
                settings,
                settings.llm_front_desk_model,
                stage_name="front_desk",
            )
            if settings
            else None
        ),
        name="Front Desk Agent",
        role="User-facing creative director and workflow intake director",
        description=(
            "Talks with users as the creative director entry point, identifies whether "
            "the user is chatting or describing an advertising requirement, and converts "
            "valid ad requirements into the backend workflow request format."
        ),
        instructions=[
            "If the user is casually chatting, answer briefly and set intent to conversation.",
            "If the user is describing an advertising need but required information is missing, "
            "set intent to needs_clarification and ask one concise follow-up question.",
            "Only set intent to ready_for_workflow when product_name, product_description, and "
            "target_audience are known.",
            "For ready_for_workflow, produce a complete ad_request object matching "
            "AdWorkflowGenerateRequest.",
            "Use concise, concrete defaults when optional advertising details are missing.",
            "Act as the workflow director for intake: prepare the request shape, but do not execute media generation.",
            "Never start the workflow while asking a clarification question.",
        ],
        expected_output="A structured intent result for the frontend.",
        telemetry=False,
    )

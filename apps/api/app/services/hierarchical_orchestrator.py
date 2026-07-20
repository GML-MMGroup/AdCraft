from typing import Any

from agno.agent import Agent

from app.services.agent_trace import AgentTraceWriter
from app.skills.registry import (
    CORE_AGENT_BY_NODE,
    augment_context_with_skills,
    record_mock_workflow_skill_trace,
    record_skill_trace,
)

MAIN_AGENT_BY_NODE = CORE_AGENT_BY_NODE


class HierarchicalAssistantExecutionError(ValueError):
    """Deprecated compatibility error; internal assistant Agents have been removed."""


def augment_context_with_assistants(
    *,
    node_id: str,
    main_agent: Agent,
    context: dict[str, Any],
    trace_writer: AgentTraceWriter,
    mock_mode: bool,
) -> dict[str, Any]:
    """Deprecated compatibility wrapper for older imports.

    The project now uses core Agents plus internal Skills. No nested Agent is created here.
    """
    return augment_context_with_skills(
        node_id=node_id,
        core_agent_name=CORE_AGENT_BY_NODE.get(node_id, main_agent.name or node_id),
        context=context,
        trace_writer=trace_writer,
        mock_mode=mock_mode,
    )


def record_mock_assistant_trace(
    *,
    node_id: str,
    main_agent_name: str,
    context: dict[str, Any],
    trace_writer: AgentTraceWriter,
) -> dict[str, dict[str, Any]]:
    """Deprecated compatibility wrapper for Skill trace recording."""
    return record_skill_trace(
        node_id=node_id,
        core_agent_name=CORE_AGENT_BY_NODE.get(node_id, main_agent_name),
        context=context,
        trace_writer=trace_writer,
        mock_mode=True,
    )


def record_mock_workflow_assistant_trace(
    *,
    request: Any,
    trace_writer: AgentTraceWriter,
    skip_audio_agents: bool,
) -> None:
    """Deprecated compatibility wrapper for workflow Skill traces."""
    record_mock_workflow_skill_trace(
        request=request,
        trace_writer=trace_writer,
        skip_audio_agents=skip_audio_agents,
    )

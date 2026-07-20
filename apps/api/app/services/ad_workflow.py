from dataclasses import replace

from app.core.config import Settings
from app.schemas.ad_workflow import AdWorkflowGenerateRequest, AdWorkflowResponse
from app.services.agent_trace import AgentTraceWriter, utc_now
from app.services.agno_orchestrator import AgentExecutionError, run_advertising_agents
from app.services.asset_library import AssetLibraryError
from app.teams.advertising import build_advertising_team
from app.tools.media import MediaConfigurationError, build_media_provider
from app.services.workflow_state import persist_workflow_response_as_node_runs
from app.skills.registry import record_mock_workflow_skill_trace
from app.workflows.ad_workflow import build_ad_workflow_graph, create_workflow_id


class WorkflowGenerationError(RuntimeError):
    """Raised when an ad workflow cannot be generated."""


class AdWorkflowService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: AdWorkflowGenerateRequest) -> AdWorkflowResponse:
        workflow_id = create_workflow_id()
        skip_audio_agents = self._settings.skip_audio_agents or request.skip_audio_agents
        effective_settings = replace(self._settings, skip_audio_agents=skip_audio_agents)
        trace_writer = AgentTraceWriter(effective_settings.media_data_dir, workflow_id)
        try:
            media_provider = build_media_provider(effective_settings)
            if effective_settings.agno_mock_mode:
                team = build_advertising_team()
                record_mock_workflow_skill_trace(
                    request=request,
                    trace_writer=trace_writer,
                    skip_audio_agents=skip_audio_agents,
                )
                agent_outputs = None
            else:
                team = build_advertising_team(effective_settings)
                agent_outputs = run_advertising_agents(
                    request,
                    team,
                    trace_writer,
                    skip_audio_agents=skip_audio_agents,
                )
            workflow = build_ad_workflow_graph(
                request,
                team,
                effective_settings.media_data_dir,
                workflow_id,
                media_provider,
                agent_outputs,
                skip_audio_agents=skip_audio_agents,
            )
            try:
                persist_workflow_response_as_node_runs(workflow, effective_settings)
            except Exception as exc:  # noqa: BLE001 - persistence must not discard workflow output.
                now = utc_now()
                trace_writer.append(
                    agent="Workflow State Persistence",
                    model=None,
                    prompt=workflow.model_dump_json(),
                    output=getattr(exc, "metadata", None),
                    error=str(exc),
                    started_at=now,
                    finished_at=now,
                    duration_ms=0,
                )
            return workflow
        except AssetLibraryError:
            raise
        except (AgentExecutionError, MediaConfigurationError, ValueError) as exc:
            trace_path = f"runs/{workflow_id}/trace.json"
            now = utc_now()
            trace_writer.append(
                agent="Media Workflow",
                model=None,
                prompt=request.model_dump_json(),
                output=getattr(exc, "metadata", None),
                error=str(exc),
                started_at=now,
                finished_at=now,
                duration_ms=0,
            )
            raise WorkflowGenerationError(
                f"Workflow {workflow_id} failed. Trace: {trace_path}. {exc}"
            ) from exc

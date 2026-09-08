from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas_capabilities import TurnIntentDecisionV2
from app.schemas.agent_canvas_creative_session import (
    CreativeGoalV2,
    GuidanceCompletionProjectionV2,
)
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_conversation import AgentConversationService
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.agent_canvas_requirements import AgentCanvasRequirementService


SAFE_FALLBACK_MESSAGE = (
    "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。"
)


class SafeFallbackGateway:
    """Model boundary already resolved to the trusted structured fallback."""

    def __init__(self) -> None:
        self.classify_calls = 0
        self.provider_dispatches = 0

    def classify_turn_intent(self, context, *, turn_id: str) -> TurnIntentDecisionV2:
        self.classify_calls += 1
        return TurnIntentDecisionV2(
            mode="ordinary_conversation",
            objective="Preserve a safe conversational response after structured validation failed.",
            assistant_message=SAFE_FALLBACK_MESSAGE,
        )

    def _provider_must_not_dispatch(self, *args, **kwargs):
        self.provider_dispatches += 1
        raise AssertionError("safe structured fallback must not dispatch a provider action")

    choose_next_action = _provider_must_not_dispatch
    author_decision_bundle = _provider_must_not_dispatch
    author_role_brief = _provider_must_not_dispatch
    plan_storyboard_sequence_outline = _provider_must_not_dispatch
    materialize_storyboard_segment = _provider_must_not_dispatch
    run_capability = _provider_must_not_dispatch
    run_materialization = _provider_must_not_dispatch


def _repositories(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    upgrade_v2_schema(database)
    events = EventRepository(database)
    workflows = AgentCanvasWorkflowRepository(database, ProjectRepository(database), events)
    timestamp = datetime.now(timezone.utc).isoformat()
    workflows.create_empty(
        project=ProjectCreate(
            project_id="project-fallback",
            name="Fallback regression",
            created_at=timestamp,
            updated_at=timestamp,
        ),
        workflow_id="workflow-fallback",
        idempotency_key="create-fallback",
        request_fingerprint="fallback-fingerprint",
    )
    conversations = AgentCanvasConversationRepository(database, events)
    return data_dir, database, events, workflows, conversations


def _service(workflows, conversations, gateway):
    requirements = AgentCanvasRequirementService(
        workflows.database,
        AgentCanvasRequirementRepository(workflows.database),
        EventRepository(workflows.database),
    )
    return AgentConversationService(
        workflows=workflows,
        conversations=conversations,
        nodes=AgentCanvasNodeService(workflows),
        gateway=gateway,
        requirements=requirements,
    )


def _snapshot(workflows, conversations, requirements):
    workflow = workflows.get_workflow("workflow-fallback")
    revision = requirements.get_current_revision("workflow-fallback")
    session = conversations.get_guidance_session_or_none("workflow-fallback")
    return {
        "workflow_revision": workflow.revision,
        "node_ids": tuple(node.node_id for node in workflow.nodes),
        "binding_ids": tuple(binding.binding_id for binding in workflow.bindings),
        "asset_ids": tuple(asset.asset_id for asset in workflow.assets),
        "requirements_revision_id": revision.revision_id,
        "requirements_revision_no": revision.revision_no,
        "requirements_digest": revision.digest,
        "guidance_revision": session.revision if session is not None else None,
    }


def test_safe_structured_fallback_persists_reply_without_workflow_side_effects(tmp_path):
    data_dir, database, events, workflows, conversations = _repositories(tmp_path)
    try:
        # Keep a real guidance revision in the baseline so a reload also verifies it.
        session = conversations.create_guidance_session(
            "workflow-fallback",
            goal=CreativeGoalV2(
                requested_output="video",
                delivery_scope="draft",
                summary="Existing guidance state",
            ),
            element_decisions=(),
            active_style_skill_run_id=None,
        )
        conversations.complete_guidance_session(
            session.session_id,
            expected_session_revision=session.revision,
            completion=GuidanceCompletionProjectionV2(),
        )
        requirements = AgentCanvasRequirementService(
            database,
            AgentCanvasRequirementRepository(database),
            events,
        )
        before = _snapshot(workflows, conversations, requirements)
        accepted = conversations.create_user_turn(
            "workflow-fallback",
            text="请继续处理这个广告请求",
            mentioned_node_ids=(),
            mentioned_image_asset_ids=(),
            video_skill_run_id=None,
            idempotency_key="fallback-turn",
        )
        gateway = SafeFallbackGateway()
        result = _service(workflows, conversations, gateway).process_turn(accepted.turn_id)

        assert result.status == "completed"
        assert gateway.classify_calls == 1
        assert gateway.provider_dispatches == 0
        assert _snapshot(workflows, conversations, requirements) == before
    finally:
        database.dispose()

    # Re-open the same SQLite file to prove the assistant reply is durable.
    reloaded = create_v2_database(data_dir)
    try:
        reloaded_events = EventRepository(reloaded)
        reloaded_workflows = AgentCanvasWorkflowRepository(
            reloaded, ProjectRepository(reloaded), reloaded_events
        )
        reloaded_conversations = AgentCanvasConversationRepository(reloaded, reloaded_events)
        reloaded_requirements = AgentCanvasRequirementService(
            reloaded,
            AgentCanvasRequirementRepository(reloaded),
            reloaded_events,
        )
        turn = reloaded_conversations.get_turn(accepted.turn_id)
        reloaded_gateway = SafeFallbackGateway()
        reloaded_service = AgentConversationService(
            workflows=reloaded_workflows,
            conversations=reloaded_conversations,
            nodes=AgentCanvasNodeService(reloaded_workflows),
            gateway=reloaded_gateway,
            requirements=reloaded_requirements,
        )
        replayed = reloaded_service.process_turn(accepted.turn_id)
        timeline = reloaded_service.get_timeline("workflow-fallback")
        assert turn.status == "completed"
        assert replayed.status == "completed"
        assert reloaded_gateway.classify_calls == 0
        assert reloaded_gateway.provider_dispatches == 0
        assert turn.request["text"] == "请继续处理这个广告请求"
        assert any(
            entry.speaker == "adcraft_video_agent" and entry.content == SAFE_FALLBACK_MESSAGE
            for entry in timeline.items
        )
        assert _snapshot(
            reloaded_workflows, reloaded_conversations, reloaded_requirements
        ) == before
    finally:
        reloaded.dispose()

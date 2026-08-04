"""Project creation and read-model orchestration for Agent Canvas V1."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.persistence.project_repository import ProjectRepository
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    ProjectCreateRequestV2,
    ProjectCreateResponseV2,
)
from app.schemas.workflow_v2_projects import (
    ProjectCatalogRecord,
    ProjectCreate,
    ProjectStatusV2,
    ProjectV2,
    ProjectV2ListResponse,
    ProjectV2Summary,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_video_skills import VideoSkillRegistry


class AgentCanvasProjectService:
    """Create empty projects and render Agent Canvas read models from SQLite."""

    def __init__(
        self,
        projects: ProjectRepository,
        workflows: AgentCanvasWorkflowRepository,
        assets: AgentCanvasAssetService,
        conversations: AgentCanvasConversationRepository,
        video_skills: VideoSkillRegistry,
    ) -> None:
        self._projects = projects
        self._workflows = workflows
        self._assets = assets
        self._conversations = conversations
        self._video_skills = video_skills

    def create(
        self,
        request: ProjectCreateRequestV2,
        *,
        idempotency_key: str,
    ) -> ProjectCreateResponseV2:
        fingerprint = hashlib.sha256(
            json.dumps(
                request.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        identity = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc).isoformat()
        initial_skill = self._video_skills.load("platform-default", "1")
        workflow = self._workflows.create_empty(
            project=ProjectCreate(
                project_id=f"proj_{identity}",
                name=request.name,
                description=request.description,
                created_at=now,
                updated_at=now,
            ),
            workflow_id=f"adwf_v2_{identity}",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        skill_run = self._conversations.get_active_style_skill_run(workflow.workflow_id)
        CreativeDirectionService().ensure_snapshot(
            self._conversations,
            skill_run,
            initial_skill,
        )
        return ProjectCreateResponseV2.model_validate(
            {
                **workflow.model_dump(),
                "active_style_skill_run_id": skill_run.skill_run_id,
                "guidance_session_id": None,
            }
        )

    def get_project(self, project_id: str) -> ProjectV2:
        return self._detail(self._projects.get_catalog(project_id))

    def list_projects(
        self,
        *,
        status: ProjectStatusV2,
        limit: int,
        cursor: str | None,
    ) -> ProjectV2ListResponse:
        page = self._projects.list_catalog(status=status, limit=limit, cursor=cursor)
        return ProjectV2ListResponse(
            items=tuple(self._summary(project) for project in page.items),
            next_cursor=page.next_cursor,
        )

    def update_project(
        self,
        project_id: str,
        *,
        expected_version: int,
        changes: dict[str, object],
    ) -> ProjectV2:
        self._projects.get_catalog(project_id)
        self._projects.update(
            project_id,
            expected_version=expected_version,
            changes=changes,
        )
        return self._detail(self._projects.get_catalog(project_id))

    def trash_project(self, project_id: str, *, expected_version: int) -> ProjectV2:
        self._projects.get_catalog(project_id)
        self._projects.trash(project_id, expected_version=expected_version)
        return self._detail(self._projects.get_catalog(project_id))

    def restore_project(self, project_id: str, *, expected_version: int) -> ProjectV2:
        self._projects.get_catalog(project_id)
        self._projects.restore(project_id, expected_version=expected_version)
        return self._detail(self._projects.get_catalog(project_id))

    def _summary(self, project: ProjectCatalogRecord) -> ProjectV2Summary:
        return ProjectV2Summary(
            **project.model_dump(exclude={"description", "created_at", "deleted_at"}),
        )

    def _detail(self, project: ProjectCatalogRecord) -> ProjectV2:
        workflow = self._workflows.get_workflow(project.workflow_id)
        return ProjectV2(
            project_id=project.project_id,
            workflow_id=workflow.workflow_id,
            name=project.name,
            description=project.description,
            status=project.status,
            is_favorite=project.is_favorite,
            cover_asset_id=project.cover_asset_id,
            project_version=project.project_version,
            semantic_revision_no=workflow.revision,
            created_at=project.created_at,
            updated_at=project.updated_at,
            deleted_at=project.deleted_at,
        )

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        workflow = self._workflows.get_workflow(workflow_id)
        asset_ids = {
            node.output_asset_id for node in workflow.nodes if node.output_asset_id is not None
        }
        asset_ids.update(
            binding.source.asset_id
            for binding in workflow.bindings
            if binding.source.kind == "image_asset"
        )
        assets = []
        for asset_id in sorted(asset_ids):
            try:
                assets.append(self._assets.resolve_asset(asset_id))
            except V2PersistenceError as error:
                if error.code != "asset_not_found":
                    raise
        return workflow.model_copy(update={"assets": tuple(assets)})

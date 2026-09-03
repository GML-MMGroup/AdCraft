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
    ActiveStyleSkillSummaryV2,
    AgentCanvasWorkflowV2,
    ProjectCreateRequestV2,
    ProjectCreateResponseV2,
)
from app.schemas.workflow_v2_projects import (
    ProjectCatalogRecord,
    ProjectCreate,
    ProjectCoverV2,
    ProjectStatusV2,
    ProjectV2,
    ProjectV2ListResponse,
    ProjectV2Summary,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.schemas.agent_canvas_conversation import VideoSkillRunCreateRequestV2
from app.schemas.v2_asset_library import AssetVersionMetadataV2
from app.services.agent_canvas_style_activation import StyleSkillActivationService


class AgentCanvasProjectService:
    """Create empty projects and render Agent Canvas read models from SQLite."""

    def __init__(
        self,
        projects: ProjectRepository,
        workflows: AgentCanvasWorkflowRepository,
        assets: AgentCanvasAssetService,
        conversations: AgentCanvasConversationRepository,
        style_activation: StyleSkillActivationService,
    ) -> None:
        self._projects = projects
        self._workflows = workflows
        self._assets = assets
        self._conversations = conversations
        self._style_activation = style_activation

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
        skill_run = self._style_activation.activate(
            workflow.workflow_id,
            VideoSkillRunCreateRequestV2(
                skill_id="platform-default",
                skill_version="1.0.0",
            ),
            idempotency_key=f"create-project:{idempotency_key}",
        )
        active_workflow = self.get_workflow(workflow.workflow_id)
        return ProjectCreateResponseV2.model_validate(
            {
                **active_workflow.model_dump(),
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
        cover_versions = self._assets.find_versions_by_id(
            tuple(
                project.cover_version_id
                for project in page.items
                if project.cover_state == "ready" and project.cover_version_id is not None
            )
        )
        return ProjectV2ListResponse(
            items=tuple(
                self._summary(project, cover_versions.get(project.cover_version_id or ""))
                for project in page.items
            ),
            next_cursor=page.next_cursor,
        )

    def update_project(
        self,
        project_id: str,
        *,
        expected_version: int,
        changes: dict[str, object],
    ) -> ProjectV2:
        project = self._projects.get_catalog(project_id)
        cover_asset_supplied = "cover_asset_id" in changes
        cover_version_supplied = "cover_version_id" in changes
        if cover_asset_supplied or cover_version_supplied:
            cover_asset_id = changes.get("cover_asset_id")
            cover_version_id = changes.get("cover_version_id")
            if cover_asset_id is None and cover_version_id is None:
                changes.update(
                    cover_asset_id=None,
                    cover_version_id=None,
                    cover_state="none",
                    cover_source="manual",
                    cover_updated_at=datetime.now(timezone.utc).isoformat(),
                )
            elif not isinstance(cover_asset_id, str) or not isinstance(cover_version_id, str):
                raise V2PersistenceError(
                    "project_cover_version_required",
                    "Project covers require exact asset and version identities.",
                    stage="agent_canvas_project_update",
                )
            else:
                cover = self._assets.resolve_target_asset_version(
                    project.workflow_id,
                    cover_asset_id,
                    cover_version_id,
                )
                if cover.media_type not in {"image", "video"}:
                    raise V2PersistenceError(
                        "project_cover_media_invalid",
                        "Project covers must be image or video assets.",
                        stage="agent_canvas_project_update",
                    )
                changes.update(
                    cover_state="ready",
                    cover_source="manual",
                    cover_updated_at=datetime.now(timezone.utc).isoformat(),
                )
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

    def _summary(
        self,
        project: ProjectCatalogRecord,
        cover_version: AssetVersionMetadataV2 | None = None,
    ) -> ProjectV2Summary:
        cover = None
        cover_state = project.cover_state
        if (
            project.cover_state == "ready"
            and cover_version is not None
            and cover_version.status == "ready"
            and cover_version.asset_id == project.cover_asset_id
            and cover_version.version_id == project.cover_version_id
            and cover_version.source_workflow_id == project.workflow_id
        ):
            media_type = _cover_media_type(cover_version.mime_type)
            if media_type in {"image", "video"}:
                cover = ProjectCoverV2(
                    asset_id=cover_version.asset_id,
                    version_id=cover_version.version_id,
                    media_type=media_type,
                    preview_url=(
                        f"/api/v2/assets/{cover_version.asset_id}/preview"
                        f"?v={cover_version.version_id}&size=320"
                    ),
                    poster_url=(
                        f"/api/v2/assets/{cover_version.asset_id}/poster"
                        f"?v={cover_version.version_id}&size=320"
                        if media_type == "video"
                        else None
                    ),
                )
        if project.cover_state == "ready" and cover is None:
            cover_state = "broken"
        return ProjectV2Summary(
            **project.model_dump(
                exclude={"description", "created_at", "deleted_at", "cover_state"}
            ),
            cover_state=cover_state,
            cover=cover,
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
            cover_version_id=project.cover_version_id,
            cover_state=project.cover_state,
            cover_source=project.cover_source,
            cover_updated_at=project.cover_updated_at,
            project_version=project.project_version,
            semantic_revision_no=workflow.revision,
            created_at=project.created_at,
            updated_at=project.updated_at,
            deleted_at=project.deleted_at,
        )

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        workflow = self._workflows.get_workflow(workflow_id)
        skill_run = self._conversations.get_active_style_skill_run(workflow_id)
        if (
            skill_run.active_creative_direction_snapshot_id is None
            or skill_run.public_skill is None
        ):
            raise V2PersistenceError(
                "style_skill_snapshot_invalid",
                "The active Style Skill snapshot is incomplete.",
                stage="agent_canvas_project_read",
            )
        public_skill = skill_run.public_skill
        active_style_skill = ActiveStyleSkillSummaryV2(
            skill_run_id=skill_run.skill_run_id,
            skill_id=skill_run.skill_id,
            skill_version=skill_run.skill_version,
            title=public_skill.title,
            summary=public_skill.summary,
            category=public_skill.category,
            creative_direction_snapshot_id=(skill_run.active_creative_direction_snapshot_id),
        )
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
        return workflow.model_copy(
            update={
                "assets": tuple(assets),
                "active_style_skill": active_style_skill,
            }
        )


def _cover_media_type(mime_type: str) -> str | None:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    return None

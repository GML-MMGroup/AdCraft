"""Atomic Video Style Skill activation orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas_conversation import (
    VideoSkillRunCreateRequestV2,
    VideoSkillRunV2,
)
from app.services.agent_canvas_creative_direction import CreativeDirectionService
from app.services.agent_canvas_video_skills import VideoSkillRegistry


class StyleSkillActivationService:
    """Verify, freeze, and atomically activate one Style Skill package."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        registry: VideoSkillRegistry,
        creative_direction: CreativeDirectionService | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._registry = registry
        self._creative_direction = creative_direction or CreativeDirectionService()

    def activate(
        self,
        workflow_id: str,
        request: VideoSkillRunCreateRequestV2,
        *,
        idempotency_key: str,
    ) -> VideoSkillRunV2:
        self._workflows.get_workflow(workflow_id)
        request_fingerprint = _activation_request_fingerprint(workflow_id, request)
        skill = self._registry.load(request.skill_id, request.skill_version)
        public_skill = self._registry.get_public_detail(request.skill_id)
        now = datetime.now(timezone.utc)
        skill_run_id = f"skill_run_{uuid4().hex}"
        snapshot = self._creative_direction.build_snapshot(
            workflow_id=workflow_id,
            skill_run_id=skill_run_id,
            skill=skill,
        )
        run = VideoSkillRunV2(
            skill_run_id=skill_run_id,
            workflow_id=workflow_id,
            skill_id=skill.manifest.skill_id,
            skill_version=skill.manifest.version,
            source_skill_run_id=request.source_skill_run_id,
            status="active",
            active_creative_direction_snapshot_id=snapshot.snapshot_id,
            public_skill=public_skill,
            created_at=now,
            updated_at=now,
        )
        return self._conversations.activate_style_skill(
            workflow_id=workflow_id,
            skill_run=run,
            snapshot=snapshot,
            public_skill=public_skill,
            request_fingerprint=request_fingerprint,
            idempotency_key=idempotency_key,
        )


def _activation_request_fingerprint(
    workflow_id: str,
    request: VideoSkillRunCreateRequestV2,
) -> str:
    payload = {
        "workflow_id": workflow_id,
        "request": request.model_dump(mode="json"),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"

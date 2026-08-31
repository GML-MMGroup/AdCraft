"""Deterministic frozen Style Guidance for Agent Canvas sessions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import VideoSkillRunV2
from app.schemas.agent_canvas_creative_session import (
    CreativeDirectionSnapshotV2,
    StyleGuidanceContextV2,
)
from app.services.agent_canvas_video_skills import LoadedVideoStyleSkillV2


_STYLE_PROJECTION_ROLES = {
    "world_setting",
    "script",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard",
    "video",
    "bgm",
    "quick_media",
}
_CONTEXT_BYTES = 8_192
_PRODUCT_IDENTITY_ROLES = {"product", "storyboard", "video"}


class CreativeDirectionService:
    """Freeze and resolve bounded Style Guidance without external calls."""

    def ensure_snapshot(
        self,
        repository: AgentCanvasConversationRepository,
        skill_run: VideoSkillRunV2,
        skill: LoadedVideoStyleSkillV2,
    ) -> CreativeDirectionSnapshotV2:
        try:
            existing = repository.get_active_creative_direction_snapshot(skill_run.workflow_id)
        except V2PersistenceError as error:
            if error.code != "creative_direction_snapshot_not_found":
                raise
        else:
            if existing.skill_run_id == skill_run.skill_run_id:
                return existing
        snapshot = self.build_snapshot(
            workflow_id=skill_run.workflow_id,
            skill_run_id=skill_run.skill_run_id,
            skill=skill,
        )
        try:
            return repository.create_creative_direction_snapshot(snapshot)
        except V2PersistenceError as error:
            if error.code != "creative_direction_version_conflict":
                raise
            return repository.get_active_creative_direction_snapshot(skill_run.workflow_id)

    def build_snapshot(
        self,
        *,
        workflow_id: str,
        skill_run_id: str,
        skill: LoadedVideoStyleSkillV2,
        version: int = 1,
    ) -> CreativeDirectionSnapshotV2:
        global_direction: dict[str, object] = {
            "global_guidance": skill.global_guidance,
            "public_skill": {
                "skill_id": skill.manifest.skill_id,
                "version": skill.manifest.version,
                "title": skill.manifest.display_name,
                "summary": skill.manifest.description,
                "category": skill.manifest.category,
                "tags": list(skill.manifest.tags),
                "supported_use_cases": list(skill.manifest.supported_use_cases),
                "preview": (
                    skill.manifest.preview.model_dump(mode="json")
                    if skill.manifest.preview is not None
                    else None
                ),
                "display_order": skill.manifest.display_order,
                "video_representation_mode": skill.manifest.video_representation_mode,
            },
            "package_digest": skill.package_digest,
        }
        role_projections = {
            role: {
                "text": guidance.text,
                "digest": guidance.digest,
            }
            for role, guidance in sorted(skill.role_guidance.items())
        }
        content = {
            "global_direction": global_direction,
            "role_projections": role_projections,
        }
        return CreativeDirectionSnapshotV2(
            snapshot_id=f"direction_{uuid4().hex}",
            workflow_id=workflow_id,
            skill_run_id=skill_run_id,
            version=version,
            source_skill_id=skill.manifest.skill_id,
            source_skill_version=skill.manifest.version,
            source_skill_digest=skill.package_digest,
            global_direction=global_direction,
            role_projections=role_projections,
            content_digest=_digest(content),
            created_at=datetime.now(timezone.utc),
        )

    def resolve_style_context(
        self,
        snapshot: CreativeDirectionSnapshotV2,
        role: str,
    ) -> StyleGuidanceContextV2:
        if role != "director" and role not in _STYLE_PROJECTION_ROLES:
            raise _error(
                "creative_direction_role_invalid",
                "Creative Direction role is not supported.",
            )
        global_guidance = str(snapshot.global_direction.get("global_guidance") or "")
        package_digest = str(
            snapshot.global_direction.get("package_digest") or snapshot.source_skill_digest or ""
        )
        if not global_guidance or not package_digest:
            raise _error(
                "style_skill_snapshot_invalid",
                "Creative Direction snapshot is incomplete.",
            )
        projection = snapshot.role_projections.get(role) if role != "director" else None
        role_guidance = str(projection.get("text") or "") if projection else None
        if not role_guidance:
            role_guidance = None
        total_bytes = len(global_guidance.encode("utf-8")) + len(
            (role_guidance or "").encode("utf-8")
        )
        if total_bytes > _CONTEXT_BYTES:
            raise _error(
                "style_skill_context_budget_exceeded",
                "Style Guidance context exceeds its byte budget.",
            )
        public_skill = snapshot.global_direction.get("public_skill")
        skill_metadata = public_skill if isinstance(public_skill, dict) else {}
        mode = skill_metadata.get("video_representation_mode", "illustrated")
        if mode not in {"illustrated", "illustration_to_live_action"}:
            raise _error(
                "style_skill_snapshot_invalid",
                "Creative Direction snapshot contains an invalid Video representation mode.",
            )
        return StyleGuidanceContextV2(
            skill_run_id=snapshot.skill_run_id,
            skill_id=snapshot.source_skill_id or "",
            skill_version=snapshot.source_skill_version or "",
            package_digest=package_digest,
            creative_direction_snapshot_id=snapshot.snapshot_id,
            global_guidance=global_guidance,
            role=None if role == "director" else role,
            role_guidance=role_guidance,
            role_guidance_digest=(
                (str(projection.get("digest") or "") or None) if projection else None
            ),
            video_representation_mode=mode,
            video_representation_source_id=(
                f"{snapshot.source_skill_id}:{snapshot.source_skill_version}"
            ),
        )

    def validate_role_projection(
        self,
        role: str,
        projection: Mapping[str, object],
        *,
        prohibited_phrases: tuple[str, ...] = (),
    ) -> None:
        if role not in _STYLE_PROJECTION_ROLES:
            raise _error(
                "creative_direction_role_invalid",
                "Creative Direction role is not supported.",
            )
        if role not in _PRODUCT_IDENTITY_ROLES and projection.get("product_identity"):
            raise _error(
                "creative_direction_role_scope_invalid",
                "Product identity is not allowed in this Creative Direction projection.",
            )
        serialized = json.dumps(projection, sort_keys=True, default=str)
        if any(_contains_phrase(serialized, phrase) for phrase in prohibited_phrases):
            raise _error(
                "creative_direction_role_scope_invalid",
                "Creative Direction projection contains a prohibited semantic phrase.",
            )


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _contains_phrase(value: str, phrase: str) -> bool:
    normalized = phrase.strip().casefold()
    if not normalized:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(normalized)}(?![A-Za-z0-9_])")
    return pattern.search(value.casefold()) is not None


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="creative_direction")

"""Deterministic Creative Direction snapshots for Agent Canvas sessions."""

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
from app.schemas.agent_canvas_creative_session import CreativeDirectionSnapshotV2
from app.services.agent_canvas_video_skills import LoadedVideoSkillV2


_ROLES = (
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
    "quick_media_agent",
)
_PRODUCT_IDENTITY_ROLES = {
    "product_designer",
    "storyboard_artist",
    "video_director",
}


class CreativeDirectionService:
    """Create bounded role projections without invoking an Agent or provider."""

    def ensure_snapshot(
        self,
        repository: AgentCanvasConversationRepository,
        skill_run: VideoSkillRunV2,
        skill: LoadedVideoSkillV2,
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
            skill_id=skill.manifest.skill_id,
            skill_version=skill.manifest.version,
            skill_digest=skill.package_digest,
            visual_language=skill.manifest.description,
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
        skill_id: str,
        skill_version: str,
        skill_digest: str,
        visual_language: str,
        product_identity: str | None = None,
        version: int = 1,
    ) -> CreativeDirectionSnapshotV2:
        normalized_style = visual_language.strip()
        if not normalized_style:
            raise _error(
                "creative_direction_invalid",
                "Creative Direction requires visual language.",
            )
        global_direction: dict[str, object] = {
            "visual_language": normalized_style,
        }
        if product_identity and product_identity.strip():
            global_direction["product_identity"] = product_identity.strip()
        role_projections = {
            role: self._role_projection(
                role,
                rendering_style=normalized_style,
                product_identity=product_identity,
            )
            for role in _ROLES
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
            source_skill_id=skill_id,
            source_skill_version=skill_version,
            source_skill_digest=skill_digest,
            global_direction=global_direction,
            role_projections=role_projections,
            content_digest=_digest(content),
            created_at=datetime.now(timezone.utc),
        )

    def validate_role_projection(
        self,
        role: str,
        projection: Mapping[str, object],
        *,
        prohibited_phrases: tuple[str, ...] = (),
    ) -> None:
        if role not in _ROLES:
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

    def _role_projection(
        self,
        role: str,
        *,
        rendering_style: str,
        product_identity: str | None,
    ) -> dict[str, object]:
        projection: dict[str, object] = {"rendering_style": rendering_style}
        if role in _PRODUCT_IDENTITY_ROLES and product_identity and product_identity.strip():
            projection["product_identity"] = product_identity.strip()
        self.validate_role_projection(role, projection)
        return projection


def _contains_phrase(value: str, phrase: str) -> bool:
    normalized = phrase.strip().casefold()
    if not normalized:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(normalized)}(?![A-Za-z0-9_])")
    return pattern.search(value.casefold()) is not None


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="creative_direction")

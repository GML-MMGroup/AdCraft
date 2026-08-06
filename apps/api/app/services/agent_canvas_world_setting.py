"""Deterministic World Setting proposal adaptation and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Mapping
from uuid import uuid4

from pydantic import ValidationError

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, CanvasPositionV2
from app.schemas.agent_canvas_conversation import (
    ConceptOptionRecordV2,
    ConceptProposalCreateV2,
    ConceptProposalV2,
)
from app.schemas.agent_canvas_creative_session import ConceptDraftSpecV2
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV1,
    WorldSettingDocumentV1,
    WorldSettingDirectionV1,
    WorldSettingProjectionSnapshotV1,
    WorldSettingProposalDraftV1,
    WorldSettingReadyProjectionBundleV1,
    WorldSettingProjectionAudienceV1,
)


WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE: dict[str, WorldSettingProjectionAudienceV1] = {
    "script": "script_writer",
    "product": "product_designer",
    "prop": "prop_designer",
    "character": "character_designer",
    "scene": "scene_designer",
    "storyboard_sequence": "storyboard_artist",
    "storyboard_video": "video_director",
    "bgm": "bgm_director",
    "creative_brief": "shared",
    "general_text": "shared",
    "general_image": "shared",
    "general_video": "shared",
    "general_audio": "shared",
}


class WorldSettingBindingPolicy:
    """Derive trusted projection routing from the target creative role."""

    def audience_for_role(self, creative_role: str) -> WorldSettingProjectionAudienceV1:
        audience = WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE.get(creative_role)
        if audience is None:
            raise V2PersistenceError(
                "world_setting_target_unsupported",
                "Target Node role does not support World Setting context.",
                stage="world_setting_binding_policy",
            )
        return audience

    def metadata_for_target(
        self,
        creative_role: str,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            **dict(metadata or {}),
            "context_kind": "world_setting",
            "projection_audience": self.audience_for_role(creative_role),
            "projection_contract_version": "world-setting-projection-v1",
        }


@dataclass(frozen=True, slots=True)
class WorldSettingPublicationCandidateV1:
    node: CanvasNodeV2
    projection: WorldSettingProjectionSnapshotV1
    materialization_run_id: str


def render_world_setting_direction(direction: WorldSettingDirectionV1) -> str:
    """Render one validated direction without interpreting its prose."""

    rules = "\n".join(f"- {item}" for item in direction.world_rules)
    continuity = "\n".join(f"- {item}" for item in direction.visual_continuity)
    return (
        f"Title: {direction.title}\n"
        f"Premise: {direction.premise}\n"
        f"Era and place: {direction.era_and_place}\n"
        f"World rules:\n{rules}\n"
        f"Visual continuity:\n{continuity}\n"
        f"User summary: {direction.user_summary}"
    )


def world_setting_proposal_from_draft(
    draft: WorldSettingProposalDraftV1,
    *,
    topic_id: str,
) -> ConceptProposalCreateV2:
    """Adapt strict Pi output to the durable generic Proposal contract."""

    return ConceptProposalCreateV2(
        proposal_kind="world_setting",
        specialist_name="scene_designer",
        topic_id=topic_id,
        options=tuple(
            ConceptOptionRecordV2(
                option_id=item.option_id,
                title=item.title,
                summary_prompt=item.user_summary,
                draft_spec=ConceptDraftSpecV2(
                    prompt=render_world_setting_direction(item),
                ),
            )
            for item in draft.options
        ),
    )


def build_world_setting_publication_candidate(
    proposal: ConceptProposalV2,
    option: ConceptOptionRecordV2,
    *,
    title: str,
    document_content: str,
    projection: WorldSettingReadyProjectionBundleV1,
    materialization_run_id: str,
    audit: Mapping[str, object],
    model_ref: str,
    now: datetime,
) -> WorldSettingPublicationCandidateV1:
    """Validate and assemble publication state before opening a transaction."""

    try:
        prompt_digest = _audit_digest(audit, "prompt_digest")
        skill_digest = _audit_digest(audit, "skill_digest")
        document = WorldSettingDocumentV1(
            content=document_content,
            authoring_provenance=WorldSettingAuthoringProvenanceV1(
                source_proposal_id=proposal.proposal_id,
                source_option_id=option.option_id,
                materialization_run_id=materialization_run_id,
                style_skill_run_id=proposal.video_skill_run_id,
                creative_direction_snapshot_id=proposal.creative_direction_snapshot_id,
            ),
        )
        node = CanvasNodeV2(
            node_id=f"node_{uuid4().hex}",
            workflow_id=proposal.workflow_id,
            node_type="text",
            creative_role="world_setting",
            title=title,
            status="ready",
            summary_prompt=option.summary_prompt,
            generation_prompt=None,
            structured_content=document.model_dump(mode="json"),
            parameters={},
            position=CanvasPositionV2(x=0, y=0),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        source_digest = _digest(document.content)
        projection_payload = projection.model_dump(mode="json")
        compiler_digest = _digest(
            json.dumps(
                {
                    "contract_version": projection.contract_version,
                    "model_ref": model_ref,
                    "prompt_digest": prompt_digest,
                    "skill_digest": skill_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        snapshot = WorldSettingProjectionSnapshotV1(
            projection_snapshot_id=f"world_projection_{uuid4().hex}",
            workflow_id=proposal.workflow_id,
            source_node_id=node.node_id,
            source_node_revision=node.revision,
            source_content_digest=source_digest,
            projection_contract_version=projection.contract_version,
            projection_prompt_digest=prompt_digest,
            projection_skill_digest=skill_digest,
            model_ref=model_ref,
            compiler_digest=compiler_digest,
            projection_mode="ready",
            shared_projection=projection.shared,
            role_projections=(
                projection.script_writer,
                projection.product_designer,
                projection.prop_designer,
                projection.character_designer,
                projection.scene_designer,
                projection.storyboard_artist,
                projection.video_director,
                projection.bgm_director,
            ),
            projection_digest=_digest(
                json.dumps(projection_payload, sort_keys=True, separators=(",", ":"))
            ),
            created_at=now,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise V2PersistenceError(
            "world_setting_materialization_invalid",
            "World Setting materialization did not satisfy the publication contract.",
            stage="world_setting_publication",
        ) from error
    return WorldSettingPublicationCandidateV1(
        node=node,
        projection=snapshot,
        materialization_run_id=materialization_run_id,
    )


def _audit_digest(audit: Mapping[str, object], key: str) -> str:
    value = str(audit.get(key) or "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"World Setting audit field {key} is not a SHA-256 digest.")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

"""Deterministic World Setting proposal adaptation and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    WorldSettingAuthoringProvenanceV2,
    WorldSettingContextAudienceV2,
    WorldSettingCoreV2,
    WorldSettingDocumentV2,
    WorldSettingDirectionV1,
    WorldSettingProposalDraftV1,
)


WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE: dict[str, WorldSettingContextAudienceV2] = {
    "script": "script_writer",
    "product": "product_designer",
    "prop": "prop_designer",
    "character": "character_designer",
    "scene": "scene_designer",
    "storyboard_sequence": "storyboard_artist",
    "storyboard_video": "video_director",
    "bgm": "bgm_director",
}


class WorldSettingBindingPolicy:
    """Derive trusted context routing from the target creative role."""

    def audience_for_role(self, creative_role: str) -> WorldSettingContextAudienceV2:
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
        supplied = {
            key: value
            for key, value in dict(metadata or {}).items()
            if key
            not in {
                "projection_audience",
                "projection_contract_version",
                "projection_snapshot_id",
            }
        }
        return {
            **supplied,
            "context_kind": "world_setting",
            "semantic_reference_role": "world_setting_reference",
            "target_audience": self.audience_for_role(creative_role),
            "context_contract_version": "world-setting-context-v2",
        }


@dataclass(frozen=True, slots=True)
class WorldSettingPublicationCandidateV2:
    node: CanvasNodeV2
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
                    world_setting_core=WorldSettingCoreV2(
                        premise=item.premise,
                        era_and_place=item.era_and_place,
                        world_rules=item.world_rules,
                        visual_continuity=item.visual_continuity,
                    ).model_dump(mode="json"),
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
    materialization_run_id: str,
    now: datetime,
) -> WorldSettingPublicationCandidateV2:
    """Validate and assemble publication state before opening a transaction."""

    try:
        persisted_option = next(
            (item for item in proposal.options if item.option_id == option.option_id),
            None,
        )
        if persisted_option is None or persisted_option != option:
            raise ValueError("The selected option does not belong to the frozen Proposal.")
        if option.draft_spec is None or option.draft_spec.world_setting_core is None:
            raise ValueError("The selected World Setting option has no frozen core.")
        document = WorldSettingDocumentV2(
            content=document_content,
            core=WorldSettingCoreV2.model_validate(option.draft_spec.world_setting_core),
            authoring_provenance=WorldSettingAuthoringProvenanceV2(
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
    except (TypeError, ValueError, ValidationError) as error:
        raise V2PersistenceError(
            "world_setting_materialization_invalid",
            "World Setting materialization did not satisfy the publication contract.",
            stage="world_setting_publication",
        ) from error
    return WorldSettingPublicationCandidateV2(
        node=node,
        materialization_run_id=materialization_run_id,
    )
